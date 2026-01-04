import streamlit as st
import hashlib
import time
import requests
import datetime

# Cấu hình trang
st.set_page_config(page_title="VnWallStreet Monitor", page_icon="📈", layout="centered")

# CSS tùy chỉnh cho đẹp (Dark Mode)
st.markdown("""
    <style>
    .news-box {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border-left: 5px solid #00ff00;
    }
    .time { color: #00ff00; font-weight: bold; font-size: 0.9em; }
    .title { color: #ffffff; font-size: 1.1em; display: block; margin-top: 5px; }
    </style>
""", unsafe_allow_html=True)

# API Config
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Hàm lấy tin
def get_news():
    try:
        ts = int(time.time() * 1000)
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        del params['key_']
        params['sign_'] = sign
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(API_URL, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            return response.json().get('data', [])
        return []
    except: return []

# Giao diện chính
st.title("📡 TIN TỨC VNWALLSTREET")

# Nút làm mới thủ công
if st.button("🔄 CẬP NHẬT NGAY"):
    st.rerun()

# Tự động reload mỗi 60 giây
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60000, key="newsrefresh")
except:
    st.caption("⚠️ Để tự động reload, cần cài thư viện: streamlit-autorefresh")

# Hiển thị tin
news_list = get_news()

if news_list:
    st.success(f"Cập nhật lúc: {datetime.datetime.now().strftime('%H:%M:%S')}")
    
    for item in news_list:
        raw_time = item.get('createtime') or item.get('showtime') or 0
        try:
            raw_time = int(raw_time)
            if raw_time > 1000000000000: raw_time = raw_time / 1000
            t_str = datetime.datetime.fromtimestamp(raw_time).strftime("%H:%M")
        except: t_str = "--:--"
        
        title = item.get('title') or item.get('content')
        
        # Render HTML block
        st.markdown(f"""
        <div class="news-box">
            <span class="time">[{t_str}]</span>
            <span class="title">{title}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.error("Không lấy được dữ liệu.")