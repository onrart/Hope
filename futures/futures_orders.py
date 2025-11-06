# futures/futures_orders.py
# Python 3.11 compatible
from __future__ import annotations
import os
import time
import uuid
import random
import logging
from typing import Any, Dict, Optional, Tuple, Callable, List

from utils.position_tools import _client_order_id, prepare_bracket_payload

logger = logging.getLogger(__name__)


# jitter/backoff helper
def _sleep_with_jitter(base: float, attempt: int, jitter: float = 0.2) -> None:
    sleep = base * (2 ** (attempt - 1))
    factor = 1.0 + (random.random() * 2 - 1) * jitter
    time.sleep(max(0.0, sleep * factor))


def _deterministic_client_order_id(
    prefix: str, symbol: str, side: str, trace_id: Optional[str] = None
) -> str:
    return _client_order_id(prefix, symbol, side, trace_id=trace_id)


def open_position(
    client: Any,
    symbol: str,
    side: str,
    quantity: float,
    price: Optional[float] = None,
    trace_id: Optional[str] = None,
    dry_run: bool = False,
    retries: int = 3,
    backoff_base: float = 0.2,
) -> Dict[str, Any]:
    sym = symbol.upper()
    side_u = side.upper()
    entry_payload = {"symbol": sym, "side": side_u, "quantity": float(quantity)}
    if price is not None:
        entry_payload["price"] = float(price)
        entry_payload["type"] = "LIMIT"
    else:
        entry_payload["type"] = "MARKET"

    entry_payload["newClientOrderId"] = _deterministic_client_order_id(
        "entry", sym, side_u, trace_id=trace_id
    )

    if dry_run:
        return {"dry_run": True, "payload": entry_payload}

    create_fn = getattr(client, "futures_create_order", None) or getattr(
        client, "create_order", None
    )
    if create_fn is None:
        raise RuntimeError(
            "client has no order creation API (futures_create_order/create_order)"
        )

    attempt = 0
    last_exc = None
    while True:
        attempt += 1
        try:
            resp = create_fn(**entry_payload)
            return {"status": "ok", "response": resp}
        except Exception as e:
            last_exc = e
            logger.warning(
                "open_position: attempt %s failed for %s %s: %s",
                attempt,
                sym,
                side_u,
                e,
                exc_info=True,
            )
            if attempt >= retries:
                logger.error("open_position: giving up after %s attempts", attempt)
                raise
            _sleep_with_jitter(backoff_base, attempt)
    # unreachable


def attach_bracket_tp_sl(
    client: Any,
    symbol: str,
    side: str,
    entry_resp: Dict[str, Any],
    take_profit: Optional[float],
    stop_loss: Optional[float],
    trace_id: Optional[str] = None,
    dry_run: bool = False,
    retries: int = 3,
    backoff_base: float = 0.2,
    close_position: bool = True,
    attach_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Attach TP and SL to an already-opened position.
    - attach_order: list with any order of "sl" and/or "tp". Default is ["sl","tp"] (place SL first).
    - Returns dict with 'tp','sl','errors' keys. For dry_run returns payloads.
    """
    if attach_order is None:
        attach_order = ["sl", "tp"]

    create_fn = getattr(client, "futures_create_order", None) or getattr(
        client, "create_order", None
    )
    if create_fn is None and not dry_run:
        raise RuntimeError("attach_bracket_tp_sl: client has no create order fn")

    # best-effort derive entry payload
    entry_payload = {}
    if isinstance(entry_resp, dict):
        entry_payload = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": float(
                entry_resp.get("executedQty")
                or entry_resp.get("quantity")
                or entry_resp.get("qty")
                or 0
            ),
        }
    else:
        entry_payload = {"symbol": symbol.upper(), "side": side.upper(), "quantity": 0}

    payloads = prepare_bracket_payload(
        symbol,
        side,
        entry_payload,
        take_profit,
        stop_loss,
        trace_id=trace_id,
        close_position=close_position,
    )
    if dry_run:
        return {"dry_run": True, "payloads": payloads}

    results: Dict[str, Any] = {"tp": None, "sl": None, "errors": {}, "partial_emergency": None}

    # close_side for client ids
    close_side = "SELL" if side.upper() == "BUY" else "BUY"

    # helper to attempt sending a payload with retries
    def _attempt_send(
        name: str, payload: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        attempt = 0
        errs: List[str] = []
        while True:
            attempt += 1
            try:
                # add client order id if not present
                if "newClientOrderId" not in payload:
                    payload["newClientOrderId"] = _deterministic_client_order_id(
                        name, symbol, close_side, trace_id=trace_id
                    )
                resp = create_fn(**payload)
                return resp, {"attempts": attempt, "errors": errs}
            except Exception as e:
                errs.append(str(e))
                logger.warning(
                    "attach_bracket_tp_sl: %s attempt %s failed: %s",
                    name.upper(),
                    attempt,
                    e,
                    exc_info=True,
                )
                if attempt >= retries:
                    logger.error(
                        "attach_bracket_tp_sl: %s give up after %s attempts",
                        name.upper(),
                        attempt,
                    )
                    return None, {"attempts": attempt, "errors": errs}
                _sleep_with_jitter(backoff_base, attempt)

    # iterate attach_order
    failed_orders: Dict[str, Dict[str, Any]] = {}
    for which in attach_order:
        if which == "tp" and payloads.get("tp_order"):
            tp_payload = payloads["tp_order"]
            resp, meta = _attempt_send("tp", tp_payload)
            if resp is not None:
                results["tp"] = resp
            else:
                results.setdefault("errors", {}).setdefault("tp", []).extend(meta["errors"])
                failed_orders["tp"] = {
                    "attempts": meta["attempts"],
                    "errors": meta["errors"],
                    "payload": {k: v for k, v in tp_payload.items()},
                }
        elif which == "sl" and payloads.get("sl_order"):
            sl_payload = payloads["sl_order"]
            resp, meta = _attempt_send("sl", sl_payload)
            if resp is not None:
                results["sl"] = resp
            else:
                results.setdefault("errors", {}).setdefault("sl", []).extend(meta["errors"])
                failed_orders["sl"] = {
                    "attempts": meta["attempts"],
                    "errors": meta["errors"],
                    "payload": {k: v for k, v in sl_payload.items()},
                }
        # ignore unknown entries

    if failed_orders:
        failure_keys = sorted(failed_orders.keys())
        if len(failure_keys) == 1:
            reason = f"attach_failed_{failure_keys[0]}"
        else:
            reason = f"attach_failed_{'_'.join(failure_keys)}"
        results["partial_emergency"] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "trace_id": trace_id,
            "failed_orders": failed_orders,
            "cooldown_reason": reason,
            "force_lock": "sl" in failed_orders,
        }

    return results
