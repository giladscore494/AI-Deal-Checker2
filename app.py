# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) - v9.3.3 Full Cross-Validation Build
# Gemini 2.5 Pro | Text + Image | Rust-Belt Risk + Climate + Insurance
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
st.set_page_config(page_title="AI Deal Checker (U.S.) v9.3.3", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.3.3")
st.caption("AI-powered used-car deal analysis with visual + web cross-validation (Gemini 2.5 Pro).")

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

# ---------------------- Rust-Belt Risk Helper ----------------------
RUST_BELT_STATES = ["OH","MI","PA","IL","NY","WI","MN"]

def rust_belt_risk(zip_code:str=""):
    """Estimate corrosion risk based on region (Rust Belt heuristic)."""
    if not zip_code:
        return 0
    zip_prefix = str(zip_code)[:3]
    # simulate region-based risk weight
    for state in RUST_BELT_STATES:
        if state.lower() in zip_code.lower():
            return 10
    try:
        z = int(zip_prefix)
        if 430 <= z <= 499:  # Midwest + Great Lakes zones
            return 10
        if 500 <= z <= 599:  # Northern plains
            return 6
    except Exception:
        pass
    return 0

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
"reasoning":"Price 8% below market, clean title, good visual condition, no rust signs, average insurance cost, suitable for warm climates, ROI +7% in 24 months.",
"risk_level":"Low",
"insurance_cost_band":"avg",
"climate_suitability":"Good",
"roi_estimate_24m":7.2,
"seller_trust_index":80,
"confidence_level":0.95,
"web_search_performed":true
}"""

def build_prompt(ad: str, extra: str):
    return f"""
You are an expert automotive analyst for the U.S. used-car market.

OBJECTIVE:
Analyze the vehicle listing below (text + photos). Return a detailed JSON result only.

TASKS:
1. Evaluate price vs. 2023–2025 fair market range (Edmunds, KBB, Cars.com, RepairPal — internal data only).
2. Evaluate reliability, ROI, maintenance trend, and resale outlook.
3. Evaluate **visual cues** from uploaded photos:
   - Exterior condition (scratches, dents, repaint)
   - Interior cleanliness and seat condition
   - Tire wear, rust traces, headlight oxidation
   - General presentation (dealer-prepped vs. private sale)
4. Evaluate regional risk (rust/corrosion) based on ZIP/state (Rust Belt = OH, MI, PA, IL, NY, WI, MN).
5. Estimate **insurance_cost_band** ("low"/"avg"/"high") and **climate_suitability** ("Good"/"Moderate"/"Poor").
6. Write a clear "reasoning" paragraph explaining all factors quantitatively (e.g., "Price 9% below market, minor scratches, Midwest region rust risk -5 pts, strong reliability +ROI offset").
7. Return JSON only, exactly like this:
{STRICT_SCHEMA_EXAMPLE}

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
with c2: zipc = st.text_input("ZIP or State (e.g., 44105 or OH)")
with c3: seller = st.selectbox("Seller type", ["","private","dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    extra = ""
    if vin: extra += f"\nVIN: {vin}"
    if zipc: extra += f"\nZIP or State: {zipc}"
    if seller: extra += f"\nSeller type: {seller}"

    rust_penalty = rust_belt_risk(zipc)
    if rust_penalty:
        extra += f"\n⚠️ Note: region is part of Rust Belt — apply corrosion risk factor ({rust_penalty} pts)."

    # Build multimodal parts
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
    else:
        st.warning("⚠️ No live web search detected — AI relied on internal knowledge.")

    st.subheader("Summary")
    st.write(data.get("classification", ""))
    st.write(data.get("short_verdict", ""))

    fa = data.get("from_ad", {}) or {}
    st.subheader("Listing Details")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')}**")
    st.write(f"**Price:** ${fa.get('price_usd',0):,} | **Miles:** {fa.get('mileage_mi',0):,}")
    st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'} | **ZIP/State:** {fa.get('zip','') or zipc or 'n/a'} | **VIN:** {fa.get('vin','') or 'n/a'}")

    st.subheader("Risk & Context")
    pill(f"Risk: {data.get('risk_level','')}", data.get("risk_level"))
    pill(f"Insurance: {data.get('insurance_cost_band','')}", data.get("insurance_cost_band"))
    pill(f"Climate: {data.get('climate_suitability','')}", data.get("climate_suitability"))

    if rust_penalty:
        st.markdown(f"<small class='muted'>Rust-belt penalty applied: −{rust_penalty} points due to regional corrosion risk.</small>", unsafe_allow_html=True)

    st.caption("© 2025 AI Deal Checker - U.S. Edition (Pro) v9.3.3. AI opinion only; verify independently.")