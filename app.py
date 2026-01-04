import streamlit as st
import hashlib
import time
import requests
import datetime
import random

# ==============================================================================
# CẤU HÌNH TRANG WEB
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet Monitor",
    page_icon="🕵️",
    layout="centered"
)

# ==============================================================================
# CẤU HÌNH API & FAKE HEADERS (QUAN TRỌNG)
# ==============================================================================
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Bộ giả lập trình duyệt Chrome đầy đủ (Full Fingerprint)
REAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    "Referer": "https://vnwallstreet.com/",
    "Origin": "https://vnwallstreet.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

# ==============================================================================
# GIAO DIỆN DARK MODE (CSS)
# ==============================================================================
st.markdown("""
    <style>
    /* Chỉnh màu nền và khung tin tức */
    .stApp {
        background-color: #0E1117;
    }
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
# HÀM LẤY TIN (CÓ CHỮ KÝ MD5)
# ==============================================================================
def get_news_stealth():
    try:
        ts = int(time.time() * 1000)
        
        # Tham số
        params = {
            "limit": 20, # Lấy 20 tin
            "uid": "-1", 
            "start": "0", 
            "token_": "", 
            "key_": SECRET_KEY, 
            "time_": ts
        }
        
        # Tạo chữ ký
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        # Chuẩn bị gửi
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
# LOGIC CHÍNH
# ==============================================================================

st.title("🕵️ VNWALLSTREET MONITOR")
st.markdown("**Chế độ:** `Stealth (Ẩn danh)` | **Nguồn:** `API Trực tiếp`")

# Nút cập nhật thủ công
if st.button("🔄 Cập nhật ngay"):
    st.rerun()

# 1. Lấy dữ liệu
news_list = get_news_stealth()

# 2. Xử lý hiển thị giờ (UTC+7)
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))
current_time = datetime.datetime.now(VN_TZ).strftime('%H:%M:%S')

if news_list:
    st.success(f"✅ Đã cập nhật dữ liệu lúc: {current_time}")
    
    for item in news_list:
        # Xử lý thời gian tin tức
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            # Nếu là miliseconds (13 số) thì chia 1000
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            
            # Chuyển sang giờ VN
            dt_object = datetime.datetime.fromtimestamp(raw_time, VN_TZ)
            t_str = dt_object.strftime("%H:%M")
        except: t_str = "--:--"
        
        # Xử lý nội dung
        title = item.get('title') or item.get('content') or ""
        
        # Render ra màn hình
        st.markdown(f"""
        <div class="news-box">
            <span class="time">[{t_str}]</span>
            <span class="title">{title}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.error("⚠️ Không lấy được dữ liệu. Server có thể đang chặn hoặc lỗi mạng.")

# ==============================================================================
# CƠ CHẾ RANDOM SLEEP (60s - 120s)
# ==============================================================================

# Random thời gian nghỉ
sleep_seconds = random.randint(60, 120)

# Hiển thị thanh trạng thái đếm ngược (để biết web vẫn đang sống)
status_placeholder = st.empty()

with status_placeholder.container():
    st.markdown(f"""
        <div class="status-bar">
            💤 Bot đang nghỉ ngẫu nhiên <b>{sleep_seconds} giây</b> để tránh bị phát hiện...<br>
            (Sẽ tự động tải lại vào lúc { (datetime.datetime.now(VN_TZ) + datetime.timedelta(seconds=sleep_seconds)).strftime('%H:%M:%S') })
        </div>
    """, unsafe_allow_html=True)

# Ngủ
time.sleep(sleep_seconds)

# Tự động tải lại trang
st.rerun()
