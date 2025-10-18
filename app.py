# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker (U.S.) – Production-Ready Minimal App
# • English UI • USD / miles • OTD & 24m TCO sketch
# • Gemini 2.5 Flash • Google Sheets history (optional)
# • Consistency smoothing & JSON auto-repair
# ===========================================================

import os, re, json, traceback
from datetime import datetime

import streamlit as st
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from json_repair import repair_json

# ----------------------- App Config ------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.)", page_icon="🚗", layout="centered")

st.markdown("""
<style>
/* Clean, readable UI */
:root { --ink: #0f172a; --muted:#64748b; --accent:#2563eb; }
h1,h2,h3,h4 { color: var(--ink); font-weight: 700; }
small, .muted { color: var(--muted); }
.stTextInput>div>div>input, .stTextArea>div>textarea { font-size: 0.95rem; }
div.block-container { padding-top: 1.2rem; }
.badge { display:inline-block; padding:4px 8px; border-radius:8px; background:#eef2ff; color:#3730a3; font-weight:600; }
.card { border:1px solid #e5e7eb; border-radius:12px; padding:14px; background:#fff; }
.hint { background:#fff8e1; border:1px solid #ffecb3; padding:10px; border-radius:10px; }
</style>
""", unsafe_allow_html=True)

# ----------------------- Secrets / Keys --------------------
# Set these on Streamlit Cloud: GEMINI_API_KEY, GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
LOCAL_FILE = "data_history_us.json"

# ----------------------- Model Init ------------------------
if not GEMINI_KEY:
    st.error("GEMINI_API_KEY is missing in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ----------------------- GSheets (optional) ----------------
sheet = None
if SERVICE_ACCOUNT_JSON and SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Cloud history: connected", icon="✅")
    except Exception:
        st.toast("⚠️ Cloud history unavailable; using local file.", icon="⚠️")
else:
    st.toast("ℹ️ Cloud history not configured; using local file.", icon="ℹ️")

# ----------------------- Persistence -----------------------
def load_history():
    """Load from Google Sheets or local file."""
    if sheet:
        try:
            rows = sheet.get_all_records()
            out = []
            for r in rows:
                # If you ever store flattened rows only, skip JSON. Here we prefer a JSON column if exists.
                if "data_json" in r and r["data_json"]:
                    try:
                        out.append(json.loads(r["data_json"]))
                    except Exception:
                        pass
            return out
        except Exception:
            pass
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry: dict):
    """Append to Google Sheets or local file."""
    try:
        if sheet:
            # Flat row for quick analytics (keep order short & useful)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {})
            flat = [
                ts,
                fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                fa.get("mileage_mi",""), fa.get("price_usd",""),
                fa.get("zip",""), fa.get("vin",""), fa.get("seller_type",""),
                entry.get("deal_score",""), entry.get("classification",""),
                entry.get("risk_level",""), entry.get("otd_estimate_usd",""),
                entry.get("price_delta_vs_fair",""),
                entry.get("short_verdict","")
            ]
            # If your sheet expects headers, set them beforehand and use append_row accordingly.
            sheet.append_row(flat, value_input_option="USER_ENTERED")
        else:
            data = load_history()
            data.append(entry)
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"History save failed: {e}")

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

# ----------------------- Heuristics ------------------------
def guess_brand_model(text: str):
    if not text: return "", ""
    head = text.splitlines()[0].strip()
    toks = [t for t in re.split(r"[^\w\-]+", head) if t]
    if len(toks) >= 2:
        return toks[0], " ".join(toks[1:3])
    return "", ""

# ----------------------- Header ----------------------------
st.markdown("<span class='badge'>U.S. Edition</span>", unsafe_allow_html=True)
st.title("🚗 AI Deal Checker — Know if it’s a smart buy")
st.caption("LLM-powered deal analysis for U.S. used-car listings. (English • USD • miles)")

with st.expander("Disclaimer", expanded=True):
    st.markdown(
        "<div class='hint'>This app provides an AI-based opinion for informational purposes only. "
        "It is not financial, mechanical, or legal advice. Always verify with a VIN report (CarFax/AutoCheck) "
        "and a certified pre-purchase inspection.</div>", unsafe_allow_html=True
    )

# ----------------------- Inputs ----------------------------
ad_text = st.text_area("Paste the listing text:", height=220, placeholder="Copy-paste the Craigslist/CarGurus/Facebook listing here…")
uploaded_images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)

cols = st.columns(3)
with cols[0]:
    vin_input = st.text_input("VIN (optional)", placeholder="1HGCM82633A004352")
with cols[1]:
    zip_input = st.text_input("ZIP (optional)", placeholder="94103")
with cols[2]:
    seller_type = st.selectbox("Seller type", ["", "private", "dealer"])

st.caption("Tip: Include the asking price, miles, trim, and any claims like 'clean title', 'one owner', 'as-is', etc.")

# ----------------------- Core Prompt -----------------------
def build_us_prompt(ad: str, extra: str) -> str:
    return f"""
You are a U.S. used-car deal checker. Analyze if the following ad is a smart buy for a U.S. consumer.
Return clear, concise English. Use U.S. market logic.

— INPUT —
Ad text:
\"\"\"{ad}\"\"\"{extra}

— If images are provided, use them to identify trim/options/warnings (accident signs, mismatched panels, dealer lot photos).

— REQUIRED EXTRACTION (from ad or infer cautiously) —
Extract JSON fields:
from_ad = {{
  "brand": "", "model": "", "year": 0,
  "trim": "", "engine": "", "transmission": "",
  "drivetrain": "",  # FWD/AWD/RWD
  "mileage_mi": 0,
  "price_usd": 0,
  "vin": "", "zip": "", "seller_type": "",  # private/dealer
  "accident_claim": "",  # if stated
  "owners_claim": "",    # if stated
  "notes": ""            # notable claims: 'one owner', 'clean title', 'rebuilt title', 'warranty', 'as-is'
}}

— MARKET BENCHMARKS (reasoned; cite typical sources as context, no live calls) —
Estimate:
- fair_price_range_usd (for zip/region if known; otherwise national)
- demand_class (low/medium/high)
- reliability_band (per brand/model generation)
- known_issues (DSG/CVT gen issues, carbon buildup, EV battery degradation, etc.)
- safety_context (IIHS/NHTSA generation-level remarks if relevant)

— DEAL MATH —
Compute:
1) price_delta_vs_fair: ((ad_price - fair_mid) / fair_mid)
2) OTD_estimate_usd = price_usd + state_tax_est + dealer_fees_est + doc_fee_est
   * If seller_type == 'dealer': assume dealer_fees_est 400–1500 USD (explain range).
   * If 'private': dealer_fees_est = 0.
   * State tax: if zip known -> estimate 5–10%; else use 7% placeholder and state it’s an estimate.
3) 24-month TCO sketch: fuel/energy, insurance (low/avg/high), routine maintenance/tires/brakes.

— U.S. EDGE CASES (apply silently) —
- Title: “Clean”=neutral; “Salvage/Rebuilt”= −25 to −40 on score.
- Prior rental/fleet = −5 to −10 unless low miles/strong records.
- Missing VIN = −5; VIN present = recommend CarFax/AutoCheck.
- Price −30% below fair → check branded title/flood/auction; increase risk_level.
- Snow/Rust belt ZIPs → rust risk; Sun belt → UV/interior wear risk.
- EVs: consider pack degradation risk, DC fast-charge history, warranty remainder.
- High trims/options can justify +10–15% over fair mid if verified.
- Dealer “As-Is” → flag risk; private “As-Is” → normal.

— SCORING (0–100) —
Weights:
- Price vs fair (region) – 30%
- Vehicle condition & history signals – 25%
- Reliability & known issues – 20%
- Mileage vs year – 15%
- Seller transparency & title status – 10%

— OUTPUT JSON ONLY —
{{
  "from_ad": {{
    "brand":"", "model":"", "year":0, "trim":"", "engine":"", "transmission":"", "drivetrain":"", 
    "mileage_mi":0, "price_usd":0, "vin":"", "zip":"", "seller_type":"", "accident_claim":"", "owners_claim":"", "notes":""
  }},
  "benchmarks": {{
    "fair_price_range_usd":[0,0],
    "reliability_band":"", "known_issues":[], "demand_class":"", "safety_context":""
  }},
  "deal_score": 0,
  "classification": "",  # "Great deal" | "Fair" | "Overpriced" | "High risk"
  "risk_level": "",      # "low" | "medium" | "high"
  "price_delta_vs_fair": 0.0,
  "otd_estimate_usd": 0,
  "tco_24m_estimate_usd": {{ "fuel_energy":0, "insurance":"low/avg/high", "maintenance":0 }},
  "short_verdict": "",
  "key_reasons": [],
  "buyer_actions": [
    "Run CarFax/AutoCheck by VIN",
    "Schedule pre-purchase inspection (PPI)",
    "Verify title status at DMV",
    "Request service records"
  ]
}}
Return only valid JSON.
"""

# ----------------------- Action Button ---------------------
st.divider()
btn = st.button("Check the deal", type="primary", use_container_width=True)

# ----------------------- Main Flow -------------------------
if btn:
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    # Light pre-compute for stability messaging
    g_brand, g_model = guess_brand_model(ad_text)
    consistency_alert, prev_scores = check_consistency_us(g_brand, g_model)

    extra = "\n"
    if vin_input: extra += f"VIN: {vin_input}\n"
    if zip_input: extra += f"ZIP: {zip_input}\n"
    if seller_type: extra += f"Seller type: {seller_type}\n"
    if consistency_alert:
        extra += f"Historical note: prior scores for {g_brand} {g_model} varied: {prev_scores}\n"

    prompt = build_us_prompt(ad_text, extra)

    # Build multimodal inputs
    inputs = [prompt]
    for img in (uploaded_images or []):
        try:
            inputs.append(Image.open(img))
        except Exception:
            pass

    with st.spinner("Analyzing the deal with AI…"):
        try:
            resp = model.generate_content(inputs, request_options={"timeout": 120})
            txt = (resp.text or "").strip()
            fixed = repair_json(txt)  # tolerate trailing commas, etc.
            data = json.loads(fixed)

            # Optional consistency smoothing vs historical avg of same model
            avg = get_model_avg_us(data.get("from_ad",{}).get("brand",""), data.get("from_ad",{}).get("model",""))
            if isinstance(avg, (int,float)) and isinstance(data.get("deal_score"), (int,float)):
                diff = data["deal_score"] - avg
                if abs(diff) >= 15:
                    data["deal_score"] = int(data["deal_score"] - diff * 0.5)
                    sv = data.get("short_verdict","").strip()
                    sv += f" ⚙️ Score stabilized vs. historical mean ({avg})."
                    data["short_verdict"] = sv

            # Persist
            save_to_history(data)

            # ---------------- UI Output ----------------
            st.divider()
            score = int(data.get("deal_score", 0) or 0)
            color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 60 else "#dc2626"
            st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {score}/100</h2>", unsafe_allow_html=True)
            st.markdown(f"<h4 style='text-align:center;'>{data.get('classification','')}</h4>", unsafe_allow_html=True)

            fa = data.get("from_ad", {})
            bm = data.get("benchmarks", {}) or {}
            fair = bm.get("fair_price_range_usd", [0,0])
            otd = data.get("otd_estimate_usd", 0)
            risk = data.get("risk_level","").title()
            pdelta = data.get("price_delta_vs_fair", 0.0)

            colA, colB = st.columns(2)
            with colA:
                st.markdown("### Listing")
                st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','')}**")
                st.write(f"**Price:** ${fa.get('price_usd',0):,}  |  **Miles:** {fa.get('mileage_mi',0):,}")
                st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'}  |  **ZIP:** {fa.get('zip','') or 'n/a'}")
                st.write(f"**VIN:** {fa.get('vin','') or 'n/a'}")
            with colB:
                st.markdown("### Market")
                try:
                    st.write(f"**Fair range:** ${int(fair[0]):,}–${int(fair[1]):,}")
                except Exception:
                    st.write("**Fair range:** n/a")
                st.write(f"**OTD estimate:** ${int(otd):,}")
                st.write(f"**Risk level:** {risk or 'n/a'}")
                st.write(f"**Δ vs fair:** {round(pdelta*100,1)}%")

            st.divider()
            st.markdown("### Key reasons")
            for r in data.get("key_reasons", []):
                st.markdown(f"- {r}")

            if bm:
                st.markdown("### Reliability & Known Issues")
                if bm.get("reliability_band"):
                    st.write(f"**Reliability:** {bm['reliability_band']}")
                if bm.get("known_issues"):
                    for ki in bm["known_issues"]:
                        st.write(f"• {ki}")
                if bm.get("safety_context"):
                    st.write(f"**Safety:** {bm['safety_context']}")

            st.markdown("### 24-month TCO (sketch)")
            tco = data.get("tco_24m_estimate_usd", {}) or {}
            st.write(f"**Fuel/Energy:** ${int(tco.get('fuel_energy',0)):,}  |  "
                    f"**Insurance:** {tco.get('insurance','n/a')}  |  "
                    f"**Maintenance:** ${int(tco.get('maintenance',0)):,}")

            st.divider()
            st.markdown("### Short verdict")
            st.write(data.get("short_verdict",""))

            st.caption("© 2025 AI Deal Checker — U.S. Edition. AI opinion only; verify with CarFax/AutoCheck and PPI.")

        except Exception:
            st.error("Processing error.")
            st.code(traceback.format_exc())

# ----------------------- Footer ----------------------------
st.write("")
st.markdown("<div class='muted'>Built with Gemini 2.5 Flash. No live data calls are made; estimates are heuristic.</div>", unsafe_allow_html=True)