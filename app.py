import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import json
import re

# ==============================================================================
# 1. CẤU HÌNH AI (INTERNAL CONFIGURATION)
# ==============================================================================
# Đã điền sẵn thông tin nội bộ của bạn
LLM_API_KEY = "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w"
LLM_BASE_URL = "https://api.cerberus.xyz/v1" 
LLM_MODEL = "gpt-oss-120b" 

# Khởi tạo Client
try:
    from openai import OpenAI
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS (DARK PRO UI)
# ==============================================================================
st.set_page_config(
    page_title=f"VnWallStreet x {LLM_MODEL}", 
    page_icon="🧠", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

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
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }
    .score-text { font-size: 2.2em; font-weight: 900; margin: 10px 0; letter-spacing: 1px;}
    
    /* NEWS CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 5px solid #6B7280;
        transition: transform 0.2s;
    }
    .news-card:hover { transform: translateX(3px); }
    
    /* BADGES */
    .ai-badge { 
        font-weight: 800; 
        padding: 3px 8px; 
        border-radius: 4px; 
        color: white; 
        font-size: 0.75em; 
        margin-right: 8px; 
        text-transform: uppercase; 
        display: inline-block;
    }
    
    .ai-reason { 
        display: block; 
        margin-top: 10px; 
        padding-top: 8px; 
        border-top: 1px dashed #374151; 
        color: #F59E0B; /* Màu cam vàng */
        font-size: 0.9em; 
        font-style: italic; 
        font-family: 'Segoe UI', sans-serif;
    }
    
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; display: inline;}
    
    /* COUNTDOWN */
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; border: 1px solid #30363d;}
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. CORE: HÀM GỌI AI BATCH (GOM TIN)
# ==============================================================================
def analyze_news_batch(news_list):
    """
    Gửi 1 Prompt chứa 20 tin cho Model 120B xử lý 1 lần.
    """
    if not AI_AVAILABLE or not news_list:
        return []

    # 1. Tạo nội dung Prompt
    news_content_str = ""
    for idx, item in enumerate(news_list):
        text = (item.get('title') or item.get('content') or "").strip()
        news_content_str += f"[ID {idx}]: {text}\n"

    # 2. System Prompt (Chỉ đạo AI trả về JSON)
    system_prompt = """
    You are an expert Financial Analyst AI (Hedge Fund Algo).
    Analyze the provided list of financial news items.
    
    OUTPUT REQUIREMENTS:
    1. Return ONLY a valid JSON Array. No markdown, no explanation.
    2. Each object must follow this schema:
       {
         "id": <integer, matching the input ID>,
         "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
         "score": <float, 0.0 to 1.0 confidence>,
         "reason_vi": "<Explain in Vietnamese: Impact on USD/Markets. Max 15 words.>"
       }
    """

    try:
        # Gọi API Cerberus
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": news_content_str}
            ],
            temperature=0.1, # Nhiệt độ thấp để JSON chuẩn
            max_tokens=3000
        )
        
        raw_content = response.choices[0].message.content
        
        # 3. Làm sạch chuỗi JSON (Parser)
        json_str = raw_content.strip()
        # Loại bỏ markdown nếu có
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1]
            
        return json.loads(json_str)
        
    except Exception as e:
        # st.error(f"AI Error: {e}") # Uncomment để debug nếu cần
        return []

# ==============================================================================
# 4. DATA FETCHING (FIXED SIGNATURE - NO ERROR 400)
# ==============================================================================
SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://vnwallstreet.com/",
    "Accept": "application/json"
}

def get_news_data():
    try:
        ts = int(time.time() * 1000)
        # Giữ nguyên đầy đủ tham số để tính Sign đúng
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": SECRET_KEY, "time_": ts}
        
        # Tạo chữ ký
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        
        # Gửi đi
        del params['key_']
        params['sign_'] = sign
        
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        return resp.json().get('data', []) if resp.status_code == 200 else []
    except: return []

# ==============================================================================
# 5. MAIN LOGIC
# ==============================================================================
st.title(f"⚡ VNWallStreet x {LLM_MODEL}")

# Config Timezone
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=7))

# 1. Load Data
raw_news = get_news_data()

if raw_news:
    
    # 2. Xử lý AI (Batch Request)
    ai_results_map = {}
    
    # Hiển thị Spinner
    with st.spinner(f"🚀 AI ({LLM_MODEL}) đang phân tích {len(raw_news)} tin tức..."):
        batch_results = analyze_news_batch(raw_news)
        
        # Chuyển List thành Map để tra cứu theo ID
        if batch_results:
            for item in batch_results:
                if isinstance(item, dict) and 'id' in item:
                    ai_results_map[item['id']] = item

    # 3. Tính toán Dashboard & Hiển thị
    scores = []
    display_items = []
    
    for idx, item in enumerate(raw_news):
        # Default data
        ai_info = {"sentiment": "NEUTRAL", "score": 0, "reason": "Chưa có nhận định", "color": "#6B7280"}
        
        # Map kết quả từ AI
        if idx in ai_results_map:
            res = ai_results_map[idx]
            sent = res.get("sentiment", "NEUTRAL").upper()
            scr = float(res.get("score", 0))
            reason = res.get("reason_vi", "")
            
            if "BULL" in sent:
                ai_info = {"sentiment": "BULLISH", "score": scr, "reason": reason, "color": "#10B981"}
                scores.append(scr)
            elif "BEAR" in sent:
                ai_info = {"sentiment": "BEARISH", "score": scr, "reason": reason, "color": "#EF4444"}
                scores.append(-scr)
            else:
                ai_info = {"sentiment": "NEUTRAL", "score": scr, "reason": reason, "color": "#6B7280"}
                scores.append(0)
        
        # Format Time
        try:
            ts = int(item.get('createtime') or 0)
            if ts > 1000000000000: ts /= 1000
            t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
        except: t_str = "--:--"
        
        display_items.append({
            "time": t_str,
            "text": (item.get('title') or item.get('content') or "").strip(),
            "ai": ai_info
        })

    # --- DASHBOARD RENDER ---
    avg = statistics.mean(scores) if scores else 0
    if avg > 0.15: 
        mood = "RISK ON 🟢"; color = "#10B981"
        msg = "Thị trường Tích cực ➔ Dòng tiền vào Stocks/Crypto. USD giảm."
    elif avg < -0.15: 
        mood = "RISK OFF 🔴"; color = "#EF4444"
        msg = "Thị trường Tiêu cực ➔ Dòng tiền trú ẩn vào USD/Vàng."
    else: 
        mood = "SIDEWAY ⚪"; color = "#9CA3AF"
        msg = "Thị trường đi ngang. Tin tức trái chiều."
    
    st.markdown(f"""
    <div class="dashboard-box">
        <div class="score-text" style="color:{color}">{mood}</div>
        <div style="color:#ddd; font-family:monospace;">AI Confidence Score: {avg:.2f}</div>
        <div style="color:#999; font-size:0.9em; margin-top:10px; font-style:italic;">{msg}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- NEWS LIST RENDER ---
    for item in display_items:
        ai = item['ai']
        st.markdown(f"""
        <div class="news-card" style="border-left: 5px solid {ai['color']};">
            <span class="time-badge">[{item['time']}]</span>
            <span class="ai-badge" style="background-color: {ai['color']};">{ai['sentiment']} {int(ai['score']*100)}%</span>
            <span class="news-text">{item['text']}</span>
            <span class="ai-reason">💡 {ai['reason']}</span>
        </div>
        """, unsafe_allow_html=True)

else:
    st.warning("⚠️ Không lấy được dữ liệu. Kiểm tra lại kết nối.")

# Auto Refresh (120s để AI xử lý kỹ)
cnt = st.empty()
for i in range(120, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Cập nhật sau {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
