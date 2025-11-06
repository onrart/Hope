# core/position_sizer.py
# Python 3.11 compatible
from __future__ import annotations
import decimal
from decimal import Decimal
import math
import logging
from typing import Any, Dict, Optional, Callable, Tuple

logger = logging.getLogger(__name__)
decimal.getcontext().prec = 28  # safe precision


def to_decimal(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)


def round_down_to_step(value: float | Decimal, step: float | Decimal) -> float:
    """
    Round down value to nearest multiple of step (floor) using Decimal arithmetic.
    """
    v = to_decimal(value)
    s = to_decimal(step)
    if s == 0:
        # fallback: floor to integer
        try:
            return float(math.floor(float(v)))
        except Exception:
            return 0.0
    try:
        quant = (v // s) * s
        qf = float(+quant)  # unary + to normalize
        if abs(qf) < 1e-15:
            qf = 0.0
        return qf
    except Exception:
        try:
            sf = float(step)
            return math.floor(float(value) / sf) * sf
        except Exception:
            return 0.0


def ceil_to_step(value: float | Decimal, step: float | Decimal) -> float:
    """
    Ceil value to nearest multiple of step.
    """
    v = to_decimal(value)
    s = to_decimal(step)
    if s == 0:
        try:
            return float(math.ceil(float(v)))
        except Exception:
            return 0.0
    try:
        n = (v / s).to_integral_value(rounding=decimal.ROUND_CEILING)
        return float(n * s)
    except Exception:
        try:
            sf = float(step)
            return math.ceil(float(value) / sf) * sf
        except Exception:
            return 0.0


def compute_position_qty(
    *,
    balance_usdt: float,
    risk_usdt: float,
    entry_price: float,
    stop_price: float,
    side: str,
    leverage: Optional[float] = 1.0,
    step_size: Optional[float] = 0.000001,
    min_qty: Optional[float] = 0.0,
    min_notional: Optional[float] = 0.0,
    price_decimals: int = 8,
    allow_inverse_stop: bool = False,
) -> Tuple[float, str]:
    """
    Compute quantity to risk `risk_usdt` given entry and stop.
    Returns (qty, reason). If qty == 0 -> reason explains why.

    allow_inverse_stop:
      - If False (default): invalid stop/orderings (e.g., SELL with stop < entry) are rejected.
      - If True: uses absolute distance abs(entry - stop) when ordering is inverted.
    """
    # validate prices
    try:
        entry = float(entry_price)
        stop = float(stop_price)
    except Exception:
        return 0.0, "invalid_price"

    if entry <= 0 or stop <= 0:
        return 0.0, "invalid_price_nonpositive"

    side_up = str(side).upper()
    if side_up not in ("BUY", "SELL"):
        return 0.0, "invalid_side"

    # compute loss per unit depending on side
    if side_up == "BUY":
        loss_per_unit = entry - stop  # stop must be < entry
    else:
        loss_per_unit = stop - entry  # stop must be > entry

    # If invalid ordering and allow_inverse_stop True, take absolute distance
    if loss_per_unit <= 0 or not math.isfinite(loss_per_unit):
        if allow_inverse_stop:
            loss_per_unit = abs(entry - stop)
            if loss_per_unit <= 0 or not math.isfinite(loss_per_unit):
                return 0.0, "invalid_stop_distance"
        else:
            return 0.0, "invalid_stop_distance"

    try:
        loss_per_unit = float(loss_per_unit)
    except Exception:
        return 0.0, "invalid_loss_per_unit"

    if loss_per_unit <= 0 or not math.isfinite(loss_per_unit):
        return 0.0, "invalid_stop_distance"

    # raw qty by risk
    try:
        raw_qty = float(risk_usdt) / loss_per_unit
    except Exception:
        return 0.0, "invalid_risk_or_distance"

    if raw_qty <= 0 or not math.isfinite(raw_qty):
        return 0.0, "qty_not_positive"

    # available notional guard (balance * leverage)
    lev = float(leverage or 1.0)
    if lev <= 0:
        lev = 1.0
    available_notional = float(balance_usdt) * lev

    # step handling
    step = float(step_size or 0.0)
    if step <= 0:
        # safe fallback
        step = 10 ** (-price_decimals)

    qty_rounded = round_down_to_step(raw_qty, step)

    # enforce min_qty
    if min_qty and qty_rounded < float(min_qty):
        return 0.0, f"below_min_qty({qty_rounded}<{min_qty})"

    # notional check
    notional = qty_rounded * entry
    if min_notional and notional < float(min_notional):
        return 0.0, f"below_min_notional({notional}<{min_notional})"

    # available notional cap (use 95% cushion)
    if available_notional and notional > available_notional * 0.95:
        return 0.0, f"exceeds_available_notional({notional}>{available_notional*0.95})"

    # final sanity
    if not math.isfinite(qty_rounded) or qty_rounded <= 0:
        return 0.0, "qty_not_finite_or_zero"

    return float(qty_rounded), "ok"


def compute_position_qty_with_filters(
    *,
    balance_usdt: float,
    risk_usdt: float,
    entry_price: float,
    stop_price: float,
    side: str,
    leverage: Optional[float] = 1.0,
    fetch_filters: Optional[Callable[[str], Dict[str, Any]]] = None,
    symbol: Optional[str] = None,
    allow_inverse_stop: bool = False,
) -> Tuple[float, str]:
    """
    Helper that fetches step/min_qty/min_notional via fetch_filters(symbol) if provided,
    and calls compute_position_qty with those parameters.
    """
    step = 0.000001
    min_qty = 0.0
    min_notional = 0.0

    if fetch_filters and symbol:
        try:
            f = fetch_filters(symbol)
            if f:
                step = float(
                    f.get("stepSize") or f.get("step") or f.get("lot_size") or step
                )
                min_qty = float(f.get("minQty") or f.get("min_qty") or 0.0)
                min_notional = float(
                    f.get("minNotional")
                    or f.get("min_notional")
                    or f.get("minNotionalUsd")
                    or 0.0
                )
        except Exception as e:
            logger.debug(
                "compute_position_qty_with_filters: fetch_filters failed: %s", e
            )

    return compute_position_qty(
        balance_usdt=balance_usdt,
        risk_usdt=risk_usdt,
        entry_price=entry_price,
        stop_price=stop_price,
        side=side,
        leverage=leverage,
        step_size=step,
        min_qty=min_qty,
        min_notional=min_notional,
        allow_inverse_stop=allow_inverse_stop,
    )
