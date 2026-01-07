import streamlit as st
import hashlib
import time
import requests
import datetime
import statistics
import json
import re
import sqlite3
from deep_translator import GoogleTranslator

# Thay thế TradingView bằng Yahoo Finance (Đơn giản, không cần Cookie)
try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

# ==============================================================================
# 1. CẤU HÌNH HỆ THỐNG (GLOBAL CONFIG)
# ==============================================================================
# --- CẤU HÌNH THỜI GIAN REFRESH (FIX LỖI NAME ERROR) ---
AUTO_REFRESH_SECONDS = 120  # Tự động làm mới sau 120 giây

# SECRETS
def _get_secret(name, default=""):
    try: return str(st.secrets.get(name, "")).strip() or default
    except: return default

LLM_API_KEY = _get_secret("CEREBRAS_API_KEY", "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w")
VNWALLSTREET_SECRET_KEY = _get_secret("VNWALLSTREET_SECRET_KEY", "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123")
LLM_MODEL = "gpt-oss-120b"

# Danh sách model fallback
MODEL_LIST = [LLM_MODEL, "llama-3.1-70b-instruct", "qwen-3-235b-a22b-instruct-2507"]

DB_PATH = "gold_ai.db"
PROMPT_VERSION = "v6_final_stable"

# Khởi tạo Client Cerebras
try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=LLM_API_KEY)
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS
# ==============================================================================
st.set_page_config(page_title="Gold AI Pro", page_icon="🏆", layout="centered")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; }
    
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
    
    /* CONTROL PANEL */
    .control-panel {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #30363d;
    }
    
    /* NEWS CARD */
    .news-card {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 5px solid #6B7280;
        transition: all 0.5s ease;
    }
    
    .ai-badge { font-weight: 800; padding: 4px 8px; border-radius: 4px; color: white; font-size: 0.75em; margin-right: 8px; text-transform: uppercase; }
    .ai-reason { display: block; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #374151; color: #F59E0B; font-size: 0.9em; font-style: italic; }
    .time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
    .news-text { color: #e6edf3; font-size: 15px; line-height: 1.5; font-weight: 500; }
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 20px; padding: 10px; background: #0d1117; border-radius: 8px; border: 1px solid #333; }
    
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    .ai-loading { color: #F59E0B; font-style: italic; animation: pulse 1.5s infinite; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. DATABASE & CACHE
# ==============================================================================
@st.cache_resource
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    # Tạo bảng nếu chưa có
    c.execute("CREATE TABLE IF NOT EXISTS news (fp TEXT PRIMARY KEY, ts INTEGER, text TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS trans (fp TEXT, lang TEXT, text TEXT, PRIMARY KEY(fp, lang))")
    c.execute("CREATE TABLE IF NOT EXISTS scores (fp TEXT, ver TEXT, model TEXT, signal TEXT, score REAL, reason TEXT, PRIMARY KEY(fp, ver))")
    conn.commit()
    return conn

def get_fingerprint(ts, text):
    raw = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha1(f"{ts}|{raw[:100]}".encode("utf-8")).hexdigest()

def db_get_trans(conn, fp, lang):
    r = conn.cursor().execute("SELECT text FROM trans WHERE fp=? AND lang=?", (fp, lang)).fetchone()
    return r[0] if r else None

def db_set_trans(conn, fp, lang, text):
    conn.cursor().execute("INSERT OR REPLACE INTO trans VALUES (?,?,?)", (fp, lang, text))
    conn.commit()

def db_get_score(conn, fp):
    r = conn.cursor().execute("SELECT signal, score, reason, model FROM scores WHERE fp=? AND ver=?", (fp, PROMPT_VERSION)).fetchone()
    return {"signal": r[0], "score": r[1], "reason": r[2], "model": r[3]} if r else None

def db_set_score(conn, fp, model, data):
    conn.cursor().execute("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?)", 
                          (fp, PROMPT_VERSION, model, data['signal'], data['score'], data['reason']))
    conn.commit()

@st.cache_data(ttl=3600, show_spinner=False)
def translate_text(text, lang):
    if not text or lang == 'vi': return text
    try: return GoogleTranslator(source='auto', target=lang).translate(text)
    except: return text

# ==============================================================================
# 4. MARKET SNAPSHOT (YAHOO FINANCE)
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_market_snapshot():
    """Lấy dữ liệu Vĩ mô từ Yahoo Finance (Không cần cookie)"""
    if not YF_AVAILABLE:
        return {"error": "Thiếu thư viện yfinance"}
    
    tickers = {
        "DXY": "DX-Y.NYB",   
        "US10Y": "^TNX",     
        "VIX": "^VIX",       
        "GOLD": "GC=F",      
        "SILVER": "SI=F"     
    }
    
    snapshot = {"data": {}, "text": "", "error": None}
    snap_text = "MARKET CONTEXT (Real-time):\n"
    
    try:
        data = yf.download(tickers=list(tickers.values()), period="5d", interval="1d", progress=False)
        
        for name, ticker in tickers.items():
            try:
                # Xử lý MultiIndex của YFinance mới
                if len(tickers) > 1:
                    closes = data['Close'][ticker].dropna()
                else:
                    closes = data['Close'].dropna()
                
                if len(closes) >= 2:
                    current = closes.iloc[-1]
                    prev = closes.iloc[-2]
                    change_pct = ((current - prev) / prev) * 100
                    
                    snapshot["data"][name] = {
                        "price": round(current, 2),
                        "change": round(change_pct, 2)
                    }
                    snap_text += f"- {name}: {current:.2f} ({change_pct:+.2f}%)\n"
            except:
                continue
        snapshot["text"] = snap_text
    except Exception as e:
        snapshot["error"] = str(e)
        
    return snapshot

# ==============================================================================
# 5. FETCH NEWS (API VNWALLSTREET)
# ==============================================================================
def fetch_news():
    try:
        ts = int(time.time() * 1000)
        params = {"limit": 20, "uid": "-1", "start": "0", "token_": "", "key_": VNWALLSTREET_SECRET_KEY, "time_": ts}
        sorted_keys = sorted(params.keys())
        query = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode('utf-8')).hexdigest().upper()
        del params['key_']
        params['sign_'] = sign
        
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://vnwallstreet.com/", "Accept": "application/json"}
        resp = requests.get("https://vnwallstreet.com/api/inter/newsFlash/page", params=params, headers=headers, timeout=10)
        return resp.json().get('data', []) if resp.status_code == 200 else []
    except: return []

# ==============================================================================
# 6. CORE AI (CONTEXT AWARE + SMART FILTER)
# ==============================================================================
def run_ai_analysis(news_list, lang_instruction, market_text):
    if not AI_AVAILABLE: return [], None
    
    # Gom tin vào Prompt
    content_str = market_text + "\nNEWS LIST:\n"
    for item in news_list:
        # ID này là index trong list batch
        content_str += f"ID {item['batch_id']}: {item['text_en']}\n"

    system_prompt = f"""
    You are an Elite Gold Trader AI.
    
    LOGIC:
    1. **DXY/Yields Inverse:** If DXY or US10Y UP -> Gold DOWN (SELL). If DOWN -> Gold UP (BUY).
    2. **Crisis/War:** Any war/coup/instability -> Gold UP (BUY).
    3. **Smart Filter:** If news is NOT about USD, Fed, US Economy, Geopolitics, or Metals -> SIGNAL "SIDEWAY", SCORE 0.0.
    4. **Silver:** Moves same as Gold.
    
    TASK: Analyze the provided news list based on Market Context.
    
    OUTPUT: JSON Array ONLY. 
    Schema: [{{"id": int, "signal": "BUY"|"SELL"|"SIDEWAY", "score": float, "reason": "Explain in {lang_instruction} (max 15 words)"}}]
    """
    
    for model in MODEL_LIST:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role":"system","content":system_prompt}, {"role":"user","content":content_str}],
                temperature=0.1, max_tokens=4000
            )
            raw = resp.choices[0].message.content
            # Clean JSON
            json_str = raw.split("```json")[1].split("```")[0] if "```json" in raw else raw
            # Fix lỗi cắt cụt
            if "]" not in json_str: json_str += "]" 
            return json.loads(json_str), model
        except: continue
        
    return [], None

# ==============================================================================
# 7. MAIN APP (LOGIC CHÍNH)
# ==============================================================================
conn = init_db()
st.title("🏆 Gold & Silver AI Intelligence")

# --- CONTROL PANEL ---
with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        lang = st.selectbox("Ngôn ngữ:", ["vi", "en"])
        ai_lang = "Vietnamese" if lang == 'vi' else "English"
    with c2:
        tz = st.selectbox("Múi giờ:", [7, -5, 0, 9], format_func=lambda x: f"UTC{x:+}")
        cur_tz = datetime.timezone(datetime.timedelta(hours=tz))
    with c3:
        st.write(""); 
        if st.button("🔄 REFRESH", use_container_width=True): st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- MARKET SNAPSHOT (DISPLAY) ---
snapshot = get_market_snapshot()
if "data" in snapshot and snapshot["data"]:
    cols = st.columns(5)
    metrics = ["DXY", "US10Y", "VIX", "GOLD", "SILVER"]
    for i, m in enumerate(metrics):
        if m in snapshot["data"]:
            d = snapshot["data"][m]
            # Màu sắc: DXY/US10Y tăng là xấu cho Gold (Đỏ), giảm là tốt (Xanh)
            is_inverse = m in ["DXY", "US10Y"]
            # Logic: Nếu DXY tăng -> Đỏ. Nếu Gold tăng -> Xanh.
            # Delta color 'inverse' nghĩa là Tăng = Đỏ.
            color = "inverse" if is_inverse else "normal"
            with cols[i]:
                st.metric(m, f"{d['price']}", f"{d['change']}%", delta_color=color)

# --- NEWS PROCESSING ---
raw_data = fetch_news()
if raw_data:
    processed_list = []
    missing_score_indices = []
    
    # 1. Dedup & Translate
    for idx, item in enumerate(raw_data):
        ts = int(item.get('createtime') or 0)
        if ts > 1000000000000: ts = int(ts/1000)
        raw_text = (item.get('title') or item.get('content') or "").strip()
        fp = get_fingerprint(ts, raw_text)
        
        # Translation
        en_text = db_get_trans(conn, fp, "en")
        if not en_text:
            en_text = translate_text(raw_text, "en")
            db_set_trans(conn, fp, "en", en_text)
            
        disp_text = db_get_trans(conn, fp, lang)
        if not disp_text:
            disp_text = translate_text(raw_text, lang)
            db_set_trans(conn, fp, lang, disp_text)
            
        # Score
        score_data = db_get_score(conn, fp)
        
        # Lưu vào list để hiển thị
        item_data = {
            "id": idx, "fp": fp, "ts": ts, "text_en": en_text, "text_disp": disp_text, "score": score_data
        }
        processed_list.append(item_data)
        
        # Nếu chưa có điểm thì thêm vào danh sách cần chấm
        if not score_data:
            # Thêm trường batch_id để AI biết thứ tự
            item_data['batch_id'] = len(missing_score_indices) 
            missing_score_indices.append(item_data)

    # 2. Show UI (Gray Phase - Loading)
    placeholder = st.empty()
    
    # 3. AI Run (Incremental - Chỉ chạy tin mới)
    if missing_score_indices:
        # Gọi AI với Context thị trường
        results, model = run_ai_analysis(missing_score_indices, ai_lang, snapshot.get("text", ""))
        
        if results:
            # Map kết quả về list chính
            res_map = {r.get('id'): r for r in results if 'id' in r} # id ở đây là batch_id
            
            for item in missing_score_indices:
                batch_id = item['batch_id']
                res = res_map.get(batch_id)
                
                if res:
                    sc = {"signal": res.get("signal", "SIDEWAY"), 
                          "score": res.get("score", 0), 
                          "reason": res.get("reason", "")}
                    
                    # Update DB
                    db_set_score(conn, item["fp"], model, sc)
                    # Update List hiện tại (để hiển thị ngay)
                    processed_list[item['id']]["score"] = sc

    # 4. Render Final (Có màu)
    with placeholder.container():
        scores = []
        display_items = []
        
        for item in processed_list:
            sc = item["score"] or {"signal": "SIDEWAY", "score": 0, "reason": ""}
            
            sig = sc.get("signal", "SIDEWAY").upper()
            val = float(sc.get("score", 0))
            reason = sc.get("reason", "")
            
            # Filter Logic: Chỉ tính điểm tin Valid (Khác 0 và khác Sideway)
            if val > 0 and "SIDEWAY" not in sig:
                if sig == "BUY": scores.append(val)
                elif sig == "SELL": scores.append(-val)
            
            # Màu sắc UI
            if sig == "BUY" and val > 0: color = "#10B981"
            elif sig == "SELL" and val > 0: color = "#EF4444"
            else: color = "#6B7280"
            
            t_str = datetime.datetime.fromtimestamp(item["ts"], cur_tz).strftime("%H:%M")
            display_items.append({"time": t_str, "text": item["text_disp"], "sig": sig, "scr": val, "r": reason, "c": color})

        # Dashboard Logic
        avg = statistics.mean(scores) if scores else 0
        if avg > 0.15: trend="BUY GOLD 📈"; clr="#10B981"; msg="DXY/Yields Giảm hoặc Rủi ro tăng"
        elif avg < -0.15: trend="SELL GOLD 📉"; clr="#EF4444"; msg="DXY/Yields Tăng mạnh, Kinh tế tốt"
        else: trend="SIDEWAY ⚠️"; clr="#FFD700"; msg="Thị trường đi ngang / Chờ tin"
        
        st.markdown(f"""
        <div class="dashboard-box">
            <h2 style="color:{clr}; margin:0;">{trend}</h2>
            <div style="color:#ddd;">Signal Strength: {avg:.2f}</div>
            <div style="color:#999; font-size:0.9em;">{msg}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # List Logic
        for item in display_items:
            # Làm mờ tin rác
            op = "1.0" if item["scr"] > 0 else "0.6"
            st.markdown(f"""
            <div class="news-card" style="border-left: 5px solid {item['c']}; opacity: {op};">
                <span class="time-badge">[{item['time']}]</span>
                <span class="ai-badge" style="background:{item['c']}">{item['sig']} {int(item['scr']*100)}%</span>
                <div class="news-text">{item['text']}</div>
                <span class="ai-reason">💡 {item['r']}</span>
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ No Data. Vui lòng kiểm tra kết nối API.")

# Auto Refresh Countdown (ĐÃ SỬA LỖI NAME ERROR)
time.sleep(1)
t = st.empty()
for i in range(AUTO_REFRESH_SECONDS, 0, -1):
    t.markdown(f"<div class='countdown-bar'>⏳ Auto-refresh in {i}s</div>", unsafe_allow_html=True)
    time.sleep(1)
st.rerun()
