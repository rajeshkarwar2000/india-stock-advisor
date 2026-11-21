import datetime as dt, json, os, re, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, streamlit as st, yfinance as yf
import streamlit.components.v1 as components

FILES_VERSION = 15     # engine.py and ui.py must carry the same number

def _files_ok():
    try:
        import engine as _e, ui as _u
        return getattr(_e, "FILES_VERSION", 0) >= FILES_VERSION and getattr(_u, "FILES_VERSION", 0) >= FILES_VERSION
    except Exception:
        return False

if not _files_ok():
    # app.py is newer than engine.py / ui.py (a partly updated repo). Repair them from the zip kept in the repo, if it is there.
    _here = os.path.dirname(os.path.abspath(globals().get("__file__", "app.py")))
    for _zp in (os.path.join(_here, "india-stock-advisor.zip"), "india-stock-advisor.zip"):
        if os.path.exists(_zp):
            try:
                with zipfile.ZipFile(_zp) as _z:
                    for _n in _z.namelist():
                        if os.path.basename(_n) in ("engine.py", "ui.py", "gemini_client.py") and "/android/" not in _n and "/tests/" not in _n:
                            with open(os.path.join(_here, os.path.basename(_n)), "wb") as _f: _f.write(_z.read(_n))
            except Exception:
                pass
            break
    for _m in ("engine", "ui", "gemini_client"): sys.modules.pop(_m, None)
    if not _files_ok():
        st.error("Some app files are older than app.py (engine.py or ui.py). Upload the newest india-stock-advisor.zip to the repo root "
                 "(replace the old one), wait for the GitHub Action to finish, then reboot the app.")
        st.stop()
import engine as E
import gemini_client as G
import ui as U

st.set_page_config(page_title="India Stock Advisor", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
IST = ZoneInfo("Asia/Kolkata")
now_ist = lambda: dt.datetime.now(IST)
NONCE = f"{time.time():.3f}"
HZ = {"1M": "1 Month", "6M": "6 Months", "1Y": "1 Year"}
KIND_HZ = E.HORIZON_TAGS                      # short -> 1M, mid -> 6M, long -> 1Y
st.markdown('<div class="gw-title">📈 India Stock Advisor<span>Practice account with virtual money. Ideas are research aids, not guarantees or SEBI-registered advice.</span></div>', unsafe_allow_html=True)

user = re.sub(r"[^a-z0-9_-]", "", str(st.session_state.get("user_name", "me")).lower()) or "me"

# ---------- demo account storage (one JSON file per account name) ----------
os.makedirs("portfolios", exist_ok=True)
path = f"portfolios/{user}.json"
def load_acct():
    try: return json.load(open(path))
    except Exception: return dict(start_cash=1000000.0, trades=[])
if st.session_state.get("acct_user") != user:
    st.session_state.acct, st.session_state.acct_user = load_acct(), user
acct = st.session_state.acct
def save(): json.dump(acct, open(path, "w"))
def flash(msg): st.session_state.setdefault("flash", []).append(msg)

def show_dialog(name, *args):
    """Open a buy / sell / settings window. Queued, then opened on a full rerun, so it also works from inside a live fragment."""
    st.session_state["pending_dlg"] = (name, args); st.rerun(scope="app")

from contextlib import contextmanager
@contextmanager
def box(title, key, sub=""):
    """A titled box around one tool (styled by ui.GROWW_CSS: class card_box_*)."""
    with st.container(border=True, key=f"card_box_{key}"):
        st.markdown(f'<div class="gw-boxh">{U.esc(title)}' + (f'<span>{U.esc(sub)}</span>' if sub else "") + "</div>", unsafe_allow_html=True)
        yield

# ---------- settings: the ⚙️ window in the top bar. Kept for the session and saved with the demo account ----------
APPEARANCE = ("theme", "blur", "fs", "hc", "anim")
DEFAULTS = dict(capital=100000, risk=1.0, auto_on=True, every=60, pf_auto=True, pf_every=60, topn=8, uni=list(E.UNIVERSES)[0], extra="",
                research_on=True, auto_exec=True, gmodel="gemini-flash-latest", gsearch=True,
                theme=E.DEFAULT_THEME, blur=16, fs=16, hc=False, anim=True)
S = {**DEFAULTS, **{k: acct[k] for k in APPEARANCE if k in acct}, **acct.get("settings", {}), **st.session_state.get("cfg", {})}
if S["uni"] not in E.UNIVERSES: S["uni"] = DEFAULTS["uni"]
if S["theme"] not in E.THEMES: S["theme"] = E.DEFAULT_THEME
if acct.get("settings", {}).get("_v", 0) < 2 and "cfg" not in st.session_state: S["every"] = S["pf_every"] = 60      # 1 minute is the standard
_persist = {**{k: S[k] for k in DEFAULTS}, "_v": 2}
if acct.get("settings") != _persist: acct["settings"] = _persist; save()
capital, risk, auto_on, every, pf_auto, pf_every = S["capital"], S["risk"], S["auto_on"], S["every"], S["pf_auto"], S["pf_every"]
topn, uni, extra, research_on, auto_exec, gmodel, gsearch = S["topn"], S["uni"], S["extra"], S["research_on"], S["auto_exec"], S["gmodel"], S["gsearch"]
th, blur, fs, hc, anim = S["theme"], S["blur"], S["fs"], S["hc"], S["anim"]
try: _k = st.secrets.get("GEMINI_API_KEY", "")
except Exception: _k = ""
gkey = st.session_state.get("gkey") or _k or os.environ.get("GEMINI_API_KEY", "")
def inject_css(css_html):
    """Put the CSS straight into the page <head> (a markdown block gets cut off partway and prints as text)."""
    css = re.sub(r"</?style[^>]*>", "", css_html)
    components.html("<script>try{const d=window.parent.document;let s=d.getElementById('gw-css');if(!s){s=d.createElement('style');s.id='gw-css';d.head.appendChild(s)}"
                    "s.textContent=" + json.dumps(css).replace("</", "<\\/") + ";}catch(e){}</script>", height=0)
inject_css(E.theme_css(th, blur, 22, anim, fs, hc) + U.GROWW_CSS)

_secs = lambda s: f"{s} sec" if s < 60 else f"{s // 60} min"
def _pick(label, options, current, key, fmt=str):
    """Capsule choice: one option highlighted. Never returns None (tapping the chosen one again keeps it)."""
    v = st.pills(label, options, selection_mode="single", default=current if current in options else options[0], format_func=fmt, key=key)
    return current if v is None else v
def _onoff(label, current, key, help=None):
    v = st.pills(label, ["On", "Off"], selection_mode="single", default="On" if current else "Off", key=key, help=help)
    return bool(current) if v is None else v == "On"
_BLUR = {"Off": 0, "Low": 8, "Medium": 16, "High": 24}; _FS = {"Small": 15, "Normal": 16, "Large": 18, "Extra large": 20}
_near = lambda d, v: min(d, key=lambda k: abs(d[k] - v))

@st.dialog("⚙️ Settings", width="large")
def settings_dialog():
    st.caption("Pick an option in each block. Nothing changes until you tap **Save & apply**.")
    with box("👤 Account", "st_acc", "Each name keeps its own virtual portfolio"):
        n_user = st.text_input("Demo account name", user, key="st_user")
        n_cap = st.number_input("Capital for sizing ideas (₹)", 10000, 100000000, int(S["capital"]), step=10000, key="st_cap")
        n_risk = _pick("Max loss per trade (% of capital)", [0.5, 1.0, 1.5, 2.0, 3.0], float(S["risk"]), "st_risk", lambda x: f"{x:g}%")
    with box("⏱ Market refresh", "st_mk", "Explore prices and the market bar"):
        n_auto = _onoff("Auto-refresh", bool(S["auto_on"]), "st_auto", "Updates by itself without reloading the page.")
        n_every = st.slider("Refresh every (seconds)", 10, 300, min(max(int(S["every"]), 10), 300), step=5, key="st_every", format="%d sec",
                            help="Anything from 10 seconds to 5 minutes. Standard: 60 seconds (1 minute).")
    with box("💼 Portfolio refresh", "st_pf", "Only your holdings"):
        n_pauto = _onoff("Auto-refresh", bool(S["pf_auto"]), "st_pauto", "The dial in the Current value card shows the time left.")
        n_pevery = st.slider("Refresh every (seconds)", 10, 300, min(max(int(S["pf_every"]), 10), 300), step=5, key="st_pevery", format="%d sec",
                             help="Anything from 10 seconds to 5 minutes. Standard: 60 seconds (1 minute).")
    with box("💡 Ideas & scan", "st_id"):
        n_topn = _pick("Ideas per list", [5, 8, 10, 15], int(S["topn"]), "st_topn")
        n_uni = _pick("Stock universe", list(E.UNIVERSES), S["uni"], "st_uni")
        n_extra = st.text_input("Add NSE symbols to the lists (comma-separated)", S["extra"], key="st_extra")
        n_res = _onoff("Use analyst & results data (slower)", bool(S["research_on"]), "st_res")
    with box("🛡 Order rules", "st_or"):
        n_aex = _onoff("Auto-sell at stop-loss / target", bool(S["auto_exec"]), "st_aex", "Checked whenever the app is open.")
    with box("🤖 Gemini", "st_gm", "Optional: for the in-app chat and one-tap reviews"):
        n_gkey = st.text_input("Gemini API key", gkey, type="password", key="st_gkey", help="Free key from aistudio.google.com. Kept only for this session, never saved to disk.")
        n_gmodel = st.text_input("Gemini model", S["gmodel"], key="st_gmodel")
        n_gsearch = _onoff("Let Gemini search the web (Google Search)", bool(S["gsearch"]), "st_gsearch")
    with box("🎨 Appearance", "st_ap"):
        n_theme = _pick("Theme", list(E.THEMES), S["theme"], "st_theme")
        n_blur = _BLUR[_pick("Glass blur", list(_BLUR), _near(_BLUR, int(S["blur"])), "st_blur")]
        n_fs = _FS[_pick("Text size", list(_FS), _near(_FS, int(S["fs"])), "st_fs")]
        n_hc = _onoff("High contrast (clearest text)", bool(S["hc"]), "st_hc")
        n_anim = _onoff("Animated background", bool(S["anim"]), "st_anim")
    c1, c2 = st.columns(2)
    if c1.button("💾 Save & apply", type="primary", key="st_save", use_container_width=True):
        st.session_state["cfg"] = dict(capital=int(n_cap), risk=float(n_risk), auto_on=bool(n_auto), every=int(n_every), pf_auto=bool(n_pauto), pf_every=int(n_pevery),
                                       topn=int(n_topn), uni=n_uni, extra=n_extra.strip(), research_on=bool(n_res), auto_exec=bool(n_aex),
                                       gmodel=n_gmodel.strip() or DEFAULTS["gmodel"], gsearch=bool(n_gsearch), theme=n_theme, blur=int(n_blur), fs=int(n_fs), hc=bool(n_hc), anim=bool(n_anim))
        st.session_state["user_name"] = re.sub(r"[^a-z0-9_-]", "", n_user.lower()) or "me"; st.session_state["gkey"] = n_gkey.strip()
        flash("⚙️ Settings saved"); st.rerun()
    if c2.button("↩️  Restore defaults", key="st_reset", use_container_width=True):
        st.session_state["cfg"] = dict(DEFAULTS); flash("Settings restored to defaults"); st.rerun()

for _m in st.session_state.pop("flash", []): st.toast(_m)

# ---------- data ----------
def _dl(tickers, period="3y"):
    df = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, threads=True)
    if df is None or df.empty: return pd.DataFrame()
    c = df["Close"] if isinstance(df.columns, pd.MultiIndex) or "Close" in df.columns else df
    if isinstance(c, pd.Series): c = c.to_frame(tickers[0])
    c.index = pd.to_datetime(c.index).tz_localize(None)
    return c

@st.cache_data(ttl=3600, show_spinner="Fetching latest NSE prices…")
def load(symbols):
    frames = []
    for i in range(0, len(symbols), 80):
        try: frames.append(_dl([s + ".NS" for s in symbols[i:i + 80]]))
        except Exception: pass
    frames = [f for f in frames if len(f)]
    if not frames: raise RuntimeError("No price data returned (Yahoo may be busy). Try again in a minute.")
    df = pd.concat(frames, axis=1); df.columns = [c.replace(".NS", "") for c in df.columns]
    return df.dropna(how="all").dropna(axis=1, how="all")

@st.cache_data(ttl=3600, show_spinner=False)
def load_extra(symbols):
    """Any NSE/BSE symbol (tries .NS then .BO, so BSE codes like 545004 work too)."""
    out = {}
    for s in symbols:
        for suf in (".NS", ".BO"):
            try:
                d = _dl([s + suf])
                if len(d.columns) and d.iloc[:, 0].notna().sum() >= 2: out[s] = d.iloc[:, 0]; break
            except Exception: pass
    return pd.DataFrame(out)

def _live_fetch(symbols):
    if not symbols: return {}
    try:
        d = yf.download([s + ".NS" for s in symbols], period="1d", interval="1m" if len(symbols) <= 40 else "5m",
                        progress=False, auto_adjust=True)["Close"]
        if isinstance(d, pd.Series): d = d.to_frame(symbols[0] + ".NS")
        d = d.ffill().iloc[-1].dropna(); d.index = [c.replace(".NS", "") for c in d.index]
        return d.to_dict()
    except Exception:
        return {}

@st.cache_data(ttl=20, show_spinner=False)
def live_prices(symbols):
    """Latest traded price for each symbol (cached 20 s; the top Refresh button clears it)."""
    return _live_fetch(symbols)

@st.cache_data(ttl=20, show_spinner=False)
def index_quotes():
    try: d = yf.download(["^NSEI", "^BSESN"], period="5d", auto_adjust=True, progress=False)["Close"].ffill()
    except Exception: return {}
    out = {}
    for k, v in (("Nifty 50", "^NSEI"), ("Sensex", "^BSESN")):
        if v in d.columns and d[v].notna().sum() >= 2:
            s = d[v].dropna(); out[k] = (float(s.iloc[-1]), float(s.iloc[-1] / s.iloc[-2] - 1) * 100)
    return out

@st.cache_data(ttl=20, show_spinner=False)
def pf_prices(symbols):
    """Prices for your holdings only: its own cache, so the Portfolio refresh never touches the market-wide one."""
    return _live_fetch(symbols), now_ist().strftime("%H:%M:%S")

def refresh_now():
    live_prices.clear(); index_quotes.clear()

def refresh_portfolio():
    pf_prices.clear()

@st.cache_data(ttl=3600, show_spinner=False)
def search_stocks(q):
    try: res = yf.Search(q, max_results=15).quotes
    except Exception: return []
    out, seen = [], set()
    for r in sorted(res, key=lambda r: not str(r.get("symbol", "")).endswith(".NS")):
        sym = str(r.get("symbol", ""))
        if sym.endswith((".NS", ".BO")) and sym[:-3] not in seen:
            seen.add(sym[:-3]); out.append(dict(symbol=sym[:-3], suffix=sym[-3:], name=r.get("longname") or r.get("shortname") or sym))
    return out

def _fund_raw(sym):
    for suf in (".NS", ".BO"):
        try:
            i = yf.Ticker(sym + suf).info
            if i and (i.get("currentPrice") or i.get("regularMarketPrice") or i.get("longName")):
                return dict(name=i.get("longName") or i.get("shortName"), sector=i.get("sector"), rev_g=i.get("revenueGrowth"),
                            eps_g=i.get("earningsGrowth"), margin=i.get("profitMargins"), roe=i.get("returnOnEquity"),
                            de=i.get("debtToEquity"), pe=i.get("trailingPE"), target=i.get("targetMeanPrice"),
                            rec=i.get("recommendationKey"), rec_mean=i.get("recommendationMean"),
                            n_an=i.get("numberOfAnalystOpinions"), inst=i.get("heldPercentInstitutions"))
        except Exception: pass
    return {}

@st.cache_data(ttl=86400, show_spinner="Reading analyst ratings and results data…")
def fund_many(symbols):
    with ThreadPoolExecutor(8) as ex: return dict(zip(symbols, ex.map(_fund_raw, symbols)))

@st.cache_data(ttl=1800, show_spinner=False)
def news(sym):
    for suf in (".NS", ".BO"):
        try:
            out = []
            for it in (yf.Ticker(sym + suf).news or [])[:5]:
                c = it.get("content") or it
                t = c.get("title"); pub = (c.get("provider") or {}).get("displayName") or it.get("publisher")
                if t: out.append(f"{t} ({pub})" if pub else t)
            if out: return out
        except Exception: pass
    return []

MKT = {"Nifty 50": "^NSEI", "Sensex": "^BSESN", "India VIX": "^INDIAVIX", "USD/INR": "INR=X", "Brent crude": "BZ=F",
       "Gold": "GC=F", "S&P 500": "^GSPC", "Nasdaq": "^IXIC", "US 10Y yield": "^TNX"}
@st.cache_data(ttl=900, show_spinner=False)
def market_snapshot():
    try: d = yf.download(list(MKT.values()), period="10d", auto_adjust=True, progress=False)["Close"].ffill()
    except Exception: return {}
    out = {}
    for k, v in MKT.items():
        if v in d.columns and d[v].notna().sum() >= 2:
            s = d[v].dropna(); out[k] = (float(s.iloc[-1]), float(s.iloc[-1] / s.iloc[-2] - 1) * 100)
    return out

# ---------- account helpers ----------
def get_pos():
    """Open positions with any stop-loss / target edits you made later (Portfolio > Gemini review)."""
    pos, realised = E.positions(acct["trades"])
    for s, lv in acct.get("levels", {}).items():
        if s in pos:
            if lv.get("stop"): pos[s]["stop"] = lv["stop"]
            if lv.get("target"): pos[s]["target"] = lv["target"]
    return pos, realised

base = list(dict.fromkeys(E.UNIVERSES[uni] + [s.strip().upper() for s in extra.split(",") if s.strip()]))
try:
    close = load(tuple(base))
except Exception as e:
    st.error(f"Could not fetch data: {e}"); st.stop()
held = list(get_pos()[0])
alias = acct.get("alias", {})
rec_syms = [alias.get(r["symbol"]) or r["symbol"] for r in acct.get("recs", {}).get("items", [])]
order_syms = [o["symbol"] for o in acct.get("orders", [])]
extras = [s for s in dict.fromkeys(acct.get("watch", []) + held + order_syms + rec_syms) if s not in close.columns]
xdf = load_extra(tuple(extras)) if extras else pd.DataFrame()
close_all = pd.concat([close, xdf], axis=1) if len(xdf.columns) else close

# ---------- scoring: technicals + broker/analyst + results ----------
m0 = E.score(E.metrics(close))
cands = tuple(dict.fromkeys(sum([list(m0.sort_values(c, ascending=False).head(20).index) for c in ("short", "mid", "long")], [])))
F = fund_many(cands) if research_on else {}
m = E.blend(m0, F)
Fh = fund_many(tuple(held)) if research_on and held else {}
FA = {**Fh, **F}                                       # fundamentals for ideas and holdings
tops = {k: list(m.dropna(subset=[k + "2"]).sort_values(k + "2", ascending=False).head(topn).index) for k in ("short", "mid", "long")}

# ---------- live prices ----------
need = [s for s in dict.fromkeys(acct.get("watch", []) + order_syms + rec_syms + sum(tops.values(), [])) if s in close_all.columns]
live = dict(live_prices(tuple(need)))
_pf_live, PF_STAMP = pf_prices(tuple(s for s in held if s in close_all.columns))
live.update(_pf_live)
mo = E.market_open(now_ist())
def px(s):
    if s in live: return float(live[s])
    return float(close_all[s].dropna().iloc[-1]) if s in close_all.columns else float("nan")
def prev_close(s):
    if s not in close_all.columns: return float("nan")
    c = close_all[s].dropna()
    if len(c) < 2: return float("nan")
    return float(c.iloc[-2] if (c.index[-1].date() == now_ist().date() or not mo) else c.iloc[-1])
def day_pct(s, price=None):
    price = px(s) if price is None else price; pc = prev_close(s)
    return (price / pc - 1) * 100 if pc == pc and pc and price == price else float("nan")
def price_of(sym):
    v = px(sym)
    if v == v: return v
    d = load_extra((sym,))
    return float(d[sym].dropna().iloc[-1]) if len(d.columns) and sym in d.columns else float("nan")

# ---------- trading ----------
def trade(sym, side, qty, price, stop=None, target=None, product="DELIVERY", horizon=None):
    pos, _ = E.positions(acct["trades"]); cash = E.cash_balance(acct["start_cash"], acct["trades"]); qty = int(qty)
    if qty < 1: return "Quantity must be at least 1."
    if not price == price or price <= 0: return "No price available for this symbol."
    if side == "BUY" and qty * price > cash: return f"Not enough virtual cash (₹{cash:,.0f} available)."
    if side == "SELL" and pos.get(sym, {}).get("qty", 0) < qty: return "You don't hold that many shares."
    if side == "BUY" and sym in pos and pos[sym].get("product", "DELIVERY") != product:
        return f"You already hold {sym} as {pos[sym]['product'].title()}. Use the same product."
    acct["trades"].append(dict(ts=now_ist().replace(tzinfo=None).isoformat(timespec="seconds"), symbol=sym, side=side, qty=qty,
                               price=round(float(price), 2), stop=stop, target=target, product=product, horizon=horizon))
    lv = acct.setdefault("levels", {})
    if side == "BUY" and (stop or target): lv.pop(sym, None)
    if side == "SELL" and sym not in E.positions(acct["trades"])[0]: lv.pop(sym, None)
    save(); return None

def run_orders():
    """Pending limit orders, intraday square-off (3:20 PM) and stop-loss / target auto-sell."""
    msgs, t = [], now_ist()
    for o in list(acct.get("orders", [])):
        last = px(o["symbol"])
        if last != last: continue
        if (last <= o["limit"]) if o["side"] == "BUY" else (last >= o["limit"]):
            err = trade(o["symbol"], o["side"], o["qty"], last, o.get("stop"), o.get("target"), o.get("product", "DELIVERY"), o.get("horizon"))
            acct["orders"].remove(o); save()
            msgs.append(f"✅ Limit {o['side'].lower()} {o['qty']} {o['symbol']} filled @ ₹{last:,.2f}" if not err else f"⚠️ Limit order for {o['symbol']} rejected: {err}")
    for s, p in E.positions(acct["trades"])[0].items():
        last = px(s)
        if p.get("product") == "INTRADAY" and last == last and (pd.Timestamp(p["since"]).date() < t.date() or (t.weekday() < 5 and t.time() >= dt.time(15, 20))):
            if not trade(s, "SELL", p["qty"], last, product="INTRADAY"): msgs.append(f"⏰ {s}: intraday position squared off @ ₹{last:,.2f}")
    if auto_exec:
        for s, p in get_pos()[0].items():
            q, last = p["qty"], px(s)
            if last != last: continue
            if p["stop"] and last <= p["stop"] and not trade(s, "SELL", q, last, product=p.get("product", "DELIVERY")): msgs.append(f"🛑 {s}: stop-loss hit, sold {q} @ ₹{last:,.2f}")
            elif p["target"] and last >= p["target"] and not trade(s, "SELL", q, last, product=p.get("product", "DELIVERY")): msgs.append(f"🎯 {s}: target hit, sold {q} @ ₹{last:,.2f}")
    return msgs

_msgs = run_orders()
if _msgs:
    for _m in _msgs: st.toast(_m)
    st.session_state.msgs = _msgs; st.rerun()
for _m in st.session_state.pop("msgs", []): st.info(_m)

# ---------- portfolio numbers (used by Portfolio, AI review and the live bar) ----------
pos, realised = get_pos()
ltp = {s: px(s) for s in pos}
perf = E.performance(acct["trades"], acct["start_cash"], ltp)
mh = E.metrics(close_all[[s for s in pos if s in close_all.columns]], min_len=3) if pos else pd.DataFrame()

def build_rows():
    rows = []
    for s, p in pos.items():
        avg = p["cost"] / p["qty"]; last = ltp[s] if ltp[s] == ltp[s] else avg
        cur = p["qty"] * last; pc = prev_close(s)
        d_pnl = (last - pc) * p["qty"] if pc == pc else 0.0
        sig, why = E.signal(mh.loc[s], last, p["stop"], p["target"]) if s in mh.index else ("HOLD", "Not enough price history yet")
        f = FA.get(s) or {}
        rows.append(dict(symbol=s, name=f.get("name"), qty=p["qty"], avg=avg, ltp=last, invested=p["cost"], current=cur,
                         pnl=cur - p["cost"], pnl_pct=(cur / p["cost"] - 1) * 100 if p["cost"] else 0.0,
                         day_pnl=d_pnl, day_pct=(last / pc - 1) * 100 if pc == pc and pc else float("nan"),
                         stop=p["stop"], target=p["target"], horizon=p.get("horizon"), product=p.get("product"), since=p["since"],
                         signal=sig, reason=why, tags=E.tags_for(mh.loc[s], f)[:3] if s in mh.index else []))
    tot = sum(r["current"] for r in rows) or 1.0
    for r in rows: r["weight"] = r["current"] / tot * 100
    return rows
rows = build_rows()
day_total = sum(r["day_pnl"] for r in rows)
day_total_pct = day_total / (perf["current"] - day_total) * 100 if perf["current"] - day_total > 0 else 0.0

def refresh_state():
    """Recompute the portfolio numbers from the latest prices (the live Portfolio fragment calls this every refresh)."""
    global pos, realised, ltp, perf, mh, rows, day_total, day_total_pct
    pos, realised = get_pos(); ltp = {s: px(s) for s in pos}
    perf = E.performance(acct["trades"], acct["start_cash"], ltp)
    mh = E.metrics(close_all[[s for s in pos if s in close_all.columns]], min_len=3) if pos else pd.DataFrame()
    rows = build_rows()
    day_total = sum(r["day_pnl"] for r in rows)
    day_total_pct = day_total / (perf["current"] - day_total) * 100 if perf["current"] - day_total > 0 else 0.0

# live net-worth points for this session (Portfolio > Growth)
_ls = st.session_state.setdefault(f"live_series_{user}", [])
if acct["trades"] and (not _ls or time.time() - _ls[-1][0] >= 10):
    _ls.append((time.time(), perf["net"])); del _ls[:-600]

# ======================================================================
# Windows (dialogs), shared pieces and the live bar
# ======================================================================
snap = market_snapshot()
pc_ = lambda x: "n/a" if x is None or pd.isna(x) else f"{x*100:+.0f}%"
HZ_REV = {v: k for k, v in HZ.items()}

def fund_lines(f, price):
    a = []
    if f.get("rec"): a.append(f"Analysts: **{str(f['rec']).replace('_', ' ')}**" + (f" ({f['n_an']} analysts)" if f.get("n_an") else ""))
    if f.get("target") and price == price: a.append(f"avg target ₹{f['target']:,.0f} ({(f['target']/price-1)*100:+.0f}%)")
    if f.get("inst") is not None: a.append(f"institutions hold {f['inst']*100:.0f}%")
    return " · ".join(a)
def fin_lines(f):
    items = [("Revenue growth", f.get("rev_g"), "pct"), ("Earnings growth", f.get("eps_g"), "pct"), ("Profit margin", f.get("margin"), "pct"),
             ("ROE", f.get("roe"), "pct"), ("Debt/Equity", f.get("de"), "num"), ("P/E", f.get("pe"), "num")]
    return " · ".join(f"{k} {v*100:+.0f}%" if t == "pct" else f"{k} {v:.1f}" for k, v, t in items if v is not None and v == v)

def build_context():
    n = lambda x, f="{:.0f}": "n/a" if x is None or x != x else f.format(x)
    L = [f"As of {close.index[-1]:%d %b %Y}."]
    if snap: L.append("Market snapshot: " + "; ".join(f"{k} {v:,.2f} ({d:+.1f}% 1d)" for k, (v, d) in snap.items()))
    for col, name in (("short2", "1-month shortlist"), ("mid2", "6-month shortlist"), ("long2", "1-year shortlist")):
        out = []
        for s, r in m.dropna(subset=[col]).sort_values(col, ascending=False).head(8).iterrows():
            f = F.get(s) or {}
            x = f"{s}: price {r.price:.0f}, 1M {n(r.r1m*100)}%, 3M {n(r.r3m*100)}%, RSI {n(r.rsi)}, volatility {n(r.vol*100)}%"
            if f: x += f"; analysts {f.get('rec')} (mean target {n(f.get('target'))}); {fin_lines(f)}"
            out.append(x)
        L.append(f"{name} from the app's screen:\n" + "\n".join(out))
    L.append("Demo holdings: " + (", ".join(f"{r['symbol']} x{r['qty']} avg {r['avg']:.0f} now {r['ltp']:.0f}" for r in rows) or "none"))
    if st.session_state.get("scan_ctx"): L.append(st.session_state["scan_ctx"])
    if acct.get("notes"): L.append("My own notes on news / policy / events:\n" + acct["notes"])
    return "\n".join(L)

def copy_open_gemini(prompt, height=110):
    tj = json.dumps(prompt).replace("</", "<\\/")
    components.html(f"""<div style="display:flex;gap:8px">
<button id="c" style="flex:1;padding:12px;border:0;border-radius:10px;background:#00b386;color:#fff;font:600 15px system-ui">📋 Copy prompt</button>
<button id="o" style="flex:1;padding:12px;border:0;border-radius:10px;background:#5367ff;color:#fff;font:600 15px system-ui">🚀 Copy + open Gemini</button></div>
<div id="m" style="font:14px system-ui;margin-top:8px;color:#555"></div>
<script>const t={tj};const $=i=>document.getElementById(i);
async function cp(){{if(window.Android&&Android.copy){{try{{Android.copy(t);return true}}catch(e){{}}}}
try{{await navigator.clipboard.writeText(t);return true}}catch(e){{}}
try{{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();const ok=document.execCommand('copy');a.remove();return ok}}catch(e){{return false}}}}
$('c').onclick=async()=>{{$('m').textContent=(await cp())?'✅ Copied. Now open Gemini and paste.':'⚠️ Copy failed: open Show prompt text below and long-press to copy.'}};
$('o').onclick=async()=>{{const ok=await cp();$('m').textContent=ok?'✅ Prompt copied. Opening Gemini, paste it there.':'Opening Gemini… (copy the prompt from Show prompt text below)';
if(window.Android&&Android.openGemini){{Android.openGemini()}}
else if(/Android/i.test(navigator.userAgent)){{window.open('intent://gemini.google.com/app#Intent;scheme=https;package=com.google.android.apps.bard;S.browser_fallback_url=https%3A%2F%2Fgemini.google.com%2Fapp;end','_top')}}
else{{window.open('https://gemini.google.com/app','_blank')}}}};</script>""", height=height)
    st.link_button("🌐 Open Gemini in browser instead", "https://gemini.google.com/app", use_container_width=True)

def style_df(df, pnl=(), side=None, fmt=None):
    """Colour profit green / loss red (and BUY green / SELL red) in a table; falls back to the plain table."""
    try:
        sty = df.style; mp = sty.map if hasattr(sty, "map") else sty.applymap
        if pnl: sty = mp(lambda v: f"color:{U.UP};font-weight:600" if isinstance(v, (int, float)) and v > 0 else f"color:{U.DOWN};font-weight:600" if isinstance(v, (int, float)) and v < 0 else "", subset=list(pnl))
        if side:
            mp = sty.map if hasattr(sty, "map") else sty.applymap
            sty = mp(lambda v: f"color:{U.UP};font-weight:700" if v == "BUY" else f"color:{U.DOWN};font-weight:700" if v == "SELL" else "", subset=[side])
        return sty.format(fmt or {}, na_rep="–")
    except Exception:
        return df

# ---------- live bar: market status, indices, countdown, refresh ----------
def index_bar():
    iq = index_quotes()
    st.markdown(U.live_bar_html(E.market_open(now_ist()), iq, now_ist().strftime("%H:%M:%S")), unsafe_allow_html=True)
    if iq.get("Nifty 50") and iq["Nifty 50"][1] <= -1.0:
        st.warning(f"The market is down {iq['Nifty 50'][1]:.1f}% (Nifty). New buys are riskier on days like this, so consider waiting and keep your stop-losses on.")
st.fragment(run_every=(every if auto_on else None))(index_bar)()
with st.container(key="topbar"):
    _l2, _l3, _l4 = st.columns([6, 1, 1], vertical_alignment="center")
    with _l2: components.html(U.countdown_html(every if auto_on else 0, "gw-stamp-mk", "Market refresh in"), height=34)
    _l3.button("🔄", key="live_refresh", on_click=refresh_now, help="Refresh market prices now")
    if _l4.button("⚙️", key="open_settings", help="Settings"): show_dialog("settings")

# ---------- Buy window (like Groww: product, order type, quantity, price) ----------
@st.dialog("Buy")
def buy_dialog(sym, name, price, dpct, stop=None, target=None, qty=1, horizon="1M"):
    p0 = get_pos()[0].get(sym); k = f"bd_{sym}_"
    st.markdown(U.dialog_head_html(sym, name, price, dpct, p0["qty"] if p0 else 0, p0["cost"] / p0["qty"] if p0 else None), unsafe_allow_html=True)
    prod = st.radio("Product", ["Delivery", "Intraday"], horizontal=True, key=k + "prod",
                    help="Delivery: keep the shares as long as you like. Intraday: sold automatically at 3:20 PM.")
    if prod == "Intraday" and not mo:
        st.warning("Intraday orders are accepted only while the market is open (9:15 AM to 3:15 PM, Mon-Fri).")
    otype = st.radio("Order type", ["Market", "Limit"], horizontal=True, key=k + "type",
                     help="Market: buy now at the current price. Limit: wait until the price falls to your price (checked whenever the app is open).")
    c1, c2 = st.columns(2)
    q = c1.number_input("Quantity", 1, 10_000_000, int(max(qty, 1)), key=k + "qty")
    if otype == "Limit": lim = c2.number_input("Limit price (₹)", 0.05, 10_000_000.0, float(round(price, 2)), step=0.05, key=k + "lim")
    else: lim = None; c2.text_input("Price", "At market", disabled=True, key=k + "mk")
    hz = st.radio("Investment horizon", list(HZ.values()), index=list(HZ).index(horizon) if horizon in HZ else 0, horizontal=True, key=k + "hz")
    with st.expander("🛡 Stop-loss (required) & target (optional)", expanded=True):
        sl = st.number_input("Stop-loss (₹): sells automatically if the price falls to it. Limits your loss.", 0.0, 10_000_000.0,
                             float(round(stop, 2)) if stop else float(round(price * 0.93, 2)), step=0.05, key=k + "sl",
                             help="Default is 7% below the price. A stop-loss caps the loss on this stock but can't remove it (gaps can fill below it).")
        tg = st.number_input("Target (₹): sells automatically when the price reaches it", 0.0, 10_000_000.0, float(round(target, 2)) if target else 0.0, step=0.05, key=k + "tg")
    at = lim or price; need = q * at; cash_ = E.cash_balance(acct["start_cash"], acct["trades"])
    st.markdown(U.order_box_html([("Order value", U.esc(U.inr(need))), ("Available cash", U.esc(U.inr(cash_))),
                                  ("Cash after order", f'<span class="gw-{"up" if cash_ >= need else "down"}">{U.esc(U.inr(cash_ - need))}</span>')]), unsafe_allow_html=True)
    errs = []
    if not sl: errs.append("A stop-loss is required: it limits how much this stock can lose.")
    if sl and sl >= at: errs.append("Stop-loss must be below the buy price.")
    if tg and tg <= at: errs.append("Target must be above the buy price.")
    if need > cash_: errs.append("Not enough virtual cash for this order.")
    for e_ in errs: st.error(e_)
    if st.button(f"Buy {q} share{'s' if q != 1 else ''}" + (" (limit order)" if lim else ""), type="primary", key="exec_buy", use_container_width=True, disabled=bool(errs)):
        product = "INTRADAY" if prod == "Intraday" else "DELIVERY"
        if product == "INTRADAY" and not mo: st.error("The market is closed, so an intraday order can't be placed."); return
        if lim:
            acct.setdefault("orders", []).append(dict(id=int(time.time() * 1000), ts=now_ist().strftime("%d %b %H:%M"), symbol=sym, side="BUY", qty=int(q),
                                                      limit=float(lim), product=product, stop=sl or None, target=tg or None, horizon=HZ_REV[hz]))
            save(); flash(f"🕒 Limit order placed: buy {q} {sym} at ₹{lim:,.2f} or lower")
        else:
            fresh = live_prices((sym,)).get(sym); fill = float(fresh) if fresh else price
            if sl >= fill: st.error("The price just moved to or below your stop-loss. Lower the stop-loss and try again."); return
            err = trade(sym, "BUY", q, fill, sl or None, tg or None, product, HZ_REV[hz])
            if err: st.error(err); return
            flash(f"✅ Bought {q} {sym} @ ₹{fill:,.2f}")
        st.rerun()

# ---------- Sell window ----------
@st.dialog("Sell")
def sell_dialog(sym, name, price, dpct, qty=None):
    p = get_pos()[0].get(sym); k = f"sd_{sym}_"
    if not p: st.info("You don't hold this stock."); return
    avg = p["cost"] / p["qty"]
    st.markdown(U.dialog_head_html(sym, name, price, dpct, p["qty"], avg), unsafe_allow_html=True)
    mode = st.radio("Quantity", ["All shares", "Some shares"], horizontal=True, index=1 if qty and qty < p["qty"] else 0, key=k + "mode")
    q = p["qty"] if mode == "All shares" else st.number_input("Shares to sell", 1, p["qty"], int(min(max(qty or 1, 1), p["qty"])), key=k + "q")
    otype = st.radio("Order type", ["Market", "Limit"], horizontal=True, key=k + "type",
                     help="Market: sell now at the current price. Limit: wait until the price rises to your price (checked whenever the app is open).")
    lim = st.number_input("Limit price (₹)", 0.05, 10_000_000.0, float(round(price, 2)), step=0.05, key=k + "lim") if otype == "Limit" else None
    at = lim or price; pnl_ = (at - avg) * q
    st.markdown(U.order_box_html([("Buy price (avg)", U.esc(U.inr(avg))), ("Sell price", U.esc(U.inr(at)) if lim else "At market ≈ " + U.esc(U.inr(at))),
                                  ("You receive", U.esc(U.inr(q * at))), ("Profit / loss", U.pnl_html(pnl_, (at / avg - 1) * 100))]), unsafe_allow_html=True)
    if st.button(f"Sell {q} share{'s' if q != 1 else ''}" + (" (limit order)" if lim else ""), key="exec_sell", use_container_width=True):
        if lim:
            acct.setdefault("orders", []).append(dict(id=int(time.time() * 1000), ts=now_ist().strftime("%d %b %H:%M"), symbol=sym, side="SELL", qty=int(q),
                                                      limit=float(lim), product=p.get("product", "DELIVERY")))
            save(); flash(f"🕒 Limit order placed: sell {q} {sym} at ₹{lim:,.2f} or higher")
        else:
            fresh = live_prices((sym,)).get(sym); fill = float(fresh) if fresh else price
            err = trade(sym, "SELL", q, fill, product=p.get("product", "DELIVERY"))
            if err: st.error(err); return
            flash(f"✅ Sold {q} {sym} @ ₹{fill:,.2f} · P&L {U.inr((fill - avg) * q, 2, True)} ({U.pct((fill / avg - 1) * 100)})")
        st.rerun()

def open_buy(sym, name, price, dpct, p=None, kind=None, qty=1):
    stop = tgt = None
    if p:   # a "wait for dip" plan is built around the dip price: keep the same distances but measure them from today's price
        shift = price - p["entry"]
        stop, tgt = p["stop"] + shift, p["target"] + shift
        if not (0 < stop < price < tgt): stop = tgt = None
    show_dialog("buy", sym, name, price, dpct, round(stop, 2) if stop else None, round(tgt, 2) if tgt else None, max(int(qty), 1), KIND_HZ.get(kind, "1M"))

_pd = st.session_state.pop("pending_dlg", None)
if _pd: {"buy": buy_dialog, "sell": sell_dialog, "settings": settings_dialog}[_pd[0]](*_pd[1])

def watch_button(c, sym, key):
    w = acct.setdefault("watch", [])
    if sym in w:
        if c.button("★ Watching", key=f"wt_{key}", use_container_width=True): w.remove(sym); save(); st.rerun()
    elif c.button("☆ Watch", key=f"wt_{key}", use_container_width=True): w.append(sym); save(); st.rerun()

# ======================================================================
# Explore: idea cards, 1M / 6M / 1Y lists, market scan, search
# ======================================================================
def idea_card(sym, r, f, kind, ns, i, gain, months, price, dpct, scan=False):
    r = r.copy(); r["price"] = price
    p = E.plan(r, capital, risk, kind, f.get("target"))
    wait = p["action"].startswith("Wait")
    sig = "SELL" if E.signal(r, price)[0] == "SELL" else ("HOLD" if wait else "BUY")
    tags = U.hz_chip(KIND_HZ[kind]) + U.action_chip(sig) + U.chips(E.tags_for(r, f, scan)[:4])
    sub = " · ".join(x for x in (f.get("name"), f.get("sector")) if x)
    vol = r.vol if r.vol == r.vol else 0.4
    with st.container(border=True, key=f"card_{ns}_{i}"):
        st.markdown(U.stock_head_html(sym, sub, price, dpct, tags) + U.levels_html(price, p["entry"], p["stop"], p["target"]), unsafe_allow_html=True)
        st.caption(f"**{p['action']}** · suggested qty {p['qty']} (≈{U.inr(p['invest'], 0)}) · worst-case loss at stop ≈ {U.inr(p['max_loss'], 0)}")
        st.caption(f"1M {pc_(r.r1m)} · 3M {pc_(r.r3m)} · 6M {pc_(r.r6m)} · 12M {pc_(r.r12m)} · RSI {r.rsi:.0f} · volatility {vol*100:.0f}%"
                   + (f" · {(price/r.hi52-1)*100:.0f}% from 52-week high" if r.hi52 == r.hi52 and r.hi52 else ""))
        if scan: st.caption(f"Avg daily traded value ₹{r.avg_val/1e7:.1f} cr" + (" · thinly traded, use limit orders and small size" if r.avg_val < 5e7 else ""))
        if fund_lines(f, price): st.write(fund_lines(f, price))
        st.caption(f"Model odds of ≥{gain}% in {months} month(s): **{E.p_hit(gain, vol, months)*100:.0f}%**")
        if st.checkbox("🔍 Financials & latest news", key=f"rs_{ns}_{i}"):
            st.write(fin_lines(f) or "No results data available from Yahoo for this stock.")
            for h in news(sym) or ["No recent headlines found."]: st.caption("• " + h)
        c1, c2 = st.columns(2)
        if c1.button("Buy", key=f"buy_{ns}_{i}", type="primary", use_container_width=True): open_buy(sym, f.get("name"), price, dpct, p, kind, p["qty"])
        watch_button(c2, sym, f"{ns}_{i}")

def show_ideas(kind, ns, months, gain, blurb):
    col = kind + "2"
    top = m.dropna(subset=[col]).sort_values(col, ascending=False).head(topn)
    st.caption(blurb + f" Top {len(top)} of {len(m)} stocks, ranked by trend, analyst ratings and results.")
    cols = st.columns(2)
    for n_, (sym, r) in enumerate(top.iterrows()):
        price = px(sym); price = price if price == price else r.price
        with cols[n_ % 2]: idea_card(sym, r, FA.get(sym) or {}, kind, ns, n_, gain, months, price, day_pct(sym, price))

SCOPES = {"Every NSE-listed stock (~2,000+ companies)": ["EQUITY_L"],
          "Nifty 500 + Microcap 250 (~750)": ["ind_nifty500list.csv", "ind_niftymicrocap250_list.csv"],
          "Nifty 500 (~500, fastest)": ["ind_nifty500list.csv"]}
os.makedirs("scan_cache", exist_ok=True)
def scan_path(scope): return "scan_cache/" + re.sub(r"[^a-z0-9]", "", scope.lower())[:24] + ".csv"

@st.cache_data(ttl=86400, show_spinner=False)
def nse_symbols(scope):
    import requests
    hdr = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
    syms = []
    for nm in SCOPES[scope]:
        urls = (["https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "https://archives.nseindia.com/content/equities/EQUITY_L.csv"]
                if nm == "EQUITY_L" else [f"https://nsearchives.nseindia.com/content/indices/{nm}", f"https://archives.nseindia.com/content/indices/{nm}"])
        for u in urls:
            try:
                r = requests.get(u, headers=hdr, timeout=25)
                if r.status_code == 200 and len(r.text) > 500: syms += E.parse_symbol_csv(r.text); break
            except Exception: pass
    return list(dict.fromkeys(syms))

def run_scan(symbols, prog):
    start = (dt.date.today() - dt.timedelta(days=400)).isoformat(); n, step, parts, t0 = len(symbols), 100, [], time.time()
    for i in range(0, n, step):
        done = i / n; eta = (time.time() - t0) / done * (1 - done) if done > 0.02 else None
        prog.progress(min(done + 0.001, 1.0), text=f"Scanning stocks {i + 1}–{min(i + step, n)} of {n}" + (f" · about {int(eta // 60)} min {int(eta % 60)} s left" if eta else ""))
        for attempt in (1, 2):
            try:
                df = yf.download([x + ".NS" for x in symbols[i:i + step]], start=start, auto_adjust=True, progress=False, threads=True)
                if df is None or df.empty: continue
                c, v = df["Close"], df["Volume"]
                if isinstance(c, pd.Series): break
                c.columns = [x.replace(".NS", "") for x in c.columns]; v.columns = [x.replace(".NS", "") for x in v.columns]
                c.index = pd.to_datetime(c.index).tz_localize(None); v.index = c.index
                parts.append(E.metrics(c.dropna(axis=1, how="all"), min_len=60, volume=v)); break
            except Exception: time.sleep(1.5)
    return pd.concat(parts) if parts else pd.DataFrame()

def scan_view():
    with box("① Choose what to scan", "scan1", "Then tap Scan now"):
        c1, c2 = st.columns(2)
        scope = c1.selectbox("1 · Which companies?", list(SCOPES)); profile = c2.selectbox("2 · Risk appetite", list(E.PROFILES))
        st.caption("Higher return potential means higher risk. 'Aggressive' includes small and micro caps that trade thinly. Nobody can guarantee returns.")
        path_s = scan_path(scope); syms = None
        with st.expander("Stock list not downloading? Upload NSE's EQUITY_L.csv instead"):
            up = st.file_uploader("EQUITY_L.csv (from nseindia.com > Market Data > Securities available for trading)", type="csv", key="eq_up")
            if up is not None: syms = E.parse_symbol_csv(up.getvalue().decode("utf-8", "ignore"))
        if st.button("🚀 3 · Scan now", type="primary", use_container_width=True, key="scan_go"):
            syms = syms or nse_symbols(scope)
            if not syms: st.warning("Couldn't download NSE's stock list, so the built-in broad list (~230 stocks) is used."); syms = E.BROAD
            prog = st.progress(0.0, text="Starting…")
            res = run_scan(syms, prog); prog.empty()
            if res.empty: st.error("No price data came back (Yahoo may be busy). Try again in a few minutes.")
            else: res.to_csv(path_s); st.rerun()
    with box("② Results", "scan2", "Ranked for the horizon you pick"):
        if not os.path.exists(path_s):
            st.info("No scan yet. Tap **Scan now**. The full market (~2,000 companies) takes a few minutes: keep the app open. Later visits are instant."); return
        sdf = pd.read_csv(path_s, index_col=0)
        hz = st.radio("4 · Rank by", list(HZ.values()), horizontal=True, key="scan_hz"); kind = {"1M": "short", "6M": "mid", "1Y": "long"}[HZ_REV[hz]]
        sc = {"short": "p1m", "mid": "p6m", "long": "p1y"}[kind]
        pot = E.potential(sdf, profile)
        pot = pot.dropna(subset=["pot"]).sort_values(sc, ascending=False) if sc in pot else pot.iloc[0:0]
        st.caption(f"Scan from {dt.datetime.fromtimestamp(os.path.getmtime(path_s)):%d %b %Y %H:%M} · {len(sdf)} stocks scanned · {len(pot)} pass the '{profile}' liquidity filter. Scan again for fresh prices.")
        top = pot.head(30); F2 = fund_many(tuple(top.index)) if research_on and len(top) else {}
        if not len(top): st.warning("No stocks passed the filter."); return
        bl = E.blend(top.assign(short=top[sc], mid=top[sc], long=top[sc]), F2)
        top = top.assign(final=np.where(bl["fund"].notna(), 0.7 * top[sc] + 0.3 * bl["fund"], top[sc])).sort_values("final", ascending=False).head(topn)
        live.update(live_prices(tuple(top.index)))
        n_ = lambda x, f="{:.0f}": "n/a" if x is None or x != x else f.format(x)
        st.session_state["scan_ctx"] = (f"Market-wide scan top picks ({profile}, {hz}, from {len(sdf)} NSE stocks): " + "; ".join(
            f"{k}: price {r.price:.0f}, 1M {n_(r.r1m*100)}%, 3M {n_(r.r3m*100)}%, volatility {n_(r.vol*100)}%, avg traded value Rs {r.avg_val/1e7:.1f} cr"
            for k, r in top.head(10).iterrows()))
        months, gain = {"short": (1, 20), "mid": (6, 40), "long": (12, 100)}[kind]
        cols = st.columns(2)
        for i, (sym, r) in enumerate(top.iterrows()):
            price = float(live.get(sym) or r.price)
            with cols[i % 2]: idea_card(sym, r, F2.get(sym) or {}, kind, "scan", i, gain, months, price, None, scan=True)

def analyze(sym):
    df = load_extra((sym,))
    if df.empty or sym not in df.columns:
        st.error("No price data found for this symbol on NSE/BSE. Check the symbol or try the BSE code."); return
    mm = E.metrics(df, min_len=3)
    if sym not in mm.index: st.error("Not enough price history yet."); return
    r = mm.loc[sym].copy(); ndays = int(df[sym].notna().sum()); s_ = df[sym].dropna()
    lp = live_prices((sym,)).get(sym); r["price"] = float(lp) if lp else r.price; price = r.price
    dpc = (price / (s_.iloc[-2] if len(s_) > 1 and (s_.index[-1].date() == now_ist().date() or not mo) else s_.iloc[-1]) - 1) * 100 if len(s_) > 1 else float("nan")
    f = fund_many((sym,)).get(sym) or {}; vol = r.vol if r.vol == r.vol else 0.4
    with st.container(border=True, key=f"card_find_{sym}"):
        st.markdown(U.stock_head_html(sym, f.get("name"), price, dpc, U.chips(E.tags_for(r, f)[:4] + ([("New listing", "info")] if ndays < 130 else []))), unsafe_allow_html=True)
        if ndays < 130: st.warning(f"🆕 New listing: only {ndays} trading days of history, so momentum numbers are rough.")
        st.caption(f"1M {pc_(r.r1m)} · 3M {pc_(r.r3m)} · 12M {pc_(r.r12m)} · RSI {'n/a' if r.rsi != r.rsi else f'{r.rsi:.0f}'} · volatility {vol*100:.0f}%")
        if fund_lines(f, price): st.write(fund_lines(f, price))
        if fin_lines(f): st.write(fin_lines(f))
        for kind, label in (("short", "1 month"), ("mid", "6 months"), ("long", "1 year")):
            p = E.plan(r, capital, risk, kind, f.get("target")); sig = "SELL" if E.signal(r, price)[0] == "SELL" else ("HOLD" if p["action"].startswith("Wait") else "BUY")
            st.markdown(f'<div class="gw-chips">{U.hz_chip(KIND_HZ[kind])}{U.action_chip(sig)}<span class="gw-sub">{U.esc(label)} plan · {U.esc(p["action"])} · qty {p["qty"]}</span></div>'
                        + U.levels_html(price, p["entry"], p["stop"], p["target"]), unsafe_allow_html=True)
            if st.button(f"Buy for {label}", key=f"fbuy_{sym}_{kind}", use_container_width=True): open_buy(sym, f.get("name"), price, dpc, p, kind, p["qty"])
        st.caption(f"Model odds of ≥10% in 1 month: {E.p_hit(10, vol, 1)*100:.0f}% · ≥100% in 1 year: {E.p_hit(100, vol, 12)*100:.0f}%")
        for h in news(sym)[:4]: st.caption("• " + h)
        watch_button(st, sym, f"find_{sym}")

def search_view():
    with box("🔍 Find a company", "find", "Any NSE or BSE company"):
        q = st.text_input("Search any company: name, NSE symbol or BSE code", placeholder="e.g. Jio Platforms, JPL, Reliance, 545004")
        if q.strip():
            hits = search_stocks(q.strip())
            opts = {f"{h['name']} — {h['symbol']} ({'NSE' if h['suffix'] == '.NS' else 'BSE'})": h["symbol"] for h in hits}
            manual = re.sub(r"[^A-Za-z0-9&-]", "", q).upper()
            if manual and manual not in opts.values(): opts[f"Try symbol directly: {manual}"] = manual
            pick = st.selectbox("Matches", list(opts))
            if st.button("Analyze", type="primary"): st.session_state["find"] = opts[pick]
        if st.session_state.get("find"): analyze(st.session_state["find"])
    if acct.get("watch"):
        with box("⭐ My watchlist", "watch"):
            cols = st.columns(2)
            for i, s in enumerate(list(acct["watch"])):
                price = price_of(s); dp = day_pct(s, price); nm = (FA.get(s) or {}).get("name")
                with cols[i % 2], st.container(border=True, key=f"card_watch_{i}"):
                    st.markdown(U.stock_head_html(s, nm, price, dp, ""), unsafe_allow_html=True)
                    b1, b2, b3 = st.columns(3)
                    if b1.button("Buy", key=f"buy_watch_{i}", type="primary", use_container_width=True): open_buy(s, nm, price, dp)
                    if b2.button("Analyze", key=f"wa_{i}", use_container_width=True): st.session_state["find"] = s; st.rerun()
                    if b3.button("Remove", key=f"wr_{i}", use_container_width=True): acct["watch"].remove(s); save(); st.rerun()

with st.container(key="mainnav"):      # the main ribbon: styled as iPhone-style pills (see ui.GROWW_CSS)
    t_ex, t_pf, t_ai, t_tools = st.tabs(["🔎 Explore", "💼 Portfolio", "🤖 Gemini", "🛠 Tools"])
def explore_section():
    """Explore area: reruns by itself every market-refresh interval with fresh prices (only this part of the page)."""
    live.update(live_prices(tuple(need)))
    e1, e6, e12, e_scan, e_find = st.tabs(["1 Month", "6 Months", "1 Year", "🚀 Scan all stocks", "🔍 Search & watchlist"])
    with e1, box("1 Month ideas", "i1m"): show_ideas("short", "i1m", 1, 10, "Short-term momentum ideas for about 1 month.")
    with e6, box("6 Months ideas", "i6m"): show_ideas("mid", "i6m", 6, 40, "Medium-term trend ideas for about 6 months.")
    with e12, box("1 Year ideas", "i1y"): show_ideas("long", "i1y", 12, 100, "Long-term strength and stability ideas for about 1 year.")
    with e_scan:
        st.write("Scans the **whole market**, not a fixed list, for stocks with the highest realistic return potential that are still **feasible to trade** (liquidity and price filters).")
        scan_view()
    with e_find: search_view()

with t_ex:
    st.fragment(run_every=(every if auto_on else None))(explore_section)()

# ======================================================================
# Portfolio
# ======================================================================
def protect_all():
    """Give every holding a stop-loss: 7% below the price, or at your buy price once you are comfortably in profit. Never lowers a stop."""
    n = 0
    for r in rows:
        s, last, avg = r["symbol"], r["ltp"], r["avg"]
        want = avg if last >= avg * 1.02 else last * 0.93
        want = round(min(want, last * 0.995), 2)
        if want > (r["stop"] or 0):
            acct.setdefault("levels", {}).setdefault(s, {})["stop"] = want; n += 1
    save(); flash(f"🛡 Stop-loss set or raised on {n} holding{'s' if n != 1 else ''}" if n else "All holdings already have a stop-loss at or above this level.")

def holdings_view():
    with st.container(key="pfhero"):
        hc1, hc2 = st.columns([3, 1], vertical_alignment="center")
        hc1.markdown(U.summary_html(perf, day_total, day_total_pct, len(rows), PF_STAMP, plain=True, part="top"), unsafe_allow_html=True)
        with hc2: components.html(U.dial_html(pf_every if pf_auto else 0, "gw-stamp-pf", "pf_refresh"), height=50)
        st.markdown(U.summary_html(perf, day_total, day_total_pct, len(rows), PF_STAMP, plain=True, part="rest"), unsafe_allow_html=True)
        st.button("🔄", key="pf_refresh", on_click=refresh_portfolio)      # pressed by the dial; hidden by CSS
    if not rows:
        st.info("No holdings yet. Open **Explore**, pick an idea and tap **Buy**."); return
    with box("🛡 Protection", "prot", "Stop-losses cap how much a stock can lose"):
        nostop = [r["symbol"] for r in rows if not r["stop"]]
        if nostop: st.warning("No stop-loss on: " + ", ".join(nostop) + ". Without one, a falling stock keeps losing.")
        st.button("🛡 Protect all holdings (set / raise stop-loss)", key="protect_all", on_click=protect_all, use_container_width=True,
                  help="Stop-loss 7% below the price, or at your buy price once you are 2% or more in profit. It sells automatically (while the app is open) to cap the loss.")
    with box("📦 Your holdings", "hold"):
        f1, f2 = st.columns(2)
        sort = f1.selectbox("Sort by", ["Returns %", "Returns ₹", "Today %", "Current value", "A–Z"], key="pf_sort")
        flt = f2.selectbox("Show", ["All", "1 Month", "6 Months", "1 Year", "In profit", "In loss", "SELL signal"], key="pf_flt")
        keyf = {"Returns %": lambda r: -r["pnl_pct"], "Returns ₹": lambda r: -r["pnl"], "Today %": lambda r: -(r["day_pct"] if r["day_pct"] == r["day_pct"] else -999),
                "Current value": lambda r: -r["current"], "A–Z": lambda r: r["symbol"]}[sort]
        ok = {"All": lambda r: True, "1 Month": lambda r: r["horizon"] == "1M", "6 Months": lambda r: r["horizon"] == "6M", "1 Year": lambda r: r["horizon"] == "1Y",
              "In profit": lambda r: r["pnl"] > 0, "In loss": lambda r: r["pnl"] < 0, "SELL signal": lambda r: r["signal"] == "SELL"}[flt]
        shown = sorted([r for r in rows if ok(r)], key=keyf)
        if not shown: st.caption("No holdings match this filter."); return
        cols = st.columns(2)
        for i, h in enumerate(shown):
            s = h["symbol"]
            with cols[i % 2], st.container(border=True, key=f"card_hold_{i}"):
                st.markdown(U.holding_html(h), unsafe_allow_html=True)
                b1, b2, b3 = st.columns(3)
                if b1.button("Buy more", key=f"buy_hold_{s}", type="primary", use_container_width=True): show_dialog("buy", s, h["name"], h["ltp"], h["day_pct"], h["stop"], h["target"], 1, h["horizon"] or "1M")
                if b2.button("Sell", key=f"sell_hold_{s}", use_container_width=True): show_dialog("sell", s, h["name"], h["ltp"], h["day_pct"])
                if b3.toggle("Details", key=f"det_{s}"):
                    sn = close_all[s].dropna() if s in close_all.columns else pd.Series(dtype=float)
                    sn = sn[sn.index >= pd.Timestamp(h["since"]).normalize() - pd.Timedelta(days=7)]
                    if len(sn) > 1:
                        st.line_chart(pd.DataFrame({"Value of your shares": sn * h["qty"], "Amount invested": h["invested"]}), color=[U.UP, U.GREY], height=170)
                        st.caption("Value of the shares you hold now, over time, against what you paid.")
                    if h.get("name") or FA.get(s): st.caption(fin_lines(FA.get(s) or {}) or "No results data available.")
                    for line in news(s)[:3]: st.caption("• " + line)

def orders_view():
    pend = acct.get("orders", [])
    with box("🕒 Open orders", "oo", "Limit orders waiting for your price"):
        if not pend: st.caption("No pending limit orders. Choose **Limit** in the Buy or Sell window to wait for your price.")
        for o in list(pend):
            with st.container(border=True, key=f"card_ord_{o['id']}"):
                now_p = px(o["symbol"])
                st.markdown(f'<div class="gw-top"><div><div class="gw-sym">{U.esc(o["symbol"])}</div><div class="gw-sub">Placed {U.esc(o["ts"])} · {o["qty"]} shares · {U.esc(o.get("product", "DELIVERY").title())}</div></div>'
                            f'<div class="gw-right"><div class="gw-px">{U.esc(U.inr(o["limit"]))}</div><div class="gw-sub">limit · now {U.esc(U.inr(now_p))}</div></div></div>'
                            f'<div class="gw-chips">{U.side_chip(o["side"])}{U.chip("Waiting", "hold")}{U.hz_chip(o.get("horizon"))}</div>', unsafe_allow_html=True)
                if st.button("Cancel order", key=f"cancel_{o['id']}"): pend.remove(o); save(); st.rerun()
    with box("📜 Order history", "oh"):
        if not acct["trades"]: st.caption("Nothing traded yet."); return
        t = pd.DataFrame(acct["trades"]).iloc[::-1]
        for c in ("product", "horizon"):
            if c not in t: t[c] = None
        show = pd.DataFrame({"Time": t.ts.str.replace("T", " "), "Stock": t.symbol, "Side": t.side, "Qty": t.qty, "Price": t.price, "Value": t.qty * t.price,
                             "Product": t["product"].fillna("DELIVERY").str.title(), "Horizon": t.horizon.fillna("")})
        st.dataframe(style_df(show, side="Side", fmt={"Price": "₹{:,.2f}", "Value": "₹{:,.2f}"}), hide_index=True, use_container_width=True)

def pnl_view():
    closed = E.ledger(acct["trades"])
    with box("📊 Summary", "ps"):
        st.markdown(U.order_box_html([
            ("Realised P&L (booked)", U.pnl_html(perf["realised"], perf["realised_pct"] if closed else None)),
            ("Unrealised P&L (open)", U.pnl_html(perf["unrealised"], perf["unrealised_pct"] if rows else None)),
            ("Total P&L", U.pnl_html(perf["total"], perf["total_pct"])),
            ("Net worth", U.esc(U.inr(perf["net"]))), ("Started with", U.esc(U.inr(acct["start_cash"]))),
            ("Winning trades", f"{perf['wins']} of {perf['closed']} ({perf['win_rate']:.0f}%)" if perf["closed"] else "–")]), unsafe_allow_html=True)
        st.caption("Realised % is on the cost of the shares you sold. Unrealised % is on what you still hold. Total % is on your starting cash. "
                   "Method: average buy price, charges ignored. Total P&L always equals Net worth minus Started with.")
    if not closed: st.info("No closed trades yet. Realised P&L appears here when you sell."); return
    with box("🏆 By stock", "pb", "Best and worst trades"):
        if perf["best"] and perf["worst"]:
            b, w = perf["best"], perf["worst"]
            st.markdown(f'<div class="gw-sub">Best trade: <b>{U.esc(b["symbol"])}</b> {U.pnl_html(b["pnl"], b["pct"])} · Worst trade: <b>{U.esc(w["symbol"])}</b> {U.pnl_html(w["pnl"], w["pct"])}</div>', unsafe_allow_html=True)
        cl = pd.DataFrame(closed)
        by = cl.groupby("symbol").agg(Trades=("pnl", "size"), Sold=("qty", "sum"), PnL=("pnl", "sum"), cost=("buy", lambda s: (s * cl.loc[s.index, "qty"]).sum())).reset_index()
        by["PnL %"] = by.PnL / by.cost * 100
        st.dataframe(style_df(by.rename(columns={"symbol": "Stock", "PnL": "P&L ₹"})[["Stock", "Trades", "Sold", "P&L ₹", "PnL %"]].sort_values("P&L ₹", ascending=False),
                              pnl=("P&L ₹", "PnL %"), fmt={"P&L ₹": "₹{:,.2f}", "PnL %": "{:+.2f}%"}), hide_index=True, use_container_width=True)
    with box("🧾 Every closed trade", "pc"):
        tr = pd.DataFrame({"Sold on": cl.ts.str.replace("T", " "), "Stock": cl.symbol, "Qty": cl.qty, "Buy price": cl.buy, "Sell price": cl.sell, "P&L ₹": cl.pnl, "P&L %": cl.pct}).iloc[::-1]
        st.dataframe(style_df(tr, pnl=("P&L ₹", "P&L %"), fmt={"Buy price": "₹{:,.2f}", "Sell price": "₹{:,.2f}", "P&L ₹": "₹{:,.2f}", "P&L %": "{:+.2f}%"}), hide_index=True, use_container_width=True)

def growth_view():
    if not acct["trades"]: st.info("Growth appears after your first trade."); return
    hist = E.history(acct["trades"], close_all, acct["start_cash"])
    if len(hist) and now_ist().weekday() < 5: hist.loc[pd.Timestamp(now_ist().date())] = perf["net"]       # today's live point
    with box("📈 Net worth", "gn"):
        rng = st.radio("Range", ["1W", "1M", "3M", "6M", "All"], horizontal=True, index=4, key="gr_rng")
        days = {"1W": 7, "1M": 31, "3M": 92, "6M": 183}.get(rng)
        if days and len(hist): hist = hist[hist.index >= hist.index[-1] - pd.Timedelta(days=days)]
        if len(hist) > 1:
            ch = hist.iloc[-1] - hist.iloc[0]
            st.markdown(f'<div class="gw-card"><div class="gw-k">Net worth · {U.esc(rng)}</div><div class="gw-big">{U.esc(U.inr(hist.iloc[-1], 0))}</div>'
                        f'{U.pnl_html(ch, ch / hist.iloc[0] * 100)}</div>', unsafe_allow_html=True)
            st.line_chart(hist.rename("Net worth"), color=U.UP if ch >= 0 else U.DOWN)
            st.caption("Cash plus holdings at each day's closing price; today's point is live.")
        else: st.caption("The daily chart appears after the first full trading day.")
    ls = st.session_state.get(f"live_series_{user}", [])
    if len(ls) > 1:
        with box("⚡ Live this session", "gl"):
            ser = pd.Series([v for _, v in ls], index=pd.to_datetime([t for t, _ in ls], unit="s", utc=True).tz_convert(IST).tz_localize(None))
            st.line_chart(ser.rename("Net worth"), color=U.UP if ser.iloc[-1] >= ser.iloc[0] else U.DOWN, height=180)
            d = ser.iloc[-1] - ser.iloc[0]
            st.caption(f"Since you opened the app: {U.inr(d, 2, True)} ({U.pct(d / ser.iloc[0] * 100)}). One point per refresh.")

def rec_cards(items, key, banner=None):
    """Cards for a parsed Gemini portfolio review: one per stock, with buttons to act."""
    if banner: st.caption(banner)
    held_ = get_pos()[0]
    for i, a in enumerate(items):
        s = alias.get(a["symbol"]) or a["symbol"]; price = price_of(s); dp = day_pct(s, price) if s in close_all.columns else float("nan")
        tone_ = {"HOLD": "hold", "BUY MORE": "buy", "BUY NEW": "buy", "SELL PART": "sell", "SELL ALL": "sell"}[a["action"]]
        with st.container(border=True, key=f"card_{key}_{i}"):
            st.markdown(f'<div class="gw-top"><div><div class="gw-sym">{U.esc(s)}</div><div class="gw-sub">{U.esc(a["confidence"] and a["confidence"] + " confidence")}</div></div>'
                        f'<div class="gw-right"><div class="gw-px">{U.esc(U.inr(price))}</div></div></div>'
                        f'<div class="gw-chips">{U.chip(a["action"], tone_)}{U.hz_chip(a["horizon"])}'
                        f'{U.chip("You hold " + str(held_[s]["qty"]), "muted") if s in held_ else ""}</div>', unsafe_allow_html=True)
            if a["reason"]: st.write(a["reason"])
            if a["risk"]: st.caption("⚠️ Risk: " + a["risk"])
            if a["stop"] or a["target"]: st.caption(f"New stop-loss {U.inr(a['stop'])} · new target {U.inr(a['target'])}")
            b = st.columns(3); nm = (FA.get(s) or {}).get("name")
            if price != price: st.info("No price found for this symbol, so it can't be traded here."); continue
            if a["action"] in ("SELL PART", "SELL ALL") and s in held_ and b[0].button(f"Sell {a['qty'] if a['action'] == 'SELL PART' and a['qty'] else 'all'}", key=f"sell_{key}_{i}", use_container_width=True):
                show_dialog("sell", s, nm, price, dp, a["qty"] if a["action"] == "SELL PART" else None)
            if a["action"] in ("BUY MORE", "BUY NEW") and b[0].button(f"Buy {a['qty'] or ''}".strip(), key=f"buy_{key}_{i}", type="primary", use_container_width=True):
                show_dialog("buy", s, nm, price, dp, a["stop"] if a["stop"] and a["stop"] < price else None, a["target"] if a["target"] and a["target"] > price else None,
                           a["qty"] or 1, a["horizon"] or "1M")
            if s in held_ and ((a["stop"] and a["stop"] < price) or (a["target"] and a["target"] > price)) and b[1].button("Apply stop/target", key=f"lv_{key}_{i}", use_container_width=True):
                lv = acct.setdefault("levels", {}).setdefault(s, {})
                if a["stop"] and a["stop"] < price: lv["stop"] = a["stop"]
                if a["target"] and a["target"] > price: lv["target"] = a["target"]
                save(); flash(f"Updated stop-loss / target for {s}"); st.rerun()

def review_view():
    with box("① Instant check (no AI)", "r1", "Rules of thumb on each holding"):
        if not rows: st.caption("Buy something first. Your holdings will be checked here.")
        for r in sorted(rows, key=lambda r: ["SELL", "HOLD", "BUY"].index(r["signal"])):
            st.markdown(f'<div class="gw-card" style="border:1px solid #8a8fa340;padding:10px 14px;margin-bottom:6px"><div class="gw-top"><div><span class="gw-sym" style="font-size:1rem">{U.esc(r["symbol"])}</span> '
                        f'{U.action_chip(r["signal"])}{U.hz_chip(r["horizon"])}<div class="gw-sub">{U.esc(r["reason"])}</div></div>'
                        f'<div class="gw-right">{U.pnl_html(r["pnl"], r["pnl_pct"])}<div class="gw-sub">{r["weight"]:.0f}% of holdings</div></div></div></div>', unsafe_allow_html=True)
        big = [r for r in rows if r["weight"] > 35 and len(rows) > 1]
        if big: st.warning("Concentration: " + ", ".join(f"{r['symbol']} is {r['weight']:.0f}%" for r in big) + " of your holdings. Consider spreading the risk.")
        st.caption("Rules of thumb from trend, stop-loss and target. Open Portfolio > Holdings to buy or sell.")
    with box("② Ask Gemini: copy & paste (no key)", "r2", "Only your holdings are included"):
        st.caption("The prompt contains only your holdings. Gemini is told not to mention any other stock, market outlook or new ideas.")
        prompt = E.build_review_prompt(rows, perf, dt.date.today())
        copy_open_gemini(prompt)
        with st.expander("Show prompt text"): st.code(prompt, language=None)
        reply = st.text_area("Paste Gemini's reply here", height=140, key="rv_paste", placeholder="Paste the JSON reply from Gemini…")
        if st.button("✅ Show actions", type="primary", use_container_width=True, key="rv_show"):
            items = E.parse_review(reply)
            if items: acct["review"] = dict(ts=now_ist().strftime("%d %b %Y %H:%M"), items=items); save(); st.rerun()
            elif items is None:
                st.error("Couldn't find the JSON list in that reply. Ask Gemini: 'Reply again with only the JSON array', then paste it.")
                if reply.strip(): st.markdown("**Gemini's raw reply:**"); st.write(reply)
            else: st.warning("The reply had no usable actions.")
        rv = acct.get("review")
        if rv:
            mine = [a for a in rv["items"] if (alias.get(a["symbol"]) or a["symbol"]) in pos or a["symbol"] in pos]
            if len(mine) < len(rv["items"]): st.caption(f"{len(rv['items']) - len(mine)} suggestion(s) about stocks you don't hold were hidden.")
            rec_cards(mine, "rv", f"Gemini review pasted {rv['ts']} · AI opinion, can be wrong, not SEBI-registered advice")
            if st.button("Clear review", key="rv_clear"): acct.pop("review", None); save(); st.rerun()
    with box("③ Ask Gemini: API key", "r3", "One tap if you added a key in ⚙️ Settings"):
        if st.button("⚡ Review my portfolio now", use_container_width=True, key="rv_api"):
            if not gkey: st.error("Add your Gemini API key in ⚙️ Settings first (free at aistudio.google.com).")
            else:
                with st.spinner("Gemini is reviewing your portfolio…"):
                    try:
                        ans = G.ask(gkey, gmodel.strip(), [dict(role="user", text=prompt)], "", gsearch, system=E.REVIEW_SYSTEM)
                        items = E.parse_review(ans)
                        if items: acct["review"] = dict(ts=now_ist().strftime("%d %b %Y %H:%M"), items=items); save(); st.rerun()
                        else: st.session_state["rv_text"] = ans
                    except Exception as e: st.error(str(e))
        if st.session_state.get("rv_text"): st.markdown(st.session_state["rv_text"])

def account_view():
    with box("💾 Backup & restore", "a1"):
        st.download_button("⬇️ Export account (backup)", json.dumps(acct), f"{user}_demo_account.json", use_container_width=True)
        up = st.file_uploader("Import a backup", type="json")
        if up and st.button("Restore backup"): acct.clear(); acct.update(json.load(up)); save(); st.rerun()
    with box("⚠️ Reset account", "a2", "Starts again with fresh virtual cash"):
        new_cash = st.number_input("Reset with starting cash (₹)", 10000, 100000000, int(acct["start_cash"]), step=50000)
        if st.button("⚠️ Reset account"):
            keep = {k: acct[k] for k in ("theme", "blur", "fs", "hc", "anim", "settings") if k in acct}
            acct.clear(); acct.update(start_cash=float(new_cash), trades=[], **keep); save(); st.rerun()
    st.caption("Demo only: virtual money, no brokerage, taxes or slippage. Market orders fill at the latest available price (can be a few minutes delayed). "
               "Limit orders and stop-loss / target sells are checked whenever the app is open. Intraday positions are squared off at 3:20 PM. "
               "On free cloud hosting, saved accounts may reset when the app restarts, so export a backup.")

def portfolio_section():
    """The whole Portfolio area. Reruns by itself every refresh interval (only this part of the page), so nothing else blinks or waits."""
    global PF_STAMP
    pf_live, PF_STAMP = pf_prices(tuple(s for s in get_pos()[0] if s in close_all.columns))
    live.update(pf_live)
    msgs = run_orders()
    if msgs:
        st.session_state.msgs = msgs; st.rerun(scope="app")          # a stop-loss / target / limit order fired: refresh everything
    refresh_state()
    p_h, p_o, p_p, p_g, p_r, p_a = st.tabs(["Holdings", "Orders", "P&L", "Growth", "Gemini", "Account"])
    with p_h: holdings_view()
    with p_o: orders_view()
    with p_p: pnl_view()
    with p_g: growth_view()
    with p_r: review_view()
    with p_a: account_view()

with t_pf:
    st.fragment(run_every=(pf_every if pf_auto else None))(portfolio_section)()

# ======================================================================
# Gemini AI (ideas)
# ======================================================================
with t_ai:
    ta, tb = st.tabs(["📋 Ideas: copy & paste (no key)", "⚡ Chat (API key)"])
    with ta:
        with box("① Build the prompt", "gp1", "Copy it, open Gemini, paste it there"):
            st.write("**1.** Build a prompt  **2.** Copy it and open Gemini  **3.** Paste Gemini's reply below to get recommendations here.")
            st.caption("The prompt tells Gemini to use broker and institutional views, global news and technology shifts, government policy, and company results, and lets it pick **any** NSE/BSE company. "
                       "To review your own holdings use **Portfolio > Gemini review**.")
            kind = st.radio("What do you want to ask?", E.IDEA_KINDS)
            own = st.text_input("Your question") if kind == E.PROMPT_KINDS[3] else ""
            notes = st.text_area("Optional: your own notes on news, policy or events to include", acct.get("notes", ""), height=90,
                                 placeholder="e.g. Budget raised railway capex; new PLI for electronics; crude fell 8% this week")
            if notes != acct.get("notes", ""): acct["notes"] = notes; save()
            prompt = E.build_prompt(kind, own, build_context(), dt.date.today())
            copy_open_gemini(prompt)
            with st.expander("Show prompt text"): st.code(prompt, language=None)
        with box("② Paste Gemini's reply", "gp2", "Gemini's answer becomes buy cards below"):
            reply = st.text_area("Paste Gemini's reply here", height=160, key="greply", placeholder="Paste the JSON reply from Gemini…")
            if st.button("✅ Show recommendations", type="primary", use_container_width=True):
                items = E.parse_recs(reply)
                if items:
                    acct["recs"] = dict(ts=now_ist().strftime("%d %b %Y %H:%M"), items=items); save(); st.rerun()
                elif items is None:
                    st.error("Couldn't find the JSON list in that reply. Ask Gemini: 'Reply again with only the JSON array', then paste it.")
                    if reply.strip(): st.markdown("**Gemini's raw reply:**"); st.write(reply)
                else:
                    st.warning("The reply had no usable recommendations.")
        recs = acct.get("recs")
        if recs:
            st.subheader("Gemini's recommendations")
            st.caption(f"Pasted {recs['ts']} · AI opinion, can be wrong, not SEBI-registered advice")
            cols = st.columns(2)
            for i, r in enumerate(recs["items"]):
                sym = r["symbol"]; al = acct.setdefault("alias", {}); use = al.get(sym) or sym
                if use not in close_all.columns and sym not in al:
                    hits = search_stocks(r.get("company") or sym); al[sym] = hits[0]["symbol"] if hits else ""; save()
                    if al[sym]: st.rerun()
                last = px(use); dp = day_pct(use, last)
                act = str(r["action"]).lower(); sig = "SELL" if "avoid" in act or "sell" in act else "HOLD" if "wait" in act or "hold" in act else "BUY"
                with cols[i % 2], st.container(border=True, key=f"card_rec_{i}"):
                    tags = U.hz_chip(E.horizon_of(r["horizon"])) + U.action_chip(sig) + U.chips([(f"{r['confidence']} confidence", "info")] if r["confidence"] else [])
                    tags += U.chips([(f"{r['liquidity']} liquidity", "muted")] if r.get("liquidity") else [])
                    st.markdown(U.stock_head_html(use, r.get("company"), last, dp, tags), unsafe_allow_html=True)
                    if last == last:
                        st.markdown(U.levels_html(last, r["entry"], r["stop"], r["target"]), unsafe_allow_html=True)
                    else: st.caption(f"Entry {U.inr(r['entry'])} · Stop-loss {U.inr(r['stop'])} · Target {U.inr(r['target'])}")
                    if r["reason"]: st.write(r["reason"])
                    for lab, k in (("🏦 Brokers/institutions", "broker_view"), ("🌍 News & policy", "news_policy"), ("📊 Financials", "financials")):
                        if r.get(k): st.caption(f"{lab}: {r[k]}")
                    if r["risk"]: st.caption(f"⚠️ Risk: {r['risk']}")
                    if last == last:
                        if r["entry"] and abs(r["entry"] / last - 1) > 0.10:
                            st.warning(f"Gemini's entry differs from the live price by {abs(r['entry']/last-1)*100:.0f}%. It may have used old prices.")
                        if r["stop"] and r["stop"] >= last: st.warning("Its stop-loss is above the live price, so it is not usable as given.")
                        if r["target"] and r["target"] <= last: st.warning("Its target is below the live price.")
                        stop_ok = r["stop"] if r["stop"] and r["stop"] < last else None
                        tgt_ok = r["target"] if r["target"] and r["target"] > last else None
                        qn = max(E.qty_for(last, stop_ok, capital, risk), 1)
                        c1, c2 = st.columns(2)
                        if c1.button("Buy", key=f"gr_{i}_{use}", type="primary", use_container_width=True):
                            show_dialog("buy", use, r.get("company"), last, dp, stop_ok, tgt_ok, qn, E.horizon_of(r["horizon"]) or "1M")
                        watch_button(c2, use, f"rec_{i}")
                    else:
                        st.info("No price found for this symbol on NSE/BSE. Check it in Explore > Search & watchlist (try the company name or BSE code).")
            if st.button("Clear recommendations"): acct.pop("recs", None); save(); st.rerun()
    with tb:
        with box("💬 Ask Gemini inside the app", "chat"):
            st.write("Ask Gemini directly inside the app. It also receives this app's rankings, analyst data and your demo holdings as context, and may suggest any company.")
            chat = st.session_state.setdefault("gchat", [])
            qs = {"Best 1‑month ideas?": "Which stocks (any NSE/BSE company) look best for the next month? Use broker/institutional views, global news, government policy and latest results. Give entry, stop-loss, target and risks.",
                  "Best 6‑month ideas?": "Which stocks (any NSE/BSE company) look best for the next 6 months? Use broker/institutional views, global news, government policy and latest results. Give entry, stop-loss, target and risks.",
                  "Best 1‑year ideas?": "Which stocks (any NSE/BSE company) look best for the next 12 months? Use broker/institutional views, global news and technology shifts, government policy and latest results.",
                  "Review my portfolio": "Review my demo holdings. What are the concentration and risk issues, and what would you change?"}
            cols_ = st.columns(len(qs)); quick = None
            for c_, (lab, txt) in zip(cols_, qs.items()):
                if c_.button(lab, use_container_width=True): quick = txt
            for h in chat: st.chat_message("user" if h["role"] == "user" else "assistant").write(h["text"])
            q = st.chat_input("Ask about any stock, strategy or your portfolio…") or quick
            if q:
                if not gkey:
                    st.error("Add your Gemini API key in ⚙️ Settings first (free at aistudio.google.com).")
                else:
                    chat.append(dict(role="user", text=q)); st.chat_message("user").write(q)
                    with st.chat_message("assistant"), st.spinner("Gemini is thinking…"):
                        try:
                            ans = G.ask(gkey, gmodel.strip(), chat, build_context(), gsearch, system=E.SYSTEM_RULES)
                            chat.append(dict(role="model", text=ans)); st.write(ans)
                        except Exception as e:
                            chat.pop(); st.error(str(e))
            if chat and st.button("Clear chat"): chat.clear(); st.rerun()
            st.caption("Gemini's answers are AI-generated opinions, can be wrong, and are not SEBI-registered advice. "
                       "Your question, the rankings and your demo holdings are sent to Google when you ask. Your API key may be billed by Google if you exceed the free tier.")

# ======================================================================
# Tools
# ======================================================================
with t_tools:
    k1, k2, k3 = st.tabs(["🌍 Market & global context", "📊 Backtest", "ℹ️ How it works"])
    with k1:
        with box("🌍 Market & global context", "mkt"):
            if snap:
                cols = st.columns(3)
                for i, (k, (v, d)) in enumerate(snap.items()):
                    cols[i % 3].markdown(f'<div class="gw-card" style="border:1px solid #8a8fa340"><div class="gw-k">{U.esc(k)}</div><div class="gw-px">{U.esc(f"{v:,.2f}")}</div>{U.pct_html(d, 1)}</div>', unsafe_allow_html=True)
            else: st.info("Market data is not available right now. Try again in a minute.")
            st.caption(f"Data as of {close.index[-1]:%d %b %Y} · {len(m)} stocks scanned in the idea lists" + (f" · {len(base) - len(close.columns)} symbols had no data (renamed/delisted?)" if len(base) > len(close.columns) else ""))
    with k2:
        with box("📊 Backtest", "bt"):
            st.write("How the 1‑month strategy (top 5 by momentum, rebalanced every ~21 trading days) would have done on this stock list over the past ~2 years:")
            bt = E.backtest(close)
            if len(bt):
                c1, c2, c3 = st.columns(3)
                c1.metric("Avg monthly return", f"{bt.strategy.mean()*100:.1f}%")
                c2.metric("Months with ≥10% gain", f"{(bt.strategy>=.10).mean()*100:.0f}%")
                c3.metric("Months with a loss", f"{(bt.strategy<0).mean()*100:.0f}%")
                st.line_chart(((1 + bt.set_index("date")[["strategy", "universe"]]).cumprod() - 1) * 100)
                st.caption("Uses today's stock list (survivorship bias), ignores brokerage, taxes and slippage. Real results will be lower.")
    with k3:
        with box("ℹ️ How it works", "how"):
            st.markdown("""
- **Explore** has 1 Month, 6 Months and 1 Year idea lists, a scan of every NSE-listed company, and a search for any company.
- Tags: **1M / 6M / 1Y** is the horizon. **BUY / HOLD / SELL** comes from the stop-loss, target, trend and momentum. Other tags show risk, momentum and analyst views.
- **Buy** opens an order window: Delivery or Intraday, Market or Limit, quantity, horizon, optional stop-loss and target.
- **Portfolio** shows cards with your buy price next to the current price, returns in ₹ and %, and today's move. Prices refresh by themselves; the countdown at the top shows the time left.
- **P&L report** lists every closed trade. Realised + unrealised always equals net worth minus starting cash.
- **Portfolio > Gemini review** checks your holdings only: an instant rule-based check and a separate Gemini prompt that covers nothing but your holdings. **Refresh portfolio** (and its own timer) updates only your holdings.
- Everything is practice money. Nobody can guarantee returns. Not SEBI-registered investment advice.""")
