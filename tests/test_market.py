# tests/test_market.py
import time
from market import MockClient, get_ohlcv, place_order


def test_mockclient_fetch_ohlcv_length():
    c = MockClient()
    rows = c.fetch_ohlcv("BTC/USDT", "1m", limit=10)
    assert isinstance(rows, list)
    assert len(rows) == 10
    # each row should be [ts, o, h, l, c, v]
    assert len(rows[0]) == 6


def test_get_ohlcv_wrapper():
    client = MockClient()
    rows = get_ohlcv(client, "BTC/USDT", "1m", limit=5)
    assert len(rows) == 5


def test_place_order_mock():
    client = MockClient()
    payload = {"symbol": "BTC/USDT", "side": "BUY", "amount": 0.001}
    res = place_order(client, payload, dry_run=True)
    assert isinstance(res, dict)
    assert res.get("mock") is True
    assert res["symbol"] == "BTC/USDT"
