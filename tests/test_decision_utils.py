# tests/test_decision_utils.py
import math
from core.decision_utils import normalize_decision


def f(x):
    return normalize_decision(x)


def test_confidence_parsing():
    assert math.isclose(f({"action": "BUY", "confidence": "82%"})["confidence"], 0.82)
    assert math.isclose(f({"action": "BUY", "confidence": "High"})["confidence"], 0.80)
    assert math.isclose(f({"action": "BUY", "confidence": "0,62"})["confidence"], 0.62)


def test_price_no_percent_scaling():
    d = f(
        {
            "action": "BUY",
            "confidence": "80%",
            "entry": "68000",
            "take_profit": "68240",
            "stop_loss": "67820",
        }
    )
    assert (
        d["entry"] == 68000.0
        and d["take_profit"] == 68240.0
        and d["stop_loss"] == 67820.0
    )


def test_hold_defaults():
    d = f({"action": "HOLD", "confidence": "60%"})
    assert (
        d["action"] == "HOLD"
        and d["entry"] is None
        and d["take_profit"] is None
        and d["stop_loss"] is None
    )
