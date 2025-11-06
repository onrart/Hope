# core/market_data.py
from typing import List, Dict, Any, Optional, Tuple
import time
import os
from .indicators import atr
from futures.futures_client import get_futures_client

_TTL = float(os.getenv("MARKET_CACHE_TTL_SECONDS", "15"))
_CACHE: Dict[Tuple[str, Tuple[Any, ...]], Tuple[float, Any]] = {}

def _cache_get(k: Tuple[str, Tuple[Any, ...]]):
    now = time.time()
    item = _CACHE.get(k)
    if not item:
        return None
    ts, val = item
    if now - ts <= _TTL:
        return val
    return None

def _cache_set(k: Tuple[str, Tuple[Any, ...]], v: Any):
    _CACHE[k] = (time.time(), v)


def get_last_price(symbol: str) -> float:
    key = ("last", (symbol.upper(),))
    hit = _cache_get(key)
    if hit is not None:
        return float(hit)
    c = get_futures_client()
    t = c.futures_symbol_ticker(symbol=symbol.upper())
    val = float(t["price"])
    _cache_set(key, val)
    return val


def get_klines(symbol: str, interval: str = "15m", limit: int = 120) -> List[List[Any]]:
    key = ("klines", (symbol.upper(), interval, int(limit)))
    hit = _cache_get(key)
    if hit is not None:
        return hit
    c = get_futures_client()
    data = c.futures_klines(symbol=symbol.upper(), interval=interval, limit=limit)
    _cache_set(key, data)
    return data


def klines_to_ohlc(klines: List[List[Any]]) -> List[Dict[str, float]]:
    ohlc = []
    for k in klines:
        ohlc.append(
            {
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            }
        )
    return ohlc


def compute_atr(
    symbol: str, interval: str = "15m", limit: int = 120, period: int = 14
) -> Optional[float]:
    key = ("atr", (symbol.upper(), interval, int(limit), int(period)))
    hit = _cache_get(key)
    if hit is not None:
        return float(hit)
    ks = get_klines(symbol, interval=interval, limit=limit)
    ohlc = klines_to_ohlc(ks)
    val = atr(ohlc, period=period)
    if val is not None:
        _cache_set(key, float(val))
    return val
