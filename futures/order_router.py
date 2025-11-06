# futures/order_router.py
"""
Emir yönlendirme katmanı:
- BUY  → market LONG aç + closePosition TP/SL kur
- SELL → market SHORT aç + closePosition TP/SL kur
- HOLD → emir vermez

Notlar
- Bracket (TP/SL) kurmadan önce küçük bir gecikme, testnet stabilitesini artırır.
- DRY_RUN=True ise borsa çağrıları yapılmaz; JSON payload döner.
"""

from __future__ import annotations
import time
from typing import Any, Dict

from futures.futures_orders import open_position, attach_bracket_tp_sl
from core.monitoring import inc_counter


def route(
    symbol: str,
    action: str,
    qty: float,
    take_profit: float,
    stop_loss: float,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Parametreler
    ----------
    symbol : str
        Örn: "BTCUSDT"
    action : str
        "BUY" | "SELL" | "HOLD"
    qty : float
        Emir miktarı (rounded/filters futures_orders içinde yapılır)
    take_profit : float
        TP tetik fiyatı
    stop_loss : float
        SL tetik fiyatı
    dry_run : bool
        True ise borsaya göndermeden sadece payload döndürür

    Dönüş
    -----
    dict
        {
          "open": {...} | {"dry_run": True, "payload": {...}},
          "bracket": {
              "tp": {...} | {"dry_run": True, "payload": {...}},
              "sl": {...} | {"dry_run": True, "payload": {...}}
          }
        }
    """
    act = (action or "").upper().strip()
    if act not in {"BUY", "SELL", "HOLD"}:
        raise ValueError(f"Unsupported action: {action}")

    if act == "HOLD":
        return {"status": "HOLD_NO_ROUTE", "symbol": symbol}

    if qty is None or qty <= 0:
        raise ValueError(f"Invalid qty for route: {qty}")

    # 1) Pozisyonu aç
    side = "BUY" if act == "BUY" else "SELL"
    pos = open_position(symbol, side, qty, dry_run=dry_run)
    inc_counter("routes_open_total", 1, {"side": act, "dry_run": str(bool(dry_run)).lower()})

    # Testnet gecikmeleri ve pozisyonun muhasebeleşmesi için küçük bekleme
    time.sleep(0.25)

    # 2) Bracket (closePosition TP/SL)
    position_side = "LONG" if act == "BUY" else "SHORT"

    # Tek deneme yeterli olmazsa, kısa bir gecikmeyle 1 kez daha dene
    try:
        br = attach_bracket_tp_sl(
            symbol,
            position_side=position_side,
            take_profit=take_profit,
            stop_loss=stop_loss,
            dry_run=dry_run,
        )
    except Exception as e1:
        # Bazı durumlarda borsa tarafında milisaniyelik gecikme olabiliyor
        time.sleep(0.35)
        br = attach_bracket_tp_sl(
            symbol,
            position_side=position_side,
            take_profit=take_profit,
            stop_loss=stop_loss,
            dry_run=dry_run,
        )
    finally:
        inc_counter("routes_bracket_total", 1, {"side": act, "dry_run": str(bool(dry_run)).lower()})

    # 3) Operasyonel özet (tek satır için sade alanlar)
    def _extract_order_id(obj: Dict[str, Any]) -> str | None:
        if not isinstance(obj, dict):
            return None
        if "orderId" in obj:
            return str(obj.get("orderId"))
        # dry_run payload’ında id yok; None döndür
        return None

    open_id = _extract_order_id(pos)
    tp_id = _extract_order_id((br or {}).get("tp", {}))
    sl_id = _extract_order_id((br or {}).get("sl", {}))

    summary = {
        "status": "ROUTED" if act in ("BUY", "SELL") else "HOLD",
        "symbol": symbol,
        "side": act,
        "qty": qty,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "orderIds": {"open": open_id, "tp": tp_id, "sl": sl_id},
        "dry_run": bool(dry_run),
    }

    inc_counter("routes_total", 1, {"side": act, "dry_run": str(bool(dry_run)).lower()})
    return {"open": pos, "bracket": br, "summary": summary}
