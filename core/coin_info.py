# core/coin_info.py
from typing import Dict


def normalize_symbol(sym: str) -> str:
    return sym.replace("/", "").upper()


def ccxt_symbol(sym: str) -> str:
    # "BTCUSDT" -> "BTC/USDT"
    s = sym.upper()
    if "/" in s:
        return s
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"
    return s


def base_quote(sym: str) -> Dict[str, str]:
    s = normalize_symbol(sym)
    if s.endswith("USDT"):
        return {"base": s[:-4], "quote": "USDT"}
    return {"base": s[:-3], "quote": s[-3:]}
