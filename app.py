# -*- coding: utf-8 -*-
# ===========================================================
# AI-Deal-Checker – גרסה סופית עם דיבאג קשיח ל-Google Sheets
# כולל פרומפט מלא, 18 מקרי קצה, גרף מגמה, ותיקון שוק
# ===========================================================

import streamlit as st
import google.generativeai as genai
import gspread, json, re, traceback, os
from google.oauth2.service_account import Credentials
from json_repair import repair_json
from PIL import Image
import pandas as pd
from datetime import datetime

# ---------- הגדרות כלליות ----------
st.set_page_config(page_title="AI Deal Checker 🚗", page_icon="🚗", layout="centered")

# ---------- חיבור למודל ----------
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")

# ---------- חיבור ל-Google Sheets עם דיבאג קשיח ----------
SHEET_ID = st.secrets.get("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_JSON = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
sheet = None

st.write("🔍 מתחיל בדיקת חיבור ל-Google Sheets...")

try:
    if not SHEET_ID:
        raise ValueError("❌ חסר GOOGLE_SHEET_ID ב-secrets.toml")
    if not SERVICE_ACCOUNT_JSON:
        raise ValueError("❌ חסר GOOGLE_SERVICE_ACCOUNT_JSON ב-secrets.toml")

    creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    client = gspread.authorize(creds)

    st.write(f"📄 מנסה לפתוח את הגיליון לפי ה-ID: {SHEET_ID}")
    sheet = client.open_by_key(SHEET_ID).sheet1

    st.success("✅ התחברות ל-Google Sheets הצליחה!")

except gspread.exceptions.APIError as api_err:
    st.error("❌ שגיאת API מגוגל:")
    try:
        err_json = api_err.response.json()
        st.code(json.dumps(err_json, indent=2, ensure_ascii=False))
    except Exception:
        st.code(str(api_err))
    sheet = None

except gspread.exceptions.SpreadsheetNotFound as nf_err:
    st.error("❌ SpreadsheetNotFound – כנראה שה־Service Account לא שותף לקובץ או ה-ID שגוי.")
    st.code(str(nf_err))
    sheet = None

except Exception as e:
    st.error("❌ שגיאה כללית בעת ניסיון להתחבר ל-Google Sheets:")
    st.code(traceback.format_exc())
    sheet = None

LOCAL_FILE = "data_history.json"

# ---------- פונקציות עזר ----------
def load_history():
    if sheet:
        try:
            data = sheet.get_all_records()
            return [json.loads(row["data_json"]) for row in data if row.get("data_json")]
        except Exception as e:
            st.warning(f"שגיאה בקריאת שיטס: {e}")
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry):
    try:
        if sheet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([timestamp, json.dumps(entry, ensure_ascii=False)])
            st.success("✅ השמירה ל-Google Sheets הצליחה!")
        else:
            data = load_history()
            data.append(entry)
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            st.info("💾 נשמר לקובץ מקומי (Fallback).")
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
    if len(relevant) >= 3:
        diff = max(relevant) - min(relevant)
        if diff >= 25:
            return True, relevant
    return False, relevant

def guess_brand_model(text):
    if not text:
        return "", ""
    line = text.splitlines()[0].strip()
    tokens = [t for t in re.split(r"[^\w\u0590-\u05FF\-]+", line) if t]
    if len(tokens) >= 2:
        return tokens[0], " ".join(tokens[1:3])
    return "", ""

# ---------- ממשק ----------
st.title("🚗 AI Deal Checker – גרסה סופית ולומדת")
st.markdown("""
<b>בדוק כדאיות עסקה לרכב משומש</b><br>
העתק את טקסט המודעה (כולל מחיר, שנה, ק״מ וכו׳) והעלה תמונות אם יש.
""", unsafe_allow_html=True)

ad_text = st.text_area("📋 הדבק כאן את טקסט המודעה:", height=250)
uploaded_images = st.file_uploader("📸 העלה תמונות של הרכב:", type=["jpg","jpeg","png"], accept_multiple_files=True)

st.markdown("""
<div style='background-color:#fff3cd; border-radius:10px; padding:10px; border:1px solid #ffeeba;'>
⚠️ <b>אזהרה:</b> הניתוח מבוסס על בינה מלאכותית ואינו תחליף לבדיקה מקצועית.<br>
מומלץ לוודא היסטוריית טיפולים, דו״ח ביטוח ותקינות מלאה.
</div>
""", unsafe_allow_html=True)

# ---------- פעולה ----------
if st.button("חשב ציון כדאיות"):
    if not ad_text.strip():
        st.error("אנא הדבק טקסט של מודעה או העלה תמונות.")
        st.stop()

    with st.spinner("🔍 מבצע הצלבה חכמה בין נתוני המודעה לנתוני השוק..."):
        try:
            g_brand, g_model = guess_brand_model(ad_text)
            consistency_alert, prev_scores = check_consistency(g_brand, g_model)
            stability_note = ""
            if consistency_alert:
                stability_note = f"⚠️ זוהתה אי-עקביות בין ציונים קודמים לדגם {g_brand} {g_model}: {prev_scores}."

            # ---- פרומפט מלא ----
            prompt = f"""
אתה אנליסט מומחה לשוק הרכב הישראלי. עליך להעריך את כדאיות העסקה של רכב משומש לפי טקסט המודעה והתמונות המצורפות.

אם קיבלת אזהרה על חוסר עקביות קודמת, קח זאת בחשבון וייצר ציון מאוזן יותר בהתבסס על מגמות עבר:
{stability_note}

ספק ניתוח מדויק, ריאלי ומבוסס עובדות.

---
🔹 שלב 1 – ניתוח מודעה
קרא את המודעה:
\"\"\"{ad_text}\"\"\"
הפק ממנה את הנתונים (יצרן, דגם, גרסה, שנה, מחיר, ק״מ, דלק, יד, אזור, טסט, טיפולים וכו׳)
וציין אילו הופקו מהמודעה.

---
🔹 שלב 2 – נתוני שוק
מצא מידע עדכני על הדגם:
מחיר שוק ממוצע, אמינות, עלות תחזוקה, תקלות ידועות, ביקוש ובטיחות.

---
🔹 שלב 3 – הצלבה
השווה בין הנתונים מהמודעה לנתוני השוק, וציין פערים, יתרונות וסיכונים.

---
🔹 שלב 4 – שיקולי זהירות
הורד ציון רק אם קיימים סיכונים ממשיים:
- מחיר נמוך ב־15%+ ללא סיבה
- היעדר היסטוריית טיפולים
- ק״מ גבוה מאוד
- יד 4+
- רכב ליסינג לא מטופל
- טורבו ישן
- גיר רובוטי ישן
- חשמלי עם סוללה לא נבדקה
- רכב ישן עם תחזוקה יקרה

---
🔹 שלב 4.5 – 18 מקרי קצה
1. ק״מ גבוה עם טיפולים = תקין.
2. מחיר נמוך עד 10% = לא חשוד.
3. מחיר גבוה מוצדק אם גרסה מאובזרת.
4. רכבי שטח – ק״מ גבוה נורמלי.
5. רכבי נישה – לא למדוד לפי ביקוש.
6. ניסוח רשלני – לא שלילה.
7. מודעה קצרה – השלם מידע.
8. מחיר נמוך ב־50% = חשד השבתה.
9. יבוא אישי – אל תשווה לשוק רגיל.
10. אספנות – גיל לא חיסרון.
11. סוחר – הפחת אמינות.
12. “מחיר סופי” – לא בהכרח חשוד.
13. צבע חריג – אם מקורי לא חיסרון.
14. אין ק״מ – הערך ממוצע.
15. אזור לח – סיכון חלודה.
16. חסר מחיר – הערך לפי טווח דגם.
17. ליסינג שטופל – תקין.
18. שפה זרה – הסתמך על נתונים בלבד.

---
🔹 שלב 5 – נוסחת ציון (0–100)
- מחיר מול שוק – 25%
- תחזוקה ומצב – 25%
- אמינות דגם – 20%
- גיל וק״מ – 15%
- אמינות מוכר – 10%
- ביקוש – 5%

---
🔹 שלב 6 – פלט JSON בלבד
{{
  "from_ad": {{
    "brand": "",
    "model": "",
    "year": 0,
    "mileage_km": 0,
    "price_nis": 0,
    "ad_claims": []
  }},
  "from_internet": {{
    "market_estimate_nis": 0,
    "reliability_score": 0,
    "avg_maintenance_cost": 0,
    "demand_level": "",
    "known_issues": []
  }},
  "cross_analysis": {{
    "price_alignment": "",
    "condition_alignment": "",
    "key_differences": []
  }},
  "deal_score": 0,
  "classification": "",
  "short_verdict": "",
  "key_reasons": [],
  "user_info": {{
    "reliability_summary": "",
    "maintenance_tips": [],
    "common_faults": [],
    "market_context": ""
  }}
}}

---
🔹 שלב 7 – תיקון שוק
אם קיימת היסטוריה לדגם זה, השווה לציונים הקודמים:
- אם הפער מעל 15 נק׳, בצע תיקון של 50% לכיוון הממוצע.
"""

            inputs = [prompt]
            for img in (uploaded_images or []):
                try:
                    inputs.append(Image.open(img))
                except Exception:
                    pass

            response = model.generate_content(inputs, request_options={"timeout": 120})
            raw_text = (response.text or "").strip()
            if not raw_text:
                st.error("⚠️ המודל לא החזיר פלט.")
                st.stop()

            fixed_json = repair_json(raw_text)
            data = json.loads(fixed_json)

            avg = get_model_avg(data["from_ad"].get("brand",""), data["from_ad"].get("model",""))
            if avg:
                diff = data["deal_score"] - avg
                if abs(diff) >= 15:
                    data["deal_score"] = int(data["deal_score"] - diff * 0.5)
                    data["short_verdict"] += f" ⚙️ בוצע תיקון לפי ממוצע היסטורי ({avg})"

            save_to_history(data)

            score = data.get("deal_score", 0)
            color = "#28a745" if score >= 80 else "#ffc107" if score >= 60 else "#dc3545"
            st.markdown(f"<h3 style='color:{color}'>🚦 ציון כדאיות כולל: {score}/100 — {data.get('classification','')}</h3>", unsafe_allow_html=True)
            st.write("🧾 **סיכום:**", data.get("short_verdict", ""))
            st.divider()

            st.subheader("📋 נתונים מתוך המודעה:")
            st.json(data.get("from_ad", {}))

            st.subheader("🌍 נתוני שוק שנמצאו באינטרנט:")
            st.json(data.get("from_internet", {}))

            st.subheader("🔍 הצלבה וניתוח פערים:")
            st.json(data.get("cross_analysis", {}))

            st.subheader("🧠 סיבות עיקריות לציון:")
            for r in data.get("key_reasons", []):
                st.write(f"• {r}")

            history = load_history()
            model_entries = [
                h for h in history
                if h.get("from_ad", {}).get("brand","") == data.get("from_ad", {}).get("brand","")
                and data.get("from_ad", {}).get("model","") in h.get("from_ad", {}).get("model","")
            ]
            if len(model_entries) >= 2:
                df = pd.DataFrame([{"Index": i+1, "Score": h.get("deal_score", 0)} for i,h in enumerate(model_entries)])
                st.line_chart(df.set_index("Index"), height=200)
                st.caption("📈 מגמת ציונים היסטורית לדגם זה")

            st.caption("© 2025 Car Advisor AI – גרסה סופית עם Google Sheets, תיקון שוק, מקרי קצה וגרף מגמה")

        except Exception:
            st.error("❌ שגיאה בעיבוד הנתונים:")
            st.code(traceback.format_exc())
