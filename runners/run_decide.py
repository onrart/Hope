# runners/run_decide.py
import os, json
from core.coin_info import normalize_symbol
from core.index_price import okx_index_price
from deciders.decider_gemini import decide

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")


def main():
    # örnek snapshot (gerçekte buraya indikatör + 24h verileri eklenmeli)
    snapshot = {"last_price": 68000.0, "okx_index": okx_index_price(SYMBOL)}
    d = decide(normalize_symbol(SYMBOL), snapshot)
    print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()
