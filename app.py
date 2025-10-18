# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v2 Stable Build
# • Handles truncated JSON gracefully
# • Confidence bar + color scoring
# • Gemini 2.5 Flash + JSON-repair fallback
# ===========================================================

import os, re, json, traceback
from datetime import datetime
import streamlit as st
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from json_repair import repair_json

# ---------------------- App Config -------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.)", page_icon="🚗", layout="centered")

st.markdown("""
<style>
:root { --ink:#0f172a; --muted:#64748b; --accent:#2563eb; }
h1,h2,h3,h4 { color:var(--ink); font-weight:700; }
small,.muted{ color:var(--muted); }
div.block-container { padding-top:1rem; }
.progress-bar { height:12px; background:#e5e7eb; border-radius:6px; overflow:hidden; }
.progress-bar-fill { height:100%; background:#16a34a; transition:width 0.6s; }
</style>
""", unsafe_allow_html=True)

# ---------------------- Secrets ----------------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
LOCAL_FILE = "data_history_us.json"

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ---------------------- Google Sheets ----------------------
sheet = None
if SERVICE_ACCOUNT_JSON and SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception:
        st.toast("⚠️ Google Sheets unavailable, fallback to local file.")
else:
    st.toast("ℹ️ Using local storage (no Sheets connection).")

# ---------------------- Persistence ------------------------
def load_history():
    if sheet:
        try:
            rows = sheet.get_all_records()
            out = []
            for r in rows:
                if "data_json" in r and r["data_json"]:
                    try:
                        out.append(json.loads(r["data_json"]))
                    except Exception:
                        pass
            return out
        except Exception:
            pass
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry):
    try:
        if sheet:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {})
            flat = [
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                fa.get("mileage_mi",""), fa.get("price_usd",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("confidence_level",""),
                entry.get("short_verdict","")
            ]
            sheet.append_row(flat, value_input_option="USER_ENTERED")
        else:
            data = load_history()
            data.append(entry)
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Save failed: {e}")

def get_model_avg_us(brand, model):
    hist = load_history()
    scores = [
        h.get("deal_score") for h in hist
        if isinstance(h.get("deal_score"), (int,float))
        and h.get("from_ad", {}).get("brand","").lower()==brand.lower()
        and model.lower() in h.get("from_ad", {}).get("model","").lower()
    ]
    return round(sum(scores)/len(scores),2) if scores else None

def check_consistency_us(brand, model):
    hist = load_history()
    rel = [
        h.get("deal_score") for h in hist
        if isinstance(h.get("deal_score"), (int,float))
        and h.get("from_ad", {}).get("brand","").lower()==brand.lower()
        and model.lower() in h.get("from_ad", {}).get("model","").lower()
    ]
    if len(rel) >= 3 and (max(rel)-min(rel) >= 20):
        return True, rel
    return False, rel

def guess_brand_model(text):
    if not text: return "", ""
    head = text.splitlines()[0].strip()
    toks = [t for t in re.split(r"[^\w\-]+", head) if t]
    if len(toks)>=2:
        return toks[0], " ".join(toks[1:3])
    return "", ""

# ---------------------- Prompt -----------------------------
def build_us_prompt(ad: str, extra: str) -> str:
    return f"""
You are a U.S. used-car deal checker. Analyze if the following ad is a smart buy for a U.S. consumer.

If you cannot find enough data, fill with reasonable approximations.
You MUST return valid JSON only — no markdown, no explanation outside the JSON.

Ad text:
\"\"\"{ad}\"\"\"{extra}

--- SCORING TABLE (apply cumulatively, capped ±40) ---
| Condition | Adjustment | Notes |
|------------|-------------|-------|
| Salvage/Rebuilt title | −35 | High risk |
| Prior rental/fleet | −8 | Unless strong records |
| Missing VIN | −5 | Transparency issue |
| Price < −30% vs fair | −15 | Possible branded title |
| Dealer “As-Is” | −10 | Higher legal exposure |
| Rust Belt ZIP (MI/OH/NY/PA/WI/MN/IL) | −7 | Corrosion risk |
| Sun Belt ZIP (AZ/NV/FL/TX/CA) | −4 | UV/interior wear |
| EV battery high miles/no warranty | −10 | Degradation risk |
| Missing CarFax mention | −3 | Transparency |
| High-trim verified | +10 | Justified premium |
| “One owner” + clean title + records | +7 | Verified low risk |

--- SCORING WEIGHTS ---
Price vs fair – 30%
Condition/history – 25%
Reliability – 20%
Mileage vs year – 15%
Transparency/title – 10%
Then apply edge-case adjustments above.

--- OUTPUT JSON ONLY ---
{{
  "from_ad": {{
    "brand":"", "model":"", "year":0, "trim":"", "engine":"", "transmission":"", "drivetrain":"",
    "mileage_mi":0, "price_usd":0, "vin":"", "zip":"", "seller_type":""
  }},
  "benchmarks": {{
    "fair_price_range_usd":[0,0],
    "reliability_band":"", "known_issues":[], "demand_class":"", "safety_context":""
  }},
  "deal_score": 0,
  "classification": "",
  "risk_level": "",
  "price_delta_vs_fair": 0.0,
  "otd_estimate_usd": 0,
  "tco_24m_estimate_usd": {{ "fuel_energy":0, "insurance":"low/avg/high", "maintenance":0 }},
  "short_verdict": "",
  "key_reasons": [],
  "confidence_level": 0.0
}}
Return valid JSON only.
"""

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition")
st.caption("AI-powered used-car deal analysis for American listings (USD / miles).")

st.info("This tool provides an AI-based opinion only. Always verify with CarFax/AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220)
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
vin_input = st.text_input("VIN (optional)")
zip_input = st.text_input("ZIP (optional)")
seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

if st.button("Check the Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    g_brand, g_model = guess_brand_model(ad_text)
    consistency_alert, prev_scores = check_consistency_us(g_brand, g_model)

    extra = ""
    if vin_input: extra += f"\nVIN: {vin_input}"
    if zip_input: extra += f"\nZIP: {zip_input}"
    if seller_type: extra += f"\nSeller type: {seller_type}"
    if consistency_alert:
        extra += f"\nHistorical note: prior scores for {g_brand} {g_model}: {prev_scores}"

    prompt = build_us_prompt(ad_text, extra)
    inputs = [prompt]
    for img in uploaded_images or []:
        try: inputs.append(Image.open(img))
        except Exception: pass

    with st.spinner("Analyzing the deal..."):
        try:
            resp = model.generate_content(inputs, request_options={"timeout": 120})
            raw = (resp.text or "").strip()

            if not raw:
                raise ValueError("Empty response from Gemini – no content returned.")

            # --- Auto-fix for truncated JSON ---
            if not raw.endswith("}"):
                raw += "}" * (raw.count("{") - raw.count("}"))
            if not raw.endswith("]") and raw.count("[") > raw.count("]"):
                raw += "]"

            try:
                fixed = repair_json(raw)
                data = json.loads(fixed)
            except Exception:
                st.warning("⚠️ Gemini returned partial JSON — trying recovery.")
                last_brace = raw.rfind("}")
                if last_brace != -1:
                    raw_cut = raw[: last_brace + 1]
                    try:
                        data = json.loads(raw_cut)
                        st.success("✅ JSON repaired successfully (auto-recovered).")
                    except Exception:
                        st.error("❌ Could not recover JSON.")
                        st.code(raw[:1000])
                        raise ValueError("Invalid JSON output from Gemini")
                else:
                    st.error("❌ Could not detect JSON braces.")
                    st.code(raw[:1000])
                    raise ValueError("Invalid JSON output from Gemini")

            avg = get_model_avg_us(data.get("from_ad",{}).get("brand",""), data.get("from_ad",{}).get("model",""))
            if isinstance(avg,(int,float)) and isinstance(data.get("deal_score"),(int,float)):
                diff = data["deal_score"] - avg
                if abs(diff)>=15:
                    data["deal_score"] = int(data["deal_score"] - diff*0.5)
                    data["short_verdict"] += f" ⚙️ Stabilized vs mean ({avg})."

            save_to_history(data)

            # --------- UI Output ----------
            st.divider()
            score = int(data.get("deal_score",0))
            conf = float(data.get("confidence_level",0))
            color = "#16a34a" if score>=80 else "#f59e0b" if score>=60 else "#dc2626"
            st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center;'>Confidence: {int(conf*100)}%</p>", unsafe_allow_html=True)
            st.markdown(f"<div class='progress-bar'><div class='progress-bar-fill' style='width:{int(conf*100)}%;'></div></div>", unsafe_allow_html=True)

            st.subheader("Summary")
            st.write(data.get("short_verdict",""))
            st.subheader("Key reasons")
            for r in data.get("key_reasons", []):
                st.write(f"- {r}")

            st.subheader("Benchmarks")
            bm = data.get("benchmarks",{})
            st.json(bm, expanded=False)

            st.caption("© 2025 AI Deal Checker — U.S. Edition • Powered by Gemini 2.5 Flash")

        except Exception:
            st.error("❌ Error processing data.")
            st.code(traceback.format_exc())