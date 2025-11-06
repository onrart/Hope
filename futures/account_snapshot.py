from __future__ import annotations
from typing import Dict, Any, List
from futures.futures_client import get_futures_client


def fetch_balance_usdt() -> float:
    c = get_futures_client()
    bals = c.futures_account_balance()
    for b in bals:
        if (b.get("asset") or "").upper() == "USDT":
            try:
                return float(b.get("balance") or b.get("crossWalletBalance") or 0.0)
            except Exception:
                return 0.0
    return 0.0


def fetch_open_positions() -> List[Dict[str, Any]]:
    c = get_futures_client()
    # Position information; returns list of positions across symbols
    ps = c.futures_position_information()
    # Sadece miktarı sıfır olmayanları filtrele
    out: List[Dict[str, Any]] = []
    for p in ps:
        try:
            qty = float(p.get("positionAmt") or 0.0)
        except Exception:
            qty = 0.0
        if qty == 0.0:
            continue
        out.append(
            {
                "symbol": p.get("symbol"),
                "positionAmt": qty,
                "entryPrice": float(p.get("entryPrice") or 0.0),
                "unRealizedProfit": float(p.get("unRealizedProfit") or 0.0),
                "leverage": p.get("leverage"),
                "positionSide": p.get("positionSide") or p.get("positionSide", "BOTH"),
            }
        )
    return out


def fetch_open_orders(symbol: str | None = None) -> List[Dict[str, Any]]:
    c = get_futures_client()
    if symbol:
        return c.futures_get_open_orders(symbol=symbol)
    return c.futures_get_open_orders()


