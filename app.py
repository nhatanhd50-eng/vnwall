import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
from deep_translator import GoogleTranslator

# Kiểm tra thư viện AI
try:
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ==============================================================================
# 1. GIAO DIỆN & CSS (DARK MODE)
# ==============================================================================
st.set_page_config(page_title="VnWallStreet AI Terminal", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    
    /* DASHBOARD */
    .dashboard-box {
        background: linear-gradient(145deg, #1f2937, #111827);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #374151;
        text-align: center;
        margin-bottom: 25px;
    }
    .score-text { font-size: 2em; font-weight: 900; margin: 10px 0; }
    
    /* NEWS CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 5px solid #6B7280;
    }
    .ai-badge { font-weight: bold; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-family: sans-serif; }
    
    /* ERROR BOX */
    .error-box {
        background-color: #7f1d1d;
        color: #fca5a5;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        border: 1px solid #991b1b;
    }
    
    .countdown-bar { text-align: center; color: #6B7280; font-size: 0.9em; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. HỆ THỐNG AI & DATA
# ==============================================================================

@st.cache_resource
def load_finbert():
    if not AI_AVAILABLE: return None
    try:
        return pipeline("text-classification", model="ProsusAI/finbert")
    except: return None

@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target='en'):
    if target == 'vi': return text
    try:
        return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

# Cấu hình API
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/",
    "Origin": "https://vnwallstreet.com"
}

# --- HÀM LẤY TIN (CÓ BÁO LỖI CHI TIẾT) ---
def get_news_debug():
    ts = int(time.time() * 1000)
    params = {"limit": 20, "uid": "-1", "key_": SECRET_KEY, "time_": ts}
    
    # 1. Tạo chữ ký
    try:
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
    except Exception as e:
        st.markdown(f'<div class="error-box">❌ Lỗi thuật toán MD5: {e}</div>', unsafe_allow_html=True)
        return []

    # 2. Gửi Request
    try:
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        
        # Nếu Server chặn (VD: 403 Forbidden)
        if resp.status_code != 200:
            st.markdown(f'<div class="error-box">❌ API Error {resp.status_code}: Server từ chối kết nối.<br>Response: {resp.text}</div>', unsafe_allow_html=True)
            return []
            
        data = resp.json()
        
        # Nếu JSON trả về không đúng cấu trúc
        if 'data' not in data:
            st.markdown(f'<div class="error-box">⚠️ Cấu trúc dữ liệu thay đổi. API trả về:<br>{data}</div>', unsafe_allow_html=True)
            return []
            
        # Nếu danh sách rỗng
        if not data['data']:
            st.warning("⚠️ Server trả về danh sách trống (No Data). Có thể hết tin hoặc bị lọc.")
            return []
            
        return data['data']

    except Exception as e:
        st.markdown(f'<div class="error-box">❌ Lỗi kết nối mạng: {e}</div>', unsafe_allow_html=True)
        return []

# ==============================================================================
# 3. LOGIC CHÍNH
# ==============================================================================
st.title("⚡ VNWallStreet AI Terminal")

# Cấu hình
with st.expander("⚙️ Settings", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        target_lang = st.selectbox("Ngôn ngữ:", ["en", "vi"], index=0)
    with c2:
        use_debug = st.checkbox("Debug Mode", False)

# Load AI & Data
finbert = load_finbert()
raw_news = get_news_debug() # Dùng hàm debug mới

if raw_news:
    scores = []
    processed = []
    
    # Xử lý
    with st.status("🚀 Processing Market Data...", expanded=True) as status:
        pbar = st.progress(0)
        for i, item in enumerate(raw_news):
            pbar.progress((i+1)/len(raw_news))
            
            # Text
            orig = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(orig, target_lang)
            ai_input = display_text if target_lang == 'en' else cached_translate(orig, 'en')
            
            # AI
            ai_res = {"label": "NEUTRAL", "score": 0.0, "color": "#6B7280"}
            if finbert:
                try:
                    r = finbert(ai_input)[0]
                    lbl = r['label']
                    scr = r['score']
                    
                    if lbl == 'positive': 
                        ai_res = {"label": "BULLISH", "score": scr, "color": "#10B981"}
                        scores.append(scr)
                    elif lbl == 'negative': 
                        ai_res = {"label": "BEARISH", "score": scr, "color": "#EF4444"}
                        scores.append(-scr)
                    else: 
                        ai_res = {"label": "NEUTRAL", "score": scr, "color": "#6B7280"}
                        scores.append(0)
                except: pass
            
            # Time
            try:
                t = int(item.get('createtime') or 0)
                if t > 1000000000000: t /= 1000
                t_str = datetime.datetime.fromtimestamp(t).strftime("%H:%M")
            except: t_str = "--:--"
            
            processed.append({"time": t_str, "text": display_text, "ai": ai_res})
        status.update(label="✅ Done!", state="complete", expanded=False)

    # Dashboard
    avg = statistics.mean(scores) if scores else 0
    if avg > 0.15: mood="RISK ON 🟢"; color="#10B981"
    elif avg < -0.15: mood="RISK OFF 🔴"; color="#EF4444"
    else: mood="NEUTRAL ⚪"; color="#9CA3AF"
    
    st.markdown(f"""
    <div class="dashboard-box">
        <div style="color:{color}" class="score-text">{mood}</div>
        <div>Avg Score: {avg:.2f}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # List
    for p in processed:
        ai = p['ai']
        st.markdown(f"""
        <div class="news-card" style="border-left: 5px solid {ai['color']};">
            <span style="color:#888; font-family:monospace; margin-right:10px">[{p['time']}]</span>
            <span class="ai-badge" style="background:{ai['color']}">{ai['label']} {int(ai['score']*100)}%</span>
            <span class="news-text">{p['text']}</span>
        </div>
        """, unsafe_allow_html=True)

# Footer Countdown
cnt = st.empty()
for i in range(90, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Refresh in {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
