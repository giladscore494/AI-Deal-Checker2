# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v8.1 Pro Visual Intelligence
# • Gemini 2.5 Pro
# • Internet Cross-Validation REQUIRED in prompt (no sources list in output)
# • ROI (24m), Seller Trust Index, Depreciation Trend
# • Visual dashboard: emphasized bars for ALL key params
# • Strict JSON schema with retry loop (up to 3 attempts)
# • Local JSON history + optional Google Sheets append
# ===========================================================

import os, re, json, time, traceback
from datetime import datetime
import streamlit as st
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from json_repair import repair_json

# ---------------------- App Config -------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) v8.1", page_icon="🚗", layout="centered")
st.markdown("""
<style>
:root { --ink:#0f172a; --muted:#64748b; --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --accent:#2563eb; }
* { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", Arial; }
h1,h2,h3,h4 { color:var(--ink); font-weight:700; }
small,.muted{ color:var(--muted); }
div.block-container { padding-top:1rem; }
hr{ border:none;height:1px;background:#e5e7eb;margin:18px 0;}
.card { border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#fff; }
.badge { display:inline-block; padding:4px 10px; border-radius:999px; background:#eef2ff; color:#3730a3; font-weight:600; font-size:.8rem;}
.progress {height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;}
.fill-ok {height:100%;background:var(--ok);transition:width .6s;}
.fill-warn {height:100%;background:var(--warn);transition:width .6s;}
.fill-bad {height:100%;background:var(--bad);transition:width .6s;}
.metric { display:flex; align-items:center; justify-content:space-between; margin:8px 0 6px; }
.metric .label { font-weight:600; color:#111827; }
.metric .value { font-variant-numeric: tabular-nums; font-weight:700; }
.pill { display:inline-flex; align-items:center; gap:.4rem; padding:.35rem .6rem; border-radius:999px; font-weight:600; }
.pill.ok { background:#ecfdf5; color:#065f46; }
.pill.warn { background:#fffbeb; color:#92400e; }
.pill.bad { background:#fef2f2; color:#991b1b; }
.grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:14px;}
@media (max-width: 860px){ .grid {grid-template-columns:1fr;} }
.kv { display:flex; gap:.5rem; flex-wrap:wrap;}
.kv span { background:#f3f4f6;border-radius:8px;padding:4px 8px; }
</style>
""", unsafe_allow_html=True)

# ---------------------- Secrets / Setup --------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
LOCAL_FILE = "data_history_us.json"

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

# Model: Gemini 2.5 Pro
MODEL_NAME = "gemini-2.5-pro"
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(MODEL_NAME)

# Google Sheets (optional – same behavior)
sheet = None
if SERVICE_ACCOUNT_JSON and SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception:
        st.toast("⚠️ Google Sheets unavailable — using local file.")
else:
    st.toast("ℹ️ Using local storage (no Sheets connection).")

# ---------------------- Persistence ------------------------
def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_to_history(entry: dict):
    try:
        data = load_history()
        data.append(entry)
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if sheet:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {})
            row = [
                ts,
                fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                fa.get("mileage_mi",""), fa.get("price_usd",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("confidence_level",""),
                entry.get("roi_estimate_24m",""),
                entry.get("seller_trust_index",""),
                entry.get("depreciation_two_year_pct",""),
                entry.get("short_verdict",""),
                entry.get("web_search_performed",""),
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.warning(f"Save failed: {e}")

def get_model_avg_us(brand: str, model_name: str):
    hist = load_history()
    scores = [
        h.get("deal_score") for h in hist
        if isinstance(h.get("deal_score"), (int,float))
        and h.get("from_ad", {}).get("brand","").lower()==brand.lower()
        and model_name.lower() in h.get("from_ad", {}).get("model","").lower()
    ]
    return round(sum(scores)/len(scores),2) if scores else None

# ---------------------- Prompt -----------------------------
STRICT_DEMO_JSON = """
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
  "key_reasons": [
    "Below-market pricing",
    "Clean title, one owner",
    "High reliability rating"
  ],
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
""".strip()

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
""".strip()

def build_us_prompt(ad: str, extra: str) -> str:
    return f"""
You are an expert U.S. used-car analyst.

CRITICAL OUTPUT RULES:
• Return ONE complete, valid JSON object ONLY (no markdown, no prose, no code fences).
• If output is truncated/invalid, you MUST re-output the FULL JSON again.
• Keep ALL keys; if unknown, set "unknown" or 0.
• JSON must start with '{{' and end with '}}'.

INTERNET CROSS-VALIDATION REQUIREMENT:
• Perform a live web search using your knowledge augmentation ability (2023–2025 data).
• Retrieve: reliability rating, common issues, real-world fuel economy (MPG), current market value range, recall/safety signals, depreciation trend (24m), insurance & maintenance averages.
• Compare web findings against the ad data and your AI estimation.
• Output fields MUST include:
  "web_search_performed": true/false,
  "cross_validation_result": ""  (short text on alignment vs live data)
• Do NOT list the specific sources in the JSON.

EDGE-CASE SCORING (apply cumulatively; cap ±40 total adjustment):
{EDGE_CASE_TABLE}

BASE SCORING WEIGHTS (0–100 before edge-case modifiers):
Price vs fair 30% • Condition/history 25% • Reliability 20% • Mileage vs year 15% • Transparency/title 10%

CLIMATE/INSURANCE/DEPRECIATION/BEHAVIOR ENRICHMENT:
• Assess climate suitability (Rust-belt risk, Sun-belt UV wear).
• Estimate insurance cost band (low/avg/high) for this model/year.
• Forecast 2-year depreciation percentage and also label trend (Low/Moderate/High).
• Compute a regional demand index (0–100).
• Compute Seller Trust Index (0–100) based on transparency (VIN/history), tone, price justification, and seller type.

IMAGE GUIDANCE (if images present):
• If dealer lot/branding visible, infer seller_type="dealer" unless stated otherwise.
• Flag mismatched panels, curb rash, unusual tire wear as risk cues.

REQUIRED OUTPUT SCHEMA (IMITATE STRUCTURE EXACTLY):
{STRICT_DEMO_JSON}

Ad text:
\"\"\"{ad}\"\"\"{extra}

Return ONLY the JSON object.
""".strip()

# ---------------------- JSON Parsing (strict) --------------
def parse_json_strict(raw: str):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty response")
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    # close braces/brackets symmetrically
    ob, cb = raw.count("{"), raw.count("}")
    if cb < ob: raw += "}" * (ob - cb)
    osq, csq = raw.count("["), raw.count("]")
    if csq < osq: raw += "]" * (osq - csq)
    try:
        return json.loads(raw)
    except Exception:
        last = max(raw.rfind("}"), raw.rfind("]"))
        if last > 0:
            cut = raw[: last + 1]
            try:
                return json.loads(cut)
            except Exception:
                fixed = repair_json(cut)
                return json.loads(fixed)
        raise

# ---------------------- Helpers (UI) -----------------------
def meter(label: str, value: float, suffix: str = "", invert: bool = False):
    """
    Render emphasized bar for a metric.
    value: 0-100 (we clamp)
    invert=True means 'lower is better' (we invert fill for color heuristic)
    """
    try:
        v = float(value)
    except Exception:
        v = 0.0
    v = max(0.0, min(100.0, v))
    show_v = v
    # choose class by value (or inverted)
    ref = (100.0 - v) if invert else v
    cls = 'fill-ok' if ref >= 70 else 'fill-warn' if ref >= 40 else 'fill-bad'
    st.markdown(f"<div class='metric'><span class='label'>{label}</span><span class='value'>{int(show_v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{cls}' style='width:{int(show_v)}%'></div></div>", unsafe_allow_html=True)

def pill(label: str, level: str):
    level = (level or "").strip().lower()
    cls = 'ok' if level in ('low','good','high') else ('warn' if level in ('avg','moderate','medium') else 'bad')
    st.markdown(f"<span class='pill {cls}'>{label}</span>", unsafe_allow_html=True)

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro) v8.1")
st.caption("AI-powered used-car deal analysis with live web cross-validation, ROI & seller trust (USD / miles).")
st.info("AI opinion only. Always verify with CarFax/AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Copy-paste the Craigslist / CarGurus / FB Marketplace ad…")
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)

c1, c2, c3 = st.columns(3)
with c1: vin_input = st.text_input("VIN (optional)")
with c2: zip_input = st.text_input("ZIP (optional)")
with c3: seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
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
                st.warning(f"Attempt {attempt} failed to produce valid JSON. Re-asking the model…")
                inputs[0] = build_us_prompt(ad_text, extra)
                time.sleep(1.0)

        if data is None:
            st.error(f"❌ Failed to get valid JSON after 3 attempts. Last error: {last_error}")
            st.stop()

        # Optional stabilization vs historical avg (no self-filling; only if both exist)
        try:
            fa = data.get("from_ad", {}) if isinstance(data, dict) else {}
            avg = get_model_avg_us(fa.get("brand",""), fa.get("model",""))
            if isinstance(avg, (int,float)) and isinstance(data.get("deal_score"), (int,float)):
                diff = data["deal_score"] - avg
                if abs(diff) >= 15:
                    data["deal_score"] = int(data["deal_score"] - diff * 0.5)
                    sv = (data.get("short_verdict","") or "").strip()
                    data["short_verdict"] = (sv + f" ⚙️ Stabilized vs historical mean ({avg}).").strip()
        except Exception:
            pass

        # Save
        try:
            save_to_history(data)
        except Exception as e:
            st.warning(f"History save issue: {e}")

        # ---------- Display (Visual Dashboard) ----------
        st.divider()
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
        mpg_city = bench.get("fuel_efficiency_mpg", {}).get("city", None) if isinstance(bench.get("fuel_efficiency_mpg", {}), dict) else None
        mpg_hwy  = bench.get("fuel_efficiency_mpg", {}).get("highway", None) if isinstance(bench.get("fuel_efficiency_mpg", {}), dict) else None

        # Headline score
        color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 60 else "#dc2626"
        st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)

        # Confidence
        meter("Confidence", conf*100, "%")

        # Web cross-validation
        if web_flag:
            st.success("🔎 Web cross-validation performed (live data used).")
            xval = data.get("cross_validation_result","")
            if xval:
                st.caption(xval)
        else:
            st.warning("⚠️ No live web search performed — AI used internal knowledge only.")

        # Summary
        st.subheader("Summary")
        st.write(data.get("short_verdict",""))

        # Listing block
        st.subheader("Listing")
        fa = data.get("from_ad", {}) or {}
        st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','')}**")
        st.write(f"**Price:** ${fa.get('price_usd',0):,}  |  **Miles:** {fa.get('mileage_mi',0):,}")
        st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'}  |  **ZIP:** {fa.get('zip','') or 'n/a'}  |  **VIN:** {fa.get('vin','') or 'n/a'}")

        # Visual metrics grid
        st.subheader("Emphasized Signals")
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='grid'>", unsafe_allow_html=True)

        # Col 1
        st.markdown("<div>", unsafe_allow_html=True)
        meter("Reliability (web)", reliability_web, "/100")
        meter("Regional Demand", demand_idx, "/100")
        # Depreciation: lower = better → invert bar color choice
        inv_dep = max(0, min(100, 100 - dep2y))
        meter("2y Depreciation (lower is better)", inv_dep, "/100 (inverted)", invert=False)
        st.markdown("</div>", unsafe_allow_html=True)

        # Col 2
        st.markdown("<div>", unsafe_allow_html=True)
        # ROI (− or +). Normalize to 0–100 for bar, cap ±30%
        roi_cap = max(-30.0, min(30.0, roi_pct))
        roi_norm = (roi_cap + 30.0) * (100.0/60.0)  # -30→0, +30→100
        meter("ROI (24m) potential", roi_norm, f"% ({roi_pct:+.1f}%)")
        meter("Seller Trust Index", trust, "/100")
        # MPG visual (if exists) – average two bars
        if (isinstance(mpg_city,(int,float)) and isinstance(mpg_hwy,(int,float))):
            city_norm = max(0,min(60, mpg_city))*(100/60)  # normalize to 60 mpg headroom
            hwy_norm = max(0,min(60, mpg_hwy))*(100/60)
            meter("Fuel Economy (city)", city_norm, f" MPG ({mpg_city})")
            meter("Fuel Economy (hwy)",  hwy_norm, f" MPG ({mpg_hwy})")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)  # .grid
        st.markdown("</div>", unsafe_allow_html=True)  # .card

        # Qualitative pills
        st.subheader("Qualitative Flags")
        pill(f"Risk: {risk_level or 'n/a'}", "low" if (risk_level or '').lower()=="low" else ("moderate" if (risk_level or '').lower()=="moderate" else "high"))
        st.write(" ")
        if insurance_band:
            pill(f"Insurance: {insurance_band}", insurance_band)
        if climate:
            pill(f"Climate: {climate}", "moderate" if "Moderate" in climate else ("low" if "Good" in climate or "Low" in clim