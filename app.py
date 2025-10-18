# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – v6 (Streamlit Full • Gemini 2.5 Pro • Strict JSON Retry)
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
st.set_page_config(page_title="AI Deal Checker (U.S.)", page_icon="🚗", layout="centered")
st.markdown("""
<style>
:root { --ink:#0f172a; --muted:#64748b; --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; }
h1,h2,h3,h4 { color:var(--ink); font-weight:700; }
small,.muted{ color:var(--muted); }
div.block-container { padding-top:1rem; }
.progress-bar {height:12px;background:#e5e7eb;border-radius:6px;overflow:hidden;}
.progress-bar-fill {height:100%;background:var(--ok);transition:width 0.6s;}
.card { border:1px solid #e5e7eb; border-radius:12px; padding:14px; background:#fff; }
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

# Google Sheets (optional)
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
    # Prefer local JSON (simple + reliable)
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
        # Optional: append flat to Sheets if configured with columns set in your sheet
        if sheet:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {})
            row = [
                ts,
                fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                fa.get("mileage_mi",""), fa.get("price_usd",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("confidence_level",""),
                entry.get("short_verdict","")
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
    "safety_context": "IIHS Top Safety Pick"
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
  "confidence_level": 0.96
}
""".strip()

def build_us_prompt(ad: str, extra: str) -> str:
    return f"""
You are an expert U.S. used-car analyst.
Return **one complete, valid JSON object only** — no markdown, no prose, no code fences.
If output is truncated or invalid, you MUST re-output the **entire JSON** again.

Ad text:
\"\"\"{ad}\"\"\"{extra}

— REQUIRED FIELDS (keep ALL keys; use "unknown" or 0 if missing) —
from_ad: brand, model, year, trim, engine, transmission, drivetrain, mileage_mi, price_usd, vin, zip, seller_type
benchmarks: fair_price_range_usd, reliability_band, known_issues, demand_class, safety_context
deal_score, classification, risk_level, price_delta_vs_fair, otd_estimate_usd,
tco_24m_estimate_usd (fuel_energy, insurance, maintenance),
short_verdict, key_reasons, confidence_level

— EDGE-CASE SCORING TABLE (apply cumulatively; cap ±40) —
| Condition | Adj. | Notes |
|-----------|------|-------|
| Salvage/Rebuilt title | −35 | High risk |
| Fleet/Rental | −8 | Unless strong records |
| Missing VIN | −5 | Transparency issue |
| Price < −30% vs fair | −15 | Possible branded/flood |
| Dealer “As-Is” | −10 | Legal exposure |
| Rust Belt ZIP (MI/OH/NY/PA/WI/MN/IL) | −7 | Corrosion risk |
| Sun Belt ZIP (AZ/NV/FL/TX/CA) | −4 | UV/interior wear |
| EV battery >80k mi or no warranty | −10 | Degradation |
| Missing CarFax mention | −3 | Transparency |
| High-trim verified | +10 | Premium justified |
| One owner + clean title + records | +7 | Lower risk |

— BASE SCORING WEIGHTS (0–100 before edge-case modifiers) —
Price vs fair 30% • Condition/history 25% • Reliability 20% • Mileage vs year 15% • Transparency/title 10%

— OUTPUT FORMAT EXAMPLE (IMITATE STRUCTURE EXACTLY) —
{STRICT_DEMO_JSON}

Return only the JSON object, nothing else.
""".strip()

# ---------------------- Robust JSON Parsing ----------------
def parse_json_strict(raw: str):
    """
    Strict parsing: no 'self-filling' of business fields.
    We only normalize wrappers (code fences) & close mismatched brackets so json.loads can work.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty response")

    # remove accidental code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    # close missing braces/brackets symmetrically (structure-only)
    open_braces, close_braces = raw.count("{"), raw.count("}")
    if close_braces < open_braces:
        raw += "}" * (open_braces - close_braces)
    open_brackets, close_brackets = raw.count("["), raw.count("]")
    if close_brackets < open_brackets:
        raw += "]" * (open_brackets - close_brackets)

    # first try direct
    try:
        return json.loads(raw)
    except Exception:
        # cut up to last closing brace/bracket and retry
        last = max(raw.rfind("}"), raw.rfind("]"))
        if last > 0:
            cut = raw[: last + 1]
            try:
                return json.loads(cut)
            except Exception:
                # deep repair (structure only)
                fixed = repair_json(cut)
                return json.loads(fixed)
        # if nothing works -> fail; outer loop will re-ask model
        raise

# ---------------------- UI -------------------------------
st.title("🚗 AI Deal Checker — U.S. Edition (Pro)")
st.caption("AI-powered used-car deal analysis for American listings (USD / miles).")
st.info("AI opinion only. Always verify with CarFax/AutoCheck and a certified mechanic.", icon="⚠️")

ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Copy-paste the Craigslist/CarGurus/FB Marketplace ad…")
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1, c2, c3 = st.columns(3)
with c1: vin_input = st.text_input("VIN (optional)")
with c2: zip_input = st.text_input("ZIP (optional)")
with c3: seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

if st.button("Check the Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    # Prepare prompt + multimodal
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

    with st.spinner("Analyzing with Gemini 2.5 Pro…"):
        data = None
        last_error = None

        # enforce JSON via retry loop (no ‘self-filling’ of business values)
        for attempt in range(1, 4):
            try:
                resp = model.generate_content(inputs, request_options={"timeout": 120})
                raw = (resp.text or "").strip()
                data = parse_json_strict(raw)
                break
            except Exception as e:
                last_error = str(e)
                st.warning(f"Attempt {attempt} failed to produce valid JSON. Re-asking the model…")
                # Rebuild the same strict prompt (re-enforce)
                inputs[0] = build_us_prompt(ad_text, extra)
                time.sleep(1.2)

        if data is None:
            st.error(f"❌ Failed to get valid JSON after 3 attempts. Last error: {last_error}")
            st.stop()

        # Optional: historical stabilization ONLY if both values exist (no auto-fill)
        try:
            fa = data.get("from_ad", {}) if isinstance(data, dict) else {}
            avg = get_model_avg_us(fa.get("brand",""), fa.get("model",""))
            if isinstance(avg, (int,float)) and isinstance(data.get("deal_score"), (int,float)):
                diff = data["deal_score"] - avg
                if abs(diff) >= 15:
                    data["deal_score"] = int(data["deal_score"] - diff * 0.5)
                    sv = data.get("short_verdict","").strip()
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
        color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 60 else "#dc2626"
        st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
        st.markdown(f"<p style='text-align:center;'>Confidence: {int(conf*100)}%</p>", unsafe_allow_html=True)
        st.markdown(f"<div class='progress-bar'><div class='progress-bar-fill' style='width:{int(conf*100)}%;'></div></div>", unsafe_allow_html=True)

        st.subheader("Summary")
        st.write(data.get("short_verdict",""))

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

        st.subheader("Key Reasons")
        for r in data.get("key_reasons", []) or []:
            st.write(f"- {r}")

        tco = (data.get("tco_24m_estimate_usd", {}) or {})
        if tco:
            st.subheader("24-month TCO (sketch)")
            st.write(
                f"**Fuel/Energy:** ${int(tco.get('fuel_energy',0)):,}  |  "
                f"**Insurance:** {tco.get('insurance','n/a')}  |  "
                f"**Maintenance:** ${int(tco.get('maintenance',0)):,}"
            )

        st.caption("© 2025 AI Deal Checker — U.S. Edition (Pro). AI opinion only; verify with VIN report & PPI.")