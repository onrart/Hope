# futures/futures_client.py
from __future__ import annotations
import os, time
from typing import Optional
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()

_client: Optional[Client] = None


def _resolve_keys():
    testnet = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

    if testnet:
        api_key = os.getenv("BINANCE_DEMO_API_KEY") or os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_DEMO_SECRET_KEY") or os.getenv(
            "BINANCE_SECRET_KEY"
        )
        base_url = "https://testnet.binancefuture.com/fapi"
    else:
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_SECRET_KEY")
        base_url = "https://fapi.binance.com/fapi"

    if not api_key or not api_secret:
        raise RuntimeError("Binance API anahtarları eksik. .env içinde kontrol et.")

    return testnet, api_key, api_secret, base_url


def get_futures_client() -> Client:
    global _client
    if _client is not None:
        return _client

    testnet, api_key, api_secret, base = _resolve_keys()

    # python-binance client
    c = Client(api_key, api_secret, testnet=testnet)
    # Kitaplık testnet’te SPOT URL’lerini ayarlıyor; biz FUTURES URL’ini de net belirtiyoruz.
    c.FUTURES_URL = base

    # İlk ping — bazen 5xx gelebilir; ufak retry
    for i in range(3):
        try:
            c.ping()
            break
        except Exception:
            time.sleep(0.3)
            if i == 2:
                raise

    _client = c
    return _client


def reset_futures_client():
    """Yeni .env yükledikten/anahtar değiştirdikten sonra çağır."""
    global _client
    _client = None
