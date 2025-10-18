# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v4 (Gemini 2.5 Pro + strict JSON demo)
# • Forces valid JSON structure with live example
# • Stable recovery for any malformed output
# ===========================================================

import os, re, json, traceback
from datetime import datetime
import streamlit as st
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from json_repair import repair_json

# ---------------------- Config ----------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.)", page_icon="🚗", layout="centered")

st.markdown("""
<style>
.progress-bar {height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;}
.progress-bar-fill {height:100%;background:#16a34a;transition:width 0.6s;}
</style>
""", unsafe_allow_html=True)

# ---------------------- Secrets ---------------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
LOCAL_FILE = "data_history_us.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

# ---------- Gemini 2.5 Pro (enforced) ----------
MODEL_NAME = "gemini-2.5-pro"
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(MODEL_NAME)

# ---------------------- Sheets ----------------------------
sheet = None
try:
    if SERVICE_ACCOUNT_JSON and SHEET_ID:
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    else:
        st.toast("ℹ️ Using local storage only.")
except Exception:
    st.toast("⚠️ Google Sheets unavailable.")

# ---------------------- Helpers ---------------------------
def load_history():
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry):
    data = load_history()
    data.append(entry)
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def guess_brand_model(txt):
    if not txt: return "",""
    parts = re.split(r"[^\w\-]+", txt.splitlines()[0])
    if len(parts)>=2: return parts[0], " ".join(parts[1:3])
    return "",""

# ---------------------- Prompt ----------------------------
def build_us_prompt(ad, extra):
    return f"""
You are an automotive analyst. Evaluate the following *U.S.* used-car listing.
Your task: produce a **single, valid JSON object only** — no markdown, no text outside the JSON.

⚠️ **DO NOT return explanations or prose. Only JSON.**
If information is missing, fill with `"unknown"` or `0` but keep all keys.

Ad text:
\"\"\"{ad}\"\"\"{extra}

--- REQUIRED OUTPUT FORMAT (imitate exactly this structure) ---
Example:
{{
  "from_ad": {{
    "brand": "Honda",
    "model": "Civic",
    "year": 2020,
    "trim": "EX",
    "engine": "2.0L I4",
    "transmission": "CVT",
    "drivetrain": "FWD",
    "mileage_mi": 48000,
    "price_usd": 18500,
    "vin": "unknown",
    "zip": "94110",
    "seller_type": "private"
  }},
  "benchmarks": {{
    "fair_price_range_usd": [17500,19500],
    "reliability_band": "High",
    "known_issues": [],
    "demand_class": "High",
    "safety_context": "IIHS Top Safety Pick"
  }},
  "deal_score": 82,
  "classification": "Great Deal",
  "risk_level": "Low",
  "price_delta_vs_fair": -0.07,
  "otd_estimate_usd": 19900,
  "tco_24m_estimate_usd": {{
    "fuel_energy": 2600,
    "insurance": "avg",
    "maintenance": 900
  }},
  "short_verdict": "Excellent condition, below-market price, one-owner history.",
  "key_reasons": [
    "Below market by ~7%",
    "Clean title and records",
    "Reliable powertrain"
  ],
  "confidence_level": 0.96
}}

Follow this schema exactly.

--- SCORING TABLE (apply cumulatively, capped ±40) ---
| Condition | Adj. | Notes |
|------------|------|-------|
| Salvage title | −35 | High risk |
| Fleet/Rental | −8 | Unless records |
| Missing VIN | −5 | Transparency issue |
| Price < −30% vs fair | −15 | Possible branded title |
| Dealer “As-Is” | −10 | Legal exposure |
| Rust Belt ZIP | −7 | Corrosion |
| Sun Belt ZIP | −4 | UV/interior wear |
| EV battery > 80k mi no warranty | −10 |
| Missing CarFax | −3 |
| High-trim verified | +10 |
| “One owner” + clean title | +7 |

Return only the final JSON.
"""

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro)")
st.caption("AI-powered used-car deal analysis for American listings (USD / miles).")

st.info("This AI opinion is informational only — verify with CarFax / AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220)
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
vin_input = st.text_input("VIN (optional)")
zip_input = st.text_input("ZIP (optional)")
seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

if st.button("Check the Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    extra = ""
    if vin_input: extra += f"\nVIN: {vin_input}"
    if zip_input: extra += f"\nZIP: {zip_input}"
    if seller_type: extra += f"\nSeller type: {seller_type}"

    prompt = build_us_prompt(ad_text, extra)
    inputs = [prompt]
    for img in uploaded_images or []:
        try: inputs.append(Image.open(img))
        except Exception: pass

    with st.spinner("Analyzing the deal with Gemini 2.5 Pro…"):
        try:
            resp = model.generate_content(inputs, request_options={"timeout":120})
            raw = (resp.text or "").strip()

            if not raw:
                raise ValueError("Empty response from Gemini Pro.")

            # --- Smart JSON Recovery ---
            if not raw.endswith("}"):
                raw += "}" * (raw.count("{") - raw.count("}"))
            if not raw.endswith("]") and raw.count("[")>raw.count("]"):
                raw += "]"

            try:
                fixed = repair_json(raw)
                data = json.loads(fixed)
            except Exception:
                st.warning("⚠️ Partial JSON – attempting recovery.")
                last = max(raw.rfind("}"), raw.rfind("]"))
                if last>0:
                    try:
                        data = json.loads(raw[:last+1])
                        st.success("✅ Recovered trimmed JSON.")
                    except Exception:
                        fixed2 = repair_json(raw[:last+1])
                        data = json.loads(fixed2)
                        st.success("✅ Recovered via deep repair.")
                else:
                    st.error("❌ Invalid JSON – showing preview.")
                    st.code(raw[:1000])
                    data = {"deal_score":0,"short_verdict":"⚠️ Gemini output invalid."}

            save_to_history(data)

            # ---------- Display ----------
            score = int(data.get("deal_score",0))
            conf = float(data.get("confidence_level",0))
            color = "#16a34a" if score>=80 else "#f59e0b" if score>=60 else "#dc2626"
            st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center;'>Confidence: {int(conf*100)}%</p>", unsafe_allow_html=True)
            st.markdown(f"<div class='progress-bar'><div class='progress-bar-fill' style='width:{int(conf*100)}%;'></div></div>", unsafe_allow_html=True)

            st.subheader("Summary")
            st.write(data.get("short_verdict",""))
            st.subheader("Key Reasons")
            for r in data.get("key_reasons", []):
                st.write(f"- {r}")

            st.subheader("Benchmarks")
            st.json(data.get("benchmarks", {}), expanded=False)

            st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro) • Gemini 2.5 Pro")

        except Exception:
            st.error("❌ Error processing data.")
            st.code(traceback.format_exc())