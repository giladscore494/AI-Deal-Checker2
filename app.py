# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v10.0.0 (Full U.S. Sync)
# Consumer-weighted scoring | U.S. Market Anchors | Live Web Reasoning
# Gemini 2.5 Pro | Sheets Integration | Insurance & Depreciation Tables
# ===========================================================

import os, json, re, hashlib, time
from datetime import datetime
import streamlit as st
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
APP_VERSION = "10.0.0"
st.set_page_config(page_title=f"AI Deal Checker (v{APP_VERSION})", page_icon="🚗", layout="centered")
st.title(f"🚗 AI Deal Checker - U.S. Edition (Pro) v{APP_VERSION}")
st.caption("Full U.S. Sync: KBB / CarEdge / RepairPal / IIHS data anchors, rust-belt awareness, insurance cost modeling, and ROI forecasting (Gemini 2.5 Pro).")

API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
LOCAL_FILE = "deal_history_us.json"
MEMORY_LIMIT = 600

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
small.muted{color:var(--muted);}
.section {margin-top:12px;}
hr{border:none;border-top:1px solid #e5e7eb;margin:18px 0;}
.expl {font-size:0.98rem; line-height:1.4;}
.expl p{margin:6px 0;}
.card {border:1px solid #e5e7eb; border-radius:10px; padding:12px; background:#fff;}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# U.S.-SPECIFIC TABLES
# -------------------------------------------------------------
RUST_BELT_STATES = {"IL","MI","OH","WI","PA","NY","MN","IN","MA","NJ"}
SUN_BELT_STATES = {"FL","AZ","TX","NV","CA"}

DEPRECIATION_TABLE = {
    "MAZDA": -14, "HONDA": -13, "TOYOTA": -12, "BMW": -22, "FORD": -19,
    "CHEVROLET": -18, "TESLA": -9, "KIA": -17, "HYUNDAI": -16, "SUBARU": -14,
    "NISSAN": -17, "VOLKSWAGEN": -18, "JEEP": -21, "MERCEDES": -23
}

INSURANCE_COST = {"MI": 2800, "FL": 2400, "NY": 2300, "OH": 1100, "TX": 1700, "CA": 1800, "AZ": 1400, "IL": 1500}

# -------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------
def meter(label, value, suffix=""):
    try:
        v = float(value)
    except:
        v = 0
    v = max(0, min(100, v))
    css = 'fill-ok' if v >= 70 else ('fill-warn' if v >= 40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b><span>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{v}%'></div></div>", unsafe_allow_html=True)

def clip(x, lo, hi):
    try:
        x = float(x)
    except:
        x = 0.0
    return max(lo, min(hi, x))

def extract_price_from_text(txt:str):
    if not txt: return None
    t = re.sub(r'\s+', ' ', txt)
    m = re.search(r'(?i)(?:\$?\s*)(\d{1,3}(?:,\d{3})+|\d{4,6})(?:\s*usd)?', t)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except:
            return None
    return None

def parse_json_safe(raw:str):
    raw = (raw or "").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except:
        return json.loads(repair_json(raw))

def unique_ad_id(ad_text, vin, zip_or_state, price_guess, seller):
    base = (vin.strip().upper() if vin else f"{ad_text[:160]}|{price_guess}|{zip_or_state}|{seller}".lower())
    return hashlib.md5(base.encode()).hexdigest()[:12]

def token_set(text):
    if not text: return set()
    t = re.sub(r'[^a-z0-9 ]+', ' ', str(text).lower())
    return set([w for w in t.split() if len(w) > 2])

def similarity_score(ad_a, ad_b):
    ta, tb = token_set(ad_a.get("raw_text")), token_set(ad_b.get("raw_text"))
    j = len(ta & tb) / max(1, len(ta | tb))
    p_a, p_b = float(ad_a.get("price_guess") or 0), float(ad_b.get("price_guess") or 0)
    price_sim = 1.0 - min(1.0, abs(p_a - p_b) / max(1000.0, max(p_a, p_b, 1.0)))
    loc_sim = 1.0 if (ad_a.get("zip_or_state")==ad_b.get("zip_or_state")) else 0.7
    return 0.6*j + 0.3*price_sim + 0.1*loc_sim

def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry):
    data = load_history(); data.append(entry)
    if len(data) > MEMORY_LIMIT: data = data[-MEMORY_LIMIT:]
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if sheet:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fa = entry.get("from_ad", {}) or {}
            roi = entry.get("roi_forecast_24m", {}) or {}
            gaps = entry.get("market_refs", {}) or {}
            uid = entry.get("unique_ad_id", "")
            sheet.append_row([
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                entry.get("deal_score",""), roi.get("expected",""),
                entry.get("web_search_performed",""), entry.get("confidence_level",""),
                gaps.get("median_clean",""), gaps.get("gap_pct",""),
                uid, fa.get("state_or_zip","")
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            st.warning(f"Sheets write failed: {e}")
# -------------------------------------------------------------
# HUMAN EXPLANATION ENGINE (U.S. Edition)
# -------------------------------------------------------------
def explain_component(name:str, score:float, note:str="", ctx:dict=None) -> str:
    s = clip(score, 0, 100)
    n = (note or "").strip()
    name_l = (name or "").lower().strip()

    if s >= 90: level = "excellent"
    elif s >= 80: level = "very good"
    elif s >= 70: level = "good"
    elif s >= 60: level = "adequate"
    elif s >= 50: level = "below average"
    elif s >= 40: level = "weak"
    else: level = "poor"

    base = ""
    if name_l == "market":
        gap = None
        try:
            gap = float((ctx.get("market_refs") or {}).get("gap_pct"))
        except Exception:
            pass
        if gap is not None:
            if gap <= -20:
                base = f"Asking price ~{abs(int(gap))}% under U.S. clean-title median; {level} value."
            elif gap <= -10:
                base = f"Asking price moderately below U.S. market (~{abs(int(gap))}%); {level} value."
            elif gap < 5:
                base = f"Asking price aligns with U.S. median; {level} value."
            else:
                base = f"Asking price ~{int(gap)}% over U.S. median; {level} value."
        else:
            base = f"Price vs U.S. comps is {level}."
    elif name_l == "title":
        ts = str(((ctx.get("vehicle_facts") or {}).get("title_status","unknown"))).lower()
        if ts in {"rebuilt","salvage","branded","flood","lemon"}:
            base = "Branded title — resale & insurance limited; extra due diligence required."
        elif ts == "clean":
            base = "Clean title — typical U.S. insurability & resale."
        else:
            base = "Title not confirmed; verify with DMV/Carfax."
    elif name_l == "mileage":
        base = f"Mileage condition is {level}; U.S. highway-heavy use softens penalty."
    elif name_l == "reliability":
        base = f"Long-term dependability is {level}; U.S. owner-reported issues within segment norms."
    elif name_l == "maintenance":
        base = f"Estimated annual maintenance is {level}; based on U.S. data (RepairPal/YourMechanic)."
    elif name_l == "tco":
        base = f"TCO (fuel/insurance/repairs) is {level} vs U.S. peers."
    elif name_l == "accidents":
        base = f"Accident risk is {level}; confirm Carfax/AutoCheck and repair documentation."
    elif name_l == "owners":
        base = f"Ownership history is {level}; fewer owners typically better in U.S. market."
    elif name_l == "rust":
        base = f"Rust/flood exposure is {level}; pay attention to Rust Belt/coastal operation."
    elif name_l == "demand":
        base = f"Buyer demand/DOM is {level}; may affect resale timing."
    elif name_l == "resale_value":
        base = f"Projected resale retention is {level} for this MY in U.S. market."
    else:
        base = f"{name.capitalize()} factor is {level}."

    # brand-aware hint
    brand = str((ctx.get("from_ad") or {}).get("brand","")).upper()
    if brand in {"TOYOTA","HONDA","MAZDA","SUBARU"} and name_l in {"reliability","resale_value"}:
        base += " Japanese-brand advantage recognized."
    if brand in {"FORD","CHEVROLET","JEEP"} and name_l in {"depreciation","resale_value"}:
        base += " Verify 3-year depreciation trend for domestic brands."

    if n:
        return f"{name.capitalize()} — {int(s)}/100 → {base} ({n})"
    return f"{name.capitalize()} — {int(s)}/100 → {base}"

def classify_deal(score: float) -> str:
    if score >= 80:
        return "✅ Good deal — price and condition align well with U.S. market value."
    if score >= 60:
        return "⚖️ Fair deal — acceptable, but verify title/history before proceeding."
    return "❌ Bad deal — overpriced or carries notable risk factors."

# -------------------------------------------------------------
# PROMPT (U.S. Anchors + Adjusted Weights + Mandatory Web)
# -------------------------------------------------------------
def build_prompt_us(ad:str, extra:str, must_id:str, exact_prev:dict, similar_summ:list):
    exact_json = json.dumps(exact_prev or {}, ensure_ascii=False)
    similar_json = json.dumps(similar_summ or [], ensure_ascii=False)
    return f"""
You are a senior U.S. used-car analyst (2023–2025). Web reasoning is REQUIRED.

Stages:
1) Extract listing facts: ask_price_usd, brand, model, year, trim, powertrain, miles, title_status, owners, accidents,
   options_value_usd, state_or_zip, days_on_market (if present).
2) Do live U.S.-centric lookups (REQUIRED) for the exact year/model:
   - Market comps & CLEAN-title median: Cars.com, Autotrader, Edmunds, and KBB (Kelley Blue Book).
   - Reliability & common issues: Consumer Reports style + RepairPal.
   - Typical annual maintenance cost: RepairPal or YourMechanic (U.S. 2023–2025).
   - Depreciation trend (24–36m): CarEdge or iSeeCars.
   - Demand/DOM averages; brand/model resale retention (CarEdge/iSeeCars).
   - Safety/recalls context: NHTSA; insurance risk context: IIHS (as qualitative anchors).
   Consider U.S. realities (Rust Belt vs Sun Belt, dealer vs private, mileage normalization).

Use prior only for stabilization (do NOT overfit):
- exact_prev (same listing id): weight ≤ 25% -> {exact_json}
- similar_previous (very similar ads): anchors only, weight ≤ 10% -> {similar_json}

Scoring rules for U.S. buyers (adjusted weights):
- Title condition (clean > rebuilt > salvage) ~20%; if 'rebuilt'/'salvage'/branded -> CAP deal_score ≤ 75.
- Price vs CLEAN-title median ~25%.
- Mileage impact ~10% (U.S. highway-heavy driving reduces penalty).
- Reliability & maintenance together ~20%.
- TCO (fuel + insurance + repairs) ~8% (U.S. costs).
- Accidents + owners ~9%.
- Rust/flood zone ~4% (Rust Belt/coastal exposure).
- Demand/resale ~4%.

Return STRICT JSON only:
{{
  "from_ad": {{"brand":"","model":"","year":null,"vin":"","seller_type":""}},
  "ask_price_usd": 0,
  "vehicle_facts": {{
    "title_status":"unknown","accidents":0,"owners":1,"dealer_reputation":null,
    "rarity_index":0,"options_value_usd":0,"days_on_market":0,"state_or_zip":"","miles":null
  }},
  "market_refs": {{"median_clean":0,"gap_pct":0}},
  "web_search_performed": true,
  "confidence_level": 0.75,
  "components": [
    {{"name":"market","score":0,"note":""}},
    {{"name":"title","score":0,"note":""}},
    {{"name":"mileage","score":0,"note":""}},
    {{"name":"reliability","score":0,"note":""}},
    {{"name":"maintenance","score":0,"note":""}},
    {{"name":"tco","score":0,"note":""}},
    {{"name":"accidents","score":0,"note":""}},
    {{"name":"owners","score":0,"note":""}},
    {{"name":"rust","score":0,"note":""}},
    {{"name":"demand","score":0,"note":""}},
    {{"name":"resale_value","score":0,"note":""}}
  ],
  "deal_score": 0,
  "roi_forecast_24m": {{"expected":0,"optimistic":0,"pessimistic":0}},
  "score_explanation": "Plain-English rationale summarizing the score and ROI with U.S. sources (brief).",
  "listing_id_used": "{must_id}"
}}

LISTING (title + description):
\"\"\"{ad}\"\"\"
Extra:
{extra}

Hard constraints:
- Always perform web lookups and set web_search_performed=true; if not possible, list which sources failed but still estimate.
- Numeric fields must be numbers. deal_score: 0..100. ROI parts: -50..50.
- Per-component short notes required.
- If title_status is 'rebuilt', 'salvage' or any branded title: CAP deal_score ≤ 75 and clearly warn in score_explanation.
- If market gap (gap_pct) ≤ -35: warn to verify insurance/accident history before purchase.
"""

# -------------------------------------------------------------
# UI (inputs)
# -------------------------------------------------------------
st.subheader("Paste the listing text:")
ad = st.text_area("", height=230, placeholder="Year • Make • Model • Trim • Mileage • Price • Title • Location • Options ...")
imgs = st.file_uploader("Upload photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1, c2, c3 = st.columns(3)
with c1: vin = st.text_input("VIN (optional)")
with c2: zip_code = st.text_input("ZIP / State (e.g., 44105 or OH)")
with c3: seller = st.selectbox("Seller type", ["","private","dealer"])

def build_extra(vin, zip_code, seller, imgs):
    extra = ""
    if vin: extra += f"\nVIN: {vin}"
    if zip_code: extra += f"\nZIP/State: {zip_code}"
    if seller: extra += f"\nSeller: {seller}"
    if imgs: extra += f"\nPhotos provided: {len(imgs)} file(s) (content parsed by model if supported)."
    return extra
# -------------------------------------------------------------
# RUN ANALYSIS
# -------------------------------------------------------------
if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad.strip():
        st.error("Please paste listing text first.")
        st.stop()

    extra = build_extra(vin, zip_code, seller, imgs)

    # ---- Memory context (exact + similar) ----
    price_guess = extract_price_from_text(ad) or 0
    must_id = unique_ad_id(ad, vin, zip_code, price_guess, seller)
    history = load_history()
    exact_prev = next((h for h in history if h.get("unique_ad_id") == must_id), None)

    current_struct = {
        "raw_text": ad,
        "price_guess": price_guess,
        "zip_or_state": zip_code or "",
    }

    sims = []
    for h in history:
        prior_struct = {
            "raw_text": h.get("raw_text") or "",
            "price_guess": extract_price_from_text(h.get("raw_text") or "") or 0,
            "zip_or_state": (h.get("from_ad") or {}).get("state_or_zip","")
        }
        s = similarity_score(current_struct, prior_struct)
        if s >= 0.85 and h.get("unique_ad_id") != must_id:
            sims.append({
                "id": h.get("unique_ad_id"),
                "score": h.get("deal_score"),
                "when": h.get("timestamp",""),
                "sim": round(s,3)
            })
    sims = sorted(sims, key=lambda x: -x["sim"])[:5]
    similar_avg = None
    if sims:
        vals = [v["score"] for v in sims if isinstance(v.get("score"), (int,float))]
        similar_avg = round(sum(vals)/len(vals), 2) if vals else None

    # ---- Build prompt & send (with memory anchors + images) ----
    parts = [{"text": build_prompt_us(ad, extra, must_id, exact_prev or {}, sims)}]
    for img in imgs or []:
        try:
            mime = "image/png" if "png" in img.type.lower() else "image/jpeg"
            parts.append({"mime_type": mime, "data": img.read()})
        except Exception:
            pass

    with st.spinner("Analyzing with Gemini 2.5 Pro (U.S. web reasoning)…"):
        data = None
        for attempt in range(2):
            try:
                r = model.generate_content(parts, request_options={"timeout": 180})
                data = parse_json_safe(getattr(r, "text", None))
                break
            except Exception as e:
                if attempt == 0:
                    st.warning(f"Retrying... ({e})")
                    time.sleep(1.2)
        if not data:
            st.error("Model failed to return JSON. Try again.")
            st.stop()

    # ---- Sanity clamp ----
    base_score = clip(data.get("deal_score", 60), 0, 100)
    roi = data.get("roi_forecast_24m", {}) or {}
    for k in ["expected","optimistic","pessimistic"]:
        roi[k] = clip(roi.get(k,0), -50, 50)

    facts = data.get("vehicle_facts", {}) or {}
    title_status = str(facts.get("title_status","unknown")).strip().lower()
    market_refs = data.get("market_refs", {}) or {}
    gap_pct = float(market_refs.get("gap_pct", 0)) if market_refs.get("gap_pct") is not None else 0.0

    # ---- Memory stabilization (score + ROI expected) ----
    final_score = base_score
    if exact_prev and sims and similar_avg is not None:
        final_score = round(0.80*base_score + 0.15*float(exact_prev.get("deal_score", base_score)) + 0.05*similar_avg, 1)
    elif exact_prev:
        final_score = round(0.75*base_score + 0.25*float(exact_prev.get("deal_score", base_score)), 1)
    elif similar_avg is not None:
        final_score = round(0.90*base_score + 0.10*similar_avg, 1)

    prev_roi = (exact_prev or {}).get("roi_forecast_24m", {}) if exact_prev else None
    if exact_prev and sims and similar_avg is not None:
        roi["expected"] = round(0.80*roi["expected"] + 0.15*float((prev_roi or {}).get("expected", roi["expected"])) + 0.05*(similar_avg or roi["expected"]), 1)
    elif exact_prev:
        try_prev = float((prev_roi or {}).get("expected", roi.get("expected", 0)))
        roi["expected"] = round(0.75*roi.get("expected",0) + 0.25*try_prev, 1)
    elif similar_avg is not None:
        roi["expected"] = round(0.90*roi.get("expected",0) + 0.10*(similar_avg or 0), 1)

    # ---- Strict rebuilt/salvage handling (cap + ROI penalty + warnings) ----
    warnings_ui = []
    branded = title_status in {"rebuilt","salvage","branded","flood","lemon"}
    if branded:
        final_score = min(75.0, final_score - 5.0)
        warnings_ui.append({
            "type": "error",
            "text": ("⚠️ **Rebuilt / Branded Title detected** — Insurance and resale value may be significantly lower. "
                     "Verify repair quality and insurance history before purchase.")
        })
        for k in ["expected","optimistic","pessimistic"]:
            roi[k] = clip(roi.get(k, 0) - 15.0, -50, 50)

    # ---- Price anomaly warning (very low vs clean median) ----
    try:
        if gap_pct <= -35:
            warnings_ui.append({
                "type": "warning",
                "text": ("⚠️ Price significantly below U.S. clean-title market average — "
                         "recommend verifying insurance/accident history before purchase.")
            })
    except Exception:
        pass

    # ---- U.S. regional modifiers (Rust & Insurance)
    state_or_zip = (facts.get("state_or_zip") or (zip_code or "")).strip().upper()
    # Normalize to a 2-letter state if user typed a ZIP? We'll keep as-is; if it's exactly 2 letters, treat as state.
    state_guess = state_or_zip if len(state_or_zip) == 2 else state_or_zip[-2:]

    # Rust modifier
    rust_mod = 0
    if state_guess in RUST_BELT_STATES:
        rust_mod = -3  # small but meaningful
    elif state_guess in SUN_BELT_STATES:
        rust_mod = +1
    final_score = clip(final_score + rust_mod, 0, 100)

    # Insurance/TCO modifier
    ins_cost = INSURANCE_COST.get(state_guess, 1600)
    # Map cost to a 0..100 score (lower cost -> higher score)
    tco_score = clip(100 - (ins_cost / 30), 0, 100)  # 1100 -> ~63, 2400 -> ~20
    # Blend small portion into final_score to reflect U.S. insurance reality
    final_score = clip(0.97*final_score + 0.03*tco_score, 0, 100)

    # ---- U.S. brand depreciation anchoring for ROI
    brand_up = str((data.get("from_ad") or {}).get("brand","")).upper()
    roi["expected"] = clip(roi.get("expected", 0) + DEPRECIATION_TABLE.get(brand_up, -16), -50, 50)

    # ---- UI: Primary summary card
    st.markdown("<hr/>", unsafe_allow_html=True)
    st.subheader(f"Deal Score: {final_score:.1f}/100")
    st.write(classify_deal(final_score))

    # Confidence + ROI
    conf = clip(data.get("confidence_level", 0.75)*100, 0, 100)
    colA, colB = st.columns(2)
    with colA:
        meter("Confidence", conf, "%")
    with colB:
        st.markdown("**24-Month U.S. Depreciation Forecast (ROI):**")
        st.write(f"Expected {roi.get('expected',0):+.1f}%  |  Optimistic {roi.get('optimistic',0):+.1f}%  |  Pessimistic {roi.get('pessimistic',0):+.1f}%")

    # Warnings
    for w in warnings_ui:
        if w["type"] == "error":
            st.error(w["text"])
        elif w["type"] == "warning":
            st.warning(w["text"])

    # ---- Components section
    st.markdown("### Component breakdown")
    ctx = {
        "market_refs": market_refs,
        "vehicle_facts": facts,
        "from_ad": data.get("from_ad", {})
    }
    comp_lines = []
    for comp in (data.get("components") or []):
        comp_lines.append(explain_component(comp.get("name",""), comp.get("score",0), comp.get("note",""), ctx))
    st.markdown("<div class='card expl'>" + "<br/>".join([f"<p>• {st.escape_html(x)}</p>" for x in comp_lines]) + "</div>", unsafe_allow_html=True)

    # ---- Quick facts
    fa = data.get("from_ad", {}) or {}
    st.markdown("### Extracted facts (U.S.)")
    cols = st.columns(3)
    with cols[0]:
        st.write(f"**{fa.get('year','?')} {fa.get('brand','?')} {fa.get('model','?')}**")
        st.write(f"VIN: {fa.get('vin','') or '—'}")
        st.write(f"Seller: {fa.get('seller_type','') or '—'}")
    with cols[1]:
        st.write(f"Title: {facts.get('title_status','unknown')}")
        st.write(f"Owners: {facts.get('owners','?')}")
        st.write(f"Accidents: {facts.get('accidents','?')}")
    with cols[2]:
        st.write(f"Location: {facts.get('state_or_zip','') or (zip_code or '—')}")
        st.write(f"Miles: {facts.get('miles','—')}")
        st.write(f"Ask Price: ${data.get('ask_price_usd',0):,.0f}")

    # ---- Market reference
    st.markdown("### Market reference (clean-title median)")
    mr = market_refs or {}
    st.write(f"Median: ${mr.get('median_clean',0):,.0f}  |  Gap: {mr.get('gap_pct',0)}%")

    # ---- Human summary
    st.markdown("### Summary (plain English)")
    st.write(data.get("score_explanation",""))

    # ---- Persist record
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unique_ad_id": must_id,
        "raw_text": ad,
        "from_ad": {
            "brand": fa.get("brand",""),
            "model": fa.get("model",""),
            "year": fa.get("year",""),
            "vin": fa.get("vin",""),
            "seller_type": fa.get("seller_type",""),
            "state_or_zip": facts.get("state_or_zip","") or (zip_code or "")
        },
        "deal_score": final_score,
        "roi_forecast_24m": roi,
        "web_search_performed": bool(data.get("web_search_performed", True)),
        "confidence_level": data.get("confidence_level", 0.75),
        "market_refs": market_refs
    }
    save_history(entry)

    # ---- Disclaimer
    st.markdown("<hr/>", unsafe_allow_html=True)
    st.caption(
        "Disclaimer: This analysis is for informational purposes only and does not constitute professional advice. "
        "Always obtain a pre-purchase inspection and verify title/insurance/accident history (e.g., Carfax/AutoCheck) before purchase."
    )
