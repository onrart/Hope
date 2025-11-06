import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runners import run_futures
from futures import futures_orders as fo


class _FlakyClient:
    def __init__(self):
        self.entry_calls = 0
        self.tp_calls = 0
        self.sl_calls = 0

    def futures_create_order(self, **kwargs):
        order_type = kwargs.get("type")
        if order_type in {"MARKET", "LIMIT"}:
            self.entry_calls += 1
            return {"symbol": kwargs["symbol"], "executedQty": kwargs.get("quantity", 0)}
        if order_type == "TAKE_PROFIT_MARKET":
            self.tp_calls += 1
            return {"symbol": kwargs["symbol"], "status": "NEW", "orderType": order_type}
        if order_type == "STOP_MARKET":
            self.sl_calls += 1
            raise RuntimeError("stop failed")
        raise RuntimeError(f"unexpected order type {order_type}")


def test_run_once_partial_emergency(tmp_path, monkeypatch):
    client = _FlakyClient()
    monkeypatch.setattr(fo, "_sleep_with_jitter", lambda *args, **kwargs: None)

    alerts = []

    def _capture_alert(payload, _cfg):
        alerts.append(payload)

    monkeypatch.setattr(run_futures, "_send_alert_webhook", _capture_alert)

    state_path = str(tmp_path / "state.json")
    cooldown_path = str(tmp_path / "cooldown.json")
    cfg = {
        "state_path": state_path,
        "cooldown_path": cooldown_path,
        "max_daily_loss": 1000.0,
        "max_drawdown": 1000.0,
        "max_attempts_per_hour": 10,
        "default_cooldown_secs_on_error": 30,
        "emergency_risk_lock_secs": 120,
        "alert_webhook_url": "",
    }

    signal = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "qty": 0.1,
        "take_profit": 101.2,
        "stop_loss": 95.4,
    }

    result = run_futures.run_once(
        signal=signal,
        client=client,
        dry_run=False,
        trace_id="trace-partial",
        config=cfg,
    )

    assert result["status"] == "partial"
    partial = result.get("partial_emergency")
    assert partial is not None
    assert "sl" in partial["failed_orders"]
    assert partial["failed_orders"]["sl"]["attempts"] == 3
    assert partial.get("force_lock") is True
    assert partial.get("force_lock_applied") is True

    # cooldown file should contain entry for symbol with trace id metadata
    cooldown_data = json.loads(Path(cooldown_path).read_text("utf-8"))
    assert "BTCUSDT" in cooldown_data
    cooldown_entry = cooldown_data["BTCUSDT"]
    assert any(
        cooldown_entry["reason"].startswith(prefix)
        for prefix in ("attach_failed", "emergency_sl_failed")
    )
    assert cooldown_entry["trace_id"] == "trace-partial"

    # risk guard should be forced locked due to emergency SL failure
    state_data = json.loads(Path(state_path).read_text("utf-8"))
    assert state_data.get("locked") is True
    assert "emergency_sl_failed" in state_data.get("lock_reason", "")

    # ensure we emitted alert(s)
    assert any(alert.get("event") == "attach_partial" for alert in alerts)
    assert any(alert.get("event") == "emergency_sl_failed" for alert in alerts)
