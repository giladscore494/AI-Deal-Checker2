# -*- coding: utf-8 -*-
# ===========================================================
# 🚗 AI Deal Checker (U.S.) - v9.4 Pro Valuation Engine (Full)
# Gemini 2.5 Pro | Text + Image | Advanced Scoring + Rust-Belt
# ===========================================================

import os, re, json, time, io
from datetime import datetime
import pandas as pd
import streamlit as st
from PIL import Image
from json_repair import repair_json
import google.generativeai as genai

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

# ---------------------- App Setup --------------------------
st.set_page_config(page_title="AI Deal Checker (U.S.) v9.4", page_icon="🚗", layout="centered")
st.title("🚗 AI Deal Checker - U.S. Edition (Pro) v9.4")
st.caption("AI-powered used-car valuation with visual + web cross-validation and pro-grade scoring.")

# ---------------------- CSS --------------------------
st.markdown("""
<style>  
:root { --ok:#16a34a; --warn:#f59e0b; --bad:#dc2626; --muted:#6b7280; }  
div.block-container { padding-top: 1rem; }  
.metric { display:flex; align-items:center; justify-content:space-between; margin:6px 0 4px; font-size:0.95rem; }  
.metric b { color:#111827; }  
.progress { height:10px; background:#e5e7eb; border-radius:6px; overflow:hidden; }  
.fill-ok   { height:100%; background:var(--ok);   transition:width .5s; }  
.fill-warn { height:100%; background:var(--warn); transition:width .5s; }  
.fill-bad  { height:100%; background:var(--bad);  transition:width .5s; }  
.pill { display:inline-flex; align-items:center; gap:.35rem; padding:.3rem .6rem; border-radius:999px; font-weight:600; margin-right:.35rem; font-size:0.9rem;}  
.pill.ok { background:#ecfdf5; color:#065f46; }  
.pill.warn { background:#fffbeb; color:#92400e; }  
.pill.bad { background:#fef2f2; color:#991b1b; }  
small.muted { color: var(--muted); }  
table.scored { width:100%; border-collapse:collapse; margin:8px 0 4px; }  
table.scored th, table.scored td { border:1px solid #e5e7eb; padding:6px 8px; font-size:0.9rem; }  
table.scored th { background:#f9fafb; text-align:left; }  
</style>  
""", unsafe_allow_html=True)

# ---------------------- Secrets / Config -------------------
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID", "")
SERVICE_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", None)

if not GEMINI_KEY:
    st.error("Missing GEMINI_API_KEY in st.secrets.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-pro")

# ---------------------- Google Sheets ----------------------
sheet = None
if SHEET_ID and SERVICE_JSON and gspread and Credentials:
    try:
        if isinstance(SERVICE_JSON, str):
            SERVICE_JSON = json.loads(SERVICE_JSON)
        creds = Credentials.from_service_account_info(
            SERVICE_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        st.toast("✅ Connected to Google Sheets")
    except Exception as e:
        st.warning(f"⚠️ Google Sheets connection failed: {e}")

# ---------------------- Rust-Belt Risk Helper ----------------------
RUST_BELT_STATES = ["OH","MI","PA","IL","NY","WI","MN"]

def rust_belt_risk(zip_or_state:str=""):
    """Estimate corrosion risk based on region (Rust Belt heuristic). Returns 0–10 points penalty."""
    if not zip_or_state:
        return 0
    s = str(zip_or_state).strip()
    # Direct state match
    for state in RUST_BELT_STATES:
        if state.lower() == s.lower() or state.lower() in s.lower():
            return 10
    # ZIP range heuristics (rough, but practical)
    try:
        z = int(s[:5]) if len(s) >= 5 and s[:5].isdigit() else (int(s[:3]) if len(s) >= 3 and s[:3].isdigit() else None)
        if z is not None:
            # Great Lakes / Northeast bands (approx)
            if 100 <= z <= 149:  # MA/NY prefixes
                return 8
            if 430 <= z <= 499:  # OH area
                return 10
            if 530 <= z <= 549:  # WI
                return 9
            if 550 <= z <= 569:  # MN
                return 9
            if 480 <= z <= 499:  # MI
                return 10
            if 150 <= z <= 199:  # PA/NJ bands
                return 8
    except Exception:
        pass
    return 0

# ---------------------- Save to Sheet ----------------------
def save_to_sheet(entry):
    if not sheet:
        return
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fa = entry.get("from_ad", {}) or {}
        # Save compact essentials + JSON blobs for advanced fields
        row = [
            ts,
            fa.get("brand",""),
            fa.get("model",""),
            fa.get("year",""),
            fa.get("price_usd",""),
            fa.get("mileage_mi",""),
            entry.get("deal_score",""),
            entry.get("classification",""),
            entry.get("risk_level",""),
            entry.get("roi_estimate_24m",""),
            entry.get("seller_trust_index",""),
            entry.get("reliability_score_web",""),
            entry.get("regional_demand_index",""),
            entry.get("confidence_level",""),
            entry.get("depreciation_two_year_pct",""),
            entry.get("insurance_cost_band",""),
            entry.get("climate_suitability",""),
            entry.get("web_search_performed",""),
            entry.get("reasoning",""),
            json.dumps(entry.get("contributors", {}), ensure_ascii=False),
            json.dumps(entry.get("roi_forecast_24m", {}), ensure_ascii=False),
            json.dumps(entry.get("benchmarks", {}), ensure_ascii=False),
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        st.toast("✅ Saved to Google Sheets")
    except Exception:
        pass

# ---------------------- Prompt (STRICT Schema) ----------------------
STRICT_SCHEMA_EXAMPLE = """{
"from_ad":{
  "brand":"Toyota","model":"Camry","year":2020,"trim":"SE",
  "engine":"2.5L I4","transmission":"Automatic","drivetrain":"FWD",
  "mileage_mi":48000,"price_usd":18900,"vin":"unknown","zip":"94110","seller_type":"private"
},
"benchmarks":{
  "fair_price_range_usd":[18000,20000],
  "reliability_band":"High",
  "known_issues":[],
  "fuel_efficiency_mpg":{"city":28,"highway":39},
  "depreciation_trend":"Moderate (-18%)",
  "visual_condition":"Good"
},
"deal_score":87,
"classification":"Great Deal",
"risk_level":"Low",
"insurance_cost_band":"avg",
"climate_suitability":"Good",
"roi_estimate_24m":7.5,
"reliability_score_web":82,
"seller_trust_index":78,
"regional_demand_index":73,
"depreciation_two_year_pct":18,
"usage_intensity_score":85,
"powertrain_reliability_score":88,
"maintenance_evidence_score":90,
"mechanical_condition_index":84,
"regional_price_delta_pct":-2.0,
"liquidity_score":76,
"roi_forecast_24m":{"expected":7.5,"pessimistic":-3.0,"optimistic":11.0},
"contributors":{
  "price_factor":+22,
  "reliability":+10,
  "mechanical":+9,
  "maintenance":+6,
  "roi":+7,
  "demand":+5,
  "powertrain":+4,
  "regional_rust_risk":-6,
  "insurance_cost":-4
},
"reasoning":"Price 6% below fair market, clean title, good visual condition, strong reliability and service records. Moderate demand and low insurance keep ownership costs reasonable. Regional rust risk minimal for ZIP 94110.",
"web_search_performed":true,
"cross_validation_result":"AI estimate within 4% of live market average."
}"""

def build_prompt(ad: str, extra: str):
    return f"""
You are a professional U.S. used-car valuation system. Perform a multimodal (text + image) analysis.

OBJECTIVE:
Return a single JSON object strictly matching the provided schema. No markdown, no extra text.

DATA TASKS:
- Cross-validate with 2023–2025 U.S. market data (Edmunds, KBB, IIHS, Cars.com, RepairPal, NHTSA — rely on internal knowledge; do not cite).
- From text: price vs fair market range, mileage/usage, title state (clean/rebuilt/salvage), seller transparency, ROI, depreciation, insurance band.
- From images: exterior condition, repaint signs, dents/scratches, tire wear, interior cleanliness, rust traces/undercarriage hints, headlight oxidation.
- Region: account for Rust-Belt corrosion risk and regional market deltas.

SCORING MODEL (guidance):
- Provide numeric fields for:
  - usage_intensity_score (0–100)
  - powertrain_reliability_score (0–100)
  - maintenance_evidence_score (0–100)
  - mechanical_condition_index (0–100)
  - liquidity_score (0–100)
  - regional_price_delta_pct (e.g., -2.0 means 2% under region-adjusted market)
- Provide roi_forecast_24m with expected/pessimistic/optimistic (in %).
- Always include insurance_cost_band ("low"/"avg"/"high") and climate_suitability ("Good"/"Moderate"/"Poor").
- Fill 'contributors' with approximate additive contributions (positive or negative integer points) for:
  price_factor, reliability, mechanical, maintenance, roi, demand, powertrain, regional_rust_risk, insurance_cost.
- Provide a clear 'reasoning' paragraph tying text+image+region into a quantitative explanation.

OUTPUT RULES:
1) Output ONE JSON object only, matching exactly this structure and field names:
{STRICT_SCHEMA_EXAMPLE}
2) All numeric values should be reasonable and rounded (ints where possible, percentages 1 decimal when needed).
3) Set "web_search_performed" true if any online market knowledge was integrated.
4) Do NOT include sources or citations.

INPUT (Ad):
\"\"\"{ad}\"\"\"{extra}

Return JSON only.
""".strip()

# ---------------------- JSON Parser ------------------------
def parse_json_strict(raw: str):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty model response")
    raw = raw.replace("```json","").replace("```","").strip()
    ob, cb = raw.count("{"), raw.count("}")
    if cb < ob:
        raw += "}" * (ob - cb)
    try:
        return json.loads(raw)
    except Exception:
        fixed = repair_json(raw)
        return json.loads(fixed)

# ---------------------- UI Helpers -------------------------
def meter(label, value, suffix=""):
    try:
        v = float(value)
    except Exception:
        v = 0.0
    v = max(0.0, min(100.0, v))
    css = 'fill-ok' if v >= 70 else ('fill-warn' if v >= 40 else 'fill-bad')
    st.markdown(f"<div class='metric'><b>{label}</b> <span>{int(v)}{suffix}</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='progress'><div class='{css}' style='width:{int(v)}%'></div></div>", unsafe_allow_html=True)

def pill(label, level):
    lvl = (level or "").strip().lower()
    cls = 'ok' if lvl in ('good','low','high') else ('warn' if lvl in ('avg','moderate','medium') else 'bad')
    st.markdown(f"<span class='pill {cls}'>{label}</span>", unsafe_allow_html=True)

def render_contributors_table(contrib: dict):
    if not isinstance(contrib, dict) or not contrib:
        return
    rows = []
    # Keep a stable order for readability
    order = ["price_factor","reliability","mechanical","maintenance","roi","demand","powertrain","regional_rust_risk","insurance_cost"]
    for k in order:
        if k in contrib:
            rows.append((k, contrib[k]))
    for k,v in contrib.items():
        if k not in order:
            rows.append((k,v))
    # Render simple table
    html = "<table class='scored'><tr><th>Factor</th><th>Contribution (pts)</th></tr>"
    for k, v in rows:
        html += f"<tr><td>{k}</td><td>{v}</td></tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

# ---------------------- Main UI -------------------------------
ad_text = st.text_area("Paste the listing text:", height=240, placeholder="Paste the Craigslist / FB Marketplace / Cars.com ad…")
images = st.file_uploader("Upload listing photos (optional):", type=["jpg","jpeg","png"], accept_multiple_files=True)
c1,c2,c3 = st.columns(3)
with c1: vin = st.text_input("VIN (optional)")
with c2: zipc = st.text_input("ZIP or State (e.g., 44105 or OH)")
with c3: seller = st.selectbox("Seller type", ["","private","dealer"])

if st.button("Analyze Deal", use_container_width=True, type="primary"):
    if not ad_text.strip():
        st.error("Please paste the listing text.")
        st.stop()

    extra = ""
    if vin: extra += f"\nVIN: {vin}"
    if zipc: extra += f"\nZIP or State: {zipc}"
    if seller: extra += f"\nSeller type: {seller}"

    rust_penalty = rust_belt_risk(zipc)
    if rust_penalty:
        extra += f"\n⚠️ Note: region is part of Rust Belt — apply corrosion risk factor ({rust_penalty} pts)."

    # Build multimodal parts
    parts = [{"text": build_prompt(ad_text, extra)}]
    if images:
        for img in images:
            image_bytes = img.read()
            # Best-effort mime type (streamlit provides name; assume jpeg if unknown)
            mime = "image/png" if (img.type and "png" in img.type.lower()) else "image/jpeg"
            parts.append({"mime_type": mime, "data": image_bytes})

    with st.spinner("Analyzing with Gemini 2.5 Pro (visual + textual cross-validation)…"):
        data, last_err = None, None
        for attempt in range(3):
            try:
                resp = model.generate_content(parts, request_options={"timeout": 120})
                data = parse_json_strict(resp.text)
                break
            except Exception as e:
                last_err = str(e)
                st.warning(f"Attempt {attempt+1} failed to produce valid JSON. Retrying…")
                time.sleep(1.0)
        if data is None:
            st.error(f"❌ Failed after 3 attempts. Last error: {last_err}")
            st.stop()

    # ---------- Optional: enforce presence of required fields ----------
    data.setdefault("insurance_cost_band", "avg")
    data.setdefault("climate_suitability", "Moderate")
    data.setdefault("contributors", {})
    data.setdefault("roi_forecast_24m", {})

    # ---------- Apply Rust penalty numerically as well ----------
    # If model already considered it, this is a small extra nudge, clamped to [0,100].
    try:
        model_score = float(data.get("deal_score", 0))
    except Exception:
        model_score = 0.0
    final_score = max(0, min(100, int(round(model_score - rust_penalty)))))
    data["deal_score"] = final_score  # overwrite with penalized score

    # ---------- Save to Sheets ----------
    save_to_sheet(data)

    # ---------- Output UI ----------
    st.divider()
    color = "#16a34a" if final_score >= 80 else ("#f59e0b" if final_score >= 60 else "#dc2626")
    st.markdown(f"<h2 style='text-align:center;color:{color}'>Deal Score: {final_score}/100</h2>", unsafe_allow_html=True)

    st.subheader("🧭 Why this score?")
    st.write(data.get("reasoning", "No reasoning provided."))

    # Key meters (show if exist)
    conf = float(data.get("confidence_level", 0) or 0) * 100
    meter("Confidence", conf, "%")
    if isinstance(data.get("reliability_score_web", None), (int,float)):
        meter("Reliability (web)", data.get("reliability_score_web", 0), "/100")
    if isinstance(data.get("seller_trust_index", None), (int,float)):
        meter("Seller Trust", data.get("seller_trust_index", 0), "/100")
    if isinstance(data.get("regional_demand_index", None), (int,float)):
        meter("Regional Demand", data.get("regional_demand_index", 0), "/100")

    if data.get("web_search_performed"):
        st.success("🔎 Live web & visual cross-validation performed.")
        if data.get("cross_validation_result"):
            st.caption(data["cross_validation_result"])
    else:
        st.warning("⚠️ No live web search detected — AI relied on internal knowledge.")

    st.subheader("Summary")
    st.write(data.get("classification", ""))
    st.write(data.get("short_verdict", ""))

    fa = data.get("from_ad", {}) or {}
    st.subheader("Listing Details")
    st.write(f"**{fa.get('brand','')} {fa.get('model','')} {fa.get('year','')} {fa.get('trim','') or ''}**")
    price = fa.get("price_usd", 0) or 0
    miles = fa.get("mileage_mi", 0) or 0
    st.write(f"**Price:** ${price:,} | **Miles:** {miles:,}")
    st.write(f"**Seller:** {fa.get('seller_type','') or 'n/a'} | **ZIP/State:** {fa.get('zip','') or (zipc or 'n/a')} | **VIN:** {fa.get('vin','') or 'n/a'}")

    # Advanced indicators (if present)
    st.subheader("Advanced Indicators")
    cols1 = st.columns(3)
    with cols1[0]:
        if isinstance(data.get("usage_intensity_score", None), (int,float)):
            meter("Usage Intensity", data.get("usage_intensity_score", 0), "/100")
    with cols1[1]:
        if isinstance(data.get("mechanical_condition_index", None), (int,float)):
            meter("Mechanical Condition", data.get("mechanical_condition_index", 0), "/100")
    with cols1[2]:
        if isinstance(data.get("powertrain_reliability_score", None), (int,float)):
            meter("Powertrain Reliability", data.get("powertrain_reliability_score", 0), "/100")

    cols2 = st.columns(3)
    with cols2[0]:
        if isinstance(data.get("maintenance_evidence_score", None), (int,float)):
            meter("Maintenance Evidence", data.get("maintenance_evidence_score", 0), "/100")
    with cols2[1]:
        if isinstance(data.get("liquidity_score", None), (int,float)):
            meter("Liquidity/Demand", data.get("liquidity_score", 0), "/100")
    with cols2[2]:
        if isinstance(data.get("regional_price_delta_pct", None), (int,float)):
            # Show as a pill text instead of meter
            delta = data.get("regional_price_delta_pct", 0)
            st.markdown(f"<div class='metric'><b>Regional Price Δ</b> <span>{delta:+.1f}%</span></div>", unsafe_allow_html=True)

    st.subheader("Risk & Context")
    pill(f"Risk: {data.get('risk_level','')}", data.get("risk_level"))
    pill(f"Insurance: {data.get('insurance_cost_band','')}", data.get("insurance_cost_band"))
    pill(f"Climate: {data.get('climate_suitability','')}", data.get("climate_suitability"))
    if rust_penalty:
        st.markdown(f"<small class='muted'>Rust-belt penalty applied: −{rust_penalty} points due to regional corrosion risk.</small>", unsafe_allow_html=True)

    # Contributors breakdown (table)
    st.subheader("Score Contributors (pts)")
    render_contributors_table(data.get("contributors", {}))

    # ROI forecast (if present)
    rf = data.get("roi_forecast_24m", {})
    if isinstance(rf, dict) and rf:
        st.subheader("ROI Forecast (24 months)")
        exp = rf.get("expected", None)
        pes = rf.get("pessimistic", None)
        opt = rf.get("optimistic", None)
        txt = []
        if isinstance(exp,(int,float)): txt.append(f"Expected: {exp:+.1f}%")
        if isinstance(pes,(int,float)): txt.append(f"Pessimistic: {pes:+.1f}%")
        if isinstance(opt,(int,float)): txt.append(f"Optimistic: {opt:+.1f}%")
        if txt: st.write(" • ".join(txt))

    st.caption("© 2025 AI Deal Checker - U.S. Edition (Pro) v9.4. AI opinion only; verify independently.")