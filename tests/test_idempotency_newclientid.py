import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from futures import futures_orders as fo
from utils import position_tools as pt


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_open_position_dry_run_deterministic(side):
    trace_id = "trace-1234"
    payload1 = fo.open_position(
        client=None,
        symbol="BTCUSDT",
        side=side,
        quantity=0.1,
        dry_run=True,
        trace_id=trace_id,
    )["payload"]
    payload2 = fo.open_position(
        client=None,
        symbol="BTCUSDT",
        side=side,
        quantity=0.1,
        dry_run=True,
        trace_id=trace_id,
    )["payload"]
    assert payload1["newClientOrderId"] == payload2["newClientOrderId"]


def test_prepare_bracket_payload_deterministic_ids():
    trace_id = "tid-9876"
    entry = {"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.1}
    first = pt.prepare_bracket_payload(
        "BTCUSDT",
        "BUY",
        entry,
        take_profit_price=101.2,
        stop_loss_price=95.4,
        trace_id=trace_id,
    )
    second = pt.prepare_bracket_payload(
        "BTCUSDT",
        "BUY",
        entry,
        take_profit_price=101.2,
        stop_loss_price=95.4,
        trace_id=trace_id,
    )
    assert first["entry_order"]["newClientOrderId"] == second["entry_order"]["newClientOrderId"]
    assert first["tp_order"]["newClientOrderId"] == second["tp_order"]["newClientOrderId"]
    assert first["sl_order"]["newClientOrderId"] == second["sl_order"]["newClientOrderId"]


def test_attach_bracket_dry_run_deterministic_newclient_ids():
    trace_id = "trace-dryrun"
    entry_resp = {"executedQty": 0.1}
    dry1 = fo.attach_bracket_tp_sl(
        client=None,
        symbol="BTCUSDT",
        side="BUY",
        entry_resp=entry_resp,
        take_profit=101.2,
        stop_loss=95.4,
        dry_run=True,
        trace_id=trace_id,
    )["payloads"]
    dry2 = fo.attach_bracket_tp_sl(
        client=None,
        symbol="BTCUSDT",
        side="BUY",
        entry_resp=entry_resp,
        take_profit=101.2,
        stop_loss=95.4,
        dry_run=True,
        trace_id=trace_id,
    )["payloads"]

    assert dry1["tp_order"]["newClientOrderId"] == dry2["tp_order"]["newClientOrderId"]
    assert dry1["sl_order"]["newClientOrderId"] == dry2["sl_order"]["newClientOrderId"]
