# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) - v9.3.2 Full Visual & Textual Build
# Gemini 2.5 Pro | Text + Image Reasoning | Live Cross-Validation
# ===========================================================

import os, re, json, time, io
from datetime import datetime
import pandas as pd
import streamlit as st
from PIL import Image
from json_repair import repair_json
import google.generativeai as genai

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# ---------------------- App Setup --------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) v9.3.2", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.3.2")
st.caption("AI-powered used-car deal analysis with live web & visual cross-validation (Gemini 2.5 Pro).")

# ---------------------- CSS --------------------------
st.markdown("""
<style>  
:root { --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --muted:#6b7280; }  
div.block-container { padding-top: 1rem; }  
.metric { display:flex; align-items:center; justify-content:space-between; margin:6px 0 4px; font-size:0.95rem; }  
.metric b { color:#111827; }  
.progress { height:10px; background:#e5e7eb; border-radius:6px; overflow:hidden; }  
.fill-ok   { height:100%; background:var(--ok);   transition:width .5s; }  
.fill-warn { height:100%; background:var(--warn); transition:width .5s; }  
.fill-bad  { height:100%; background:var(--bad);  transition:width .5s; }  
.pill { display:inline-flex; align-items:center; gap:.35rem; padding:.3rem .6rem; border-radius:999px; font-weight:600; margin-right:.35rem; font-size:0.9rem;}  
.pill.ok { background:#ecfdf5; color:#065f46; }  
.pill.warn { background:#fffbeb; color:#92400e; }  
.pill.bad { background:#fef2f2; color:#991b1b; }  
small.muted { color: var(--muted); }  
</style>  
""", unsafe_allow_html=True)

# ---------------------- Secrets / Config -------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-pro")

# ---------------------- Google Sheets ----------------------
sheet = None
if SHEET_ID and SERVICE_JSON and gspread and Credentials:
    try:
        if isinstance(SERVICE_JSON, str):
            SERVICE_JSON = json.loads(SERVICE_JSON)
        creds = Credentials.from_service_account_info(
            SERVICE_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception as e:
        st.warning(f"⚠️ Google Sheets connection failed: {e}")

# ---------------------- Save to Sheet ----------------------
def save_to_sheet(entry):
    if not sheet:
        return
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fa = entry.get("from_ad", {}) or {}
        row = [
            ts,
            fa.get("brand",""),
            fa.get("model",""),
            fa.get("year",""),
            fa.get("price_usd",""),
            fa.get("mileage_mi",""),
            entry.get("deal_score",""),
            entry.get("classification",""),
            entry.get("risk_level",""),
            entry.get("roi_estimate_24m",""),
            entry.get("seller_trust_index",""),
            entry.get("reliability_score_web",""),
            entry.get("regional_demand_index",""),
            entry.get("confidence_level",""),
            entry.get("depreciation_two_year_pct",""),
            entry.get("insurance_cost_band",""),
            entry.get("climate_suitability",""),
            entry.get("web_search_performed",""),
            entry.get("reasoning",""),
            entry.get("short_verdict","")
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        st.toast("✅ Saved to Google Sheets")
    except Exception:
        pass

# ---------------------- Prompt -----------------------------
STRICT_SCHEMA_EXAMPLE = """{
"from_ad":{"brand":"Toyota","model":"Camry","year":2020,"price_usd":18900},
"benchmarks":{"fair_price_range_usd":[18000,20000],"visual_condition":"Good"},
"deal_score":87,
"classification":"Great Deal",
"reasoning":"Price 8% below fair range, clean title, excellent visual condition, low mileage, high reliability score, projected ROI 7.2% over 24 months.",
"risk_level":"Low",
"roi_estimate_24m":7.2,
"seller_trust_index":80,
"confidence_level":0.95,
"web_search_performed":true
}"""

def build_prompt(ad: str, extra: str):
    return f"""
You are an AI automotive analyst specializing in used-car evaluation.

TASK:
Perform a full multimodal (text + image) analysis of the car listing below.

Cross-validate using up-to-date 2023–2025 U.S. market data (Edmunds, KBB, IIHS, Cars.com, RepairPal).
Do NOT cite sources directly.

INSTRUCTIONS:
1. Analyze both the **text description** and the **uploaded photos**.
2. From photos, estimate:
   - Exterior condition (scratches, dents, paint quality)
   - Tire wear and interior cleanliness
   - Signs of rust, flood damage, or repaint
   - Whether it looks dealer-prepped or private-sale used
3. From text, evaluate:
   - Price vs. fair market range
   - Mileage and ownership history
   - Title type (clean, rebuilt, salvage)
   - Brand reliability, maintenance trend, ROI outlook
4. Combine image + text insights into a unified reasoning paragraph.
   Example: “Price 8% below KBB fair value, one-owner clean title, tires look new, exterior well-kept, strong ROI outlook (+7% over 2y).”
5. Output JSON only, exactly in this structure:
{STRICT_SCHEMA_EXAMPLE}

Make the reasoning quantitative, detailed, and natural-language readable.

INPUT (Ad):
\"\"\"{ad}\"\"\"{extra}

Return JSON only.
""".strip()

# ---------------------- JSON Parser ------------------------
def parse_json_strict(raw: str):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty model response")
    raw = raw.replace("```json","").replace("```","").strip()
    ob, cb = raw.count("{"), raw.count("}")
    if cb < ob:
        raw += "}" * (ob - cb)
    try:
        return json.loads(raw)
    except Exception:
        fixed = repair_json(raw)
        return json.loads(fixed)

# ---------------------- UI Helpers -------------------------
def meter(label, value, suffix=""):
    try:
        v = float(value)
    except Exception:
        v = 0.0
    v = max(0.0, min(100.0, v))
    css = 'fill-ok' if v >= 70 else ('fill-warn' if v >= 40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b> <span>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{int(v)}%'></div></div>", unsafe_allow_html=True)

def pill(label, level):
    lvl = (level or "").strip().lower()
    cls = 'ok' if lvl in ('good','low','high') else ('warn' if lvl in ('avg','moderate','medium') else 'bad')
    st.markdown(f"<span class='pill {cls}'>{label}</span>", unsafe_allow_html=True)

# ---------------------- Main UI -------------------------------
ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Paste the Craigslist / FB Marketplace / Cars.com ad…")
images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1,c2,c3 = st.columns(3)
with c1: vin = st.text_input("VIN (optional)")
with c2: zipc = st.text_input("ZIP (optional)")
with c3: seller = st.selectbox("Seller type", ["","private","dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    extra = ""
    if vin: extra += f"\nVIN: {vin}"
    if zipc: extra += f"\nZIP: {zipc}"
    if seller: extra += f"\nSeller type: {seller}"

    # Build multimodal input parts
    parts = [{"text": build_prompt(ad_text, extra)}]
    if images:
        for img in images:
            image_bytes = img.read()
            parts.append({"mime_type": "image/jpeg", "data": image_bytes})

    with st.spinner("Analyzing with Gemini 2.5 Pro (visual + textual cross-validation)…"):
        data, last_err = None, None
        for attempt in range(3):
            try:
                resp = model.generate_content(parts, request_options={"timeout": 120})
                data = parse_json_strict(resp.text)
                break
            except Exception as e:
                last_err = str(e)
                st.warning(f"Attempt {attempt+1} failed to produce valid JSON. Retrying…")
                time.sleep(1.0)
        if data is None:
            st.error(f"❌ Failed after 3 attempts. Last error: {last_err}")
            st.stop()

    save_to_sheet(data)

    # ---- Output ----
    st.divider()
    score = int(data.get("deal_score", 0))
    color = "#16a34a" if score >= 80 else ("#f59e0b" if score >= 60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)

    st.subheader("🧭 Why this score?")
    st.write(data.get("reasoning", "No reasoning provided."))

    conf = float(data.get("confidence_level", 0) or 0) * 100
    meter("Confidence", conf, "%")

    if data.get("web_search_performed"):
        st.success("🔎 Live web & visual cross-validation performed.")
        if data.get("cross_validation_result"):
            st.caption(data["cross_validation_result"])
    else:
        st.warning("⚠️ No live web search detected — AI relied on internal knowledge.")

    st.subheader("Summary")
    st.write(data.get("classification", ""))
    st.write(data.get("short_verdict", ""))

    fa = data.get("from_ad", {}) or {}
    st.subheader("Listing Details")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')}**")
    st.write(f"**Price:** ${fa.get('price_usd',0):,} | **Miles:** {fa.get('mileage_mi',0):,}")
    st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'} | **ZIP:** {fa.get('zip','') or 'n/a'} | **VIN:** {fa.get('vin','') or 'n/a'}")

    st.subheader("Risk & Context")
    pill(f"Risk: {data.get('risk_level','')}", data.get("risk_level"))
    pill(f"Insurance: {data.get('insurance_cost_band','')}", data.get("insurance_cost_band"))
    pill(f"Climate: {data.get('climate_suitability','')}", data.get("climate_suitability"))

    st.caption("© 2025 AI Deal Checker - U.S. Edition (Pro) v9.3.2. AI opinion only; verify independently.")