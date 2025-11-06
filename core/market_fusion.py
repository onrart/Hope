# core/market_fusion.py
from __future__ import annotations
from typing import Dict, Any, Optional
import os

from core.coin_info import normalize_symbol
from core.market_data import get_last_price as bin_last, compute_atr as bin_atr

# >>> YENİ: OKX verilerini doğrudan yeni modülden çek
from core.market_data_okx import get_last_price as okx_last, compute_atr as okx_atr
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from core.monitoring import set_health

FUSION_VERBOSE = os.getenv("FUSION_VERBOSE", "false").lower() in ("1", "true", "yes")


def _log(*args):
    if FUSION_VERBOSE:
        print("[FUSION]", *args)


def _pack(
    source_name: str, last: Optional[float], atr: Optional[float]
) -> Dict[str, Any]:
    return {
        "last_price": last if last is not None else None,
        "atr": atr if atr is not None else None,
        "available": (last is not None and atr is not None),
        "source": source_name,
    }


def get_dual_snapshot(
    symbol: str, interval: str = "15m", limit: int = 120, period: int = 14
) -> Dict[str, Any]:
    sym = normalize_symbol(symbol)

    # Paralel çekim
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {
            ex.submit(bin_last, sym): ("bin", "last"),
            ex.submit(bin_atr, sym, interval, limit, period): ("bin", "atr"),
            ex.submit(okx_last, sym): ("okx", "last"),
            ex.submit(okx_atr, sym, interval, limit, period): ("okx", "atr"),
        }
        results: Dict[str, Dict[str, Any]] = {"bin": {}, "okx": {}}
        for f in as_completed(futs):
            src, kind = futs[f]
            try:
                results[src][kind] = f.result()
            except Exception:
                results[src][kind] = None

    b_last = results["bin"].get("last")
    b_atr = results["bin"].get("atr")
    binance = _pack("BINANCE", b_last, b_atr)

    o_last = results["okx"].get("last")
    o_atr = results["okx"].get("atr")
    okx = _pack("OKX", o_last, o_atr)

    # FUSION: Mevcut kurgu → her iki kaynağı yan yana sunalım.
    fused: Dict[str, Any] = {
        "last_price": None,
        "atr": None,
        "price_spread_abs": None,
        "price_spread_bps": None,
        "sources": [],
    }

    # Öncelik: Binance → OKX (sen istemiştin)
    if binance["available"]:
        fused["last_price"] = binance["last_price"]
        fused["atr"] = binance["atr"]
        fused["sources"].append("BINANCE")
    if okx["available"]:
        # Eğer Binance de varsa, spread hesapla
        if fused["last_price"] is not None:
            try:
                p_bin = float(fused["last_price"])
                p_okx = float(okx["last_price"])
                fused["price_spread_abs"] = p_okx - p_bin
                fused["price_spread_bps"] = (fused["price_spread_abs"] / p_bin) * 10_000
            except Exception:
                pass
        else:
            # Binance yoksa OKX'i direkt kullan
            fused["last_price"] = okx["last_price"]
            fused["atr"] = okx["atr"]
        fused["sources"].append("OKX")

    _log("BINANCE:", binance)
    _log("OKX    :", okx)
    _log("FUSED  :", fused)

    # Health: snapshot tazeliği
    try:
        set_health({"last_snapshot_ts": time.time()})
    except Exception:
        pass

    return {"binance": binance, "okx": okx, "fused": fused}
