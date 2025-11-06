# spot/orders.py
from core.binance_client import get_client
from binance.enums import SIDE_SELL, ORDER_TYPE_MARKET


def market_sell(symbol: str, quantity: float, dry_run: bool = True):
    if dry_run:
        return {
            "dry_run": True,
            "payload": {
                "symbol": symbol.upper(),
                "side": "SELL",
                "type": "MARKET",
                "quantity": quantity,
            },
        }
    return get_client().create_order(
        symbol=symbol.upper(), side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=quantity
    )
