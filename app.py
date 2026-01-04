import streamlit as st
import hashlib
import time
import requests
import datetime
import random
from deep_translator import GoogleTranslator
from transformers import pipeline

# ==============================================================================
# 1. CẤU HÌNH TRANG & CSS DARK MODE
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet AI Terminal",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    /* Nền tối chuyên nghiệp */
    .stApp { background-color: #0E1117; }
    
    /* Card tin tức cơ bản */
    .news-card {
        background-color: #1F2937;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        transition: all 0.3s ease;
        border-left: 5px solid #4B5563; /* Mặc định xám */
    }
    
    /* Hiệu ứng loading cho AI */
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    .ai-loading {
        color: #9CA3AF;
        font-size: 0.75em;
        font-weight: bold;
        font-style: italic;
        animation: pulse 1.5s infinite;
        display: inline-block;
        margin-right: 10px;
    }
    
    /* Badge kết quả AI */
    .ai-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75em;
        font-weight: 800;
        color: white;
        margin-right: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Thời gian */
    .time-badge {
        color: #6B7280;
        font-family: 'Consolas', monospace;
        font-size: 0.85em;
        margin-right: 8px;
    }
    
    /* Nội dung tin */
    .news-content {
        color: #E5E7EB;
        font-size: 15px;
        line-height: 1.6;
        font-family: 'Segoe UI', sans-serif;
        display: block;
        margin-top: 5px;
    }
    
    /* Thanh điều khiển */
    .control-panel {
        background-color: #111827;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #374151;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. KHỞI TẠO AI & API
# ==============================================================================

# Cache Model FinBERT (Chỉ load 1 lần duy nhất)
@st.cache_resource
def load_finbert_model():
    try:
        # Tải model chuyên tài chính
        return pipeline("text-classification", model="ProsusAI/finbert")
    except Exception as e:
        return None

# Cache Dịch thuật (Lưu kết quả dịch trong 1 tiếng)
@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target_lang):
    if target_lang == 'vi': return text
    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except: return text

# Cấu hình API VnWallStreet
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/"
}

def get_news_data():
    try:
        ts = int(time.time() * 1000)
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
        response = requests.get(API_URL, params=params, headers=HEADERS, timeout=5)
        if response.status_code == 200: return response.json().get('data', [])
        return []
    except: return []

# ==============================================================================
# 3. GIAO DIỆN & LOGIC CHÍNH
# ==============================================================================

st.title("⚡ VNWallStreet Intelligence")

# --- CONTROL PANEL ---
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    
    with c1:
        # Chọn ngôn ngữ hiển thị
        LANGUAGES = {"🇬🇧 English": "en", "🇻🇳 Tiếng Việt": "vi", "🇨🇳 中文": "zh-CN"}
        selected_lang = st.selectbox("Language:", list(LANGUAGES.keys()), index=0)
        target_lang_code = LANGUAGES[selected_lang]
        
    with c2:
        # Chọn Múi giờ
        TIMEZONES = {
            "New York (UTC-5)": -5, "London (UTC+0)": 0, 
            "Vietnam (UTC+7)": 7, "Tokyo (UTC+9)": 9
        }
        selected_tz = st.selectbox("Timezone:", list(TIMEZONES.keys()), index=2)
        tz_offset = TIMEZONES[selected_tz]
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

    with c3:
        # Nút Refresh
        st.write("") # Spacer
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- LOAD AI (Không chặn UI nếu đã cache) ---
with st.spinner("Initializing AI Neural Network..."):
    finbert = load_finbert_model()

# --- LẤY DỮ LIỆU ---
news_list = get_news_data()

if news_list:
    last_update = datetime.datetime.now(CURRENT_TZ).strftime('%H:%M:%S')
    st.caption(f"Last updated: {last_update} | AI Engine: {'Active 🟢' if finbert else 'Inactive 🔴'}")
    
    # --- VÒNG LẶP XỬ LÝ ---
    for item in news_list:
        # 1. TẠO PLACEHOLDER (Chiếm chỗ trước)
        card_placeholder = st.empty()
        
        # 2. XỬ LÝ CƠ BẢN (Tốc độ cao)
        # Thời gian
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            t_str = datetime.datetime.fromtimestamp(raw_time, CURRENT_TZ).strftime("%H:%M")
        except: t_str = "--:--"
        
        # Nội dung
        original_text = (item.get('title') or item.get('content') or "").strip()
        # Dịch sang ngôn ngữ hiển thị
        display_text = cached_translate(original_text, target_lang_code)
        
        # 3. HIỂN THỊ LẦN 1 (Chưa có điểm AI, hiện Loading)
        # Giúp người dùng đọc được tin ngay lập tức
        card_placeholder.markdown(f"""
        <div class="news-card">
            <div>
                <span class="time-badge">[{t_str}]</span>
                <span class="ai-loading">⚡ Analyzing impact...</span>
                <span class="news-content">{display_text}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 4. XỬ LÝ AI (Chạy ngầm) & CẬP NHẬT LẠI (Re-render)
        if finbert:
            try:
                # FinBERT bắt buộc phải nhận tiếng Anh
                input_ai = display_text if target_lang_code == 'en' else cached_translate(original_text, 'en')
                
                # Inference
                result = finbert(input_ai)[0]
                label = result['label']
                score = result['score']
                
                # Logic màu sắc
                if label == 'positive':
                    color = "#10B981"; text_label = "BULLISH"; border = "#10B981"
                elif label == 'negative':
                    color = "#EF4444"; text_label = "BEARISH"; border = "#EF4444"
                else:
                    color = "#6B7280"; text_label = "NEUTRAL"; border = "#6B7280"
                
                # 5. HIỂN THỊ LẦN 2 (Ghi đè lên placeholder cũ)
                card_placeholder.markdown(f"""
                <div class="news-card" style="border-left: 5px solid {border};">
                    <div>
                        <span class="time-badge">[{t_str}]</span>
                        <span class="ai-badge" style="background-color: {color};">{text_label} {int(score*100)}%</span>
                        <span class="news-content">{display_text}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
            except Exception as e:
                # Nếu lỗi AI thì giữ nguyên, hoặc báo lỗi nhẹ
                pass

else:
    st.info("Waiting for market data feed...")

# Tự động refresh sau 60s
time.sleep(60)
st.rerun()
