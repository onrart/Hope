# runners/run_spot.py
import os, json
from core.coin_info import normalize_symbol
from deciders.decider_gemini import decide
from core.binance_connector_spot import place_market_buy

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.65"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")


def main():
    sym = normalize_symbol(SYMBOL)
    snapshot = {"last_price": 68000.0}
    d = decide(sym, snapshot)
    if d["action"] == "BUY" and d["confidence"] >= MIN_CONFIDENCE:
        qty = 10.0 / snapshot["last_price"]  # örnek: 10 USDT
        res = place_market_buy(sym, qty, dry_run=DRY_RUN)
        print(json.dumps({"status": "BUY", "res": res}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "HOLD", "decision": d}, ensure_ascii=False))


if __name__ == "__main__":
    main()
