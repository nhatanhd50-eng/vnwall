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

# Optional libs
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
APP_TITLE = "🏆 XAU/USD Intelligence (Incremental + Snapshot + No-Block Countdown)"
DB_PATH = "xau_cache.sqlite3"
PROMPT_VERSION = "xau_snapshot_v2"
FETCH_LIMIT = 20

# Refresh strategy:
AUTO_REFRESH_SECONDS = 180          # full refresh interval (fetch news + snapshot + AI if needed)
UI_TICK_SECONDS = 5                 # UI countdown update interval (NO fetch)

MODEL_LIST = [
    "gpt-oss-120b",
    "qwen-3-235b-a22b-instruct-2507",
    "qwen-3-32b",
]

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
FRED_SERIES = {
    "usd_proxy_dtwexbgs": "DTWEXBGS",   # USD proxy index
    "us10y_dgs10": "DGS10",             # 10Y nominal yield (daily)
    "us10y_real_dfii10": "DFII10",      # 10Y real yield (daily)
    "vix_vixcls": "VIXCLS",             # VIX close (daily)
}

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
  padding:18px; margin-bottom:18px;
  box-shadow:0 4px 15px rgba(255,215,0,0.18);
  text-align:center;
}
.snapshot-box{
  background:#10151c; border:1px solid #30363d; border-radius:12px;
  padding:14px; margin-bottom:16px;
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
  margin-top:18px; padding:10px;
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
# 7) FETCH VNW NEWS (signature full params)
# ==============================================================================
def fetch_latest_news(limit: int = 20):
    if not VNWALLSTREET_SECRET_KEY:
        return [], "Missing VNWALLSTREET_SECRET_KEY"

    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://vnwallstreet.com/",
        "Accept": "application/json",
    }

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
# 8) MARKET SNAPSHOT (YFinance -> fallback FRED)
# ==============================================================================
def _parse_fred_csv(csv_text: str):
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return []
    out = []
    for row in lines[1:]:
        parts = row.split(",")
        if len(parts) < 2:
            continue
        d, v = parts[0].strip(), parts[1].strip()
        if not d or v in (".", ""):
            continue
        try:
            out.append((d, float(v)))
        except Exception:
            pass
    return out

@st.cache_data(ttl=900, show_spinner=False)  # 15 minutes
def get_market_snapshot():
    """
    Snapshot object:
    {
      "asof": "...",
      "source": "yfinance"|"fred"|"none",
      "data": { ... },
      "text": "...",
      "error": None|"..."
    }
    """
    snap = {
        "asof": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": "none",
        "data": {},
        "text": "",
        "error": None,
    }

    # 1) Try yfinance (can rate-limit)
    if YF_AVAILABLE:
        try:
            df = yf.download(
                tickers=list(YF_TICKERS.values()),
                period="5d",
                interval="1d",
                progress=False,
                threads=False,
            )
            if df is not None and not df.empty:
                snap["source"] = "yfinance"
                for name, ticker in YF_TICKERS.items():
                    try:
                        closes = df["Close"][ticker].dropna()
                        if len(closes) >= 2:
                            curr = float(closes.iloc[-1])
                            prev = float(closes.iloc[-2])
                            chg = (curr / prev - 1.0) * 100.0
                            snap["data"][name] = {"value": round(curr, 3), "chg_1d_pct": round(chg, 3)}
                    except Exception:
                        pass
        except Exception as e:
            snap["error"] = f"yfinance error: {e}"

    # 2) If yfinance didn’t return core macro, fallback to FRED (daily)
    def _need_fred():
        # need at least USD proxy + yields + vix to be useful
        return not (("DXY" in snap["data"]) and ("US10Y" in snap["data"]) and ("VIX" in snap["data"]))

    if _need_fred():
        try:
            snap["source"] = "fred"
            for key, sid in FRED_SERIES.items():
                url = FRED_CSV_URL.format(series_id=sid)
                resp = http_get_retry(url, timeout=10, retries=3)
                if resp.status_code != 200:
                    continue
                rows = _parse_fred_csv(resp.text)
                if len(rows) < 2:
                    continue
                (d0, v0), (d1, v1) = rows[-2], rows[-1]
                if key.startswith("us10y"):
                    # yields in % => bps change = diff * 100
                    chg_bps = (v1 - v0) * 100.0
                    snap["data"][key] = {"series": sid, "date": d1, "value": v1, "chg_1d_bps": round(chg_bps, 3)}
                else:
                    chg_pct = (v1 / v0 - 1.0) * 100.0
                    snap["data"][key] = {"series": sid, "date": d1, "value": v1, "chg_1d_pct": round(chg_pct, 3)}
        except Exception as e:
            snap["error"] = (snap["error"] + " | " if snap["error"] else "") + f"fred error: {e}"
            snap["source"] = "none"

    # Build text block for AI prompt
    snap["text"] = json.dumps(snap, ensure_ascii=False)
    return snap

# ==============================================================================
# 9) AI PROMPT + FALLBACK
# ==============================================================================
def build_prompt(lang_instruction: str, n_items: int, snapshot_json: str) -> str:
    return f"""
You are an Elite Macro & Metals Strategist. Analyze news for XAU/USD (Gold vs USD).

MARKET SNAPSHOT (pricing context; may be daily for some series):
{snapshot_json}

INTER-MARKET:
- Gold typically moves inverse to USD (DXY/proxy) and US Treasury yields (nominal/real).
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
    system_prompt = build_prompt(lang_instruction, n, snapshot.get("text", "{}"))

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
# 10) SESSION STATE (non-blocking refresh)
# ==============================================================================
def ensure_state():
    if "next_refresh_at" not in st.session_state:
        st.session_state.next_refresh_at = time.time() + AUTO_REFRESH_SECONDS
    if "force_refresh" not in st.session_state:
        st.session_state.force_refresh = True  # first run fetches immediately
    if "current_batch" not in st.session_state:
        st.session_state.current_batch = []    # list of dicts: fp, ts
    if "last_fetch_at" not in st.session_state:
        st.session_state.last_fetch_at = 0.0
    if "last_model_used" not in st.session_state:
        st.session_state.last_model_used = ""
    if "last_status_msg" not in st.session_state:
        st.session_state.last_status_msg = ""

ensure_state()

# ==============================================================================
# 11) CONTROL PANEL (language, timezone, refresh)
# ==============================================================================
st.title(APP_TITLE)

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.6, 1.6, 1])

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
        st.write("")
        if st.button("🔄 REFRESH", use_container_width=True):
            st.session_state.force_refresh = True
            st.session_state.next_refresh_at = time.time() + AUTO_REFRESH_SECONDS
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    f"AI: {'ON' if AI_AVAILABLE else 'OFF'} | "
    f"VNW key: {'OK' if bool(VNWALLSTREET_SECRET_KEY) else 'MISSING'} | "
    f"YF: {'ON' if YF_AVAILABLE else 'OFF'} | "
    f"Prompt: {PROMPT_VERSION}"
)

# ==============================================================================
# 12) REFRESH TICK (no-block)
# ==============================================================================
if AUTOREFRESH_AVAILABLE:
    st_autorefresh(interval=UI_TICK_SECONDS * 1000, key="ui_tick")

now = time.time()
do_refresh = st.session_state.force_refresh or (now >= st.session_state.next_refresh_at)

# ==============================================================================
# 13) MAIN PIPELINE (only runs on refresh)
# ==============================================================================
conn = init_db()

snapshot = None
raw_items = None
fetch_err = None

if do_refresh:
    st.session_state.force_refresh = False
    st.session_state.last_fetch_at = now
    st.session_state.next_refresh_at = now + AUTO_REFRESH_SECONDS

    # 1) snapshot (cached + fallback)
    snapshot = get_market_snapshot()

    # 2) fetch news
    raw_items, fetch_err = fetch_latest_news(FETCH_LIMIT)

    if fetch_err:
        st.session_state.last_status_msg = f"Fetch error: {fetch_err}"
        raw_items = []

    if raw_items:
        # Build batch & upsert, translations, scoring decisions
        current = []
        english_texts = []
        display_texts = []

        missing_score_indices = []
        cached_scores = []

        for it in raw_items:
            raw_text = normalize_text(it.get("title") or it.get("content") or "")
            raw_ts = int(it.get("createtime") or it.get("showtime") or 0)
            if raw_ts > 1000000000000:
                raw_ts = int(raw_ts / 1000)

            fp = fingerprint_item(raw_ts, raw_text)
            db_upsert_news(conn, fp, raw_ts, raw_text)

            # ensure translations (EN + display)
            en = get_or_make_translation(conn, fp, raw_text, "en")
            disp = get_or_make_translation(conn, fp, raw_text, target_lang)

            english_texts.append(en)
            display_texts.append(disp)

            sc = db_get_score(conn, fp, PROMPT_VERSION)
            cached_scores.append(sc)

            current.append({"fp": fp, "ts": raw_ts})

        # Which need scoring?
        for i, item in enumerate(current):
            if cached_scores[i] is None:
                missing_score_indices.append(i)

        # AI call only if at least one item missing score
        used_model = None
        ai_raw = None
        ai_err = None

        if missing_score_indices:
            results, used_model, ai_raw, ai_err = call_ai_with_fallback(english_texts, ai_lang_instruction, snapshot)

            if used_model:
                st.session_state.last_model_used = used_model
                db_set_meta(conn, "last_ai_model", used_model)
                db_set_meta(conn, "last_ai_at", str(int(time.time())))

            # map results
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

            # reload cache scores for current
            cached_scores = [db_get_score(conn, it["fp"], PROMPT_VERSION) for it in current]
            st.session_state.last_status_msg = f"Refreshed. New AI scores stored: {stored}."
            if ai_err:
                st.session_state.last_status_msg += f" (AI err: {ai_err})"
        else:
            st.session_state.last_status_msg = "Refreshed. No new AI scoring needed."

        # Save into session_state for UI ticks
        st.session_state.current_batch = current
        st.session_state._display_texts = display_texts
        st.session_state._cached_scores = cached_scores
        st.session_state._snapshot = snapshot

    else:
        st.session_state.current_batch = []
        st.session_state._display_texts = []
        st.session_state._cached_scores = []
        st.session_state._snapshot = get_market_snapshot()
        st.session_state.last_status_msg = "Refreshed. No news returned."

# ==============================================================================
# 14) RENDER (works also during UI ticks without refetch)
# ==============================================================================
snapshot = st.session_state.get("_snapshot") or {"source": "none", "data": {}, "error": "no snapshot"}
display_texts = st.session_state.get("_display_texts") or []
cached_scores = st.session_state.get("_cached_scores") or []
current_batch = st.session_state.get("current_batch") or []

# Snapshot box
with st.container():
    d = snapshot.get("data", {})
    st.markdown("<div class='snapshot-box'>", unsafe_allow_html=True)
    st.markdown(f"<div class='small-muted'>Market Snapshot source: <b>{snapshot.get('source')}</b> • asof: {snapshot.get('asof')}</div>", unsafe_allow_html=True)

    # Print yfinance metrics if available
    if any(k in d for k in ("DXY", "US10Y", "VIX", "GOLD", "SILVER")):
        for k in ("DXY", "US10Y", "VIX", "GOLD", "SILVER"):
            if k in d:
                st.markdown(f"<div class='kv'><span>{k}</span><span>{d[k].get('value')} | {d[k].get('chg_1d_pct', 'N/A')}%</span></div>", unsafe_allow_html=True)

    # Print FRED fallback metrics if available
    for k in ("usd_proxy_dtwexbgs", "us10y_dgs10", "us10y_real_dfii10", "vix_vixcls"):
        if k in d:
            val = d[k].get("value")
            if "chg_1d_bps" in d[k]:
                ch = d[k].get("chg_1d_bps")
                st.markdown(f"<div class='kv'><span>{k}</span><span>{val} | Δ1D {ch} bps</span></div>", unsafe_allow_html=True)
            else:
                ch = d[k].get("chg_1d_pct")
                st.markdown(f"<div class='kv'><span>{k}</span><span>{val} | Δ1D {ch}%</span></div>", unsafe_allow_html=True)

    if snapshot.get("error"):
        st.markdown(f"<div class='small-muted'>Snapshot error: {snapshot.get('error')}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# Status
st.caption(st.session_state.get("last_status_msg", ""))

# Dashboard + list
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

    # Render each item
    for i, item in enumerate(current_batch):
        sc = cached_scores[i]
        sig = (sc.get("signal") if sc else "SIDEWAY").upper() if sc else "SIDEWAY"
        score = float(sc.get("score") or 0.0) if sc else 0.0
        reason = sc.get("reason") if sc else ""

        if sig == "BUY" and score > 0:
            color = "#10B981"
            label = "BUY XAU"
        elif sig == "SELL" and score > 0:
            color = "#EF4444"
            label = "SELL XAU"
        else:
            # SIDEWAY
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
    st.warning("⚠️ No cached batch to display yet. Press REFRESH.")

# ==============================================================================
# 15) COUNTDOWN BAR (non-blocking)
# ==============================================================================
seconds_left = max(0, int(st.session_state.next_refresh_at - time.time()))
st.markdown(
    f"""
    <div class="countdown-bar">
        ⏳ Next refresh in <b style="color:#FFD700;">{seconds_left}</b>s
        <span class="small-muted">| Full refresh interval: {AUTO_REFRESH_SECONDS}s</span>
    </div>
    """,
    unsafe_allow_html=True,
)
