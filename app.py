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
    page_title="VnWallStreet Live",
    page_icon="⚡",
    layout="centered"
)

# ==============================================================================
# 2. CSS GIAO DIỆN (DARK MODE & BO GÓC)
# ==============================================================================
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    
    /* Style cho khung tin tức */
    .news-box {
        background-color: #262730;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 12px;
        border-left: 4px solid #00FF00;
        color: #E0E0E0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    
    /* Style cho giờ */
    .time { 
        color: #00FF00; 
        font-weight: bold; 
        font-family: 'Consolas', monospace; 
        margin-right: 10px; 
    }
    
    /* Style cho tiêu đề tin */
    .title { 
        font-size: 16px; 
        line-height: 1.5; 
        font-family: 'Arial', sans-serif;
    }
    
    /* Thanh đếm ngược bên dưới */
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
# 3. CẤU HÌNH API
# ==============================================================================
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Header giả lập
REAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/",
}

# ==============================================================================
# 4. HÀM LẤY TIN (MD5 SIGNATURE)
# ==============================================================================
def get_news_stealth():
    try:
        ts = int(time.time() * 1000)
        params = {
            "limit": 20, "uid": "-1", "start": "0", 
            "token_": "", "key_": SECRET_KEY, "time_": ts
        }
        
        # Tạo chữ ký
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        del params['key_']
        params['sign_'] = sign
        
        response = requests.get(API_URL, params=params, headers=REAL_HEADERS, timeout=5)
        
        if response.status_code == 200:
            return response.json().get('data', [])
        return []
    except: return []

# ==============================================================================
# 5. GIAO DIỆN CHÍNH (HEADER & CONTROL)
# ==============================================================================

st.title("⚡ VNWALLSTREET MONITOR")

# --- KHU VỰC ĐIỀU KHIỂN (Cột 1: Nút bấm | Cột 2: Múi giờ) ---
col1, col2 = st.columns([1, 2]) # Chia tỷ lệ cột: Cột 2 rộng gấp đôi Cột 1

with col1:
    # Nút bấm cập nhật (Thêm khoảng trắng phía trên để căn giữa với ô chọn bên cạnh)
    st.write("") 
    if st.button("🔄 Cập nhật ngay", use_container_width=True):
        st.rerun()

with col2:
    # Ô chọn múi giờ có biểu tượng Trái Đất
    timezones = {
        "Vietnam (UTC+7)": 7,
        "New York (UTC-5)": -5,
        "London (UTC+0)": 0,
        "Tokyo (UTC+9)": 9,
        "Dubai (UTC+4)": 4
    }
    selected_tz_label = st.selectbox(
        "🌍 Chọn Múi Giờ Hiển Thị:", 
        list(timezones.keys()), 
        index=0
    )

# Tính toán múi giờ đã chọn
tz_offset = timezones[selected_tz_label]
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

st.markdown("---") # Đường kẻ ngang phân cách

# ==============================================================================
# 6. HIỂN THỊ TIN TỨC
# ==============================================================================

# Lấy dữ liệu
news_list = get_news_stealth()

# Hiển thị giờ hệ thống hiện tại
current_time_str = datetime.datetime.now(CURRENT_TZ).strftime('%H:%M:%S')

if news_list:
    st.success(f"✅ Đã cập nhật lúc: **{current_time_str}**")
    
    for item in news_list:
        # Xử lý thời gian tin
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            
            # Chuyển đổi sang múi giờ người dùng chọn
            dt_object = datetime.datetime.fromtimestamp(raw_time, CURRENT_TZ)
            t_str = dt_object.strftime("%H:%M")
        except: t_str = "--:--"
        
        title = item.get('title') or item.get('content') or ""
        
        # Vẽ tin ra màn hình
        st.markdown(f"""
        <div class="news-box">
            <span class="time">[{t_str}]</span>
            <span class="title">{title}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.error("⚠️ Không lấy được dữ liệu. Server đang bận hoặc chặn IP.")

# ==============================================================================
# 7. TỰ ĐỘNG CHẠY LẠI (RANDOM 60s - 120s)
# ==============================================================================

# Random thời gian nghỉ
sleep_seconds = random.randint(60, 120)

# Tính giờ cập nhật tiếp theo
next_time = datetime.datetime.now(CURRENT_TZ) + datetime.timedelta(seconds=sleep_seconds)
next_str = next_time.strftime('%H:%M:%S')

# Hiển thị thanh trạng thái bên dưới cùng
status_placeholder = st.empty()
with status_placeholder.container():
    st.markdown(f"""
        <div class="status-bar">
            💤 Đang nghỉ ngẫu nhiên <b>{sleep_seconds} giây</b>...<br>
            Tự động cập nhật lại lúc: <b>{next_str}</b>
        </div>
    """, unsafe_allow_html=True)

# Ngủ
time.sleep(sleep_seconds)

# Reload trang
st.rerun()
