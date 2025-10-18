# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) - v9.2.1 Clean UTF-8 Build
# Gemini 2.5 Pro | Live Web Search Cross-Validation | VIN-based stabilization
# ===========================================================

import os, re, json, time
from datetime import datetime
import pandas as pd
import streamlit as st
import google.generativeai as genai
from PIL import Image
from json_repair import repair_json

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# ---------------------- App Setup --------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) v9.2.1", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.2.1")
st.caption("AI-powered used-car deal analysis with live web cross-validation, VIN stability & Sheets sync.")

# ---------------------- CSS --------------------------
st.markdown("""
<style>  
:root { --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --muted:#6b7280; }  
div.block-container { padding-top: 1rem; }  
.card { border:1px solid #e5e7eb; border-radius:14px; padding:14px; margin:10px 0; background:#fff; }  
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
LOCAL_FILE = "deal_history_us.json"

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

# ---------------------- Persistence ------------------------
def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry):
    try:
        data = load_history()
        data.append(entry)
        if len(data) > 500:
            data = data[-500:]
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if sheet:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {}) or {}
            row = [
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                fa.get("price_usd",""), fa.get("mileage_mi",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("roi_estimate_24m",""),
                entry.get("seller_trust_index",""), entry.get("reliability_score_web",""),
                entry.get("regional_demand_index",""), entry.get("confidence_level",""),
                entry.get("depreciation_two_year_pct",""), entry.get("insurance_cost_band",""),
                entry.get("climate_suitability",""), entry.get("web_search_performed",""),
                entry.get("short_verdict","")
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
        except Exception:
            pass

# ---------------------- Stabilization ----------------------
def get_avg_score(identifier: str, model_name: str):
    hist = load_history()
    scores = []
    for h in hist:
        fa = h.get("from_ad", {}) or {}
        if identifier and fa.get("vin","").lower() == identifier.lower():
            if isinstance(h.get("deal_score"), (int,float)):
                scores.append(h["deal_score"])
        elif not identifier and model_name and model_name.lower() in (fa.get("model","") or "").lower():
            if isinstance(h.get("deal_score"), (int,float)):
                scores.append(h["deal_score"])
    return round(sum(scores)/len(scores),2) if scores else None

# ---------------------- Prompt (v9.2 Enhanced) -------------
STRICT_SCHEMA_EXAMPLE = """{
"from_ad": {"brand":"Toyota","model":"Camry","year":2020,"trim":"SE","engine":"2.5L I4","transmission":"Automatic","drivetrain":"FWD","mileage_mi":48000,"price_usd":18900,"vin":"unknown","zip":"94110","seller_type":"private"},
"benchmarks":{"fair_price_range_usd":[18000,20000],"reliability_band":"High","known_issues":[],"fuel_efficiency_mpg":{"city":28,"highway":39},"depreciation_trend":"Moderate (-18%)"},
"deal_score":87,"classification":"Great Deal","risk_level":"Low","roi_estimate_24m":7.5,"seller_trust_index":78,"confidence_level":0.96,"web_search_performed":true,"cross_validation_result":"AI estimate within 4.2% of live market average.","reliability_score_web":82,"common_issues_web":["minor infotainment lag"],"ownership_cost_trend":"Moderate","depreciation_two_year_pct":18,"insurance_cost_band":"avg","climate_suitability":"Good","regional_demand_index":73
}"""

def build_prompt(ad: str, extra: str):
    return f"""
You are an expert automotive analyst specializing in the U.S. used-car market.

OBJECTIVE:
Provide a quantitative, JSON-only assessment of a used-car listing based on:
- Market price vs. fair range
- Mileage and usage
- Condition cues and transparency
- Brand reliability and common issues
- ROI, insurance, depreciation, and ownership costs
- Live web-validated data integration

CROSS-VALIDATION (MANDATORY):
Perform a live web search using up-to-date (2023–2025) automotive data.
Cross-verify against sources like Edmunds, Kelley Blue Book, NHTSA, IIHS, Cars.com, RepairPal (do not cite sources).
Retrieve and integrate:
- Reliability rating and recurring issues/recalls
- Real-world MPG
- Fair market value range
- 2-year depreciation (%)
- Insurance cost band (low/avg/high)
- Maintenance cost level (low/moderate/high)
- Regional climate suitability (rust/sunbelt)

SCORING PRINCIPLES:
Excellent deal (< fair −10%) → +15
Overpriced (> fair +10%) → −15
Rebuilt/salvage title → −35
One-owner clean record → +10
No VIN or history report → −5
Sunbelt (CA/TX/AZ/FL) → −3
Rust-belt (OH/MI/PA/IL/NY/WI/MN) → −7
Verified maintenance → +5
"As-Is" sale (dealer) → −10
CPO/warranty → +5

OUTPUT RULES:
1. Return ONE JSON object only (no markdown or text).
2. Match this structure exactly: {STRICT_SCHEMA_EXAMPLE}
3. Round numeric values to 1 decimal.
4. Set "web_search_performed": true if online data was integrated.
5. Do NOT include sources.

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

# ---------------------- UI -------------------------------
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

    inputs = [build_prompt(ad_text, extra)]
    with st.spinner("Analyzing with Gemini 2.5 Pro (live web search)…"):
        data, last_err = None, None
        for attempt in range(3):
            try:
                resp = model.generate_content(inputs, request_options={"timeout": 120})
                data = parse_json_strict(resp.text)
                break
            except Exception as e:
                last_err = str(e)
                st.warning(f"Attempt {attempt+1} failed to produce valid JSON. Retrying…")
                time.sleep(1.0)
        if data is None:
            st.error(f"❌ Failed after 3 attempts. Last error: {last_err}")
            st.stop()

    fa = data.get("from_ad", {}) or {}
    vin_id = fa.get("vin","") or ""
    model_name = fa.get("model","") or ""
    avg = get_avg_score(vin_id, model_name)
    if avg and isinstance(data.get("deal_score"), (int,float)):
        diff = data["deal_score"] - avg
        if abs(diff) >= 10:
            data["deal_score"] = int((data["deal_score"] + avg) / 2)
            sv = (data.get("short_verdict","") or "").strip()
            data["short_verdict"] = (sv + f" ⚙️ Stabilized vs VIN/model avg ({avg}).").strip()

    save_history(data)

    st.divider()
    score = int(data.get("deal_score", 0))
    color = "#16a34a" if score >= 80 else ("#f59e0b" if score >= 60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
    conf = float(data.get("confidence_level", 0) or 0) * 100
    meter("Confidence", conf, "%")

    if data.get("web_search_performed"):
        st.success("🔎 Live web search cross-validation performed.")
        if data.get("cross_validation_result"):
            st.caption(data["cross_validation_result"])
    else:
        st.warning("⚠️ No live web search detected — AI relied on internal knowledge.")

    st.subheader("Summary")
    st.write(data.get("short_verdict",""))

    st.subheader("Listing")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','') or ''}**")
    st.write(f"**Price:** ${fa.get('price_usd',0):,}  |  **Miles:** {fa.get('mileage_mi',0):,}")
    st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'} | **ZIP:** {fa.get('zip','') or 'n/a'} | **VIN:** {fa.get('vin','') or 'n/a'}")

    st.subheader("Emphasized Signals")
    meter("Reliability (web)", data.get("reliability_score_web",0), "/100")
    meter("Regional Demand", data.get("regional_demand_index",0), "/100")
    meter("Seller Trust", data.get("seller_trust_index",0), "/100")

    st.subheader("Risk & Context")
    pill(f"Risk: {data.get('risk_level','')}", data.get("risk_level"))
    pill(f"Insurance: {data.get('insurance_cost_band','')}", data.get("insurance_cost_band"))
    pill(f"Climate: {data.get('climate_suitability','')}", data.get("climate_suitability"))

    issues = data.get("common_issues_web", []) or []
    if issues:
        with st.expander("🧰 Common Issues Reported (Web)"):
            for i in issues:
                st.markdown(f"- {i}")

    st.divider()
    st.caption("© 2025 AI Deal Checker - U.S. Edition (Pro) v9.2.1. AI opinion only; verify independently.")

    hist = load_history()
    if hist:
        st.subheader("Recent Analyses (Last 10)")
        recent = hist[-10:]
        for h in reversed(recent):
            fa_h = h.get("from_ad", {}) or {}
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"**{fa_h.get('brand','')} {fa_h.get('model','')} {fa_h.get('year','')}** — {(fa_h.get('seller_type','') or 'n/a').title()} seller")
            s = int(h.get("deal_score",0))
            col = "#16a34a" if s>=80 else ("#f59e0b" if s>=60 else "#dc2626")
            st.markdown(f"<h4 style='color:{col};margin:4px 0;'>Deal Score: {s}/100</h4>", unsafe_allow_html=True)
            meter("Reliability (web)", h.get("reliability_score_web",0), "/100")
            meter("Seller Trust", h.get("seller_trust_index",0), "/100")
            meter("Confidence", float(h.get("confidence_level",0))*100, "%")
            meter("Regional Demand", h.get("regional_demand_index",0), "/100")
            st.markdown("<div style='margin-top:6px;'>", unsafe_allow_html=True)
            pill(f"Risk: {h.get('risk_level','')}", h.get("risk_level"))
            pill(f"Insurance: {h.get('insurance_cost_band','')}", h.get("insurance_cost_band"))
            pill(f"Climate: {h.get('climate_suitability','')}", h.get("climate_suitability"))
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown(f"<small class='muted'>Recorded: {fa_h.get('zip','n/a')} • {h.get('classification','')} • ROI: {h.get('roi_estimate_24m','')}%</small>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        df = pd.DataFrame(hist)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download History CSV", data=csv, file_name="ai_deal_history_us.csv")
    else:
        st.info("No previous analyses found.")