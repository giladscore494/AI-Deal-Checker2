# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.8 (Full Engine)
# Consumer-weighted scoring + strict rebuilt handling + memory + Sheets + full disclaimer
# Gemini 2.5 Pro | Mandatory Live Web Reasoning | On-screen human-readable explanations
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
APP_VERSION = "9.9.8"
st.set_page_config(page_title=f"AI Deal Checker (v{APP_VERSION})", page_icon="🚗", layout="centered")
st.title(f"🚗 AI Deal Checker - U.S. Edition (Pro) v{APP_VERSION}")
st.caption("Consumer-weighted scoring with strict rebuilt/salvage handling, memory stabilization and full disclaimer (Gemini 2.5 Pro).")

API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)
LOCAL_FILE = "deal_history_us.json"     # local memory ring
MEMORY_LIMIT = 600                      # keep last N records

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
# STYLE (clean UI)
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
</style>
""", unsafe_allow_html=True)

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
    m = re.search(r'(?i)(?:\\$?\\s*)(\\d{1,3}(?:,\\d{3})+|\\d{4,6})(?:\\s*usd)?', t)
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
    loc_sim = 1.0 if (ad_a.get("zip_or_state") == ad_b.get("zip_or_state")) else 0.7
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
            sheet.append_row([
                ts, fa.get("brand",""), fa.get("model",""), fa.get("year",""),
                entry.get("deal_score",""), roi.get("expected",""),
                entry.get("web_search_performed",""), entry.get("confidence_level",""),
                entry.get("unique_ad_id",""), gaps.get("median_clean",""), gaps.get("gap_pct","")
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            st.warning(f"Sheets write failed: {e}")

def classify_deal(score: float) -> str:
    if score >= 80:
        return "✅ Good deal — price and condition align well with market value."
    if score >= 60:
        return "⚖️ Fair deal — acceptable, but verify title and history before proceeding."
    return "❌ Bad deal — overpriced or carries significant risk factors."

# -------------------------------------------------------------
# PROMPT (Web Reasoning + Consumer Weights + Rebuilt Cap + Price Warning)
# -------------------------------------------------------------
def build_prompt(ad:str, extra:str, must_id:str, exact_prev:dict, similar_summ:list):
    exact_json = json.dumps(exact_prev or {}, ensure_ascii=False)
    similar_json = json.dumps(similar_summ or [], ensure_ascii=False)
    return f"""
You are a senior US used-car analyst (2023–2025). Web reasoning is REQUIRED.

Stages:
1) Extract listing facts: ask_price_usd, brand, model, year, trim, powertrain, miles, title_status, owners, accidents,
   options_value_usd, state_or_zip, days_on_market (if present).
2) Do live web lookups (REQUIRED) for the exact year/model:
   - Market comps (Cars.com, Autotrader, Edmunds) and CLEAN-title median.
   - Reliability & common issues (RepairPal/Consumer Reports style).
   - Typical annual maintenance cost.
   - Depreciation trend (24–36m).
   - Demand/DOM averages; brand/model value retention.
   Consider US realities (Rust Belt/flood, dealer vs private, mileage normalization).

Use prior only for stabilization (do NOT overfit):
- exact_prev (same listing id): weight ≤ 25% -> {exact_json}
- similar_previous (very similar ads): anchors only, weight ≤ 10% -> {similar_json}

Scoring rules for US buyers (consumer-weighted):
- Title condition (clean > rebuilt > salvage) ~20% weight; if 'rebuilt'/'salvage'/branded -> CAP deal_score at 75.
- Price vs CLEAN-title median ~25%.
- Mileage ~12% (log/normalized).
- Reliability & maintenance together ~18%.
- TCO (fuel + insurance + repairs) ~7%.
- Accidents + owners ~10%.
- Rust/flood zone ~4%.
- Demand/resale ~4%.

Return STRICT JSON only:
{{
  "from_ad": {{"brand":"","model":"","year":null,"vin":"","seller_type":""}},
  "ask_price_usd": 0,
  "vehicle_facts": {{
    "title_status":"unknown","accidents":0,"owners":1,"dealer_reputation":null,
    "rarity_index":0,"options_value_usd":0,"days_on_market":0,"state_or_zip":"","miles":null
  }},
  "market_refs": {{"median_clean":0,"gap_pct":0}},   // negative gap_pct means priced below clean-title market
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
  "score_explanation": "Plain-English rationale summarizing the score and ROI with sources (brief).",
  "listing_id_used": "{must_id}"
}}

LISTING (title + description):
\"\"\"{ad}\"\"\"
Extra:
{extra}

Hard constraints:
- Always perform web lookups and set web_search_performed=true; if not possible, list which sources failed but still estimate.
- Numeric fields must be numbers. deal_score: 0..100. ROI parts: -50..50.
- Add a short, plain-English note per component explaining the score source.
- If title_status is 'rebuilt', 'salvage' or any branded title: CAP deal_score ≤ 75 and include a clear warning in score_explanation.
- If market gap (gap_pct) ≤ -35: add a note recommending to verify insurance/accident history before purchase.
"""

# -------------------------------------------------------------
# UI
# -------------------------------------------------------------
ad = st.text_area("Paste the listing text:", height=230)
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
    parts = [{"text": build_prompt(ad, extra, must_id, exact_prev or {}, sims)}]
    for img in imgs or []:
        try:
            mime = "image/png" if "png" in img.type.lower() else "image/jpeg"
            parts.append({"mime_type": mime, "data": img.read()})
        except Exception:
            pass

    with st.spinner("Analyzing with Gemini 2.5 Pro (mandatory live web reasoning)…"):
        data = None
        raw_text = None
        for attempt in range(2):
            try:
                r = model.generate_content(parts, request_options={"timeout": 180})
                raw_text = getattr(r, "text", None)
                data = parse_json_safe(raw_text)
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
        memory_note = f"Applied memory: 15% exact ({exact_prev.get('unique_ad_id')}), 5% similar (n={len(sims)})."
    elif exact_prev:
        final_score = round(0.75*base_score + 0.25*float(exact_prev.get("deal_score", base_score)), 1)
        memory_note = f"Applied memory: 25% exact ({exact_prev.get('unique_ad_id')})."
    elif similar_avg is not None:
        final_score = round(0.90*base_score + 0.10*similar_avg, 1)
        memory_note = f"Applied memory: 10% similar (n={len(sims)})."
    else:
        memory_note = "No memory applied."

    prev_roi = (exact_prev or {}).get("roi_forecast_24m", {}) if exact_prev else None
    if exact_prev and sims and similar_avg is not None:
        roi["expected"] = round(0.80*roi["expected"] + 0.15*float((prev_roi or {}).get("expected", roi["expected"])) + 0.05*(similar_avg or roi["expected"]), 1)
    elif exact_prev:
        try_prev = float((prev_roi or {}).get("expected", roi.get("expected", 0)))
        roi["expected"] = round(0.75*roi.get("expected",0) + 0.25*try_prev, 1)
    elif similar_avg is not None:
        roi["expected"] = round(0.90*roi.get("expected",0) + 0.10*(similar_avg or 0), 1)

    # ---- Strict rebuilt/salvage handling (cap + stronger ROI penalty + warnings) ----
    warnings_ui = []
    branded = title_status in {"rebuilt","salvage","branded","flood","lemon"}
    if branded:
        # Cap at 75, plus nudge -5 to avoid ceiling inflation
        final_score = min(75.0, final_score - 5.0)
        warnings_ui.append({
            "type": "error",
            "text": ("⚠️ **Rebuilt / Branded Title detected** — "
                     "This vehicle has a branded title. Insurance and resale value may be significantly lower. "
                     "Verify repair quality and insurance history before purchase.")
        })
        # Harsher ROI: -15 points across scenarios, clamped
        for k in ["expected","optimistic","pessimistic"]:
            roi[k] = clip(roi.get(k, 0) - 15.0, -50, 50)

    # ---- Price anomaly warning (very low vs clean median) ----
    try:
        if gap_pct <= -35:
            warnings_ui.append({
                "type": "warning",
                "text": ("⚠️ Price significantly below clean-title market average — "
                         "recommend verifying insurance/accident history before purchase.")
            })
    except Exception:
        pass

    # ---- Persist record ----
    record = {
        "unique_ad_id": must_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": APP_VERSION,
        "raw_text": ad,
        "from_ad": data.get("from_ad", {}),
        "ask_price_usd": data.get("ask_price_usd", 0),
        "vehicle_facts": facts,
        "web_search_performed": bool(data.get("web_search_performed", False)),
        "confidence_level": float(data.get("confidence_level", 0.75)),
        "components": data.get("components", []),
        "deal_score": final_score,
        "deal_score_base": base_score,
        "roi_forecast_24m": roi,
        "score_explanation": data.get("score_explanation", ""),
        "memory_note": memory_note,
        "similar_used": sims[:3] if sims else [],
        "market_refs": market_refs
    }
    save_history(record)

    # ---------------------------------------------------------
    # RENDER
    # ---------------------------------------------------------
    color = "#16a34a" if final_score>=80 else ("#f59e0b" if final_score>=60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {final_score}/100</h2>", unsafe_allow_html=True)
    st.write(f"**Base (pre-memory):** {record['deal_score_base']}  |  **Memory:** {record['memory_note']}")

    # Classification
    st.info(classify_deal(final_score))

    # Disclaimer (primary block, always shown under score)
    st.markdown("""
    <div style='border:1px solid #f59e0b; border-radius:8px; padding:12px; background-color:#fff7ed; color:#92400e; font-size:0.9rem;'>
    <strong>Disclaimer:</strong> This analysis is for informational purposes only.
    It does not constitute professional advice or a purchase recommendation.
    Always have the vehicle inspected by a certified mechanic and verify its insurance and accident history before any transaction.
    </div>
    """, unsafe_allow_html=True)

    # Warnings (visual)
    for w in warnings_ui:
        if w["type"] == "error":
            st.error(w["text"])
        else:
            st.warning(w["text"])

    # Web lookup status + Confidence
    if record.get("web_search_performed"):
        st.success("🌐 Live web search performed (model).")
    else:
        st.warning("⚠️ Model could not confirm live web lookup; estimates may be less reliable.")
    meter("Confidence", float(record.get("confidence_level",0))*100, "%")

    # ROI
    st.subheader("ROI Forecast (24 months)")
    st.write(f"Expected {roi.get('expected',0)}% | Optimistic {roi.get('optimistic',0)}% | Pessimistic {roi.get('pessimistic',0)}%")

    # Summary
    if record.get("score_explanation"):
        st.subheader("Summary (plain English)")
        st.write(record["score_explanation"])

    # Components — human-readable (no raw debug)
    comps = record.get("components") or []
    if comps:
        st.subheader("Component breakdown")
        for c in comps:
            try:
                nm = str(c.get("name","")).strip()
                sc = clip(c.get("score",0), 0, 100)
                note = str(c.get("note","")).strip()
                st.write(f"• **{nm.capitalize()}** — {int(sc)}/100 → {note or 'No note provided.'}")
            except Exception:
                continue

    # Market refs
    if market_refs and (market_refs.get("median_clean") or market_refs.get("gap_pct") is not None):
        try:
            med_clean = int(market_refs.get('median_clean',0))
        except Exception:
            med_clean = market_refs.get('median_clean',0)
        gap_str = market_refs.get('gap_pct',0)
        st.caption(f"Market reference (clean-title median): ${med_clean} | Gap: {gap_str}%")

    # Similar anchors
    if record.get("similar_used"):
        st.subheader("Similar listings used (anchors)")
        for s in record["similar_used"]:
            st.write(f"- ID {s['id']} | prior score {s['score']} | sim={s['sim']} | when={s['when']}")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.caption("⚠️ Disclaimer: This report is not professional advice. Always perform a full mechanical inspection and insurance history check before purchase.")
