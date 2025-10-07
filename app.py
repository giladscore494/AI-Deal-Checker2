# -*- coding: utf-8 -*-
# ===========================================================
# AI-Deal-Checker – גרסה לומדת (Gemini 2.5 Flash)
# כולל ניתוח עקביות, 18 מקרי קצה, תיקון JSON ושמירה מקומית בלבד
# ===========================================================

import streamlit as st
import google.generativeai as genai
import json, os, traceback, re
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

HISTORY_FILE = "data_history.json"

# ---------- פונקציות עזר ----------
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_history(entry):
    history = load_history()
    history.append(entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_model_avg(brand, model_name):
    history = load_history()
    scores = [
        h.get("deal_score") for h in history
        if h.get("from_ad", {}).get("brand", "").strip() == (brand or "").strip()
        and (model_name or "").strip() in h.get("from_ad", {}).get("model", "")
    ]
    scores = [s for s in scores if isinstance(s, (int, float))]
    return round(sum(scores) / len(scores), 2) if scores else None

def check_consistency(brand, model_name):
    history = load_history()
    relevant = [
        h.get("deal_score") for h in history
        if h.get("from_ad", {}).get("brand", "").strip() == (brand or "").strip()
        and (model_name or "").strip() in h.get("from_ad", {}).get("model", "")
    ]
    relevant = [s for s in relevant if isinstance(s, (int, float))]
    if len(relevant) >= 3:
        diff = max(relevant) - min(relevant)
        if diff >= 25:
            return True, relevant
    return False, relevant

def guess_brand_model(text: str):
    """
    ניחוש מהיר ל-brand/model מתוך טקסט המודעה.
    אם אין, נחזיר ("","").
    """
    if not text:
        return "", ""
    # נסה לתפוס שורה ראשונה נורמלית
    line = text.splitlines()[0].strip()
    # הפרדה בסיסית: שתי המילים הראשונות = brand/model (לרוב עובד בטויוטה C-HR, מאזדה 3, קיה נירו, אלפא רומיאו 159 וכו')
    tokens = [t for t in re.split(r"[^\w\u0590-\u05FF\-]+", line) if t]
    if len(tokens) >= 2:
        return tokens[0], " ".join(tokens[1:3])  # מודל יכול להיות מילה אחת או שתיים
    # fallback: קח שתי מילים ראשונות מכל הטקסט
    tokens = [t for t in re.split(r"[^\w\u0590-\u05FF\-]+", text) if t]
    if len(tokens) >= 2:
        return tokens[0], tokens[1]
    return "", ""

# ---------- ממשק ----------
st.title("🚗 AI Deal Checker – בדיקת כדאיות חכמה ולומדת")
st.write("העתק את טקסט המודעה (כולל מחיר, שנה, ק״מ וכו׳) והעלה תמונות של הרכב לביצוע הצלבה בין נתוני המודעה לנתוני השוק בפועל:")

ad_text = st.text_area("📋 הדבק כאן את טקסט המודעה:", height=250)
uploaded_images = st.file_uploader("📸 העלה תמונות של הרכב (ניתן לבחור כמה):", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

st.markdown(
    """
    <div style='background-color:#fff3cd; border-radius:10px; padding:10px; border:1px solid #ffeeba;'>
    ⚠️ <b>הבהרה:</b> ניתוח זה מבוסס בינה מלאכותית ואינו תחליף לבדיקה מקצועית.
    יש לבקש היסטוריית טיפולים מלאה ולהוציא דו״ח עבר ביטוחי לפני רכישה.
    </div>
    """,
    unsafe_allow_html=True
)

# ---------- פעולה ----------
if st.button("חשב ציון כדאיות"):
    if not ad_text.strip() and not uploaded_images:
        st.error("אנא הדבק טקסט או העלה לפחות תמונה אחת.")
    else:
        with st.spinner("🔍 מבצע הצלבה חכמה בין נתוני המודעה לנתוני השוק..."):
            try:
                # ---------- שלב יציבות ----------
                g_brand, g_model = guess_brand_model(ad_text)
                consistency_alert, prev_scores = check_consistency(g_brand, g_model)
                stability_note = ""
                if consistency_alert:
                    stability_note = f"⚠️ זוהתה אי-עקביות בין ציונים קודמים לדגם {g_brand} {g_model}: {prev_scores}. ייצב את הציון סביב הממוצע ההיסטורי."

                # ---------- פרומפט מלא ----------
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

                # ---------- קריאה למודל ----------
                inputs = [prompt]
                for img in (uploaded_images or []):
                    try:
                        inputs.append(Image.open(img))
                    except Exception:
                        pass

                response = model.generate_content(inputs, request_options={"timeout": 120})
                raw_text = (response.text or "").strip()

                if not raw_text:
                    st.error("⚠️ המודל החזיר תשובה ריקה.")
                    st.stop()

                fixed_json = repair_json(raw_text)
                try:
                    data = json.loads(fixed_json)
                except Exception:
                    st.error("⚠️ הפלט אינו JSON תקני גם לאחר תיקון. מציג RAW לצורך דיבוג:")
                    st.code(raw_text)
                    st.stop()

                # ---------- תיקון שוק ----------
                avg = get_model_avg(data["from_ad"].get("brand", ""), data["from_ad"].get("model", ""))
                if isinstance(avg, (int, float)):
                    diff = data.get("deal_score", 0) - avg
                    if abs(diff) >= 15:
                        correction = -diff * 0.5
                        data["deal_score"] = int(data.get("deal_score", 0) + correction)
                        data["short_verdict"] = (data.get("short_verdict") or "") + f" ⚙️ (בוצע תיקון קל לפי ממוצע היסטורי: {avg})"

                # ---------- שמירה ----------
                save_to_history(data)

                # ---------- תצוגה ----------
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

                st.divider()
                st.subheader("📚 מידע נוסף למשתמש")
                info = data.get("user_info", {})
                if info:
                    if info.get("reliability_summary"):
                        st.write(f"**אמינות הדגם:** {info['reliability_summary']}")
                    if info.get("common_faults"):
                        st.write("**תקלות נפוצות:**")
                        for f in info["common_faults"]:
                            st.write(f"• {f}")
                    if info.get("maintenance_tips"):
                        st.write("**טיפים לתחזוקה:**")
                        for tip in info["maintenance_tips"]:
                            st.write(f"• {tip}")
                    if info.get("market_context"):
                        st.write("**הקשר שוק כללי:**", info["market_context"])

                # ---------- גרף מגמה ----------
                history = load_history()
                model_entries = [
                    h for h in history
                    if h.get("from_ad", {}).get("brand", "") == data.get("from_ad", {}).get("brand", "")
                    and (data.get("from_ad", {}).get("model", "") in h.get("from_ad", {}).get("model", ""))
                ]
                if len(model_entries) >= 2:
                    df = pd.DataFrame([{"Index": i + 1, "Score": h.get("deal_score", 0)} for i, h in enumerate(model_entries)])
                    st.line_chart(df.set_index("Index"), height=200)
                    st.caption("📈 מגמת ציונים היסטורית לדגם זה")

                st.caption("© 2025 Car Advisor AI – גרסה לומדת עם תיקון שוק ומקרי קצה מלאים")

            except Exception:
                st.error("❌ שגיאה בעיבוד הפלט או בקריאת המידע מהמודל.")
                st.code(traceback.format_exc())
