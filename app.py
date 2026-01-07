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

# Thay thế TradingView bằng Yahoo Finance
try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

# ==============================================================================
# 1. CẤU HÌNH HỆ THỐNG
# ==============================================================================
# SECRETS (Lấy từ Streamlit Secrets hoặc Environment)
def _get_secret(name, default=""):
    try: return str(st.secrets.get(name, "")).strip() or default
    except: return default

# API Key & Model
LLM_API_KEY = _get_secret("CEREBRAS_API_KEY", "csk-dwtjyxt4yrvdxf2d28fk3x8whdkdtf526njm925enm3pt32w")
VNWALLSTREET_SECRET_KEY = _get_secret("VNWALLSTREET_SECRET_KEY", "zxadpfiadfjapppasdfdddddddddddddfffffffffffffffffdfa3123123123")
LLM_MODEL = "gpt-oss-120b"

# Fallback Models
MODEL_LIST = [LLM_MODEL, "llama-3.1-70b-instruct", "qwen-3-235b-a22b-instruct-2507"]

# Database Config
DB_PATH = "gold_ai.db"
PROMPT_VERSION = "v5_yfinance_context"

# Khởi tạo AI Client
try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=LLM_API_KEY)
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

# ==============================================================================
# 2. GIAO DIỆN & CSS (DARK GOLD THEME)
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
    .countdown-bar { text-align: center; color: #6B7280; margin-top: 20px; padding: 10px; background: #0d1117; border-radius: 8px; }
    
    /* METRICS */
    .metric-container { display: flex; justify-content: space-between; text-align: center; margin-bottom: 10px; }
    .metric-box { background: #161b22; padding: 10px; border-radius: 8px; width: 19%; border: 1px solid #333; }
    .metric-label { font-size: 0.8em; color: #888; }
    .metric-value { font-size: 1.1em; font-weight: bold; color: #eee; }
    .metric-delta-up { color: #10B981; font-size: 0.8em; }
    .metric-delta-down { color: #EF4444; font-size: 0.8em; }
    
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    .ai-loading { color: #F59E0B; font-style: italic; animation: pulse 1.5s infinite; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. DATABASE & UTILS (CACHE LAYER)
# ==============================================================================
@st.cache_resource
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
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
# 4. MARKET SNAPSHOT (YAHOO FINANCE - NO COOKIE NEEDED)
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False) # Cache 5 phút
def get_market_snapshot():
    if not YF_AVAILABLE:
        return {"error": "Thiếu thư viện yfinance"}
    
    # Symbol Map: Name -> YF Ticker
    tickers = {
        "DXY": "DX-Y.NYB",   # Dollar Index
        "US10Y": "^TNX",     # 10Y Yield
        "VIX": "^VIX",       # Volatility
        "GOLD": "GC=F",      # Gold Futures
        "SILVER": "SI=F"     # Silver Futures
    }
    
    snapshot = {"data": {}, "text": "", "error": None}
    snap_text = "MARKET CONTEXT (Yahoo Finance):\n"
    
    try:
        # Download 1 lần cho nhanh
        data = yf.download(tickers=list(tickers.values()), period="5d", interval="1d", progress=False)
        
        # Xử lý dữ liệu (Lấy giá đóng cửa mới nhất và % thay đổi)
        for name, ticker in tickers.items():
            try:
                # Lấy Close price của ticker
                # yfinance trả về MultiIndex columns nếu tải nhiều ticker
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
                else:
                    snapshot["data"][name] = {"price": 0, "change": 0}
            except:
                continue
                
        snapshot["text"] = snap_text
        
    except Exception as e:
        snapshot["error"] = str(e)
        
    return snapshot

# ==============================================================================
# 5. FETCH NEWS (API)
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
    
    # 1. Prepare Input (English)
    content_str = market_text + "\nNEWS LIST:\n"
    for item in news_list:
        content_str += f"ID {item['id']}: {item['text_en']}\n"

    # 2. Prompt (Logic Vàng & Bạc)
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
            json_str = raw.split("```json")[1].split("```")[0] if "```json" in raw else raw
            if "]" in json_str: json_str = json_str[:json_str.rfind("]")+1]
            return json.loads(json_str), model
        except: continue
        
    return [], None

# ==============================================================================
# 7. MAIN APP
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
            color = "inverse" if is_inverse else "normal"
            with cols[i]:
                st.metric(m, f"{d['price']}", f"{d['change']}%", delta_color=color)

# --- NEWS PROCESSING ---
raw_data = fetch_news()
if raw_data:
    # 1. Dedup & Translate (Incremental)
    processed_list = []
    missing_score_indices = []
    
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
        if not score_data: missing_score_indices.append(idx)
        
        processed_list.append({
            "id": idx, "fp": fp, "ts": ts, "text_en": en_text, "text_disp": disp_text, "score": score_data
        })

    # 2. Show UI (Gray Phase)
    placeholder = st.empty()
    
    # 3. AI Run (Only for missing scores)
    if missing_score_indices:
        # Lọc ra các tin cần chấm điểm
        batch_input = [processed_list[i] for i in missing_score_indices]
        
        # Gọi AI với Context thị trường
        results, model = run_ai_analysis(batch_input, ai_lang, snapshot.get("text", ""))
        
        if results:
            res_map = {r.get('id'): r for r in results if 'id' in r}
            for i in missing_score_indices:
                # Map lại ID batch (0,1,2...) về ID gốc của list
                # Trong prompt ta gửi ID theo thứ tự 0..N của batch_input
                # Cần logic map chính xác hơn nếu batch lớn. 
                # Ở đây đơn giản hóa: AI trả về ID khớp với index trong batch input
                
                # Sửa lại logic map ID cho chuẩn batch:
                batch_idx = missing_score_indices.index(i) # Vị trí trong batch
                res = res_map.get(batch_idx) # Lấy kết quả
                
                if res:
                    sc = {"signal": res.get("signal", "SIDEWAY"), 
                          "score": res.get("score", 0), 
                          "reason": res.get("reason", "")}
                    
                    # Update DB & List
                    db_set_score(conn, processed_list[i]["fp"], model, sc)
                    processed_list[i]["score"] = sc

    # 4. Render Final
    with placeholder.container():
        scores = []
        display_items = []
        
        for item in processed_list:
            sc = item["score"] or {"signal": "SIDEWAY", "score": 0, "reason": ""}
            
            sig = sc.get("signal", "SIDEWAY").upper()
            val = float(sc.get("score", 0))
            reason = sc.get("reason", "")
            
            # Logic bỏ qua tin rác (0.0)
            if val > 0 and sig != "SIDEWAY":
                if sig == "BUY": scores.append(val)
                elif sig == "SELL": scores.append(-val)
            
            # Màu sắc
            if sig == "BUY" and val > 0: color = "#10B981"
            elif sig == "SELL" and val > 0: color = "#EF4444"
            else: color = "#6B7280"
            
            # Time
            t_str = datetime.datetime.fromtimestamp(item["ts"], cur_tz).strftime("%H:%M")
            display_items.append({"time": t_str, "text": item["text_disp"], "sig": sig, "scr": val, "r": reason, "c": color})

        # Dashboard
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
        
        # List
        for item in display_items:
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
    st.warning("⚠️ No Data")

# Auto refresh
time.sleep(1)
st.markdown(f"<div class='countdown-bar'>Auto-refresh in {AUTO_REFRESH_SECONDS}s</div>", unsafe_allow_html=True)
time.sleep(AUTO_REFRESH_SECONDS)
st.rerun()
