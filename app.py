import streamlit as st
import hashlib
import time
import requests
import datetime
import random

# ==============================================================================
# 1. CẤU HÌNH TRANG WEB (SỬA LẠI ĐOẠN NÀY)
# ==============================================================================
st.set_page_config(
    page_title="VnWallStreet Monitor",
    page_icon="🕵️",
    layout="centered",
    initial_sidebar_state="expanded"  # <--- THÊM DÒNG NÀY (Bắt buộc mở Sidebar)
)

# ==============================================================================
# 2. THANH CÔNG CỤ BÊN TRÁI (SIDEBAR)
# ==============================================================================
st.sidebar.header("⚙️ CẤU HÌNH") # Dùng Header cho to rõ

# Danh sách múi giờ
timezones = {
    "Vietnam (UTC+7)": 7,
    "New York (UTC-5)": -5,
    "London (UTC+0)": 0,
    "Tokyo (UTC+9)": 9,
    "Dubai (UTC+4)": 4,
    "UTC (Server)": 0
}

# Hộp chọn múi giờ
selected_tz_label = st.sidebar.selectbox(
    "Múi giờ hiển thị:", 
    list(timezones.keys()), 
    index=0
)
tz_offset = timezones[selected_tz_label]

CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

st.sidebar.success(f"Đang xem giờ: **{selected_tz_label}**")
st.sidebar.markdown("---")
st.sidebar.caption("Tự động ẩn danh & random thời gian quét.")

# ... (PHẦN CÒN LẠI CỦA CODE GIỮ NGUYÊN NHƯ CŨ) ...
