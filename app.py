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
# 1. CẤU HÌNH AI (INTERNAL KEY)
# ==============================================================================
LLM_API_KEY = "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w"
LLM_BASE_URL = "https://api.cerberus.xyz/v1" 
LLM_MODEL = "gpt-oss-120b" 

try:
    from openai import OpenAI
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS (DARK UI)
# ==============================================================================
st.set_page_config(page_title=f"VnWallStreet x {LLM_MODEL}", page_icon="🧠", layout="centered")

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
    .score-text { font-size: 2em; font-weight: 900; margin: 10px 0; letter-spacing: 1px; }
    
    /* CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 5px solid #6B7280;
        transition: transform 0.2s;
    }
    .news-card:hover { transform: translateX(5px); }
    
    /* BADGES */
    .ai-badge { font-weight: 800; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    .ai-reason { 
        display: block; 
        margin-top: 10px; 
        padding-top: 8px; 
        border-top: 1px dashed #374151; 
        color: #F59E0B; 
        font-size: 0.9em; 
        font-style: italic; 
        font-family: 'Segoe UI', sans-serif;
    }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    
    /* COUNTDOWN */
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. HELPER: DỊCH THUẬT CÓ CACHE (ĐỂ CHUYỂN INPUT SANG TIẾNG ANH)
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def translate_to_english(text):
    """Chuyển tin tức sang tiếng Anh để AI đọc hiểu tốt hơn"""
    try:
        if not text or len(text) < 2: return text
        # Dùng Google Translate dịch sang 'en'
        return GoogleTranslator(source='auto', target='en').translate(text)
    except:
        return text

# ==============================================================================
# 4. CORE: HÀM AI VỚI INPUT TIẾNG ANH (FORCED ENGLISH)
# ==============================================================================
def analyze_news_batch(news_list):
    if not AI_AVAILABLE or not news_list: return [], ""

    # 1. CHUẨN BỊ INPUT (DỊCH SANG TIẾNG ANH)
    # Bước này cực quan trọng: Giúp model 120B phát huy tối đa trí tuệ
    news_content_str = ""
    for idx, item in enumerate(news_list):
        raw_text = (item.get('title') or item.get('content') or "").strip()
        
        # --- QUY TRÌNH DỊCH ---
        english_text = translate_to_english(raw_text)
        
        # Đóng gói vào prompt
        news_content_str += f"ID_{idx}: {english_text}\n"

    # 2. SYSTEM PROMPT
    system_prompt = """
    You are an expert Hedge Fund Algorithm.
    
    INPUT: 
    I will provide a list of financial news headlines in ENGLISH.
    
    TASK:
    Analyze the sentiment and market impact of each news item.
    
    OUTPUT FORMAT:
    Return ONLY a raw JSON Array. Order must match input.
    Schema:
    [
      {
        "id": <integer matching input ID>,
        "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
        "score": <float 0.1 to 0.99 confidence>,
        "reason_vi": "<Translate your reasoning into VIETNAMESE. Explain why (USD/Stocks impact). Max 15 words.>"
      }
    ]
    """

    raw_content = ""
    try:
        # Gọi API
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": news_content_str}
            ],
            temperature=0.1, # Giữ thấp để JSON ổn định
            max_tokens=4000
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # Xử lý JSON (Clean Markdown)
        json_str = raw_content
        if "```json" in json_str: json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str: json_str = json_str.split("```")[1]
        
        # Parse
        # Dùng regex tìm mảng [...]
        match = re.search(r'\[.*\]', json_str, re.DOTALL)
        if match:
            return json.loads(match.group(0)), raw_content
        
        return json.loads(json_str), raw_content

    except Exception as e:
        return [], f"AI Error: {e} | Raw: {raw_content}"

# ==============================================================================
# 5. DATA FETCHING (FULL PARAMS - NO 400 ERROR)
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
        # Giữ nguyên tham số để server vnwallstreet không chặn
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
# 6. MAIN LOGIC
# ==============================================================================
st.title(f"⚡ VNWallStreet x {LLM_MODEL}")
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=7))

# 1. Lấy dữ liệu
raw_news = get_news_data()

if raw_news:
    
    # 2. Xử lý AI (Input Tiếng Anh -> Output Lý do Việt)
    with st.spinner(f"🚀 Translating & Analyzing {len(raw_news)} items with {LLM_MODEL}..."):
        batch_results, debug_raw = analyze_news_batch(raw_news)
    
    # Debug Box (Để kiểm tra xem AI có nhận đúng English không)
    with st.expander("🔍 DEBUG: AI Response", expanded=False):
        st.text(debug_raw)

    scores = []
    display_items = []
    
    # 3. Ghép dữ liệu
    for idx, item in enumerate(raw_news):
        # Mặc định
        ai_info = {"sentiment": "NEUTRAL", "score": 0, "reason": "AI chưa phân tích", "color": "#6B7280"}
        
        # Logic Fallback thông minh:
        # Ưu tiên 1: Tìm theo ID
        matched = None
        if batch_results:
            for res in batch_results:
                if res.get('id') == idx:
                    matched = res
                    break
            # Ưu tiên 2: Lấy theo vị trí (nếu ID sai)
            if not matched and idx < len(batch_results):
                matched = batch_results[idx]
        
        if matched:
            sent = str(matched.get("sentiment", "NEUTRAL")).upper()
            scr = float(matched.get("score", 0))
            reason = matched.get("reason_vi", "") # AI sẽ trả lý do tiếng Việt
            
            if "BULL" in sent:
                ai_info = {"sentiment": "BULLISH", "score": scr, "reason": reason, "color": "#10B981"}
                scores.append(scr)
            elif "BEAR" in sent:
                ai_info = {"sentiment": "BEARISH", "score": scr, "reason": reason, "color": "#EF4444"}
                scores.append(-scr)
            else:
                ai_info = {"sentiment": "NEUTRAL", "score": scr, "reason": reason, "color": "#6B7280"}
                scores.append(0)
        
        # Time
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

    # 4. Render Dashboard
    avg = statistics.mean(scores) if scores else 0
    if avg > 0.15: mood="RISK ON 🟢"; color="#10B981"; msg="Thị trường Tích cực ➔ Dòng tiền vào Stocks"
    elif avg < -0.15: mood="RISK OFF 🔴"; color="#EF4444"; msg="Thị trường Tiêu cực ➔ Dòng tiền vào USD/Vàng"
    else: mood="SIDEWAY ⚪"; color="#9CA3AF"; msg="Thị trường Đi ngang / Chưa rõ xu hướng"
    
    st.markdown(f"""
    <div class="dashboard-box">
        <h2 style="color:{color}; margin:0;">{mood}</h2>
        <div style="color:#ddd;">AI Score: {avg:.2f}</div>
        <div style="color:#999; font-size:0.9em; margin-top:5px;">{msg}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # 5. Render List
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
    st.warning("⚠️ Không có dữ liệu.")

cnt = st.empty()
for i in range(120, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Cập nhật sau {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
