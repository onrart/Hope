# core/binance_connector_spot.py
from .binance_client import get_client
from binance.enums import (
    SIDE_BUY,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
)


def place_market_buy(symbol: str, quantity: float, dry_run: bool = True):
    if dry_run:
        return {
            "dry_run": True,
            "payload": {
                "symbol": symbol.upper(),
                "side": "BUY",
                "type": "MARKET",
                "quantity": quantity,
            },
        }
    return get_client().create_order(
        symbol=symbol.upper(), side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=quantity
    )


def place_limit_order(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    tick: float,
    step: float,
    dry_run: bool = True,
):
    price = round(price / tick) * tick
    quantity = round(quantity / step) * step
    payload = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": ORDER_TYPE_LIMIT,
        "timeInForce": TIME_IN_FORCE_GTC,
        "quantity": quantity,
        "price": price,
    }
    if dry_run:
        return {"dry_run": True, "payload": payload}
    return get_client().create_order(**payload)
