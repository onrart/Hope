# core/okx_ccxt.py
import ccxt

_okx = None


def _get_okx():
    global _okx
    if _okx is None:
        _okx = ccxt.okx({"enableRateLimit": True})
    return _okx


def get_okx_price(symbol_ccxt: str) -> float | None:
    try:
        t = _get_okx().fetch_ticker(symbol_ccxt)
        return float(t.get("last"))
    except Exception:
        return None
