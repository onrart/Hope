import os
from pathlib import Path
from dotenv import load_dotenv

import pytest


def _write_env(tmp_path: Path, lines: str):
    p = tmp_path / ".env"
    p.write_text(lines, encoding="utf-8")
    return p


def test_validate_env_with_testnet(tmp_path, monkeypatch):
    # Hazır bir .env yaz
    env_text = """
BINANCE_TESTNET=true
BINANCE_DEMO_API_KEY=demo_key
BINANCE_DEMO_SECRET_KEY=demo_secret
GOOGLE_API_KEY=dummy
WORKING_TYPE=MARK_PRICE
SYMBOL=BTCUSDT
""".strip()
    _write_env(tmp_path, env_text)

    # Çalışma dizininde bu .env görülsün
    monkeypatch.chdir(tmp_path)

    # Ortamı temizle: process env yerine .env yüklensin
    for k in list(os.environ.keys()):
        if k.startswith("BINANCE") or k in ("GOOGLE_API_KEY", "WORKING_TYPE", "SYMBOL"):
            os.environ.pop(k, None)

    # .env'i zorla yükle (override=True)
    load_dotenv(dotenv_path=tmp_path / ".env", override=True)

    from importlib import reload
    import core.config as cfg
    reload(cfg)

    # validate_env patlamamalı ve resolved anahtarlar set edilmeli
    cfg.validate_env()

    keys = cfg.resolved_binance_keys()
    assert keys["testnet"] is True
    assert keys["api_key"] == "demo_key"
    assert keys["api_secret"] == "demo_secret"

    assert cfg.get_working_type() == "MARK_PRICE"


def test_get_working_type_defaults(monkeypatch):
    monkeypatch.delenv("WORKING_TYPE", raising=False)
    from importlib import reload
    import core.config as cfg
    reload(cfg)
    assert cfg.get_working_type() in ("MARK_PRICE", "CONTRACT_PRICE")


def test_resolved_binance_keys_prod_requires_keys(tmp_path, monkeypatch):
    env_text = """
BINANCE_TESTNET=false
GOOGLE_API_KEY=dummy
""".strip()
    _write_env(tmp_path, env_text)
    monkeypatch.chdir(tmp_path)

    # Ortam temiz
    for k in list(os.environ.keys()):
        if k.startswith("BINANCE") or k == "GOOGLE_API_KEY":
            os.environ.pop(k, None)

    # .env'i zorla yükle (override=True)
    load_dotenv(dotenv_path=tmp_path / ".env", override=True)

    # Her ihtimale karşı prod anahtarlarını boşla ki validate_env hata versin
    monkeypatch.setenv("BINANCE_API_KEY", "", prepend=False)
    monkeypatch.setenv("BINANCE_SECRET_KEY", "", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "", prepend=False)
    monkeypatch.setenv("BINANCE_DEMO_SECRET_KEY", "", prepend=False)

    from importlib import reload
    import core.config as cfg
    reload(cfg)

    with pytest.raises(RuntimeError):
        cfg.validate_env()


