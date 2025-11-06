# spot/balances.py
from core.binance_client import get_client


def total_usdt() -> float:
    info = get_client().get_asset_balance(asset="USDT")
    free = float(info.get("free", 0.0))
    locked = float(info.get("locked", 0.0))
    return free + locked
