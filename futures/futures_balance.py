# futures/futures_balance.py
from __future__ import annotations
from typing import Optional
from futures.futures_client import get_futures_client


def _find_balance(balances, asset: str) -> Optional[dict]:
    asset = asset.upper()
    for b in balances:
        if (b.get("asset") or "").upper() == asset:
            return b
    return None


def futures_total_usdt() -> float:
    """
    USDT toplamını (crossWalletBalance) döndürür.
    Testnet’te faucet sonrası hemen görünür; prod’da gerçek bakiyeyi verir.
    """
    c = get_futures_client()
    balances = c.futures_account_balance()  # v3
    usdt = _find_balance(balances, "USDT")
    if usdt:
        try:
            return float(usdt.get("crossWalletBalance") or usdt.get("balance") or 0.0)
        except Exception:
            pass
    return 0.0
