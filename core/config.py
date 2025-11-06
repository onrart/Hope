# core/config.py
from __future__ import annotations
import os
from typing import List
from dotenv import load_dotenv

from core.logging_utils import get_logger

load_dotenv()
log = get_logger("config")


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name, str(default)).lower().strip()
    return v in ("1", "true", "yes", "on")


def get_working_type() -> str:
    """
    Futures closePosition tetiklerinde kullanılacak fiyat referansı.
    Varsayılan: MARK_PRICE (likidasyon ve tetik davranışı için genelde daha güvenli)
    Alternatif: CONTRACT_PRICE
    """
    wt = os.getenv("WORKING_TYPE", "MARK_PRICE").upper()
    if wt not in ("MARK_PRICE", "CONTRACT_PRICE"):
        wt = "MARK_PRICE"
    return wt


def resolved_binance_keys() -> dict:
    """
    Testnet açıksa DEMO anahtarları, değilse PROD anahtarları döndürür.
    """
    testnet = _bool_env("BINANCE_TESTNET", False)

    if testnet:
        api_key = os.getenv("BINANCE_DEMO_API_KEY") or os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_DEMO_SECRET_KEY") or os.getenv(
            "BINANCE_SECRET_KEY"
        )
    else:
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_SECRET_KEY")

    return {
        "testnet": testnet,
        "api_key": api_key,
        "api_secret": api_secret,
    }


def _mask(s: str, keep: int = 3) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return s[0] + "…" + s[-1]
    return s[:keep] + "…" + s[-keep:]


def _require(names: List[str]) -> List[str]:
    missing = [n for n in names if not os.getenv(n)]
    return missing


def validate_env() -> None:
    """
    Çalışma öncesi kritik env doğrulamaları.
    Testnet → DEMO anahtarlar; Prod → PROD anahtarlar.
    """
    keys = resolved_binance_keys()
    google_key = os.getenv("GOOGLE_API_KEY")

    # Zorunlu: Google GenAI
    if not google_key:
        raise RuntimeError("Missing required environment variables: GOOGLE_API_KEY")

    # Binance anahtar çözümü
    if not keys["api_key"] or not keys["api_secret"]:
        if keys["testnet"]:
            raise RuntimeError(
                "Missing DEMO keys: BINANCE_DEMO_API_KEY / BINANCE_DEMO_SECRET_KEY"
            )
        else:
            raise RuntimeError(
                "Missing PROD keys: BINANCE_API_KEY / BINANCE_SECRET_KEY"
            )

    # Bilgilendirici log (maskeli)
    os.environ["RESOLVED_BINANCE_API_KEY"] = keys["api_key"] or ""
    os.environ["RESOLVED_BINANCE_SECRET_KEY"] = keys["api_secret"] or ""
    log.info("[ENV] BINANCE_TESTNET = %s", str(keys["testnet"]).lower())
    log.info("[ENV] BINANCE_API_KEY = %s", _mask(os.getenv("BINANCE_API_KEY", "")))
    log.info(
        "[ENV] BINANCE_SECRET_KEY = %s", _mask(os.getenv("BINANCE_SECRET_KEY", ""))
    )
    log.info(
        "[ENV] BINANCE_DEMO_API_KEY = %s", _mask(os.getenv("BINANCE_DEMO_API_KEY", ""))
    )
    log.info(
        "[ENV] BINANCE_DEMO_SECRET_KEY = %s",
        _mask(os.getenv("BINANCE_DEMO_SECRET_KEY", "")),
    )
    log.info("[ENV] RESOLVED_BINANCE_API_KEY = %s", _mask(keys["api_key"]))
    log.info("[ENV] RESOLVED_BINANCE_SECRET_KEY = %s", _mask(keys["api_secret"]))
    log.info("[ENV] GOOGLE_API_KEY = %s", _mask(google_key))

    # Opsiyonel/önerilenler
    wt = get_working_type()
    log.info("[ENV] WORKING_TYPE = %s", wt)

    # Diğer opsiyoneller (default’larla)
    _ = os.getenv("SYMBOL", "BTCUSDT")
    _ = os.getenv("MIN_CONFIDENCE", "0.65")
    _ = os.getenv("RISK_PER_TRADE", "0.02")
    _ = os.getenv("ATR_MULTIPLIER", "1.5")
    _ = os.getenv("RR", "1.2")
    _ = os.getenv("COOLDOWN_MINUTES", "15")
    _ = os.getenv("LEVERAGE", "5")
    _ = os.getenv("TOTAL_USDT", "")  # override edilirse kullanılıyor


def test_config_log():
    """
    Hızlı notebook testi için: logger’ı ve env çözümünü dener.
    """
    log.info("Logging sistemi aktif!")
    log.warning("Uyarı testidir!")
    log.error("Hata testidir!")
    print("SYMBOL:", os.getenv("SYMBOL", "BTCUSDT"))
    print(
        "BINANCE_FUTURES_BASE_URL:",
        (
            "https://testnet.binancefuture.com"
            if _bool_env("BINANCE_TESTNET", False)
            else "https://fapi.binance.com"
        ),
    )
    print("DRY_RUN:", _bool_env("DRY_RUN", True))
