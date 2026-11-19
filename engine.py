"""Scoring, strategy and backtest logic (pandas/numpy only)."""
import numpy as np, pandas as pd
from math import erf, sqrt, log

UNIVERSE = """RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC SBIN LT HINDUNILVR KOTAKBANK AXISBANK BAJFINANCE
MARUTI SUNPHARMA TITAN ULTRACEMCO ASIANPAINT NTPC POWERGRID ONGC M&M TATAMOTORS TATASTEEL JSWSTEEL ADANIENT
ADANIPORTS BEL HAL COALINDIA TRENT CIPLA DRREDDY EICHERMOT HCLTECH WIPRO TECHM NESTLEIND TATACONSUM
BAJAJFINSV INDIGO HINDALCO GRASIM DIVISLAB APOLLOHOSP SBILIFE HDFCLIFE TVSMOTOR CGPOWER POLYCAB DIXON
PERSISTENT COFORGE MUTHOOTFIN CHOLAFIN PFC RECLTD IRFC BANKBARODA HAVELLS PIDILITIND ETERNAL JPL JIOFIN""".split()
# TATAMOTORS was demerged in 2025 (TMPV / TMCV); symbols that return no data are skipped automatically.
BROAD = list(dict.fromkeys(UNIVERSE + """BAJAJ-AUTO HEROMOTOCO INDUSINDBK BPCL SHRIRAMFIN TMPV TMCV ADANIGREEN ADANIPOWER AMBUJACEM DMART DLF GAIL
GODREJCP ICICIGI ICICIPRULI IOC IRCTC JINDALSTEL LICI LODHA MARICO MOTHERSON NAUKRI SIEMENS SRF TATAPOWER TORNTPHARM VEDL
ZYDUSLIFE ABB ATGL BOSCHLTD CANBK COLPAL CUMMINSIND DABUR HDFCAMC INDHOTEL JSWENERGY LTIM MAXHEALTH NHPC OBEROIRLTY PAYTM
PIIND PNB SAIL SHREECEM SOLARINDS SUPREMEIND SWIGGY TATAELXSI TATATECH TIINDIA UNIONBANK UNITDSPR VBL VOLTAS YESBANK ABCAPITAL
ABFRL ACC APLAPOLLO ASHOKLEY ASTRAL AUBANK AUROPHARMA BALKRISIND BANDHANBNK BATAINDIA BERGEPAINT BHARATFORG BHEL BIOCON
BLUESTARCO CONCOR CROMPTON DALBHARAT DEEPAKNTR ESCORTS EXIDEIND FEDERALBNK FORTIS GLENMARK GMRAIRPORT GODREJPROP HINDPETRO
HUDCO IDFCFIRSTB IEX IGL INDIANB INDUSTOWER IPCALAB JKCEMENT JUBLFOOD KALYANKJIL KEI KPITTECH LAURUSLABS LICHSGFIN LUPIN
MANKIND MAZDOCK MFSL MPHASIS MRF NATIONALUM NAVINFLUOR NMDC OFSS OIL PAGEIND PATANJALI PETRONET PHOENIXLTD POLICYBZR
POONAWALLA PRESTIGE RAMCOCEM RVNL SBICARD SONACOMS SUZLON SYNGENE TATACHEM TATACOMM TORNTPOWER UPL UNOMINDA WAAREEENER
HYUNDAI LGEINDIA TATACAP NTPCGREEN BAJAJHFL ITCHOTELS PREMIERENE INOXWIND SJVN IREDA COCHINSHIP GRSE BDL BSE MCX CDSL
ANGELONE KFINTECH CAMS HINDZINC GODREJIND AWL DELHIVERY NYKAA LTF BANKINDIA IDBI RBLBANK KARURVYSYA CITYUNIONBK""".split()))
UNIVERSES = {"Popular (~65 stocks, fastest)": UNIVERSE, "Broad (~230 stocks, slower)": BROAD}

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def metrics(close: pd.DataFrame, min_len: int = 130, volume=None) -> pd.DataFrame:
    rows = {}
    for c in close.columns:
        s = close[c].dropna()
        if len(s) < min_len:
            continue
        p = s.iloc[-1]
        v = volume[c].reindex(s.index).fillna(0) if volume is not None and c in volume.columns else None
        ret = lambda n: p / s.iloc[-1 - n] - 1 if len(s) > n else np.nan
        rows[c] = dict(
            price=p, r1m=ret(21), r3m=ret(63), r6m=ret(126), r12m=ret(252),
            vol=s.pct_change().std() * np.sqrt(252), rsi=rsi(s).iloc[-1],
            dma20=s.rolling(20).mean().iloc[-1], dma50=s.rolling(50).mean().iloc[-1],
            dma200=s.rolling(200).mean().iloc[-1], hi52=s.iloc[-252:].max(),
            atr=s.diff().abs().rolling(14).mean().iloc[-1],
            avg_val=float((s * v).tail(20).mean()) if v is not None else np.nan,
            vsurge=float(v.tail(5).mean() / v.tail(60).mean()) if v is not None and v.tail(60).mean() > 0 else np.nan)
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
    atr = r.atr if r.atr == r.atr else 0.025 * p
    if kind == "short":
        wait = r.rsi >= 70 and r.dma20 == r.dma20
        entry = r.dma20 if wait else p
        stop = entry - 2 * atr
        target = entry + 3 * atr
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
_ASK = {PROMPT_KINDS[0]: "Pick the stocks with the highest realistic return potential for roughly the next 1 month, from ANY listed company that is liquid enough to trade.",
        PROMPT_KINDS[1]: "Pick the stocks with the highest realistic return potential for roughly the next 12 months, from ANY listed company that is liquid enough to trade.",
        PROMPT_KINDS[2]: "Review my demo holdings below and say what to buy more of, hold or avoid, and suggest better alternatives."}

RESEARCH_RULES = (
    "You may recommend ANY company listed on NSE or BSE: large, mid, small or micro cap, recent IPOs and new listings "
    "(for example Jio Platforms, NSE: JPL). Do NOT limit yourself to the companies in the app data; the app data is only one input.\n"
    "Prioritise feasible stocks with the highest realistic upside: look beyond well-known names, including mid and small caps, turnarounds, sector leaders benefiting from policy or technology shifts and recent IPOs, "
    "but avoid illiquid, pump-and-dump, ASM/GSM-listed or fraud-risk stocks and say how liquid each pick is.\n"
    "Base every pick on ALL of these, using the latest information you can find (use Google Search / web browsing):\n"
    "1. EXPERT VIEWS: recent buy/sell ratings, target prices and notes from major brokerages and banks (e.g. Motilal Oswal, ICICI Securities, "
    "Kotak, Axis, HDFC Securities, Nuvama, Jefferies, CLSA, Goldman Sachs, Morgan Stanley, Nomura, UBS, JP Morgan, Citi), plus institutional buying: "
    "FII/FPI and DII flows, mutual fund buying, bulk/block deals, rising promoter or institutional holding.\n"
    "2. GLOBAL NEWS AND TECHNOLOGY: technology and industry shifts (AI, semiconductors, electrification and EVs, renewables, telecom/5G, pharma, defence, "
    "supply chains) and international events (US Fed and interest rates, USD/INR, crude oil, tariffs and trade deals, wars and geopolitics, China, global markets), "
    "and which Indian companies they help or hurt.\n"
    "3. GOVERNMENT POLICY: Indian government and regulator moves: Budget and capex plans, PLI and other incentives, RBI/SEBI decisions, GST/tax and tariff changes, "
    "sector reforms, privatisation, defence/infrastructure/green-energy backing, new laws or approvals affecting a company.\n"
    "4. FINANCIALS (profit sheets): latest quarterly and annual results: revenue, EBITDA, net profit growth, margins, return on equity, debt, cash flow, "
    "order book, management guidance, valuation (P/E versus peers and history), earnings surprises.\n"
    "5. PRICE ACTION AND RISK: trend, volume, volatility, upcoming events (results, lock-in expiries, ex-dates) and what could go wrong.\n"
    "Be balanced and include what the bears say. Never promise returns; moves like +10-20% in a month or +100% in a year are uncertain and usually not achieved. "
    "This is not SEBI-registered investment advice.")

SYSTEM_RULES = ("You are a cautious, thorough equity research assistant for an Indian retail investor (NSE/BSE, prices in ₹). "
                "Use the app data provided as one input and say when something is not in it. " + RESEARCH_RULES)

_FORMAT = ('Reply ONLY with a JSON array (no other text, no markdown) of up to 8 objects, each exactly like: '
           '{"symbol":"NSE symbol e.g. RELIANCE","company":"full company name","action":"Buy now | Wait for dip | Avoid",'
           '"entry":number in rupees,"stop_loss":number,"target":number,"horizon":"1 month | 1 year",'
           '"confidence":"low | medium | high","liquidity":"high | medium | low","reason":"max 2 sentences","broker_view":"what major brokers/institutions say, 1 sentence",'
           '"news_policy":"key global news / government policy driver, 1 sentence","financials":"latest results/profit trend, 1 sentence",'
           '"risk":"main risk, 1 sentence"}')

def build_prompt(kind, own, context, today):
    ask = (own.strip() or "Suggest stocks worth researching.") if kind == PROMPT_KINDS[3] else _ASK[kind]
    return (f"You are a cautious, thorough equity research assistant for an Indian retail investor (NSE/BSE, prices in ₹). "
            f"Today is {today:%d %b %Y}.\nTASK: {ask}\n{RESEARCH_RULES}\n\nApp data (one input only):\n{context}\n\n{_FORMAT}")

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
        g = lambda k: str(d.get(k, "") or "")
        out.append(dict(symbol=sym, company=g("company"), action=g("action"), entry=_num(d.get("entry")),
                        stop=_num(d.get("stop_loss", d.get("stop"))), target=_num(d.get("target")),
                        horizon=g("horizon"), confidence=g("confidence"), liquidity=g("liquidity"), reason=g("reason"), risk=g("risk"),
                        broker_view=g("broker_view"), news_policy=g("news_policy"), financials=g("financials")))
    return out[:10]

def qty_for(price, stop, capital, risk_pct):
    """Shares to buy: risk-based if the stop is below price, else 10% of capital; never above 20% of capital."""
    if not price or price <= 0: return 0
    if stop and stop < price: q = capital * risk_pct / 100 / (price - stop)
    else: q = capital * 0.10 / price
    return int(min(q, capital * 0.2 / price))


def blend(m, F):
    """Combine technical scores with broker/analyst and results data (F = {symbol: info dict})."""
    m = m.copy(); m["fund"] = np.nan
    keys = [k for k in m.index if F.get(k)]
    if not keys:
        m["short2"], m["long2"] = m["short"], m["long"]
        return m
    for c in ("up", "rec_mean", "eps_g", "rev_g"): m[c] = np.nan
    for k in keys:
        f = F[k]
        if f.get("target"): m.loc[k, "up"] = f["target"] / m.loc[k, "price"] - 1
        for c in ("rec_mean", "eps_g", "rev_g"):
            if f.get(c) is not None: m.loc[k, c] = f[c]
    sub = m.loc[keys]
    rk = lambda x: (x.rank(pct=True) * 100).fillna(50)
    fs = 0.35 * rk(sub["up"]) + 0.25 * rk(sub["eps_g"]) + 0.2 * rk(sub["rev_g"]) + 0.2 * rk(-sub["rec_mean"])
    m["short2"] = np.nan; m["long2"] = np.nan; m.loc[keys, "fund"] = fs
    m.loc[keys, "short2"] = 0.8 * sub["short"] + 0.2 * fs
    m.loc[keys, "long2"] = 0.6 * sub["long"] + 0.4 * fs
    return m


import csv as _csv, io as _io

def parse_symbol_csv(text):
    """Symbols (series EQ) from an NSE EQUITY_L.csv or an index constituents csv."""
    out = []
    for row in _csv.DictReader(_io.StringIO(text)):
        row = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        sym, ser = row.get("SYMBOL"), row.get("SERIES")
        if sym and (ser is None or ser == "EQ"): out.append(sym)
    return list(dict.fromkeys(out))

PROFILES = {"Balanced": dict(min_val=5e7, min_price=50, volw=0.0, cap1m=60),
            "High growth": dict(min_val=1e7, min_price=20, volw=0.10, cap1m=90),
            "Aggressive (small & micro caps)": dict(min_val=2.5e6, min_price=10, volw=0.20, cap1m=150)}

def potential(m, profile):
    """High-potential score (0-100) for stocks that are feasible to trade (liquidity and price filters)."""
    p = PROFILES[profile]
    m = m[(m.avg_val >= p["min_val"]) & (m.price >= p["min_price"])].copy()
    if len(m) < 5:
        m["pot"] = np.nan; return m
    rk = lambda x: x.rank(pct=True) * 100
    trend = np.where((m.price > m.dma50) & (m.dma50 > m.dma200), 100, np.where(m.price > m.dma200, 60, 0))
    base = (0.25 * rk(m.r3m) + 0.15 * rk(m.r1m) + 0.15 * rk(m.r6m.fillna(m.r3m)) + 0.15 * rk(m.price / m.hi52)
            + 0.10 * rk(m.vsurge.fillna(1)) + 0.20 * trend)
    m["pot"] = (1 - p["volw"]) * base + p["volw"] * rk(m.vol)
    m.loc[m.rsi > 85, "pot"] -= 10                      # overheated
    m.loc[m.r1m * 100 > p["cap1m"], "pot"] -= 10        # already parabolic this month
    return m

# ---------- Themes (ColorOS 7 style glass etc.) ----------
DEFAULT_THEME = "ColorOS 7 Glass"
THEMES = {
    "Classic (default)": None,
    "ColorOS 7 Glass": dict(
        dark=False, base="#eaf1fa", acc_text="#ffffff",
        blobs=[("120,200,255,.55", "12% 8%"), ("150,230,190,.50", "88% 35%"), ("255,205,170,.35", "40% 95%")],
        card="rgba(255,255,255,.80)", side="rgba(255,255,255,.88)", border="rgba(255,255,255,.95)",
        shadow="0 8px 28px rgba(31,60,120,.14)", accent="#0e9f5a", text="#0b1424", muted="#3b4759", pop="#ffffff"),
    "Midnight Glass": dict(
        dark=True, base="#070b16", acc_text="#06101f",
        blobs=[("60,90,220,.40", "10% 10%"), ("130,60,210,.30", "90% 30%"), ("0,160,170,.25", "45% 95%")],
        card="rgba(22,30,56,.72)", side="rgba(8,12,26,.88)", border="rgba(255,255,255,.22)",
        shadow="0 8px 28px rgba(0,0,0,.50)", accent="#7ab8ff", text="#f4f7ff", muted="#c4cde3", pop="#1a2038"),
    "Aurora": dict(
        dark=True, base="#08121f", acc_text="#04201b",
        blobs=[("0,230,190,.35", "8% 12%"), ("150,80,255,.35", "92% 25%"), ("255,90,170,.25", "50% 100%")],
        card="rgba(18,34,56,.72)", side="rgba(8,18,32,.88)", border="rgba(255,255,255,.26)",
        shadow="0 10px 32px rgba(0,0,0,.45)", accent="#35f0cf", text="#f3fcff", muted="#bcd3e0", pop="#16263c"),
    "Sunset": dict(
        dark=False, base="#fff1e6", acc_text="#ffffff",
        blobs=[("255,150,100,.45", "10% 10%"), ("255,110,160,.35", "90% 30%"), ("255,215,120,.40", "45% 95%")],
        card="rgba(255,255,255,.82)", side="rgba(255,248,242,.90)", border="rgba(255,255,255,.95)",
        shadow="0 8px 28px rgba(160,70,40,.16)", accent="#d9482a", text="#2a1510", muted="#5e4036", pop="#ffffff"),
    "Neon Terminal": dict(
        dark=True, base="#04060a", acc_text="#00140a", font="ui-monospace, SFMono-Regular, Menlo, monospace",
        blobs=[("0,255,140,.08", "15% 10%"), ("0,200,255,.06", "90% 70%")],
        card="rgba(6,18,12,.85)", side="rgba(4,8,6,.92)", border="rgba(0,255,140,.55)",
        shadow="0 0 16px rgba(0,255,140,.25)", accent="#00ff8c", text="#e4ffef", muted="#9fd8b8", pop="#0c1a14"),
}

def theme_css(name, blur=16, radius=22, animate=True, font_px=16, contrast=False):
    t = THEMES.get(name)
    if not t:
        return f"<style>html{{font-size:{font_px}px}}</style>" if font_px != 16 else ""
    t = dict(t)
    if contrast:  # solid, no blur, maximum contrast
        dark = t["dark"]
        t.update(card="#000000" if dark else "#ffffff", side="#000000" if dark else "#ffffff",
                 border="#ffffff" if dark else "#000000", text="#ffffff" if dark else "#000000",
                 muted="#e6e6e6" if dark else "#1a1a1a", base="#000000" if dark else "#ffffff", blobs=[], shadow="none")
        blur, animate = 0, False
    layers = ",".join(f"radial-gradient(circle at {pos}, rgba({c}) 0, transparent 45%)" for c, pos in t["blobs"])
    bg = f"{layers}, {t['base']}" if layers else t["base"]
    glass = f"backdrop-filter: blur({blur}px) saturate(160%); -webkit-backdrop-filter: blur({blur}px) saturate(160%);" if blur else ""
    anim = "background-size: 150% 150%; animation: oslide 22s ease-in-out infinite alternate;" if animate else ""
    font = f"font-family: {t['font']};" if t.get("font") else ""
    tx, mu, ac, at, bd = t["text"], t["muted"], t["accent"], t["acc_text"], t["border"]
    return f"""<style>
html {{ font-size: {font_px}px; }}
@keyframes oslide {{ 0% {{ background-position: 0% 0%; }} 100% {{ background-position: 100% 100%; }} }}
@media (prefers-reduced-motion: reduce) {{ .stApp {{ animation: none !important; }} }}
.stApp {{ background: {bg}; background-attachment: fixed; {anim} color: {tx}; {font} }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2, [data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] strong, [data-testid="stWidgetLabel"] p, [data-testid="stMetricLabel"] p, [data-testid="stMetricValue"],
h1, h2, h3, label, .stRadio label p, .stCheckbox label p, .stButton button p, .stDownloadButton button p,
[data-testid^="stBaseLinkButton"] p, .stTabs button p, [data-testid="stExpander"] summary p, [data-testid="stAlert"] p {{ color: {tx} !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {mu} !important; }}
input, textarea {{ color: {tx} !important; -webkit-text-fill-color: {tx} !important; }}
::placeholder {{ color: {mu} !important; opacity: 1 !important; -webkit-text-fill-color: {mu} !important; }}
[data-testid="stSidebar"] > div:first-child {{ background: {t['side']}; {glass} border-right: 1px solid {bd}; }}
[class*="st-key-card"], [data-testid="stMetric"], [data-testid="stExpander"], [data-testid="stForm"] {{
  background: {t['card']} !important; {glass} border: 1px solid {bd} !important; border-radius: {radius}px !important; box-shadow: {t['shadow']}; }}
[data-testid="stAlert"] {{ {glass} border: 1px solid {bd}; border-radius: {radius}px; }}
[data-testid="stMetric"] {{ padding: 10px 14px; }}
[data-testid="stExpander"] details {{ border: 0 !important; }}
.stTabs [data-baseweb="tab-list"] {{ background: {t['card']}; {glass} border: 1px solid {bd}; border-radius: 999px; padding: 4px; gap: 4px; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 999px; height: auto; padding: 8px 14px; }}
.stTabs [aria-selected="true"] {{ background: {ac}; }}
.stTabs [aria-selected="true"] p {{ color: {at} !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, [data-testid^="stBaseLinkButton"] {{
  border-radius: 999px !important; border: 1px solid {bd} !important; background: {t['card']}; {glass} box-shadow: {t['shadow']}; }}
button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{ background: {ac} !important; border: 0 !important; }}
button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{ color: {at} !important; }}
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {{ border-radius: 16px !important; background: {t['card']} !important; border-color: {bd} !important; }}
[data-baseweb="popover"] > div, [data-baseweb="menu"], ul[role="listbox"] {{ background: {t['pop']} !important; }}
ul[role="listbox"] li, [data-baseweb="menu"] li {{ color: {'#f4f7ff' if t['dark'] else '#0b1424'} !important; }}
[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"], [data-testid="stDataFrame"] {{
  border-radius: {radius}px; overflow: hidden; background: rgba(255,255,255,.95); padding: 6px; }}
</style>"""
