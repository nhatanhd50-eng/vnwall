import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import json
import re

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
# 2. GIAO DIỆN DARK UI
# ==============================================================================
st.set_page_config(page_title=f"VnWallStreet x {LLM_MODEL}", page_icon="🧠", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    .dashboard-box { background: linear-gradient(145deg, #1f2937, #111827); padding: 20px; border-radius: 12px; border: 1px solid #374151; text-align: center; margin-bottom: 25px; }
    .news-card { background-color: #161b22; padding: 15px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #6B7280; }
    .ai-badge { font-weight: 800; padding: 3px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    .ai-reason { display: block; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #374151; color: #F59E0B; font-size: 0.9em; font-style: italic; }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. CORE: HÀM AI VỚI PROMPT "THÉP"
# ==============================================================================
def analyze_news_batch(news_list):
    if not AI_AVAILABLE or not news_list: return []

    # 1. PHÂN ĐOẠN DỮ LIỆU RÕ RÀNG CHO AI
    news_content_str = ""
    for idx, item in enumerate(news_list):
        text = (item.get('title') or item.get('content') or "").strip()
        # Đánh dấu rõ ràng ID cho từng tin
        news_content_str += f"--- News Item ID {idx} ---\nContent: {text}\n\n"

    # 2. PROMPT CỰC KỲ CHI TIẾT
    system_prompt = """
    You are a strictly automated JSON generator. You are NOT a chatbot.
    
    TASK:
    Analyze the provided list of financial news items (Vietnam Stock Market & Macro).
    
    OUTPUT FORMAT:
    Return a RAW JSON Array of objects. Do not include markdown code blocks (```json). Do not write any intro/outro text.
    
    SCHEMA FOR EACH OBJECT:
    {
      "id": <integer, MUST match the input News Item ID>,
      "sentiment": "BULLISH" or "BEARISH" or "NEUTRAL",
      "score": <float, 0.1 to 0.99 reflecting confidence>,
      "reason_vi": "<Vietnamese string: Explain impact on USD/Stocks in max 15 words>"
    }
    """

    try:
        # Gọi API
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": news_content_str}
            ],
            temperature=0.1, # Giảm sáng tạo để tăng độ chính xác
            max_tokens=4000
        )
        
        raw_content = response.choices[0].message.content.strip()
        
        # --- DEBUG: In ra câu trả lời thô của AI để kiểm tra ---
        # (Nếu bạn thấy nó in ra text linh tinh thì do Model chưa nghe lời)
        # st.expander("🔍 AI Raw Response (Debug)", expanded=False).code(raw_content)

        # 3. XỬ LÝ LỖI JSON (AUTO FIX)
        # Tìm đoạn bắt đầu bằng [ và kết thúc bằng ]
        match = re.search(r'\[.*\]', raw_content, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
        else:
            # Nếu không tìm thấy [], thử parse trực tiếp
            return json.loads(raw_content)
        
    except Exception as e:
        st.error(f"⚠️ AI Parse Error: {e}")
        return []

# ==============================================================================
# 4. DATA FETCHING
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
# 5. MAIN LOGIC
# ==============================================================================
st.title(f"⚡ VNWallStreet x {LLM_MODEL}")
CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=7))

raw_news = get_news_data()

if raw_news:
    
    # 2. Gửi AI phân tích (Batch)
    ai_results_map = {}
    
    with st.spinner(f"🚀 AI đang đọc {len(raw_news)} tin tức..."):
        batch_results = analyze_news_batch(raw_news)
        
        if batch_results:
            for item in batch_results:
                if isinstance(item, dict) and 'id' in item:
                    ai_results_map[item['id']] = item

    # 3. Hiển thị
    scores = []
    display_items = []
    
    for idx, item in enumerate(raw_news):
        # Mặc định
        ai_info = {"sentiment": "NEUTRAL", "score": 0, "reason": "AI chưa nhận định được", "color": "#6B7280"}
        
        # Khớp kết quả
        if idx in ai_results_map:
            res = ai_results_map[idx]
            sent = str(res.get("sentiment", "NEUTRAL")).upper()
            scr = float(res.get("score", 0))
            reason = res.get("reason_vi", "")
            
            if "BULL" in sent or "POS" in sent:
                ai_info = {"sentiment": "BULLISH", "score": scr, "reason": reason, "color": "#10B981"}
                scores.append(scr)
            elif "BEAR" in sent or "NEG" in sent:
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

    # Dashboard
    avg = statistics.mean(scores) if scores else 0
    if avg > 0.15: mood="RISK ON 🟢"; color="#10B981"; msg="Thị trường Tích cực -> Bán USD, Mua Chứng"
    elif avg < -0.15: mood="RISK OFF 🔴"; color="#EF4444"; msg="Thị trường Tiêu cực -> Mua USD/Vàng"
    else: mood="SIDEWAY ⚪"; color="#9CA3AF"; msg="Thị trường đi ngang"
    
    st.markdown(f"""
    <div class="dashboard-box">
        <h2 style="color:{color}; margin:0;">{mood}</h2>
        <div style="color:#ddd;">Confidence: {avg:.2f}</div>
        <div style="color:#999; font-size:0.9em; margin-top:5px;">{msg}</div>
    </div>
    """, unsafe_allow_html=True)
    
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
    cnt.markdown(f"<div class='countdown-bar'>⏳ Refresh in {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
