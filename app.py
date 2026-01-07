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
# 0) CONSTANTS / DEFAULTS
# ==============================================================================
APP_TITLE = "🏆 XAU/USD Intelligence (Incremental + Snapshot + UI Tick)"
DB_PATH = "xau_cache.sqlite3"
PROMPT_VERSION = "xau_snapshot_ui_v3"
FETCH_LIMIT = 20

DEFAULT_FULL_REFRESH = 180      # seconds
DEFAULT_SNAPSHOT_TTL = 900      # seconds (15 min)
DEFAULT_YF_DELAY = 1.2          # seconds per ticker
DEFAULT_UI_TICK = 5             # seconds (UI rerun interval)

MODEL_LIST = [
    "gpt-oss-120b",
    "qwen-3-235b-a22b-instruct-2507",
    "qwen-3-32b",
]

YF_TICKERS = {
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "VIX": "^VIX",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
}

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
# 5) DB (SQLite) — full funcs
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
# 7) VNW FETCH (signature)
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
# 8) MARKET SNAPSHOT (YFinance sequential + delay + DB TTL cache)
# ==============================================================================
def yf_fetch_one_ticker(ticker: str):
    df = yf.download(tickers=ticker, period="5d", interval="1d", progress=False, threads=False)
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return None
    curr = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    chg = (curr / prev - 1.0) * 100.0
    return {"value": round(curr, 4), "chg_1d_pct": round(chg, 4)}

def get_market_snapshot_dynamic(conn, ttl_seconds: int, delay_seconds: float):
    """
    DB cache keys: snapshot_json, snapshot_ts
    - If cache fresh => return cached
    - Else => sequential yfinance with delay; if blocked => return old cached if any
    """
    now = int(time.time())
    cached_json = db_get_meta(conn, "snapshot_json")
    cached_ts = db_get_meta(conn, "snapshot_ts")

    if cached_json and cached_ts:
        try:
            cached_ts_i = int(cached_ts)
            if now - cached_ts_i < ttl_seconds:
                snap = json.loads(cached_json)
                snap["cache"] = True
                return snap
        except Exception:
            pass

    snap = {
        "asof_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": "yfinance",
        "cache": False,
        "data": {},
        "error": None
    }

    if not YF_AVAILABLE:
        snap["source"] = "none"
        snap["error"] = "yfinance not installed"
        return snap

    try:
        for name, ticker in YF_TICKERS.items():
            val = yf_fetch_one_ticker(ticker)
            if val:
                snap["data"][name] = val
            time.sleep(max(0.0, float(delay_seconds)))

        # store
        db_set_meta(conn, "snapshot_json", json.dumps(snap, ensure_ascii=False))
        db_set_meta(conn, "snapshot_ts", str(now))
        return snap

    except Exception as e:
        # if blocked, return cached if exists
        if cached_json:
            try:
                old = json.loads(cached_json)
                old["error"] = f"yfinance blocked/rate-limited: {e}"
                old["source"] = old.get("source", "cache")
                old["cache"] = True
                return old
            except Exception:
                pass

        snap["source"] = "none"
        snap["error"] = f"yfinance blocked/rate-limited: {e}"
        return snap

def snapshot_to_prompt_block(snap: dict) -> str:
    # keep compact
    return json.dumps(snap, ensure_ascii=False)

# ==============================================================================
# 9) AI PROMPT + FALLBACK
# ==============================================================================
def build_prompt(lang_instruction: str, n_items: int, snapshot_json: str) -> str:
    return f"""
You are an Elite Macro & Metals Strategist. Analyze news for XAU/USD (Gold vs USD).

MARKET SNAPSHOT (pricing context; may be daily):
{snapshot_json}

INTER-MARKET:
- Gold typically moves inverse to USD (DXY/proxy) and US Treasury yields.
- If news implies USD up or yields up => XAU down => SELL.
- If news implies USD down or yields down => XAU up => BUY.
- War/geopolitical crisis/political unrest => safe haven => BUY.

RELEVANCE FILTER (MANDATORY):
- If a news item has NO meaningful link to:
  (USD/DXY, US yields/treasuries, Fed/US macro, geopolitical risk, precious metals),
  then: signal="SIDEWAY" AND score=0.0.

SIDEWAY WITH NONZERO:
- If relevant but mixed/uncertain => signal="SIDEWAY", score 0.10..0.60.

PRECIOUS METALS CO-MOVE:
- Gold (XAU) and Silver (XAG) are precious metals and often move in the SAME direction.

OUTPUT:
- Return ONLY a valid JSON Array (no markdown).
- Must include every ID 0..{n_items-1}.
- Schema per item:
  {{
    "id": int,
    "signal": "BUY"|"SELL"|"SIDEWAY",
    "score": float 0.0..0.99,
    "reason": "Explanation in {lang_instruction} (max 18 words)"
  }}

PROMPT_VERSION: {PROMPT_VERSION}
"""

def call_ai_with_fallback(english_items: list[str], lang_instruction: str, snapshot: dict):
    if not AI_AVAILABLE or client is None:
        return [], None, None, "AI not available"

    n = len(english_items)
    user_content = "\n".join([f"ID {i}: {english_items[i]}" for i in range(n)])
    system_prompt = build_prompt(lang_instruction, n, snapshot_to_prompt_block(snapshot))

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
# 10) SESSION STATE
# ==============================================================================
def ensure_state():
    if "next_refresh_at" not in st.session_state:
        st.session_state.next_refresh_at = time.time() + DEFAULT_FULL_REFRESH
    if "force_refresh" not in st.session_state:
        st.session_state.force_refresh = True
    if "last_status_msg" not in st.session_state:
        st.session_state.last_status_msg = ""
    if "current_batch" not in st.session_state:
        st.session_state.current_batch = []
    if "_display_texts" not in st.session_state:
        st.session_state._display_texts = []
    if "_cached_scores" not in st.session_state:
        st.session_state._cached_scores = []
    if "_snapshot" not in st.session_state:
        st.session_state._snapshot = {"source": "none", "data": {}, "error": "no snapshot"}
    if "last_model_used" not in st.session_state:
        st.session_state.last_model_used = ""

ensure_state()

# ==============================================================================
# 11) CONTROL PANEL + INPUTS
# ==============================================================================
st.title(APP_TITLE)

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
        full_refresh_seconds = st.number_input(
            "⏱ Full refresh (s)",
            min_value=60, max_value=1800,
            value=int(st.session_state.get("full_refresh_seconds", DEFAULT_FULL_REFRESH)),
            step=30
        )
        st.session_state.full_refresh_seconds = int(full_refresh_seconds)

        snapshot_ttl_seconds = st.number_input(
            "🧊 Snapshot TTL (s)",
            min_value=60, max_value=7200,
            value=int(st.session_state.get("snapshot_ttl_seconds", DEFAULT_SNAPSHOT_TTL)),
            step=60
        )
        st.session_state.snapshot_ttl_seconds = int(snapshot_ttl_seconds)

    with c4:
        yf_delay = st.number_input(
            "🐢 YF delay/ticker (s)",
            min_value=0.0, max_value=5.0,
            value=float(st.session_state.get("yf_delay", DEFAULT_YF_DELAY)),
            step=0.1
        )
        st.session_state.yf_delay = float(yf_delay)

        ui_tick_seconds = st.number_input(
            "🖥 UI tick (s)",
            min_value=1, max_value=30,
            value=int(st.session_state.get("ui_tick_seconds", DEFAULT_UI_TICK)),
            step=1
        )
        st.session_state.ui_tick_seconds = int(ui_tick_seconds)

        if st.button("🔄 REFRESH NOW", use_container_width=True):
            st.session_state.force_refresh = True
            st.session_state.next_refresh_at = time.time()  # refresh immediately
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    f"AI: {'ON' if AI_AVAILABLE else 'OFF'} | "
    f"VNW key: {'OK' if bool(VNWALLSTREET_SECRET_KEY) else 'MISSING'} | "
    f"YF: {'ON' if YF_AVAILABLE else 'OFF'} | Prompt: {PROMPT_VERSION}"
)

# ==============================================================================
# 12) UI TICK (no-block)
# ==============================================================================
if AUTOREFRESH_AVAILABLE:
    st_autorefresh(interval=st.session_state.ui_tick_seconds * 1000, key="ui_tick")

now = time.time()
do_refresh = st.session_state.force_refresh or (now >= st.session_state.next_refresh_at)

# ==============================================================================
# 13) MAIN PIPELINE (only on full refresh)
# ==============================================================================
conn = init_db()

if do_refresh:
    st.session_state.force_refresh = False
    st.session_state.next_refresh_at = now + st.session_state.full_refresh_seconds

    # (A) snapshot with DB TTL + yfinance delay
    snapshot = get_market_snapshot_dynamic(
        conn,
        ttl_seconds=st.session_state.snapshot_ttl_seconds,
        delay_seconds=st.session_state.yf_delay
    )

    # (B) fetch news
    raw_items, fetch_err = fetch_latest_news(FETCH_LIMIT)
    if fetch_err:
        st.session_state.last_status_msg = f"Fetch error: {fetch_err}"
        raw_items = []

    # If no news, still store snapshot for UI
    st.session_state._snapshot = snapshot

    if raw_items:
        current = []
        english_texts = []
        display_texts = []
        cached_scores = []
        missing_score_indices = []

        # Build batch
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

        # (C) show first (gray) will happen in render section; here run AI only if needed
        if missing_score_indices:
            results, used_model, ai_raw, ai_err = call_ai_with_fallback(english_texts, ai_lang_instruction, snapshot)

            if used_model:
                st.session_state.last_model_used = used_model
                db_set_meta(conn, "last_ai_model", used_model)
                db_set_meta(conn, "last_ai_at", str(int(time.time())))

            # map results by id
            res_map = {}
            if isinstance(results, list):
                for r in results:
                    if isinstance(r, dict) and "id" in r:
                        try:
                            res_map[int(r["id"])] = r
                        except Exception:
                            pass

            stored = 0
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

            # reload scores
            cached_scores = [db_get_score(conn, it["fp"], PROMPT_VERSION) for it in current]

            st.session_state.last_status_msg = f"Refreshed. Stored new AI scores: {stored}."
            if ai_err:
                st.session_state.last_status_msg += f" (AI err: {ai_err})"
        else:
            st.session_state.last_status_msg = "Refreshed. No new AI scoring needed."

        st.session_state.current_batch = current
        st.session_state._display_texts = display_texts
        st.session_state._cached_scores = cached_scores

    else:
        st.session_state.current_batch = []
        st.session_state._display_texts = []
        st.session_state._cached_scores = []
        st.session_state.last_status_msg = "Refreshed. No news returned."

# ==============================================================================
# 14) RENDER (always; during UI ticks doesn't refetch)
# ==============================================================================
snapshot = st.session_state.get("_snapshot") or {}
display_texts = st.session_state.get("_display_texts") or []
cached_scores = st.session_state.get("_cached_scores") or []
current_batch = st.session_state.get("current_batch") or []

# Snapshot UI
d = snapshot.get("data", {})
st.markdown("<div class='snapshot-box'>", unsafe_allow_html=True)
st.markdown(
    f"<div class='small-muted'>Snapshot source: <b>{snapshot.get('source','none')}</b> • "
    f"cache: {snapshot.get('cache', False)} • asof: {snapshot.get('asof_utc','')}</div>",
    unsafe_allow_html=True
)
if snapshot.get("error"):
    st.markdown(f"<div class='small-muted'>Snapshot error: {snapshot.get('error')}</div>", unsafe_allow_html=True)

for k in ("DXY", "US10Y", "VIX", "GOLD", "SILVER"):
    if k in d:
        st.markdown(f"<div class='kv'><span>{k}</span><span>{d[k].get('value')} | Δ1D {d[k].get('chg_1d_pct')}%</span></div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

st.caption(st.session_state.get("last_status_msg", ""))

# If we have a batch, render dashboard + list
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
        msg = "USD/Yields down or risk-off → XAU & XAG often rise"
    elif avg < -0.15:
        trend, tcolor = "SHORT / SELL XAUUSD 📉", "#EF4444"
        msg = "USD/Yields up → XAU & XAG often pressured"
    else:
        trend, tcolor = "SIDEWAY / WAIT ⚠️", "#FFD700"
        msg = "No strong USD/Yields-driven edge detected"

    model_used = st.session_state.get("last_model_used") or db_get_meta(conn, "last_ai_model") or "(none)"
    st.markdown(
        f"""
        <div class="dashboard-box">
            <div class="small-muted">XAU/USD Inter-market Signal</div>
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
    st.info("Nhấn REFRESH NOW để tải lần đầu hoặc kiểm tra secrets/key.")

# Countdown (no blocking)
seconds_left = max(0, int(st.session_state.next_refresh_at - time.time()))
st.markdown(
    f"""
    <div class="countdown-bar">
        ⏳ Next full refresh in <b style="color:#FFD700;">{seconds_left}</b>s
        <span class="small-muted">| UI tick: {st.session_state.ui_tick_seconds}s</span>
    </div>
    """,
    unsafe_allow_html=True,
)
