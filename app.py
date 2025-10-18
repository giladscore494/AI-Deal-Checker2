# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v5 (Gemini 2.5 Pro + Retry JSON enforcement)
# ===========================================================

import os, re, json, traceback, time
from datetime import datetime
import streamlit as st
import google.generativeai as genai
from PIL import Image
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
if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
MODEL_NAME = "gemini-2.5-pro"
model = genai.GenerativeModel(MODEL_NAME)

# ---------------------- Prompt ----------------------------
def build_us_prompt(ad, extra):
    return f"""
You are an expert automotive analyst for U.S. used-car listings.
Your ONLY job: return **one complete, valid JSON object** — no markdown, no prose.

If the model output is incomplete or truncated, you MUST re-output the full JSON again.

Ad text:
\"\"\"{ad}\"\"\"{extra}

--- REQUIRED OUTPUT FORMAT ---
{{
  "from_ad": {{
    "brand": "Toyota",
    "model": "Camry",
    "year": 2020,
    "trim": "SE",
    "engine": "2.5L I4",
    "transmission": "Automatic",
    "drivetrain": "FWD",
    "mileage_mi": 48000,
    "price_usd": 18900,
    "vin": "unknown",
    "zip": "94110",
    "seller_type": "private"
  }},
  "benchmarks": {{
    "fair_price_range_usd": [18000,20000],
    "reliability_band": "High",
    "known_issues": [],
    "demand_class": "High",
    "safety_context": "IIHS Top Safety Pick"
  }},
  "deal_score": 87,
  "classification": "Great Deal",
  "risk_level": "Low",
  "price_delta_vs_fair": -0.05,
  "otd_estimate_usd": 19900,
  "tco_24m_estimate_usd": {{
    "fuel_energy": 2600,
    "insurance": "avg",
    "maintenance": 900
  }},
  "short_verdict": "Excellent value, reliable powertrain, priced below market.",
  "key_reasons": [
    "Below-market pricing",
    "Clean title, one owner",
    "High reliability rating"
  ],
  "confidence_level": 0.96
}}

If you cannot infer a field, set `"unknown"` or `0`, but KEEP ALL KEYS.
ALWAYS ensure valid JSON with matching brackets.
Output only the JSON — no explanations, no markdown fences.
"""

# ---------------------- Helper ----------------------------
def try_parse_json(raw):
    """Attempt to clean and parse JSON from Gemini output."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    open_braces, close_braces = raw.count("{"), raw.count("}")
    if close_braces < open_braces:
        raw += "}" * (open_braces - close_braces)
    open_brackets, close_brackets = raw.count("["), raw.count("]")
    if close_brackets < open_brackets:
        raw += "]" * (open_brackets - close_brackets)

    try:
        return json.loads(raw)
    except Exception:
        last = max(raw.rfind("}"), raw.rfind("]"))
        if last > 0:
            try:
                return json.loads(raw[:last+1])
            except Exception:
                fixed = repair_json(raw[:last+1])
                return json.loads(fixed)
        raise ValueError("Invalid JSON")

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

    with st.spinner("Analyzing with Gemini 2.5 Pro (JSON strict mode)..."):
        attempt = 0
        data = None
        error_msg = None

        while attempt < 3 and data is None:
            attempt += 1
            try:
                resp = model.generate_content(inputs, request_options={"timeout":90})
                raw = (resp.text or "").strip()
                data = try_parse_json(raw)
            except Exception as e:
                error_msg = str(e)
                time.sleep(1.5)
                st.warning(f"Attempt {attempt} failed — retrying JSON generation...")
                inputs[0] = build_us_prompt(ad_text, extra)  # reinforce structure

        if data is None:
            st.error(f"❌ Failed after 3 attempts. Last error: {error_msg}")
            st.stop()

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

        st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro) • Gemini 2.5 Pro strict JSON mode")