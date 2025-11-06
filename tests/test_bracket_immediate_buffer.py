from futures import futures_orders as fo


class _FakeClient:
    def __init__(self, mark_price: float):
        self._mark_price = mark_price
        self._captured = []

    def futures_mark_price(self, symbol: str):
        return {"symbol": symbol, "markPrice": str(self._mark_price)}

    def futures_create_order(self, **kwargs):
        self._captured.append(kwargs)
        return {"ok": True, "request": kwargs}


def test_tp_buffer_long_avoids_immediate_trigger(monkeypatch):
    # Mark fiyatı TP'ye eşit veya üstünde → buffer ile yukarı itilmesini bekleriz
    monkeypatch.setenv("BINANCE_TESTNET", "true", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "x", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "y", prepend=False)
    monkeypatch.setenv("IMMEDIATE_BUFFER_BPS", "10", prepend=False)  # 10 bps

    # tick/step
    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})

    fake = _FakeClient(mark_price=100.0)
    monkeypatch.setattr(fo, "get_futures_client", lambda: fake)

    out = fo.attach_bracket_tp_sl("BTCUSDT", "LONG", take_profit=100.0, stop_loss=90.0, dry_run=False)
    tp_req = out["tp"]["request"]
    # 10 bps üstüne itilmiş olmalı: 100 * (1+0.001) = 100.1 → tick 0.1 ile zaten 100.1
    assert float(tp_req["stopPrice"]) >= 100.1


def test_sl_buffer_short_avoids_immediate_trigger(monkeypatch):
    # SHORT'ta mark sl'ye eşit veya üstünde → SL buffer ile yukarı itilir (tetik anında kaçınmak için)
    monkeypatch.setenv("BINANCE_TESTNET", "true", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "x", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "y", prepend=False)
    monkeypatch.setenv("IMMEDIATE_BUFFER_BPS", "10", prepend=False)

    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})

    fake = _FakeClient(mark_price=100.0)
    monkeypatch.setattr(fo, "get_futures_client", lambda: fake)

    out = fo.attach_bracket_tp_sl("BTCUSDT", "SHORT", take_profit=99.0, stop_loss=100.0, dry_run=False)
    sl_req = out["sl"]["request"]
    # SHORT için SL tetik koşulu mark >= stopPrice, buffer ile stopPrice yukarı çekilir
    assert float(sl_req["stopPrice"]) > 100.0


