# tests/test_strategy.py
import os
from strategy import evaluate_and_build_order


def test_strategy_builds_order_on_buy():
    cfg = {"MIN_CONFIDENCE": "0.5", "DEFAULT_AMOUNT": "0.002", "SYMBOL": "BTC/USDT"}
    model_resp = {"action": "BUY", "confidence": 0.8}
    payload = evaluate_and_build_order(model_resp, cfg)
    assert payload is not None
    assert payload["symbol"] == "BTC/USDT"
    assert payload["side"] == "BUY"
    assert payload["amount"] == 0.002


def test_strategy_skips_low_confidence():
    cfg = {"MIN_CONFIDENCE": "0.9", "DEFAULT_AMOUNT": "0.002", "SYMBOL": "BTC/USDT"}
    model_resp = {"action": "BUY", "confidence": 0.5}
    payload = evaluate_and_build_order(model_resp, cfg)
    assert payload is None


def test_strategy_skips_hold():
    cfg = {"MIN_CONFIDENCE": "0.5", "DEFAULT_AMOUNT": "0.001", "SYMBOL": "BTC/USDT"}
    model_resp = {"action": "HOLD", "confidence": 1.0}
    assert evaluate_and_build_order(model_resp, cfg) is None
