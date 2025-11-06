# core/indicators.py
from typing import List, Dict, Any
import math


def ema(values: List[float], period: int) -> float | None:
    if not values or len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def rsi(values: List[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = values[-i] - values[-i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def atr(ohlc: List[Dict[str, float]], period: int = 14) -> float | None:
    if len(ohlc) < period + 1:
        return None
    trs = []
    prev_close = ohlc[0]["close"]
    for i in range(1, len(ohlc)):
        h = ohlc[i]["high"]
        l = ohlc[i]["low"]
        c = ohlc[i]["close"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    return sum(trs[-period:]) / period if len(trs) >= period else None
