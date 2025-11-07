# utils.py — env helpers
from dotenv import load_dotenv
import os


def load_env():
    load_dotenv()
    # return dict of important envs
    keys = [
        "OKX_API_KEY",
        "OKX_SECRET_KEY",
        "OKX_PASSPHRASE",
        "BINANCE_DEMO_API_KEY",
        "BINANCE_DEMO_SECRET_KEY",
        "BINANCE_API_KEY",
        "BINANCE_SECRET_KEY",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "DRY_RUN",
        "SYMBOL",
        "TIMEFRAME",
        "DATA_POINTS",
        "RUN_INTERVAL_SECS",
        "MAX_ITER",
        "RISK_PER_TRADE_PCT",
        "EXCHANGE_ID",
    ]
    return {k: os.getenv(k) for k in keys}


def env_bool(k: str, default: bool = False) -> bool:
    v = os.getenv(k)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


def get_env(k: str, default: str = "") -> str:
    return os.getenv(k, default)
