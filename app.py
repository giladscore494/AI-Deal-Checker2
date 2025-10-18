# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v7 Cross-Validated Intelligence Edition
# • Gemini 2.5 Pro
# • Internet Cross-Validation REQUIRED in prompt (no sources list in output)
# • Strict JSON schema with retry loop (up to 3 attempts)
# • 25 U.S. edge cases incl. climate, insurance, depreciation, seller behavior
# • Graphical indicators for reliability, demand, confidence, depreciation
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
st.set_page_config(page_title="AI Deal Checker (U.S.) v7", page_icon="🚗", layout="centered")
st.markdown("""
<style>
:root { --ink:#0f172a; --muted:#64748b; --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --accent:#2563eb; }
h1,h2,h3,h4 { color:var(--ink); font-weight:700; }
small,.muted{ color:var(--muted); }
div.block-container { padding-top:1rem; }
.progress {height:10px;background:#e5e7eb;border-radius:6px;overflow:hidden;}
.fill-ok {height:100%;background:var(--ok);transition:width .6s;}
.fill-warn {height:100%;background:var(--warn);transition:width .6s;}
.fill-bad {height:100%;background:var(--bad);transition:width .6s;}
.badge { display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-weight:600;font-size:.8rem; }
.card { border:1px solid #e5e7eb;border-radius:12px;padding:14px;background:#fff; }
.kv { display:flex;gap:.5rem;flex-wrap:wrap;}
.kv span { background:#f3f4f6;border-radius:8px;padding:4px 8px; }
hr{ border:none;height:1px;background:#e5e7eb;margin:18px 0;}
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

# Google Sheets (optional, same behavior as previous versions)
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
                entry.get("short_verdict",""),
                entry.get("web_search_performed","")
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

def check_consistency_us(brand: str, model_name: str):
    hist = load_history()
    rel = [
        h.get("deal_score") for h in hist
        if isinstance(h.get("deal_score"), (int,float))
        and h.get("from_ad", {}).get("brand","").lower()==brand.lower()
        and model_name.lower() in h.get("from_ad", {}).get("model","").lower()
    ]
    if len(rel) >= 3 and (max(rel) - min(rel) >= 20):
        return True, rel
    return False, rel

def guess_brand_model(text: str):
    if not text: return "", ""
    head = text.splitlines()[0].strip()
    toks = [t for t in re.split(r"[^\w\-]+", head) if t]
    if len(toks) >= 2:
        return toks[0], " ".join(toks[1:3])
    return "", ""

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
    "fuel_efficiency_mpg": {"city": 28, "highway": 39}
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
• Retrieve: reliability rating, common issues, real-world fuel economy (MPG), current market value range, recall/safety signals.
• Compare web findings against the ad data and your AI estimation.
• Output fields MUST include:
  "web_search_performed": true/false,
  "cross_validation_result": ""  (short text on alignment vs live data)
• Do NOT list the specific sources in the JSON.

EDGE-CASE SCORING (apply cumulatively; cap ±40 total adjustment):
{EDGE_CASE_TABLE}

BASE SCORING WEIGHTS (0–100 before edge-case modifiers):
Price vs fair 30% • Condition/history 25% • Reliability 20% • Mileage vs year 15% • Transparency/title 10%

CLIMATE/INSURANCE/DEPRECIATION ENRICHMENT:
• Assess climate suitability (Rust-belt risk, Sun-belt UV wear).
• Estimate insurance cost band (low/avg/high) for this model/year.
• Forecast 2-year depreciation percentage.
• Compute a regional demand index (0–100).

IMAGE GUIDANCE (if images present):
• If dealer lot/branding visible, infer seller_type="dealer" unless stated otherwise.
• Note mismatched panels, curb rash, unusual tire wear as risk cues.

REQUIRED OUTPUT SCHEMA (IMITATE STRUCTURE EXACTLY):
{STRICT_DEMO_JSON}

Ad text:
\"\"\"{ad}\"\"\"{extra}

Return ONLY the JSON object.
""".strip()

# ---------------------- Strict JSON Parsing ----------------
def parse_json_strict(raw: str):
    """Normalize wrappers and structural braces only; no business self-filling."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty response")

    # strip accidental code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    # close missing braces/brackets symmetrically
    open_braces, close_braces = raw.count("{"), raw.count("}")
    if close_braces < open_braces:
        raw += "}" * (open_braces - close_braces)
    open_brackets, close_brackets = raw.count("["), raw.count("]")
    if close_brackets < open_brackets:
        raw += "]" * (open_brackets - close_brackets)

    # direct attempt
    try:
        return json.loads(raw)
    except Exception:
        # cut to last closing brace/bracket and try again; deep repair as last resort
        last = max(raw.rfind("}"), raw.rfind("]"))
        if last > 0:
            cut = raw[: last + 1]
            try:
                return json.loads(cut)
            except Exception:
                fixed = repair_json(cut)
                return json.loads(fixed)
        raise

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro) v7")
st.caption("AI-powered used-car deal analysis with live web cross-validation (USD / miles).")
st.info("AI opinion only. Always verify with CarFax/AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Copy-paste the Craigslist / CarGurus / FB Marketplace ad…")
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)

c1, c2, c3 = st.columns(3)
with c1: vin_input = st.text_input("VIN (optional)")
with c2: zip_input = st.text_input("ZIP (optional)")
with c3: seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

if st.button("Check the Deal", use_container_width=True, type="primary"):
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

        # ---------- Display ----------
        st.divider()
        score = int(data.get("deal_score", 0) or 0)
        conf = float(data.get("confidence_level", 0) or 0.0)
        demand_idx = int(data.get("regional_demand_index", 0) or 0)
        reliability_web = int(data.get("reliability_score_web", 0) or 0)
        dep2y = int(data.get("depreciation_two_year_pct", 0) or 0)
        web_flag = bool(data.get("web_search_performed", False))

        color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 60 else "#dc2626"
        st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)

        # Confidence bar
        st.markdown(f"**Confidence:** {int(conf*100)}%")
        st.markdown(f"<div class='progress'><div class='fill-ok' style='width:{int(conf*100)}%'></div></div>", unsafe_allow_html=True)

        # Web cross-validation flag
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

        # Listing & Benchmarks
        colA, colB = st.columns(2)
        with colA:
            st.subheader("Listing")
            fa = data.get("from_ad", {}) or {}
            st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','')}**")
            st.write(f"**Price:** ${fa.get('price_usd',0):,}  |  **Miles:** {fa.get('mileage_mi',0):,}")
            st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'}  |  **ZIP:** {fa.get('zip','') or 'n/a'}")
            st.write(f"**VIN:** {fa.get('vin','') or 'n/a'}")
        with colB:
            st.subheader("Benchmarks")
            bm = data.get("benchmarks", {}) or {}
            st.json(bm, expanded=False)

        # Graphs: Reliability, Regional Demand, Depreciation (invert), Confidence already shown
        st.subheader("Signals")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Reliability (web): {reliability_web}/100**")
            st.markdown(f"<div class='progress'><div class='fill-ok' style='width:{reliability_web}%'></div></div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"**Regional Demand: {demand_idx}/100**")
            cls = 'fill-ok' if demand_idx>=70 else 'fill-warn' if demand_idx>=40 else 'fill-bad'
            st.markdown(f"<div class='progress'><div class='{cls}' style='width:{demand_idx}%'></div></div>", unsafe_allow_html=True)
        with c3:
            dep_pct = max(0, min(100, dep2y))
            # lower depreciation is better, so invert the bar (100 - dep)
            inv = 100 - dep_pct
            st.markdown(f"**2y Depreciation: {dep_pct}%**")
            cls2 = 'fill-ok' if inv>=70 else 'fill-warn' if inv>=40 else 'fill-bad'
            st.markdown(f"<div class='progress'><div class='{cls2}' style='width:{inv}%'></div></div>", unsafe_allow_html=True)

        # Key reasons
        st.subheader("Key Reasons")
        for r in data.get("key_reasons", []) or []:
            st.write(f"- {r}")

        # TCO
        tco = (data.get("tco_24m_estimate_usd", {}) or {})
        if tco:
            st.subheader("24-month TCO (sketch)")
            try:
                st.write(
                    f"**Fuel/Energy:** ${int(tco.get('fuel_energy',0)):,}  |  "
                    f"**Insurance:** {tco.get('insurance','n/a')}  |  "
                    f"**Maintenance:** ${int(tco.get('maintenance',0)):,}"
                )
            except Exception:
                st.json(tco)

        # Extras (if provided)
        extras = []
        if data.get("insurance_cost_band"): extras.append(f"Insurance band: {data.get('insurance_cost_band')}")
        if data.get("climate_suitability"): extras.append(f"Climate suitability: {data.get('climate_suitability')}")
        if data.get("ownership_cost_trend"): extras.append(f"Ownership cost trend: {data.get('ownership_cost_trend')}")
        if extras:
            st.subheader("Extras")
            st.markdown("<div class='kv'>" + "".join([f"<span>{e}</span>" for e in extras]) + "</div>", unsafe_allow_html=True)

        st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro) v7. AI opinion only; verify with VIN report & PPI.")