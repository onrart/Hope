# utils/position_tools.py
# Python 3.11 compatible
from __future__ import annotations
import hashlib
import os
import time
import uuid
import json
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

FORCE_REDUCEONLY = os.getenv("FORCE_REDUCEONLY", "false").lower() == "true"


def _client_order_id(
    prefix: str, symbol: str, side: str, trace_id: Optional[str] = None
) -> str:
    """
    Build a deterministic client order id suitable for idempotent retries.

    When a trace_id is provided we derive a stable suffix from it so repeated
    calls for the same logical trade produce the exact same identifier.  When
    no trace_id is supplied we fallback to a time + random based suffix to keep
    the identifier unique enough for manual invocations.
    """

    safe_symbol = symbol.replace("/", "").replace("-", "").upper()
    safe_side = side.upper()
    base = f"{prefix}-{safe_symbol}-{safe_side}"

    if trace_id:
        digest = hashlib.blake2s(str(trace_id).encode("utf-8"), digest_size=10).hexdigest()
        return f"{base}-{digest}"

    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex[:8]
    return f"{base}-{rand}-{ts}"


def _normalize_price(p: Any) -> Optional[float]:
    try:
        return float(p)
    except Exception:
        return None


def _payload_for_take_profit(
    symbol: str,
    close_side: str,
    tp_price: float,
    working_type: str = "MARK_PRICE",
    close_position: bool = True,
) -> Dict[str, Any]:
    """
    Return a dict representing a take-profit MARKET order payload (for futures).
    Note: do NOT include 'reduceOnly' if close_position True unless FORCE_REDUCEONLY is set.
    """
    payload = {
        "symbol": symbol.upper(),
        "side": close_side,
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": tp_price,
        "workingType": working_type,
        "closePosition": True if close_position else False,
    }
    # Add reduceOnly only if explicitly forced or if payload is non-close position and we want reduceOnly behavior.
    if not payload["closePosition"] and not FORCE_REDUCEONLY:
        # non-close position take profit: include reduceOnly for partial reductions
        payload["reduceOnly"] = True
    elif FORCE_REDUCEONLY and payload["closePosition"]:
        payload["reduceOnly"] = True
    return payload


def _payload_for_stop_loss(
    symbol: str,
    close_side: str,
    sl_price: float,
    working_type: str = "MARK_PRICE",
    reduce_only: bool = True,
) -> Dict[str, Any]:
    """
    Return dict for stop-loss order (can be STOP_MARKET or STOP_LOSS depending on exchange).
    """
    payload = {
        "symbol": symbol.upper(),
        "side": close_side,
        "type": "STOP_MARKET",
        "stopPrice": sl_price,
        "workingType": working_type,
    }
    # reduceOnly typically required for stop orders to avoid opening opposite positions
    if reduce_only:
        payload["reduceOnly"] = True
    return payload


def prepare_bracket_payload(
    symbol: str,
    side: str,
    entry_order: Dict[str, Any],
    take_profit_price: Optional[float],
    stop_loss_price: Optional[float],
    trace_id: Optional[str] = None,
    working_type: str = "MARK_PRICE",
    close_position: bool = True,
) -> Dict[str, Any]:
    """
    Construct a dictionary with all payloads needed to attach a bracket (TP + SL).
    This function does NOT call the exchange; it returns the payloads so caller can decide how to send them.
    """
    out: Dict[str, Any] = {
        "entry_order": entry_order.copy(),
        "tp_order": None,
        "sl_order": None,
        "trace_id": trace_id,
    }
    if trace_id is not None and "newClientOrderId" not in out["entry_order"]:
        out["entry_order"]["newClientOrderId"] = _client_order_id(
            "entry", symbol, side, trace_id=trace_id
        )
    close_side = "SELL" if side.upper() == "BUY" else "BUY"

    if take_profit_price is not None:
        tp_payload = _payload_for_take_profit(
            symbol,
            close_side,
            float(take_profit_price),
            working_type=working_type,
            close_position=close_position,
        )
        if trace_id is not None and "newClientOrderId" not in tp_payload:
            tp_payload["newClientOrderId"] = _client_order_id(
                "tp", symbol, close_side, trace_id=trace_id
            )
        out["tp_order"] = tp_payload

    if stop_loss_price is not None:
        # For SL, we usually want reduceOnly True to avoid netting into opposite side
        sl_payload = _payload_for_stop_loss(
            symbol,
            close_side,
            float(stop_loss_price),
            working_type=working_type,
            reduce_only=True,
        )
        if trace_id is not None and "newClientOrderId" not in sl_payload:
            sl_payload["newClientOrderId"] = _client_order_id(
                "sl", symbol, close_side, trace_id=trace_id
            )
        out["sl_order"] = sl_payload

    return out


def place_bracket(
    client: Any,
    symbol: str,
    side: str,
    qty: float,
    entry_price: Optional[float] = None,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
    trace_id: Optional[str] = None,
    dry_run: bool = False,
    working_type: str = "MARK_PRICE",
    close_position: bool = True,
) -> Dict[str, Any]:
    """
    High-level helper: (1) open entry order; (2) attach TP and SL if provided.
    The client is expected to have methods:
      - futures_create_order(**payload)  OR create_order(**payload)
    This helper returns a dict with 'entry', 'tp', 'sl' results (or payloads if dry_run True).
    """
    # Build entry payload
    entry_payload = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "MARKET" if entry_price is None else "LIMIT",
        "quantity": qty,
    }
    if entry_price is not None:
        entry_payload["price"] = float(entry_price)

    # add deterministic client order id for idempotency
    entry_payload["newClientOrderId"] = _client_order_id(
        "entry", symbol, side, trace_id=trace_id
    )

    results: Dict[str, Any] = {"entry": None, "tp": None, "sl": None, "payloads": None}

    # if dry_run -> return payloads only
    if dry_run:
        payloads = prepare_bracket_payload(
            symbol,
            side,
            entry_payload,
            take_profit,
            stop_loss,
            trace_id=trace_id,
            working_type=working_type,
            close_position=close_position,
        )
        results["payloads"] = payloads
        return results

    # send entry order (try futures_create_order then fallback)
    create_fn = getattr(client, "futures_create_order", None) or getattr(
        client, "create_order", None
    )
    if create_fn is None:
        raise RuntimeError(
            "client has no create order function (futures_create_order/create_order)"
        )

    # call entry
    entry_result = create_fn(**entry_payload)
    results["entry"] = entry_result

    # Prepare TP/SL payloads
    payloads = prepare_bracket_payload(
        symbol,
        side,
        entry_payload,
        take_profit,
        stop_loss,
        trace_id=trace_id,
        working_type=working_type,
        close_position=close_position,
    )
    results["payloads"] = payloads

    # compute close_side for TP/SL clientOrderId generation
    close_side = "SELL" if side.upper() == "BUY" else "BUY"

    # attach TP then SL (order can vary by exchange; attach in non-blocking way)
    try:
        if payloads.get("tp_order"):
            tp_payload = payloads["tp_order"]
            # add unique client id for TP to help identify it in exchange
            tp_payload["newClientOrderId"] = _client_order_id(
                "tp", symbol, close_side, trace_id=trace_id
            )
            results["tp"] = create_fn(**tp_payload)
    except Exception as e:
        logger.exception("place_bracket: TP attach failed", exc_info=e)
        results["tp_error"] = str(e)

    try:
        if payloads.get("sl_order"):
            sl_payload = payloads["sl_order"]
            sl_payload["newClientOrderId"] = _client_order_id(
                "sl", symbol, close_side, trace_id=trace_id
            )
            results["sl"] = create_fn(**sl_payload)
    except Exception as e:
        logger.exception("place_bracket: SL attach failed", exc_info=e)
        results["sl_error"] = str(e)

    return results
