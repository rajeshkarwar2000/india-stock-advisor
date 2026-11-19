import datetime as dt, json, os, re
import numpy as np, pandas as pd, streamlit as st, yfinance as yf
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
    extra = st.text_input("Add NSE symbols (comma-separated)", "")
    auto_exec = st.checkbox("Auto-sell at stop-loss / target (demo)", True)
    st.divider(); st.caption("🤖 Gemini (optional)")
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

# ---------- data ----------
@st.cache_data(ttl=3600, show_spinner="Fetching latest NSE prices…")
def load(symbols):
    df = yf.download([s + ".NS" for s in symbols], period="3y", auto_adjust=True, progress=False)["Close"]
    df.columns = [c.replace(".NS", "") for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.dropna(how="all")

@st.cache_data(ttl=60, show_spinner=False)
def live_prices(symbols):
    try:
        d = yf.download([s + ".NS" for s in symbols], period="1d", interval="5m", progress=False, auto_adjust=True)["Close"]
        d = d.ffill().iloc[-1].dropna(); d.index = [c.replace(".NS", "") for c in d.index]
        return d.to_dict()
    except Exception:
        return {}

@st.cache_data(ttl=86400, show_spinner=False)
def fundamentals(sym):
    try:
        i = yf.Ticker(sym + ".NS").info
        return dict(rev_g=i.get("revenueGrowth"), eps_g=i.get("earningsGrowth"), target=i.get("targetMeanPrice"))
    except Exception:
        return {}

held = tuple(E.positions(acct["trades"])[0])
symbols = list(dict.fromkeys(E.UNIVERSE + [s.strip().upper() for s in extra.split(",") if s.strip()] + list(held)))
try:
    close = load(tuple(symbols))
except Exception as e:
    st.error(f"Could not fetch data: {e}"); st.stop()
live = live_prices(tuple(close.columns))
def px(s):
    if s in live: return float(live[s])
    return float(close[s].dropna().iloc[-1]) if s in close.columns else float("nan")

def trade(sym, side, qty, price, stop=None, target=None):
    pos, _ = E.positions(acct["trades"]); cash = E.cash_balance(acct["start_cash"], acct["trades"])
    if qty < 1: return "Quantity must be at least 1."
    if not price == price: return "No price available for this symbol."
    if side == "BUY" and qty * price > cash: return f"Not enough virtual cash (₹{cash:,.0f} available)."
    if side == "SELL" and pos.get(sym, {}).get("qty", 0) < qty: return "You don't hold that many shares."
    acct["trades"].append(dict(ts=dt.datetime.now().isoformat(timespec="seconds"), symbol=sym, side=side,
                               qty=int(qty), price=round(float(price), 2), stop=stop, target=target))
    save(); return None

# auto stop-loss / target execution (like a bracket order)
if auto_exec:
    msgs = []
    for s, p in E.positions(acct["trades"])[0].items():
        q, last = p["qty"], px(s)
        if p["stop"] and last <= p["stop"] and not trade(s, "SELL", q, last): msgs.append(f"🛑 {s}: stop-loss hit, sold {q} @ ₹{last:,.2f}")
        elif p["target"] and last >= p["target"] and not trade(s, "SELL", q, last): msgs.append(f"🎯 {s}: target hit, sold {q} @ ₹{last:,.2f}")
    if msgs:
        for m_ in msgs: st.toast(m_)
        st.session_state.msgs = msgs; st.rerun()
for m_ in st.session_state.pop("msgs", []): st.info(m_)

m = E.score(E.metrics(close))
st.caption(f"Data as of {close.index[-1]:%d %b %Y} · prices refresh automatically · {len(m)} stocks scanned")
pct = lambda x: "n/a" if pd.isna(x) else f"{x*100:+.0f}%"

def show(kind, col, months, gain):
    for sym, r in m.sort_values(col, ascending=False).head(topn).iterrows():
        f = fundamentals(sym) if kind == "long" else {}
        r = r.copy(); r["price"] = px(sym)
        p = E.plan(r, capital, risk, kind, f.get("target"))
        with st.container(border=True):
            a, b = st.columns([3, 1]); a.subheader(sym); b.metric("Score", f"{r[col]:.0f}")
            st.write(f"**{p['action']}** · Entry ₹{p['entry']:,.0f} · Stop-loss ₹{p['stop']:,.0f} · Target ₹{p['target']:,.0f}")
            st.write(f"Suggested qty **{p['qty']}** (≈₹{p['invest']:,.0f}); worst case loss at stop ≈ ₹{p['max_loss']:,.0f}")
            st.caption(f"1M {pct(r.r1m)} · 3M {pct(r.r3m)} · 12M {pct(r.r12m)} · RSI {r.rsi:.0f} · volatility {r.vol*100:.0f}%")
            if f.get("rev_g") is not None or f.get("eps_g") is not None:
                st.caption(f"Revenue growth {pct(f.get('rev_g') or np.nan)} · Earnings growth {pct(f.get('eps_g') or np.nan)}")
            st.caption(f"Model odds of ≥{gain}% in {months} month(s): **{E.p_hit(gain, r.vol, months)*100:.0f}%**")
            if p["qty"] >= 1 and st.button(f"🧪 Demo buy {p['qty']} @ ₹{r.price:,.2f} (with stop & target)", key=f"b_{kind}_{sym}"):
                err = trade(sym, "BUY", p["qty"], r.price, round(p["stop"], 2), round(p["target"], 2))
                st.error(err) if err else (st.success("Demo order placed. See the Portfolio tab."), st.rerun())

t1, t2, t3, t4, t5 = st.tabs(["1‑Month ideas", "1‑Year ideas", "💼 Demo portfolio", "Backtest", "🤖 Ask Gemini"])
with t1: show("short", "short", 1, 10)
with t2: show("long", "long", 12, 100)

with t3:
    pos, realised = E.positions(acct["trades"]); cash = E.cash_balance(acct["start_cash"], acct["trades"])
    rows = []
    for s, p in pos.items():
        last = px(s); inv = p["cost"]; cur = p["qty"] * last
        rows.append({"Stock": s, "Qty": p["qty"], "Avg price": inv / p["qty"], "LTP": last, "Invested": inv,
                     "Current": cur, "P&L ₹": cur - inv, "P&L %": (cur / inv - 1) * 100,
                     "Stop": p["stop"], "Target": p["target"]})
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
        sym = st.selectbox("Stock", sorted(close.columns))
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
        s_ = close[pick].dropna(); s_ = s_[s_.index >= since - pd.Timedelta(days=5)]
        if len(s_) > 1: st.line_chart(s_ / pos[pick]["cost"] * pos[pick]["qty"])
        st.caption("Chart shows the current worth of that holding over time (₹).")
        for s in pos:
            if st.button(f"Sell all {s}", key=f"sell_{s}"):
                trade(s, "SELL", pos[s]["qty"], px(s)); st.rerun()
    else:
        st.info("No holdings yet. Use a 🧪 Demo buy button on an idea or place an order above.")

    hist = E.history(acct["trades"], close, acct["start_cash"])
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

with t5:
    st.write("Ask Gemini for its own view. It also receives this app's current rankings and your demo holdings as context.")
    def build_context():
        cols = ["price", "r1m", "r3m", "r12m", "rsi", "vol"]
        def block(col, name):
            t = m.sort_values(col, ascending=False).head(10)[cols].copy()
            for c in ["r1m", "r3m", "r12m", "vol"]: t[c] = (t[c] * 100).round(0)
            t[["price", "rsi"]] = t[["price", "rsi"]].round(0)
            return f"Top {name} (price Rs, 1M/3M/12M return %, RSI, volatility %):\n" + t.to_string()
        pos_, _ = E.positions(acct["trades"])
        hold = ", ".join(f"{k} x{v['qty']} avg {v['cost']/v['qty']:.0f}" for k, v in pos_.items()) or "none"
        return f"As of {close.index[-1]:%d %b %Y}\n{block('short', '1-month momentum ideas')}\n{block('long', '1-year ideas')}\nDemo holdings: {hold}"
    chat = st.session_state.setdefault("gchat", [])
    qs = {"Best 1‑month ideas?": "From the app data and current news, which 3 stocks look best for the next month, and what are the risks, entry, stop-loss and target for each?",
          "Best 1‑year ideas?": "From the app data and current news, which 3 stocks look best for a 1-year horizon, and what could go wrong?",
          "Review my demo portfolio": "Review my demo holdings. What are the concentration and risk issues, and what would you change?"}
    cols_ = st.columns(len(qs)); quick = None
    for c_, (lab, txt) in zip(cols_, qs.items()):
        if c_.button(lab, use_container_width=True): quick = txt
    for h in chat: st.chat_message("user" if h["role"] == "user" else "assistant").write(h["text"])
    q = st.chat_input("Ask about a stock, strategy or your portfolio…") or quick
    if q:
        if not gkey:
            st.error("Add your Gemini API key in the sidebar first (free at aistudio.google.com).")
        else:
            chat.append(dict(role="user", text=q)); st.chat_message("user").write(q)
            with st.chat_message("assistant"), st.spinner("Gemini is thinking…"):
                try:
                    ans = G.ask(gkey, gmodel.strip(), chat, build_context(), gsearch)
                    chat.append(dict(role="model", text=ans)); st.write(ans)
                except Exception as e:
                    chat.pop(); st.error(str(e))
    if chat and st.button("Clear chat"): chat.clear(); st.rerun()
    st.caption("Gemini's answers are AI-generated opinions, can be wrong, and are not SEBI-registered advice. "
               "Your question, the rankings and your demo holdings are sent to Google when you ask. Your API key may be billed by Google if you exceed the free tier.")
