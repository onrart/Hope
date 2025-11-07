# model_decide_gemini.py — wrapper for Gemini calls (minimal, dry-run mock)
import os
import json
import logging
import requests  # placeholder for real API calls
from typing import Any, Dict

LOG = logging.getLogger("model")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# minimum relative move (fraction) to consider it a real BUY/SELL signal
# default 0.001 = 0.1%
MIN_MOVE_PCT = float(os.getenv("MIN_MOVE_PCT", "0.001"))


def build_prompt(symbol: str, timeframe: str, ohlcv: list) -> str:
    sample = ohlcv[-10:] if len(ohlcv) >= 10 else ohlcv
    prompt = f"""
You are a trading assistant. Given recent OHLCV for {symbol} timeframe {timeframe}, return a single JSON object with fields:

- action: one of "BUY", "SELL", "HOLD"
- confidence: float between 0.0 and 1.0

Recent data (most recent last): {sample}

Return ONLY the JSON object.
"""
    return prompt


def query_gemini(
    symbol: str, timeframe: str, ohlcv: list, dry_run: bool = True
) -> Dict[str, Any]:
    """
    Dry-run mock uses a momentum heuristic with a small threshold:
      - if relative change < MIN_MOVE_PCT -> HOLD
      - if last > prev by >= MIN_MOVE_PCT -> BUY
      - if last < prev by >= MIN_MOVE_PCT -> SELL
    """
    if not isinstance(ohlcv, list) or len(ohlcv) < 2:
        LOG.warning("Not enough OHLCV rows; returning HOLD")
        return {"action": "HOLD", "confidence": 0.0}

    prompt = build_prompt(symbol, timeframe, ohlcv)
    LOG.debug("Prompt prepared (len=%s)", len(prompt))

    # Dry-run / mock logic
    if dry_run or not GEMINI_API_KEY:
        LOG.info(
            "Mocking Gemini response (dry_run=%s, GEMINI_API_KEY_set=%s)",
            dry_run,
            bool(GEMINI_API_KEY),
        )
        try:
            last = float(ohlcv[-1][4])
            prev = float(ohlcv[-2][4])
        except Exception:
            LOG.exception("Failed to parse close prices from OHLCV; returning HOLD")
            return {"action": "HOLD", "confidence": 0.0}

        # compute relative change safely
        if prev != 0:
            rel = (last - prev) / prev
        else:
            rel = last - prev  # fallback absolute diff if prev==0

        if abs(rel) < MIN_MOVE_PCT:
            # movement too small -> HOLD
            return {"action": "HOLD", "confidence": 0.5}

        if rel > 0:
            return {"action": "BUY", "confidence": 0.75}
        else:
            return {"action": "SELL", "confidence": 0.75}

    # Real implementation placeholder:
    url = "https://api.example.com/generate"  # <-- replace with real endpoint
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {"model": GEMINI_MODEL, "prompt": prompt, "max_tokens": 200}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=10)
        r.raise_for_status()
        parsed = r.json()
        if isinstance(parsed, dict) and "action" in parsed:
            return parsed
        text = parsed.get("text") if isinstance(parsed, dict) else r.text
        return json.loads(text)
    except Exception as e:
        LOG.exception("Gemini request failed: %s", e)
        return {"action": "HOLD", "confidence": 0.0}
