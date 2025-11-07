# spot.py — helper functions for spot account queries
def get_balance(client, currency: str = "USDT"):
    try:
        bal = client.fetch_balance()
        return bal.get(currency) or bal
    except Exception:
        return None


def list_open_orders(client, symbol: str = None):
    try:
        if symbol:
            return client.fetch_open_orders(symbol)
        return client.fetch_open_orders()
    except Exception:
        return []
