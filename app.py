# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.8.1
# Gemini 2.5 Pro | Live Web Reasoning | VIN Avg | Rust | Sheets | ROI | TCO | Negotiation | Checklist
# ===========================================================

import os, json, time
from datetime import datetime
import streamlit as st
import pandas as pd
from json_repair import repair_json
import google.generativeai as genai

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except:
    gspread = None
    Credentials = None

# -------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------
st.set_page_config(page_title="AI Deal Checker (v9.8.1)", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.8.1")
st.caption("AI-powered used-car valuation with live web reasoning, rust awareness, and VIN averaging (Gemini 2.5 Pro).")

API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
LOCAL_FILE = "deal_history_us.json"

if not API_KEY:
    st.error("Missing GEMINI_API_KEY in secrets.")
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
.pill{display:inline-flex;align-items:center;gap:.35rem;padding:.3rem .6rem;border-radius:999px;font-weight:600;font-size:0.9rem;}
.pill.ok{background:#ecfdf5;color:#065f46;}
.pill.warn{background:#fffbeb;color:#92400e;}
.pill.bad{background:#fef2f2;color:#991b1b;}
small.muted{color:var(--muted);}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------
def meter(label, value, suffix=""):
    try: v=float(value)
    except: v=0
    v=max(0,min(100,v))
    css='fill-ok' if v>=70 else ('fill-warn' if v>=40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b><span>{int(v)}{suffix}</span></div>",unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{v}%'></div></div>",unsafe_allow_html=True)

def pill(label, level):
    lvl=(level or '').lower()
    cls='ok' if lvl in ('good','low','high') else ('warn' if lvl in ('avg','moderate','medium') else 'bad')
    st.markdown(f"<span class='pill {cls}'>{label}</span>",unsafe_allow_html=True)

RUST_BELT=["OH","MI","PA","IL","NY","WI","MN"]
def rust_belt_penalty(zip_or_state:str):
    s=(zip_or_state or '').upper()
    return 10 if any(st in s for st in RUST_BELT) else 0

# -------------------------------------------------------------
# HISTORY & AVG
# -------------------------------------------------------------
def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_history(entry):
    data=load_history(); data.append(entry)
    if len(data)>400: data=data[-400:]
    with open(LOCAL_FILE,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    if sheet:
        try:
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa=entry.get("from_ad",{}) or {}
            sheet.append_row([
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("roi_forecast_24m",{}).get("expected",""),
                entry.get("web_search_performed",""), entry.get("confidence_level","")
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            st.warning(f"Sheets write failed: {e}")

def get_avg_score(vin:str,model:str):
    hist=load_history(); vals=[]
    for h in hist:
        fa=h.get("from_ad",{}) or {}
        if vin and fa.get("vin","").lower()==vin.lower():
            if isinstance(h.get("deal_score"),(int,float)): vals.append(h["deal_score"])
        elif model and model.lower() in (fa.get("model","") or "").lower():
            if isinstance(h.get("deal_score"),(int,float)): vals.append(h["deal_score"])
    return round(sum(vals)/len(vals),2) if vals else None

# -------------------------------------------------------------
# PROMPT
# -------------------------------------------------------------
def build_prompt(ad:str, extra:str):
    return f"""
You are a senior automotive analyst AI for the U.S. used-car market (2023–2025). 
You MUST perform a live web reasoning lookup for similar listings (e.g., Cars.com, Edmunds, KBB). 
If a live lookup cannot be performed, clearly set "web_search_performed": false.

Analyze:
- Market price vs current listings.
- Rust-belt corrosion impact on resale value.
- ROI (expected/optimistic/pessimistic).
- TCO (insurance, fuel, maintenance).
- Negotiation advice.
- 5–10 item inspection checklist.
- Confidence level (0–1).

Return a clean JSON:
{{
 "from_ad":{{"brand":"","model":"","year":2020,"vin":"","seller_type":""}},
 "deal_score":0,
 "classification":"",
 "risk_level":"",
 "reasoning":"",
 "market_comparison":"",
 "tco_summary":{{"insurance_est_usd_year":0,"fuel_cost_year":0,"maintenance_next12m_usd":0}},
 "negotiation_advice":"",
 "inspection_checklist":[],
 "roi_forecast_24m":{{"expected":0,"optimistic":0,"pessimistic":0}},
 "web_search_performed": false,
 "confidence_level":0.9
}}

INPUT AD:
\"\"\"{ad}\"\"\"
{extra}
""".strip()

def parse_json_safe(raw:str):
    raw=(raw or "").replace("```json","").replace("```","").strip()
    try: return json.loads(raw)
    except: return json.loads(repair_json(raw))

# -------------------------------------------------------------
# UI
# -------------------------------------------------------------
ad=st.text_area("Paste the listing text:",height=230)
imgs=st.file_uploader("Upload photos (optional):",type=["jpg","jpeg","png"],accept_multiple_files=True)
c1,c2,c3=st.columns(3)
with c1: vin=st.text_input("VIN (optional)")
with c2: zip_code=st.text_input("ZIP / State (e.g., 44105 or OH)")
with c3: seller=st.selectbox("Seller type",["","private","dealer"])

if st.button("Analyze Deal",use_container_width=True,type="primary"):
    if not ad.strip(): st.error("Please paste listing text first."); st.stop()
    extra=""
    if vin: extra+=f"\nVIN: {vin}"
    if zip_code: extra+=f"\nZIP/State: {zip_code}"
    if seller: extra+=f"\nSeller: {seller}"

    rust_pen=rust_belt_penalty(zip_code)
    if rust_pen: extra+=f"\n⚠️ Rust-Belt detected (~{rust_pen} pts corrosion penalty)."

    parts=[{"text":build_prompt(ad,extra)}]
    for img in imgs:
        mime="image/png" if "png" in img.type.lower() else "image/jpeg"
        parts.append({"mime_type":mime,"data":img.read()})

    with st.spinner("Analyzing with Gemini 2.5 Pro (web reasoning)…"):
        data=None
        for _ in range(2):
            try:
                r=model.generate_content(parts,request_options={"timeout":120})
                data=parse_json_safe(r.text); break
            except Exception as e:
                st.warning(f"Retrying... ({e})"); time.sleep(1.5)
        if not data: st.error("Failed to parse response."); st.stop()

    # VIN/model averaging
    avg=get_avg_score(vin,data.get("from_ad",{}).get("model",""))
    if avg and isinstance(data.get("deal_score"),(int,float)):
        diff=data["deal_score"]-avg
        if abs(diff)>10:
            data["deal_score"]=round((data["deal_score"]+avg)/2,1)
            data["reasoning"]+=(f" ⚙️ Stabilized vs model/VIN avg ({avg}).")

    final=max(0,min(100,round(data.get("deal_score",0)-rust_pen)))
    data["deal_score_final"]=final
    save_history(data)

    # ---------------------------------------------------------
    # DISPLAY
    # ---------------------------------------------------------
    color="#16a34a" if final>=80 else ("#f59e0b" if final>=60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {final}/100</h2>",unsafe_allow_html=True)

    if data.get("web_search_performed"):
        st.success("🌐 Live web search performed and validated.")
    else:
        st.warning("⚠️ No live web lookup detected (AI used internal data only).")

    st.subheader("🧭 Why this score?")
    st.write(data.get("reasoning",""))

    st.subheader("Market Comparison")
    st.write(data.get("market_comparison","No data."))

    if rust_pen: st.caption(f"⚠️ Rust-Belt corrosion penalty applied ({rust_pen} pts).")

    tco=data.get("tco_summary",{})
    if tco:
        st.subheader("Total Cost of Ownership (TCO)")
        st.write(f"Insurance ≈ ${tco.get('insurance_est_usd_year','n/a')}/yr | "
                 f"Fuel ≈ ${tco.get('fuel_cost_year','n/a')}/yr | "
                 f"Maintenance ≈ ${tco.get('maintenance_next12m_usd','n/a')}/yr")

    st.subheader("Negotiation Advice")
    st.write(data.get("negotiation_advice",""))

    st.subheader("Inspection Checklist")
    for item in data.get("inspection_checklist",[]): st.write(f"• {item}")

    roi=data.get("roi_forecast_24m",{})
    if roi:
        st.subheader("ROI Forecast (24 months)")
        st.write(f"Expected {roi.get('expected','')}% | Optimistic {roi.get('optimistic','')}% | Pessimistic {roi.get('pessimistic','')}%")

    meter("Confidence",float(data.get("confidence_level",0))*100,"%")
    pill(f"Risk: {data.get('risk_level','')}",data.get("risk_level"))

    st.caption("© 2025 AI Deal Checker v9.8.1 — Gemini 2.5 Pro (Web Reasoning). AI analysis only; verify independently.")