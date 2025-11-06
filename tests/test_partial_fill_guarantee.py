from futures import futures_orders as fo


def test_bracket_payload_closes_full_position(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "x", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "y", prepend=False)

    # Basit filtre
    monkeypatch.setattr(fo, "fetch_symbol_filters", lambda s: {"step_str": "0.001", "tick_str": "0.1"})

    out = fo.attach_bracket_tp_sl("BTCUSDT", "LONG", 110.0, 90.0, dry_run=True)
    tp = out["tp"]["payload"]
    sl = out["sl"]["payload"]

    # quantity içermemeli, closePosition True olmalı → kısmi dolum sonrasında kalan tüm pozisyonu kapatır
    assert "quantity" not in tp and tp.get("closePosition") is True
    assert "quantity" not in sl and sl.get("closePosition") is True


