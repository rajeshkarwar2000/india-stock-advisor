import os, sys
from unittest import mock
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import engine as E, gemini_client as G, themes as T

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

def test_themes_generate_css():
    assert "ColorOS 7 Glass" in T.THEMES and T.DEFAULT in T.THEMES
    for name, t in T.THEMES.items():
        out = T.css(name)
        if t.get("css") is False:
            assert out == ""
        else:
            assert out.startswith("<style>") and out.endswith("</style>") and "__" not in out and "\n" not in out
            assert t["accent"] in out and "backdrop-filter" in out
    assert "--blur:7px" in T.css("ColorOS 7 Glass", blur=7) and "--r:5px" in T.css("ColorOS 7 Glass", radius=5)
    assert "animation:osdrift" not in T.css("ColorOS 7 Glass", animate=False)
    assert "invert" in T.css("Aurora Dark") and "invert" not in T.css("ColorOS 7 Glass")

def test_universe_csv_and_any_company_prompt():
    csv_text = "Company Name,Industry,Symbol,Series,ISIN Code\nA Ltd,X,AAA,EQ,1\nB Ltd,X,bbb ,EQ,2\nD,X,DUMMYXYZ,EQ,3\nA again,X,AAA,EQ,4\n"
    assert E.parse_universe_csv(csv_text) == ["AAA", "BBB"]
    assert E.parse_universe_csv("garbage") == [] and E.parse_universe_csv("") == []
    assert len(E.EXTENDED) > len(E.UNIVERSE) > 50 and len(set(E.EXTENDED)) == len(E.EXTENDED)
    import datetime as dt
    p = E.build_prompt(E.PROMPT_KINDS[1], "", "CTX", dt.date(2026, 11, 19), n=8)
    assert "ANY NSE-listed company" in p and "up to 8 objects" in p
    assert "ANY NSE/BSE-listed company" in G.SYSTEM
