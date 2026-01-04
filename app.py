import streamlit as st
import hashlib
import time
import requests
import datetime
import random
from deep_translator import GoogleTranslator

# ==============================================================================
# 1. CẤU HÌNH TRANG WEB
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet Pro",
    page_icon="🌍",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ==============================================================================
# 2. CSS GIAO DIỆN (PREMIUM DARK MODE)
# ==============================================================================
st.markdown("""
    <style>
    /* Nền chung */
    .stApp { background-color: #0E1117; }
    
    /* Khung tin tức */
    .news-card {
        background-color: #1F2937;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 15px;
        border-left: 5px solid #10B981; /* Xanh lá */
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s;
    }
    .news-card:hover {
        transform: scale(1.01); /* Hiệu ứng phóng to nhẹ khi di chuột */
        background-color: #374151;
    }
    
    /* Thời gian */
    .time-badge {
        background-color: #064E3B;
        color: #6EE7B7;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: bold;
        font-family: 'Consolas', monospace;
        font-size: 0.85em;
        margin-right: 10px;
        display: inline-block;
    }
    
    /* Tiêu đề tin */
    .news-content {
        color: #F3F4F6;
        font-size: 16px;
        line-height: 1.5;
        font-family: 'Segoe UI', sans-serif;
    }
    
    /* Thanh trạng thái */
    .status-bar {
        text-align: center;
        color: #9CA3AF;
        font-size: 0.9em;
        margin-top: 25px;
        padding: 10px;
        border-top: 1px solid #374151;
        font-style: italic;
    }
    
    /* Header control panel */
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
# 3. CẤU HÌNH API
# ==============================================================================
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Header giả lập
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/"
}

# ==============================================================================
# 4. HÀM LẤY TIN
# ==============================================================================
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
        if response.status_code == 200:
            return response.json().get('data', [])
        return []
    except: return []

# ==============================================================================
# 5. GIAO DIỆN ĐIỀU KHIỂN (CONTROL PANEL)
# ==============================================================================
st.title("🌍 GLOBAL NEWS MONITOR")

with st.container():
    # Tạo khung bao quanh control panel
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1.5, 1.5, 1])
    
    with col1:
        # Chọn Ngôn ngữ
        LANGUAGES = {
            "🇻🇳 Tiếng Việt (Gốc)": "vi",
            "🇬🇧 English (Anh)": "en",
            "🇫🇷 Français (Pháp)": "fr",
            "🇯🇵 日本語 (Nhật)": "ja",
            "🇰🇷 한국어 (Hàn)": "ko",
            "🇨🇳 中文 (Trung)": "zh-CN",
            "🇩🇪 Deutsch (Đức)": "de",
            "🇷🇺 Русский (Nga)": "ru"
        }
        selected_lang_label = st.selectbox("🌐 Ngôn ngữ dịch:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[selected_lang_label]

    with col2:
        # Chọn Múi giờ
        TIMEZONES = {
            "Vietnam (UTC+7)": 7,
            "New York (UTC-5)": -5,
            "London (UTC+0)": 0,
            "Berlin (UTC+1)": 1,
            "Moscow (UTC+3)": 3,
            "Dubai (UTC+4)": 4,
            "Tokyo (UTC+9)": 9,
            "Sydney (UTC+11)": 11
        }
        selected_tz_label = st.selectbox("🕒 Múi giờ hiển thị:", list(TIMEZONES.keys()))
        tz_offset = TIMEZONES[selected_tz_label]
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

    with col3:
        # Nút Cập nhật
        st.write("") # Spacer
        st.write("") 
        if st.button("🔄 LÀM MỚI", use_container_width=True):
            st.rerun()
            
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# 6. XỬ LÝ & HIỂN THỊ DỮ LIỆU
# ==============================================================================

# Khởi tạo bộ dịch
translator = GoogleTranslator(source='auto', target=target_lang)

news_list = get_news_data()
current_time_str = datetime.datetime.now(CURRENT_TZ).strftime('%H:%M:%S')

if news_list:
    st.success(f"✅ Đã cập nhật lúc: **{current_time_str}**")
    
    for item in news_list:
        # --- Xử lý Thời Gian ---
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            dt_object = datetime.datetime.fromtimestamp(raw_time, CURRENT_TZ)
            t_str = dt_object.strftime("%H:%M")
        except: t_str = "--:--"
        
        # --- Xử lý Nội Dung ---
        original_text = item.get('title') or item.get('content') or ""
        original_text = original_text.strip()
        
        # Dịch thuật (Nếu không phải Tiếng Việt)
        display_text = original_text
        if target_lang != 'vi':
            try:
                # Dịch title
                display_text = translator.translate(original_text)
            except: 
                display_text = original_text # Fallback nếu lỗi dịch
        
        # --- Render HTML Card ---
        st.markdown(f"""
        <div class="news-card">
            <div>
                <span class="time-badge">{t_str}</span>
                <span class="news-content">{display_text}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
else:
    st.warning("⚠️ Đang chờ dữ liệu từ máy chủ...")

# ==============================================================================
# 7. TỰ ĐỘNG CHẠY LẠI (CÓ ĐẾM NGƯỢC)
# ==============================================================================

# Random thời gian nghỉ từ 60 đến 90 giây
sleep_seconds = random.randint(60, 90)

# Tính giờ cập nhật tiếp theo (để hiển thị cố định)
next_time = datetime.datetime.now(CURRENT_TZ) + datetime.timedelta(seconds=sleep_seconds)
next_str = next_time.strftime('%H:%M:%S')

# Tạo khung chứa nội dung đếm ngược
placeholder = st.empty()

# Vòng lặp đếm ngược từng giây
for i in range(sleep_seconds, 0, -1):
    with placeholder.container():
        st.markdown(f"""
            <div class="status-bar">
                ⏳ Tự động cập nhật sau <b style="color: #FFD700; font-size: 1.2em;">{i}</b> giây... <br>
                <span style="color: gray; font-size: 0.8em;">(Dự kiến: {next_str})</span>
            </div>
        """, unsafe_allow_html=True)
    
    # Ngủ 1 giây rồi lặp lại
    time.sleep(1)

# Hết giờ -> Tải lại trang
st.rerun()
