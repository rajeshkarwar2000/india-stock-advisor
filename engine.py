"""Scoring, strategy and backtest logic (pandas/numpy only)."""
import numpy as np, pandas as pd
from math import erf, sqrt, log

UNIVERSE = """RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC SBIN LT HINDUNILVR KOTAKBANK AXISBANK BAJFINANCE
MARUTI SUNPHARMA TITAN ULTRACEMCO ASIANPAINT NTPC POWERGRID ONGC M&M TATAMOTORS TATASTEEL JSWSTEEL ADANIENT
ADANIPORTS BEL HAL COALINDIA TRENT CIPLA DRREDDY EICHERMOT HCLTECH WIPRO TECHM NESTLEIND TATACONSUM
BAJAJFINSV INDIGO HINDALCO GRASIM DIVISLAB APOLLOHOSP SBILIFE HDFCLIFE TVSMOTOR CGPOWER POLYCAB DIXON
PERSISTENT COFORGE MUTHOOTFIN CHOLAFIN PFC RECLTD IRFC BANKBARODA HAVELLS PIDILITIND ZOMATO""".split()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def metrics(close: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for c in close.columns:
        s = close[c].dropna()
        if len(s) < 130:
            continue
        p = s.iloc[-1]
        ret = lambda n: p / s.iloc[-1 - n] - 1 if len(s) > n else np.nan
        rows[c] = dict(
            price=p, r1m=ret(21), r3m=ret(63), r6m=ret(126), r12m=ret(252),
            vol=s.pct_change().std() * np.sqrt(252), rsi=rsi(s).iloc[-1],
            dma20=s.rolling(20).mean().iloc[-1], dma50=s.rolling(50).mean().iloc[-1],
            dma200=s.rolling(200).mean().iloc[-1], hi52=s.iloc[-252:].max(),
            atr=s.diff().abs().rolling(14).mean().iloc[-1])
    return pd.DataFrame(rows).T.astype(float)

def _rk(x): return x.rank(pct=True) * 100

def score(m: pd.DataFrame) -> pd.DataFrame:
    m = m.copy()
    trend = np.where((m.price > m.dma20) & (m.dma20 > m.dma50), 100, np.where(m.price > m.dma50, 50, 0))
    m["short"] = 0.35*_rk(m.r1m) + 0.35*_rk(m.r3m) + 0.15*_rk(m.price/m.hi52) + 0.15*trend
    m.loc[m.rsi > 78, "short"] -= 15          # overheated: likely to pull back
    t200 = np.where(m.price > m.dma200, 100, 0)
    m["long"] = 0.35*_rk(m.r12m.fillna(m.r6m)) + 0.25*_rk(m.r6m) + 0.2*_rk(-m.vol) + 0.2*t200
    return m

def p_hit(gain_pct, vol, months):
    """Rough chance of gaining >= gain_pct (zero-drift lognormal)."""
    s = vol * sqrt(months / 12)
    if s <= 0: return 0.0
    z = (log(1 + gain_pct/100) + 0.5*s*s) / s
    return 0.5 * (1 - erf(z / sqrt(2)))

def plan(r, capital, risk_pct, kind, target_px=None):
    p = r.price
    if kind == "short":
        wait = r.rsi >= 70
        entry = r.dma20 if wait else p
        stop = entry - 2 * r.atr
        target = entry + 3 * r.atr
        action = f"Wait for dip to ~₹{entry:,.0f}" if wait else "Buy now"
    else:
        entry = p
        stop = max(r.dma200 * 0.97 if not np.isnan(r.dma200) else p * 0.8, p * 0.75)
        target = target_px if target_px and target_px > p else p * 1.3
        action = "Accumulate in 3 parts"
    risk_per_share = max(entry - stop, 0.01)
    qty = int(min(capital * risk_pct / 100 / risk_per_share, capital * 0.2 / entry))
    return dict(action=action, entry=entry, stop=stop, target=target, qty=qty,
                invest=qty * entry, max_loss=qty * (entry - stop))

def backtest(close: pd.DataFrame, topn=5, hold=21):
    close = close.dropna(axis=1, thresh=int(len(close) * .9)).ffill()
    out = []
    for i in range(252, len(close) - hold, hold):
        now = close.iloc[i]
        sc = 0.5 * (now / close.iloc[i-21] - 1).rank() + 0.5 * (now / close.iloc[i-63] - 1).rank()
        picks = sc.nlargest(topn).index
        fwd = close.iloc[i + hold][picks] / now[picks] - 1
        bench = (close.iloc[i + hold] / now - 1).mean()
        out.append(dict(date=close.index[i], strategy=fwd.mean(), universe=bench, hit10=(fwd >= .10).mean()))
    return pd.DataFrame(out)

# ---------- Demo (paper) trading ----------
def positions(trades):
    """Open positions (average-cost method) and realised P&L from a trade list."""
    pos, realised = {}, 0.0
    for t in trades:
        p = pos.setdefault(t["symbol"], dict(qty=0, cost=0.0, stop=None, target=None, since=t["ts"]))
        if t["side"] == "BUY":
            if p["qty"] == 0: p["since"] = t["ts"]
            p["cost"] += t["qty"] * t["price"]; p["qty"] += t["qty"]
            if t.get("stop"): p["stop"], p["target"] = t["stop"], t.get("target")
        else:
            avg = p["cost"] / p["qty"]
            realised += (t["price"] - avg) * t["qty"]
            p["cost"] -= avg * t["qty"]; p["qty"] -= t["qty"]
    return {k: v for k, v in pos.items() if v["qty"] > 0}, realised

def cash_balance(start_cash, trades):
    return start_cash + sum((1 if t["side"] == "SELL" else -1) * t["qty"] * t["price"] for t in trades)

def history(trades, close, start_cash):
    """Daily net worth (cash + holdings at closing prices) since the first trade."""
    if not trades: return pd.Series(dtype=float)
    t = pd.DataFrame(trades); t["d"] = pd.to_datetime(t.ts).dt.normalize()
    close = close.ffill(); rows = {}
    for d in close.index[close.index >= t.d.min()]:
        cash, q = start_cash, {}
        for _, x in t[t.d <= d].iterrows():
            s = 1 if x.side == "BUY" else -1
            cash -= s * x.qty * x.price; q[x.symbol] = q.get(x.symbol, 0) + s * x.qty
        rows[d] = cash + sum(n * close[s].loc[d] for s, n in q.items() if n and s in close.columns)
    return pd.Series(rows)

# ---------- Copy-paste Gemini flow ----------
import json as _json, re as _re

PROMPT_KINDS = ["1‑month ideas", "1‑year ideas", "Review my demo portfolio", "My own question"]
_ASK = {PROMPT_KINDS[0]: "Pick the best NSE stocks to consider for roughly the next 1 month.",
        PROMPT_KINDS[1]: "Pick the best NSE stocks to consider for roughly the next 12 months.",
        PROMPT_KINDS[2]: "Review my demo holdings below and say what to buy more of, hold or avoid."}
_FORMAT = ('Reply ONLY with a JSON array (no other text, no markdown) of up to 5 objects, each exactly like: '
           '{"symbol":"NSE symbol e.g. RELIANCE","action":"Buy now | Wait for dip | Avoid","entry":number in rupees,'
           '"stop_loss":number,"target":number,"horizon":"1 month | 1 year","confidence":"low | medium | high",'
           '"reason":"max 2 sentences","risk":"main risk, max 1 sentence"}')

def build_prompt(kind, own, context, today):
    ask = own.strip() or "Suggest NSE stocks worth researching." if kind == PROMPT_KINDS[3] else _ASK[kind]
    return (f"You are a cautious equity research assistant for an Indian retail investor (NSE, prices in ₹). "
            f"Today is {today:%d %b %Y}. {ask} Use the app data below plus the latest news and prices you can find. "
            f"Never promise returns; targets like +10-20% in a month or +100% in a year are uncertain. "
            f"This is not SEBI-registered advice.\n\nApp data:\n{context}\n\n{_FORMAT}")

def _num(v):
    try: return float(str(v).replace(",", "").replace("₹", "").replace("Rs", "").strip())
    except Exception: return None

def parse_recs(text):
    """Extract recommendation objects from a pasted Gemini reply. Returns a list (maybe empty) or None if no JSON found."""
    m = _re.search(r"\[.*\]", text or "", _re.S)
    if not m: return None
    try: data = _json.loads(m.group(0))
    except Exception: return None
    out = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not d.get("symbol"): continue
        sym = _re.sub(r"^(NSE:|BSE:)|\.(NS|BO)$", "", str(d["symbol"]).upper().strip())
        out.append(dict(symbol=sym, action=str(d.get("action", "")), entry=_num(d.get("entry")),
                        stop=_num(d.get("stop_loss", d.get("stop"))), target=_num(d.get("target")),
                        horizon=str(d.get("horizon", "")), confidence=str(d.get("confidence", "")),
                        reason=str(d.get("reason", "")), risk=str(d.get("risk", ""))))
    return out[:10]

def qty_for(price, stop, capital, risk_pct):
    """Shares to buy: risk-based if the stop is below price, else 10% of capital; never above 20% of capital."""
    if not price or price <= 0: return 0
    if stop and stop < price: q = capital * risk_pct / 100 / (price - stop)
    else: q = capital * 0.10 / price
    return int(min(q, capital * 0.2 / price))
