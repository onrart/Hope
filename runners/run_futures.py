# runners/run_futures.py
# Python 3.11 compatible
from __future__ import annotations
import argparse
import json
import logging
import os
import time
import uuid
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from core.cooldown import CooldownManager
from core.risk_guard import RiskGuard
from futures import futures_orders as fo
from utils import position_tools as pt

# Logging
logger = logging.getLogger("runners.run_futures")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


# ---------------- Config / helpers ----------------
def make_trace_id(prefix: Optional[str] = None) -> str:
    ts = int(time.time() * 1000)
    short = uuid.uuid4().hex[:8]
    if prefix:
        return f"{prefix}-{short}-{ts}"
    return f"{short}-{ts}"


def load_config_from_env() -> Dict[str, Any]:
    """
    Load runner configuration from environment with sensible defaults.
    """
    return {
        "state_path": os.getenv(
            "RISK_STATE_PATH", os.path.join(os.getcwd(), "state.json")
        ),
        "cooldown_path": os.getenv(
            "COOLDOWN_PATH", os.path.join(os.getcwd(), "cooldown.json")
        ),
        "max_daily_loss": float(os.getenv("MAX_DAILY_LOSS", "100.0")),
        "max_drawdown": float(os.getenv("MAX_DRAWDOWN", "200.0")),
        "max_attempts_per_hour": int(os.getenv("MAX_ATTEMPTS_PER_HOUR", "10")),
        "default_cooldown_secs_on_error": int(
            os.getenv("DEFAULT_COOLDOWN_SECS_ON_ERROR", "60")
        ),
        "emergency_risk_lock_secs": int(os.getenv("EMERGENCY_RISK_LOCK_SECS", "3600")),
        "alert_webhook_url": os.getenv("ALERT_WEBHOOK_URL", ""),
    }


def _send_alert_webhook(payload: dict, cfg: dict) -> None:
    """
    Best-effort send alert to configured webhook URL (ALERT_WEBHOOK_URL).
    Failures are logged but do not raise.
    """
    url = cfg.get("alert_webhook_url")
    if not url:
        return
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Alert webhook sent, status=%s", resp.status)
    except urllib.error.HTTPError as e:
        logger.exception("Alert webhook HTTPError: %s", e)
    except Exception as e:
        logger.exception("Alert webhook failed: %s", e)


# ---------------- Core runner ----------------
def run_once(
    *,
    signal: Dict[str, Any],
    client: Any,
    dry_run: bool = True,
    trace_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a single futures trade flow with safety checks.

    Args:
      - signal: trade signal dict:
          {
            "symbol": "BTCUSDT",
            "side": "BUY"|"SELL",
            "qty": float (optional),
            "entry_price": float or None,
            "take_profit": float|None,
            "stop_loss": float|None,
            "risk_usdt": float|None,
            "balance_usdt": float|optional (for qty calculation)
          }
      - client: injected exchange client (must provide futures_create_order or create_order)
      - dry_run: if True, don't send real orders (returns payloads)
      - trace_id: optional trace id; if not provided a new one is generated
      - config: optional config dict (overrides env)
    Returns:
      dict with status and details (see tests / examples)
    """
    cfg = config or load_config_from_env()
    # instantiate guards/managers
    rg = RiskGuard(
        path=cfg["state_path"],
        max_daily_loss=cfg["max_daily_loss"],
        max_drawdown=cfg["max_drawdown"],
        max_attempts_per_hour=cfg["max_attempts_per_hour"],
    )
    cm = CooldownManager(path=cfg["cooldown_path"])

    tid = trace_id or make_trace_id("run")
    symbol = signal.get("symbol")
    if not symbol:
        raise ValueError("signal must contain 'symbol'")
    symbol = symbol.upper()
    side = str(signal.get("side", "BUY")).upper()

    # 1) Risk guard
    guard = rg.guard_check()
    if guard.get("locked"):
        logger.warning(
            "run_once[%s] aborted: risk guard locked until %s reason=%s",
            tid,
            guard.get("locked_until"),
            guard.get("reason"),
        )
        return {
            "status": "aborted",
            "reason": "risk_locked",
            "locked_until": guard.get("locked_until"),
            "trace_id": tid,
        }

    # 2) Cooldown check
    if cm.is_on_cooldown(symbol):
        logger.warning("run_once[%s] aborted: symbol %s on cooldown", tid, symbol)
        return {
            "status": "aborted",
            "reason": "symbol_on_cooldown",
            "trace_id": tid,
            "symbol": symbol,
        }

    # 3) Register attempt rate-limiter
    ok, reason = rg.register_trade_attempt()
    if not ok:
        logger.warning(
            "run_once[%s] aborted: register_trade_attempt denied -> %s", tid, reason
        )
        return {"status": "aborted", "reason": reason, "trace_id": tid}

    # 4) Determine qty (prefer provided qty; else compute from risk_usdt)
    qty = signal.get("qty")
    entry_price = signal.get("entry_price")
    tp = signal.get("take_profit")
    sl = signal.get("stop_loss")

    if qty is None:
        risk_usdt = signal.get("risk_usdt")
        if risk_usdt is not None and entry_price is not None and sl is not None:
            qty_calc, reason_q = pt.compute_position_qty(
                balance_usdt=signal.get("balance_usdt", 0.0),
                risk_usdt=float(risk_usdt),
                entry_price=float(entry_price),
                stop_price=float(sl),
                side=side,
                allow_inverse_stop=False,
            )
            if qty_calc <= 0:
                logger.warning(
                    "run_once[%s] qty calculation failed -> %s", tid, reason_q
                )
                return {
                    "status": "aborted",
                    "reason": "qty_calc_failed",
                    "detail": reason_q,
                    "trace_id": tid,
                }
            qty = qty_calc
        else:
            logger.warning(
                "run_once[%s] aborted: no qty and insufficient data to compute qty", tid
            )
            return {"status": "aborted", "reason": "missing_qty", "trace_id": tid}

    logger.info(
        "run_once[%s] proceeding: %s %s qty=%s entry_price=%s tp=%s sl=%s dry_run=%s",
        tid,
        symbol,
        side,
        qty,
        entry_price,
        tp,
        sl,
        dry_run,
    )

    # 5) Open position
    try:
        entry_res = fo.open_position(
            client=client,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=entry_price,
            trace_id=tid,
            dry_run=dry_run,
            retries=3,
        )
    except Exception as e:
        logger.exception("run_once[%s] entry order failed: %s", tid, e)
        try:
            cm.mark_trade(
                symbol,
                ttl_seconds=cfg["default_cooldown_secs_on_error"],
                reason="entry_failed",
                trace_id=tid,
            )
        except Exception:
            logger.exception(
                "run_once[%s] failed to set cooldown after entry failure", tid
            )
        # send alert
        _send_alert_webhook(
            {
                "event": "entry_failed",
                "trace_id": tid,
                "symbol": symbol,
                "error": str(e),
            },
            cfg,
        )
        return {"status": "error", "stage": "entry", "error": str(e), "trace_id": tid}

    # entry dry-run handling
    if isinstance(entry_res, dict) and entry_res.get("dry_run"):
        logger.info("run_once[%s] dry_run entry payload prepared", tid)
        payloads = pt.prepare_bracket_payload(
            symbol, side, entry_res["payload"], tp, sl, trace_id=tid
        )
        return {
            "status": "dry_run",
            "entry_payload": entry_res["payload"],
            "bracket_payloads": payloads,
            "trace_id": tid,
        }

    entry_resp = entry_res.get("response") if isinstance(entry_res, dict) else entry_res

    # 6) Attach TP/SL with safety (SL-first) and emergency SL logic
    try:
        attach_res = fo.attach_bracket_tp_sl(
            client=client,
            symbol=symbol,
            side=side,
            entry_resp=entry_resp,
            take_profit=tp,
            stop_loss=sl,
            trace_id=tid,
            dry_run=dry_run,
            retries=3,
            backoff_base=0.2,
            close_position=True,
            attach_order=["sl", "tp"],  # SL first for safety
        )
    except Exception as e:
        logger.exception("run_once[%s] attach TP/SL raised exception: %s", tid, e)
        try:
            cm.mark_trade(
                symbol,
                ttl_seconds=cfg["default_cooldown_secs_on_error"],
                reason="attach_raised",
                trace_id=tid,
            )
        except Exception:
            logger.exception(
                "run_once[%s] failed to set cooldown after attach exception", tid
            )
        _send_alert_webhook(
            {
                "event": "attach_exception",
                "trace_id": tid,
                "symbol": symbol,
                "error": str(e),
            },
            cfg,
        )
        return {
            "status": "error",
            "stage": "attach_exception",
            "error": str(e),
            "trace_id": tid,
            "entry_resp": entry_resp,
        }

    # attach dry-run handling
    if isinstance(attach_res, dict) and attach_res.get("dry_run"):
        logger.info("run_once[%s] dry_run attach prepared", tid)
        return {
            "status": "dry_run",
            "entry_resp": entry_resp,
            "bracket_payloads": attach_res["payloads"],
            "trace_id": tid,
        }

    errors = attach_res.get("errors") if isinstance(attach_res, dict) else {}
    partial_payload = (
        attach_res.get("partial_emergency") if isinstance(attach_res, dict) else None
    )
    if errors:
        logger.warning(
            "run_once[%s] attach had errors: %s (partial=%s)",
            tid,
            errors,
            partial_payload,
        )
        cooldown_reason = "attach_errors"
        meta = {"errors": errors, "trace_id": tid}
        if partial_payload:
            cooldown_reason = partial_payload.get("cooldown_reason", cooldown_reason)
            meta["partial_emergency"] = partial_payload
        try:
            cm.mark_trade(
                symbol,
                ttl_seconds=max(60, cfg["default_cooldown_secs_on_error"]),
                reason=cooldown_reason,
                trace_id=tid,
                meta=meta,
            )
        except Exception:
            logger.exception(
                "run_once[%s] failed to set cooldown after attach errors", tid
            )

        alert_payload = {
            "event": "attach_partial" if partial_payload else "attach_errors",
            "trace_id": tid,
            "symbol": symbol,
            "errors": errors,
        }
        if partial_payload:
            alert_payload["partial_emergency"] = partial_payload
        _send_alert_webhook(alert_payload, cfg)

        # Emergency: if SL not placed and stop_loss present, try aggressive SL placement
        emergency_result = None
        emergency_errors = None
        if sl is not None and (not attach_res.get("sl")):
            logger.warning(
                "run_once[%s] attempting emergency SL placement for %s", tid, symbol
            )
            try:
                emergency_res = fo.attach_bracket_tp_sl(
                    client=client,
                    symbol=symbol,
                    side=side,
                    entry_resp=entry_resp,
                    take_profit=None,
                    stop_loss=sl,
                    trace_id=tid,
                    dry_run=dry_run,
                    retries=5,
                    backoff_base=0.5,
                    close_position=True,
                    attach_order=["sl"],  # only SL
                )
                emergency_result = emergency_res
                emergency_errors = emergency_res.get("errors")
                if emergency_errors:
                    logger.error(
                        "run_once[%s] emergency SL also failed: %s",
                        tid,
                        emergency_errors,
                    )
                    try:
                        cm.mark_trade(
                            symbol,
                            ttl_seconds=max(300, cfg["default_cooldown_secs_on_error"]),
                            reason="emergency_sl_failed",
                            trace_id=tid,
                        )
                    except Exception:
                        logger.exception(
                            "run_once[%s] failed to set cooldown after emergency SL failure",
                            tid,
                    )

                    # Force a risk lock to block further ops for a period
                    try:
                        lock_secs = cfg.get("emergency_risk_lock_secs", 3600)
                        rg.force_lock(lock_secs, reason=f"emergency_sl_failed:{symbol}")
                        logger.warning(
                            "run_once[%s] forced risk lock for %s seconds due to emergency SL failure",
                            tid,
                            lock_secs,
                        )
                        if partial_payload is not None:
                            partial_payload["force_lock_applied"] = True
                            partial_payload["force_lock_reason"] = (
                                f"emergency_sl_failed:{symbol}"
                            )
                    except Exception:
                        logger.exception("run_once[%s] failed to force risk lock", tid)

                    # send alert with emergency failure details
                    _send_alert_webhook(
                        {
                            "event": "emergency_sl_failed",
                            "trace_id": tid,
                            "symbol": symbol,
                            "attach_errors": errors,
                            "emergency_errors": emergency_errors,
                            "entry_resp": entry_resp,
                        },
                        cfg,
                    )
                else:
                    logger.info("run_once[%s] emergency SL placed successfully", tid)
                    _send_alert_webhook(
                        {
                            "event": "emergency_sl_placed",
                            "trace_id": tid,
                            "symbol": symbol,
                            "entry_resp": entry_resp,
                            "emergency_resp": emergency_res,
                        },
                        cfg,
                    )
            except Exception as e:
                logger.exception(
                    "run_once[%s] emergency SL placement raised exception: %s", tid, e
                )
                try:
                    cm.mark_trade(
                        symbol,
                        ttl_seconds=max(300, cfg["default_cooldown_secs_on_error"]),
                        reason="emergency_sl_exception",
                        trace_id=tid,
                    )
                except Exception:
                    logger.exception(
                        "run_once[%s] failed to set cooldown after emergency SL exception",
                        tid,
                    )
                _send_alert_webhook(
                    {
                        "event": "emergency_sl_exception",
                        "trace_id": tid,
                        "symbol": symbol,
                        "error": str(e),
                        "entry_resp": entry_resp,
                    },
                    cfg,
                )

        if partial_payload is not None:
            partial_payload = dict(partial_payload)
            if emergency_result is not None:
                partial_payload["emergency_attempt"] = emergency_result
            if emergency_errors is not None:
                partial_payload["emergency_errors"] = emergency_errors
        return {
            "status": "partial",
            "stage": "attach",
            "errors": errors,
            "entry_resp": entry_resp,
            "trace_id": tid,
            "partial_emergency": partial_payload,
        }

    # All good
    logger.info("run_once[%s] entry+bracket succeeded for %s", tid, symbol)
    return {
        "status": "ok",
        "entry_resp": entry_resp,
        "attach_resp": attach_res,
        "trace_id": tid,
    }


# ---------------- CLI / helper to load signal ----------------
def _load_signal_from_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main_cli():
    parser = argparse.ArgumentParser(
        prog="run_futures",
        description="Run a single futures trade flow (risk guard + cooldown integrated).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't send real orders, just prepare payloads.",
    )
    parser.add_argument("--signal-file", type=str, help="JSON file with trade signal")
    parser.add_argument("--symbol", type=str, help="Symbol (e.g. BTCUSDT)")
    parser.add_argument("--side", type=str, help="BUY/SELL")
    parser.add_argument(
        "--qty", type=float, help="Quantity (optional if risk_usdt provided)"
    )
    parser.add_argument(
        "--entry-price", type=float, help="Entry price (optional for market)"
    )
    parser.add_argument("--tp", type=float, help="Take profit price")
    parser.add_argument("--sl", type=float, help="Stop loss price")
    parser.add_argument(
        "--risk-usdt", type=float, help="Risk amount in USDT (optional)"
    )
    args = parser.parse_args()

    # Build signal
    if args.signal_file:
        sig = _load_signal_from_file(args.signal_file)
    else:
        if not args.symbol or not args.side:
            parser.error("Either --signal-file or --symbol and --side must be provided")
        sig = {
            "symbol": args.symbol,
            "side": args.side,
            "qty": args.qty,
            "entry_price": args.entry_price,
            "take_profit": args.tp,
            "stop_loss": args.sl,
            "risk_usdt": args.risk_usdt,
        }

    # CLI mode: we do not create an exchange client here for safety.
    # The runner expects an injected client (for tests / service integration).
    raise RuntimeError(
        "CLI mode requires passing a proper exchange client. Use run_once() from code with an injected client."
    )


if __name__ == "__main__":
    main_cli()
