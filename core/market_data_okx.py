# core/market_data_okx.py
from __future__ import annotations
import time
from typing import Optional, List, Tuple, Dict, Any
import os
import httpx

OKX_BASE = "https://www.okx.com"

OKX_TIMEOUT = float(os.getenv("OKX_TIMEOUT", "10"))
OKX_RETRIES = int(os.getenv("OKX_RETRIES", "2"))
OKX_VERBOSE = os.getenv("OKX_VERBOSE", "false").lower() in ("1", "true", "yes")
OKX_CACHE_TTL = float(os.getenv("OKX_CACHE_TTL_SECONDS", "15"))
_CACHE: Dict[Tuple[str, Tuple[Any, ...]], Tuple[float, Any]] = {}

def _cache_get(k: Tuple[str, Tuple[Any, ...]]):
    now = time.time()
    item = _CACHE.get(k)
    if not item:
        return None
    ts, val = item
    if now - ts <= OKX_CACHE_TTL:
        return val
    return None

def _cache_set(k: Tuple[str, Tuple[Any, ...]], v: Any):
    _CACHE[k] = (time.time(), v)


# --- Sembol normalizasyonu ---
def _to_okx_inst_id(symbol: str) -> str:
    # Binance format: BTCUSDT -> OKX swap instId: BTC-USDT-SWAP
    s = symbol.upper().replace("/", "")
    if s.endswith("USDT"):
        base = s[:-4]
        return f"{base}-USDT-SWAP"
    return f"{s}-USDT-SWAP"


def _log(*args):
    if OKX_VERBOSE:
        print("[OKX]", *args)


def _get(url: str, params: Dict) -> Dict:
    last_exc = None
    for attempt in range(OKX_RETRIES + 1):
        try:
            with httpx.Client(timeout=OKX_TIMEOUT) as client:
                r = client.get(url, params=params)
                r.raise_for_status()
                js = r.json()
                code = str(js.get("code", ""))
                if code != "0":
                    _log("non-zero code:", code, js.get("msg"))
                return js
        except Exception as e:
            last_exc = e
            _log(f"GET fail ({attempt+1}/{OKX_RETRIES+1})", url, params, "->", repr(e))
            time.sleep(0.4 * (attempt + 1))
    if last_exc:
        raise last_exc
    return {}


# ---------- Last Price ----------
def _get_ticker_by_instId(inst_id: str) -> Optional[float]:
    # Tekil enstrüman
    js = _get(f"{OKX_BASE}/api/v5/market/ticker", {"instId": inst_id})
    data = js.get("data") or []
    if data:
        last = data[0].get("last")
        return float(last) if last is not None else None
    return None


def _get_ticker_from_list(inst_id: str) -> Optional[float]:
    # Liste endpointi: daha stabil, bazen tekil boş dönerken burada bulunuyor.
    js = _get(f"{OKX_BASE}/api/v5/market/tickers", {"instType": "SWAP"})
    rows = js.get("data") or []
    for row in rows:
        if row.get("instId") == inst_id:
            last = row.get("last")
            return float(last) if last is not None else None
    return None


def get_last_price(symbol: str) -> Optional[float]:
    inst_id = _to_okx_inst_id(symbol)
    key = ("last", (inst_id,))
    hit = _cache_get(key)
    if hit is not None:
        return float(hit)
    try:
        p = _get_ticker_by_instId(inst_id)
        if p is not None:
            _cache_set(key, p)
            return p
        v = _get_ticker_from_list(inst_id)
        if v is not None:
            _cache_set(key, v)
        return v
    except Exception as e:
        _log("get_last_price error:", repr(e))
        return None


# ---------- ATR ----------
def _true_range(h: float, l: float, prev_close: float) -> float:
    return max(h - l, abs(h - prev_close), abs(l - prev_close))


def _atr_from_ohlc(
    hlc: List[Tuple[float, float, float]], period: int = 14
) -> Optional[float]:
    if len(hlc) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(hlc)):
        h, l, c = hlc[i]
        _, _, prev_c = hlc[i - 1]
        trs.append(_true_range(h, l, prev_c))
    # Wilder
    first_atr = sum(trs[:period]) / period
    atr = first_atr
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _okx_bar(interval: str) -> str:
    m = interval.lower()
    if m == "1h":
        return "1H"
    if m == "2h":
        return "2H"
    if m == "4h":
        return "4H"
    if m == "6h":
        return "6H"
    if m == "12h":
        return "12H"
    if m in ("1d", "1day", "d1"):
        return "1D"
    return interval  # 1m, 3m, 5m, 15m, 30m vb.


def _candles(inst_id: str, bar: str, limit: int) -> List[List[str]]:
    # Önce "candles", olmazsa "history-candles"
    for path in ("/api/v5/market/candles", "/api/v5/market/history-candles"):
        try:
            js = _get(
                f"{OKX_BASE}{path}",
                {"instId": inst_id, "bar": bar, "limit": str(limit)},
            )
            data = js.get("data") or []
            if data:
                return data
        except Exception as e:
            _log("candles path err:", path, repr(e))
    return []


def compute_atr(
    symbol: str, interval: str = "15m", limit: int = 120, period: int = 14
) -> Optional[float]:
    inst_id = _to_okx_inst_id(symbol)
    key = ("atr", (inst_id, interval, int(limit), int(period)))
    hit = _cache_get(key)
    if hit is not None:
        return float(hit)
    bar = _okx_bar(interval)
    try:
        data = _candles(inst_id, bar, limit)
        if not data:
            return None
        # OKX yeni->eski döner; tersine çevir.
        data = list(reversed(data))
        hlc: List[Tuple[float, float, float]] = []
        for row in data:
            # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            try:
                h = float(row[2])
                l = float(row[3])
                c = float(row[4])
                hlc.append((h, l, c))
            except Exception:
                continue
        val = _atr_from_ohlc(hlc, period=period)
        if val is not None:
            _cache_set(key, float(val))
        return val
    except Exception as e:
        _log("compute_atr error:", repr(e))
        return None
