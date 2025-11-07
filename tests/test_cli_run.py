# tests/test_cli_run.py
# This is a tiny runtime smoke-test that imports monitör and runs one iteration
import os
from monitor import main as monitor_main


def test_monitor_runs_one_iteration(monkeypatch):
    os.environ["DRY_RUN"] = "true"
    os.environ["MAX_ITER"] = "1"
    os.environ["SYMBOL"] = "BTC/USDT"
    os.environ["TIMEFRAME"] = "1m"
    os.environ["DATA_POINTS"] = "10"
    # run monitor main (should not raise)
    monitor_main()
