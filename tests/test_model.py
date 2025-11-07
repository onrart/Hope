# tests/test_model.py
import os
from model_decide_gemini import query_gemini


def make_ohlcv_uptrend():
    # generate two rows: prev close small, last close bigger than prev + 1
    now = 1_000_000
    return [
        [now, 100, 101, 99, 100, 1],
        [now + 60000, 101, 102, 100, 103, 1],  # last > prev + 1 => BUY
    ]


def make_ohlcv_downtrend():
    now = 1_000_000
    return [
        [now, 100, 101, 99, 105, 1],
        [now + 60000, 101, 102, 100, 103, 1],  # last < prev - 1? here not, adjust
    ]


def test_query_gemini_buy():
    ohlcv = make_ohlcv_uptrend()
    res = query_gemini("BTC/USDT", "1m", ohlcv, dry_run=True)
    assert isinstance(res, dict)
    assert res["action"] in ("BUY", "SELL", "HOLD")
    # With our uptrend fixture should be BUY
    assert res["action"] == "BUY"
    assert 0.0 <= float(res["confidence"]) <= 1.0


def test_query_gemini_hold_on_flat():
    # craft flat data so HOLD triggered
    ohlcv = [
        [1, 100, 101, 99, 100, 1],
        [2, 100.1, 101.1, 99.1, 100.05, 1],
    ]
    res = query_gemini("BTC/USDT", "1m", ohlcv, dry_run=True)
    assert res["action"] == "HOLD"
