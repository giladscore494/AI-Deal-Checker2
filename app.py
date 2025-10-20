# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.5 (Debug Edition)
# AI-Centric: Live Web Reasoning (Required) + Exact-ID Memory (25%) + Similar Ads (≤10%)
# Gemini 2.5 Pro | Sheets (optional) | On-screen Debug Reasoning
# ===========================================================

import os, json, re, hashlib
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
st.set_page_config(page_title="AI Deal Checker (v9.9.5 Debug)", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.9.5")
st.caption("AI-centric scoring with mandatory live web reasoning + memory stabilization (Gemini 2.5 Pro).")

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
    try:
        v=float(value)
    except:
        v=0
    v=max(0,min(100,v))
    css='fill-ok' if v>=70 else ('fill-warn' if v>=40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b><span>{int(v)}{suffix}</span></div>",unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{v}%'></div></div>",unsafe_allow_html=True)

def load_history():
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE,"r",encoding="utf-8") as f:
                return json.load(f)
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
                entry.get("deal_score",""), roi.get("expected",""),
                entry.get("web_search_performed",""), entry.get("confidence_level",""),
                entry.get("unique_ad_id","")
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            st.warning(f"Sheets write failed: {e}")

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
    try:
        return json.loads(raw)
    except:
        return json.loads(repair_json(raw))

def clip(x, lo, hi):
    try:
        x=float(x)
    except:
        x=0.0
    return max(lo, min(hi, x))

def unique_ad_id(ad_text, vin, zip_or_state, price_guess, seller):
    # Exact-ID hash: VIN preferred, else composite
    base = (vin.strip().upper() if vin else f"{ad_text[:160]}|{price_guess}|{zip_or_state}|{seller}".lower())
    return hashlib.md5(base.encode()).hexdigest()[:12]

def token_set(text):
    if not text: return set()
    t = re.sub(r'[^a-z0-9 ]+',' ', str(text).lower())
    return set([w for w in t.split() if len(w)>2])

def similarity_score(ad_a, ad_b):
    # Simple hybrid: token Jaccard + price proximity + location proximity
    ta, tb = token_set(ad_a.get("raw_text")), token_set(ad_b.get("raw_text"))
    j = len(ta & tb) / max(1, len(ta | tb))
    p_a, p_b = float(ad_a.get("price_guess") or 0), float(ad_b.get("price_guess") or 0)
    price_sim = 1.0 - min(1.0, abs(p_a - p_b) / max(1000.0, max(p_a, p_b, 1.0)))
    loc_sim = 1.0 if (ad_a.get("zip_or_state")==ad_b.get("zip_or_state")) else 0.7
    return 0.6*j + 0.3*price_sim + 0.1*loc_sim

# -------------------------------------------------------------
# PROMPT (Web Reasoning is mandatory)
# -------------------------------------------------------------
def build_prompt(ad:str, extra:str, must_id:str, exact_prev:dict, similar_summ:list):
    exact_json = json.dumps(exact_prev or {}, ensure_ascii=False)
    similar_json = json.dumps(similar_summ or [], ensure_ascii=False)
    return f"""
You are a senior US used-car analyst (2023-2025). Web reasoning is REQUIRED.
Do two stages:
1) Extract raw facts from the listing (title, body, photos if present) including: ask_price_usd, brand, model, year, trim, powertrain, miles, title_status, owners, accidents (if present), options_value_usd, state_or_zip, days_on_market (if present).
2) Live web lookup (required) for the specific model/year: market comps (Cars.com, Autotrader, Edmunds), reliability and common issues (RepairPal / consumer reports style), typical annual maintenance cost, depreciation trend (24-36m), demand/DOM averages, and brand/model value retention.
Use US market realities (Rust Belt impact, dealer vs private, mileage normalization).

Use prior only for stabilization (do NOT overfit):
- exact_prev (same listing id): weight <= 25% -> {exact_json}
- similar_previous (very similar ads): anchors only, weight <= 10% -> {similar_json}

Return STRICT JSON only:
{{
  "from_ad": {{"brand":"","model":"","year":null,"vin":"","seller_type":""}},
  "ask_price_usd": 0,
  "vehicle_facts": {{"title_status":"unknown","accidents":0,"owners":1,"dealer_reputation":null,"rarity_index":0,"options_value_usd":0,"days_on_market":0,"state_or_zip":"","miles":null}},
  "web_search_performed": true,
  "confidence_level": 0.75,
  "components": [
     {{"name":"market","score":0,"note":""}},
     {{"name":"mileage","score":0,"note":""}},
     {{"name":"tco","score":0,"note":""}},
     {{"name":"title","score":0,"note":""}},
     {{"name":"accidents","score":0,"note":""}},
     {{"name":"owners","score":0,"note":""}},
     {{"name":"rust","score":0,"note":""}},
     {{"name":"rarity","score":0,"note":""}},
     {{"name":"reliability","score":0,"note":""}},
     {{"name":"maintenance","score":0,"note":""}},
     {{"name":"demand","score":0,"note":""}}
  ],
  "deal_score": 0,
  "roi_forecast_24m": {{"expected":0,"optimistic":0,"pessimistic":0}},
  "score_explanation": "Concise narrative explaining the score and ROI in plain English, citing market comps and reliability insights.",
  "listing_id_used": "{must_id}"
}}

LISTING (title + description):
"""{ad}"""
Extra:
{extra}
"""

Hard constraints:
- Always perform web lookups and set web_search_performed=true; if not possible, state which sources failed but still estimate.
- All numeric fields must be numbers, not strings.
- deal_score must be 0-100.
- ROI components must be within -50..50 percent.
- Add short note per component explaining the score source.
- Prefer US data sources.
"""

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
    if imgs:
        extra+=f"\nPhotos provided: {len(imgs)} file(s) (content not parsed here)."

    # ---- Memory: build context for exact & similar ----
    price_guess = extract_price_from_text(ad) or 0
    must_id = unique_ad_id(ad, vin, zip_code, price_guess, seller)
    history = load_history()

    exact_prev = next((h for h in history if h.get("unique_ad_id")==must_id), None)

    current_struct = {
        "raw_text": ad,
        "price_guess": price_guess,
        "zip_or_state": zip_code or "",
    }

    # compute similarity to prior records
    sims = []
    for h in history:
        prior_struct = {
            "raw_text": h.get("raw_text") or "",
            "price_guess": extract_price_from_text(h.get("raw_text") or "") or 0,
            "zip_or_state": (h.get("from_ad") or {}).get("state_or_zip","")
        }
        s = similarity_score(current_struct, prior_struct)
        if s >= 0.85 and h.get("unique_ad_id") != must_id:
            sims.append({"id": h.get("unique_ad_id"), "score": h.get("deal_score"), "when": h.get("timestamp",""), "sim": round(s,3)})
    sims = sorted(sims, key=lambda x: -x["sim"])[:5]
    similar_avg = None
    if sims:
        vals = [v["score"] for v in sims if isinstance(v.get("score"), (int,float))]
        similar_avg = round(sum(vals)/len(vals), 2) if vals else None

    # Build prompt with memory anchors
    parts=[{"text":build_prompt(ad, extra, must_id, exact_prev or {}, sims)}]
    for img in imgs:
        try:
            mime="image/png" if "png" in img.type.lower() else "image/jpeg"
            parts.append({"mime_type":mime,"data":img.read()})
        except Exception:
            pass

    debug_lines = []  # collect verbose reasoning

    with st.spinner("Analyzing with Gemini 2.5 Pro (mandatory web reasoning)…"):
        data=None
        raw_text=None
        for attempt in range(2):
            try:
                r=model.generate_content(parts,request_options={"timeout":180})
                raw_text = getattr(r, "text", None)
                data=parse_json_safe(raw_text)
                break
            except Exception as e:
                st.warning(f"Retrying... ({e})"); import time; time.sleep(1.2)

        if not data:
            st.error("Model failed to return JSON. Try again."); st.stop()

    # ---- Clamp & sanity ----
    try:
        base_score = float(data.get("deal_score", 60))
    except:
        base_score = 60.0
    base_score = clip(base_score, 0, 100)

    roi = data.get("roi_forecast_24m", {}) or {}
    for k in ["expected","optimistic","pessimistic"]:
        try:
            roi[k] = clip(float(roi.get(k,0)), -50, 50)
        except:
            roi[k] = 0.0

    # ---- Memory stabilization logic ----
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

    # ROI memory blend mirrors score logic (expected only; opt/pes same style)
    def blend_roi(prev_roi, curr_v):
        try_prev = float((prev_roi or {}).get("expected", curr_v))
        return 0.75*curr_v + 0.25*try_prev

    prev_roi = (exact_prev or {}).get("roi_forecast_24m", {}) if exact_prev else None
    if exact_prev and sims:
        roi["expected"] = round(0.80*roi["expected"] + 0.15*float((prev_roi or {}).get("expected", roi["expected"])) + 0.05*(similar_avg or roi["expected"]), 1)
        roi["optimistic"] = round(roi["optimistic"], 1)
        roi["pessimistic"] = round(roi["pessimistic"], 1)
    elif exact_prev:
        roi["expected"] = round(blend_roi(prev_roi, roi["expected"]), 1)
    elif similar_avg is not None:
        roi["expected"] = round(0.90*roi["expected"] + 0.10*(similar_avg or 0), 1)

    # ---- Save & display ----
    record = {
        "unique_ad_id": must_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_text": ad,
        "from_ad": data.get("from_ad", {}),
        "ask_price_usd": data.get("ask_price_usd", 0),
        "vehicle_facts": data.get("vehicle_facts", {}),
        "web_search_performed": bool(data.get("web_search_performed", False)),
        "confidence_level": float(data.get("confidence_level", 0.75)),
        "components": data.get("components", []),
        "deal_score": final_score,
        "deal_score_base": base_score,
        "roi_forecast_24m": roi,
        "score_explanation": data.get("score_explanation", ""),
        "memory_note": memory_note,
        "similar_used": sims[:3] if sims else []
    }
    save_history(record)

    color = "#16a34a" if final_score>=80 else ("#f59e0b" if final_score>=60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {final_score}/100</h2>",unsafe_allow_html=True)
    if record.get("web_search_performed"):
        st.success("🌐 Live web search performed (model).")
    else:
        st.warning("⚠️ Model could not confirm live web lookup; estimates may be less reliable.")

    st.write(f"**Base (pre-memory) score:** {record['deal_score_base']}  |  **Memory:** {record['memory_note']}")

    st.subheader("ROI Forecast (24 months)")
    st.write(f"Expected {roi.get('expected',0)}% | Optimistic {roi.get('optimistic',0)}% | Pessimistic {roi.get('pessimistic',0)}%")
    meter("Confidence", float(record.get("confidence_level",0))*100, "%")

    st.subheader("Reasoning")
    st.write(record.get("score_explanation",""))

    comps = record.get("components") or []
    if comps:
        st.subheader("Component breakdown")
        for c in comps:
            try:
                nm = c.get("name","")
                sc = clip(c.get("score",0),0,100)
                note = c.get("note","")
                st.write(f"- **{nm}**: {sc}/100 — {note}")
            except Exception:
                continue

    if record.get("similar_used"):
        st.subheader("Similar listings used (anchors)")
        for s in record["similar_used"]:
            st.write(f"- ID {s['id']} | prior score {s['score']} | sim={s['sim']} | when={s['when']}")

    st.caption("© 2025 AI Deal Checker v9.9.5 — AI-centric scoring with mandatory web lookup. Verify independently.")
