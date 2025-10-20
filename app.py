# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.3 (Stable Full)
# Elastic-Deterministic Deal Score + Flexible ROI (24m)
# + On-screen DEBUG breakdown for Score & ROI reasoning
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
st.set_page_config(page_title="AI Deal Checker (v9.9.3 Stable)", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.3")
st.caption("Deterministic score + Flexible ROI with on-screen debug reasoning (Gemini 2.5 Pro).")

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
.debug {font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        background:#0b1220; color:#e6edf3; border-radius:10px; padding:14px; line-height:1.45;}
.debug h4{margin:0 0 8px 0; color:#8ab4f8;}
.debug .k{color:#7ee787;}
.debug .v{color:#79c0ff;}
.debug .n{color:#ffa657;}
.debug .w{color:#ff7b72;}
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
    t = re.sub(r'\s+', ' ', txt)
    m = re.search(r'(?i)(?:\$?\s*)(\d{1,3}(?:,\d{3})+|\d{4,6})(?:\s*usd)?', t)
    if m:
        try:
            val = m.group(1).replace(',','')
            return float(val)
        except:
            return None
    return None

def parse_json_safe(raw:str):
    raw=(raw or "").replace("```json","").replace("```","").strip()
    try: return json.loads(raw)
    except: return json.loads(repair_json(raw))

def safe_get_ask_price(data:dict):
    if not isinstance(data, dict): return None
    for k in ("ask_price_usd","price_usd","asking_price","price"):
        v = data.get(k)
        try:
            if v is None: 
                continue
            return float(str(v).replace(",","").replace("$","").strip())
        except:
            continue
    return None

# -------------------------------------------------------------
# HARDENING LAYERS (Sanity + Fallback)
# -------------------------------------------------------------
def clip(x, lo, hi):
    try:
        x=float(x)
    except:
        x=0.0
    return max(lo, min(hi, x))

def safe_value(data:dict, key:str, default):
    if not isinstance(data, dict): return default
    v = data.get(key, default)
    if v in (None, "", [], {}, "null", "N/A", "NA"): return default
    return v

def validate_model_output(data:dict, debug_lines:list):
    if not isinstance(data, dict): data = {}

    # --- Normalize deal score ---
    score_raw = data.get("deal_score", None)
    try:
        score = float(score_raw)
    except:
        score = None

    if score is None:
        debug_lines.append("deal_score: <missing> → set to 50.0 (default)")
        score = 50.0
    elif score <= 10:
        debug_lines.append(f"deal_score: detected 0–10 scale ({score_raw}) → ×10")
        score *= 10
    elif 300 <= score <= 1000:
        debug_lines.append(f"deal_score: detected 0–1000 scale ({score_raw}) → ÷10")
        score /= 10.0
    elif score > 1000:
        debug_lines.append(f"deal_score: absurd scale ({score_raw}) → clamp to 90")
        score = 90.0

    score = round(clip(score, 0, 100), 1)
    data["deal_score"] = score

    # --- Normalize ROI ---
    roi = data.get("roi_forecast_24m", {})
    if not isinstance(roi, dict): roi = {}
    for k in ["expected", "optimistic", "pessimistic"]:
        v_raw = roi.get(k, None)
        try:
            v = float(v_raw)
        except:
            v = None
        if v is None:
            roi[k] = 0.0
            debug_lines.append(f"roi.{k}: <missing> → set 0.0")
            continue
        if abs(v) > 200:
            debug_lines.append(f"roi.{k}: detected ×100 scale ({v_raw}) → ÷100")
            v = v / 100.0
        roi[k] = round(clip(v, -80, 60), 1)
    data["roi_forecast_24m"] = roi

    # Ensure numeric blocks
    data["price_stats"] = safe_value(data, "price_stats", {"median": None, "p25": None, "p75": None})
    data["mileage_stats"] = safe_value(data, "mileage_stats", {"median": None, "std": None})
    data["vehicle_facts"] = safe_value(data, "vehicle_facts", {})
    data["weights"] = safe_value(data, "weights", {})
    data["missing_factors"] = safe_value(data, "missing_factors", [])

    return data

def quick_fallback_score(ad_text:str, debug_lines:list):
    ad = (ad_text or "").lower()
    score = 50
    if "clean title" in ad or "clean carfax" in ad:
        score += 10; debug_lines.append("fallback: +10 (clean title/carfax)")
    if "rebuilt" in ad or "salvage" in ad:
        score -= 20; debug_lines.append("fallback: -20 (rebuilt/salvage)")
    if "low miles" in ad or "one owner" in ad:
        score += 8; debug_lines.append("fallback: +8 (low miles/one owner)")
    if "fleet" in ad or "rental" in ad or "press" in ad:
        score -= 10; debug_lines.append("fallback: -10 (fleet/rental/press)")
    if "ppf" in ad or "warranty" in ad or "cpo" in ad:
        score += 6; debug_lines.append("fallback: +6 (ppf/warranty/cpo)")
    score = max(0, min(100, score))
    debug_lines.append(f"fallback: final score {score}")
    return score

# -------------------------------------------------------------
# Deterministic elastic scoring & ROI
# -------------------------------------------------------------
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

def build_components(P_ask, price_stats, mileage_stats, facts, tco_year, state_or_zip, age_years, debug_lines:list):
    P_med = (price_stats or {}).get("median") or P_ask
    miles_med = (mileage_stats or {}).get("median") or 0
    miles_std = (mileage_stats or {}).get("std") or max(1, abs(miles_med)*0.25)

    # Market
    market_delta_pct = 100.0 * (P_ask - P_med) / max(P_med,1.0) if P_med else 0.0
    market_component = clip(100 - abs(market_delta_pct)*0.8, 0, 100)
    debug_lines.append(f"market: P_ask={P_ask}, P_med={P_med} → Δ={market_delta_pct:.2f}% → comp={market_component:.1f}")

    # Mileage
    miles = facts.get("miles") or facts.get("odometer") or 0
    miles_z = (miles - miles_med)/max(miles_std,1.0) if miles_std else 0
    mileage_component = clip(100 - abs(miles_z*10), 0, 100)
    debug_lines.append(f"mileage: miles={miles}, miles_med={miles_med}, std={miles_std} → z={miles_z:.2f} → comp={mileage_component:.1f}")

    # TCO
    tco_ratio = 100.0 * (tco_year or 0)/max(P_ask,1.0) if P_ask else 0
    tco_component = clip(100 - (tco_ratio - 10.0), 0, 100)
    debug_lines.append(f"tco: tco_year={tco_year}, ratio={tco_ratio:.2f}% → comp={tco_component:.1f}")

    # Title
    title = (facts.get("title_status") or "unknown").lower()
    title_component = {"clean":100, "rebuilt":70, "salvage":50}.get(title, 80)
    debug_lines.append(f"title: '{title}' → comp={title_component}")

    # Accidents
    accidents = int(facts.get("accidents") or 0)
    accidents_component = clip(100 - accidents*10, 0, 100)
    debug_lines.append(f"accidents: count={accidents} → comp={accidents_component}")

    # Owners
    owners = int(facts.get("owners") or 1)
    owners_component = clip(100 - (owners-1)*8, 0, 100)
    debug_lines.append(f"owners: count={owners} → comp={owners_component}")

    # Rust
    r_base = rust_base(state_or_zip)
    rust_component = clip(100 - (r_base * (age_years or 0)*2), 0, 100)
    debug_lines.append(f"rust: state_zip='{state_or_zip}', base={r_base}, age={age_years} → comp={rust_component}")

    # Rarity
    rarity = float(facts.get("rarity_index") or 0.0)
    rarity_component = clip(50 + rarity*50, 0, 100)
    debug_lines.append(f"rarity: index={rarity} → comp={rarity_component}")

    # Options
    options_val = float(facts.get("options_value_usd") or 0.0)
    options_component = clip(60 + (options_val/1000)*2, 0, 100)
    debug_lines.append(f"options: value_usd={options_val} → comp={options_component:.1f}")

    # Days on market
    dom = int(facts.get("days_on_market") or 0)
    dom_component = clip(100 - (dom/10), 0, 100)
    debug_lines.append(f"dom: days={dom} → comp={dom_component:.1f}")

    # Dealer reputation
    dealer_component = float(facts.get("dealer_reputation")) if facts.get("dealer_reputation") is not None else None
    if dealer_component is None:
        debug_lines.append("dealer_reputation: <missing> → ignored in scoring")
    else:
        dealer_component = clip(dealer_component, 0, 100)
        debug_lines.append(f"dealer_reputation: rep={facts.get('dealer_reputation')} → comp={dealer_component}")

    return {
        "market": market_component, "mileage": mileage_component, "tco": tco_component,
        "title": title_component, "accidents": accidents_component, "owners": owners_component,
        "rust": rust_component, "rarity": rarity_component, "options": options_component,
        "dom": dom_component, "dealer_reputation": dealer_component
    }

# ---------- Flexible ROI (24m) ----------
def calc_roi_24m_flexible(inputs:dict, debug_lines:list):
    P_ask = float(inputs.get("P_ask") or 0)
    P_comp_median = float(inputs.get("P_comp_median") or (P_ask or 1))
    dep = float(inputs.get("depreciation_brand_pct_per_year") or 10)/100.0
    tco = float(inputs.get("tco_year") or 0)
    trend = float(inputs.get("market_trend") or 0)/100.0
    mileage_pen = float(inputs.get("mileage_factor") or 0)/100.0
    own_pen = float(inputs.get("ownership_cost_modifiers") or 0)/100.0
    sell_cost = float(inputs.get("sell_cost_pct") or 2)/100.0
    hold_years = float(inputs.get("hold_period") or 24)/12.0

    if P_ask <= 0 or P_ask < 1000:
        debug_lines.append(f"ROI.calc: invalid P_ask ({P_ask}), skipping ROI calc (too low)")
        return {"expected": 0.0, "optimistic": 0.0, "pessimistic": 0.0, "confidence": 0.0}

    dep_eff = clip(dep + mileage_pen + own_pen - trend, 0.02, 0.25)
    P_exit = P_ask * ((1 - dep_eff)**hold_years)
    P_exit_net = P_exit * (1 - sell_cost)
    cash_out = P_ask + (tco * hold_years)
    cash_in = P_exit_net

    debug_lines.extend([
        f"ROI.inputs: P_ask={P_ask}, P_comp_med={P_comp_median}, dep={dep*100:.1f}%, trend={trend*100:.1f}%",
        f"ROI.inputs: mileage_pen={mileage_pen*100:.2f}%, own_pen={own_pen*100:.2f}%, sell_cost={sell_cost*100:.1f}%, hold_years={hold_years}",
        f"ROI.calc: dep_eff={dep_eff*100:.2f}% → P_exit={P_exit:.0f}, P_exit_net={P_exit_net:.0f}, cash_out={cash_out:.0f}, cash_in={cash_in:.0f}"
    ])

    roi_exp = 100.0 * (cash_in - cash_out)/P_ask
    roi_exp = clip(roi_exp, -80, 60)

    missing_keys = [k for k in ["depreciation_brand_pct_per_year","tco_year","market_trend","mileage_factor"] if not inputs.get(k)]
    uncertainty = min(0.3 + 0.05*len(missing_keys), 0.6)
    debug_lines.append(f"ROI.uncertainty: missing={missing_keys} → u={uncertainty:.2f}")

    roi_opt = roi_exp * (1 + uncertainty*0.5)
    roi_pes = roi_exp * (1 - uncertainty)

    out = {
        "expected": round(clip(roi_exp, -80, 60), 1),
        "optimistic": round(clip(roi_opt, -80, 60), 1),
        "pessimistic": round(clip(roi_pes, -80, 60), 1),
        "confidence": round(1 - uncertainty, 2)
    }
    debug_lines.append(f"ROI.out: exp={out['expected']}%, opt={out['optimistic']}%, pes={out['pessimistic']}%, conf={out['confidence']}")
    return out

# -------------------------------------------------------------
# PROMPT
# -------------------------------------------------------------
def build_prompt(ad:str, extra:str):
    return f"""
You are a senior US used-car analyst (2023–2025).
You MUST perform a live web lookup for comps (Cars.com, Autotrader, Edmunds).
If live lookup fails, set "web_search_performed": false.

IMPORTANT EXTRACTION RULES:
- Extract the ASK PRICE (USD) even if it appears only in the TITLE, with a $ sign or commas (e.g., "$26,995" → 26995).
- Normalize numbers; return numeric fields as numbers (not strings).
- If any numeric is missing, set 0 (not null).

Return STRICT JSON with:
{{
 "from_ad": {{"brand":"","model":"","year":null,"vin":"","seller_type":""}},
 "ask_price_usd": 0,
 "price_stats": {{"median":null,"p25":null,"p75":null}},
 "mileage_stats": {{"median":null,"std":null}},
 "tco_year_usd": null,
 "market_trend_24m_pct": 0,
 "depreciation_brand_pct_per_year": null,
 "vehicle_facts": {{"title_status":"clean","accidents":0,"owners":1,"dealer_reputation":null,"rarity_index":0,"options_value_usd":0,"days_on_market":0,"state_or_zip":"","miles":null}},
 "weights": {{"market":0.25,"mileage":0.15,"tco":0.10,"title":0.10,"accidents":0.05,"owners":0.05,"rust":0.05,"rarity":0.05,"options":0.05,"dom":0.05,"dealer_reputation":0.10}},
 "missing_factors": [],
 "deal_score_llm_adj_hint": "neutral|slightly_positive|positive|strong_positive|slightly_negative|negative|strong_negative",
 "web_search_performed": false,
 "confidence_level": 0.8
}}

INPUT AD (title + description combined):
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
        try:
            mime="image/png" if "png" in img.type.lower() else "image/jpeg"
            parts.append({"mime_type":mime,"data":img.read()})
        except Exception:
            pass

    debug_lines = []  # collect verbose reasoning

    with st.spinner("Analyzing with Gemini 2.5 Pro (web reasoning)…"):
        data=None
        raw_text=None
        for attempt in range(2):
            try:
                r=model.generate_content(parts,request_options={"timeout":120})
                raw_text = getattr(r, "text", None)
                data=parse_json_safe(raw_text); 
                break
            except Exception as e:
                st.warning(f"Retrying... ({e})"); time.sleep(1.5)

        if not data:
            fb = quick_fallback_score(ad, debug_lines)
            data = {
                "from_ad": {"brand":"","model":"","year":None,"vin":"","seller_type":seller},
                "price_stats": {"median": None, "p25": None, "p75": None},
                "mileage_stats": {"median": None, "std": None},
                "vehicle_facts": {"title_status":"unknown","accidents":None,"owners":None,"state_or_zip":zip_code},
                "weights": {},
                "missing_factors": ["all"],
                "deal_score": fb,
                "roi_forecast_24m": {"expected": -20.0, "optimistic": -10.0, "pessimistic": -35.0, "confidence": 0.5},
                "web_search_performed": False,
                "confidence_level": 0.5,
                "analysis_note": "⚠️ Fallback heuristics used due to model output error."
            }

    # ---------- Validation layer ----------
    data = validate_model_output(data, debug_lines)

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

    # price detect (multi-source, robust)
    P_ask_val = (
        extract_price_from_text(ad)
        or safe_extract_price_from_data(data)
        or safe_get_ask_price(data)
        or 0
    )
    state_or_zip_eff = facts.get("state_or_zip") or zip_code or ""

    components = build_components(
        P_ask=P_ask_val,
        price_stats=price_stats,
        mileage_stats=mileage_stats,
        facts=facts,
        tco_year=tco_year,
        state_or_zip=state_or_zip_eff,
        age_years=age_years,
        debug_lines=debug_lines
    )

    base_weights = {
        "market": 0.25,"mileage":0.15,"tco":0.10,"title":0.10,"accidents":0.05,"owners":0.05,
        "rust":0.05,"rarity":0.05,"options":0.05,"dom":0.05,"dealer_reputation":0.10
    }
    model_weights = data.get("weights") or {}
    blended = {}
    for k in base_weights:
        try:
            mv = float(model_weights.get(k, base_weights[k]) or 0)
        except:
            mv = base_weights[k]
        blended[k] = 0.7*base_weights[k] + 0.3*mv
    weights = normalize_weights(blended, data.get("missing_factors") or [])

    # explain weights
    for k in sorted(weights, key=lambda x: -weights[x]):
        debug_lines.append(f"weight.{k} = {weights[k]:.3f}")

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

    debug_lines.append(f"score.det = {deal_score_det:.1f}, adj_hint='{adj_hint}' → final={final:.1f}")

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
    if (facts.get("accidents") or 0):
        try:
            if int(facts.get("accidents")) >= 2: ownership_pen += 0.02
        except: pass

    P_med_val = (price_stats or {}).get("median") or P_ask_val

    roi_inputs = {
        "P_ask": P_ask_val,
        "P_comp_median": P_med_val,
        "depreciation_brand_pct_per_year": dep_brand or 10,
        "tco_year": float(tco_year or 0),
        "market_trend": float(market_trend or 0),
        "mileage_factor": float(mileage_factor*100),
        "ownership_cost_modifiers": float(ownership_pen*100),
        "sell_cost_pct": 2.0,
        "hold_period": 24
    }
    roi_calc = calc_roi_24m_flexible(roi_inputs, debug_lines)
    data["roi_forecast_24m"] = roi_calc

    # ---------- Optional VIN/model averaging stabilization ----------
    avg=get_avg_score(vin, (data.get("from_ad",{}) or {}).get("model",""))
    if avg and isinstance(final,(int,float)):
        diff=final-avg
        if abs(diff)>10:
            final_before = final
            final = round((final+avg)/2,1)
            data["deal_score"]=final
            data["deal_score_note"]=f"⚙️ Stabilized vs model/VIN avg ({avg})"
            debug_lines.append(f"stabilizer: final {final_before:.1f} vs avg {avg} → {final:.1f}")

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

    if data.get("analysis_note"):
        st.warning(data.get("analysis_note"))

    with st.expander("Scoring breakdown (components × weights)"):
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

    if final < 30 or (roi and roi.get("confidence",1.0) < 0.6):
        st.warning("⚠️ Low confidence: score/ROI may be distorted due to missing or malformed data.")

    st.subheader("Raw Model Confidence")
    meter("Model confidence", float(data.get("confidence_level",0))*100, "%")

    # ---------- DEBUG OUTPUT ----------
    st.markdown("<div class='debug'><h4>🧩 Debug Breakdown (Score & ROI reasoning)</h4>" + 
                "<br/>".join([ln.replace("→", "→").replace("<","&lt;").replace(">","&gt;") for ln in debug_lines]) +
                "</div>", unsafe_allow_html=True)

    st.caption("© 2025 AI Deal Checker v9.9.3 — Deterministic scoring + on-screen debug reasoning. AI analysis only; verify independently.")
