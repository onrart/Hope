# core/binance_client.py
import os, requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_SECRET_KEY") or "").strip()
TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")
SPOT_TESTNET_API = "https://testnet.binance.vision"
SPOT_BASE_URL = (os.getenv("BINANCE_SPOT_BASE_URL") or "").strip()


def _make_client() -> Client:
    if TESTNET:
        c = Client(API_KEY, API_SECRET, testnet=True)
        # spot testnet base url override
        c.API_URL = SPOT_TESTNET_API
        return c
    c = Client(API_KEY, API_SECRET, testnet=False)
    if SPOT_BASE_URL:
        c.API_URL = SPOT_BASE_URL
    return c


_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def ping_ok() -> bool:
    try:
        r = requests.get(get_client().API_URL + "/api/v3/ping", timeout=5)
        return r.status_code == 200
    except Exception:
        return False
