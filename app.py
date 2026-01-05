import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import random
from deep_translator import GoogleTranslator

# Kiểm tra thư viện AI
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
    /* Nền đen Deep Dark */
    .stApp { background-color: #0b0f19; }
    
    /* DASHBOARD */
    .dashboard-box {
        background: linear-gradient(145deg, #1f2937, #111827);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #374151;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    .sentiment-label { font-size: 2em; font-weight: 900; margin: 5px 0; letter-spacing: 1px; }
    .sentiment-score { font-size: 1.2em; font-family: monospace; color: #E5E7EB; }
    .flow-advice { 
        color: #9CA3AF; 
        font-style: italic; 
        font-size: 0.9em; 
        margin-top: 15px; 
        padding-top: 10px; 
        border-top: 1px dashed #374151; 
    }
    
    /* NEWS CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 5px solid #6B7280; /* Mặc định xám */
        transition: transform 0.2s;
    }
    .news-card:hover { transform: translateX(5px); }
    
    /* BADGES */
    .ai-badge {
        font-weight: 800;
        padding: 4px 8px;
        border-radius: 4px;
        color: white;
        font-size: 0.75em;
        margin-right: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .time-badge { color: #6B7280; font-family: 'Consolas', monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-family: 'Segoe UI', sans-serif; }
    
    /* ERROR BOX */
    .error-box {
        background-color: #7f1d1d;
        color: #fca5a5;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 20px;
        border: 1px solid #991b1b;
        font-family: monospace;
        font-size: 0.9em;
    }
    
    /* DEBUG TEXT */
    .debug-info {
        font-size: 0.75em;
        color: #F59E0B; /* Màu cam */
        font-family: monospace;
        margin-top: 8px;
        padding-top: 5px;
        border-top: 1px dashed #374151;
    }
    
    /* COUNTDOWN */
    .countdown-bar {
        text-align: center;
        color: #6B7280;
        font-size: 0.85em;
        margin-top: 30px;
        padding: 10px;
        background-color: #0d1117;
        border-radius: 8px;
        border: 1px solid #30363d;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. HỆ THỐNG AI & DATA
# ==============================================================================

@st.cache_resource
def load_finbert():
    """Load model FinBERT (Chỉ chạy 1 lần)"""
    if not AI_AVAILABLE: return None
    try:
        return pipeline("text-classification", model="ProsusAI/finbert")
    except Exception: return None

@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target='en'):
    """Dịch thuật có Cache"""
    if target == 'vi': return text
    try:
        if not text or len(text) < 2: return text
        return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

# Cấu hình API VnWallStreet
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"

# Header giả lập
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/",
    "Origin": "https://vnwallstreet.com",
    "Accept": "application/json, text/plain, */*"
}

def get_news_batch():
    try:
        ts = int(time.time() * 1000)
        
        # --- KHÔI PHỤC ĐẦY ĐỦ THAM SỐ ---
        params = {
            "limit": 20,
            "uid": "-1",
            "start": "0",       
            "token_": "",       
            "key_": SECRET_KEY,
            "time_": ts
        }
        
        # 1. Tạo chữ ký MD5
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        
        # Mã hóa MD5 và viết hoa
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        # 2. Chuẩn bị params gửi đi (Xóa key_, thêm sign_)
        del params['key_']
        params['sign_'] = sign
        
        # 3. Gửi Request
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        
        # --- KIỂM TRA LỖI ---
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                return data['data']
            else:
                return []
        else:
            # Nếu lỗi 400/403 -> In ra màn hình để debug
            st.markdown(f'<div class="error-box">⚠️ API ERROR {resp.status_code}: {resp.text}</div>', unsafe_allow_html=True)
            return []
            
    except Exception as e:
        st.error(f"❌ Lỗi kết nối: {e}")
        return []

# ==============================================================================
# 3. THANH ĐIỀU KHIỂN (CONTROL PANEL)
# ==============================================================================
st.title("⚡ VNWallStreet AI Terminal")

with st.expander("⚙️ CẤU HÌNH HỆ THỐNG (SETTINGS)", expanded=True):
    col1, col2, col3 = st.columns([1.5, 1.5, 1])
    
    with col1:
        LANGUAGES = {"🇬🇧 English": "en", "🇻🇳 Tiếng Việt": "vi"}
        sel_lang = st.selectbox("Ngôn ngữ hiển thị:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        
    with col2:
        TIMEZONES = {"Vietnam (UTC+7)": 7, "New York (UTC-5)": -5, "London (UTC+0)": 0}
        sel_tz = st.selectbox("Múi giờ:", list(TIMEZONES.keys()))
        tz_offset = TIMEZONES[sel_tz]
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

    with col3:
        # Nút bật chế độ Debug
        debug_mode = st.checkbox("🛠 Debug Mode", value=False, help="Hiển thị text tiếng Anh mà AI đang đọc")
        if st.button("🔄 Cập nhật ngay"):
            st.rerun()

# ==============================================================================
# 4. QUY TRÌNH XỬ LÝ (PIPELINE)
# ==============================================================================

finbert = load_finbert()
raw_news = get_news_batch()

if raw_news:
    processed_items = []
    math_scores = [] 
    
    # Hiển thị Progress Bar
    with st.status("🚀 AI đang quét dữ liệu thị trường...", expanded=True) as status:
        total = len(raw_news)
        prog_bar = st.progress(0)
        
        for idx, item in enumerate(raw_news):
            prog_bar.progress((idx + 1) / total)
            
            # 1. Xử lý Text
            original_text = (item.get('title') or item.get('content') or "").strip()
            
            # Text hiển thị (Theo ngôn ngữ user chọn)
            display_text = cached_translate(original_text, target_lang)
            
            # Text cho AI (BẮT BUỘC TIẾNG ANH)
            if target_lang == 'en':
                ai_input_text = display_text
            else:
                ai_input_text = cached_translate(original_text, 'en')
            
            # 2. FinBERT Analysis
            ai_res = {"label": "NEUTRAL", "score": 0.0, "color": "#6B7280"} 
            
            if finbert and ai_input_text:
                try:
                    res = finbert(ai_input_text)[0]
                    lbl = res['label'] 
                    conf_score = res['score'] 
                    
                    if lbl == 'positive':
                        ai_res = {"label": "BULLISH", "score": conf_score, "color": "#10B981"}
                        math_scores.append(conf_score) 
                    elif lbl == 'negative':
                        ai_res = {"label": "BEARISH", "score": conf_score, "color": "#EF4444"}
                        math_scores.append(-conf_score) 
                    else:
                        # NEUTRAL: Vẫn lưu score để hiển thị
                        ai_res = {"label": "NEUTRAL", "score": conf_score, "color": "#6B7280"}
                        math_scores.append(0) 
                except: pass
            
            # 3. Thời gian
            try:
                raw_t = int(item.get('createtime') or item.get('showtime') or 0)
                if raw_t > 1000000000000: raw_t /= 1000
                time_str = datetime.datetime.fromtimestamp(raw_t, CURRENT_TZ).strftime("%H:%M")
            except: time_str = "--:--"
            
            # Lưu kết quả
            processed_items.append({
                "time": time_str,
                "text": display_text,
                "ai": ai_res,
                "debug": ai_input_text
            })
            
        status.update(label="✅ Phân tích hoàn tất!", state="complete", expanded=False)

    # --- TÍNH TOÁN DASHBOARD ---
    avg_score = statistics.mean(math_scores) if math_scores else 0
    
    if avg_score > 0.15:
        mood_text = "RISK ON (HƯNG PHẤN) 🟢"
        mood_color = "#10B981"
        advice = "Thị trường Tích cực. Dòng tiền vào Chứng khoán/Crypto. USD/Vàng giảm áp lực."
    elif avg_score < -0.15:
        mood_text = "RISK OFF (SỢ HÃI) 🔴"
        mood_color = "#EF4444"
        advice = "Thị trường Tiêu cực. Dòng tiền trú ẩn vào USD/Vàng. Cẩn trọng với Cổ phiếu."
    else:
        mood_text = "NEUTRAL (ĐI NGANG) ⚪"
        mood_color = "#9CA3AF"
        advice = "Thị trường chưa rõ xu hướng hoặc tin tức trái chiều."

    # --- HIỂN THỊ DASHBOARD ---
    st.markdown(f"""
    <div class="dashboard-box">
        <div style="font-size:0.9em; color:#9CA3AF; letter-spacing:1px;">MARKET SENTIMENT</div>
        <div class="sentiment-label" style="color: {mood_color}">{mood_text}</div>
        <div class="sentiment-score">Avg Score: {avg_score:.2f}</div>
        <div class="flow-advice">{advice}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- HIỂN THỊ TIN TỨC ---
    for item in processed_items:
        ai = item['ai']
        
        # Phần Debug (Chỉ hiện nếu user tích chọn)
        debug_html = ""
        if debug_mode:
            debug_html = f'<div class="debug-info">🔍 [DEBUG] AI Input: "{item["debug"]}"</div>'
        
        st.markdown(f"""
        <div class="news-card" style="border-left: 5px solid {ai['color']};">
            <div>
                <span class="time-badge">[{item['time']}]</span>
                <span class="ai-badge" style="background-color: {ai['color']};">
                    {ai['label']} {int(ai['score']*100)}%
                </span>
                <span class="news-text">{item['text']}</span>
                {debug_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

else:
    if not raw_news:
         st.warning("⚠️ Không có dữ liệu hoặc Server đang lọc tin.")

# ==============================================================================
# 5. ĐẾM NGƯỢC (AUTO REFRESH)
# ==============================================================================
REFRESH_SECONDS = 90
footer = st.empty()

for i in range(REFRESH_SECONDS, 0, -1):
    with footer.container():
        st.markdown(f"""
            <div class="countdown-bar">
                ⏳ Auto-refresh in <b style="color: #FFD700;">{i}</b>s 
                <span style="margin-left:10px; opacity:0.7">| Next: {(datetime.datetime.now() + datetime.timedelta(seconds=i)).strftime('%H:%M:%S')}</span>
            </div>
        """, unsafe_allow_html=True)
    time.sleep(1)

st.rerun()
