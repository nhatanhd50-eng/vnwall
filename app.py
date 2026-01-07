import os
import re
import json
import time
import hashlib
import datetime
import statistics
import sqlite3
import requests
import streamlit as st
from deep_translator import GoogleTranslator

# optional libs
try:
    import yfinance as yf
    YF_AVAILABLE = True
except Exception:
    YF_AVAILABLE = False

try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except Exception:
    AUTOREFRESH_AVAILABLE = False

# ==============================================================================
# 0) CONFIG
# ==============================================================================
APP_TITLE = "🏆 XAU/USD Intelligence (M15 Snapshot Gate + Incremental + Macro Prompt)"
DB_PATH = "xau_cache.sqlite3"
PROMPT_VERSION = "xau_m15_gate_macro_v1"
FETCH_LIMIT = 20

MODEL_LIST = [
    "gpt-oss-120b",
    "qwen-3-235b-a22b-instruct-2507",
    "qwen-3-32b",
]

# yfinance tickers (NO fallback; if M15 empty => N/A)
YF_TICKERS = {
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "VIX": "^VIX",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
}

DEFAULT_NEWS_REFRESH_SECONDS = 180
DEFAULT_UI_TICK_SECONDS = 5
DEFAULT_YF_DELAY_SECONDS = 1.0
M15_SAFETY_SECONDS = 10

# ==============================================================================
# 1) SECRETS
# ==============================================================================
def _get_secret(name: str, default: str = "") -> str:
    try:
        v = str(st.secrets.get(name, "")).strip()
        return v or os.environ.get(name, default)
    except Exception:
        return os.environ.get(name, default)

CEREBRAS_API_KEY = _get_secret("CEREBRAS_API_KEY")
VNWALLSTREET_SECRET_KEY = _get_secret("VNWALLSTREET_SECRET_KEY")

# ==============================================================================
# 2) CEREBRAS CLIENT
# ==============================================================================
AI_AVAILABLE = False
client = None
try:
    from cerebras.cloud.sdk import Cerebras
    if CEREBRAS_API_KEY:
        client = Cerebras(api_key=CEREBRAS_API_KEY)
        AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False
    client = None

# ==============================================================================
# 3) UI + CSS
# ==============================================================================
st.set_page_config(page_title=APP_TITLE, page_icon="🏆", layout="centered")

st.markdown(
    """
<style>
.stApp { background-color: #0b0f19; }

.control-panel{
  background:#161b22; border:1px solid #30363d; padding:15px; border-radius:10px; margin-bottom:18px;
}
.dashboard-box{
  background: linear-gradient(145deg, #2A2100, #1a1a1a);
  border:1px solid #FFD700; border-radius:12px;
  padding:16px; margin-bottom:14px;
  box-shadow:0 4px 15px rgba(255,215,0,0.18);
  text-align:center;
}
.snapshot-box{
  background:#10151c; border:1px solid #30363d; border-radius:12px;
  padding:12px; margin-bottom:14px;
}
.news-card{
  background:#161b22;
  border-left:5px solid #6B7280;
  border-radius:10px;
  padding:14px;
  margin-bottom:12px;
}
.time-badge{ color:#6B7280; font-family:Consolas, monospace; font-size:0.85em; margin-right:8px; }
.news-text{ color:#e6edf3; font-size:15px; line-height:1.55; font-weight:500; }

.ai-badge{
  display:inline-block;
  font-weight:800;
  padding:4px 8px;
  border-radius:4px;
  color:white;
  font-size:0.75em;
  margin-right:8px;
  text-transform:uppercase;
}
.ai-reason{
  display:block;
  margin-top:10px;
  padding-top:8px;
  border-top:1px dashed #374151;
  color:#F59E0B;
  font-size:0.9em;
  font-style:italic;
}
.small-muted{ color:#6B7280; font-size:0.85em; }
.kv { color:#cbd5e1; font-family:Consolas, monospace; font-size:0.9em; display:flex; justify-content:space-between; padding:2px 0; }
.kv span:last-child { font-weight:700; color:#FFD700; }

.countdown-bar{
  text-align:center; color:#6B7280;
  margin-top:16px; padding:10px;
  background:#0d1117; border:1px solid #30363d;
  border-radius:8px;
}
</style>
""",
    unsafe_allow_html=True,
)

# ==============================================================================
# 4) HTTP RETRY
# ==============================================================================
def http_get_retry(url, params=None, headers=None, timeout=10, retries=3, backoff=1.6):
    last_exc = None
    for i in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(backoff ** i)
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(backoff ** i)
    raise last_exc if last_exc else RuntimeError("http_get_retry failed")

# ==============================================================================
# 5) DB (SQLite) — FULL FUNCTIONS
# ==============================================================================
@st.cache_resource
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS news (
        fp TEXT PRIMARY KEY,
        source_ts INTEGER,
        raw_text TEXT,
        created_at INTEGER
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS translations (
        fp TEXT,
        lang TEXT,
        text TEXT,
        updated_at INTEGER,
        PRIMARY KEY (fp, lang)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS scores (
        fp TEXT,
        prompt_version TEXT,
        model TEXT,
        signal TEXT,
        score REAL,
        reason TEXT,
        updated_at INTEGER,
        PRIMARY KEY (fp, prompt_version)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY,
        v TEXT
    );
    """)
    conn.commit()
    return conn

def db_get_meta(conn, key: str):
    cur = conn.cursor()
    cur.execute("SELECT v FROM meta WHERE k=?", (key,))
    r = cur.fetchone()
    return r[0] if r else None

def db_set_meta(conn, key: str, value: str):
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO meta(k,v) VALUES(?,?)
    ON CONFLICT(k) DO UPDATE SET v=excluded.v
    """, (key, value))
    conn.commit()

def db_upsert_news(conn, fp: str, source_ts: int, raw_text: str):
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO news(fp, source_ts, raw_text, created_at)
    VALUES(?,?,?,?)
    ON CONFLICT(fp) DO UPDATE SET
        source_ts=excluded.source_ts,
        raw_text=excluded.raw_text
    """, (fp, source_ts, raw_text, int(time.time())))
    conn.commit()

def db_get_translation(conn, fp: str, lang: str):
    cur = conn.cursor()
    cur.execute("SELECT text FROM translations WHERE fp=? AND lang=?", (fp, lang))
    r = cur.fetchone()
    return r[0] if r else None

def db_set_translation(conn, fp: str, lang: str, text: str):
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO translations(fp, lang, text, updated_at)
    VALUES(?,?,?,?)
    ON CONFLICT(fp,lang) DO UPDATE SET
        text=excluded.text,
        updated_at=excluded.updated_at
    """, (fp, lang, text, int(time.time())))
    conn.commit()

def db_get_score(conn, fp: str, prompt_version: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT model, signal, score, reason, updated_at
        FROM scores
        WHERE fp=? AND prompt_version=?
    """, (fp, prompt_version))
    r = cur.fetchone()
    if not r:
        return None
    return {"model": r[0], "signal": r[1], "score": float(r[2]), "reason": r[3], "updated_at": int(r[4])}

def db_set_score(conn, fp: str, prompt_version: str, model: str, signal: str, score: float, reason: str):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO scores(fp, prompt_version, model, signal, score, reason, updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(fp,prompt_version) DO UPDATE SET
            model=excluded.model,
            signal=excluded.signal,
            score=excluded.score,
            reason=excluded.reason,
            updated_at=excluded.updated_at
    """, (fp, prompt_version, model, signal, float(score), reason, int(time.time())))
    conn.commit()

# ==============================================================================
# 6) UTILS: normalize/fingerprint/translate/json parse
# ==============================================================================
def normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def fingerprint_item(source_ts: int, raw_text: str) -> str:
    base = f"{source_ts}|{normalize_text(raw_text)[:800]}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

@st.cache_data(ttl=3600, show_spinner=False)
def translate_runtime(text: str, target: str) -> str:
    if not text:
        return ""
    if target == "vi":
        return text
    try:
        return GoogleTranslator(source="auto", target=target).translate(text)
    except Exception:
        return text

def get_or_make_translation(conn, fp: str, raw_text: str, lang: str) -> str:
    t = db_get_translation(conn, fp, lang)
    if t is not None:
        return t
    if lang == "vi":
        t = raw_text
    else:
        t = translate_runtime(raw_text, lang)
    db_set_translation(conn, fp, lang, t)
    return t

def parse_json_array_loose(s: str):
    if not s:
        return None
    raw = s.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0]
    m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(raw)

# ==============================================================================
# 7) NEWS FETCH (VNWALLSTREET signature)
# ==============================================================================
def fetch_latest_news(limit: int = 20):
    if not VNWALLSTREET_SECRET_KEY:
        return [], "Missing VNWALLSTREET_SECRET_KEY"

    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://vnwallstreet.com/", "Accept": "application/json"}

    try:
        ts_ms = int(time.time() * 1000)
        params = {
            "limit": limit,
            "uid": "-1",
            "start": "0",
            "token_": "",
            "key_": VNWALLSTREET_SECRET_KEY,
            "time_": ts_ms,
        }
        sorted_keys = sorted(params.keys())
        query = "&".join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode("utf-8")).hexdigest().upper()

        del params["key_"]
        params["sign_"] = sign

        resp = http_get_retry(API_URL, params=params, headers=HEADERS, timeout=10, retries=3)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        return data.get("data", []) or [], None
    except Exception as e:
        return [], f"Fetch error: {e}"

# ==============================================================================
# 8) M15 GATE (UTC)
# ==============================================================================
def last_completed_m15_key_utc(safety_seconds: int = 10) -> str:
    now = datetime.datetime.utcnow() - datetime.timedelta(seconds=safety_seconds)
    minute_bucket = (now.minute // 15) * 15
    t = now.replace(minute=minute_bucket, second=0, microsecond=0)
    return t.strftime("%Y-%m-%d %H:%M")

def next_m15_close_seconds_left(safety_seconds: int = 10) -> int:
    now = datetime.datetime.utcnow()
    next_min_bucket = ((now.minute // 15) + 1) * 15
    nxt = now.replace(second=0, microsecond=0)
    if next_min_bucket >= 60:
        nxt = (nxt + datetime.timedelta(hours=1)).replace(minute=0)
    else:
        nxt = nxt.replace(minute=next_min_bucket)
    nxt = nxt + datetime.timedelta(seconds=safety_seconds)
    return max(0, int((nxt - now).total_seconds()))

# ==============================================================================
# 9) YFINANCE M15 FETCH (NO FALLBACK): sequential + delay
# ==============================================================================
def yf_fetch_m15_one(ticker: str):
    if not YF_AVAILABLE:
        return {"ok": False, "price": None, "chg_15m_pct": None, "last_bar": None}

    df = yf.download(tickers=ticker, period="5d", interval="15m", progress=False, threads=False)
    if df is None or df.empty or "Close" not in df:
        return {"ok": False, "price": None, "chg_15m_pct": None, "last_bar": None}

    closes = df["Close"].dropna()
    if len(closes) < 2:
        return {"ok": False, "price": None, "chg_15m_pct": None, "last_bar": None}

    curr = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    chg = (curr / prev - 1.0) * 100.0

    try:
        last_bar = str(closes.index[-1])
    except Exception:
        last_bar = None

    return {
        "ok": True,
        "price": round(curr, 6),
        "chg_15m_pct": round(chg, 6),
        "last_bar": last_bar
    }

def update_snapshot_if_m15_closed(conn, per_ticker_delay: float, safety_seconds: int = 10):
    key = last_completed_m15_key_utc(safety_seconds=safety_seconds)

    last_key = db_get_meta(conn, "snapshot_m15_key") or ""
    attempt_key = db_get_meta(conn, "snapshot_attempt_key") or ""
    cached_json = db_get_meta(conn, "snapshot_json")

    if attempt_key == key and cached_json:
        try:
            return json.loads(cached_json)
        except Exception:
            pass

    if last_key == key and cached_json:
        try:
            return json.loads(cached_json)
        except Exception:
            pass

    db_set_meta(conn, "snapshot_attempt_key", key)

    snapshot = {
        "asof_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "m15_key_utc": key,
        "source": "yfinance_15m",
        "data": {},
        "error": None,
        "note": "NO FALLBACK. If 15m data missing => N/A."
    }

    if not YF_AVAILABLE:
        snapshot["error"] = "yfinance not installed"
    else:
        for name, ticker in YF_TICKERS.items():
            try:
                snapshot["data"][name] = yf_fetch_m15_one(ticker)
            except Exception as e:
                snapshot["data"][name] = {"ok": False, "price": None, "chg_15m_pct": None, "last_bar": None}
                snapshot["error"] = f"yfinance error: {e}"
            time.sleep(max(0.0, float(per_ticker_delay)))

    db_set_meta(conn, "snapshot_json", json.dumps(snapshot, ensure_ascii=False))
    db_set_meta(conn, "snapshot_m15_key", key)
    return snapshot

# ==============================================================================
# 10) AI PROMPT (FULL macro logic incl. Fed/Inflation/Risk-off USD+Gold)
# ==============================================================================
def build_prompt(lang_instruction: str, n_items: int, snapshot_json: str) -> str:
    return f"""
You are an Elite Macro & Metals Strategist. Score NEWS for XAU/USD (Gold vs USD).

SNAPSHOT NOTICE (M15 snapshot may be missing/N/A):
- If snapshot values are N/A/missing => treat as UNKNOWN.
- Do NOT hallucinate moves; rely more on news and be conservative.
- If missing snapshot reduces confidence, mention it briefly.

SNAPSHOT_JSON:
{snapshot_json}

MACRO DRIVERS (Correct trader logic):

A) YIELDS + USD:
- Rising US yields (especially real yields) is typically bearish for gold.
- Rising USD (DXY) is typically bearish for gold.
- Falling yields and/or falling USD is typically bullish for gold.

B) FED / CENTRAL BANK SPEAK (hawkish vs dovish):
- Hawkish (higher-for-longer, restrictive, inflation risk) => tends to lift yields => SELL bias for gold.
- Dovish (rate cuts, easing, inflation falling, growth concern) => tends to lower yields => BUY bias for gold.
- If unclear => SIDEWAY with low/moderate score.

C) INFLATION PRINTS (CPI/PCE) + FED REACTION FUNCTION:
- Hot inflation can be inflation-hedge bullish for gold BUT can also trigger hawkish Fed => yields up => gold down.
- Decide direction by expected Fed reaction / yields impact:
  - If hot CPI/PCE likely => hawkish Fed / yields UP => SELL or cautious SIDEWAY.
  - If soft CPI/PCE => dovish Fed / yields DOWN => BUY.
- If snapshot shows yields already jumped after the print => stronger SELL confidence.

D) EXTREME RISK-OFF CASE (USD + GOLD both up allowed):
- In severe crisis (war escalation, coup, systemic stress), USD can rise for liquidity AND gold can rise as safe haven.
- You ARE allowed to output BUY gold even if USD is also rising, if risk-off dominates.
- If you do so, explicitly say: "risk-off dominates; USD also bid but gold safe haven".

E) OIL / ENERGY NEWS:
- Treat oil news as RELEVANT only when it clearly affects inflation expectations, Fed/yields path, or geopolitical/supply risk.
- Supply shock / geopolitical escalation (OPEC+ surprise cuts, attacks, Hormuz risk) => often BUY gold.
- Minor oil chatter/company-only oil news without macro implication => NO EDGE => SIDEWAY score=0.0.

PRECIOUS METALS CO-MOVE:
- Gold (XAU) and Silver (XAG) are precious metals; they often move in the same direction under USD/yields/risk regimes.

RELEVANCE FILTER (MANDATORY):
- If news has NO meaningful link to:
  (USD/DXY, yields, Fed/CB speak, CPI/PCE/inflation, geopolitics/risk-off, precious metals, or oil macro channels)
  => signal="SIDEWAY" AND score=0.0.

SIDEWAY WITH NONZERO:
- If relevant but mixed/uncertain => signal="SIDEWAY" with score 0.10..0.60.

OUTPUT:
- Return ONLY a valid JSON Array (no markdown).
- Must include every ID 0..{n_items-1}.
- Schema:
  {{
    "id": int,
    "signal": "BUY"|"SELL"|"SIDEWAY",
    "score": float 0.0..0.99,
    "reason": "Explain in {lang_instruction} (max 18 words)"
  }}

PROMPT_VERSION: {PROMPT_VERSION}
"""

def call_ai_with_fallback(english_items: list[str], lang_instruction: str, snapshot: dict):
    if not AI_AVAILABLE or client is None:
        return [], None, None, "AI not available"

    n = len(english_items)
    user_content = "\n".join([f"ID {i}: {english_items[i]}" for i in range(n)])
    system_prompt = build_prompt(lang_instruction, n, json.dumps(snapshot, ensure_ascii=False))

    last_raw = None
    last_err = None

    for model_name in MODEL_LIST:
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_content}],
                temperature=0.1,
                max_tokens=4000,
            )
            raw = resp.choices[0].message.content
            last_raw = raw
            arr = parse_json_array_loose(raw)
            if not isinstance(arr, list):
                raise ValueError("AI output not JSON array")
            return arr, model_name, raw, None
        except Exception as e:
            last_err = f"{model_name} failed: {e}"
            continue

    return [], None, last_raw, last_err or "All models failed"

# ==============================================================================
# 11) SESSION STATE
# ==============================================================================
def ensure_state():
    if "next_news_refresh_at" not in st.session_state:
        st.session_state.next_news_refresh_at = time.time() + DEFAULT_NEWS_REFRESH_SECONDS
    if "force_news_refresh" not in st.session_state:
        st.session_state.force_news_refresh = True

    if "ui_tick_seconds" not in st.session_state:
        st.session_state.ui_tick_seconds = DEFAULT_UI_TICK_SECONDS
    if "news_refresh_seconds" not in st.session_state:
        st.session_state.news_refresh_seconds = DEFAULT_NEWS_REFRESH_SECONDS
    if "yf_delay" not in st.session_state:
        st.session_state.yf_delay = DEFAULT_YF_DELAY_SECONDS

    if "last_status_msg" not in st.session_state:
        st.session_state.last_status_msg = ""
    if "last_model_used" not in st.session_state:
        st.session_state.last_model_used = ""
    if "current_batch" not in st.session_state:
        st.session_state.current_batch = []
    if "_display_texts" not in st.session_state:
        st.session_state._display_texts = []
    if "_cached_scores" not in st.session_state:
        st.session_state._cached_scores = []

ensure_state()

# ==============================================================================
# 12) CONTROL PANEL
# ==============================================================================
st.title(APP_TITLE)
conn = init_db()

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1.4, 1.4, 1.2, 1.2])

    with c1:
        LANGUAGES = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        sel_lang = st.selectbox("Ngôn ngữ / Language:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        ai_lang_instruction = "Vietnamese" if target_lang == "vi" else "English"

    with c2:
        TIMEZONES = {
            "Vietnam (UTC+7)": 7,
            "New York (UTC-5)": -5,
            "London (UTC+0)": 0,
            "Tokyo (UTC+9)": 9,
        }
        sel_tz = st.selectbox("Múi giờ / Timezone:", list(TIMEZONES.keys()), index=0)
        tz_offset = TIMEZONES[sel_tz]
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))

    with c3:
        st.session_state.news_refresh_seconds = int(st.number_input(
            "📰 News refresh (s)",
            min_value=30, max_value=1800,
            value=int(st.session_state.news_refresh_seconds),
            step=30
        ))
        st.session_state.ui_tick_seconds = int(st.number_input(
            "🖥 UI tick (s)",
            min_value=1, max_value=30,
            value=int(st.session_state.ui_tick_seconds),
            step=1
        ))

    with c4:
        st.session_state.yf_delay = float(st.number_input(
            "🐢 YF delay/ticker (s)",
            min_value=0.0, max_value=5.0,
            value=float(st.session_state.yf_delay),
            step=0.1
        ))
        if st.button("🔄 REFRESH NOW", use_container_width=True):
            st.session_state.force_news_refresh = True
            st.session_state.next_news_refresh_at = time.time()
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    f"AI: {'ON' if AI_AVAILABLE else 'OFF'} | "
    f"VNW key: {'OK' if bool(VNWALLSTREET_SECRET_KEY) else 'MISSING'} | "
    f"YF: {'ON' if YF_AVAILABLE else 'OFF'} | Prompt: {PROMPT_VERSION}"
)

# ==============================================================================
# 13) UI TICK (no-block)
# ==============================================================================
if AUTOREFRESH_AVAILABLE:
    st_autorefresh(interval=st.session_state.ui_tick_seconds * 1000, key="ui_tick")

# ==============================================================================
# 14) SNAPSHOT UPDATE (M15 gate)
# ==============================================================================
snapshot = update_snapshot_if_m15_closed(conn, per_ticker_delay=st.session_state.yf_delay, safety_seconds=M15_SAFETY_SECONDS)

# Render snapshot
st.markdown("<div class='snapshot-box'>", unsafe_allow_html=True)
st.markdown(
    f"<div class='small-muted'>Snapshot M15 key (UTC): <b>{snapshot.get('m15_key_utc')}</b> • asof UTC: {snapshot.get('asof_utc')}</div>",
    unsafe_allow_html=True
)
if snapshot.get("error"):
    st.markdown(f"<div class='small-muted'>Snapshot error: {snapshot.get('error')}</div>", unsafe_allow_html=True)

for k, v in snapshot.get("data", {}).items():
    if not isinstance(v, dict) or not v.get("ok"):
        st.markdown(f"<div class='kv'><span>{k}</span><span>N/A</span></div>", unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div class='kv'><span>{k}</span><span>{v.get('price')} | Δ15m {v.get('chg_15m_pct')}%</span></div>",
            unsafe_allow_html=True
        )
st.markdown("</div>", unsafe_allow_html=True)

# ==============================================================================
# 15) NEWS REFRESH SCHEDULE
# ==============================================================================
now = time.time()
do_news_refresh = st.session_state.force_news_refresh or (now >= st.session_state.next_news_refresh_at)

if do_news_refresh:
    st.session_state.force_news_refresh = False
    st.session_state.next_news_refresh_at = now + st.session_state.news_refresh_seconds

    raw_items, fetch_err = fetch_latest_news(FETCH_LIMIT)
    if fetch_err:
        st.session_state.last_status_msg = f"Fetch error: {fetch_err}"
        raw_items = []

    if raw_items:
        current = []
        english_texts = []
        display_texts = []
        cached_scores = []
        missing_score_indices = []

        for it in raw_items:
            raw_text = normalize_text(it.get("title") or it.get("content") or "")
            raw_ts = int(it.get("createtime") or it.get("showtime") or 0)
            if raw_ts > 1000000000000:
                raw_ts = int(raw_ts / 1000)

            fp = fingerprint_item(raw_ts, raw_text)
            db_upsert_news(conn, fp, raw_ts, raw_text)

            en = get_or_make_translation(conn, fp, raw_text, "en")
            disp = get_or_make_translation(conn, fp, raw_text, target_lang)

            sc = db_get_score(conn, fp, PROMPT_VERSION)

            current.append({"fp": fp, "ts": raw_ts})
            english_texts.append(en)
            display_texts.append(disp)
            cached_scores.append(sc)

        for i in range(len(current)):
            if cached_scores[i] is None:
                missing_score_indices.append(i)

        stored = 0
        if missing_score_indices:
            results, used_model, ai_raw, ai_err = call_ai_with_fallback(english_texts, ai_lang_instruction, snapshot)

            if used_model:
                st.session_state.last_model_used = used_model
                db_set_meta(conn, "last_ai_model", used_model)
                db_set_meta(conn, "last_ai_at", str(int(time.time())))

            res_map = {}
            if isinstance(results, list):
                for r in results:
                    if isinstance(r, dict) and "id" in r:
                        try:
                            res_map[int(r["id"])] = r
                        except Exception:
                            pass

            for idx in missing_score_indices:
                fp = current[idx]["fp"]
                r = res_map.get(idx) or (results[idx] if isinstance(results, list) and idx < len(results) and isinstance(results[idx], dict) else None)
                if not isinstance(r, dict):
                    continue

                signal = str(r.get("signal", "SIDEWAY")).upper().strip()
                try:
                    score = float(r.get("score", 0.0))
                except Exception:
                    score = 0.0
                reason = str(r.get("reason", "")).strip()

                score = max(0.0, min(0.99, score))
                if signal not in ("BUY", "SELL", "SIDEWAY"):
                    signal = "SIDEWAY"

                db_set_score(conn, fp, PROMPT_VERSION, used_model or "", signal, score, reason)
                stored += 1

            cached_scores = [db_get_score(conn, it["fp"], PROMPT_VERSION) for it in current]
            st.session_state.last_status_msg = f"News refreshed. Stored new AI scores: {stored}."
            if ai_err:
                st.session_state.last_status_msg += f" (AI err: {ai_err})"
        else:
            st.session_state.last_status_msg = "News refreshed. No new AI scoring needed."

        st.session_state.current_batch = current
        st.session_state._display_texts = display_texts
        st.session_state._cached_scores = cached_scores

    else:
        st.session_state.current_batch = []
        st.session_state._display_texts = []
        st.session_state._cached_scores = []
        st.session_state.last_status_msg = "News refreshed. No news returned."

# ==============================================================================
# 16) RENDER dashboard + list
# ==============================================================================
st.caption(st.session_state.get("last_status_msg", ""))

current_batch = st.session_state.get("current_batch") or []
display_texts = st.session_state.get("_display_texts") or []
cached_scores = st.session_state.get("_cached_scores") or []

if current_batch and display_texts and cached_scores and len(current_batch) == len(display_texts) == len(cached_scores):
    buy_sell_scores = []
    for sc in cached_scores:
        if not sc:
            continue
        sig = (sc.get("signal") or "SIDEWAY").upper()
        s = float(sc.get("score") or 0.0)
        if sig == "BUY" and s > 0:
            buy_sell_scores.append(+s)
        elif sig == "SELL" and s > 0:
            buy_sell_scores.append(-s)

    avg = statistics.mean(buy_sell_scores) if buy_sell_scores else 0.0
    if avg > 0.15:
        trend, tcolor = "LONG / BUY XAUUSD 📈", "#10B981"
        msg = "Bias BUY (macro rules incl. Fed/Inflation/Risk-off) + snapshot if available"
    elif avg < -0.15:
        trend, tcolor = "SHORT / SELL XAUUSD 📉", "#EF4444"
        msg = "Bias SELL (macro rules incl. Fed/Inflation/Risk-off) + snapshot if available"
    else:
        trend, tcolor = "SIDEWAY / WAIT ⚠️", "#FFD700"
        msg = "No strong edge (or many items irrelevant => score 0.0)"

    model_used = st.session_state.get("last_model_used") or db_get_meta(conn, "last_ai_model") or "(none)"
    st.markdown(
        f"""
        <div class="dashboard-box">
            <div class="small-muted">XAU/USD Signal</div>
            <h2 style="color:{tcolor}; margin:6px 0 0 0;">{trend}</h2>
            <div style="color:#ddd; margin-top:8px;">Strength: {avg:.2f}</div>
            <div style="color:#bbb; font-size:0.9em; margin-top:10px; font-style:italic;">{msg}</div>
            <div class="small-muted" style="margin-top:12px; border-top:1px solid #333; padding-top:8px;">
                Model: {model_used}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i, item in enumerate(current_batch):
        sc = cached_scores[i]
        sig = (sc.get("signal") if sc else "SIDEWAY").upper() if sc else "SIDEWAY"
        score = float(sc.get("score") or 0.0) if sc else 0.0
        reason = sc.get("reason") if sc else ""

        if sig == "BUY" and score > 0:
            color, label = "#10B981", "BUY XAU"
        elif sig == "SELL" and score > 0:
            color, label = "#EF4444", "SELL XAU"
        else:
            color = "#FFD700" if score > 0 else "#6B7280"
            label = "SIDEWAY"

        try:
            t_str = datetime.datetime.fromtimestamp(item["ts"], CURRENT_TZ).strftime("%H:%M")
        except Exception:
            t_str = "--:--"

        st.markdown(
            f"""
            <div class="news-card" style="border-left:5px solid {color}; opacity:{1.0 if score>0 else 0.65};">
                <span class="time-badge">[{t_str}]</span>
                <span class="ai-badge" style="background:{color};">{label} {int(score*100)}%</span>
                <div class="news-text">{display_texts[i]}</div>
                <span class="ai-reason">💡 {reason}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    st.info("Nhấn REFRESH NOW để tải tin lần đầu.")

# ==============================================================================
# 17) COUNTDOWN BAR
# ==============================================================================
news_left = max(0, int(st.session_state.next_news_refresh_at - time.time()))
m15_left = next_m15_close_seconds_left(safety_seconds=M15_SAFETY_SECONDS)

st.markdown(
    f"""
    <div class="countdown-bar">
        ⏳ Next NEWS refresh in <b style="color:#FFD700;">{news_left}</b>s
        <span class="small-muted">| Next M15 snapshot in ~{m15_left}s (UTC)</span>
    </div>
    """,
    unsafe_allow_html=True,
)
