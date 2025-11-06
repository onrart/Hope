import time
from types import SimpleNamespace

import core.market_fusion as fusion
import core.market_data as binmd
import core.market_data_okx as okxmd


def test_cache_hits_reduce_calls(monkeypatch):
    calls = {"last": 0, "klines": 0}

    def _last(symbol):
        calls["last"] += 1
        return 100.0

    def _klines(symbol, interval="15m", limit=120):
        calls["klines"] += 1
        return [[0, 0, 1, 0, 1, 0]] * 120  # minimal OHLC

    monkeypatch.setattr(binmd, "get_futures_client", lambda: SimpleNamespace())
    monkeypatch.setattr(binmd, "get_last_price", _last)
    monkeypatch.setattr(binmd, "get_klines", _klines)

    # İlk atr hesaplaması cache set eder
    _ = binmd.compute_atr("BTCUSDT")
    # Tekrar çağrıda klines tekrar çekilmemeli
    _ = binmd.compute_atr("BTCUSDT")
    assert calls["klines"] == 1


def test_parallel_snapshot_faster_than_serial(monkeypatch):
    # Her çağrı ~0.2s uyusun. Paralelde toplam süre ~0.25-0.35 civarı olur.
    def sleep_ret(v):
        time.sleep(0.2)
        return v

    monkeypatch.setattr(fusion, "bin_last", lambda s: sleep_ret(100.0))
    monkeypatch.setattr(fusion, "bin_atr", lambda s, i, l, p: sleep_ret(1.0))
    monkeypatch.setattr(fusion, "okx_last", lambda s: sleep_ret(100.1))
    monkeypatch.setattr(fusion, "okx_atr", lambda s, i, l, p: sleep_ret(1.1))

    t0 = time.perf_counter()
    _ = fusion.get_dual_snapshot("BTCUSDT")
    dt = time.perf_counter() - t0
    assert dt < 0.5  # seri olsa ~0.8s olurdu


