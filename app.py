import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import json
import re
from deep_translator import GoogleTranslator

# ==============================================================================
# 1. CẤU HÌNH CEREBRAS (INTERNAL KEY)
# ==============================================================================
LLM_API_KEY = "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w"
LLM_MODEL = "gpt-oss-120b" 

try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=LLM_API_KEY)
    AI_AVAILABLE = True
except ImportError:
    st.error("⚠️ Chưa cài thư viện Cerebras! Hãy chạy: pip install cerebras_cloud_sdk")
    AI_AVAILABLE = False
except Exception as e:
    st.error(f"⚠️ Lỗi khởi tạo Cerebras: {e}")
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS (GOLD TRADING THEME)
# ==============================================================================
st.set_page_config(page_title="Gold Signal AI (XAU/USD)", page_icon="🏆", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    
    /* DASHBOARD */
    .dashboard-box {
        background: linear-gradient(145deg, #2A2100, #1a1a1a); /* Tone vàng đen */
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #FFD700;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(255, 215, 0, 0.2);
    }
    
    /* CARD TIN TỨC */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 5px solid #6B7280;
        transition: all 0.5s ease;
    }
    
    /* BADGES */
    .ai-badge { font-weight: 800; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    
    /* ANIMATION */
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    .ai-loading { color: #F59E0B; font-style: italic; font-size: 0.85em; animation: pulse 1.5s infinite; display: block; margin-top: 5px; }
    
    .ai-reason { display: block; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #374151; color: #F59E0B; font-size: 0.9em; font-style: italic; }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def translate_to_english(text):
    try:
        if not text or len(text) < 2: return text
        return GoogleTranslator(source='auto', target='en').translate(text)
    except: return text

def get_news_data():
    SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://vnwallstreet.com/", "Accept": "application/json"}
    try:
        ts = int(time.time() * 1000)
        # Giữ nguyên full tham số để không lỗi 400
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        return resp.json().get('data', []) if resp.status_code == 200 else []
    except: return []

# ==============================================================================
# 4. CORE AI: GOLD TRADING EXPERT
# ==============================================================================
def analyze_news_batch(news_list):
    if not AI_AVAILABLE or not news_list: return []
    
    # 1. Input (Dịch sang Anh)
    content_str = ""
    for idx, item in enumerate(news_list):
        raw = (item.get('title') or item.get('content') or "").strip()
        eng = translate_to_english(raw)
        content_str += f"ID {idx}: {eng}\n"

    # 2. System Prompt (CHUYÊN GIA VÀNG XAU/USD)
    # Logic:
    # - War/Instability/Rate Cut -> BUY XAU/USD
    # - Strong US Economy/Rate Hike/Peace -> SELL XAU/USD
    system_prompt = """
    You are a Professional Gold Trader (XAU/USD Strategist).
    
    TASK: Analyze the provided news for their specific impact on Gold Price (XAU/USD).
    
    LOGIC:
    - Bad US Economy / War / Uncertainty / Rate Cuts -> BUY GOLD
    - Good US Economy / High Dollar / Peace / Rate Hikes -> SELL GOLD
    
    OUTPUT FORMAT:
    Return ONLY a valid JSON Array. No markdown.
    Schema: 
    [
      {
        "id": int, 
        "signal": "BUY" | "SELL" | "SIDEWAY", 
        "score": float (0.1-0.99 confidence), 
        "reason_vi": "Vietnamese explanation specific to XAU (max 15 words)"
      }
    ]
    """
    try:
        # GỌI CEREBRAS SDK
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_str}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        
        raw = response.choices[0].message.content
        
        # Clean JSON
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1]
            
        return json.loads(json_str)
        
    except Exception as e:
        return []

# ==============================================================================
# 5. MAIN APP LOGIC
# ==============================================================================
st.title(f"🏆 Gold Signal AI (XAU/USD)")
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=7))

# 1. LẤY DỮ LIỆU
raw_news = get_news_data()

if raw_news:
    # --- BƯỚC 1: HIỂN THỊ NGAY (GRAY PHASE) ---
    news_placeholder = st.empty()
    
    with news_placeholder.container():
        st.info("⏳ Đang quét dữ liệu thị trường...")
        for item in raw_news:
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            text = (item.get('title') or item.get('content') or "").strip()
            
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid #4B5563;">
                <span class="time-badge">[{t_str}]</span>
                <span class="ai-loading">⚡ Analyzing XAU Impact...</span>
                <div class="news-text">{text}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- BƯỚC 2: AI PHÂN TÍCH (XAU/USD) ---
    batch_results = analyze_news_batch(raw_news)

    # --- BƯỚC 3: CẬP NHẬT TÍN HIỆU (COLOR PHASE) ---
    with news_placeholder.container():
        scores = []
        display_items = []
        
        for idx, item in enumerate(raw_news):
            # Mặc định
            ai_info = {"signal": "SIDEWAY", "score": 0, "reason": "Không rõ xu hướng", "color": "#6B7280"}
            
            matched = None
            if batch_results:
                for res in batch_results:
                    if res.get('id') == idx: matched = res; break
                if not matched and idx < len(batch_results): matched = batch_results[idx]
            
            if matched:
                sig = str(matched.get("signal", "SIDEWAY")).upper()
                scr = float(matched.get("score", 0))
                reason = matched.get("reason_vi", "")
                
                # Logic Màu sắc Giao dịch
                if "BUY" in sig:
                    ai_info = {"signal": "BUY GOLD", "score": scr, "reason": reason, "color": "#10B981"} # Xanh lá = Mua
                    scores.append(scr) # Cộng điểm cho phe Mua
                elif "SELL" in sig:
                    ai_info = {"signal": "SELL GOLD", "score": scr, "reason": reason, "color": "#EF4444"} # Đỏ = Bán
                    scores.append(-scr) # Trừ điểm cho phe Bán
                else:
                    ai_info = {"signal": "SIDEWAY", "score": scr, "reason": reason, "color": "#FFD700"} # Vàng = Đi ngang
                    scores.append(0)

            # Re-process Time & Text
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            
            text = (item.get('title') or item.get('content') or "").strip()
            
            display_items.append({"time": t_str, "text": text, "ai": ai_info})

        # --- DASHBOARD LOGIC (XAU/USD) ---
        avg = statistics.mean(scores) if scores else 0
        
        # Ngưỡng tín hiệu
        if avg > 0.15: 
            trend = "LONG / BUY GOLD 📈"
            main_color = "#10B981" # Xanh
            advice = "Tin tức hỗ trợ giá Vàng tăng (USD yếu/Rủi ro cao)"
        elif avg < -0.15: 
            trend = "SHORT / SELL GOLD 📉"
            main_color = "#EF4444" # Đỏ
            advice = "Tin tức gây áp lực giảm Vàng (USD mạnh/Kinh tế tốt)"
        else: 
            trend = "SIDEWAY / WAIT ⚠️"
            main_color = "#FFD700" # Vàng
            advice = "Thị trường chưa rõ xu hướng hoặc tin trái chiều"

        st.markdown(f"""
        <div class="dashboard-box">
            <h2 style="color:{main_color}; margin:0; text-shadow: 0 0 10px {main_color}44;">{trend}</h2>
            <div style="color:#ddd; margin-top:5px;">Signal Strength: {avg:.2f}</div>
            <div style="color:#bbb; font-size:0.9em; margin-top:10px; font-style:italic;">{advice}</div>
        </div>
        """, unsafe_allow_html=True)

        # Render List
        for item in display_items:
            ai = item['ai']
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid {ai['color']};">
                <span class="time-badge">[{item['time']}]</span>
                <span class="ai-badge" style="background-color: {ai['color']};">{ai['signal']} {int(ai['score']*100)}%</span>
                <div class="news-text">{item['text']}</div>
                <span class="ai-reason">💡 {ai['reason']}</span>
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ Không có dữ liệu tin tức.")

# Auto Refresh
cnt = st.empty()
for i in range(120, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Cập nhật sau {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
