import os
import json
import time
import hashlib
import datetime
import statistics
import re
import requests
import streamlit as st
from deep_translator import GoogleTranslator

# ==============================================================================
# 0) LOAD SECRETS (KHÔNG hardcode)
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
# 1) AI MODELS (FALLBACK)
# ==============================================================================
MODEL_LIST = [
    "gpt-oss-120b",
    "qwen-3-235b-a22b-instruct-2507",
    "qwen-3-32b",
]

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
# 2) STREAMLIT PAGE + CSS
# ==============================================================================
st.set_page_config(
    page_title="XAU/USD Intelligence (USD/Yields → Gold)",
    page_icon="🏆",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
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
    transition: all 0.2s ease;
}

/* TEXT */
.time-badge { color: #6B7280; font-family: monospace; font-size: 0.85em; margin-right: 8px; }
.news-text { color: #e6edf3; font-size: 15px; line-height: 1.55; font-weight: 500; }

/* BADGE */
.ai-badge {
    font-weight: 800;
    padding: 4px 8px;
    border-radius: 4px;
    color: white;
    font-size: 0.75em;
    margin-right: 8px;
    text-transform: uppercase;
    display: inline-block;
}

/* loading */
@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
.ai-loading {
    color: #F59E0B;
    font-style: italic;
    font-size: 0.85em;
    display: block;
    margin-top: 5px;
    animation: pulse 1.5s infinite;
}

/* reason */
.ai-reason {
    display: block;
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px dashed #374151;
    color: #F59E0B;
    font-size: 0.9em;
    font-style: italic;
}

.countdown-bar {
    text-align: center;
    color: #6B7280;
    margin-top: 30px;
    padding: 10px;
    background: #0d1117;
    border-radius: 8px;
    border: 1px solid #30363d;
}
.small-muted { color:#6B7280; font-size:0.85em; }
</style>
""",
    unsafe_allow_html=True,
)

# ==============================================================================
# 3) HELPERS: TRANSLATE, JSON PARSE, API FETCH (SIGNATURE)
# ==============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def cached_translate(text: str, target: str = "en") -> str:
    if not text:
        return ""
    if target == "vi":
        return text
    try:
        return GoogleTranslator(source="auto", target=target).translate(text)
    except Exception:
        return text

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

def get_news_data():
    if not VNWALLSTREET_SECRET_KEY:
        return [], "Missing VNWALLSTREET_SECRET_KEY"

    API_URL = "https://vnwallstreet.com/api/inter/newsFlash/page"
    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://vnwallstreet.com/",
        "Accept": "application/json",
    }

    try:
        ts = int(time.time() * 1000)
        params = {
            "limit": 20,
            "uid": "-1",
            "start": "0",
            "token_": "",
            "key_": VNWALLSTREET_SECRET_KEY,
            "time_": ts,
        }

        sorted_keys = sorted(params.keys())
        query = "&".join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hashlib.md5(query.encode("utf-8")).hexdigest().upper()

        del params["key_"]
        params["sign_"] = sign

        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}: {resp.text}"
        data = resp.json()
        return data.get("data", []) or [], None
    except Exception as e:
        return [], f"Fetch error: {e}"

# ==============================================================================
# 4) CORE AI: CONTEXT-AWARE + USD/YIELDS FILTER + XAU/XAG CO-MOVE
# ==============================================================================
def analyze_news_with_context_fallback(news_list, lang_instruction: str):
    if not AI_AVAILABLE or client is None:
        return [], None, None, "Cerebras client not available (missing SDK or API key)"
    if not news_list:
        return [], None, None, "Empty news list"

    content_lines = []
    for idx, item in enumerate(news_list):
        raw_text = (item.get("title") or item.get("content") or "").strip()
        eng = cached_translate(raw_text, "en")
        content_lines.append(f"ID {idx}: {eng}")
    content_str = "\n".join(content_lines)

    system_prompt = f"""
You are an Elite Macro & Metals Strategist.
Analyze news for XAU/USD (Gold vs USD).

INTER-MARKET:
- Gold usually moves inverse to USD (DXY) and US Treasury yields.
- If news implies USD or yields UP => XAU down => SELL.
- If news implies USD or yields DOWN => XAU up => BUY.
- War/geopolitical crisis/political unrest => safe haven => BUY.

RELEVANCE FILTER (IMPORTANT):
- If a news item has NO meaningful link to USD (DXY), US yields/treasuries, Fed/US macro, geopolitical risk, or precious metals,
  then: signal="SIDEWAY" and score=0.0.

SIDEWAY WITH NONZERO:
- If relevant but mixed/uncertain => signal="SIDEWAY", score 0.10..0.60.

PRECIOUS METALS CO-MOVE:
- Gold (XAU) and Silver (XAG) are precious metals and often move in the SAME direction.
- Treat silver news as aligned with gold unless clearly contradicted.

OUTPUT:
- Return ONLY a valid JSON Array, no markdown.
- Must include every ID 0..{len(news_list)-1}
Schema:
{{
  "id": int,
  "signal": "BUY"|"SELL"|"SIDEWAY",
  "score": float 0.0..0.99,
  "reason": "in {lang_instruction} (max 18 words)"
}}
"""

    used_model = None
    last_raw = None
    last_err = None

    for model_name in MODEL_LIST:
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_str},
                ],
                temperature=0.1,
                max_tokens=4000,
            )
            raw = resp.choices[0].message.content
            last_raw = raw
            results = parse_json_array_loose(raw)
            if not isinstance(results, list):
                raise ValueError("AI output is not a JSON array")
            used_model = model_name
            return results, used_model, last_raw, None
        except Exception as e:
            last_err = f"{model_name} failed: {e}"
            continue

    return [], None, last_raw, last_err or "All models failed"

# ==============================================================================
# 5) UI: CONTROL PANEL
# ==============================================================================
st.title("🏆 XAU/USD Intelligence (USD/Yields relevance filter + XAU/XAG co-move)")

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])

    with c1:
        LANGUAGES = {"🇻🇳 Tiếng Việt": "vi", "🇬🇧 English": "en"}
        sel_lang = st.selectbox("Ngôn ngữ / Language:", list(LANGUAGES.keys()))
        target_lang = LANGUAGES[sel_lang]
        ai_lang_instruct = "Vietnamese" if target_lang == "vi" else "English"

    with c2:
        TIMEZONES = {
            "Vietnam (UTC+7)": 7,
            "New York (UTC-5)": -5,
            "London (UTC+0)": 0,
            "Tokyo (UTC+9)": 9,
        }
        sel_tz = st.selectbox("Múi giờ / Timezone:", list(TIMEZONES.keys()))
        CURRENT_TZ = datetime.timezone(datetime.timedelta(hours=TIMEZONES[sel_tz]))

    with c3:
        st.write("")
        if st.button("🔄 REFRESH", use_container_width=True):
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    f"AI: {'ON' if AI_AVAILABLE else 'OFF'} | "
    f"VNW key: {'OK' if bool(VNWALLSTREET_SECRET_KEY) else 'MISSING'}"
)

# ==============================================================================
# 6) MAIN: FETCH → SHOW GRAY → AI → SHOW COLORED + DASHBOARD
# ==============================================================================
AUTO_REFRESH_SECONDS = 120
raw_news, fetch_err = get_news_data()
if fetch_err:
    st.error(fetch_err)

if raw_news:
    placeholder = st.empty()

    # Phase 1: show gray immediately
    with placeholder.container():
        st.info(f"⏳ Showing {len(raw_news)} items first. AI will score XAU/USD after...")
        for item in raw_news:
            try:
                ts = int(item.get("createtime") or item.get("showtime") or 0)
                if ts > 1000000000000:
                    ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except Exception:
                t_str = "--:--"

            raw_text = (item.get("title") or item.get("content") or "").strip()
            display_text = cached_translate(raw_text, target_lang)

            st.markdown(
                f"""
                <div class="news-card" style="border-left: 5px solid #4B5563;">
                    <span class="time-badge">[{t_str}]</span>
                    <span class="ai-loading">⚡ AI analyzing relevance to USD/Yields + XAU/XAG…</span>
                    <div class="news-text">{display_text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Phase 2: AI
    results, used_model, raw_ai, ai_err = analyze_news_with_context_fallback(raw_news, ai_lang_instruct)

    # Phase 3: render
    with placeholder.container():
        if ai_err:
            st.warning(f"AI error: {ai_err}")
            if raw_ai:
                with st.expander("DEBUG: AI raw output", expanded=False):
                    st.text(raw_ai)

        result_map = {}
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and "id" in r:
                    result_map[int(r["id"])] = r

        display_items = []
        buy_sell_scores = []  # only BUY/SELL score>0 affects trend

        for idx, item in enumerate(raw_news):
            r = result_map.get(idx)
            if r is None and isinstance(results, list) and idx < len(results) and isinstance(results[idx], dict):
                r = results[idx]

            signal = "SIDEWAY"
            score = 0.0
            reason = "No signal"

            if isinstance(r, dict):
                signal = str(r.get("signal", "SIDEWAY")).upper().strip()
                try:
                    score = float(r.get("score", 0.0))
                except Exception:
                    score = 0.0
                reason = str(r.get("reason", reason)).strip()

            # bounds
            score = max(0.0, min(0.99, score))

            if signal == "BUY" and score > 0:
                color = "#10B981"
                label = "BUY XAU"
                buy_sell_scores.append(+score)
            elif signal == "SELL" and score > 0:
                color = "#EF4444"
                label = "SELL XAU"
                buy_sell_scores.append(-score)
            else:
                # sideway
                if score > 0:
                    color = "#FFD700"  # relevant but uncertain
                    label = "SIDEWAY"
                else:
                    color = "#6B7280"  # irrelevant => 0%
                    label = "SIDEWAY"

            try:
                ts = int(item.get("createtime") or item.get("showtime") or 0)
                if ts > 1000000000000:
                    ts /= 1000
                t_str = datetime.datetime.fromtimestamp(ts, CURRENT_TZ).strftime("%H:%M")
            except Exception:
                t_str = "--:--"

            raw_text = (item.get("title") or item.get("content") or "").strip()
            display_text = cached_translate(raw_text, target_lang)

            display_items.append(
                {
                    "time": t_str,
                    "text": display_text,
                    "signal": label,
                    "score": score,
                    "reason": reason,
                    "color": color,
                }
            )

        # dashboard from buy/sell only
        avg = statistics.mean(buy_sell_scores) if buy_sell_scores else 0.0
        if avg > 0.15:
            trend = "LONG / BUY XAUUSD 📈"
            tcolor = "#10B981"
            msg = "USD/Yields down or risk-off → XAU & XAG often rise"
        elif avg < -0.15:
            trend = "SHORT / SELL XAUUSD 📉"
            tcolor = "#EF4444"
            msg = "USD/Yields up → XAU & XAG often pressured"
        else:
            trend = "SIDEWAY / WAIT ⚠️"
            tcolor = "#FFD700"
            msg = "No strong USD/Yields-driven edge detected"

        model_status = f"✅ Model: {used_model}" if used_model else "⚠️ Model: none"
        st.markdown(
            f"""
            <div class="dashboard-box">
                <div class="small-muted">XAU/USD Inter-market Signal</div>
                <h2 style="color:{tcolor}; margin:6px 0 0 0;">{trend}</h2>
                <div style="color:#ddd; margin-top:8px;">Strength: {avg:.2f}</div>
                <div style="color:#bbb; font-size:0.9em; margin-top:10px; font-style:italic;">{msg}</div>
                <div class="small-muted" style="margin-top:12px; border-top:1px solid #333; padding-top:8px;">{model_status}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for it in display_items:
            opacity = 1.0 if it["score"] > 0 else 0.65
            st.markdown(
                f"""
                <div class="news-card" style="border-left: 5px solid {it['color']}; opacity:{opacity};">
                    <span class="time-badge">[{it['time']}]</span>
                    <span class="ai-badge" style="background-color:{it['color']};">{it['signal']} {int(it['score']*100)}%</span>
                    <div class="news-text">{it['text']}</div>
                    <span class="ai-reason">💡 {it['reason']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
else:
    st.warning("⚠️ No data returned (or missing VNWALLSTREET_SECRET_KEY).")

# ==============================================================================
# 7) COUNTDOWN AUTO-REFRESH
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
