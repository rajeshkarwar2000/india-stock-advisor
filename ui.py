"""HTML/CSS building blocks: Groww-style cards, tag chips, profit/loss colours and the refresh countdown.

Everything here returns plain strings (no Streamlit import) so it can be unit-tested.
HTML is built on one line: Streamlit's markdown turns indented lines into code blocks.
"""
FILES_VERSION = 22
import html as _h
import json as _json

UP, DOWN, AMBER, BLUE, GREY = "#00b386", "#eb5b3c", "#e59a00", "#5367ff", "#8a8fa3"
HZ_NAMES = {"1M": "1 Month", "6M": "6 Months", "1Y": "1 Year"}


def esc(x):
    return _h.escape(str(x), quote=True)


def _ok(x):
    return x is not None and x == x


def inr(x, d=2, sign=False):
    """₹ with Indian digit grouping (₹12,34,567.50). sign=True adds + for gains."""
    if not _ok(x):
        return "–"
    s = f"{abs(float(x)):.{d}f}"
    ip, _, fp = s.partition(".")
    if len(ip) > 3:
        head, tail, parts = ip[:-3], ip[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        ip = ",".join(parts + [tail])
    neg = float(x) < 0 and float(s) != 0
    return ("-" if neg else "+" if (sign and float(s) != 0) else "") + "₹" + ip + ("." + fp if d else "")


def pct(x, d=2, sign=True):
    if not _ok(x):
        return "–"
    neg = float(x) < 0 and round(abs(float(x)), d) != 0
    return ("-" if neg else "+" if (sign and round(abs(float(x)), d) != 0) else "") + f"{abs(float(x)):.{d}f}%"


def tone(x):
    if not _ok(x) or round(float(x), 2) == 0:
        return "flat"
    return "up" if x > 0 else "down"


def pnl_html(v, p=None, d=2):
    """Coloured P&L: +₹1,234.00 (+2.31%) in green, loss in red."""
    if not _ok(v):
        return '<span class="gw-flat">–</span>'
    txt = inr(v, d, sign=True) + (f" ({pct(p)})" if _ok(p) else "")
    return f'<span class="gw-{tone(v)}">{esc(txt)}</span>'


def pct_html(p, d=2):
    return f'<span class="gw-{tone(p)}">{esc(pct(p, d))}</span>' if _ok(p) else '<span class="gw-flat">–</span>'


def chip(text, kind="muted"):
    """kinds: buy | sell | hold | h (horizon) | risk | info | muted"""
    return f'<span class="gw-chip gw-c-{esc(kind)}">{esc(text)}</span>'


def chips(items):
    return "".join(chip(t, k) for t, k in items if t)


def hz_chip(h):
    return chip(h, "h") if h in HZ_NAMES else ""


def action_chip(sig):
    return chip(sig, {"BUY": "buy", "SELL": "sell"}.get(sig, "hold"))


def side_chip(side):
    return chip(side, "buy" if str(side).upper() == "BUY" else "sell")


def range_bar(sl, tg, price, avg=None):
    """Where the price sits between the stop-loss and the target."""
    if not (_ok(sl) and _ok(tg) and sl and tg and tg > sl and _ok(price)):
        return ""
    pos = lambda v: max(0.0, min(100.0, (v - sl) / (tg - sl) * 100))
    colour = UP if (not _ok(avg) or price >= avg) else DOWN
    mark = f'<i class="gw-avg" style="left:{pos(avg):.1f}%"></i>' if _ok(avg) and avg else ""
    return (f'<div class="gw-range"><div class="gw-track">{mark}<i class="gw-dot" style="left:{pos(price):.1f}%;background:{colour}"></i></div>'
            f'<div class="gw-rl"><span class="gw-down">Stop-loss {esc(inr(sl))}</span><span class="gw-up">Target {esc(inr(tg))}</span></div></div>')


def _kv(label, value_html):
    return f'<div class="gw-kv"><span class="gw-k">{esc(label)}</span><span class="gw-v">{value_html}</span></div>'


def live_bar_html(is_open, idx, stamp):
    """Market status + Nifty/Sensex ticker line. The stamp text is watched by the countdown to restart it."""
    st = chip("Market open", "buy") if is_open else chip("Market closed", "muted")
    bits = "".join(f'<span class="gw-idx"><b>{esc(k)}</b> {esc(f"{v:,.2f}")} {pct_html(d)}</span>' for k, (v, d) in (idx or {}).items())
    return f'<div class="gw-live">{st}{bits}<span class="gw-sub gw-stamp-mk">Updated {esc(stamp)}</span></div>'


def summary_html(perf, day, day_pct, n_hold, stamp="", plain=False, part="all"):
    """Portfolio hero (current value, returns, 1-day returns, invested, realised, cash).
    plain=True: no frame of its own. part: "top" = title + big value, "rest" = the stats, "stamp" = the small update time, "all" = everything."""
    big = f'<div class="gw-big">{esc(inr(perf["current"], 2))}</div>'
    grid = (_kv("Invested", esc(inr(perf["invested"])))
            + _kv("Total returns", pnl_html(perf["unrealised"], perf["unrealised_pct"]))
            + _kv("1D returns", pnl_html(day, day_pct))
            + _kv("Realised P&L", pnl_html(perf["realised"], perf["realised_pct"] if perf["closed"] else None))
            + _kv("Virtual cash", esc(inr(perf["cash"])))
            + _kv("Net worth", f'{esc(inr(perf["net"]))} {pct_html(perf["total_pct"])}'))
    st_ = f'<div class="gw-sub gw-stamp-pf">Updated {esc(stamp)}</div>' if stamp else ""
    top = f'<div class="gw-k">Current value · {n_hold} holding{"s" if n_hold != 1 else ""}</div>{big}'
    rest = f'<div class="gw-grid gw-grid-hero">{grid}</div>'
    stamp_html = f'<div class="gw-sub gw-stamp-pf" style="text-align:right;white-space:nowrap;font-size:.7rem;margin-bottom:2px">Updated {esc(stamp)}</div>' if stamp else ""
    inner = {"top": top, "rest": rest, "stamp": stamp_html}.get(part, top + rest + st_)
    return inner if (plain or part != "all") else f'<div class="gw-card gw-hero">{inner}</div>'


def holding_html(h):
    """One portfolio card: name, tags, LTP and day change, buy price vs current price, returns and the stop/target bar."""
    tags = chips([(h.get("horizon"), "h")] if h.get("horizon") in HZ_NAMES else []) + action_chip(h["signal"]) \
        + chips([("No stop-loss", "sell")] if not h.get("stop") else []) + chips([("Intraday", "info")] if h.get("product") == "INTRADAY" else []) + chips(h.get("tags", [])[:3])
    sub = f'{esc(h["name"])} · ' if h.get("name") else ""
    return (f'<div class="gw-top"><div><div class="gw-sym">{esc(h["symbol"])}</div>'
            f'<div class="gw-sub">{sub}{h["qty"]} share{"s" if h["qty"] != 1 else ""}</div></div>'
            f'<div class="gw-right"><div class="gw-px">{esc(inr(h["ltp"]))}</div><div class="gw-sub">{pct_html(h["day_pct"])} today</div></div></div>'
            f'<div class="gw-chips">{tags}</div>'
            f'<div class="gw-grid">{_kv("Buy price (avg)", esc(inr(h["avg"])))}{_kv("Current price", esc(inr(h["ltp"])))}'
            f'{_kv("Invested", esc(inr(h["invested"])))}{_kv("Current value", esc(inr(h["current"])))}</div>'
            f'<div class="gw-ret"><span class="gw-k">Returns</span>{pnl_html(h["pnl"], h["pnl_pct"])}</div>'
            f'<div class="gw-ret"><span class="gw-k">Today</span>{pnl_html(h["day_pnl"], h["day_pct"])}</div>'
            f'{range_bar(h.get("stop"), h.get("target"), h["ltp"], h["avg"])}'
            f'<div class="gw-sub gw-why">{esc(h.get("reason", ""))}</div>')


def stock_head_html(sym, name, price, day_pct, tags):
    """Header used on idea, scan, search and watchlist cards: name, tags, current price and day change."""
    return (f'<div class="gw-top"><div><div class="gw-sym">{esc(sym)}</div><div class="gw-sub">{esc(name or "")}</div></div>'
            f'<div class="gw-right"><div class="gw-px">{esc(inr(price))}</div>'
            f'<div class="gw-sub">{pct_html(day_pct) if _ok(day_pct) else ""}{" today" if _ok(day_pct) else "current price"}</div></div></div>'
            f'<div class="gw-chips">{tags}</div>')


def levels_html(price, entry, stop, target):
    """Entry (buy price), stop-loss and target with the distance from the current price."""
    away = lambda v: pct_html((v / price - 1) * 100, 1) if _ok(v) and _ok(price) and price else ""
    cell = lambda lab, v, cls: (f'<div class="gw-kv"><span class="gw-k">{lab}</span><span class="gw-v {cls}">{esc(inr(v))}</span>'
                                f'<span class="gw-sub">{away(v)}</span></div>')
    return f'<div class="gw-grid">{cell("Buy price", entry, "")}{cell("Stop-loss", stop, "gw-down")}{cell("Target", target, "gw-up")}</div>'


def dialog_head_html(sym, name, price, day_pct, held=0, avg=None):
    own = f'<div class="gw-sub">You hold {held} @ {esc(inr(avg))}</div>' if held else ""
    return (f'<div class="gw-top"><div><div class="gw-sym">{esc(sym)}</div><div class="gw-sub">{esc(name or "")}</div>{own}</div>'
            f'<div class="gw-right"><div class="gw-px">{esc(inr(price))}</div><div class="gw-sub">{pct_html(day_pct)} today</div></div></div>')


def order_box_html(rows):
    """Small summary box in the buy/sell windows. rows: list of (label, html)."""
    return '<div class="gw-box">' + "".join(_kv(k, v) for k, v in rows) + "</div>"


_WATCH_JS = """function stamp(){try{const e=window.parent.document.querySelector('.%s');return e?e.textContent:null}catch(x){return null}}"""

def countdown_html(seconds, stamp_class, label="Next refresh in"):
    """Display-only countdown. The real refresh is done by Streamlit (a fragment with run_every); this restarts
    whenever the watched stamp text (class `stamp_class`) changes, so it stays in step with the data."""
    if not seconds:
        return '<div style="font:600 13px system-ui,sans-serif;color:#8a8fa3;padding:6px 0">Auto-refresh is off. Tap the refresh button.</div>'
    return f"""<style>body{{margin:0;overflow:hidden}}</style><div style="font:600 13px system-ui,sans-serif;color:#6b7083;display:flex;align-items:center;gap:10px;padding:6px 0">
<span style="width:9px;height:9px;border-radius:50%;background:{UP};flex:none"></span>
<span id="t" style="white-space:nowrap">{esc(label)} {int(seconds)}s</span>
<div style="flex:1;height:5px;background:#e3e5ea;border-radius:5px;overflow:hidden"><div id="b" style="height:5px;width:100%;background:{UP}"></div></div></div>
<script>{_WATCH_JS % stamp_class}
const total={int(seconds)}; let end=Date.now()+total*1000, last=null; const T=document.getElementById('t'), B=document.getElementById('b');
setInterval(()=>{{const s=stamp(); if(s!==last){{last=s; end=Date.now()+total*1000}}
 let l=Math.max(0,Math.ceil((end-Date.now())/1000)); if(l<=0){{end=Date.now()+total*1000; l=total}}
 T.textContent={_json.dumps(label)}+' '+l+'s'; B.style.width=(l/total*100)+'%';}},250);
</script>"""


def dial_html(seconds, stamp_class, target, compact=True):
    """Small countdown ring with its own round refresh button beside it. Tapping the button (or the ring) presses the app's
    hidden Refresh button whose key is `target`; the icon spins until fresh data arrives. The countdown restarts when
    the watched stamp text changes."""
    C = 238.76
    return f"""<style>body{{margin:0;overflow:hidden}} @keyframes sp{{to{{transform:rotate(360deg)}}}} .spin{{animation:sp .8s linear infinite}}</style>
<div id="w" style="display:flex;align-items:center;justify-content:flex-end;gap:6px;font-family:system-ui,sans-serif;-webkit-tap-highlight-color:transparent;user-select:none">
<svg width="46" height="46" viewBox="0 0 92 92" style="cursor:pointer"><circle cx="46" cy="46" r="38" fill="none" stroke="#e3e5ea" stroke-width="9"/>
<circle id="r" cx="46" cy="46" r="38" fill="none" stroke="{UP}" stroke-width="9" stroke-linecap="round" stroke-dasharray="{C}" stroke-dashoffset="0" transform="rotate(-90 46 46)"/>
<text id="n" x="46" y="58" text-anchor="middle" font-size="34" font-weight="700" fill="#4b4f60">{int(seconds) if seconds else "–"}</text></svg>
<div id="btn" role="button" title="Refresh now" style="width:36px;height:36px;border-radius:50%;background:{UP}1f;border:1.5px solid {UP};color:{UP};display:flex;align-items:center;justify-content:center;cursor:pointer">
<span id="ic" style="font-size:21px;line-height:1;display:block">↻</span></div></div>
<script>{_WATCH_JS % stamp_class}
const total={int(seconds or 0)}, C={C}, R=document.getElementById('r'), IC=document.getElementById('ic'), N=document.getElementById('n'); let end=Date.now()+total*1000, last=null, busy=0;
function press(){{try{{const b=window.parent.document.querySelector('.st-key-{esc(target)} button'); if(b){{busy=Date.now(); IC.classList.add('spin'); b.click();}}}}catch(e){{}}}}
document.getElementById('btn').addEventListener('click', press); document.querySelector('svg').addEventListener('click', press);
setInterval(()=>{{const s=stamp(); if(s!==last){{last=s; end=Date.now()+total*1000; busy=0; IC.classList.remove('spin')}}
 if(busy && Date.now()-busy>9000){{busy=0; IC.classList.remove('spin')}}
 if(!total) return;
 let l=Math.max(0,Math.ceil((end-Date.now())/1000)); if(l<=0){{end=Date.now()+total*1000; l=total}}
 N.textContent=busy?'…':l; R.style.strokeDashoffset=C*(1-l/total);}},250);
</script>"""


GROWW_CSS = f"""<style>
.gw-up{{color:{UP}!important;font-weight:600}} .gw-down{{color:{DOWN}!important;font-weight:600}} .gw-flat{{opacity:.6}}
.gw-card{{border-radius:14px;padding:14px 16px;margin-bottom:10px}}
.gw-hero{{background:linear-gradient(135deg,{UP}14,{BLUE}10);border:1px solid {UP}33}}
.gw-big{{font-size:2rem;font-weight:700;line-height:1.15;margin:2px 0 10px}}
.gw-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}}
.gw-sym{{font-size:1.12rem;font-weight:700;line-height:1.2}}
.gw-sub{{font-size:.8rem;opacity:.68}} .gw-why{{margin-top:6px}}
.gw-right{{text-align:right}} .gw-px{{font-size:1.12rem;font-weight:700}}
.gw-chips{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 6px}}
.gw-chip{{display:inline-block;font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}}
.gw-c-buy{{color:{UP};background:{UP}1f}} .gw-c-sell{{color:{DOWN};background:{DOWN}1f}}
.gw-c-hold{{color:{AMBER};background:{AMBER}22}} .gw-c-h{{color:{BLUE};background:{BLUE}1c}}
.gw-c-risk{{color:#d9692c;background:#d9692c1f}} .gw-c-info{{color:#2a8bd8;background:#2a8bd81f}}
.gw-c-muted{{color:{GREY};background:{GREY}26}}
.gw-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px 14px;margin:8px 0}}
.gw-kv{{display:flex;flex-direction:column;gap:1px}} .gw-k{{font-size:.76rem;opacity:.65}} .gw-v{{font-size:.95rem;font-weight:600}}
.gw-ret{{display:flex;justify-content:space-between;align-items:baseline;border-top:1px solid {GREY}33;padding:6px 0 0;margin-top:4px}}
.gw-range{{margin-top:10px}} .gw-track{{position:relative;height:6px;border-radius:6px;background:linear-gradient(90deg,{DOWN}55,{GREY}33,{UP}55)}}
.gw-dot{{position:absolute;top:-4px;width:14px;height:14px;margin-left:-7px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px #0004}}
.gw-avg{{position:absolute;top:-3px;width:2px;height:12px;background:{GREY}}}
.gw-rl{{display:flex;justify-content:space-between;font-size:.74rem;margin-top:6px}}
.gw-live{{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:.88rem;padding:6px 2px}}
.gw-box{{border:1px solid {GREY}40;border-radius:12px;padding:10px 12px;margin:10px 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}}
[class*="st-key-sell"] button{{color:{DOWN}!important;border-color:{DOWN}!important}}
[class*="st-key-sell"] button p{{color:{DOWN}!important}}
.st-key-exec_sell button{{background:{DOWN}!important;border:0!important}}
.st-key-exec_sell button p{{color:#fff!important}}
.st-key-exec_buy button{{background:{UP}!important;border:0!important}}
.st-key-exec_buy button p{{color:#fff!important}}
[role="tablist"]{{position:sticky;top:2.6rem;z-index:99;background:rgba(255,255,255,.42)!important;backdrop-filter:blur(22px) saturate(190%)!important;-webkit-backdrop-filter:blur(22px) saturate(190%)!important;border:1px solid rgba(255,255,255,.85)!important;border-radius:999px!important;padding:4px!important;gap:2px!important;box-shadow:inset 0 1.5px 1px rgba(255,255,255,.95),inset 0 -1.5px 2px rgba(0,0,0,.06),0 8px 22px rgba(40,60,110,.16)!important}}
[role="tablist"] button,[role="tablist"] [role="tab"]{{flex:1 1 auto;justify-content:center;white-space:nowrap;border-radius:999px!important;padding:8px 8px!important;background:transparent!important;border:1.5px solid transparent!important;box-shadow:none!important;height:auto!important}}
[role="tablist"] button *,[role="tablist"] [role="tab"] *{{color:#5f6270!important;font-weight:600!important;font-size:.9rem!important;white-space:nowrap}}
[role="tablist"] [aria-selected="true"]{{background:rgba(110,115,130,.22)!important;border:1.5px solid transparent!important;box-shadow:inset 0 1.5px 2px rgba(255,255,255,.75),inset 0 -1px 4px rgba(0,0,0,.10)!important}}
[role="tablist"] [aria-selected="true"] *{{color:{UP}!important;font-weight:700!important}}
[role="tablist"] div:empty,[role="tablist"] [data-baseweb*="highlight"],[role="tablist"] [data-baseweb*="border"],[role="tablist"] [role="tab"]::before,[role="tablist"] [role="tab"]::after,[role="tablist"] button::before,[role="tablist"] button::after{{display:none!important;content:none!important}}
[role="tabpanel"] [role="tablist"]{{position:static!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important;box-shadow:none!important;background:transparent!important;border:0!important;border-radius:0!important;padding:2px 0!important;gap:4px!important}}
[role="tabpanel"] [role="tablist"] button,[role="tabpanel"] [role="tablist"] [role="tab"]{{flex:none;border-radius:999px!important;padding:6px 12px!important;background:transparent!important;box-shadow:none!important;border:1.5px solid transparent!important;height:auto!important}}
[role="tabpanel"] [role="tablist"] button *,[role="tabpanel"] [role="tablist"] [role="tab"] *{{color:inherit!important;font-weight:500!important;font-size:.88rem!important;white-space:nowrap}}
[role="tabpanel"] [role="tablist"] [aria-selected="true"]{{background:rgba(110,115,130,.16)!important;border:1.5px solid transparent!important;box-shadow:inset 0 1px 2px rgba(255,255,255,.6)!important}}
[role="tabpanel"] [role="tablist"] [aria-selected="true"] *{{color:{UP}!important;font-weight:700!important}}
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],#MainMenu,footer{{display:none!important}}
header[data-testid="stHeader"]{{height:2.4rem!important;min-height:0!important;background:transparent!important}}
.st-key-pfhero{{background:linear-gradient(135deg,{UP}14,{BLUE}10)!important;border:1px solid {UP}33!important;border-radius:14px!important;padding:6px 10px!important}}
.st-key-pfhero [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;gap:4px!important;align-items:center!important}}
.st-key-pfhero [data-testid="stColumn"],.st-key-pfhero [data-testid="column"]{{min-width:0!important}}
.st-key-pfhero [data-testid="stColumn"]:not(:first-child),.st-key-pfhero [data-testid="column"]:not(:first-child){{flex:0 0 112px!important;width:112px!important}}
.gw-grid-hero{{grid-template-columns:repeat(auto-fit,minmax(104px,1fr))}}
.st-key-pf_refresh{{display:none!important}}
[data-stale="true"],.stale-element{{opacity:1!important;transition:none!important}}
.st-key-open_settings button{{width:46px!important;min-height:46px!important;padding:0!important;border-radius:50%!important;line-height:1!important}}
.st-key-open_settings button p{{font-size:1.65rem!important;line-height:1!important;margin:0!important}}
.st-key-isa_restore{{position:absolute!important;left:-9999px!important;height:0!important;overflow:hidden!important}}
[data-testid="stBaseButton-pills"],[data-testid="stBaseButton-segmented_control"]{{border-radius:999px!important}}
[data-testid="stBaseButton-pillsActive"],[data-testid="stBaseButton-segmented_controlActive"]{{border-radius:999px!important;background:{UP}1f!important;border-color:{UP}!important;color:{UP}!important;font-weight:700!important}}
[data-testid="stBaseButton-pillsActive"] *,[data-testid="stBaseButton-segmented_controlActive"] *{{color:{UP}!important}}
.block-container,[data-testid="stMainBlockContainer"]{{padding-top:2.6rem!important;padding-bottom:3rem!important}}
[class*="st-key-card_box"]{{background:rgba(120,124,140,.07)!important;border-left:4px solid {UP}!important}}
.gw-boxh{{font-size:1.02rem;font-weight:700;margin-bottom:6px}} .gw-boxh span{{display:block;font-size:.76rem;font-weight:400;opacity:.65;margin-top:1px}}
.gw-title{{font-size:1.2rem;font-weight:700;line-height:1.2;margin-bottom:2px}} .gw-title span{{display:block;font-size:.72rem;font-weight:400;opacity:.62;margin-top:2px}}
.st-key-headbar [data-testid="stHorizontalBlock"],.st-key-topbar [data-testid="stHorizontalBlock"],.st-key-pfbar [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;gap:6px!important;align-items:center!important}}
.st-key-headbar [data-testid="stColumn"],.st-key-topbar [data-testid="stColumn"],.st-key-pfbar [data-testid="stColumn"],.st-key-topbar [data-testid="column"],.st-key-pfbar [data-testid="column"]{{min-width:0!important}}
.st-key-headbar [data-testid="stColumn"]:not(:first-child){{flex:0 0 52px!important;width:52px!important}}
.st-key-topbar [data-testid="stColumn"]:not(:first-child),.st-key-pfbar [data-testid="stColumn"]:not(:first-child),.st-key-topbar [data-testid="column"]:not(:first-child),.st-key-pfbar [data-testid="column"]:not(:first-child){{flex:0 0 auto!important;width:auto!important}}
.st-key-live_refresh button,.st-key-pf_refresh button{{border-radius:999px!important;padding:2px 12px!important;min-height:2.2rem!important}}
</style>"""
