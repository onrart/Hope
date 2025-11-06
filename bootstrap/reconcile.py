# bootstrap/reconcile.py
import os, math
from dotenv import load_dotenv
from typing import Optional, Tuple, Dict, Any, List

load_dotenv()

from futures.futures_client import get_futures_client
from core.state import (
    read_state,
    write_state,
    set_position,
    set_tp_sl_orders,
    clear_position,
)


def _abs_float(x) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return abs(v)
    except Exception:
        return 0.0


def _detect_side_and_qty(
    pos_info: Dict[str, Any],
) -> Tuple[Optional[str], float, float]:
    """
    BOTH modda:
      positionAmt > 0 → LONG
      positionAmt < 0 → SHORT
      0 → no position
    return: (side or None, qty_abs, entry_price)
    """
    amt = float(pos_info.get("positionAmt", "0"))
    entry = float(pos_info.get("entryPrice", "0"))
    if amt > 0:
        return "LONG", abs(amt), entry
    elif amt < 0:
        return "SHORT", abs(amt), entry
    return None, 0.0, entry


def _pick_close_orders(
    orders: List[Dict[str, Any]], symbol: str, side_for_close: str
) -> Tuple[Optional[int], Optional[int]]:
    """
    closePosition=True olan emirler arasından TP/SL orderId'lerini seçer.
    Long pozisyonu kapatan emirlerin side'ı SELL olacaktır; Short'ta BUY.
    """
    tp_id, sl_id = None, None
    for o in orders:
        if o.get("symbol") != symbol.upper():
            continue
        if not o.get("closePosition"):
            continue
        if o.get("side") != side_for_close:
            continue

        t = o.get("type")
        if t == "TAKE_PROFIT_MARKET":
            tp_id = o.get("orderId")
        elif t == "STOP_MARKET":
            sl_id = o.get("orderId")
    return tp_id, sl_id


def _cancel_extras(c, symbol: str, keep_ids: List[int]) -> None:
    """
    Aynı tipten birden fazla closePosition emri varsa keep_ids dışındakileri iptal et.
    """
    open_orders = c.futures_get_open_orders(symbol=symbol.upper())
    for o in open_orders:
        if not o.get("closePosition"):
            continue
        oid = o.get("orderId")
        if oid not in keep_ids:
            try:
                c.futures_cancel_order(symbol=symbol.upper(), orderId=oid)
            except Exception:
                pass


def reconcile_for_symbol(symbol: str) -> Dict[str, Any]:
    c = get_futures_client()
    symbol = symbol.upper()

    # 1) Pozisyonu çek
    pos_list = c.futures_position_information(symbol=symbol)
    pos_info = pos_list[0] if pos_list else None
    if not pos_info:
        # Pozisyon kaydı yoksa, state'ten sil + closePosition emirlerini de temizle
        _cancel_extras(c, symbol, keep_ids=[])
        clear_position(symbol)
        return {"symbol": symbol, "status": "NO_POSITION"}

    side, qty, entry = _detect_side_and_qty(pos_info)

    # 2) Açık emirlerden closePosition TP/SL seç
    open_orders = c.futures_get_open_orders(symbol=symbol)
    close_side = "SELL" if side == "LONG" else ("BUY" if side == "SHORT" else None)
    tp_id, sl_id = (None, None)
    if close_side:
        tp_id, sl_id = _pick_close_orders(open_orders, symbol, close_side)

    # 3) State güncelle
    if side is None or qty == 0.0:
        # Pozisyon yok → state temizle ve varsa TP/SL iptal et
        _cancel_extras(c, symbol, keep_ids=[])
        clear_position(symbol)
        return {"symbol": symbol, "status": "NO_POSITION"}
    else:
        set_position(symbol, side, qty, entry)
        set_tp_sl_orders(symbol, tp_id, sl_id)
        # 4) Fazla closePosition emirleri iptal et (varsa)
        keep = [x for x in [tp_id, sl_id] if x is not None]
        _cancel_extras(c, symbol, keep_ids=keep)
        return {
            "symbol": symbol,
            "status": "OK",
            "side": side,
            "qty": qty,
            "entry": entry,
            "tp_order_id": tp_id,
            "sl_order_id": sl_id,
        }


def main():
    symbols_env = os.getenv("SYMBOLS")  # "BTCUSDT,ETHUSDT" gibi
    if symbols_env:
        symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]
    else:
        symbols = [os.getenv("SYMBOL", "BTCUSDT").upper()]

    results = []
    for sym in symbols:
        try:
            results.append(reconcile_for_symbol(sym))
        except Exception as e:
            results.append({"symbol": sym, "status": "ERROR", "error": str(e)})

    # Basit çıktı
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
