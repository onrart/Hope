# futures/futures_filters.py
from __future__ import annotations
from typing import Dict, Any
from decimal import Decimal

from futures.futures_client import get_futures_client


def _find_filter(filters, ftype: str):
    for f in filters:
        if f.get("filterType") == ftype:
            return f
    return {}


def _decimals_from_step_str(step_str: str) -> int:
    # '0.001' -> 3, '0.10' -> 1
    if "." not in step_str:
        return 0
    return len(step_str.split(".")[1].rstrip("0"))


def fetch_symbol_filters(symbol: str) -> Dict[str, Any]:
    """
    USD-M Futures 'exchangeInfo' üzerinden sembolün filtrelerini döndürür.
    Dönüş:
      {
        "tick": 0.1,
        "step": 0.001,
        "tick_str": "0.10",
        "step_str": "0.001",
        "tick_decimals": 1,
        "step_decimals": 3,
        "min_qty": 0.001,
        "min_notional": 100.0
      }
    """
    sym = symbol.upper()
    c = get_futures_client()
    info = c.futures_exchange_info()
    symbols = info.get("symbols", [])
    row = next((s for s in symbols if s.get("symbol") == sym), None)
    if not row:
        raise ValueError(f"Symbol not found in futures exchangeInfo: {sym}")

    f_price = _find_filter(row.get("filters", []), "PRICE_FILTER")
    f_lot = _find_filter(row.get("filters", []), "LOT_SIZE")
    f_not = _find_filter(row.get("filters", []), "MIN_NOTIONAL")

    tick_str = f_price.get("tickSize", "0.10")
    step_str = f_lot.get("stepSize", "0.001")
    min_qty = float(f_lot.get("minQty", "0.001"))
    min_notional = float(f_not.get("notional", "100"))

    tick = float(Decimal(tick_str))
    step = float(Decimal(step_str))

    return {
        "tick": tick,
        "step": step,
        "tick_str": tick_str,
        "step_str": step_str,
        "tick_decimals": _decimals_from_step_str(tick_str),
        "step_decimals": _decimals_from_step_str(step_str),
        "min_qty": min_qty,
        "min_notional": min_notional,
    }
