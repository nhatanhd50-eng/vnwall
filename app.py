import streamlit as st
import hashlib
import time
import requests
import datetime
import random
from deep_translator import GoogleTranslator
# Thêm thư viện AI
from transformers import pipeline

# ==============================================================================
# 1. CẤU HÌNH & CSS
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet Pro + AI",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    
    .news-card {
        background-color: #1F2937;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 15px;
        border-left: 5px solid #374151; /* Mặc định viền xám */
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    
    .time-badge {
        color: #9CA3AF;
        font-family: 'Consolas', monospace;
        font-size: 0.85em;
        margin-right: 8px;
    }
    
    .news-content {
        color: #F3F4F6;
        font-size: 16px;
        line-height: 1.5;
        font-family: 'Segoe UI', sans-serif;
    }
    
    /* Highlight cho AI Score */
    .ai-badge {
        display: inline-block;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.75em;
        font-weight: bold;
        color: white;
        margin-right: 8px;
        text-transform: uppercase;
        vertical-align: middle;
    }
    
    .control-panel {
        background-color: #1F2937;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #374151;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. KHỞI TẠO AI (CACHE RESOURCE ĐỂ KHÔNG LOAD LẠI)
# ==============================================================================
@st.cache_resource
def load_finbert():
    """Tải model FinBERT 1 lần duy nhất khi khởi động"""
    try:
        # Load pipeline phân tích cảm xúc tài chính
        pipe = pipeline("text-classification", model="ProsusAI/finbert")
        return pipe
    except Exception as e:
        return None

# ==============================================================================
# 3. CẤU HÌNH API & HÀM DỊCH
# ==============================================================================
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

# Cache dịch thuật để tiết kiệm thời gian
@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target_lang):
    if target_lang == 'vi': return text
    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except: return text

# ==============================================================================
# 4. GIAO DIỆN ĐIỀU KHIỂN
# ==============================================================================
st.title("🤖 VNWALLSTREET PRO + FINBERT")

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1.2])
    
    with c1:
        LANGUAGES = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English (FinBERT Ready)": "en"}
        selected_lang_label = st.selectbox("Ngôn ngữ:", list(LANGUAGES.keys()), index=1) # Mặc định tiếng Anh
        target_lang = LANGUAGES[selected_lang_label]

    with c2:
        # Toggle bật tắt AI
        use_ai = st.checkbox("Kích hoạt AI Scoring", value=True)
        
    with c3:
        st.write("")
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()
            
    # --- CẢNH BÁO QUAN TRỌNG ---
    if use_ai and target_lang != 'en':
        st.warning("⚠️ LƯU Ý: Chế độ AI hoạt động chính xác nhất khi Ngôn ngữ là 'English'. Nếu chọn Tiếng Việt, máy sẽ phải dịch ngầm 2 lần, có thể gây chậm.")
        
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# 5. LOGIC XỬ LÝ CHÍNH
# ==============================================================================

# Tải model (hiển thị loading nếu lần đầu chạy)
with st.spinner("Đang khởi động bộ não FinBERT..."):
    finbert_pipeline = load_finbert()

news_list = get_news_data()
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=7)) # UTC+7

if news_list:
    st.caption(f"Cập nhật: {datetime.datetime.now(CURRENT_TZ).strftime('%H:%M:%S')}")
    
    for item in news_list:
        # 1. Xử lý thời gian
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            t_str = datetime.datetime.fromtimestamp(raw_time, CURRENT_TZ).strftime("%H:%M")
        except: t_str = "--:--"
        
        # 2. Xử lý nội dung gốc
        original_text = (item.get('title') or item.get('content') or "").strip()
        
        # 3. Dịch thuật hiển thị
        display_text = cached_translate(original_text, target_lang)
        
        # 4. XỬ LÝ AI FINBERT (Chỉ chạy nếu user bật)
        ai_badge_html = ""
        border_color = "#374151" # Màu xám mặc định
        
        if use_ai and finbert_pipeline:
            try:
                # FinBERT BẮT BUỘC cần tiếng Anh
                # Nếu đang hiển thị tiếng Anh rồi thì lấy luôn, nếu không phải dịch ngầm
                input_for_ai = display_text if target_lang == 'en' else cached_translate(original_text, 'en')
                
                # Chạy model
                result = finbert_pipeline(input_for_ai)[0]
                label = result['label'] # positive, negative, neutral
                score = result['score']
                
                # Logic màu sắc
                if label == 'positive':
                    badge_color = "#10B981" # Xanh lá
                    label_text = "BULLISH"
                    border_color = "#10B981"
                elif label == 'negative':
                    badge_color = "#EF4444" # Đỏ
                    label_text = "BEARISH"
                    border_color = "#EF4444"
                else:
                    badge_color = "#6B7280" # Xám
                    label_text = "NEUTRAL"
                    border_color = "#6B7280" # Giữ nguyên xám
                
                # Tạo HTML Badge
                ai_badge_html = f'<span class="ai-badge" style="background-color: {badge_color};">{label_text} {int(score*100)}%</span>'
                
            except Exception as e:
                ai_badge_html = f'<span class="ai-badge" style="background-color: #F59E0B;">AI ERROR</span>'

        # 5. Render ra màn hình
        st.markdown(f"""
        <div class="news-card" style="border-left: 5px solid {border_color};">
            <div>
                <span class="time-badge">[{t_str}]</span>
                {ai_badge_html}
                <span class="news-content">{display_text}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

else:
    st.info("Đang chờ dữ liệu...")

# Auto reload
time.sleep(60)
st.rerun()
