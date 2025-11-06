# core/risk_guard.py
# Python 3.11
from __future__ import annotations
import json
import os
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

from filelock import FileLock

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_STATE_PATH = os.path.join(os.getcwd(), "state.json")
_LOCK_SUFFIX = ".lock"
_ONE_HOUR = 3600


def _now_ts() -> float:
    return time.time()


def _today_utc_date_str() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _ensure_dir_for_file(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _atomic_read_json(path: str) -> Dict[str, Any]:
    """
    Read JSON state from path under a FileLock. Returns {} if missing or corrupted.
    """
    lock_path = path + _LOCK_SUFFIX
    lock = FileLock(lock_path, timeout=5)
    with lock:
        p = Path(path)
        if not p.exists():
            return {}
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception(
                "risk_guard: failed to read state file (corrupt?) %s", path
            )
            return {}


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """
    Atomically write JSON to path (tmp -> replace) under FileLock.
    """
    _ensure_dir_for_file(path)
    lock_path = path + _LOCK_SUFFIX
    tmp_path = path + ".tmp"
    lock = FileLock(lock_path, timeout=5)
    with lock:
        # add metadata
        data["_updated_at"] = _now_ts()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


@dataclass
class RiskGuardConfig:
    state_path: str = _DEFAULT_STATE_PATH
    max_daily_loss: float = (
        100.0  # positive number, guard triggers when total losses <= -max_daily_loss
    )
    max_drawdown: float = 1000.0
    max_attempts_per_hour: int = 20
    default_force_lock_secs: int = 3600


class RiskGuard:
    """
    File-backed Risk Guard.

    State JSON schema (internal):
    {
      "locked": False,
      "locked_until": 0.0,
      "lock_reason": "",
      "attempts": {
         "last_hour_ts": 0.0,
         "count_last_hour": 0
      },
      "total_loss_today": 0.0,  # negative number for losses
      "last_loss_date": "YYYY-MM-DD"
    }
    """

    def __init__(
        self,
        path: Optional[str] = None,
        max_daily_loss: float = 100.0,
        max_drawdown: float = 1000.0,
        max_attempts_per_hour: int = 20,
        default_force_lock_secs: int = 3600,
    ):
        cfg_path = path or _DEFAULT_STATE_PATH
        self._cfg = RiskGuardConfig(
            state_path=cfg_path,
            max_daily_loss=float(max_daily_loss),
            max_drawdown=float(max_drawdown),
            max_attempts_per_hour=int(max_attempts_per_hour),
            default_force_lock_secs=int(default_force_lock_secs),
        )
        # ensure file exists with sane defaults
        self._init_state_if_missing()

    # --- internal state helpers ---
    def _init_state_if_missing(self) -> None:
        s = _atomic_read_json(self._cfg.state_path)
        modified = False
        if not s:
            s = {}
            modified = True

        # ensure keys
        if "locked" not in s:
            s["locked"] = False
            s["locked_until"] = 0.0
            s["lock_reason"] = ""
            modified = True
        if "attempts" not in s:
            s["attempts"] = {"last_hour_ts": 0.0, "count_last_hour": 0}
            modified = True
        if "total_loss_today" not in s:
            s["total_loss_today"] = 0.0
            s["last_loss_date"] = _today_utc_date_str()
            modified = True
        if modified:
            try:
                _atomic_write_json(self._cfg.state_path, s)
            except Exception:
                logger.exception(
                    "risk_guard: failed to initialize state file %s",
                    self._cfg.state_path,
                )

    def _read_state(self) -> Dict[str, Any]:
        return _atomic_read_json(self._cfg.state_path)

    def _write_state(self, s: Dict[str, Any]) -> None:
        _atomic_write_json(self._cfg.state_path, s)

    # --- public API ---
    def guard_check(self) -> Dict[str, Any]:
        """
        Return guard status:
        { "locked": bool, "locked_until": float, "reason": str }
        """
        s = self._read_state()
        locked = bool(s.get("locked", False))
        locked_until = float(s.get("locked_until", 0.0) or 0.0)
        reason = s.get("lock_reason", "")
        if locked and locked_until > 0:
            if _now_ts() >= locked_until:
                # expired — clear lock
                s["locked"] = False
                s["locked_until"] = 0.0
                s["lock_reason"] = ""
                try:
                    self._write_state(s)
                except Exception:
                    logger.exception("risk_guard: failed to clear expired lock")
                return {"locked": False, "locked_until": 0.0, "reason": "ok"}
            else:
                return {"locked": True, "locked_until": locked_until, "reason": reason}
        return {"locked": False, "locked_until": 0.0, "reason": "ok"}

    def register_trade_attempt(self) -> Tuple[bool, str]:
        """
        Register a trade attempt under the hourly quota.
        Returns (ok:bool, reason:str)
        """
        now = _now_ts()
        s = self._read_state()
        at = s.get("attempts", {"last_hour_ts": 0.0, "count_last_hour": 0})
        last_ts = float(at.get("last_hour_ts", 0.0) or 0.0)
        count = int(at.get("count_last_hour", 0))

        # if last_ts is too old -> reset counter window
        if now - last_ts >= _ONE_HOUR:
            last_ts = now
            count = 1
        else:
            count += 1

        at["last_hour_ts"] = last_ts
        at["count_last_hour"] = count
        s["attempts"] = at

        # persist
        try:
            self._write_state(s)
        except Exception:
            logger.exception(
                "risk_guard: failed to write state on register_trade_attempt"
            )

        if count > self._cfg.max_attempts_per_hour:
            logger.warning(
                "RiskGuard: attempts limit reached %s/hour (current %s)",
                self._cfg.max_attempts_per_hour,
                count,
            )
            return False, "attempts_limit_exceeded"
        return True, "ok"

    def register_loss(
        self,
        loss_amount: float,
        lock_on_exceed: bool = True,
        lock_secs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Register a realized loss (negative number expected for loss, positive for gain).
        Returns state summary dict.
        If accumulated losses exceed threshold, optionally force lock.
        """
        if loss_amount is None:
            raise ValueError("loss_amount is required")
        # we accept negative numbers for losses; convert inputs to float
        loss_amount = float(loss_amount)
        s = self._read_state()

        # reset daily bucket if date changed
        today = _today_utc_date_str()
        last_date = s.get("last_loss_date", today)
        if last_date != today:
            s["total_loss_today"] = 0.0
            s["last_loss_date"] = today

        total_loss = float(s.get("total_loss_today", 0.0) or 0.0)
        total_loss += loss_amount  # expect loss_amount negative for a loss
        s["total_loss_today"] = total_loss
        s["last_loss_date"] = today

        # persist
        try:
            self._write_state(s)
        except Exception:
            logger.exception("risk_guard: failed to write state on register_loss")

        # check thresholds
        summary = {
            "total_loss_today": total_loss,
            "locked": False,
            "locked_until": 0.0,
            "reason": "ok",
        }
        if total_loss <= -abs(self._cfg.max_daily_loss):
            # exceed daily loss (losses are negative or zero)
            secs = int(lock_secs or self._cfg.default_force_lock_secs)
            self.force_lock(secs, reason=f"max_daily_loss_exceeded:{total_loss}")
            ns = self._read_state()
            summary.update(
                {
                    "locked": ns.get("locked", True),
                    "locked_until": ns.get("locked_until", 0.0),
                    "reason": ns.get("lock_reason", ""),
                }
            )
            logger.warning(
                "RiskGuard: max_daily_loss exceeded -> locking until %s (loss=%s)",
                summary["locked_until"],
                total_loss,
            )
        return summary

    def reset_daily(self) -> None:
        """
        Reset daily loss counter to 0 (e.g., at UTC midnight by scheduler).
        """
        s = self._read_state()
        s["total_loss_today"] = 0.0
        s["last_loss_date"] = _today_utc_date_str()
        try:
            self._write_state(s)
        except Exception:
            logger.exception("risk_guard: failed to write state on reset_daily")

    def force_lock(self, secs: int, reason: str = "forced") -> None:
        """
        Force a lock for `secs` seconds with a textual reason.
        """
        s = self._read_state()
        s["locked"] = True
        s["locked_until"] = _now_ts() + int(secs)
        s["lock_reason"] = reason
        try:
            self._write_state(s)
            logger.info(
                "RiskGuard: force_lock applied for %s seconds (reason=%s)", secs, reason
            )
        except Exception:
            logger.exception("risk_guard: failed to write state on force_lock")

    # convenience: read snapshot for debugging
    def snapshot(self) -> Dict[str, Any]:
        return self._read_state()

    # optional: clear lock (manual)
    def clear_lock(self) -> None:
        s = self._read_state()
        s["locked"] = False
        s["locked_until"] = 0.0
        s["lock_reason"] = ""
        try:
            self._write_state(s)
        except Exception:
            logger.exception("risk_guard: failed to write state on clear_lock")
