import datetime as dt, json, os, re
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, streamlit as st, yfinance as yf
import streamlit.components.v1 as components
import engine as E
import gemini_client as G

st.set_page_config(page_title="India Stock Advisor", page_icon="📈", layout="centered")
st.title("📈 India Stock Advisor")
st.warning("Auto-updating ideas, **not** guarantees. No tool can reliably deliver +10–20% in a month or "
           "+100% in a year. Demo trading uses virtual money only. Not investment advice; "
           "consult a SEBI-registered advisor.")

with st.sidebar:
    user = re.sub(r"[^a-z0-9_-]", "", st.text_input("Demo account name", "me").lower()) or "me"
    capital = st.number_input("Capital for sizing ideas (₹)", 10000, 100000000, 100000, step=10000)
    risk = st.slider("Max loss per trade (% of capital)", 0.5, 3.0, 1.0, 0.5)
    topn = st.slider("How many ideas", 3, 15, 8)
    uni = st.selectbox("Stock universe", list(E.UNIVERSES), help="Any other company can be added in the 'Find any stock' tab.")
    extra = st.text_input("Add NSE symbols to the scan (comma-separated)", "")
    research_on = st.checkbox("Use analyst & results data (slower)", True)
    auto_exec = st.checkbox("Auto-sell at stop-loss / target (demo)", True)
    st.divider(); st.caption("🤖 Gemini (optional API)")
    try: _k = st.secrets.get("GEMINI_API_KEY", "")
    except Exception: _k = ""
    gkey = st.text_input("Gemini API key", value=_k or os.environ.get("GEMINI_API_KEY", ""), type="password",
                         help="Free key from aistudio.google.com. Stored only for this session.")
    gmodel = st.text_input("Gemini model", "gemini-flash-latest", help="Check ai.google.dev for current model names.")
    gsearch = st.checkbox("Let Gemini search the web (Google Search)", True)

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

# ---------- appearance (saved per demo account) ----------
_names = list(E.THEMES)
with st.sidebar:
    st.divider(); st.caption("🎨 Appearance")
    th = st.selectbox("Theme", _names, index=_names.index(acct["theme"]) if acct.get("theme") in _names else _names.index(E.DEFAULT_THEME))
    blur = st.slider("Glass blur", 0, 30, int(acct.get("blur", 16)), help="Lower is faster and saves battery. 0 = no blur.")
    fs = st.slider("Text size", 14, 20, int(acct.get("fs", 16)))
    hc = st.checkbox("High contrast (clearest text)", bool(acct.get("hc", False)))
    anim = st.checkbox("Animated background", bool(acct.get("anim", True)))
_cur = dict(theme=th, blur=blur, fs=fs, hc=hc, anim=anim)
if any(acct.get(k) != v for k, v in _cur.items()): acct.update(_cur); save()
st.markdown(E.theme_css(th, blur, 22, anim, fs, hc), unsafe_allow_html=True)

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

@st.cache_data(ttl=60, show_spinner=False)
def live_prices(symbols):
    try:
        d = yf.download([s + ".NS" for s in symbols], period="1d", interval="5m", progress=False, auto_adjust=True)["Close"]
        if isinstance(d, pd.Series): d = d.to_frame(symbols[0] + ".NS")
        d = d.ffill().iloc[-1].dropna(); d.index = [c.replace(".NS", "") for c in d.index]
        return d.to_dict()
    except Exception:
        return {}

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

base = list(dict.fromkeys(E.UNIVERSES[uni] + [s.strip().upper() for s in extra.split(",") if s.strip()]))
try:
    close = load(tuple(base))
except Exception as e:
    st.error(f"Could not fetch data: {e}"); st.stop()
held = list(E.positions(acct["trades"])[0])
alias = acct.get("alias", {})
rec_syms = [alias.get(r["symbol"]) or r["symbol"] for r in acct.get("recs", {}).get("items", [])]
extras = [s for s in dict.fromkeys(acct.get("watch", []) + held + rec_syms) if s not in close.columns]
xdf = load_extra(tuple(extras)) if extras else pd.DataFrame()
close_all = pd.concat([close, xdf], axis=1) if len(xdf.columns) else close
live = live_prices(tuple(close_all.columns))
def px(s):
    if s in live: return float(live[s])
    return float(close_all[s].dropna().iloc[-1]) if s in close_all.columns else float("nan")

def trade(sym, side, qty, price, stop=None, target=None):
    pos, _ = E.positions(acct["trades"]); cash = E.cash_balance(acct["start_cash"], acct["trades"])
    if qty < 1: return "Quantity must be at least 1."
    if not price == price: return "No price available for this symbol."
    if side == "BUY" and qty * price > cash: return f"Not enough virtual cash (₹{cash:,.0f} available)."
    if side == "SELL" and pos.get(sym, {}).get("qty", 0) < qty: return "You don't hold that many shares."
    acct["trades"].append(dict(ts=dt.datetime.now().isoformat(timespec="seconds"), symbol=sym, side=side,
                               qty=int(qty), price=round(float(price), 2), stop=stop, target=target))
    save(); return None

if auto_exec:   # bracket-order style stop-loss / target
    msgs = []
    for s, p in E.positions(acct["trades"])[0].items():
        q, last = p["qty"], px(s)
        if last != last: continue
        if p["stop"] and last <= p["stop"] and not trade(s, "SELL", q, last): msgs.append(f"🛑 {s}: stop-loss hit, sold {q} @ ₹{last:,.2f}")
        elif p["target"] and last >= p["target"] and not trade(s, "SELL", q, last): msgs.append(f"🎯 {s}: target hit, sold {q} @ ₹{last:,.2f}")
    if msgs:
        for m_ in msgs: st.toast(m_)
        st.session_state.msgs = msgs; st.rerun()
for m_ in st.session_state.pop("msgs", []): st.info(m_)

# ---------- scoring: technicals + broker/analyst + results ----------
m0 = E.score(E.metrics(close))
cands = tuple(dict.fromkeys(list(m0.sort_values("short", ascending=False).head(20).index) + list(m0.sort_values("long", ascending=False).head(20).index)))
F = fund_many(cands) if research_on else {}
m = E.blend(m0, F)
miss = len(base) - len(close.columns)
st.caption(f"Data as of {close.index[-1]:%d %b %Y} · {len(m)} stocks scanned" + (f" · {miss} symbols had no data (renamed/delisted?)" if miss > 0 else "")
           + " · any other company: use the **Find any stock** tab")

snap = market_snapshot()
if snap:
    with st.expander("🌍 Market & global context"):
        cols = st.columns(3)
        for i, (k, (v, d)) in enumerate(snap.items()): cols[i % 3].metric(k, f"{v:,.2f}", f"{d:+.1f}%")

pct = lambda x: "n/a" if x is None or pd.isna(x) else f"{x*100:+.0f}%"
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
    for col, name in (("short2", "1-month shortlist"), ("long2", "1-year shortlist")):
        rows = []
        for s, r in m.dropna(subset=[col]).sort_values(col, ascending=False).head(8).iterrows():
            f = F.get(s) or {}
            x = f"{s}: price {r.price:.0f}, 1M {n(r.r1m*100)}%, 3M {n(r.r3m*100)}%, RSI {n(r.rsi)}, volatility {n(r.vol*100)}%"
            if f: x += f"; analysts {f.get('rec')} (mean target {n(f.get('target'))}); {fin_lines(f)}"
            rows.append(x)
        L.append(f"{name} from the app's screen:\n" + "\n".join(rows))
    pos_, _ = E.positions(acct["trades"])
    L.append("Demo holdings: " + (", ".join(f"{k} x{v['qty']} avg {v['cost']/v['qty']:.0f}" for k, v in pos_.items()) or "none"))
    if st.session_state.get("scan_ctx"): L.append(st.session_state["scan_ctx"])
    if acct.get("notes"): L.append("My own notes on news / policy / events:\n" + acct["notes"])
    return "\n".join(L)

def show(kind, col, months, gain):
    top = m.dropna(subset=[col + "2"]).sort_values(col + "2", ascending=False).head(topn)
    for n_, (sym, r) in enumerate(top.iterrows()):
        f = F.get(sym) or {}
        r = r.copy(); price = px(sym); r["price"] = price if price == price else r.price; price = r["price"]
        p = E.plan(r, capital, risk, kind, f.get("target"))
        with st.container(border=True, key=f"card_{kind}_{n_}"):
            a, b = st.columns([3, 1]); a.subheader(sym); b.metric("Score", f"{r[col + '2']:.0f}")
            if f.get("name"): a.caption(f"{f['name']}" + (f" · {f['sector']}" if f.get("sector") else ""))
            st.write(f"**{p['action']}** · Entry ₹{p['entry']:,.0f} · Stop-loss ₹{p['stop']:,.0f} · Target ₹{p['target']:,.0f}")
            st.write(f"Suggested qty **{p['qty']}** (≈₹{p['invest']:,.0f}); worst case loss at stop ≈ ₹{p['max_loss']:,.0f}")
            st.caption(f"1M {pct(r.r1m)} · 3M {pct(r.r3m)} · 12M {pct(r.r12m)} · RSI {r.rsi:.0f} · volatility {r.vol*100:.0f}%")
            if fund_lines(f, price): st.write(fund_lines(f, price))
            st.caption(f"Model odds of ≥{gain}% in {months} month(s): **{E.p_hit(gain, r.vol, months)*100:.0f}%**")
            if st.checkbox("🔍 Financials & latest news", key=f"rs_{kind}_{n_}"):
                st.write(fin_lines(f) or "No results data available from Yahoo for this stock.")
                for h in news(sym) or ["No recent headlines found."]: st.caption("• " + h)
            if p["qty"] >= 1 and st.button(f"🧪 Demo buy {p['qty']} @ ₹{price:,.2f} (with stop & target)", key=f"b_{kind}_{n_}"):
                err = trade(sym, "BUY", p["qty"], price, round(p["stop"], 2), round(p["target"], 2))
                st.error(err) if err else (st.success("Demo order placed. See the Demo portfolio tab."), st.rerun())

def analyze(sym):
    df = load_extra((sym,))
    if df.empty or sym not in df.columns:
        st.error("No price data found for this symbol on NSE/BSE. Check the symbol or try the BSE code."); return
    mm = E.metrics(df, min_len=3)
    if sym not in mm.index: st.error("Not enough price history yet."); return
    r = mm.loc[sym].copy(); ndays = int(df[sym].notna().sum())
    lp = live_prices((sym,)).get(sym); r["price"] = float(lp) if lp else r.price
    f = fund_many((sym,)).get(sym) or {}
    with st.container(border=True, key=f"card_find_{sym}"):
        st.subheader(f"{sym}" + (f" · {f['name']}" if f.get("name") else ""))
        st.metric("Price", f"₹{r.price:,.2f}")
        if ndays < 130: st.warning(f"🆕 New listing: only {ndays} trading days of history, so momentum numbers are rough.")
        st.caption(f"1M {pct(r.r1m)} · 3M {pct(r.r3m)} · 12M {pct(r.r12m)} · RSI {'n/a' if r.rsi != r.rsi else f'{r.rsi:.0f}'} · volatility {'n/a' if r.vol != r.vol else f'{r.vol*100:.0f}%'}")
        if fund_lines(f, r.price): st.write(fund_lines(f, r.price))
        if fin_lines(f): st.write(fin_lines(f))
        vol = r.vol if r.vol == r.vol else 0.4
        for kind, label in (("short", "1‑month plan"), ("long", "1‑year plan")):
            p = E.plan(r, capital, risk, kind, f.get("target"))
            st.write(f"**{label}:** {p['action']} · Entry ₹{p['entry']:,.0f} · Stop ₹{p['stop']:,.0f} · Target ₹{p['target']:,.0f} · qty {p['qty']}")
        st.caption(f"Model odds of ≥10% in 1 month: {E.p_hit(10, vol, 1)*100:.0f}% · ≥100% in 1 year: {E.p_hit(100, vol, 12)*100:.0f}%")
        for h in news(sym)[:4]: st.caption("• " + h)
        pl = E.plan(r, capital, risk, "short", None)
        q = st.number_input("Quantity", 1, 10000000, max(pl["qty"], 1), key=f"fq_{sym}")
        c1, c2 = st.columns(2)
        if c1.button("🧪 Demo buy", key=f"fb_{sym}"):
            err = trade(sym, "BUY", q, r.price, round(pl["stop"], 2), round(pl["target"], 2))
            st.error(err) if err else (st.success("Demo order placed."), st.rerun())
        w = acct.setdefault("watch", [])
        if sym in w:
            if c2.button("➖ Remove from watchlist", key=f"fw_{sym}"): w.remove(sym); save(); st.rerun()
        elif c2.button("➕ Add to watchlist", key=f"fw_{sym}"): w.append(sym); save(); st.rerun()

SCOPES = {"Nifty 500 (~500 stocks, fastest)": ["ind_nifty500list.csv"],
          "Nifty 500 + Microcap 250 (~750)": ["ind_nifty500list.csv", "ind_niftymicrocap250_list.csv"],
          "Every NSE-listed stock (~2,000+, slowest)": ["EQUITY_L"]}
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
    start = (dt.date.today() - dt.timedelta(days=400)).isoformat(); n, step, parts = len(symbols), 100, []
    for i in range(0, n, step):
        prog.progress(min((i + step) / n, 1.0), text=f"Scanning {min(i + step, n)} of {n} stocks…")
        try:
            df = yf.download([x + ".NS" for x in symbols[i:i + step]], start=start, auto_adjust=True, progress=False, threads=True)
            if df is None or df.empty: continue
            c, v = df["Close"], df["Volume"]
            if isinstance(c, pd.Series): continue
            c.columns = [x.replace(".NS", "") for x in c.columns]; v.columns = [x.replace(".NS", "") for x in v.columns]
            c.index = pd.to_datetime(c.index).tz_localize(None); v.index = c.index
            parts.append(E.metrics(c.dropna(axis=1, how="all"), min_len=60, volume=v))
        except Exception: continue
    return pd.concat(parts) if parts else pd.DataFrame()

tm, t1, t2, tf, t3, t5, t4 = st.tabs(["🚀 Market scan", "1‑Month ideas", "1‑Year ideas", "🔎 Find any stock", "💼 Demo portfolio", "🤖 Ask Gemini", "Backtest"])
with tm:
    st.write("Scans the **whole market**, not a fixed list, for stocks with the highest realistic return potential that are still **feasible to trade** (liquidity and price filters).")
    c1, c2 = st.columns(2)
    scope = c1.selectbox("Scan scope", list(SCOPES)); profile = c2.selectbox("Risk appetite", list(E.PROFILES))
    st.caption("Higher return potential means higher risk. 'Aggressive' includes small and micro caps that trade thinly. Nobody can guarantee returns.")
    path_s = scan_path(scope)
    if st.button("🚀 Run market-wide scan", type="primary", use_container_width=True):
        syms = nse_symbols(scope)
        if not syms: st.warning("Couldn't download NSE's stock list, so the built-in broad list is used."); syms = E.BROAD
        prog = st.progress(0.0, text="Starting…")
        res = run_scan(syms, prog); prog.empty()
        if res.empty: st.error("No price data came back (Yahoo may be busy). Try again in a few minutes.")
        else: res.to_csv(path_s); st.rerun()
    if os.path.exists(path_s):
        sdf = pd.read_csv(path_s, index_col=0)
        pot = E.potential(sdf, profile).dropna(subset=["pot"]).sort_values("pot", ascending=False)
        st.caption(f"Scan from {dt.datetime.fromtimestamp(os.path.getmtime(path_s)):%d %b %Y %H:%M} · {len(sdf)} stocks scanned · {len(pot)} pass the '{profile}' liquidity filter. Re-run for fresh prices.")
        top = pot.head(30)
        F2 = fund_many(tuple(top.index)) if research_on and len(top) else {}
        if len(top):
            bl = E.blend(top.assign(short=top.pot, long=top.pot), F2)
            top = top.assign(pot2=np.where(bl["fund"].notna(), 0.7 * top.pot + 0.3 * bl["fund"], top.pot)).sort_values("pot2", ascending=False).head(topn)
        n_ = lambda x, f="{:.0f}": "n/a" if x is None or x != x else f.format(x)
        st.session_state["scan_ctx"] = (f"Market-wide scan top picks ({profile}, from {len(sdf)} NSE stocks): " + "; ".join(
            f"{k}: price {r.price:.0f}, 1M {n_(r.r1m*100)}%, 3M {n_(r.r3m*100)}%, volatility {n_(r.vol*100)}%, avg traded value Rs {r.avg_val/1e7:.1f} cr"
            for k, r in top.head(10).iterrows())) if len(top) else ""
        for i, (sym, r) in enumerate(top.iterrows()):
            f = F2.get(sym) or {}; price = float(r.price); pl = E.plan(r, capital, risk, "short")
            risk_l = "Very high risk" if r.vol >= 0.7 else "High risk" if r.vol >= 0.45 else "Medium risk"
            with st.container(border=True, key=f"card_scan_{i}"):
                a, b2 = st.columns([3, 1]); a.subheader(sym); b2.metric("Potential", f"{r.pot2:.0f}")
                a.caption(" · ".join(x for x in (f.get("name"), f.get("sector"), risk_l) if x))
                st.write(f"**{pl['action']}** · Entry ₹{pl['entry']:,.2f} · Stop-loss ₹{pl['stop']:,.2f} · Target ₹{pl['target']:,.2f} · qty {pl['qty']}")
                st.caption(f"1M {pct(r.r1m)} · 3M {pct(r.r3m)} · 6M {pct(r.r6m)} · {(price/r.hi52-1)*100:.0f}% from 52w high · volume surge x{n_(r.vsurge, '{:.1f}')} · volatility {r.vol*100:.0f}%")
                st.caption(f"Avg daily traded value ₹{r.avg_val/1e7:.1f} cr" + (" · thinly traded, use limit orders and small size" if r.avg_val < 5e7 else ""))
                if fund_lines(f, price): st.write(fund_lines(f, price))
                st.caption(f"Model odds of ≥+20% in 1 month: **{E.p_hit(20, r.vol, 1)*100:.0f}%** · ≥+100% in 1 year: **{E.p_hit(100, r.vol, 12)*100:.0f}%**")
                if st.checkbox("🔍 Financials & latest news", key=f"rs_scan_{i}"):
                    st.write(fin_lines(f) or "No results data available from Yahoo for this stock.")
                    for h in news(sym) or ["No recent headlines found."]: st.caption("• " + h)
                if pl["qty"] >= 1 and st.button(f"🧪 Demo buy {pl['qty']} @ ₹{price:,.2f}", key=f"b_scan_{i}"):
                    err = trade(sym, "BUY", pl["qty"], price, round(pl["stop"], 2), round(pl["target"], 2))
                    st.error(err) if err else (st.success("Demo order placed. See the Demo portfolio tab."), st.rerun())
    else:
        st.info("No scan yet. Tap **Run market-wide scan**. The first run can take a few minutes, so keep the app open; later opens are instant.")

with t1: show("short", "short", 1, 10)
with t2: show("long", "long", 12, 100)

with tf:
    st.write("Search **any** NSE/BSE company, including new listings such as Jio Platforms (NSE: JPL, BSE: 545004).")
    q = st.text_input("Company name, NSE symbol or BSE code", placeholder="e.g. Jio Platforms, JPL, Reliance, 545004")
    if q.strip():
        hits = search_stocks(q.strip())
        opts = {f"{h['name']} — {h['symbol']} ({'NSE' if h['suffix'] == '.NS' else 'BSE'})": h["symbol"] for h in hits}
        manual = re.sub(r"[^A-Za-z0-9&-]", "", q).upper()
        if manual and manual not in opts.values(): opts[f"Try symbol directly: {manual}"] = manual
        pick = st.selectbox("Matches", list(opts))
        if st.button("Analyze", type="primary"): st.session_state["find"] = opts[pick]
    if st.session_state.get("find"): analyze(st.session_state["find"])
    if acct.get("watch"):
        st.markdown("#### My watchlist")
        for s in acct["watch"]:
            c1, c2 = st.columns([3, 1]); c1.write(f"**{s}**"); c2.write(f"₹{px(s):,.2f}")
            if c1.button(f"Analyze {s}", key=f"wa_{s}"): st.session_state["find"] = s; st.rerun()

with t3:
    pos, realised = E.positions(acct["trades"]); cash = E.cash_balance(acct["start_cash"], acct["trades"])
    rows = []
    for s, p in pos.items():
        last = px(s); last = last if last == last else p["cost"] / p["qty"]; inv = p["cost"]; cur = p["qty"] * last
        rows.append({"Stock": s, "Qty": p["qty"], "Avg price": inv / p["qty"], "LTP": last, "Invested": inv,
                     "Current": cur, "P&L ₹": cur - inv, "P&L %": (cur / inv - 1) * 100, "Stop": p["stop"], "Target": p["target"]})
    H = pd.DataFrame(rows)
    inv_t = H["Invested"].sum() if len(H) else 0.0; cur_t = H["Current"].sum() if len(H) else 0.0
    net = cash + cur_t; total_pl = net - acct["start_cash"]
    c1, c2 = st.columns(2)
    c1.metric("Net worth", f"₹{net:,.0f}", f"{total_pl:,.0f} ({total_pl/acct['start_cash']*100:+.2f}%)")
    c2.metric("Virtual cash", f"₹{cash:,.0f}")
    c3, c4 = st.columns(2)
    c3.metric("Holdings value", f"₹{cur_t:,.0f}", f"{cur_t-inv_t:,.0f} unrealised")
    c4.metric("Realised P&L", f"₹{realised:,.0f}")

    st.markdown("#### Place a demo order")
    with st.form("ticket"):
        sym = st.selectbox("Stock (any company: add it in 'Find any stock' first)", sorted(close_all.columns))
        side = st.radio("Side", ["BUY", "SELL"], horizontal=True)
        qty = st.number_input("Quantity", 1, 1000000, 10)
        st.caption(f"Last price ≈ ₹{px(sym):,.2f} (can be delayed a few minutes) · order value ≈ ₹{qty*px(sym):,.0f}")
        sl = st.number_input("Stop-loss ₹ (optional, BUY only)", 0.0, value=0.0)
        tg = st.number_input("Target ₹ (optional, BUY only)", 0.0, value=0.0)
        if st.form_submit_button("Place order"):
            err = trade(sym, side, qty, px(sym), sl or None, tg or None)
            if err: st.error(err)
            else: st.success(f"{side} {qty} {sym} executed (demo)"); st.rerun()

    st.markdown("#### Holdings")
    if len(H):
        st.dataframe(H, hide_index=True, use_container_width=True, column_config={
            **{k: st.column_config.NumberColumn(format="₹%.2f") for k in ["Avg price", "LTP", "Invested", "Current", "P&L ₹", "Stop", "Target"]},
            "P&L %": st.column_config.NumberColumn(format="%.2f%%")})
        pick = st.selectbox("Track growth of", list(pos))
        since = pd.Timestamp(pos[pick]["since"]).normalize()
        if pick in close_all.columns:
            s_ = close_all[pick].dropna(); s_ = s_[s_.index >= since - pd.Timedelta(days=5)]
            if len(s_) > 1: st.line_chart(s_ / pos[pick]["cost"] * pos[pick]["qty"])
        st.caption("Chart shows the current worth of that holding over time (₹).")
        for s in pos:
            if st.button(f"Sell all {s}", key=f"sell_{s}"):
                trade(s, "SELL", pos[s]["qty"], px(s)); st.rerun()
    else:
        st.info("No holdings yet. Use a 🧪 Demo buy button on an idea or place an order above.")

    hist = E.history(acct["trades"], close_all, acct["start_cash"])
    if len(hist) > 1:
        st.markdown("#### Portfolio growth"); st.line_chart(hist)
    elif acct["trades"]:
        st.caption("Portfolio growth chart appears after the first full trading day.")

    with st.expander("Order history & account"):
        if acct["trades"]:
            st.dataframe(pd.DataFrame(acct["trades"]).iloc[::-1], hide_index=True, use_container_width=True)
        st.download_button("⬇️ Export account (backup)", json.dumps(acct), f"{user}_demo_account.json")
        up = st.file_uploader("Import a backup", type="json")
        if up and st.button("Restore backup"):
            acct.clear(); acct.update(json.load(up)); save(); st.rerun()
        new_cash = st.number_input("Reset with starting cash (₹)", 10000, 100000000, int(acct["start_cash"]), step=50000)
        if st.button("⚠️ Reset account"):
            acct.clear(); acct.update(start_cash=float(new_cash), trades=[]); save(); st.rerun()
        st.caption("Demo only: virtual money, no brokerage, taxes or slippage, instant fills at the last available price. "
                   "On free cloud hosting, saved accounts may reset when the app restarts, so export a backup.")

with t5:
    ta, tb = st.tabs(["📋 Copy & paste (no key)", "⚡ Direct (API key)"])
    with ta:
        st.write("**1.** Build a prompt  **2.** Copy it and open Gemini  **3.** Paste Gemini's reply below to get recommendations here.")
        st.caption("The prompt tells Gemini to use broker and institutional views, global news and technology shifts, government policy, "
                   "and company results, and lets it pick **any** NSE/BSE company.")
        kind = st.radio("What do you want to ask?", E.PROMPT_KINDS)
        own = st.text_input("Your question") if kind == E.PROMPT_KINDS[3] else ""
        notes = st.text_area("Optional: your own notes on news, policy or events to include", acct.get("notes", ""), height=90,
                             placeholder="e.g. Budget raised railway capex; new PLI for electronics; crude fell 8% this week")
        if notes != acct.get("notes", ""): acct["notes"] = notes; save()
        prompt = E.build_prompt(kind, own, build_context(), dt.date.today())
        tj = json.dumps(prompt).replace("</", "<\\/")
        components.html(f"""<div style="display:flex;gap:8px">
<button id="c" style="flex:1;padding:12px;border:0;border-radius:10px;background:#0e9f5a;color:#fff;font:600 15px system-ui">📋 Copy prompt</button>
<button id="o" style="flex:1;padding:12px;border:0;border-radius:10px;background:#1d6fd8;color:#fff;font:600 15px system-ui">🚀 Copy + open Gemini</button></div>
<div id="m" style="font:14px system-ui;margin-top:8px;color:#222"></div>
<script>const t={tj};const $=i=>document.getElementById(i);
async function cp(){{if(window.Android&&Android.copy){{try{{Android.copy(t);return true}}catch(e){{}}}}
try{{await navigator.clipboard.writeText(t);return true}}catch(e){{}}
try{{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();const ok=document.execCommand('copy');a.remove();return ok}}catch(e){{return false}}}}
$('c').onclick=async()=>{{$('m').textContent=(await cp())?'✅ Copied. Now open Gemini and paste.':'⚠️ Copy failed: open Show prompt text below and long-press to copy.'}};
$('o').onclick=async()=>{{const ok=await cp();$('m').textContent=ok?'✅ Prompt copied. Opening Gemini, paste it there.':'Opening Gemini… (copy the prompt from Show prompt text below)';
if(window.Android&&Android.openGemini){{Android.openGemini()}}
else if(/Android/i.test(navigator.userAgent)){{window.open('intent://gemini.google.com/app#Intent;scheme=https;package=com.google.android.apps.bard;S.browser_fallback_url=https%3A%2F%2Fgemini.google.com%2Fapp;end','_top')}}
else{{window.open('https://gemini.google.com/app','_blank')}}}};</script>""", height=110)
        st.link_button("🌐 Open Gemini in browser instead", "https://gemini.google.com/app", use_container_width=True)
        with st.expander("Show prompt text"): st.code(prompt, language=None)
        st.divider()
        reply = st.text_area("Paste Gemini's reply here", height=160, key="greply", placeholder="Paste the JSON reply from Gemini…")
        if st.button("✅ Show recommendations", type="primary", use_container_width=True):
            items = E.parse_recs(reply)
            if items:
                acct["recs"] = dict(ts=dt.datetime.now().strftime("%d %b %Y %H:%M"), items=items); save(); st.rerun()
            elif items is None:
                st.error("Couldn't find the JSON list in that reply. Ask Gemini: 'Reply again with only the JSON array', then paste it.")
                if reply.strip(): st.markdown("**Gemini's raw reply:**"); st.write(reply)
            else:
                st.warning("The reply had no usable recommendations.")
        recs = acct.get("recs")
        if recs:
            st.subheader("Gemini's recommendations")
            st.caption(f"Pasted {recs['ts']} · AI opinion, can be wrong, not SEBI-registered advice")
            for i, r in enumerate(recs["items"]):
                sym = r["symbol"]; al = acct.setdefault("alias", {}); use = al.get(sym) or sym
                if use not in close_all.columns and sym not in al:
                    hits = search_stocks(r.get("company") or sym); al[sym] = hits[0]["symbol"] if hits else ""; save()
                    if al[sym]: st.rerun()
                last = px(use)
                with st.container(border=True, key=f"card_rec_{i}"):
                    st.markdown(f"### {use} · {r['action'] or 'n/a'}")
                    if r.get("company"): st.caption(r["company"])
                    f_ = lambda v: "n/a" if v is None else f"₹{v:,.2f}"
                    st.write(f"Entry {f_(r['entry'])} · Stop-loss {f_(r['stop'])} · Target {f_(r['target'])}")
                    st.caption(f"{r['horizon']} · confidence {r['confidence'] or 'n/a'}" + (f" · liquidity {r['liquidity']}" if r.get("liquidity") else ""))
                    if r["reason"]: st.write(r["reason"])
                    for lab, k in (("🏦 Brokers/institutions", "broker_view"), ("🌍 News & policy", "news_policy"), ("📊 Financials", "financials")):
                        if r.get(k): st.caption(f"{lab}: {r[k]}")
                    if r["risk"]: st.caption(f"⚠️ Risk: {r['risk']}")
                    if last == last:
                        st.caption(f"Live price now ≈ ₹{last:,.2f}")
                        if r["entry"] and abs(r["entry"] / last - 1) > 0.10:
                            st.warning(f"Gemini's entry differs from the live price by {abs(r['entry']/last-1)*100:.0f}%. It may have used old prices.")
                        if r["stop"] and r["stop"] >= last: st.warning("Its stop-loss is above the live price, so it is not usable as given.")
                        if r["target"] and r["target"] <= last: st.warning("Its target is below the live price.")
                        stop_ok = r["stop"] if r["stop"] and r["stop"] < last else None
                        qn = E.qty_for(last, stop_ok, capital, risk)
                        if qn >= 1 and st.button(f"🧪 Demo buy {qn} @ ₹{last:,.2f}", key=f"gr_{i}_{use}"):
                            err = trade(use, "BUY", qn, last, stop_ok, r["target"] if r["target"] and r["target"] > last else None)
                            st.error(err) if err else (st.success("Demo order placed. See the Demo portfolio tab."), st.rerun())
                    else:
                        st.info("No price found for this symbol on NSE/BSE. Check it in the 'Find any stock' tab (try the company name or BSE code).")
            if st.button("Clear recommendations"): acct.pop("recs", None); save(); st.rerun()
    with tb:
        st.write("Ask Gemini directly inside the app. It also receives this app's rankings, analyst data and your demo holdings as context, and may suggest any company.")
        chat = st.session_state.setdefault("gchat", [])
        qs = {"Best 1‑month ideas?": "Which stocks (any NSE/BSE company) look best for the next month? Use broker/institutional views, global news, government policy and latest results. Give entry, stop-loss, target and risks.",
              "Best 1‑year ideas?": "Which stocks (any NSE/BSE company) look best for the next 12 months? Use broker/institutional views, global news and technology shifts, government policy and latest results.",
              "Review my demo portfolio": "Review my demo holdings. What are the concentration and risk issues, and what would you change?"}
        cols_ = st.columns(len(qs)); quick = None
        for c_, (lab, txt) in zip(cols_, qs.items()):
            if c_.button(lab, use_container_width=True): quick = txt
        for h in chat: st.chat_message("user" if h["role"] == "user" else "assistant").write(h["text"])
        q = st.chat_input("Ask about any stock, strategy or your portfolio…") or quick
        if q:
            if not gkey:
                st.error("Add your Gemini API key in the sidebar first (free at aistudio.google.com).")
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

with t4:
    st.write("How the 1‑month strategy (top 5 by momentum, rebalanced every ~21 trading days) would have done on this stock list over the past ~2 years:")
    bt = E.backtest(close)
    if len(bt):
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg monthly return", f"{bt.strategy.mean()*100:.1f}%")
        c2.metric("Months with ≥10% gain", f"{(bt.strategy>=.10).mean()*100:.0f}%")
        c3.metric("Months with a loss", f"{(bt.strategy<0).mean()*100:.0f}%")
        st.line_chart(((1 + bt.set_index("date")[["strategy", "universe"]]).cumprod() - 1) * 100)
        st.caption("Uses today's stock list (survivorship bias), ignores brokerage, taxes and slippage. Real results will be lower.")
