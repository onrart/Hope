import copy
import time

from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _reset_system_state():
    from core import monitoring

    with monitoring._SYSTEM_LOCK:  # type: ignore[attr-defined]
        original_state = copy.deepcopy(monitoring._SYSTEM_STATE)  # type: ignore[attr-defined]
    try:
        yield
    finally:
        with monitoring._SYSTEM_LOCK:  # type: ignore[attr-defined]
            monitoring._SYSTEM_STATE.clear()  # type: ignore[attr-defined]
            monitoring._SYSTEM_STATE.update(original_state)  # type: ignore[attr-defined]


def test_system_snapshot_includes_binance_feed(monkeypatch):
    from core import monitoring

    fake_klines = [[0, "1", "2", "0.5", "1.5", 0, 0, 0, 0, 0, 0, 0] for _ in range(5)]

    monkeypatch.setattr("core.market_data.get_last_price", lambda symbol: 42123.5)
    monkeypatch.setattr("core.market_data.compute_atr", lambda *args, **kwargs: 54.2)
    monkeypatch.setattr("core.market_data.get_klines", lambda *args, **kwargs: fake_klines)
    monkeypatch.setattr(
        "core.market_data.klines_to_ohlc",
        lambda klines: [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5} for _ in klines],
    )

    snapshot = monitoring._system_snapshot("BTCUSDT")  # type: ignore[attr-defined]

    assert snapshot["source"] == "binance"
    assert snapshot["last_price"] == 42123.5
    assert snapshot["atr"] == 54.2
    assert snapshot["recent_ohlc"]
    assert all("close" in candle for candle in snapshot["recent_ohlc"])


def test_system_tick_sends_snapshot_to_gemini(monkeypatch):
    from core import monitoring

    expected_snapshot = {
        "source": "binance",
        "last_price": 123.4,
        "atr": 6.7,
        "recent_ohlc": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5}],
    }

    monkeypatch.setattr("core.monitoring._system_snapshot", lambda symbol: expected_snapshot)

    captured = {}

    def fake_decide(symbol, snapshot, dry_run=False, **_):
        captured["symbol"] = symbol
        captured["snapshot"] = snapshot
        return {
            "action": "HOLD",
            "confidence": 0.82,
            "_raw_text": "{\"action\":\"HOLD\"}",
        }

    monkeypatch.setattr("deciders.decider_gemini.decide", fake_decide)

    result = monitoring._system_tick()  # type: ignore[attr-defined]

    assert captured["symbol"] == monitoring._SYSTEM_SYMBOL  # type: ignore[attr-defined]
    assert captured["snapshot"] is expected_snapshot
    assert result["gemini_text"] == "{\"action\":\"HOLD\"}"
    assert result["snapshot"] is expected_snapshot


def test_get_system_status_exposes_gemini_history():
    from core import monitoring

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "HOLD",
        "gemini_text": "{\"action\":\"HOLD\"}",
    }

    monitoring._system_record(entry)  # type: ignore[attr-defined]

    status = monitoring.get_system_status()

    assert status["history"][0]["gemini_text"] == entry["gemini_text"]
    assert status["history"][0]["status"] == "HOLD"


def test_stop_system_loop_can_halt_running_thread(monkeypatch):
    from core import monitoring

    call_count = {"ticks": 0}

    def fake_tick():
        call_count["ticks"] += 1
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": "HOLD",
            "action": "HOLD",
            "confidence": 0.5,
            "dry_run": True,
        }

    monkeypatch.setattr("core.monitoring._system_tick", fake_tick)

    start = monitoring.start_system_loop()
    assert start["running"] is True

    try:
        # let the loop tick at least once
        time.sleep(0.1)

        stop = monitoring.stop_system_loop()
        assert stop["running"] is False
        assert stop["stopped"] is True
        assert call_count["ticks"] >= 1
    finally:
        monitoring.stop_system_loop()
