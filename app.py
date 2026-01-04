import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import random
from deep_translator import GoogleTranslator

# Xử lý lỗi nếu chưa cài thư viện AI
try:
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ==============================================================================
# 1. CẤU HÌNH & CSS (DARK MODE PREMIUM)
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet AI Terminal",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    /* Nền ứng dụng */
    .stApp { background-color: #0b0f19; }
    
    /* DASHBOARD TỔNG HỢP */
    .dashboard-box {
        background: linear-gradient(145deg, #1f2937, #111827);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #374151;
        text-align: center;
        margin-bottom: 30px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    .score-big { font-size: 2.5em; font-weight: 900; margin: 10px 0; }
    .flow-advice { color: #9CA3AF; font-style: italic; font-size: 0.9em; margin-top: 10px; border-top: 1px solid #374151; padding-top: 10px;}
    
    /* CARD TIN TỨC */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 5px solid #4B5563;
        transition: transform 0.2s;
    }
    .news-card:hover { transform: translateX(5px); }
    
    /* BADGES */
    .ai-badge {
        font-weight: 800;
        padding: 3px 8px;
        border-radius: 4px;
        color: white;
        font-size: 0.75em;
        margin-right: 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .time-badge { color: #6B7280; font-family: 'Consolas', monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-family: 'Segoe UI', sans-serif; }
    
    /* COUNTDOWN BAR */
    .countdown-bar {
        text-align: center;
        color: #6B7280;
        font-size: 0.9em;
        margin-top: 30px;
        padding: 15px;
        border-top: 1px solid #30363d;
        background-color: #0d1117;
        border-radius: 8px;
    }
    
    /* CONTROL PANEL */
    .control-panel { background-color: #161b22; padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #30363d; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. CORE AI & DATA ENGINE
# ==============================================================================

@st.cache_resource
def load_finbert():
    """Tải FinBERT 1 lần duy nhất."""
    if not AI_AVAILABLE: return None
    try:
        return pipeline("text-classification", model="ProsusAI/finbert")
    except Exception as e:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target='en'):
    if target == 'vi': return text
    try:
        if not text or len(text) < 3: return text
        return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/"
}

def get_news_batch():
    try:
        ts = int(time.time() * 1000)
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('data', [])
        return []
    except: return []

# ==============================================================================
# 3. GIAO DIỆN ĐIỀU KHIỂN
# ==============================================================================
st.title("⚡ VNWallStreet AI Terminal")

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    
    with c1:
        LANGUAGES = {"🇬🇧 English": "en", "🇻🇳 Tiếng Việt": "vi", "🇨🇳 中文": "zh-CN"}
        sel_lang = st.selectbox("Hiển thị / Display:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        
    with c2:
        TIMEZONES = {"Vietnam (UTC+7)": 7, "New York (UTC-5)": -5, "London (UTC+0)": 0}
        sel_tz = st.selectbox("Múi giờ / Timezone:", list(TIMEZONES.keys()))
        tz_offset = TIMEZONES[sel_tz]
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

    with c3:
        st.write("")
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# 4. LOGIC XỬ LÝ (PIPELINE)
# ==============================================================================

finbert = load_finbert()
raw_news = get_news_batch()

if raw_news:
    # --- GIAI ĐOẠN 1: XỬ LÝ NGẦM ---
    processed_items = []
    sentiment_values = [] 
    
    with st.status("🚀 AI System Processing...", expanded=True) as status:
        total_items = len(raw_news)
        progress_bar = st.progress(0)
        
        for idx, item in enumerate(raw_news):
            progress_bar.progress((idx + 1) / total_items)
            
            # 1. Text & Translation
            original_text = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(original_text, target_lang)
            ai_input_text = original_text if target_lang == 'en' else cached_translate(original_text, 'en')
            
            # 2. FinBERT Analysis
            ai_data = {"label": "NEUTRAL", "score": 0, "color": "#6B7280"}
            
            if finbert and ai_input_text:
                try:
                    res = finbert(ai_input_text)[0]
                    lbl = res['label']
                    scr = res['score']
                    
                    if lbl == 'positive':
                        ai_data = {"label": "BULLISH", "score": scr, "color": "#10B981"}
                        sentiment_values.append(scr)
                    elif lbl == 'negative':
                        ai_data = {"label": "BEARISH", "score": scr, "color": "#EF4444"}
                        sentiment_values.append(-scr)
                    else:
                        sentiment_values.append(0)
                except: pass
            
            # 3. Time Processing
            try:
                raw_t = int(item.get('createtime') or item.get('showtime') or 0)
                if raw_t > 1000000000000: raw_t = raw_t / 1000
                time_str = datetime.datetime.fromtimestamp(raw_t, CURRENT_TZ).strftime("%H:%M")
            except: time_str = "--:--"
            
            processed_items.append({"time": time_str, "text": display_text, "ai": ai_data})
            
        status.update(label="✅ Analysis Complete!", state="complete", expanded=False)

    # --- GIAI ĐOẠN 2: DASHBOARD ---
    avg_score = statistics.mean(sentiment_values) if sentiment_values else 0
    
    if avg_score > 0.15:
        mood = "RISK ON (Hưng Phấn)"
        mood_color = "#10B981"
        flow_text = "Dòng tiền đổ vào <b>Cổ phiếu/Crypto</b>. USD Index có xu hướng <b>GIẢM</b>."
    elif avg_score < -0.15:
        mood = "RISK OFF (Sợ Hãi)"
        mood_color = "#EF4444"
        flow_text = "Thị trường bất ổn. Dòng tiền trú ẩn vào <b>USD / Vàng</b>. Cổ phiếu chịu áp lực."
    else:
        mood = "NEUTRAL (Đi Ngang)"
        mood_color = "#9CA3AF"
        flow_text = "Thị trường chưa rõ xu hướng. Tin tức trái chiều."

    # Render Dashboard
    st.markdown(f"""
    <div class="dashboard-box">
        <div style="color: #9CA3AF; letter-spacing: 2px; font-size: 0.8em; text-transform: uppercase;">Market Sentiment (AI FinBERT)</div>
        <div class="score-big" style="color: {mood_color}">{mood}</div>
        <div style="font-size: 1.2em; font-weight: bold;">Score: {avg_score:.2f}</div>
        <div class="flow-advice">{flow_text}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Render News List
    st.caption(f"Latest News Feed ({sel_tz})")
    for item in processed_items:
        ai = item['ai']
        st.markdown(f"""
        <div class="news-card" style="border-left: 5px solid {ai['color']};">
            <div>
                <span class="time-badge">[{item['time']}]</span>
                <span class="ai-badge" style="background-color: {ai['color']};">{ai['label']} {int(ai['score']*100)}%</span>
                <div class="news-text">{item['text']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

else:
    st.warning("⚠️ Waiting for data stream...")

# ==============================================================================
# 5. AUTO REFRESH COUNTDOWN (ĐÃ THÊM LẠI)
# ==============================================================================

# Thời gian đếm ngược (giây)
REFRESH_SECONDS = 90

# Placeholder ở cuối trang để hiện đếm ngược
footer = st.empty()

# Vòng lặp đếm ngược
for i in range(REFRESH_SECONDS, 0, -1):
    with footer.container():
        st.markdown(f"""
            <div class="countdown-bar">
                ⏳ Auto-refresh in <b style="color: #FFD700; font-size: 1.2em;">{i}</b> seconds... <br>
                <span style="font-size: 0.8em;">(Next update: {(datetime.datetime.now() + datetime.timedelta(seconds=i)).strftime('%H:%M:%S')})</span>
            </div>
        """, unsafe_allow_html=True)
    time.sleep(1)

# Hết giờ thì reload
st.rerun()
