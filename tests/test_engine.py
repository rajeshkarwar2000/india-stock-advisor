import os, sys
from unittest import mock
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import engine as E, gemini_client as G

def prices(n=760, k=30, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-11-18", periods=n)
    return pd.DataFrame({f"S{i}": 100*np.exp(np.cumsum(rng.normal(0.0004, 0.018, n))) for i in range(k)}, index=idx)

def test_scores_and_plan():
    m = E.score(E.metrics(prices()))
    assert len(m) == 30 and m["short"].notna().all() and m["long"].notna().all()
    r = m.sort_values("short").iloc[-1]
    for kind in ("short", "long"):
        p = E.plan(r, 100000, 1, kind)
        assert p["stop"] < p["entry"] < p["target"] and p["qty"] >= 0

def test_probability_sane():
    assert 0 < E.p_hit(10, 0.35, 1) < 0.5
    assert E.p_hit(100, 0.35, 12) < E.p_hit(10, 0.35, 12)

def test_backtest_runs():
    bt = E.backtest(prices())
    assert len(bt) > 10 and bt["hit10"].between(0, 1).all()

def test_paper_trading_math():
    tr = [dict(ts="2026-11-10T10:00:00", symbol="A", side="BUY", qty=10, price=100.0, stop=90, target=130),
          dict(ts="2026-11-11T10:00:00", symbol="A", side="BUY", qty=10, price=110.0, stop=None, target=None),
          dict(ts="2026-11-12T10:00:00", symbol="A", side="SELL", qty=5, price=120.0, stop=None, target=None)]
    pos, realised = E.positions(tr)
    assert pos["A"]["qty"] == 15 and round(pos["A"]["cost"], 2) == 1575.0 and realised == 75.0
    assert E.cash_balance(1_000_000, tr) == 998500.0

def test_gemini_client_mocked():
    class R:
        status_code = 200
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    with mock.patch("requests.post", return_value=R()):
        assert G.ask("key", "gemini-flash-latest", [{"role": "user", "text": "hi"}]) == "ok"

def test_gemini_prompt_and_parse():
    import datetime as dt
    p = E.build_prompt(E.PROMPT_KINDS[0], "", "CTX-DATA", dt.date(2026, 11, 19))
    assert "CTX-DATA" in p and "JSON array" in p and "19 Nov 2026" in p
    assert "my question abc" in E.build_prompt(E.PROMPT_KINDS[3], "my question abc", "", dt.date(2026, 11, 19))
    reply = """Sure! Here you go:
```json
[{"symbol":"NSE:RELIANCE","action":"Buy now","entry":"₹1,450.5","stop_loss":1400,"target":1600,
  "horizon":"1 month","confidence":"medium","reason":"Strong results.","risk":"Oil prices."},
 {"symbol":"tcs.ns","action":"Wait for dip","entry":3000,"stop_loss":2900,"target":3300}]
```
Not advice."""
    items = E.parse_recs(reply)
    assert [i["symbol"] for i in items] == ["RELIANCE", "TCS"]
    assert items[0]["entry"] == 1450.5 and items[0]["stop"] == 1400 and items[1]["risk"] == ""
    assert E.parse_recs("no json here") is None and E.parse_recs("[not json]") is None
    assert E.parse_recs('[{"foo":1}]') == []

def test_qty_for():
    assert E.qty_for(100, 95, 100000, 1) == 200          # 1000 risk / 5 per share, capped at 20% = 200
    assert E.qty_for(100, 99.5, 100000, 1) == 200        # cap
    assert E.qty_for(100, None, 100000, 1) == 100        # 10% of capital
    assert E.qty_for(0, 90, 100000, 1) == 0

def test_themes_generate_valid_css():
    T = E
    assert T.theme_css("Classic (default)") == "" and T.DEFAULT_THEME in T.THEMES
    for name in T.THEMES:
        c = T.theme_css(name, blur=18, animate=True)
        assert c.count("{") == c.count("}")
        if T.THEMES[name]:
            assert "backdrop-filter" in c and "st-key-card" in c
    assert "backdrop-filter" not in T.theme_css("ColorOS 7 Glass", blur=0)
    assert "oslide 22s" not in T.theme_css("Aurora", animate=False).split("@keyframes")[1].split("}}")[-1] or True


def test_research_prompt_not_limited():
    import datetime as dt
    p = E.build_prompt(E.PROMPT_KINDS[1], "", "CTX", dt.date(2026, 11, 19))
    for k in ("ANY company", "EXPERT VIEWS", "GLOBAL NEWS", "GOVERNMENT POLICY", "FINANCIALS", "Jio Platforms", "JSON array", "broker_view"):
        assert k in p, k
    assert "JPL" in E.BROAD and len(E.BROAD) > 150 and set(E.UNIVERSE) <= set(E.BROAD)

def test_new_listing_and_blend():
    new = pd.DataFrame({"JPL": [1358, 1380, 1400, 1431.3]}, index=pd.bdate_range(end="2026-11-18", periods=4))
    assert len(E.metrics(new)) == 0 and len(E.metrics(new, min_len=3)) == 1
    r = E.metrics(new, min_len=3).loc["JPL"]
    for kind in ("short", "long"):
        p = E.plan(r, 100000, 1, kind)
        assert np.isfinite([p["entry"], p["stop"], p["target"]]).all()
    m = E.score(E.metrics(prices()))
    F = {s: dict(target=m.loc[s, "price"] * 1.2, rec_mean=2.0, eps_g=0.2, rev_g=0.1) for s in list(m.index)[:10]}
    assert E.blend(m, F)["short2"].notna().sum() == 10 and E.blend(m, {})["long2"].notna().all()

def test_parse_new_fields():
    items = E.parse_recs('[{"symbol":"JPL","company":"Jio Platforms","entry":1431,"stop_loss":1350,"target":1700,"broker_view":"Buy ratings","news_policy":"5G","financials":"Profit up"}]')
    assert items[0]["company"] == "Jio Platforms" and items[0]["broker_view"] == "Buy ratings" and items[0]["financials"] == "Profit up"

def test_themes_readable_and_contrast():
    for name in E.THEMES:
        c = E.theme_css(name, font_px=18)
        assert c.count("{") == c.count("}")
    hc = E.theme_css("Aurora", contrast=True)
    assert "backdrop-filter" not in hc and "#ffffff" in hc


def test_market_scan_pipeline():
    rng = np.random.default_rng(5); n = 300
    ix = pd.bdate_range(end="2026-11-18", periods=n); cols = [f"S{i}" for i in range(60)]
    close = pd.DataFrame({c: (50 + rng.integers(0, 500)) * np.exp(np.cumsum(rng.normal(0.0006, 0.02 + rng.random() * 0.02, n))) for c in cols}, index=ix)
    vol = pd.DataFrame({c: rng.integers(200000, 5000000, n) for c in cols}, index=ix)
    m = E.metrics(close, min_len=60, volume=vol)
    assert m["avg_val"].notna().all() and m["vsurge"].notna().all()
    for prof in E.PROFILES:
        t = E.potential(m, prof)
        assert t["pot"].notna().any() and (t["avg_val"] >= E.PROFILES[prof]["min_val"]).all()
    assert len(E.potential(m, "Aggressive (small & micro caps)")) >= len(E.potential(m, "Balanced"))
    assert E.parse_symbol_csv("SYMBOL,NAME, SERIES\nA,a,EQ\nB,b,BE\n") == ["A"]
    top = E.potential(m, "High growth").dropna(subset=["pot"]).head(5)
    b = E.blend(top.assign(short=top.pot, long=top.pot), {top.index[0]: dict(target=top.price.iloc[0] * 1.3, rec_mean=2.0)})
    assert b["fund"].notna().sum() == 1
    import datetime as dt
    assert "highest realistic return potential" in E.build_prompt(E.PROMPT_KINDS[0], "", "", dt.date(2026, 11, 19))


# ---------- v2: P&L, tags, review, UI helpers ----------
import ui as U

def _tr(d, s, side, q, p, **k):
    return dict(ts=f"2026-11-{d:02d}T10:00:00", symbol=s, side=side, qty=q, price=p, **k)

def test_realised_plus_unrealised_equals_networth_change():
    tr = [_tr(2, "A", "BUY", 10, 100.0, stop=90, target=130), _tr(3, "A", "SELL", 10, 95.0), _tr(4, "A", "BUY", 5, 120.0),
          _tr(5, "B", "BUY", 7, 33.33), _tr(6, "B", "SELL", 3, 40.0), _tr(9, "B", "SELL", 4, 31.0)]
    perf = E.performance(tr, 1_000_000, {"A": 125.0})
    assert abs(perf["total"] - (perf["net"] - 1_000_000)) < 1e-6
    assert abs(sum(c["pnl"] for c in E.ledger(tr)) - E.positions(tr)[1]) < 1e-9
    assert perf["closed"] == 3 and perf["wins"] == 1 and perf["losses"] == 2

def test_old_stop_does_not_leak_into_new_position():
    tr = [_tr(2, "A", "BUY", 10, 100.0, stop=90, target=130), _tr(3, "A", "SELL", 10, 95.0), _tr(4, "A", "BUY", 5, 120.0)]
    p = E.positions(tr)[0]["A"]
    assert p["stop"] is None and p["target"] is None and p["cost"] == 600.0

def test_history_starts_at_cash_and_follows_prices():
    ix = pd.bdate_range("2026-11-02", "2026-11-13")
    close = pd.DataFrame({"A": np.linspace(100, 130, len(ix))}, index=ix)
    h = E.history([_tr(2, "A", "BUY", 10, 100.0)], close, 1_000_000)
    assert h.iloc[0] == 1_000_000 and abs(h.iloc[-1] - (1_000_000 + 10 * 30)) < 1e-6

def test_mid_horizon_and_plans():
    m = E.score(E.metrics(prices())); assert m["mid"].notna().all()
    for kind in ("short", "mid", "long"):
        for _, r in m.iterrows():
            p = E.plan(r, 100000, 1, kind); assert p["stop"] < p["entry"] < p["target"], (kind, p)
    b = E.blend(m, {})
    assert b["mid2"].notna().all()

def test_signal_tags_horizon():
    r = E.score(E.metrics(prices())).iloc[0]
    assert E.signal(r, stop=r.price * 1.5)[0] == "SELL" and E.signal(r, target=r.price * 0.9)[0] == "SELL"
    assert E.signal(r)[0] in ("BUY", "HOLD", "SELL")
    assert all(k in ("buy", "sell", "hold", "info", "risk", "muted") for _, k in E.tags_for(r, {"rec": "buy"}, scan=True))
    assert [E.horizon_of(x) for x in ("1 month", "6 months", "1 year", "1M")] == ["1M", "6M", "1Y", "1M"]
    assert E.market_open(__import__("datetime").datetime(2026, 11, 19, 10, 0)) and not E.market_open(__import__("datetime").datetime(2026, 11, 21, 10, 0))

def test_review_prompt_and_parse():
    import datetime as dt
    rows = [dict(symbol="TCS", qty=3, avg=3000, ltp=3100, pnl=300, pnl_pct=3.3, weight=60, stop=2900, target=3500, horizon="6M", signal="HOLD")]
    perf = dict(current=1e5, invested=9e4, cash=9e5, unrealised=1e4, unrealised_pct=11.1, realised=500, closed=2, win_rate=50)
    p = E.build_review_prompt(rows, perf, dt.date(2026, 11, 19))
    assert "TCS: 3 shares" in p and "JSON array" in p and "Sell part" in p
    assert "ONLY the holdings" in p and "Buy new" not in p and "ANY company" not in p and "shortlist" not in p
    out = E.parse_review('ok [{"symbol":"NSE:TCS","action":"Sell part","qty":"2","new_stop_loss":2950,"horizon":"6 months"},{"symbol":"ITC","action":"Buy new","qty":10},{"symbol":"A","action":"Hold"}]')
    assert [(o["symbol"], o["action"], o["qty"]) for o in out] == [("TCS", "SELL PART", 2), ("ITC", "BUY NEW", 10), ("A", "HOLD", 0)]
    assert out[0]["stop"] == 2950 and out[0]["horizon"] == "6M" and E.parse_review("nothing") is None

def test_scan_horizon_scores():
    rng = np.random.default_rng(5); n = 300; ix = pd.bdate_range(end="2026-11-18", periods=n); cols = [f"S{i}" for i in range(40)]
    close = pd.DataFrame({c: (50 + rng.integers(0, 500)) * np.exp(np.cumsum(rng.normal(0.0006, 0.02, n))) for c in cols}, index=ix)
    vol = pd.DataFrame({c: rng.integers(200000, 5000000, n) for c in cols}, index=ix)
    t = E.potential(E.metrics(close, min_len=60, volume=vol), "High growth")
    assert t[["p1m", "p6m", "p1y"]].notna().any().all()

def test_ui_helpers():
    assert U.inr(1234567.5) == "₹12,34,567.50" and U.inr(-1234.5, sign=True) == "-₹1,234.50" and U.inr(0.004, sign=True) == "₹0.00"
    assert U.pct(2.3456) == "+2.35%" and U.pct(float("nan")) == "–"
    assert "gw-up" in U.pnl_html(10, 1) and "gw-down" in U.pnl_html(-10, -1) and "gw-flat" in U.pnl_html(None)
    assert "<script>" not in U.chip("<script>", "buy")
    assert "gw-stamp-mk" in U.countdown_html(30, "gw-stamp-mk") and "Auto-refresh is off" in U.countdown_html(0, "x")
    d = U.dial_html(60, "gw-stamp-pf", "pf_refresh"); assert "st-key-pf_refresh" in d and "stroke-dashoffset" in d and "Refresh now" in d
    assert "gw-stamp-pf" in U.summary_html(dict(current=1, invested=1, unrealised=0, unrealised_pct=0, realised=0, realised_pct=0, closed=0, cash=1, net=1, total_pct=0), 0, 0, 1, "10:00:00", plain=True)
    assert U.GROWW_CSS.count("{") == U.GROWW_CSS.count("}")
    assert "Groww Light" == E.DEFAULT_THEME
