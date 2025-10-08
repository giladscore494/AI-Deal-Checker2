# -*- coding: utf-8 -*-
# ===========================================================
# AI Deal Checker – גרסה סופית ומצוחצחת (Gemini 2.5 Flash)
# כולל ניתוח עקביות, תיקון שוק, 18 מקרי קצה, ושמירה ב-Google Sheets
# ===========================================================

import streamlit as st
import google.generativeai as genai
import gspread, json, os, re, traceback
from google.oauth2.service_account import Credentials
from json_repair import repair_json
from PIL import Image
import pandas as pd
from datetime import datetime

# ---------- הגדרות כלליות ----------
st.set_page_config(page_title="AI Deal Checker 🚗", page_icon="🚗", layout="centered")

# ---------- חיבור ל-Gemini ----------
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")

# ---------- חיבור ל-Google Sheets ----------
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
sheet = None

try:
    creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    st.success("✅ זיכרון AI מחובר בהצלחה – נתונים נשמרים לענן.")
except Exception:
    st.warning("⚠️ לא ניתן להתחבר לזיכרון AI, תתבצע שמירה מקומית בלבד.")
    sheet = None

LOCAL_FILE = "data_history.json"

# ---------- פונקציות עזר ----------
def load_history():
    """קריאת נתונים מהשיטס או מקובץ מקומי."""
    if sheet:
        try:
            data = sheet.get_all_records()
            return [json.loads(row["data_json"]) for row in data if row.get("data_json")]
        except Exception:
            pass
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry):
    """שמירה לשיטס או fallback מקומי."""
    try:
        if sheet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            flat_entry = [
                timestamp,
                entry["from_ad"].get("brand", ""),
                entry["from_ad"].get("model", ""),
                entry["from_ad"].get("year", ""),
                entry.get("deal_score", ""),
                entry.get("classification", ""),
                entry["from_ad"].get("price_nis", ""),
                entry.get("short_verdict", "")
            ]
            sheet.append_row(flat_entry)
        else:
            data = load_history()
            data.append(entry)
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"שגיאה בשמירה: {e}")

def get_model_avg(brand, model_name):
    history = load_history()
    scores = [
        h.get("deal_score") for h in history
        if h.get("from_ad", {}).get("brand", "").lower() == brand.lower()
        and model_name.lower() in h.get("from_ad", {}).get("model", "").lower()
    ]
    scores = [s for s in scores if isinstance(s, (int, float))]
    return round(sum(scores)/len(scores), 2) if scores else None

def check_consistency(brand, model_name):
    history = load_history()
    relevant = [
        h.get("deal_score") for h in history
        if h.get("from_ad", {}).get("brand", "").lower() == brand.lower()
        and model_name.lower() in h.get("from_ad", {}).get("model", "").lower()
    ]
    relevant = [s for s in relevant if isinstance(s, (int, float))]
    if len(relevant) >= 3 and max(relevant) - min(relevant) >= 25:
        return True, relevant
    return False, relevant

def guess_brand_model(text):
    if not text:
        return "", ""
    tokens = [t for t in re.split(r"[^\w\u0590-\u05FF\-]+", text.splitlines()[0]) if t]
    if len(tokens) >= 2:
        return tokens[0], " ".join(tokens[1:3])
    return "", ""

# ---------- ממשק ----------
st.title("🚗 AI Deal Checker")
st.caption("בדוק כדאיות של מודעות רכב משומש עם ניתוח מבוסס בינה מלאכותית")

ad_text = st.text_area("📋 הדבק כאן את טקסט המודעה:", height=250)
uploaded_images = st.file_uploader("📸 העלה תמונות של הרכב (לא חובה):", type=["jpg","jpeg","png"], accept_multiple_files=True)

st.markdown(
    """
    <div style='background-color:#fff3cd; border-radius:10px; padding:10px; border:1px solid #ffeeba;'>
    ⚠️ <b>הבהרה:</b> ניתוח זה מבוסס בינה מלאכותית ואינו תחליף לבדיקה מקצועית. מומלץ לבצע בדיקת מוסך מלאה לפני רכישה.
    </div>
    """,
    unsafe_allow_html=True
)

# ---------- פעולה ----------
if st.button("חשב ציון כדאיות"):
    if not ad_text.strip():
        st.error("אנא הדבק טקסט של מודעה.")
        st.stop()

    with st.spinner("🔍 מחשב את כדאיות העסקה..."):
        try:
            g_brand, g_model = guess_brand_model(ad_text)
            consistency_alert, prev_scores = check_consistency(g_brand, g_model)
            stability_note = f"⚠️ זוהתה אי-עקביות בציונים קודמים לדגם זה ({prev_scores})." if consistency_alert else ""

            prompt = f"""
אתה אנליסט מומחה לשוק הרכב הישראלי. הערך את כדאיות העסקה למודעה הבאה.
{stability_note}

--- שלבי הניתוח ---
1. נתח את טקסט המודעה והפק נתונים: יצרן, דגם, שנה, מחיר, ק״מ, רמת גימור, מצב כללי.
2. מצא נתוני שוק ממוצעים לדגם זה (מחיר, אמינות, תחזוקה, תקלות ידועות, ביקוש).
3. השווה בין המידע מהמודעה לנתוני השוק.
4. השתמש ב־18 מקרי הקצה להימנעות משגיאות:
5.החזר תשובות רק בעברית רהוטה ומסודרת
   - ק״מ גבוה אך מטופל = תקין
   - מחיר נמוך עד 10% = לא חשוד
   - מחיר גבוה מוצדק אם רמה מאובזרת
   - רכב שטח = ק״מ גבוה נורמלי
   - רכב נישה – לא לפי ביקוש
   - ניסוח רשלני – לא שלילה
   - מודעה קצרה – השלם מידע
   - מחיר נמוך ב־50% = חשד השבתה
   - יבוא אישי – אל תשווה רגיל
   - אספנות – גיל לא חיסרון
   - סוחר – הפחת אמינות
   - “מחיר סופי” – לא בהכרח שלילי
   - צבע חריג – אם מקורי לא חיסרון
   - אין ק״מ – הערך ממוצע
   - אזור לח – סיכון חלודה
   - חסר מחיר – הערך לפי ממוצע
   - ליסינג שטופל – תקין
   - שפה זרה – הסתמך על נתונים בלבד

--- נוסחת הציון (0–100) ---
- מחיר מול שוק – 25%
- תחזוקה ומצב – 25%
- אמינות דגם – 20%
- גיל וק״מ – 15%
- אמינות מוכר – 10%
- ביקוש – 5%

ספק פלט JSON בלבד בפורמט:
{{
  "from_ad": {{"brand":"", "model":"", "year":0, "mileage_km":0, "price_nis":0}},
  "deal_score": 0,
  "classification": "",
  "short_verdict": "",
  "key_reasons": [],
  "user_info": {{"reliability_summary":"", "maintenance_tips":[], "common_faults":[], "market_context":""}}
}}

מודעה:
\"\"\"{ad_text}\"\"\"
"""

            inputs = [prompt]
            for img in uploaded_images or []:
                try:
                    inputs.append(Image.open(img))
                except Exception:
                    pass

            response = model.generate_content(inputs, request_options={"timeout": 120})
            fixed_json = repair_json(response.text or "")
            data = json.loads(fixed_json)

            avg = get_model_avg(data["from_ad"].get("brand",""), data["from_ad"].get("model",""))
            if avg:
                diff = data["deal_score"] - avg
                if abs(diff) >= 15:
                    data["deal_score"] = int(data["deal_score"] - diff * 0.5)
                    data["short_verdict"] += f" ⚙️ בוצע תיקון לפי ממוצע היסטורי ({avg})."

            save_to_history(data)

            # ---------- תצוגה ----------
            score = data.get("deal_score", 0)
            color = "#28a745" if score >= 80 else "#ffc107" if score >= 60 else "#dc3545"
            st.markdown(f"<h2 style='color:{color};text-align:center;'>🚦 ציון העסקה: {score}/100</h2>", unsafe_allow_html=True)
            st.markdown(f"<h4 style='text-align:center;'>{data.get('classification','')}</h4>", unsafe_allow_html=True)
            st.write("🧾", data.get("short_verdict",""))

            st.divider()
            st.subheader("💡 ערך מוסף למשתמש")
            info = data.get("user_info", {})
            if info.get("reliability_summary"):
                st.write(f"**אמינות הדגם:** {info['reliability_summary']}")
            if info.get("common_faults"):
                st.write("**תקלות נפוצות:**")
                for fault in info["common_faults"]:
                    st.write(f"• {fault}")
            if info.get("maintenance_tips"):
                st.write("**טיפים לתחזוקה:**")
                for tip in info["maintenance_tips"]:
                    st.write(f"• {tip}")
            if info.get("market_context"):
                st.write("**הקשר שוק כללי:**", info["market_context"])

            st.subheader("🎯 סיבות עיקריות לציון")
            for reason in data.get("key_reasons", []):
                st.markdown(f"- {reason}")

            st.caption("© 2025 Car Advisor AI – גרסה לומדת עם חיבור זיכרון חכם ל-Google Sheets")

        except Exception:
            st.error("❌ שגיאה בעיבוד הנתונים.")
            st.code(traceback.format_exc())
