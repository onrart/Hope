import types

from futures import futures_orders as fo


class _FakeClient:
    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self._calls = 0

    def futures_create_order(self, **kwargs):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RuntimeError("transient")
        return {"ok": True, "request": kwargs}


def test_open_position_dry_run_has_id(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "x", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "y", prepend=False)
    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})
    out = fo.open_position("BTCUSDT", "BUY", 0.01, dry_run=True)
    assert out["dry_run"] is True
    assert "newClientOrderId" in out["payload"]


def test_open_position_retry(monkeypatch):
    # monkeypatch client
    fake = _FakeClient(fail_times=1)

    def _get_client():
        return fake

    monkeypatch.setattr(fo, "get_futures_client", _get_client)

    # monkeypatch filters to avoid external calls
    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})

    out = fo.open_position("BTCUSDT", "BUY", 0.01, dry_run=False)
    assert out["ok"] is True


def test_attach_bracket_dry_run_has_ids(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "x", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "y", prepend=False)
    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})
    out = fo.attach_bracket_tp_sl("BTCUSDT", "LONG", 100.0, 90.0, dry_run=True)
    assert out["tp"]["dry_run"] is True
    assert out["sl"]["dry_run"] is True


