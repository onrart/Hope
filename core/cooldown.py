# core/cooldown.py
# Python 3.11
from __future__ import annotations
import json
import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN_PATH = os.path.join(os.getcwd(), "cooldown.json")
_LOCK_SUFFIX = ".lock"


def _now_ts() -> float:
    return time.time()


def _ensure_dir_for_file(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _atomic_read_json(path: str) -> Dict[str, Any]:
    """
    Read JSON file under file lock. Return {} on missing/corrupt file.
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
            logger.exception("cooldown: failed to read state file (corrupt?): %s", path)
            return {}


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """
    Atomically write JSON data to path under file lock.
    """
    _ensure_dir_for_file(path)
    lock_path = path + _LOCK_SUFFIX
    tmp_path = path + ".tmp"
    lock = FileLock(lock_path, timeout=5)
    with lock:
        # metadata
        data["_updated_at"] = _now_ts()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


class CooldownManager:
    """
    File-backed cooldown manager.

    Store format (JSON):
    {
      "<SYMBOL>": {
         "until": 1762444443.123,
         "reason": "attach_errors",
         "trace_id": "t-1234",
         "meta": { ... },
         "marked_at": 1762444383.123
      },
      ...
      "_updated_at": 1762444383.123
    }
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or _DEFAULT_COOLDOWN_PATH
        # ensure file exists with empty dict
        if not Path(self._path).exists():
            try:
                _atomic_write_json(self._path, {})
            except Exception:
                logger.exception("cooldown: failed to initialize file %s", self._path)

    # --- internal helpers ---
    def _read_store(self) -> Dict[str, Any]:
        s = _atomic_read_json(self._path)
        # On read, optionally clear expired entries (lazy cleanup)
        now = _now_ts()
        changed = False
        for k, v in list(s.items()):
            if k.startswith("_"):
                continue
            try:
                until = float(v.get("until", 0.0) or 0.0)
            except Exception:
                until = 0.0
            if until and now >= until:
                # expired -> remove
                s.pop(k, None)
                changed = True
        if changed:
            try:
                _atomic_write_json(self._path, s)
            except Exception:
                logger.exception("cooldown: failed to write store during cleanup")
        return s

    def _write_store(self, store: Dict[str, Any]) -> None:
        _atomic_write_json(self._path, store)

    # --- public API ---
    def is_on_cooldown(self, symbol: str) -> bool:
        """
        Return True if the symbol is currently on cooldown.
        """
        if not symbol:
            return False
        symbol = str(symbol).upper()
        s = self._read_store()
        entry = s.get(symbol)
        if not entry:
            return False
        try:
            until = float(entry.get("until", 0.0) or 0.0)
        except Exception:
            return False
        now = _now_ts()
        if until and now < until:
            return True
        # expired -> cleanup and return False
        try:
            # remove expired key and persist
            s.pop(symbol, None)
            self._write_store(s)
        except Exception:
            logger.exception("cooldown: failed to cleanup expired symbol %s", symbol)
        return False

    def mark_trade(
        self,
        symbol: str,
        ttl_seconds: int = 60,
        reason: str = "",
        trace_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Put symbol on cooldown for ttl_seconds from now.
        Returns the stored entry for convenience.
        """
        if not symbol:
            raise ValueError("symbol is required")
        symbol = str(symbol).upper()
        now = _now_ts()
        until = now + int(ttl_seconds or 0)
        entry = {
            "until": until,
            "reason": reason or "",
            "trace_id": trace_id,
            "meta": meta or {},
            "marked_at": now,
        }
        s = self._read_store()
        s[symbol] = entry
        try:
            self._write_store(s)
        except Exception:
            logger.exception(
                "cooldown: failed to write store on mark_trade for %s", symbol
            )
        return entry

    def remove(self, symbol: str) -> bool:
        """
        Remove a symbol from cooldown store. Returns True if removed.
        """
        if not symbol:
            return False
        symbol = str(symbol).upper()
        s = self._read_store()
        existed = symbol in s
        if existed:
            s.pop(symbol, None)
            try:
                self._write_store(s)
            except Exception:
                logger.exception(
                    "cooldown: failed to write store on remove for %s", symbol
                )
        return existed

    def keys(self) -> List[str]:
        """
        List non-metadata keys currently present in the store (after cleanup).
        """
        s = self._read_store()
        return [k for k in s.keys() if not k.startswith("_")]

    def snapshot(self) -> Dict[str, Any]:
        """
        Return the raw store (including metadata). Note: expired entries are cleaned up first.
        """
        return self._read_store()

    def clear(self) -> None:
        """
        Remove all cooldown entries (useful for tests).
        """
        try:
            self._write_store({})
        except Exception:
            logger.exception("cooldown: failed to clear store")

    def get_entry(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Return the raw entry for symbol (or None). This does NOT auto-delete expired entries,
        but uses the cleaned store so expired items are normally not present.
        """
        if not symbol:
            return None
        symbol = str(symbol).upper()
        s = self._read_store()
        return s.get(symbol)

    # convenience: expire all expired entries now (explicit)
    def clear_expired(self) -> None:
        try:
            self._read_store()  # read_store performs lazy cleanup and persists if needed
        except Exception:
            logger.exception("cooldown: clear_expired encountered error")
