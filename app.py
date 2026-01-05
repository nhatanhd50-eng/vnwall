import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import json
import re
from deep_translator import GoogleTranslator

# ==============================================================================
# 1. CẤU HÌNH CEREBRAS
# ==============================================================================
LLM_API_KEY = "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w"
LLM_MODEL = "gpt-oss-120b" 

try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=LLM_API_KEY)
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
except Exception:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS
# ==============================================================================
st.set_page_config(page_title="VnWallStreet x Cerebras", page_icon="🧠", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    
    /* CONTROL PANEL */
    .control-panel {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #30363d;
    }

    /* DASHBOARD */
    .dashboard-box {
        background: linear-gradient(145deg, #1f2937, #111827);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #374151;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    
    /* CARD TIN TỨC */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 5px solid #6B7280;
        transition: all 0.5s ease;
    }
    
    .ai-badge { font-weight: 800; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    .ai-loading { color: #F59E0B; font-style: italic; font-size: 0.85em; animation: pulse 1.5s infinite; display: block; margin-top: 5px; }
    .ai-reason { display: block; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #374151; color: #F59E0B; font-size: 0.9em; font-style: italic; }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. HELPER: DỊCH & API
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target='en'):
    if target == 'vi': return text
    try:
        if not text or len(text) < 2: return text
        return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

def get_news_data():
    SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://vnwallstreet.com/", "Accept": "application/json"}
    try:
        ts = int(time.time() * 1000)
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        return resp.json().get('data', []) if resp.status_code == 200 else []
    except: return []

# ==============================================================================
# 4. CORE AI: CEREBRAS BATCH
# ==============================================================================
def analyze_news_batch(news_list, lang_instruction="Vietnamese"):
    if not AI_AVAILABLE or not news_list: return []
    
    # Chuẩn bị input (Dịch sang Anh cho AI đọc tốt nhất)
    content_str = ""
    for idx, item in enumerate(news_list):
        raw = (item.get('title') or item.get('content') or "").strip()
        eng = cached_translate(raw, 'en')
        content_str += f"ID {idx}: {eng}\n"

    # Prompt Dynamic theo ngôn ngữ người dùng chọn
    system_prompt = f"""
    You are a Financial Analyst AI.
    TASK: Analyze sentiment of provided news.
    
    OUTPUT: Valid JSON Array ONLY.
    Schema: 
    [
      {{
        "id": int, 
        "sentiment": "BULLISH"|"BEARISH"|"NEUTRAL", 
        "score": float (0.1-0.99), 
        "reason": "Explanation in {lang_instruction} (max 15 words)"
      }}
    ]
    """
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content_str}],
            temperature=0.1, max_tokens=4000
        )
        raw = response.choices[0].message.content
        json_str = raw.split("```json")[1].split("```")[0] if "```json" in raw else raw
        return json.loads(json_str)
    except: return []

# ==============================================================================
# 5. MAIN LOGIC
# ==============================================================================
st.title(f"⚡ VNWallStreet x Cerebras")

# --- CONTROL PANEL (ĐÃ KHÔI PHỤC) ---
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    
    with c1:
        LANGUAGES = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        sel_lang = st.selectbox("Ngôn ngữ / Language:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        # Xác định ngôn ngữ AI cần trả lời
        ai_lang_instruction = "Vietnamese" if target_lang == 'vi' else "English"

    with c2:
        TIMEZONES = {"Vietnam (UTC+7)": 7, "New York (UTC-5)": -5, "London (UTC+0)": 0}
        sel_tz = st.selectbox("Múi giờ / Timezone:", list(TIMEZONES.keys()))
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=TIMEZONES[sel_tz]))

    with c3:
        st.write("") # Spacer
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()
            
    st.markdown('</div>', unsafe_allow_html=True)

# --- 1. LẤY DỮ LIỆU ---
raw_news = get_news_data()

if raw_news:
    # --- 2. HIỂN THỊ NGAY (GRAY PHASE) ---
    news_placeholder = st.empty()
    
    with news_placeholder.container():
        st.info("⏳ Loading & Translating...")
        for item in raw_news:
            # Xử lý thời gian theo múi giờ chọn
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            
            # Xử lý text theo ngôn ngữ chọn
            orig_text = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(orig_text, target_lang)
            
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid #4B5563;">
                <span class="time-badge">[{t_str}]</span>
                <span class="ai-loading">⚡ Analyzing...</span>
                <div class="news-text">{display_text}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- 3. AI CHẠY NGẦM ---
    batch_results = analyze_news_batch(raw_news, ai_lang_instruction)

    # --- 4. CẬP NHẬT MÀU (COLOR PHASE) ---
    with news_placeholder.container():
        scores = []
        display_items = []
        
        for idx, item in enumerate(raw_news):
            ai_info = {"sentiment": "NEUTRAL", "score": 0, "reason": "No data", "color": "#6B7280"}
            
            # Khớp dữ liệu
            matched = None
            if batch_results:
                for res in batch_results:
                    if res.get('id') == idx: matched = res; break
                if not matched and idx < len(batch_results): matched = batch_results[idx]
            
            if matched:
                sent = str(matched.get("sentiment", "NEUTRAL")).upper()
                scr = float(matched.get("score", 0))
                reason = matched.get("reason", "")
                
                if "BULL" in sent: ai_info = {"sentiment": "BULLISH", "score": scr, "reason": reason, "color": "#10B981"}; scores.append(scr)
                elif "BEAR" in sent: ai_info = {"sentiment": "BEARISH", "score": scr, "reason": reason, "color": "#EF4444"}; scores.append(-scr)
                else: ai_info = {"sentiment": "NEUTRAL", "score": scr, "reason": reason, "color": "#6B7280"}; scores.append(0)

            # Time & Text (Re-process for final render)
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            
            orig_text = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(orig_text, target_lang)
            
            display_items.append({"time": t_str, "text": display_text, "ai": ai_info})

        # Dashboard Logic
        avg = statistics.mean(scores) if scores else 0
        if avg > 0.15: mood="RISK ON 🟢"; color="#10B981"; msg="Stocks/Crypto 🚀 | USD 📉"
        elif avg < -0.15: mood="RISK OFF 🔴"; color="#EF4444"; msg="USD/Gold 🛡️ | Stocks 📉"
        else: mood="SIDEWAY ⚪"; color="#9CA3AF"; msg="Market Mixed / Waiting"

        # Render Dashboard
        st.markdown(f"""
        <div class="dashboard-box">
            <h2 style="color:{color}; margin:0;">{mood}</h2>
            <div style="color:#ddd;">Score: {avg:.2f}</div>
            <div style="color:#999; font-size:0.9em; margin-top:5px;">{msg}</div>
        </div>
        """, unsafe_allow_html=True)

        # Render News List
        for item in display_items:
            ai = item['ai']
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid {ai['color']};">
                <span class="time-badge">[{item['time']}]</span>
                <span class="ai-badge" style="background-color: {ai['color']};">{ai['sentiment']} {int(ai['score']*100)}%</span>
                <div class="news-text">{item['text']}</div>
                <span class="ai-reason">💡 {ai['reason']}</span>
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ No data available.")

# Auto Refresh Countdown
cnt = st.empty()
for i in range(120, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Auto-refresh in {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
