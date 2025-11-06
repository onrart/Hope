# core/decision_utils.py
# Python 3.11 compatible
from __future__ import annotations
import json
import re
import math
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Public API
__all__ = [
    "safe_json",
    "parse_confidence",
    "parse_price",
    "normalize_decision",
    "validate_decision",
]


# ---------- safe_json ----------
def safe_json(text: Optional[str]) -> Dict[str, Any]:
    """
    Try to extract a JSON object from arbitrary text.
    Returns an empty dict on failure.
    """
    if not text:
        return {}
    # fast path
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        # if it's a list with a single dict, return that dict
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj[0]
    except Exception:
        pass

    # try to find the first {...} block
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            candidate = m.group(0)
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                # minor cleanup attempts: replace trailing commas, fix quotes
                candidate2 = re.sub(r",\s*}", "}", candidate)
                candidate2 = re.sub(r",\s*\]", "]", candidate2)
                try:
                    obj = json.loads(candidate2)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass
    except Exception:
        pass

    return {}


# ---------- parse_confidence ----------
def parse_confidence(value: Any) -> Optional[float]:
    """
    Parse various confidence representations into a float in [0.0, 1.0].
    Accepts "82%", "0.82", 82, "very high" (mapped heuristically), etc.
    Returns None if cannot parse.
    """
    if value is None:
        return None
    # if already float or int
    try:
        if isinstance(value, float):
            if math.isfinite(value):
                if 0.0 <= value <= 1.0:
                    return float(value)
                if 1.0 < value <= 100.0:
                    return float(value / 100.0)
                # values >100 considered suspicious -> cap
                if value > 100.0:
                    return 1.0
        if isinstance(value, int):
            if 0 <= value <= 1:
                return float(value)
            if 1 <= value <= 100:
                return float(value / 100.0)
            if value > 100:
                return 1.0
    except Exception:
        pass

    s = str(value).strip()
    if not s:
        return None

    # percent like "82%" or "82 %"
    m = re.match(r"^([0-9]+(?:[.,][0-9]+)?)\s*%$", s)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            return max(0.0, min(1.0, val / 100.0))
        except Exception:
            return None

    # number like "0.82" or "82" (82 treated as percent)
    m = re.match(r"^([0-9]+(?:[.,][0-9]+)?)$", s)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            if 0.0 <= val <= 1.0:
                return val
            if 1.0 < val <= 100.0:
                return val / 100.0
            if val > 100.0:
                return 1.0
        except Exception:
            return None

    # heuristic words
    lowered = s.lower()
    if lowered in ("very high", "high", "strong", "confident", "certain"):
        return 0.95
    if lowered in ("medium", "moderate", "ok"):
        return 0.6
    if lowered in ("low", "weak", "uncertain"):
        return 0.25

    # fallback: try to extract any number inside text
    m = re.search(r"([0-9]+(?:[.,][0-9]+)?)", s)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            if 0.0 <= val <= 1.0:
                return val
            if 1.0 < val <= 100.0:
                return val / 100.0
            if val > 100.0:
                return 1.0
        except Exception:
            pass

    return None


# ---------- parse_price ----------
def parse_price(value: Any) -> Optional[float]:
    """
    Parse price-like strings into float. Returns None if not parseable.
    Accepts "100.5", "100,5", "$100.5", "100 USD", etc.
    """
    if value is None:
        return None
    if isinstance(value, (float, int)):
        try:
            v = float(value)
            if math.isfinite(v):
                return v
            return None
        except Exception:
            return None

    s = str(value).strip()
    if not s:
        return None

    # remove currency symbols and common words
    s = s.replace(",", ".")
    s = re.sub(r"[^\d\.\-eE]", " ", s)
    s = s.strip()
    if not s:
        return None

    # take the first numeric token
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s)
    if not m:
        return None
    try:
        v = float(m.group(0))
        if math.isfinite(v):
            return v
    except Exception:
        return None
    return None


# ---------- validate_decision ----------
def validate_decision(dec: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate normalized decision dict.
    Expected keys: action (BUY/SELL/HOLD), confidence (float 0..1), entry, take_profit, stop_loss (floats or None)
    Returns (True, None) if ok, otherwise (False, reason).
    """
    if not isinstance(dec, dict):
        return False, "decision-not-dict"

    action = (dec.get("action") or "").upper()
    if action not in ("BUY", "SELL", "HOLD"):
        return False, "invalid-action"

    conf = dec.get("confidence")
    if conf is None:
        # allow None but treat as 0.0 in practice
        dec["confidence"] = 0.0
    else:
        try:
            conf_f = float(conf)
            if not (0.0 <= conf_f <= 1.0):
                return False, "confidence-out-of-range"
            dec["confidence"] = conf_f
        except Exception:
            return False, "confidence-not-float"

    # parse/validate prices if present
    entry = dec.get("entry")
    tp = dec.get("take_profit")
    sl = dec.get("stop_loss")

    for name, val in (("entry", entry), ("take_profit", tp), ("stop_loss", sl)):
        if val is None:
            continue
        try:
            v = float(val)
            if not math.isfinite(v):
                return False, f"{name}-not-finite"
            dec[name] = v
        except Exception:
            return False, f"{name}-not-float"

    # logical checks depending on action
    if action == "BUY":
        # if all present: sl < entry < tp
        if (
            dec.get("entry") is not None
            and dec.get("take_profit") is not None
            and dec.get("stop_loss") is not None
        ):
            if not (dec["stop_loss"] < dec["entry"] < dec["take_profit"]):
                return False, "logical-ordering-buy"
    elif action == "SELL":
        if (
            dec.get("entry") is not None
            and dec.get("take_profit") is not None
            and dec.get("stop_loss") is not None
        ):
            if not (dec["stop_loss"] > dec["entry"] > dec["take_profit"]):
                return False, "logical-ordering-sell"

    return True, None


# ---------- normalize_decision ----------
def normalize_decision(raw: Any) -> Dict[str, Any]:
    """
    Normalize various input shapes into a unified decision dict:
    {
        "action": "BUY"|"SELL"|"HOLD",
        "confidence": float (0..1),
        "entry": float | None,
        "take_profit": float | None,
        "stop_loss": float | None
    }

    If normalization fails or validation fails, returns a safe HOLD decision.
    """
    # default safe hold
    safe_hold = {
        "action": "HOLD",
        "confidence": 0.0,
        "entry": None,
        "take_profit": None,
        "stop_loss": None,
    }

    # if raw is string -> try parse as json
    dec: Dict[str, Any] = {}
    if isinstance(raw, str):
        dec = safe_json(raw)
    elif isinstance(raw, dict):
        dec = {k: raw[k] for k in raw}
    else:
        # try to convert to dict if object-like
        try:
            dec = dict(raw)  # may raise
        except Exception:
            logger.debug(
                "normalize_decision: cannot convert raw to dict", exc_info=True
            )
            return safe_hold

    # map possible field names
    mapping = {
        "action": ["action", "trade", "side", "signal"],
        "confidence": ["confidence", "conf", "score", "probability"],
        "entry": ["entry", "price", "entry_price", "entryPrice"],
        "take_profit": ["take_profit", "tp", "takeProfit", "target"],
        "stop_loss": ["stop_loss", "sl", "stopLoss", "stop"],
    }

    out: Dict[str, Any] = {
        "action": None,
        "confidence": None,
        "entry": None,
        "take_profit": None,
        "stop_loss": None,
    }

    # extract mapped values
    for out_key, aliases in mapping.items():
        for a in aliases:
            if a in dec and dec[a] not in (None, ""):
                out[out_key] = dec[a]
                break

    # normalize action (string)
    if isinstance(out["action"], str):
        out["action"] = out["action"].strip().upper()

    # try some heuristic extractions if action missing but text present
    if not out["action"]:
        # check raw dict for free text keys
        for k in ("text", "message", "body"):
            v = dec.get(k)
            if isinstance(v, str):
                if re.search(r"\bBUY\b", v, re.I):
                    out["action"] = "BUY"
                    break
                if re.search(r"\bSELL\b", v, re.I):
                    out["action"] = "SELL"
                    break
        # default to HOLD if still missing
        if not out["action"]:
            out["action"] = "HOLD"

    # parse confidence
    out_conf = (
        parse_confidence(out["confidence"]) if out["confidence"] is not None else None
    )
    if out_conf is None:
        # try to find confidence inside any string fields
        for k in ("text", "message"):
            v = dec.get(k)
            if isinstance(v, str):
                m = re.search(r"([0-9]{1,3})\s*%?", v)
                if m:
                    try:
                        candidate = float(m.group(1))
                        out_conf = candidate / 100.0 if candidate > 1 else candidate
                        break
                    except Exception:
                        pass
    out["confidence"] = float(out_conf) if out_conf is not None else 0.0

    # parse prices
    out["entry"] = parse_price(out["entry"]) if out["entry"] is not None else None
    out["take_profit"] = (
        parse_price(out["take_profit"]) if out["take_profit"] is not None else None
    )
    out["stop_loss"] = (
        parse_price(out["stop_loss"]) if out["stop_loss"] is not None else None
    )

    # final validation
    ok, reason = validate_decision(out)
    if not ok:
        logger.warning(
            "normalize_decision: validation failed -> %s; returning HOLD. raw=%s",
            reason,
            raw,
        )
        return safe_hold

    # ensure action normalization to canonical values
    out["action"] = out["action"].upper()
    return out
