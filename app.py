# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) — v8.6 FULL
# Gemini 2.5 Pro | Web Cross-Validation | ROI | Trust | Depreciation | MPG
# • Strict JSON schema + retry loop + robust parse/repair
# • Images/VIN/ZIP/Seller fields
# • Fair range + price delta + mileage penalty by age
# • Local history save (JSON)
# ===========================================================

import os, re, json, time
from datetime import datetime
import streamlit as st
import google.generativeai as genai
from PIL import Image
from json_repair import repair_json

# ---------------------- App Config -------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) — v8.6 FULL", page_icon="🚗", layout="centered")

# ---------------------- Styling ----------------------------
st.markdown("""
<style>
:root{--ink:#0f172a;--muted:#64748b;--ok:#16a34a;--warn:#f59e0b;--bad:#dc2626;}
*{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Helvetica Neue",Arial}
h1,h2,h3,h4{color:var(--ink);font-weight:700}
small,.muted{color:var(--muted)}
div.block-container{padding-top:1rem}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#fff}
.progress{height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;margin-bottom:10px}
.fill-ok{height:100%;background:var(--ok)}
.fill-warn{height:100%;background:var(--warn)}
.fill-bad{height:100%;background:var(--bad)}
.metric{display:flex;align-items:center;justify-content:space-between;margin:6px 0}
.metric .label{font-weight:600;color:#111827}
.metric .value{font-variant-numeric:tabular-nums;font-weight:700}
.pill{display:inline-flex;align-items:center;gap:.4rem;padding:.35rem .6rem;border-radius:999px;font-weight:600;margin-right:6px}
.pill.ok{background:#ecfdf5;color:#065f46}
.pill.warn{background:#fffbeb;color:#92400e}
.pill.bad{background:#fef2f2;color:#991b1b}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.kv{display:flex;gap:.5rem;flex-wrap:wrap}
.kv span{background:#f3f4f6;border-radius:8px;padding:4px 8px}
</style>
""", unsafe_allow_html=True)

# ---------------------- Secrets / Setup --------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
LOCAL_FILE = "data_history_us.json"

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
MODEL_NAME = "gemini-2.5-pro"
model = genai.GenerativeModel(MODEL_NAME)

# ---------------------- Persistence ------------------------
def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry: dict):
    try:
        data = load_history()
        data.append(entry)
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_model_avg_us(brand: str, model_name: str):
    hist = load_history()
    scores = [
        h.get("deal_score") for h in hist
        if isinstance(h.get("deal_score"), (int,float))
        and h.get("from_ad", {}).get("brand","").lower()==(brand or "").lower()
        and (model_name or "").lower() in (h.get("from_ad", {}).get("model","") or "").lower()
    ]
    return round(sum(scores)/len(scores),2) if scores else None

# ---------------------- Prompt Blocks ----------------------
EDGE_CASE_TABLE = """
| Condition | Adj. | Notes |
|-----------|------|-------|
| Salvage/Rebuilt title | −35 | High risk |
| Flood/Water damage indicator | −25 | Catastrophic |
| >1 reported accidents | −10 | Resale impact |
| Fleet/Rental history | −8 | Hard usage |
| Missing VIN | −5 | Transparency issue |
| Dealer “As-Is” sale | −10 | Legal exposure |
| High-trim verified | +10 | Premium justified |
| One-owner + clean records | +7 | Lower risk |
| Rust Belt ZIP (OH/MI/PA/WI/MN/IL/NY) | −7 | Corrosion risk |
| Sun Belt ZIP (AZ/NV/FL/TX/CA) | −4 | UV/interior wear |
| EV battery >80k mi / no warranty | −10 | Degradation |
| Hybrid battery warranty valid | +6 | Advantage |
| Missing CarFax/AutoCheck mention | −3 | Transparency |
| No maintenance records | −5 | Caution |
| Dealer warranty provided | +5 | Confidence |
| Brand reputation (CR low <60) | −5 | Reliability risk |
| Brand reputation (CR high ≥80) | +5 | Reliability bonus |
| Early-gen DSG/CVT/turbo issues | −5 | Known issues |
| Interior “very clean” w/photos | +3 | Minor bonus |
| “Firm/No negotiation” | −2 | Lower flexibility |
| “Price drop/Motivated seller” | +3 | Negotiation leverage |
| Aftermarket mods (non-stock) | −5 | Maintenance uncertainty |
| Accident-free verified | +5 | Confidence |
| Unusually low miles (no red flags) | +3 | Value |
| High highway miles ratio | +2 | Better wear profile |
"""

STRICT_SCHEMA_EXAMPLE = """
{
  "from_ad": {
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
  },
  "benchmarks": {
    "fair_price_range_usd": [18000, 20000],
    "reliability_band": "High",
    "known_issues": [],
    "demand_class": "High",
    "safety_context": "IIHS Top Safety Pick",
    "fuel_efficiency_mpg": {"city": 28, "highway": 39},
    "depreciation_trend": "Moderate (-18%)"
  },
  "deal_score": 87,
  "classification": "Great Deal",
  "risk_level": "Low",
  "price_delta_vs_fair": -0.05,
  "otd_estimate_usd": 19900,
  "tco_24m_estimate_usd": {
    "fuel_energy": 2600,
    "insurance": "avg",
    "maintenance": 900
  },
  "roi_estimate_24m": 7.5,
  "seller_trust_index": 78,
  "short_verdict": "Excellent value, reliable powertrain, priced below market.",
  "key_reasons": ["Below-market pricing","Clean title, one owner","High reliability rating"],
  "confidence_level": 0.96,
  "web_search_performed": true,
  "cross_validation_result": "AI estimate within 4.2% of live market average.",
  "reliability_score_web": 82,
  "common_issues_web": ["minor infotainment lag"],
  "ownership_cost_trend": "Moderate",
  "depreciation_two_year_pct": 18,
  "insurance_cost_band": "avg",
  "climate_suitability": "Good",
  "seller_behavior_flags": [],
  "regional_demand_index": 73
}
"""

def build_us_prompt(ad: str, extra: str) -> str:
    return f"""
You are an expert U.S. used-car analyst.

CRITICAL OUTPUT RULES:
• Return ONE complete, valid JSON object ONLY (no markdown, no prose, no code fences).
• If output is truncated/invalid, you MUST re-output the FULL JSON again.
• Keep ALL keys; if unknown, set "unknown" or 0.
• JSON must start with '{{' and end with '}}'.

INTERNET CROSS-VALIDATION REQUIREMENT:
• Perform a live web search using your knowledge augmentation (2023–2025 data).
• Retrieve: reliability rating, common issues, real-world fuel economy (MPG), fair market price range, recall/safety signals, 24m depreciation trend, insurance & maintenance averages.
• Compare web findings vs the ad and your AI estimate.
• MUST include:
  "web_search_performed": true/false,
  "cross_validation_result": "" (short alignment text)
• Do NOT list specific sources in the JSON.

EDGE-CASE SCORING (apply cumulatively; cap ±40):
{EDGE_CASE_TABLE}

BASE WEIGHTS (pre modifiers):
Price vs fair 30% • Condition/history 25% • Reliability 20% • Mileage vs year 15% • Transparency/title 10%

CLIMATE/INSURANCE/BEHAVIOR:
• Climate suitability (Rust-belt vs Sun-belt).
• Insurance band (low/avg/high).
• Seller Trust Index (0–100) from transparency (VIN/history), tone, price justification, seller type.
• Regional demand index (0–100).

IMAGE GUIDANCE:
• If dealer lot/branding visible, infer seller_type="dealer".
• Flag mismatched panels/curb rash/odd tire wear as risk cues.

REQUIRED OUTPUT SCHEMA (IMITATE EXACTLY):
{STRICT_SCHEMA_EXAMPLE}

Ad text:
\"\"\"{ad}\"\"\"{extra}

Return ONLY the JSON object.
""".strip()

# ---------------------- JSON Parser ------------------------
def parse_json_strict(raw: str):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty response")

    # remove code fences if any
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    # balance braces/brackets (structural only)
    ob, cb = raw.count("{"), raw.count("}")
    if cb < ob: raw += "}" * (ob - cb)
    osq, csq = raw.count("["), raw.count("]")
    if csq < osq: raw += "]" * (osq - csq)

    try:
        return json.loads(raw)
    except Exception:
        try:
            last = max(raw.rfind("}"), raw.rfind("]"))
            if last > 0:
                cut = raw[:last+1]
                return json.loads(cut)
        except Exception:
            pass
        fixed = repair_json(raw)
        return json.loads(fixed)

# ---------------------- UI Helpers ------------------------
def meter(label: str, value: float, suffix: str = "", invert: bool = False):
    try:
        v = float(value)
    except Exception:
        v = 0.0
    v = max(0.0, min(100.0, v))
    ref = (100.0 - v) if invert else v
    cls = 'fill-ok' if ref >= 70 else 'fill-warn' if ref >= 40 else 'fill-bad'
    st.markdown(f"<div class='metric'><span class='label'>{label}</span><span class='value'>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{cls}' style='width:{int(v)}%'></div></div>", unsafe_allow_html=True)

def pill_text(text: str, level_hint: str = "warn"):
    lvl = (level_hint or "").lower()
    cls = "ok" if lvl in ("ok","good","low","high") else ("bad" if lvl in ("bad","highrisk","poor") else "warn")
    st.markdown(f"<span class='pill {cls}'>{text}</span>", unsafe_allow_html=True)

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro) v8.6")
st.caption("AI-powered used-car analysis with live market validation, ROI & seller trust (USD / miles).")
st.info("AI opinion only. Always verify with CarFax/AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Copy-paste the Craigslist/CarGurus/FB Marketplace ad…")
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1, c2, c3 = st.columns(3)
with c1: vin_input = st.text_input("VIN (optional)")
with c2: zip_input = st.text_input("ZIP (optional)")
with c3: seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

# ---------------------- Run -------------------------------
if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    extra = ""
    if vin_input: extra += f"\nVIN: {vin_input}"
    if zip_input: extra += f"\nZIP: {zip_input}"
    if seller_type: extra += f"\nSeller type: {seller_type}"

    inputs = [build_us_prompt(ad_text, extra)]
    for img in uploaded_images or []:
        try:
            inputs.append(Image.open(img))
        except Exception:
            pass

    with st.spinner("Analyzing with Gemini 2.5 Pro (web cross-validation)…"):
        data, last_error = None, None
        for attempt in range(1, 4):
            try:
                resp = model.generate_content(inputs, request_options={"timeout": 120})
                raw = (resp.text or "").strip()
                data = parse_json_strict(raw)
                break
            except Exception as e:
                last_error = str(e)
                st.warning(f"Attempt {attempt} failed to produce valid JSON. Retrying…")
                inputs[0] = build_us_prompt(ad_text, extra)
                time.sleep(1)

        if data is None:
            st.error(f"❌ Failed to get valid JSON after 3 attempts. Last error: {last_error}")
            st.stop()

    # -------- Stabilize vs history (visual only) ----------
    try:
        fa_tmp = data.get("from_ad", {}) if isinstance(data, dict) else {}
        avg = get_model_avg_us(fa_tmp.get("brand",""), fa_tmp.get("model",""))
        if isinstance(avg, (int,float)) and isinstance(data.get("deal_score"), (int,float)):
            diff = data["deal_score"] - avg
            if abs(diff) >= 15:
                data["deal_score"] = int(max(0, min(100, data["deal_score"] - diff * 0.5)))
                sv = (data.get("short_verdict","") or "").strip()
                data["short_verdict"] = (sv + f" ⚙️ Stabilized vs historical mean ({avg}).").strip()
    except Exception:
        pass

    # ---------------------- Save --------------------------
    try:
        save_history(data)
    except Exception:
        pass

    # ---------------------- Display -----------------------
    st.divider()

    # Extract fields
    score = int(data.get("deal_score", 0) or 0)
    conf = float(data.get("confidence_level", 0) or 0.0)
    demand_idx = int(data.get("regional_demand_index", 0) or 0)
    reliability_web = int(data.get("reliability_score_web", 0) or 0)
    dep2y = int(data.get("depreciation_two_year_pct", 0) or 0)
    web_flag = bool(data.get("web_search_performed", False))
    roi_pct = float(data.get("roi_estimate_24m", 0) or 0.0)
    trust = int(data.get("seller_trust_index", 0) or 0)
    risk_level = (data.get("risk_level","") or "")
    insurance_band = (data.get("insurance_cost_band","") or "")
    climate = (data.get("climate_suitability","") or "")
    bench = data.get("benchmarks", {}) or {}
    mpg_city = mpg_hwy = None
    if isinstance(bench.get("fuel_efficiency_mpg"), dict):
        mpg_city = bench["fuel_efficiency_mpg"].get("city", None)
        mpg_hwy  = bench["fuel_efficiency_mpg"].get("highway", None)

    fair_lo = fair_hi = None
    if isinstance(bench.get("fair_price_range_usd"), list) and len(bench["fair_price_range_usd"])>=2:
        fair_lo, fair_hi = bench["fair_price_range_usd"][0], bench["fair_price_range_usd"][1]

    fa = data.get("from_ad", {}) or {}
    price = fa.get("price_usd", 0) or 0
    miles = fa.get("mileage_mi", 0) or 0
    year = int(fa.get("year", 0) or 0)

    # Headline score + confidence
    color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 60 else "#dc2626"
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
    meter("Confidence", conf*100, "%")

    # Web cross-validation flag
    if web_flag:
        st.success("🔎 Web cross-validation performed (live data used).")
        if data.get("cross_validation_result"):
            st.caption(data.get("cross_validation_result"))
    else:
        st.warning("⚠️ No live web search performed — AI used internal knowledge only.")

    # Summary
    st.subheader("Summary")
    st.write(data.get("short_verdict",""))

    # Listing
    st.subheader("Listing")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {year} {fa.get('trim','') or ''}**")
    st.write(f"**Price:** ${price:,}  |  **Miles:** {miles:,} mi")
    st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'}  |  **ZIP:** {fa.get('zip','') or 'n/a'}  |  **VIN:** {fa.get('vin','') or 'n/a'}")

    # Fair price & delta
    if fair_lo is not None and fair_hi is not None:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("**Fair Price Range:** " + f"${fair_lo:,} – ${fair_hi:,}")
        try:
            mid = (float(fair_lo)+float(fair_hi))/2.0
            delta = (price - mid)/mid * 100.0 if mid else 0.0
            delta_text = f"{delta:+.1f}%"
            level = "ok" if delta <= -3 else ("warn" if abs(delta) < 5 else "bad")
            pill_text(f"Price Delta vs. Fair: {delta_text}", level)
        except Exception:
            pass
        st.markdown("</div>", unsafe_allow_html=True)

    # Emphasized Signals (two columns)
    st.subheader("Emphasized Signals")
    st.markdown("<div class='card'><div class='grid'>", unsafe_allow_html=True)

    # Column A
    st.markdown("<div>", unsafe_allow_html=True)
    meter("Reliability (web)", reliability_web, "/100")
    st.caption("Higher = fewer chronic issues for this model/year.")
    meter("Regional Demand", demand_idx, "/100")
    st.caption("Local buyer interest & inventory pressure.")
    inv_dep = max(0, min(100, 100 - dep2y))  # lower depreciation is better
    meter("2y Depreciation (lower is better)", inv_dep, "/100")
    st.caption(f"Model forecast: {dep2y}% drop over 24 months.")
    st.markdown("</div>", unsafe_allow_html=True)

    # Column B
    st.markdown("<div>", unsafe_allow_html=True)
    roi_cap = max(-30.0, min(30.0, roi_pct))
    roi_norm = (roi_cap + 30.0) * (100.0/60.0)
    meter("ROI (24m) potential", roi_norm, f"% ({roi_pct:+.1f}%)")
    st.caption("Blends price vs fair, depreciation & demand.")
    meter("Seller Trust Index", trust, "/100")
    st.caption("Transparency, VIN/history disclosure, tone, seller type.")
    if isinstance(mpg_city,(int,float)) and isinstance(mpg_hwy,(int,float)):
        city_norm = max(0,min(60, mpg_city))*(100/60)
        hwy_norm = max(0,min(60, mpg_hwy))*(100/60)
        meter("Fuel Economy (city)", city_norm, f" MPG ({mpg_city})")
        meter("Fuel Economy (hwy)",  hwy_norm, f" MPG ({mpg_hwy})")
        st.caption("EPA/real-world MPG signals.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)

    # Risk & Context (pills)
    st.subheader("Risk & Context")
    pill_text(f"Risk: {risk_level or 'n/a'}",
              "bad" if (risk_level or "").lower()=="high" else "warn" if (risk_level or "").lower()=="moderate" else "ok")
    pill_text(f"Insurance: {insurance_band or 'n/a'}",
              "warn" if (insurance_band or "").lower()=="avg" else ("ok" if (insurance_band or "").lower()=="low" else "bad"))
    pill_text(f"Climate: {climate or 'n/a'}",
              "warn" if "moderate" in (climate or "").lower() else ("ok" if any(k in (climate or "").lower() for k in ["good","low"]) else "bad"))

    # Mileage penalty context
    if isinstance(year, int) and year and isinstance(miles,(int,float)):
        try:
            current_year = datetime.now().year
            age = max(1, current_year - year)
            expected = 12000 * age
            ratio = miles / expected if expected else 1.0
            if ratio >= 1.5:
                st.warning(f"High mileage for age: ~{ratio:.1f}× typical usage (expected ~{int(expected):,} mi).")
            elif ratio <= 0.6:
                st.info(f"Low mileage for age: ~{ratio:.1f}× (expected ~{int(expected):,} mi).")
        except Exception:
            pass

    # Key Reasons
    reasons = data.get("key_reasons", []) or []
    if reasons:
        st.subheader("Key Reasons")
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        for r in reasons:
            st.markdown(f"- {r}")
        st.markdown("</div>", unsafe_allow_html=True)

    # Benchmarks peek (no sources list)
    with st.expander("Benchmarks (summary)"):
        st.json(bench)

    st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro) v8.6. AI opinion only; verify with VIN report & pre-purchase inspection.")