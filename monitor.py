# monitor.py — minimal orchestrator
from utils import load_env, env_bool, get_env
from market import create_client, get_ohlcv, place_order
from model_decide_gemini import query_gemini
from strategy import evaluate_and_build_order
import time
import logging

LOG = logging.getLogger("monitor")


def main():
    cfg = load_env()
    dry_run = env_bool("DRY_RUN", True)
    symbol = get_env("SYMBOL", "BTC/USDT")
    timeframe = get_env("TIMEFRAME", "1m")
    max_iter = int(get_env("MAX_ITER", "1"))
    interval = int(get_env("RUN_INTERVAL_SECS", "60"))

    client = create_client(cfg, dry_run=dry_run)

    i = 0
    while True:
        if max_iter and i >= max_iter:
            LOG.info("Reached max_iter, exiting")
            break
        i += 1
        LOG.info("Iteration %s - fetching OHLCV for %s %s", i, symbol, timeframe)
        ohlcv = get_ohlcv(client, symbol, timeframe, int(get_env("DATA_POINTS", "100")))
        LOG.debug("OHLCV fetched: %s rows", len(ohlcv))

        # Query Gemini
        model_resp = query_gemini(symbol, timeframe, ohlcv, dry_run=dry_run)
        LOG.info("Model response: %s", model_resp)

        # Strategy -> build order payload or skip
        order_payload = evaluate_and_build_order(model_resp, cfg)
        if order_payload:
            LOG.info("Placing order (dry_run=%s): %s", dry_run, order_payload)
            res = place_order(client, order_payload, dry_run=dry_run)
            LOG.info("Order result: %s", res)
        else:
            LOG.info("No actionable signal")

        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
