from futures import order_router as r


def test_route_summary_dry_run(monkeypatch):
    # BUY, dry_run: open/bracket mock'ları id döndürmez; summary yine oluşmalı
    def _open(symbol, side, qty, dry_run=True):
        return {"dry_run": True, "payload": {"symbol": symbol, "side": side, "quantity": qty}}

    def _br(symbol, position_side, take_profit, stop_loss, dry_run=True):
        return {
            "tp": {"dry_run": True, "payload": {"symbol": symbol, "type": "TAKE_PROFIT_MARKET"}},
            "sl": {"dry_run": True, "payload": {"symbol": symbol, "type": "STOP_MARKET"}},
        }

    monkeypatch.setattr(r, "open_position", _open)
    monkeypatch.setattr(r, "attach_bracket_tp_sl", _br)

    out = r.route("BTCUSDT", "BUY", 0.01, 101.0, 99.0, dry_run=True)
    assert "summary" in out
    s = out["summary"]
    assert s["symbol"] == "BTCUSDT"
    assert s["side"] == "BUY"
    assert s["qty"] == 0.01
    assert s["take_profit"] == 101.0
    assert s["stop_loss"] == 99.0
    assert s["dry_run"] is True
    assert s["orderIds"] == {"open": None, "tp": None, "sl": None}


def test_route_summary_order_ids(monkeypatch):
    # SELL, live: open/bracket mock'ları orderId verir; summary id'leri toplar
    def _open(symbol, side, qty, dry_run=True):
        return {"orderId": 111, "symbol": symbol, "side": side, "executedQty": str(qty)}

    def _br(symbol, position_side, take_profit, stop_loss, dry_run=True):
        return {
            "tp": {"orderId": 222, "symbol": symbol},
            "sl": {"orderId": 333, "symbol": symbol},
        }

    monkeypatch.setattr(r, "open_position", _open)
    monkeypatch.setattr(r, "attach_bracket_tp_sl", _br)

    out = r.route("BTCUSDT", "SELL", 0.02, 99.0, 101.0, dry_run=False)
    s = out["summary"]
    assert s["side"] == "SELL"
    assert s["orderIds"] == {"open": "111", "tp": "222", "sl": "333"}

