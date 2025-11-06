# core/state.py
import os, json, time, threading
from typing import Dict, Any, Optional

_STATE_LOCK = threading.Lock()


def _state_path() -> str:
    path = os.getenv("STATE_FILE", "state.json")
    # Klasör yoksa oluştur
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    return path


def _now() -> float:
    return time.time()


def _empty_state() -> Dict[str, Any]:
    return {
        "positions": {},  # "BTCUSDT": {...}
        "meta": {
            "created_at": _now(),
            "updated_at": _now(),
            "schema": 1,
        },
    }


def read_state() -> Dict[str, Any]:
    with _STATE_LOCK:
        p = _state_path()
        if not os.path.exists(p):
            st = _empty_state()
            with open(p, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            return st
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # Bozulduysa sıfırla
            st = _empty_state()
            with open(p, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            return st


def write_state(state: Dict[str, Any]) -> None:
    with _STATE_LOCK:
        state.setdefault("meta", {})
        state["meta"]["updated_at"] = _now()
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ---- Position helpers ------------------------------------------------------


def get_position(symbol: str) -> Optional[Dict[str, Any]]:
    st = read_state()
    return st.get("positions", {}).get(symbol.upper())


def set_position(symbol: str, side: str, qty: float, entry: float) -> Dict[str, Any]:
    symbol = symbol.upper()
    st = read_state()
    st.setdefault("positions", {})
    pos = {
        "symbol": symbol,
        "side": side.upper(),  # LONG / SHORT
        "qty": float(qty),
        "entry": float(entry),
        "tp_order_id": None,
        "sl_order_id": None,
        "updated_at": _now(),
    }
    st["positions"][symbol] = pos
    write_state(st)
    return pos


def set_tp_sl_orders(
    symbol: str, tp_order_id: Optional[int], sl_order_id: Optional[int]
) -> Dict[str, Any]:
    symbol = symbol.upper()
    st = read_state()
    pos = st.get("positions", {}).get(symbol)
    if not pos:
        pos = {"symbol": symbol, "side": "LONG", "qty": 0.0, "entry": 0.0}
        st.setdefault("positions", {})[symbol] = pos
    pos["tp_order_id"] = tp_order_id
    pos["sl_order_id"] = sl_order_id
    pos["updated_at"] = _now()
    write_state(st)
    return pos


def clear_position(symbol: str) -> None:
    symbol = symbol.upper()
    st = read_state()
    if st.get("positions", {}).pop(symbol, None) is not None:
        write_state(st)


def all_positions() -> Dict[str, Any]:
    return read_state().get("positions", {})
