# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.9
# Elastic-Deterministic Deal Score + Flexible ROI (24m)
# Gemini 2.5 Pro | Live Web Reasoning | Dynamic Weights | VIN/Model History | Sheets (optional)
# ===========================================================

import os, json, time, re
from datetime import datetime
import streamlit as st
import pandas as pd
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
st.set_page_config(page_title="AI Deal Checker (v9.9)", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.9")
st.caption("Elastic deterministic Deal Score + ROI 24m with dynamic weights (Gemini 2.5 Pro web reasoning).")

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

def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry):
    data=load_history(); data.append(entry)
    if len(data)>400: data=data[-400:]
    with open(LOCAL_FILE,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    if sheet:
        try:
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa=entry.get("from_ad",{}) or {}
            roi=entry.get("roi_forecast_24m",{}) or {}
            sheet.append_row([
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), roi.get("expected",""),
                entry.get("web_search_performed",""), entry.get("confidence_level","")
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            st.warning(f"Sheets write failed: {e}")

# Simple VIN/model average stabilizer (optional usage)
def get_avg_score(vin:str,model:str):
    hist=load_history(); vals=[]
    for h in hist:
        fa=h.get("from_ad",{}) or {}
        if vin and fa.get("vin","").lower()==str(vin).lower():
            if isinstance(h.get("deal_score"),(int,float)): vals.append(h["deal_score"])
        elif model and model.lower() in (fa.get("model","") or "").lower():
            if isinstance(h.get("deal_score"),(int,float)): vals.append(h["deal_score"])
    return round(sum(vals)/len(vals),2) if vals else None

def extract_price_from_text(txt:str):
    if not txt: return None
    t = txt.replace(' ', '')
    m = re.search(r'[\$]?([0-9]{2,3}(?:[,][0-9]{3})+)', t)
    if m:
        try:
            return float(m.group(1).replace(',',''))
        except:
            return None
    return None

def parse_json_safe(raw:str):
    raw=(raw or "").replace("```json","").replace("```","").strip()
    try: return json.loads(raw)
    except: return json.loads(repair_json(raw))

# -------------------------------------------------------------
# Deterministic elastic scoring & ROI
# -------------------------------------------------------------
def clip(x, lo, hi):
    return max(lo, min(hi, x))

RUST_STATES = {"OH","MI","PA","IL","NY","WI","MN"}

def rust_base(state_or_zip:str):
    if not state_or_zip: return 0
    s = str(state_or_zip).upper()
    return 1 if any(k in s for k in RUST_STATES) else 0

def normalize_weights(weights:dict, missing:list):
    w = {k:max(0.0, float(v or 0)) for k,v in (weights or {}).items()}
    for m in (missing or []):
        if m in w: w[m] = 0.0
    s = sum(w.values())
    if s <= 0:
        keys = ["market","mileage","tco","title","accidents","owners","rust","rarity","options","dom","dealer_reputation"]
        return {k: 1.0/len(keys) for k in keys}
    return {k: v/s for k,v in w.items()}

def weighted_score(components:dict, weights:dict):
    score, wsum = 0.0, 0.0
    for k, w in weights.items():
        v = components.get(k, None)
        if v is None: 
            continue
        score += clip(v,0,100) * w
        wsum += w
    if wsum == 0: return 0.0
    return round(score / wsum, 1)

def build_components(P_ask, price_stats, mileage_stats, facts, tco_year, state_or_zip, age_years):
    P_med = (price_stats or {}).get("median") or P_ask
    P_p25 = (price_stats or {}).get("p25") or P_med
    P_p75 = (price_stats or {}).get("p75") or P_med
    miles_med = (mileage_stats or {}).get("median") or 0
    miles_std = (mileage_stats or {}).get("std") or max(1, abs(miles_med)*0.25)

    market_delta_pct = 100.0 * (P_ask - P_med) / max(P_med,1.0)
    market_pen = clip(market_delta_pct * (0.7 if market_delta_pct>0 else 0.3), -10, 30)
    market_component = clip(100 - (market_pen*2), 0, 100)  # scale to visible range

    miles = facts.get("miles") or facts.get("odometer") or 0  # allow later extension
    miles_z = clip((miles - miles_med)/max(miles_std,1.0), -3, 3)
    miles_pen = clip(4.0 * miles_z, -8, 10)
    mileage_component = clip(100 - (miles_pen*6), 0, 100)

    tco_ratio = 100.0 * (tco_year or 0)/max(P_ask,1.0)
    tco_pen = clip((tco_ratio - 10.0)*0.8, 0, 12)
    tco_component = clip(100 - (tco_pen*8), 0, 100)

    title = (facts.get("title_status") or "unknown").lower()
    title_pen = {"clean":0, "rebuilt":20, "salvage":40}.get(title, 8)
    title_component = clip(100 - (title_pen*2), 0, 100)

    accidents = int(facts.get("accidents") or 0)
    acc_pen = clip(7.0*accidents, 0, 20)
    accidents_component = clip(100 - (acc_pen*5), 0, 100)

    owners = int(facts.get("owners") or 1)
    owners_pen = clip(3.0*max(0, owners-1), 0, 12)
    owners_component = clip(100 - (owners_pen*6), 0, 100)

    r_base = rust_base(state_or_zip)
    rust_index = r_base * clip((age_years or 0)/10.0, 0, 1)
    rust_pen = 10.0 * rust_index
    rust_component = clip(100 - (rust_pen*5), 0, 100)

    rarity = float(facts.get("rarity_index") or 0.0)  # 0..1
    rarity_component = clip(50 + rarity*50, 0, 100)

    options_val = float(facts.get("options_value_usd") or 0.0)
    options_bonus_points = clip(max(0.0, options_val)*0.3/1000.0, 0, 4)
    options_component = clip(60 + options_bonus_points*10, 0, 100)

    dom = int(facts.get("days_on_market") or 0)
    dom_pen = 0 if dom<=30 else 5 if dom<=60 else 10 if dom<=90 else 15
    dom_component = clip(100 - dom_pen*5, 0, 100)

    dealer_rep = facts.get("dealer_reputation")
    dealer_component = None if dealer_rep is None else clip(float(dealer_rep),0,100)

    return {
        "market": market_component,
        "mileage": mileage_component,
        "tco": tco_component,
        "title": title_component,
        "accidents": accidents_component,
        "owners": owners_component,
        "rust": rust_component,
        "rarity": rarity_component,
        "options": options_component,
        "dom": dom_component,
        "dealer_reputation": dealer_component
    }

# ---------- Flexible ROI (24m) ----------

def calc_roi_24m_flexible(inputs:dict):
    P_ask = float(inputs.get("P_ask") or 0)
    P_comp_median = float(inputs.get("P_comp_median") or (P_ask or 1))
    dep = float(inputs.get("depreciation_brand_pct_per_year") or 10)/100.0
    tco = float(inputs.get("tco_year") or 0)
    trend = float(inputs.get("market_trend") or 0)/100.0
    mileage_pen = float(inputs.get("mileage_factor") or 0)/100.0
    own_pen = float(inputs.get("ownership_cost_modifiers") or 0)/100.0
    sell_cost = float(inputs.get("sell_cost_pct") or 2)/100.0
    hold_years = float(inputs.get("hold_period") or 24)/12.0

    dep_eff = dep + mileage_pen + own_pen - trend
    dep_eff = clip(dep_eff, 0.02, 0.25)

    P_exit = P_ask * ((1 - dep_eff)**hold_years)
    P_exit_net = P_exit * (1 - sell_cost)

    cash_out = P_ask + (tco * hold_years)
    cash_in = P_exit_net

    if P_ask <= 0:
        return {"expected": 0.0, "optimistic": 0.0, "pessimistic": 0.0, "confidence": 0.5}

    roi_exp = 100.0 * (cash_in - cash_out)/P_ask

    # uncertainty from missing
    missing_keys = [k for k in ["depreciation_brand_pct_per_year","tco_year","market_trend","mileage_factor"] if not inputs.get(k)]
    uncertainty = min(0.3 + 0.05*len(missing_keys), 0.6)

    roi_opt = roi_exp * (1 + uncertainty*0.5)
    roi_pes = roi_exp * (1 - uncertainty)

    return {
        "expected": round(clip(roi_exp, -80, 60), 1),
        "optimistic": round(clip(roi_opt, -80, 60), 1),
        "pessimistic": round(clip(roi_pes, -80, 60), 1),
        "confidence": round(1 - uncertainty, 2)
    }

# -------------------------------------------------------------
# PROMPT (updated to request dynamic weights & numeric blocks)
# -------------------------------------------------------------
def build_prompt(ad:str, extra:str):
    return f"""
You are a senior US used-car analyst (2023–2025).
You MUST perform a live web lookup for comps (Cars.com, Autotrader, Edmunds). 
If live lookup fails, set "web_search_performed": false.

Return STRICT JSON with:
- numeric price stats & mileage stats for matching comps,
- deterministic TCO/year,
- depreciation & market trend,
- discrete vehicle facts,
- dynamic weights that sum to ~1.0 for scoring components,
- and which factors were missing/unverifiable.

{{
 "from_ad": {{"brand":"","model":"","year":null,"vin":"","seller_type":""}},
 "price_stats": {{"median":null,"p25":null,"p75":null}},
 "mileage_stats": {{"median":null,"std":null}},
 "tco_year_usd": null,
 "market_trend_24m_pct": 0,
 "depreciation_brand_pct_per_year": null,

 "vehicle_facts": {{
   "title_status": "clean",
   "accidents": 0,
   "owners": 1,
   "cpo": false,
   "warranty_months": 0,
   "dealer_reputation": null,    // 0-100 or null
   "rarity_index": 0.0,          // 0..1
   "options_value_usd": 0,       // PPF/ceramics etc (realistic fraction of value)
   "days_on_market": 0,
   "state_or_zip": "",
   "miles": null
 }},
 "weights": {{
   "market": 0.25,
   "mileage": 0.15,
   "tco": 0.10,
   "title": 0.10,
   "accidents": 0.05,
   "owners": 0.05,
   "rust": 0.05,
   "rarity": 0.05,
   "options": 0.05,
   "dom": 0.05,
   "dealer_reputation": 0.10
 }},
 "missing_factors": [],

 "deal_score_llm_adj_hint": "neutral|slightly_positive|positive|strong_positive|slightly_negative|negative|strong_negative",

 "web_search_performed": false,
 "confidence_level": 0.8
}}

INPUT AD:
\"\"\"{ad}\"\"\"
{extra}
""".strip()

# -------------------------------------------------------------
# UI
# -------------------------------------------------------------
ad=st.text_area("Paste the listing text:",height=230)
imgs=st.file_uploader("Upload photos (optional):",type=["jpg","jpeg","png"],accept_multiple_files=True)
c1,c2,c3=st.columns(3)
with c1: vin=st.text_input("VIN (optional)")
with c2: zip_code=st.text_input("ZIP / State (e.g., 44105 or OH)")
with c3: seller=st.selectbox("Seller type",["","private","dealer"])

def safe_extract_price_from_data(data:dict):
    # try from market_comparison text if exists
    mc = (data or {}).get("market_comparison") or ""
    return extract_price_from_text(mc)

if st.button("Analyze Deal",use_container_width=True,type="primary"):
    if not ad.strip(): st.error("Please paste listing text first."); st.stop()
    extra=""
    if vin: extra+=f"\nVIN: {vin}"
    if zip_code: extra+=f"\nZIP/State: {zip_code}"
    if seller: extra+=f"\nSeller: {seller}"

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

    # ---------- Deterministic elastic scoring ----------
    price_stats = data.get("price_stats") or {}
    mileage_stats = data.get("mileage_stats") or {}
    tco_year = data.get("tco_year_usd") or data.get("tco_year") or 0
    facts = data.get("vehicle_facts") or {}

    # derive age
    try:
        y = int((data.get("from_ad") or {}).get("year") or 0)
        age_years = max(0, datetime.now().year - y) if y else 0
    except:
        age_years = 0

    # price detect
    P_ask_val = extract_price_from_text(ad) or safe_extract_price_from_data(data) or 0
    state_or_zip_eff = facts.get("state_or_zip") or zip_code or ""

    components = build_components(
        P_ask=P_ask_val,
        price_stats=price_stats,
        mileage_stats=mileage_stats,
        facts=facts,
        tco_year=tco_year,
        state_or_zip=state_or_zip_eff,
        age_years=age_years
    )

    base_weights = {
        "market": 0.25,"mileage":0.15,"tco":0.10,"title":0.10,"accidents":0.05,"owners":0.05,
        "rust":0.05,"rarity":0.05,"options":0.05,"dom":0.05,"dealer_reputation":0.10
    }
    model_weights = data.get("weights") or {}
    blended = {}
    for k in base_weights:
        blended[k] = 0.7*base_weights[k] + 0.3*float(model_weights.get(k, base_weights[k]) or 0)
    weights = normalize_weights(blended, data.get("missing_factors") or [])

    deal_score_det = weighted_score(components, weights)

    # optional small LLM sentiment adj
    adj_hint = (data.get("deal_score_llm_adj_hint") or "neutral").lower()
    adj_map = {
        "strong_negative": -6, "negative": -4, "slightly_negative": -2,
        "neutral": 0, "slightly_positive": 2, "positive": 4, "strong_positive": 6
    }
    final = clip(deal_score_det + adj_map.get(adj_hint,0), 0, 100)
    data["deal_score"] = final
    data["deal_score_components"] = components
    data["deal_score_weights"] = weights

    # ---------- ROI Flexible ----------
    dep_brand = data.get("depreciation_brand_pct_per_year") or (data.get("vehicle_facts") or {}).get("depreciation_brand_pct_per_year")
    market_trend = data.get("market_trend_24m_pct") or 0

    miles = facts.get("miles") or facts.get("odometer") or 0
    miles_med = (mileage_stats or {}).get("median") or miles
    mileage_factor = 0.0
    try:
        if miles_med:
            diff = (float(miles) - float(miles_med))
            mileage_factor = clip(diff/2000.0 * 0.5, -3.0, 3.0)  # ~±0.5% per 2k miles
    except: 
        mileage_factor = 0.0

    ownership_pen = 0.0
    t_stat = str(facts.get("title_status","clean")).lower()
    if t_stat == "rebuilt": ownership_pen += 0.05  # +5% yearly
    if t_stat == "salvage": ownership_pen += 0.10  # +10% yearly
    if (facts.get("accidents") or 0) >= 2: ownership_pen += 0.02

    P_med_val = (price_stats or {}).get("median") or P_ask_val

    roi_inputs = {
        "P_ask": P_ask_val,
        "P_comp_median": P_med_val,
        "depreciation_brand_pct_per_year": dep_brand or 10,
        "tco_year": float(tco_year or 0),
        "market_trend": float(market_trend or 0),
        "mileage_factor": float(mileage_factor*100),            # back to %
        "ownership_cost_modifiers": float(ownership_pen*100),   # back to %
        "sell_cost_pct": 2.0,
        "hold_period": 24
    }
    roi_calc = calc_roi_24m_flexible(roi_inputs)
    data["roi_forecast_24m"] = roi_calc

    # ---------- Optional VIN/model averaging stabilization ----------
    avg=get_avg_score(vin, (data.get("from_ad",{}) or {}).get("model",""))
    if avg and isinstance(final,(int,float)):
        diff=final-avg
        if abs(diff)>10:
            final = round((final+avg)/2,1)
            data["deal_score"]=final
            data["deal_score_note"]="⚙️ Stabilized vs model/VIN avg ({})".format(avg)

    # Save history (local + optional Sheets)
    data["web_search_performed"] = bool(data.get("web_search_performed"))
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

    st.subheader("Scoring breakdown (components × weights)")
    rows=[]
    for k,v in (data.get("deal_score_components") or {}).items():
        rows.append({"component":k,"component_score":v,"weight":round((data.get('deal_score_weights') or {}).get(k,0),3)})
    if rows:
        st.dataframe(pd.DataFrame(rows).sort_values("weight",ascending=False), use_container_width=True)

    st.subheader("ROI Forecast (24 months)")
    roi = data.get("roi_forecast_24m",{})
    st.write(f"Expected {roi.get('expected','')}% | Optimistic {roi.get('optimistic','')}% | Pessimistic {roi.get('pessimistic','')}%")
    if roi.get("confidence") is not None:
        meter("ROI Confidence", float(roi.get("confidence",0))*100, "%")

    st.subheader("Model Notes")
    st.write(data.get("deal_score_note",""))
    st.subheader("Raw Model Confidence")
    meter("Model confidence", float(data.get("confidence_level",0))*100, "%")

    st.caption("© 2025 AI Deal Checker v9.9 — Elastic deterministic scoring with Gemini 2.5 Pro web reasoning. AI analysis only; verify independently.")