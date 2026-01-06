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
# 1. CẤU HÌNH HỆ THỐNG (AI & API)
# ==============================================================================
LLM_API_KEY = "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w"
LLM_BASE_URL = "https://api.cerberus.xyz/v1" 

# Danh sách Model (Ưu tiên model lớn để hiểu ngữ cảnh chính trị)
MODEL_LIST = [
    "gpt-oss-120b", 
    "llama-3.1-70b-instruct",
    "qwen-3-235b-a22b-instruct-2507"
]

# Khởi tạo Client Cerebras
try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=LLM_API_KEY)
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS (THEME GOLD PRO)
# ==============================================================================
st.set_page_config(page_title="Gold Signal Pro", page_icon="🏆", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    
    /* CONTROL PANEL */
    .control-panel {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #30363d;
    }
    
    /* DASHBOARD */
    .dashboard-box {
        background: linear-gradient(145deg, #2A2100, #1a1a1a);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #FFD700;
        text-align: center;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(255, 215, 0, 0.2);
    }
    
    /* NEWS CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 15px;
        border-left: 5px solid #6B7280;
        transition: all 0.5s ease;
    }
    
    .ai-badge { font-weight: 800; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    .ai-loading { color: #F59E0B; font-style: italic; font-size: 0.85em; display: block; margin-top: 5px; animation: pulse 1.5s infinite; }
    .ai-reason { display: block; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #374151; color: #F59E0B; font-size: 0.9em; font-style: italic; }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 30px; padding: 10px; background: #0d1117; border-radius: 8px; }
    
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. HELPER FUNCTIONS (DỊCH & LẤY TIN)
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text, target='en'):
    if target == 'vi': return text
    try:
        if not text or len(text) < 2: return text
        return GoogleTranslator(source='auto', target=target).translate(text)
    except: return text

def get_news_data():
    SECRET_KEY = "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123"
    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://vnwallstreet.com/", "Accept": "application/json"}
    try:
        ts = int(time.time() * 1000)
        # Full params để tránh lỗi 400
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
# 4. CORE AI: CONTEXT-AWARE ANALYSIS (QUAN TRỌNG NHẤT)
# ==============================================================================
def analyze_news_with_context(news_list, lang_instruction):
    if not AI_AVAILABLE or not news_list: return [], None
    
    # 1. Gom toàn bộ tin thành 1 khối văn bản (Context)
    content_str = ""
    for idx, item in enumerate(news_list):
        raw = (item.get('title') or item.get('content') or "").strip()
        eng = cached_translate(raw, 'en') # Dịch sang Anh cho AI
        content_str += f"ID {idx}: {eng}\n"

    # 2. Prompt "Thần thánh": Yêu cầu AI nhìn toàn cảnh
    system_prompt = f"""
    You are an Elite Gold Trading Algorithm (XAU/USD).
    
    STEP 1: CONTEXT SCAN
    Read ALL news items together to understand the situation.
    - If you see gunfire/tanks/coups (e.g. Venezuela) -> This is POLITICAL UNREST -> SIGNAL: BUY GOLD.
    - If you see War (Russia/Ukraine) -> SIGNAL: BUY GOLD (Safe Haven).
    - If you see US Rate Cuts -> SIGNAL: BUY GOLD.
    - If you see Strong US Economy -> SIGNAL: SELL GOLD.
    
    STEP 2: SIGNAL ASSIGNMENT
    Assign a signal to EACH news ID based on the global context found in Step 1.
    
    OUTPUT: Valid JSON Array ONLY.
    Schema: 
    [
      {{
        "id": int, 
        "signal": "BUY"|"SELL"|"SIDEWAY", 
        "score": float (0.1-0.99), 
        "reason": "Explain in {lang_instruction} (max 15 words)"
      }}
    ]
    """
    
    # 3. Fallback Loop (Thử lần lượt các model nếu lỗi)
    active_model = None
    final_result = []

    for model_name in MODEL_LIST:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content_str}],
                temperature=0.1, max_tokens=4000
            )
            raw = response.choices[0].message.content
            # Clean JSON
            json_str = raw.split("```json")[1].split("```")[0] if "```json" in raw else raw
            # Cắt phần thừa
            if "]" in json_str: json_str = json_str[:json_str.rfind("]")+1]
            
            final_result = json.loads(json_str)
            active_model = model_name
            break # Thành công thì thoát
        except Exception:
            continue # Lỗi thì thử model tiếp theo

    return final_result, active_model

# ==============================================================================
# 5. MAIN LOGIC (APP)
# ==============================================================================
st.title(f"🏆 Gold Signal Pro")

# --- CONTROL PANEL (ĐẦY ĐỦ TÍNH NĂNG) ---
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    
    with c1:
        # Chọn Ngôn ngữ
        LANGUAGES = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        sel_lang = st.selectbox("Ngôn ngữ / Language:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        ai_lang_instruct = "Vietnamese" if target_lang == 'vi' else "English"

    with c2:
        # Chọn Múi giờ
        TIMEZONES = {"Vietnam (UTC+7)": 7, "New York (UTC-5)": -5, "London (UTC+0)": 0}
        sel_tz = st.selectbox("Múi giờ / Timezone:", list(TIMEZONES.keys()))
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=TIMEZONES[sel_tz]))

    with c3:
        # Nút Refresh
        st.write("") 
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# 1. LẤY DỮ LIỆU
raw_news = get_news_data()

if raw_news:
    # --- PHASE 1: HIỂN THỊ XÁM (LOADING) ---
    news_placeholder = st.empty()
    
    with news_placeholder.container():
        st.info(f"⏳ Scanning Market Context in {sel_tz}...")
        for item in raw_news:
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            
            # Hiển thị theo ngôn ngữ chọn
            raw_text = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(raw_text, target_lang)
            
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid #4B5563;">
                <span class="time-badge">[{t_str}]</span>
                <span class="ai-loading">⚡ Analyzing Geopolitical Risks...</span>
                <div class="news-text">{display_text}</div>
            </div>
            """, unsafe_allow_html=True)

    # --- PHASE 2: AI ANALYZE (CHẠY NGẦM) ---
    batch_results, used_model = analyze_news_with_context(raw_news, ai_lang_instruct)

    # --- PHASE 3: HIỂN THỊ MÀU (RESULT) ---
    with news_placeholder.container():
        scores = []
        display_items = []
        
        # Mapping Data
        for idx, item in enumerate(raw_news):
            ai_info = {"signal": "SIDEWAY", "score": 0, "reason": "No Signal", "color": "#6B7280"}
            
            matched = None
            if batch_results:
                # Tìm ID chính xác
                for res in batch_results:
                    if res.get('id') == idx: matched = res; break
                # Fallback vị trí
                if not matched and idx < len(batch_results): matched = batch_results[idx]
            
            if matched:
                sig = str(matched.get("signal", "SIDEWAY")).upper()
                scr = float(matched.get("score", 0))
                reason = matched.get("reason", "")
                
                if "BUY" in sig: 
                    ai_info = {"signal": "BUY GOLD", "score": scr, "reason": reason, "color": "#10B981"}
                    scores.append(scr)
                elif "SELL" in sig: 
                    ai_info = {"signal": "SELL GOLD", "score": scr, "reason": reason, "color": "#EF4444"}
                    scores.append(-scr)
                else: 
                    ai_info = {"signal": "SIDEWAY", "score": scr, "reason": reason, "color": "#FFD700"}
                    scores.append(0)

            # Re-process for final render
            try:
                ts = int(item.get('createtime') or 0)
                if ts > 1000000000000: ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except: t_str = "--:--"
            
            raw_text = (item.get('title') or item.get('content') or "").strip()
            display_text = cached_translate(raw_text, target_lang)
            
            display_items.append({"time": t_str, "text": display_text, "ai": ai_info})

        # Dashboard Logic
        avg = statistics.mean(scores) if scores else 0
        if avg > 0.15: trend="LONG / BUY GOLD 📈"; color="#10B981"; msg="Bất ổn Chính trị / USD Suy yếu"
        elif avg < -0.15: trend="SHORT / SELL GOLD 📉"; color="#EF4444"; msg="Kinh tế ổn định / USD Mạnh lên"
        else: trend="SIDEWAY / WAIT ⚠️"; color="#FFD700"; msg="Chưa có tin tức dẫn dắt xu hướng"

        model_status = f"✅ Model: {used_model}" if used_model else "❌ AI Busy"

        st.markdown(f"""
        <div class="dashboard-box">
            <h2 style="color:{color}; margin:0; text-shadow: 0 0 10px {color}44;">{trend}</h2>
            <div style="color:#ddd; margin-top:5px;">Trend Strength: {avg:.2f}</div>
            <div style="color:#bbb; font-size:0.9em; margin-top:10px; font-style:italic;">{msg}</div>
            <div style="font-size:0.7em; color:#555; margin-top:15px; border-top:1px solid #333; padding-top:5px;">{model_status}</div>
        </div>
        """, unsafe_allow_html=True)

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

# Auto Refresh 120s
cnt = st.empty()
for i in range(120, 0, -1):
    cnt.markdown(f"<div class='countdown-bar'>⏳ Auto-refresh in {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
