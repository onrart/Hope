# core/index_price.py
from .okx_ccxt import get_okx_price
from .coin_info import ccxt_symbol


def okx_index_price(symbol_spot: str) -> float | None:
    # ör: BTCUSDT -> BTC/USDT
    return get_okx_price(ccxt_symbol(symbol_spot))
