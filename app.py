# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.7
# Consumer-weighted scoring + strict rebuilt handling + full disclaimer
# Gemini 2.5 Pro | Sheets (optional) | Mandatory Live Web Reasoning
# ===========================================================

import os, json, re, hashlib, time
from datetime import datetime
import streamlit as st
from json_repair import repair_json

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# Google Generative AI (Gemini)
import google.generativeai as genai

# -------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------
st.set_page_config(page_title="AI Deal Checker (v9.9.7)", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.7")
st.caption("Consumer-weighted scoring with strict rebuilt/salvage handling and mandatory disclaimer (Gemini 2.5 Pro).")

API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
LOCAL_FILE = "deal_history_us.json"

if not API_KEY:
    st.error("Missing GEMINI_API_KEY in Streamlit secrets.")
    st.stop()

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.5-pro")

# ---------------- Sheets -----------------
sheet = None
if SHEET_ID and SERVICE_JSON and gspread and Credentials:
    try:
        if isinstance(SERVICE_JSON, str):
            SERVICE_JSON = json.loads(SERVICE_JSON)
        creds = Credentials.from_service_account_info(
            SERVICE_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        sheet = gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception as e:
        st.warning(f"⚠️ Sheets connection failed: {e}")

# -------------------------------------------------------------
# STYLE
# -------------------------------------------------------------
st.markdown("""
<style>
:root { --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --muted:#6b7280; }
.metric { display:flex; align-items:center; justify-content:space-between; margin:6px 0; font-size:0.95rem; }
.progress { height:10px; background:#e5e7eb; border-radius:6px; overflow:hidden; }
.fill-ok{background:var(--ok);height:100%;}
.fill-warn{background:var(--warn);height:100%;}
.fill-bad{background:var(--bad);height:100%;}
small.muted{color:var(--muted);}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------
def meter(label, value, suffix=""):
    try:
        v = float(value)
    except:
        v = 0
    v = max(0, min(100, v))
    css = 'fill-ok' if v >= 70 else ('fill-warn' if v >= 40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b><span>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{v}%'></div></div>", unsafe_allow_html=True)

def clip(x, lo, hi):
    try:
        x = float(x)
    except:
        x = 0.0
    return max(lo, min(hi, x))

def extract_price_from_text(txt:str):
    if not txt: return None
    t = re.sub(r'\s+', ' ', txt)
    m = re.search(r'(?i)(?:\\$?\\s*)(\\d{1,3}(?:,\\d{3})+|\\d{4,6})(?:\\s*usd)?', t)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except:
            return None
    return None

def parse_json_safe(raw:str):
    raw = (raw or "").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except:
        return json.loads(repair_json(raw))

def unique_ad_id(ad_text, vin, zip_or_state, price_guess, seller):
    base = (vin.strip().upper() if vin else f"{ad_text[:160]}|{price_guess}|{zip_or_state}|{seller}".lower())
    return hashlib.md5(base.encode()).hexdigest()[:12]

def classify_deal(score: float) -> str:
    if score >= 80:
        return "✅ Good deal — price and condition align well with market value."
    if score >= 60:
        return "⚖️ Fair deal — acceptable, but verify title and history before proceeding."
    return "❌ Bad deal — overpriced or carries significant risk factors."

# -------------------------------------------------------------
# PROMPT
# -------------------------------------------------------------
def build_prompt(ad, extra, must_id, exact_prev, similar_summ):
    exact_json = json.dumps(exact_prev or {}, ensure_ascii=False)
    similar_json = json.dumps(similar_summ or [], ensure_ascii=False)
    return f"""
You are a senior US used-car analyst (2023–2025). Web reasoning is REQUIRED.

Scoring logic:
- Title condition (clean > rebuilt > salvage): 20% weight; rebuilt/salvage cap deal_score ≤ 75.
- Market gap (vs clean comps): 25%.
- Mileage: 12%.
- Reliability + maintenance: 18%.
- TCO (fuel + insurance): 7%.
- Accidents + owners: 10%.
- Rust/flood zone: 4%.
- Demand/resale: 4%.
If price gap ≤ -35%, warn to verify insurance history.

Return strict JSON with readable component notes and plain-English summary.
"""

# -------------------------------------------------------------
# UI
# -------------------------------------------------------------
ad = st.text_area("Paste the listing text:", height=230)
imgs = st.file_uploader("Upload photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
vin = st.text_input("VIN (optional)")
zip_code = st.text_input("ZIP / State (e.g., 44105 or OH)")
seller = st.selectbox("Seller type", ["","private","dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad.strip():
        st.error("Please paste listing text first.")
        st.stop()

    parts=[{"text": build_prompt(ad, "", "id", {}, [])}]
    for img in imgs or []:
        mime="image/png" if "png" in img.type.lower() else "image/jpeg"
        parts.append({"mime_type": mime, "data": img.read()})

    with st.spinner("Analyzing with Gemini 2.5 Pro…"):
        try:
            r=model.generate_content(parts,request_options={"timeout":180})
            data=parse_json_safe(r.text)
        except Exception as e:
            st.error(f"Model error: {e}")
            st.stop()

    score=clip(data.get("deal_score",60),0,100)
    facts=data.get("vehicle_facts",{}) or {}
    title=str(facts.get("title_status","")).lower()
    roi=data.get("roi_forecast_24m",{}) or {}
    gap=data.get("market_refs",{}).get("gap_pct",-1)
    color="#16a34a" if score>=80 else ("#f59e0b" if score>=60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
    st.info(classify_deal(score))

    # --- New Disclaimer block ---
    st.markdown("""
    <div style='border:1px solid #f59e0b; border-radius:8px; padding:12px; background-color:#fff7ed; color:#92400e; font-size:0.9rem;'>
    <strong>Disclaimer:</strong> This analysis is for informational purposes only.  
    It does not constitute professional advice or a purchase recommendation.  
    Always have the vehicle inspected by a certified mechanic and verify its insurance and accident history before any transaction.
    </div>
    """, unsafe_allow_html=True)

    # Warnings
    if title in {"rebuilt","salvage","branded"}:
        st.error("⚠️ Rebuilt / Branded Title detected — resale value and insurability may be limited.")
    if gap is not None and float(gap) <= -35:
        st.warning("⚠️ Price significantly below market — verify accident or insurance history.")

    st.subheader("ROI Forecast (24 months)")
    st.write(f"Expected {roi.get('expected',0)}% | Optimistic {roi.get('optimistic',0)}% | Pessimistic {roi.get('pessimistic',0)}%")
    st.subheader("Explanation")
    st.write(data.get("score_explanation","No detailed reasoning provided."))
    comps=data.get("components",[]) or []
    if comps:
        st.subheader("Component breakdown")
        for c in comps:
            st.write(f"• **{c.get('name','').capitalize()}** — {int(clip(c.get('score',0),0,100))}/100 → {c.get('note','')}")
    st.markdown("<hr>", unsafe_allow_html=True)
    st.caption("⚠️ Disclaimer: This report is not professional advice. Always perform a full mechanical inspection and insurance history check before purchase.")
