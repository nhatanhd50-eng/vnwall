import streamlit as st
import hashlib
import time
import requests
import datetime
import random

# ==============================================================================
# 1. CẤU HÌNH TRANG WEB
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet Monitor",
    page_icon="🕵️",
    layout="centered"
)

# ==============================================================================
# 2. THANH CÔNG CỤ BÊN TRÁI (SIDEBAR) - CHỌN MÚI GIỜ
# ==============================================================================
st.sidebar.title("⚙️ CẤU HÌNH")

# Danh sách múi giờ phổ biến cho Trader
timezones = {
    "Vietnam (UTC+7)": 7,
    "New York (UTC-5)": -5,  # Giờ mùa đông (Mùa hè là -4)
    "London (UTC+0)": 0,
    "Tokyo (UTC+9)": 9,
    "Dubai (UTC+4)": 4,
    "UTC (Server)": 0
}

selected_tz_label = st.sidebar.selectbox("🕒 Chọn Múi Giờ Hiển Thị:", list(timezones.keys()), index=0)
tz_offset = timezones[selected_tz_label]

# Tạo đối tượng Timezone
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

st.sidebar.markdown("---")
st.sidebar.info(f"Đang hiển thị theo: **{selected_tz_label}**")

# ==============================================================================
# 3. CẤU HÌNH API & FAKE HEADER
# ==============================================================================
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Header giả lập Chrome xịn
REAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://vnwallstreet.com/",
    "Origin": "https://vnwallstreet.com"
}

# ==============================================================================
# 4. CSS GIAO DIỆN (DARK MODE)
# ==============================================================================
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    .news-box {
        background-color: #262730;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 12px;
        border-left: 4px solid #00FF00;
        color: #E0E0E0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .time { 
        color: #00FF00; 
        font-weight: bold; 
        font-family: 'Consolas', monospace; 
        margin-right: 10px; 
    }
    .title { 
        font-size: 16px; 
        line-height: 1.5; 
        font-family: 'Arial', sans-serif;
    }
    .status-bar {
        text-align: center;
        color: #888;
        font-size: 0.9em;
        margin-top: 20px;
        font-style: italic;
        padding: 10px;
        border-top: 1px solid #333;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 5. HÀM LẤY DỮ LIỆU
# ==============================================================================
def get_news_stealth():
    try:
        ts = int(time.time() * 1000)
        
        # Tham số API
        params = {
            "limit": 20,
            "uid": "-1", 
            "start": "0", 
            "token_": "", 
            "key_": SECRET_KEY, 
            "time_": ts
        }
        
        # Tạo chữ ký MD5
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        del params['key_']
        params['sign_'] = sign
        
        # Gửi request với Header giả
        response = requests.get(API_URL, params=params, headers=REAL_HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '200':
                return data.get('data', [])
        return []
    except: return []

# ==============================================================================
# 6. HIỂN THỊ DỮ LIỆU
# ==============================================================================

st.title("🕵️ VNWALLSTREET MONITOR")
st.markdown(f"**Múi giờ:** `{selected_tz_label}` | **Chế độ:** `Stealth (Random Update)`")

# Nút cập nhật thủ công
if st.button("🔄 Làm mới ngay"):
    st.rerun()

# Gọi API
news_list = get_news_stealth()

# Hiển thị giờ cập nhật hiện tại theo múi giờ đã chọn
current_time_str = datetime.datetime.now(CURRENT_TZ).strftime('%H:%M:%S')

if news_list:
    st.success(f"✅ Đã cập nhật lúc: {current_time_str}")
    
    for item in news_list:
        # Xử lý thời gian tin tức (Chuyển đổi theo múi giờ)
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            # Nếu là miliseconds (13 số) thì chia 1000
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            
            # --- CHUYỂN ĐỔI SANG MÚI GIỜ ĐÃ CHỌN ---
            dt_object = datetime.datetime.fromtimestamp(raw_time, CURRENT_TZ)
            t_str = dt_object.strftime("%H:%M")
        except: t_str = "--:--"
        
        # Xử lý nội dung
        title = item.get('title') or item.get('content') or ""
        
        # Vẽ hộp tin
        st.markdown(f"""
        <div class="news-box">
            <span class="time">[{t_str}]</span>
            <span class="title">{title}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.error("⚠️ Không lấy được dữ liệu. Server có thể đang chặn hoặc lỗi mạng.")

# ==============================================================================
# 7. CƠ CHẾ RANDOM SLEEP (60s - 120s)
# ==============================================================================

# Random thời gian nghỉ từ 60 đến 120 giây
sleep_seconds = random.randint(60, 120)

# Tính toán giờ sẽ cập nhật tiếp theo
next_update_time = datetime.datetime.now(CURRENT_TZ) + datetime.timedelta(seconds=sleep_seconds)
next_update_str = next_update_time.strftime('%H:%M:%S')

# Hiển thị thanh trạng thái
status_placeholder = st.empty()
with status_placeholder.container():
    st.markdown(f"""
        <div class="status-bar">
            💤 Đang nghỉ ngẫu nhiên <b>{sleep_seconds} giây</b>...<br>
            Dự kiến cập nhật lại lúc: <b>{next_update_str}</b>
        </div>
    """, unsafe_allow_html=True)

# Ngủ
time.sleep(sleep_seconds)

# Tự động tải lại trang
st.rerun()
