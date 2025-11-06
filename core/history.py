# core/history.py
import json, os, time
from typing import Dict, Any

HISTORY_FILE = os.getenv("HISTORY_FILE", "history.jsonl")


def log_event(data: Dict[str, Any]):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), **data}, ensure_ascii=False) + "\n")
