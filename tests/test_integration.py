# tests/test_integration.py
import os
from utils import load_env
from market import create_client, get_ohlcv, place_order
from model_decide_gemini import query_gemini
from strategy import evaluate_and_build_order


def test_single_iteration_flow(monkeypatch):
    # ensure deterministic env for test
    os.environ["DRY_RUN"] = "true"
    os.environ["SYMBOL"] = "BTC/USDT"
    os.environ["TIMEFRAME"] = "1m"
    os.environ["DATA_POINTS"] = "10"
    os.environ["MIN_CONFIDENCE"] = "0.5"
    cfg = load_env()
    client = create_client(cfg, dry_run=True)

    # fetch ohlcv
    ohlcv = get_ohlcv(
        client,
        cfg.get("SYMBOL"),
        cfg.get("TIMEFRAME"),
        limit=int(os.getenv("DATA_POINTS")),
    )
    assert len(ohlcv) == 10

    model_resp = query_gemini(
        cfg.get("SYMBOL"), cfg.get("TIMEFRAME"), ohlcv, dry_run=True
    )
    # parse model_resp no exception
    payload = evaluate_and_build_order(model_resp, cfg)
    if payload:
        res = place_order(client, payload, dry_run=True)
        assert isinstance(res, dict)
        assert res.get("mock", True) is True
    else:
        assert payload is None
