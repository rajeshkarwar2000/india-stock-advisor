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
