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

# ==============================================================================
# 0) CONFIG
# ==============================================================================
APP_TITLE = "🏆 XAU/USD Intelligence + Market Snapshot (Incremental Cache)"
DB_PATH = "xau_cache.sqlite3"
PROMPT_VERSION = "xau_intermarket_snapshot_v1"
AUTO_REFRESH_SECONDS = 120
FETCH_LIMIT = 20

MODEL_LIST = [
    "gpt-oss-120b",
    "qwen-3-235b-a22b-instruct-2507",
    "qwen-3-32b",
]

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# FRED series (daily)
FRED_SERIES = {
    "usd_proxy_dtwexbgs": "DTWEXBGS",   # USD proxy index
    "us10y_dgs10": "DGS10",             # 10Y nominal yield
    "us10y_real_dfii10": "DFII10",      # 10Y real yield (TIPS)
    "vix_vixcls": "VIXCLS",             # VIX close
}

# Optional: daily gold price from FRED is not guaranteed in this snippet.
# We focus on USD/yields/VIX which are the main drivers.
# You can add a gold series later if you confirm the exact FRED ID you want.

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

OANDA_API_KEY = _get_secret("OANDA_API_KEY")
OANDA_ENV = (_get_secret("OANDA_ENV", "practice") or "practice").lower().strip()
OANDA_BASE = "https://api-fxpractice.oanda.com" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com"

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
@keyframes pulse{0%{opacity:.5}50%{opacity:1}100%{opacity:.5}}
.ai-loading{ color:#F59E0B; font-style:italic; font-size:0.85em; display:block; margin-top:5px; animation:pulse 1.5s infinite; }
.ai-reason{
  display:block;
  margin-top:10px;
  padding-top:8px;
  border-top:1px dashed #374151;
  color:#F59E0B;
  font-size:0.9em;
  font-style:italic;
}
.countdown-bar{
  text-align:center; color:#6B7280;
  margin-top:18px; padding:10px;
  background:#0d1117; border:1px solid #30363d;
  border-radius:8px;
}
.small-muted{ color:#6B7280; font-size:0.85em; }
.kv { color:#cbd5e1; font-family:Consolas, monospace; font-size:0.9em; }
</style>
""",
    unsafe_allow_html=True,
)

# ==============================================================================
# 4) HTTP RETRY (fix 502/503 transient)
# ==============================================================================
def http_get_retry(url, params=None, headers=None, timeout=10, retries=3, backoff=1.5):
    last_exc = None
    for i in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (502, 503, 504, 429):
                time.sleep(backoff ** i)
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(backoff ** i)
    raise last_exc if last_exc else RuntimeError("http_get_retry failed")

# ==============================================================================
# 5) DB (SQLite) - full funcs
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
# 6) Utils: normalize/fingerprint/translate/json parse
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
# 7) Fetch VnWallStreet (signature)
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
# 8) Market Snapshot (FRED daily + optional OANDA intraday)
# ==============================================================================
def _parse_fred_csv(csv_text: str):
    # CSV: DATE,VALUE with missing as "."
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

@st.cache_data(ttl=300, show_spinner=False)
def fred_last_two(series_id: str):
    url = FRED_CSV_URL.format(series_id=series_id)
    resp = http_get_retry(url, timeout=10, retries=3)
    if resp.status_code != 200:
        return None
    rows = _parse_fred_csv(resp.text)
    if len(rows) < 2:
        return None
    return rows[-2], rows[-1]  # (prev_date,val), (last_date,val)

def pct_change(curr, prev):
    if prev == 0 or prev is None or curr is None:
        return None
    return (curr / prev - 1.0) * 100.0

def bps_change(curr_pct, prev_pct):
    if curr_pct is None or prev_pct is None:
        return None
    # yields in % => 1.00% = 100 bps
    return (curr_pct - prev_pct) * 100.0

def oanda_candles(instrument: str, granularity: str, count: int = 5):
    if not OANDA_API_KEY:
        return None
    url = f"{OANDA_BASE}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    params = {"granularity": granularity, "count": count, "price": "M"}
    resp = http_get_retry(url, params=params, headers=headers, timeout=10, retries=2)
    if resp.status_code != 200:
        return None
    data = resp.json()
    candles = data.get("candles", [])
    closes = []
    for c in candles:
        if not c.get("complete", True):
            continue
        mid = c.get("mid", {})
        close = mid.get("c")
        t = c.get("time")
        try:
            closes.append((t, float(close)))
        except Exception:
            pass
    return closes

@st.cache_data(ttl=60, show_spinner=False)
def get_market_snapshot():
    snap = {
        "asof_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "fred": {},
        "oanda": {},
        "notes": [],
    }

    # FRED daily series
    for k, sid in FRED_SERIES.items():
        pair = fred_last_two(sid)
        if not pair:
            snap["fred"][k] = {"series": sid, "ok": False}
            continue
        (d0, v0), (d1, v1) = pair
        entry = {"series": sid, "date": d1, "value": v1}
        if k in ("us10y_dgs10", "us10y_real_dfii10"):
            entry["chg_1d_bps"] = bps_change(v1, v0)
        else:
            entry["chg_1d_pct"] = pct_change(v1, v0)
        snap["fred"][k] = entry

    # Optional OANDA intraday for XAUUSD/XAGUSD
    if OANDA_API_KEY:
        for inst in ("XAU_USD", "XAG_USD"):
            h1 = oanda_candles(inst, "H1", count=6)
            h4 = oanda_candles(inst, "H4", count=6)
            d1 = oanda_candles(inst, "D", count=3)

            def _chg_from_closes(closes, n_back: int):
                if not closes or len(closes) <= n_back:
                    return None
                curr = closes[-1][1]
                prev = closes[-1 - n_back][1]
                return pct_change(curr, prev)

            entry = {"instrument": inst}
            # approximate:
            # 1h: compare last close vs 1 candle back on H1
            entry["chg_1h_pct"] = _chg_from_closes(h1, 1)
            # 4h: compare last close vs 1 candle back on H4
            entry["chg_4h_pct"] = _chg_from_closes(h4, 1)
            # 1d: compare last close vs 1 candle back on D
            entry["chg_1d_pct"] = _chg_from_closes(d1, 1)
            entry["price"] = (h1[-1][1] if h1 else (d1[-1][1] if d1 else None))
            snap["oanda"][inst] = entry
    else:
        snap["notes"].append("OANDA_API_KEY missing => XAU/XAG intraday snapshot unavailable.")

    return snap

def snapshot_to_prompt_block(snapshot: dict) -> str:
    # keep compact to save tokens
    return json.dumps(snapshot, ensure_ascii=False)

# ==============================================================================
# 9) AI prompt with snapshot
# ==============================================================================
def build_prompt(lang_instruction: str, n_items: int, snapshot_json: str) -> str:
    return f"""
You are an Elite Macro & Metals Strategist. Analyze news for XAU/USD (Gold vs USD).

MARKET SNAPSHOT (recent pricing context; may be daily for some series):
{snapshot_json}

CONTEXT MODE:
- Read ALL items to understand overall context, then score EACH item.

INTER-MARKET (key drivers):
- Gold typically moves inverse to USD (DXY proxy) and US Treasury yields (nominal/real).
- If news implies USD up or yields up => XAU down => SELL.
- If news implies USD down or yields down => XAU up => BUY.
- War/geopolitical crisis/political unrest => safe haven => BUY.

RELEVANCE FILTER (MANDATORY):
- If a news item has NO meaningful link to:
  (USD/DXY proxy, US yields, Fed/US macro, geopolitical risk, precious metals),
  then: signal="SIDEWAY" AND score=0.0.

SIDEWAY WITH NONZERO:
- If relevant but mixed/uncertain => signal="SIDEWAY", score 0.10..0.60.

PRECIOUS METALS CO-MOVE:
- Gold (XAU) and Silver (XAG) are precious metals and often move in the SAME direction.
- Treat silver news as aligned with gold unless explicitly contradicted.

OUTPUT:
- Return ONLY a valid JSON Array (no markdown).
- Must include every ID from 0..{n_items-1}.
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
    snapshot_json = snapshot_to_prompt_block(snapshot)
    system_prompt = build_prompt(lang_instruction, n, snapshot_json)

    last_raw = None
    last_err = None

    for model_name in MODEL_LIST:
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
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
# 10) CONTROL PANEL
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
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    f"AI: {'ON' if AI_AVAILABLE else 'OFF'} | "
    f"VNW key: {'OK' if bool(VNWALLSTREET_SECRET_KEY) else 'MISSING'} | "
    f"OANDA: {'ON' if bool(OANDA_API_KEY) else 'OFF'} | "
    f"Prompt: {PROMPT_VERSION}"
)

# ==============================================================================
# 11) PIPELINE: incremental translation + incremental scoring + snapshot prompt
# ==============================================================================
conn = init_db()

# Market snapshot (cached)
snapshot = get_market_snapshot()

# Show snapshot box
with st.container():
    usd = snapshot["fred"].get("usd_proxy_dtwexbgs", {})
    dgs10 = snapshot["fred"].get("us10y_dgs10", {})
    dfii10 = snapshot["fred"].get("us10y_real_dfii10", {})
    vix = snapshot["fred"].get("vix_vixcls", {})
    xau = snapshot["oanda"].get("XAU_USD", {})
    xag = snapshot["oanda"].get("XAG_USD", {})

    st.markdown(
        f"""
        <div class="dashboard-box">
          <div class="small-muted">Market Snapshot (context for AI)</div>
          <div class="kv">USD proxy (DTWEXBGS): {usd.get('value', 'N/A')} | 1D: {usd.get('chg_1d_pct', 'N/A')}</div>
          <div class="kv">US10Y (DGS10): {dgs10.get('value', 'N/A')}% | Δ1D(bps): {dgs10.get('chg_1d_bps', 'N/A')}</div>
          <div class="kv">Real 10Y (DFII10): {dfii10.get('value', 'N/A')}% | Δ1D(bps): {dfii10.get('chg_1d_bps', 'N/A')}</div>
          <div class="kv">VIX (VIXCLS): {vix.get('value', 'N/A')} | 1D: {vix.get('chg_1d_pct', 'N/A')}</div>
          <div class="kv">XAUUSD: {xau.get('price','N/A')} | 1h: {xau.get('chg_1h_pct','N/A')} | 4h: {xau.get('chg_4h_pct','N/A')} | 1d: {xau.get('chg_1d_pct','N/A')}</div>
          <div class="kv">XAGUSD: {xag.get('price','N/A')} | 1h: {xag.get('chg_1h_pct','N/A')} | 4h: {xag.get('chg_4h_pct','N/A')} | 1d: {xag.get('chg_1d_pct','N/A')}</div>
          <div class="small-muted">asof UTC: {snapshot.get('asof_utc')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Fetch news
raw_items, fetch_err = fetch_latest_news(FETCH_LIMIT)
if fetch_err:
    st.error(fetch_err)

if not raw_items:
    st.warning("⚠️ No data returned.")
else:
    current = []
    for it in raw_items:
        raw_text = normalize_text(it.get("title") or it.get("content") or "")
        raw_ts = int(it.get("createtime") or it.get("showtime") or 0)
        if raw_ts > 1000000000000:
            raw_ts = int(raw_ts / 1000)

        fp = fingerprint_item(raw_ts, raw_text)
        db_upsert_news(conn, fp, raw_ts, raw_text)

        current.append({"fp": fp, "source_ts": raw_ts, "raw_text": raw_text})

    # incremental translations
    english_texts = []
    display_texts = []
    new_translate_count = 0
    for item in current:
        fp = item["fp"]
        raw_text = item["raw_text"]

        en = db_get_translation(conn, fp, "en")
        if en is None:
            en = get_or_make_translation(conn, fp, raw_text, "en")
            new_translate_count += 1
        english_texts.append(en)

        disp = db_get_translation(conn, fp, target_lang)
        if disp is None:
            disp = get_or_make_translation(conn, fp, raw_text, target_lang)
            new_translate_count += 1
        display_texts.append(disp)

    # incremental scoring check
    need_score_idx = []
    cached_scores = [None] * len(current)
    for i, item in enumerate(current):
        sc = db_get_score(conn, item["fp"], PROMPT_VERSION)
        cached_scores[i] = sc
        if sc is None:
            need_score_idx.append(i)

    placeholder = st.empty()

    # Phase 1: show immediately
    with placeholder.container():
        st.info(
            f"✅ Loaded {len(current)} items. New translations this run: {new_translate_count}. "
            f"New items needing AI scoring: {len(need_score_idx)}."
        )
        for i, item in enumerate(current):
            try:
                t_str = datetime.datetime.fromtimestamp(item["source_ts"], CURRENT_TZ).strftime("%H:%M")
            except Exception:
                t_str = "--:--"

            sc = cached_scores[i]
            if sc is None:
                color = "#4B5563"
                badge = '<span class="ai-loading">⚡ AI analyzing…</span>'
                reason = ""
            else:
                sig = (sc.get("signal") or "SIDEWAY").upper()
                score = float(sc.get("score") or 0.0)
                reason = sc.get("reason") or ""

                if sig == "BUY" and score > 0:
                    color = "#10B981"
                    label = "BUY XAU"
                elif sig == "SELL" and score > 0:
                    color = "#EF4444"
                    label = "SELL XAU"
                else:
                    color = "#FFD700" if score > 0 else "#6B7280"
                    label = "SIDEWAY"

                badge = f'<span class="ai-badge" style="background:{color};">{label} {int(score*100)}%</span>'

            st.markdown(
                f"""
                <div class="news-card" style="border-left:5px solid {color};">
                    <span class="time-badge">[{t_str}]</span>
                    {badge}
                    <div class="news-text">{display_texts[i]}</div>
                    {"<span class='ai-reason'>💡 "+reason+"</span>" if reason else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Phase 2: AI only if new items
    used_model, ai_raw, ai_err = None, None, None
    stored_count = 0

    if need_score_idx:
        results, used_model, ai_raw, ai_err = call_ai_with_fallback(english_texts, ai_lang_instruction, snapshot)

        res_map = {}
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and "id" in r:
                    try:
                        res_map[int(r["id"])] = r
                    except Exception:
                        pass

        if used_model:
            db_set_meta(conn, "last_ai_model", used_model)
            db_set_meta(conn, "last_ai_at", str(int(time.time())))

        for idx in need_score_idx:
            fp = current[idx]["fp"]
            r = res_map.get(idx) or (
                results[idx] if isinstance(results, list) and idx < len(results) and isinstance(results[idx], dict) else None
            )
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
            stored_count += 1

        # reload cached scores
        for i, item in enumerate(current):
            cached_scores[i] = db_get_score(conn, item["fp"], PROMPT_VERSION)

        # Phase 3: render dashboard + final list
        with placeholder.container():
            if ai_err:
                st.warning(f"AI error: {ai_err}")
                if ai_raw:
                    with st.expander("DEBUG: AI raw output", expanded=False):
                        st.text(ai_raw)

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

            model_used = used_model or db_get_meta(conn, "last_ai_model") or "(none)"
            st.markdown(
                f"""
                <div class="dashboard-box">
                  <div class="small-muted">XAU/USD Signal (news + market snapshot)</div>
                  <h2 style="color:{tcolor}; margin:6px 0 0 0;">{trend}</h2>
                  <div style="color:#ddd; margin-top:8px;">Strength: {avg:.2f}</div>
                  <div style="color:#bbb; font-size:0.9em; margin-top:10px; font-style:italic;">{msg}</div>
                  <div class="small-muted" style="margin-top:12px; border-top:1px solid #333; padding-top:8px;">
                    Model: {model_used} • Stored new scores: {stored_count}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            for i, item in enumerate(current):
                sc = cached_scores[i]
                try:
                    t_str = datetime.datetime.fromtimestamp(item["source_ts"], CURRENT_TZ).strftime("%H:%M")
                except Exception:
                    t_str = "--:--"

                if not sc:
                    color = "#6B7280"
                    label = "SIDEWAY"
                    pct = 0
                    reason = "No score"
                else:
                    sig = (sc.get("signal") or "SIDEWAY").upper()
                    score = float(sc.get("score") or 0.0)
                    reason = sc.get("reason") or ""

                    if sig == "BUY" and score > 0:
                        color = "#10B981"
                        label = "BUY XAU"
                    elif sig == "SELL" and score > 0:
                        color = "#EF4444"
                        label = "SELL XAU"
                    else:
                        color = "#FFD700" if score > 0 else "#6B7280"
                        label = "SIDEWAY"
                    pct = int(score * 100)

                st.markdown(
                    f"""
                    <div class="news-card" style="border-left:5px solid {color}; opacity:{1.0 if (sc and float(sc.get('score',0))>0) else 0.65};">
                      <span class="time-badge">[{t_str}]</span>
                      <span class="ai-badge" style="background:{color};">{label} {pct}%</span>
                      <div class="news-text">{display_texts[i]}</div>
                      <span class="ai-reason">💡 {reason}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

# ==============================================================================
# 12) COUNTDOWN AUTO-REFRESH
# ==============================================================================
footer = st.empty()
next_time = datetime.datetime.now() + datetime.timedelta(seconds=AUTO_REFRESH_SECONDS)
for i in range(AUTO_REFRESH_SECONDS, 0, -1):
    footer.markdown(
        f"""
        <div class="countdown-bar">
            ⏳ Auto-refresh in <b style="color:#FFD700;">{i}</b>s
            <span class="small-muted">| Next: {next_time.strftime('%H:%M:%S')}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    time.sleep(1)

st.rerun()
