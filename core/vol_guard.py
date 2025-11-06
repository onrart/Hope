# core/vol_guard.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Tuple, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

# =========================
# Ortam değişkenleri
# =========================
# ATR yüzdesi üst eşiği (ör: 0.025 = %2.5)
MAX_ATR_PCT: float = float(os.getenv("MAX_ATR_PCT", "0.025"))
# Borsalar arası yayılım (bps) üst sınırı (örn: 25 bps = %0.25)
MAX_SPREAD_BPS: float = float(os.getenv("MAX_SPREAD_BPS", "25"))
# TP/SL için minimum mesafe (her ikisi birlikte değerlendirilir)
MIN_TP_SL_BPS: float = float(os.getenv("MIN_TP_SL_BPS", "5"))  # 5 bps = %0.05
MIN_TP_SL_USDT: float = float(os.getenv("MIN_TP_SL_USDT", "2.0"))  # en az 2 USDT
# Çalışırken kullanılan tetik tipi (immediate-trigger kontrolünde kullanıyoruz)
WORKING_TYPE: str = os.getenv(
    "WORKING_TYPE", "CONTRACT_PRICE"
).upper()  # MARK_PRICE / CONTRACT_PRICE


def _bps(value: float, ref: float) -> float:
    if ref == 0:
        return 0.0
    return (value / ref) * 10_000.0


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def check_volatility(fused_snapshot: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    fused_snapshot: get_dual_snapshot(...) çıktısındaki "fused" dict'i bekler.
    """
    fused = fused_snapshot or {}
    last = _safe_float(fused.get("last_price"), 0.0)
    atr = _safe_float(fused.get("atr"), 0.0)

    if last <= 0.0:
        # fiyat yoksa engelleme — işlem akışı üst katmanda karar verir
        return True, {"reason": "NO_PRICE", "last": last, "atr": atr}

    atr_pct = (atr / last) if last > 0 else 0.0

    if atr_pct > MAX_ATR_PCT:
        return False, {
            "type": "VOL_GUARD",
            "atr_pct": atr_pct,
            "max_atr_pct": MAX_ATR_PCT,
            "last": last,
            "atr": atr,
        }

    return True, {
        "type": "VOL_GUARD_OK",
        "atr_pct": atr_pct,
        "max_atr_pct": MAX_ATR_PCT,
        "last": last,
        "atr": atr,
    }


def market_health_guard(snap: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Pazar sağlığı kontrolü:
      - Borsa yayılımı (fused.price_spread_bps) MAX_SPREAD_BPS üzerinde mi?
      - ATR/Price (check_volatility)
    """
    fused = (snap or {}).get("fused", {}) or {}
    last = _safe_float(fused.get("last_price"), 0.0)
    spread_bps = fused.get("price_spread_bps")

    # 1) Volatilite guard
    ok_vol, meta_vol = check_volatility(fused)

    # 2) Yayılım guard (spread)
    if spread_bps is not None and _safe_float(spread_bps) > MAX_SPREAD_BPS:
        return False, {
            "type": "SPREAD_GUARD",
            "spread_bps": _safe_float(spread_bps),
            "max_spread_bps": MAX_SPREAD_BPS,
            "volatility": meta_vol,
            "last": last,
        }

    # Volatilite guard tek başına engelliyorsa
    if not ok_vol:
        return False, meta_vol

    # Her şey sağlıklı
    return True, {
        "type": "MARKET_GUARD_OK",
        "spread_bps": _safe_float(spread_bps) if spread_bps is not None else None,
        "max_spread_bps": MAX_SPREAD_BPS,
        "volatility": meta_vol,
        "last": last,
    }


def trade_sanity_guard(
    action: str,
    entry: float,
    tp: float,
    sl: float,
    last: float,
    filters: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Emir sağlığı kontrolü: yön, minimum mesafe, immediate-trigger güvenliği.
    - action: "BUY" (long) veya "SELL" (short)
    - entry/tp/sl/last: fiyatlar
    - filters: {'tick': 0.1, 'step': 0.001, 'tick_str': '0.10', ...}
    """
    action = (action or "").upper()
    entry = _safe_float(entry)
    tp = _safe_float(tp)
    sl = _safe_float(sl)
    last = _safe_float(last)
    tick = _safe_float(filters.get("tick"), 0.1)  # default: 0.1 USDT

    # 1) Yön kontrolü (TP/SL yönü)
    if action == "BUY":
        if not (tp > entry and sl < entry):
            return False, {
                "type": "DIR_GUARD",
                "reason": "For LONG: tp must be > entry and sl must be < entry",
                "action": action,
                "entry": entry,
                "tp": tp,
                "sl": sl,
            }
    elif action == "SELL":
        if not (tp < entry and sl > entry):
            return False, {
                "type": "DIR_GUARD",
                "reason": "For SHORT: tp must be < entry and sl must be > entry",
                "action": action,
                "entry": entry,
                "tp": tp,
                "sl": sl,
            }
    else:
        return False, {
            "type": "DIR_GUARD",
            "reason": "Unknown action",
            "action": action,
        }

    # 2) Minimum mesafe (hem bps hem USDT)
    min_dist_abs = max(MIN_TP_SL_USDT, (MIN_TP_SL_BPS / 10_000.0) * entry)

    if action == "BUY":
        # uzaklıklar
        if (tp - entry) < min_dist_abs or (entry - sl) < min_dist_abs:
            return False, {
                "type": "DIST_GUARD",
                "reason": "Distance too small (LONG)",
                "min_abs": min_dist_abs,
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "MIN_TP_SL_BPS": MIN_TP_SL_BPS,
                "MIN_TP_SL_USDT": MIN_TP_SL_USDT,
            }
    else:  # SELL
        if (entry - tp) < min_dist_abs or (sl - entry) < min_dist_abs:
            return False, {
                "type": "DIST_GUARD",
                "reason": "Distance too small (SHORT)",
                "min_abs": min_dist_abs,
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "MIN_TP_SL_BPS": MIN_TP_SL_BPS,
                "MIN_TP_SL_USDT": MIN_TP_SL_USDT,
            }

    # 3) Immediate-trigger güvenliği
    # Binance mantığı (MARK_PRICE/CONTRACT_PRICE fark etmeksizin tetik koşulu yön kontrolü):
    #  - LONG için:
    #     * TP (SELL TAKE_PROFIT_MARKET) tetiklenir: last >= tp  → bunu engellemek için tp > last + tick
    #     * SL (SELL STOP_MARKET)        tetiklenir: last <= sl  → bunu engellemek için sl < last - tick
    #  - SHORT için:
    #     * TP (BUY TAKE_PROFIT_MARKET)  tetiklenir: last <= tp  → engelle: tp < last - tick
    #     * SL (BUY STOP_MARKET)         tetiklenir: last >= sl  → engelle: sl > last + tick
    if action == "BUY":
        if tp <= last + tick:
            return False, {
                "type": "IMMEDIATE_TRIGGER_GUARD",
                "reason": "LONG TP would trigger immediately",
                "last": last,
                "tp": tp,
                "tick": tick,
            }
        if sl >= last - tick:
            return False, {
                "type": "IMMEDIATE_TRIGGER_GUARD",
                "reason": "LONG SL would trigger immediately",
                "last": last,
                "sl": sl,
                "tick": tick,
            }
    else:  # SELL (short)
        if tp >= last - tick:
            return False, {
                "type": "IMMEDIATE_TRIGGER_GUARD",
                "reason": "SHORT TP would trigger immediately",
                "last": last,
                "tp": tp,
                "tick": tick,
            }
        if sl <= last + tick:
            return False, {
                "type": "IMMEDIATE_TRIGGER_GUARD",
                "reason": "SHORT SL would trigger immediately",
                "last": last,
                "sl": sl,
                "tick": tick,
            }

    # Hepsi geçti
    return True, {
        "type": "TRADE_SANITY_OK",
        "action": action,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "last": last,
        "min_dist_abs": min_dist_abs,
        "tick": tick,
        "working_type": WORKING_TYPE,
    }
