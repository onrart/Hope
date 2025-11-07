# deciders/decider_gemini.py
# Python 3.11 compatible
from __future__ import annotations
import json
import os
import time
import random
import logging
from typing import Any, Callable, Dict, Optional

# import shared helpers
from core.decision_utils import safe_json, normalize_decision

try:  # pragma: no cover - import guard handled via tests
    import google.generativeai as _genai_mod
except Exception:  # pragma: no cover
    try:
        from google import genai as _genai_mod  # type: ignore
    except Exception:  # pragma: no cover
        _genai_mod = None  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["decide", "decide_with_gemini", "default_client_call", "safe_resp_text"]


_DEFAULT_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5-flash")
_PROMPT_INSTRUCTIONS = (
    "You are an automated trading analyst. Given the symbol and market snapshot, "
    "respond ONLY with JSON describing the action to take."
)


def _ensure_genai_configured() -> None:
    if _genai_mod is None:
        raise RuntimeError(
            "google-generativeai (or compatible google.genai client) is required."
        )
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is required")
    configure = getattr(_genai_mod, "configure", None)
    if callable(configure):
        configure(api_key=api_key)


def _call_gemini(prompt: str, *, model: Optional[str] = None, timeout: int = 10):
    """Call Google Gemini using either the new or legacy SDK surface."""

    _ensure_genai_configured()
    model_name = model or _DEFAULT_MODEL

    if hasattr(_genai_mod, "GenerativeModel"):
        generative_model = _genai_mod.GenerativeModel(model_name)
        return generative_model.generate_content(
            prompt, request_options={"timeout": timeout}
        )

    client_cls = getattr(_genai_mod, "Client", None)
    models_iface = getattr(_genai_mod, "models", None)
    if callable(client_cls) and hasattr(models_iface, "generate_content"):
        # Legacy surface (used by unit tests)
        client_cls(api_key=os.getenv("GOOGLE_API_KEY"))
        return models_iface.generate_content(
            model=model_name,
            contents=prompt,
            request_options={"timeout": timeout},
        )

    raise RuntimeError("No compatible Gemini client available")


def _build_prompt(symbol: str, snapshot: Dict[str, Any]) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    return (
        f"{_PROMPT_INSTRUCTIONS}\n"
        f"Symbol: {symbol}\n"
        "Respond with a JSON object with keys action, confidence, entry, take_profit, stop_loss.\n"
        "Market snapshot:\n"
        f"{snapshot_json}\n"
        "The action must be BUY, SELL or HOLD. Confidence must be between 0 and 1."
    )


def decide(
    symbol: str,
    snapshot: Dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout: int = 10,
    retries: int = 3,
    dry_run: bool = False,
    client_call_func: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """High level helper that builds prompt and calls Gemini."""

    trace_id = f"{symbol}-{int(time.time() * 1000)}"
    prompt = _build_prompt(symbol, snapshot)
    captured: Dict[str, Any] = {}

    def _client(prompt_text: str, *, model: Optional[str] = None, timeout: int = timeout):
        call_fn = client_call_func or _call_gemini
        resp = call_fn(prompt_text, model=model, timeout=timeout)
        captured["response"] = resp
        return resp

    decision = decide_with_gemini(
        prompt,
        client_call_func=_client,
        model=model or _DEFAULT_MODEL,
        timeout=timeout,
        retries=retries,
        trace_id=trace_id,
        dry_run=dry_run,
    )
    decision["_prompt"] = prompt
    decision["_model"] = model or _DEFAULT_MODEL
    decision["_raw_text"] = safe_resp_text(captured.get("response"))
    return decision


# ---------------- retry/backoff helper ----------------
def retry_with_backoff_callable(
    fn: Callable[[], Any],
    retries: int = 3,
    base: float = 0.5,
    factor: float = 2.0,
    jitter: float = 0.2,
):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise
            sleep = base * (factor ** (attempt - 1))
            jitter_factor = 1.0 + (random.random() * 2 - 1) * jitter
            time.sleep(max(0.0, sleep * jitter_factor))


# ---------------- safe response extractor ----------------
def safe_resp_text(resp: Any) -> str:
    """
    Try several common shapes to extract textual content from a model client response.
    Accepts:
      - objects with .text, .content, .output, .choices, .message
      - dict-like responses
      - plain strings
    Returns string (may be empty).
    """
    if resp is None:
        return ""
    # if it's already a string
    if isinstance(resp, str):
        return resp

    # dict-like
    if isinstance(resp, dict):
        # common OpenAI-like shape: {'choices':[{'message':{'content':'...'}}]}
        try:
            if (
                "choices" in resp
                and isinstance(resp["choices"], list)
                and resp["choices"]
            ):
                first = resp["choices"][0]
                # try nested message.content
                msg = first.get("message") or first.get("delta") or first
                if isinstance(msg, dict) and "content" in msg:
                    return str(msg["content"])
                # fallback to text-like keys
                if "text" in first:
                    return str(first["text"])
        except Exception:
            pass
        # try 'text' or 'content' keys at top-level
        for k in ("text", "content", "output"):
            if k in resp and resp[k] not in (None, ""):
                return str(resp[k])
        # fallback to JSON string
        try:
            return json.dumps(resp)
        except Exception:
            return str(resp)

    # object-like: try attributes
    for attr in ("text", "content", "output", "message", "result"):
        val = getattr(resp, attr, None)
        if val:
            # choices/message.content nested
            if isinstance(val, (list, tuple)) and val:
                first = val[0]
                if isinstance(first, dict) and "content" in first:
                    return str(first["content"])
                return str(first)
            return str(val)

    # choices attribute (e.g., OpenAI response object)
    choices = getattr(resp, "choices", None)
    if choices:
        try:
            first = choices[0]
            # try message->content or text
            if isinstance(first, dict):
                if (
                    "message" in first
                    and isinstance(first["message"], dict)
                    and "content" in first["message"]
                ):
                    return str(first["message"]["content"])
                if "text" in first:
                    return str(first["text"])
            # object with .message
            msg = getattr(first, "message", None)
            if msg:
                c = getattr(msg, "content", None)
                if c:
                    return str(c)
        except Exception:
            pass

    # last resort: stringify
    try:
        return str(resp)
    except Exception:
        return ""


# ---------------- default client call ----------------
def default_client_call(
    prompt: str, *, model: Optional[str] = None, timeout: int = 10
) -> Any:
    """
    Default placeholder. We intentionally do NOT call any external SDK here,
    because different deployments use different SDKs (Google Gemini, OpenAI, etc.).
    When running in production, pass a concrete `client_call` function that:
        client_call(prompt, model=..., timeout=...) -> response-like
    For tests, you can pass a fake function that returns e.g. a dict or an object
    with .text attribute.
    """
    raise NotImplementedError(
        "default_client_call is a placeholder. Pass client_call_func to decide_with_gemini."
    )


# ---------------- main function ----------------
def decide_with_gemini(
    prompt: str,
    *,
    client_call_func: Optional[Callable[[str], Any]] = None,
    model: Optional[str] = None,
    timeout: int = 10,
    retries: int = 3,
    backoff_base: float = 0.5,
    trace_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Call a Gemini-like model via injected client_call_func and return normalized decision dict.
    client_call_func should be a callable taking (prompt, model=model, timeout=timeout) and returning a response-like object.

    On any failure or invalid parse, returns a safe HOLD dict.
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
            "decide_with_gemini: dry_run True -> returning HOLD",
            extra={"trace_id": trace_id},
        )
        return safe_hold

    if client_call_func is None:
        # Fail safe: do not try to call anything if user didn't provide client
        logger.warning(
            "decide_with_gemini: no client_call_func provided -> returning HOLD",
            extra={"trace_id": trace_id},
        )
        return safe_hold

    def _call():
        # The provided client_call_func may accept signature (prompt, model=model, timeout=timeout)
        try:
            return client_call_func(prompt, model=model, timeout=timeout)
        except TypeError:
            # fallback for client_call_func(prompt) signature
            return client_call_func(prompt)

    try:
        raw_resp = retry_with_backoff_callable(
            lambda: _call(), retries=retries, base=backoff_base
        )
    except Exception as e:
        logger.exception(
            "decide_with_gemini: client call failed after retries",
            exc_info=e,
            extra={"trace_id": trace_id},
        )
        return safe_hold

    # extract textual content
    text = safe_resp_text(raw_resp)
    if not text:
        # try safe_json on raw_resp itself if it's dict-like
        if isinstance(raw_resp, dict):
            parsed = safe_json(json.dumps(raw_resp))
        else:
            parsed = safe_json(None)
    else:
        parsed = safe_json(text)

    # if parsed empty, try key:value heuristic
    if not parsed:
        # attempt simple kv extraction
        kv = _parse_keyvals_from_text(text or str(raw_resp))
        parsed = kv or {}

    if not parsed:
        logger.warning(
            "decide_with_gemini: could not parse model response -> HOLD",
            extra={"trace_id": trace_id, "preview": (text or "")[:500]},
        )
        return safe_hold

    try:
        norm = normalize_decision(parsed)
        if not isinstance(norm, dict):
            logger.warning(
                "decide_with_gemini: normalization did not return dict -> HOLD",
                extra={"trace_id": trace_id},
            )
            return safe_hold
        norm["_trace_id"] = trace_id
        return norm
    except Exception as e:
        logger.exception(
            "decide_with_gemini: normalization error",
            exc_info=e,
            extra={"trace_id": trace_id},
        )
        return safe_hold


# ---------------- small key:value parser like in Ollama module ----------------
def _parse_keyvals_from_text(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not text:
        return out
    lines = []
    if "\n" in text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
    else:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        lines = parts
    for line in lines:
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
            if line.strip().upper() in ("BUY", "SELL", "HOLD"):
                out["action"] = line.strip().upper()
    if "action" not in out:
        return {}
    return out
