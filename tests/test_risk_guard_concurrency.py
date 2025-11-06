import multiprocessing
import time
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.risk_guard import RiskGuard


def worker(state_path, max_daily_loss=1000):
    """
    Each process instantiates its own RiskGuard pointing to the same state file
    and calls register_trade_attempt() once.
    """
    rg = RiskGuard(path=state_path, max_daily_loss=max_daily_loss)
    ok, reason = rg.register_trade_attempt()
    # Optionally register result into a file for debugging
    # print("worker result:", ok, reason)


def test_concurrent_register_attempts(tmp_path):
    state_file = str(tmp_path / "test_state.json")
    # ensure clean
    if os.path.exists(state_file):
        os.remove(state_file)

    procs = []
    n = 5
    for _ in range(n):
        p = multiprocessing.Process(target=worker, args=(state_file,))
        p.start()
        procs.append(p)

    for p in procs:
        p.join(timeout=10)
        assert not p.is_alive()

    # after all processes joined, read state and assert attempts count
    with open(state_file, "r", encoding="utf-8") as f:
        s = json.load(f)

    # Adjust these keys according to your RiskGuard internal state layout
    attempts = s.get("attempts", {})
    count_last_hour = attempts.get("count_last_hour", attempts.get("count", 0))
    assert (
        count_last_hour == n
    ), f"expected {n} attempts, got {count_last_hour}, state: {s}"
