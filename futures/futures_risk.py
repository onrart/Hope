# futures/futures_risk.py
from typing import Dict, Any


def position_size(
    total_balance_usdt: float, risk_per_trade: float, entry: float, stop: float
) -> float:
    risk_amount = total_balance_usdt * risk_per_trade
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    return max(0.0, risk_amount / risk_per_unit)
