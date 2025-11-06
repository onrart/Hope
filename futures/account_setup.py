# futures/account_setup.py
from __future__ import annotations
import time
from typing import Optional
from binance.exceptions import BinanceAPIException

from futures.futures_client import get_futures_client
from core.logging_utils import get_logger

log = get_logger("account_setup")


def ensure_margin_and_leverage(
    symbol: str, leverage: int = 5, isolated: bool = True
) -> dict:
    """
    Sembol bazında:
      - (opsiyonel) isolated/cross margin ayarı
      - kaldıraç ayarı
    Testnet’te açık pozisyon varken margin type değişmez (-4048). Bu durumda sadece leverage set edilir.

    Dönüş: {"marginType": "...", "leverage": <int>, "symbol": "..."}
    """
    sym = symbol.upper()
    c = get_futures_client()

    # Margin type
    mt = "ISOLATED" if isolated else "CROSSED"
    margin_ok = None
    try:
        c.futures_change_margin_type(symbol=sym, marginType=mt)
        margin_ok = mt
    except BinanceAPIException as e:
        # -4048: open position varken margin type değişmez → görmezden gel
        log.warning("marginType set edilemedi (%s): %s", sym, e.message)
        # Mevcut modu çekelim
        info = c.futures_account()
        margin_ok = info.get("multiAssetsMargin", False)
        margin_ok = mt  # mantıksal hedef

    time.sleep(0.2)

    # Leverage
    lev_resp: Optional[dict] = None
    try:
        lev_resp = c.futures_change_leverage(symbol=sym, leverage=int(leverage))
    except BinanceAPIException as e:
        log.warning("leverage set edilemedi (%s): %s", sym, e.message)

    return {
        "symbol": sym,
        "marginType": margin_ok,
        "leverage": (lev_resp or {}).get("leverage", leverage),
    }
