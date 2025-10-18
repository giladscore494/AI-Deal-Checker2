# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) — v9.1 COMPLETE
# Gemini 2.5 Pro | Web Cross-Validation | VIN-based stabilization
# Includes: common_issues_web expander + full stability via VIN or model
# ===========================================================

import os, re, json, time
from datetime import datetime
import pandas as pd
import streamlit as st
import google.generativeai as genai
from PIL import Image
from json_repair import repair_json
import matplotlib.pyplot as plt

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# ---------------------- Setup ------------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) — v9.1", page_icon="🚗", layout="centered")

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
        creds = Credentials.from_service_account_info(
            SERVICE_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception:
        st.warning("⚠️ Google Sheets connection failed")

# ---------------------- Local Storage ----------------------
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
    """Return avg score for VIN (if available) or by model name."""
    hist = load_history()
    scores = []
    for h in hist:
        fa = h.get("from_ad", {}) or {}
        if identifier and fa.get("vin","").lower() == identifier.lower():
            if isinstance(h.get("deal_score"), (int,float)):
                scores.append(h["deal_score"])
        elif not identifier and model_name.lower() in (fa.get("model","") or "").lower():
            if isinstance(h.get("deal_score"), (int,float)):
                scores.append(h["deal_score"])
    return round(sum(scores)/len(scores),2) if scores else None

# ---------------------- Prompt -----------------------------
STRICT_SCHEMA_EXAMPLE = """{
  "from_ad": {"brand":"Toyota","model":"Camry","year":2020,"trim":"SE","engine":"2.5L","mileage_mi":50000,"price_usd":19000,"vin":"unknown","zip":"90001","seller_type":"private"},
  "benchmarks":{"fair_price_range_usd":[18000,20000],"reliability_band":"High","known_issues":[],"fuel_efficiency_mpg":{"city":28,"highway":39}},
  "deal_score":84,"classification":"Great Deal","risk_level":"Low","roi_estimate_24m":6.8,"seller_trust_index":81,"confidence_level":0.93,
  "web_search_performed":true,"cross_validation_result":"Within ~5% of live market.","reliability_score_web":87,"common_issues_web":["minor infotainment lag"],
  "insurance_cost_band":"avg","climate_suitability":"Good","regional_demand_index":78
}"""

def build_prompt(ad: str, extra: str):
    return f"""
You are a professional U.S. used-car evaluator.
Perform live web validation (2023–2025) and return ONE valid JSON matching exactly:
{STRICT_SCHEMA_EXAMPLE}
Include reliability, common_issues_web, fair price range, MPG, ROI, trust, depreciation, climate, and insurance.
Ad:
\"\"\"{ad}\"\"\"{extra}
Return JSON only.
""".strip()

# ---------------------- Parser -----------------------------
def parse_json_strict(raw: str):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.I).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    ob, cb = raw.count("{"), raw.count("}")
    if cb < ob: raw += "}"*(ob-cb)
    try:
        return json.loads(raw)
    except Exception:
        fixed = repair_json(raw)
        return json.loads(fixed)

# ---------------------- UI Helpers ------------------------
def meter(label, value, suffix=""):
    try: v=float(value)
    except: v=0.0
    v=max(0,min(100,v))
    color = 'fill-ok' if v>=70 else 'fill-warn' if v>=40 else 'fill-bad'
    st.markdown(f"<div class='metric'><b>{label}</b> <span>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{color}' style='width:{v}%'></div></div>", unsafe_allow_html=True)

def pill(label, level):
    level = (level or "").lower()
    cls = "ok" if level in ["good","low","high"] else ("warn" if level in ["avg","moderate"] else "bad")
    st.markdown(f"<span class='pill {cls}'>{label}</span>", unsafe_allow_html=True)

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro) v9.1")
st.caption("AI-powered used-car deal analysis with live web cross-validation, VIN stability & Sheets sync.")

ad_text = st.text_area("Paste the listing text:", height=220)
images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1,c2,c3 = st.columns(3)
with c1: vin = st.text_input("VIN (optional)")
with c2: zipc = st.text_input("ZIP (optional)")
with c3: seller = st.selectbox("Seller type", ["","private","dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad_text.strip(): st.error("Please paste listing text."); st.stop()
    extra = ""
    if vin: extra += f"\nVIN: {vin}"
    if zipc: extra += f"\nZIP: {zipc}"
    if seller: extra += f"\nSeller type: {seller}"

    inputs = [build_prompt(ad_text, extra)]
    for i in images or []:
        try: inputs.append(Image.open(i))
        except: pass

    with st.spinner("Analyzing..."):
        data = None
        for i in range(3):
            try:
                resp = model.generate_content(inputs, request_options={"timeout":120})
                data = parse_json_strict(resp.text)
                break
            except Exception as e:
                st.warning(f"Attempt {i+1} failed: {e}")
                time.sleep(1)

        if not data:
            st.error("❌ Failed after 3 attempts.")
            st.stop()

    # Stabilization by VIN or model
    fa = data.get("from_ad",{}) or {}
    vin_id = fa.get("vin","") or ""
    model_name = fa.get("model","") or ""
    avg = get_avg_score(vin_id, model_name)
    if avg and isinstance(data.get("deal_score"), (int,float)):
        diff = data["deal_score"] - avg
        if abs(diff) >= 10:
            data["deal_score"] = int((data["deal_score"] + avg)/2)
            data["short_verdict"] = (data.get("short_verdict","") + f" ⚙️ Stabilized vs VIN/model avg ({avg}).").strip()

    save_history(data)

    # -------- Display --------
    st.divider()
    score = int(data.get("deal_score",0))
    color = "#16a34a" if score>=80 else "#f59e0b" if score>=60 else "#dc2626"
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)

    conf = data.get("confidence_level",0)*100
    meter("Confidence", conf, "%")

    if data.get("web_search_performed"): st.success("🔎 Web cross-validation performed.")
    else: st.warning("⚠️ No live web validation detected.")

    st.subheader("Summary")
    st.write(data.get("short_verdict",""))

    st.subheader("Listing")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','') or ''}**")
    st.write(f"**Price:** ${fa.get('price_usd',0):,}  |  **Miles:** {fa.get('mileage_mi',0):,}")
    st.write(f"**Seller:** {fa.get('seller_type','')} | **ZIP:** {fa.get('zip','')} | **VIN:** {fa.get('vin','')}")

    # Metrics
    st.subheader("Emphasized Signals")
    meter("Reliability (web)", data.get("reliability_score_web",0), "/100")
    meter("Regional Demand", data.get("regional_demand_index",0), "/100")
    meter("Seller Trust", data.get("seller_trust_index",0), "/100")

    # Pills
    st.subheader("Risk & Context")
    pill(f"Risk: {data.get('risk_level','')}", data.get("risk_level"))
    pill(f"Insurance: {data.get('insurance_cost_band','')}", data.get("insurance_cost_band"))
    pill(f"Climate: {data.get('climate_suitability','')}", data.get("climate_suitability"))

    # Common Issues section
    issues = data.get("common_issues_web", []) or []
    if issues:
        with st.expander("🧰 Common Issues Reported (Web)"):
            for i in issues:
                st.markdown(f"- {i}")

    # History & Export
    st.divider()
    st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro) v9.1. AI opinion only; verify independently.")

    hist = load_history()
    if hist:
        df = pd.DataFrame(hist)
        st.dataframe(df.tail(10), use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download History CSV", data=csv, file_name="ai_deal_history_us.csv")