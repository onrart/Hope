# market.py — minimal exchange adapter (ccxt + MockClient fallback)
import os
import logging
from typing import Any, List

LOG = logging.getLogger("market")


class MockClient:
    def __init__(self):
        self._log = logging.getLogger("MockClient")

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        # return synthetic data: [timestamp, open, high, low, close, volume]
        import time, random

        now = int(time.time() * 1000)
        rows = []
        price = 30000.0
        for i in range(limit):
            o = price + random.uniform(-50, 50)
            c = o + random.uniform(-20, 20)
            h = max(o, c) + random.uniform(0, 10)
            l = min(o, c) - random.uniform(0, 10)
            v = random.uniform(0.1, 5)
            rows.append([now - i * 60000, o, h, l, c, v])
            price = c
        return list(reversed(rows))

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self._log.info(
            "MOCK create_order %s %s %s %s %s", symbol, type, side, amount, price
        )
        return {"mock": True, "symbol": symbol, "side": side, "amount": amount}


def create_client(cfg: dict, dry_run: bool = True) -> Any:
    if dry_run:
        return MockClient()
    try:
        import ccxt

        ex_id = cfg.get("EXCHANGE_ID", os.getenv("EXCHANGE_ID", "binance"))
        exchange_class = getattr(ccxt, ex_id)
        exchange = exchange_class(
            {
                "apiKey": cfg.get("BINANCE_API_KEY") or cfg.get("BINANCE_DEMO_API_KEY"),
                "secret": cfg.get("BINANCE_SECRET_KEY")
                or cfg.get("BINANCE_DEMO_SECRET_KEY"),
                "enableRateLimit": True,
            }
        )
        # for testnet certain exchanges need sandbox options — left minimal here
        return exchange
    except Exception as e:
        LOG.exception("Failed to create real client, falling back to MockClient: %s", e)
        return MockClient()


def get_ohlcv(
    client: Any, symbol: str, timeframe: str, limit: int = 100
) -> List[List[float]]:
    # client is either ccxt exchange or MockClient
    return client.fetch_ohlcv(symbol, timeframe, limit=limit)


def place_order(client: Any, payload: dict, dry_run: bool = True):
    # payload: {symbol, side, amount, price(optional), type}
    if dry_run:
        return client.create_order(
            payload["symbol"],
            payload.get("type", "market"),
            payload["side"],
            payload["amount"],
            payload.get("price"),
        )
    try:
        # ccxt create_order signature: symbol, type, side, amount, price, params
        return client.create_order(
            payload["symbol"],
            payload.get("type", "market"),
            payload["side"],
            payload["amount"],
            payload.get("price"),
        )
    except Exception as e:
        LOG.exception("place_order failed: %s", e)
        return {"error": str(e)}
