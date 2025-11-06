# deciders/decider_ollama.py
# Python 3.11 compatible
from __future__ import annotations
import json
import time
import random
import logging
from typing import Any, Callable, Dict, Optional, Tuple

import requests

# import helpers from core
from core.decision_utils import safe_json, normalize_decision

logger = logging.getLogger(__name__)

__all__ = ["decide_with_ollama", "default_post_func"]


# ----------------- small retry/backoff helper -----------------
def retry_with_backoff(
    fn: Callable[..., Any],
    retries: int = 3,
    base: float = 0.5,
    factor: float = 2.0,
    jitter: float = 0.2,
):
    """
    Simple wrapper that retries a callable with exponential backoff + jitter.
    The callable should raise exceptions on transient errors.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise
            sleep = base * (factor ** (attempt - 1))
            # apply jitter +/- jitter fraction
            jitter_factor = 1.0 + (random.random() * 2 - 1) * jitter
            time.sleep(max(0.0, sleep * jitter_factor))


# ----------------- default_post_func (real HTTP) -----------------
def default_post_func(
    url: str, json_payload: Dict[str, Any], timeout: int = 10
) -> requests.Response:
    """
    Default function to perform HTTP POST to Ollama (or equivalent).
    We keep it separate to allow injection/mocking in tests.
    """
    return requests.post(url, json=json_payload, timeout=timeout)


# ----------------- main decision function -----------------
def decide_with_ollama(
    prompt: str,
    ollama_url: str,
    *,
    model: Optional[str] = None,
    timeout: int = 10,
    retries: int = 3,
    backoff_base: float = 0.5,
    post_func: Optional[Callable[[str, Dict[str, Any], int], Any]] = None,
    trace_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Query an Ollama-like endpoint and normalize its response into the canonical decision dict.
    Returns a dict with keys: action, confidence, entry, take_profit, stop_loss
    If anything goes wrong, returns a safe HOLD decision.

    Parameters:
      - prompt: str, the prompt to send
      - ollama_url: str, endpoint URL
      - model: optional model name to include in payload
      - timeout: per-request timeout (seconds)
      - retries: retry attempts on transient failures
      - backoff_base: base backoff in seconds
      - post_func: optional custom callable(url, payload, timeout) -> response-like (for tests)
      - trace_id: optional tracing id for logs
      - dry_run: if True, do not hit network (returns HOLD or simulated result)
    """
    safe_hold = {
        "action": "HOLD",
        "confidence": 0.0,
        "entry": None,
        "take_profit": None,
        "stop_loss": None,
    }

    if dry_run:
        logger.info(
            "decide_with_ollama: dry_run True -> returning HOLD",
            extra={"trace_id": trace_id},
        )
        return safe_hold

    if not ollama_url:
        logger.warning(
            "decide_with_ollama: no ollama_url provided -> HOLD",
            extra={"trace_id": trace_id},
        )
        return safe_hold

    if post_func is None:
        post_func = default_post_func

    payload: Dict[str, Any] = {"prompt": prompt}
    if model:
        payload["model"] = model

    def _call():
        logger.debug(
            "decide_with_ollama: calling ollama",
            extra={"trace_id": trace_id, "payload_preview": str(payload)[:200]},
        )
        resp = post_func(ollama_url, payload, timeout)
        # If it's a requests.Response, use .text, else support duck-typed objects
        text = getattr(resp, "text", None)
        if text is None:
            # maybe resp is a dict-like or has content field
            try:
                text = json.dumps(resp)
            except Exception:
                text = str(resp)
        return text

    try:
        raw_text = retry_with_backoff(
            lambda: _call(), retries=retries, base=backoff_base
        )
    except Exception as e:
        logger.exception(
            "decide_with_ollama: HTTP/transport failure after retries",
            exc_info=e,
            extra={"trace_id": trace_id},
        )
        return safe_hold

    # try to extract JSON object from the returned text
    parsed = safe_json(raw_text)
    if not parsed:
        # if no JSON, try heuristic extraction: look for first line that looks like JSON or 'action: BUY' style
        txt = (raw_text or "").strip()
        # quick check: simple "action: BUY, entry: 100" style parse
        keyvals = _parse_keyvals_from_text(txt)
        if keyvals:
            parsed = keyvals

    if not parsed:
        logger.warning(
            "decide_with_ollama: could not parse response into JSON-like object; returning HOLD",
            extra={"trace_id": trace_id, "raw": (raw_text or "")[:1000]},
        )
        return safe_hold

    # Normalize to canonical decision dict using shared utility
    try:
        norm = normalize_decision(parsed)
        # normalize_decision returns HOLD safe if validation fails
        if not isinstance(norm, dict):
            logger.warning(
                "decide_with_ollama: normalize_decision did not return dict; returning HOLD",
                extra={"trace_id": trace_id},
            )
            return safe_hold
        # Add trace info for debugging if available
        norm["_trace_id"] = trace_id
        return norm
    except Exception as e:
        logger.exception(
            "decide_with_ollama: normalization failed",
            exc_info=e,
            extra={"trace_id": trace_id},
        )
        return safe_hold


# ----------------- helper to parse "key: value" style freeform text -----------------
def _parse_keyvals_from_text(text: str) -> Dict[str, Any]:
    """
    Very small heuristic parser for lines like:
      action: BUY
      confidence: 82%
      entry: 100.5
    Returns dict if finds at least 'action' key, otherwise empty dict.
    """
    out: Dict[str, Any] = {}
    if not text:
        return out
    # split by lines and also support single-line comma separated
    lines = []
    if "\n" in text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
    else:
        # split by commas if single line
        parts = [p.strip() for p in text.split(",") if p.strip()]
        lines = parts
    for line in lines:
        # try match "key: value" or "key = value"
        m = None
        for sep in (":", "=", "-"):
            if sep in line:
                parts = line.split(sep, 1)
                if len(parts) == 2:
                    k = parts[0].strip().lower().replace(" ", "_")
                    v = parts[1].strip()
                    out[k] = v
                    m = True
                    break
        if not m:
            # try "BUY" or "SELL" alone
            if line.strip().upper() in ("BUY", "SELL", "HOLD"):
                out["action"] = line.strip().upper()
    # ensure requires at least 'action'
    if "action" not in out:
        return {}
    return out
