# strategy.py — simple rule to convert model output to order payload
from typing import Dict, Any
import os


def evaluate_and_build_order(
    model_resp: Dict[str, Any], cfg: dict
) -> Dict[str, Any] | None:
    # model_resp should be {action, confidence}
    action = (model_resp.get("action") or "HOLD").upper()
    try:
        confidence = float(model_resp.get("confidence", 0.0))
    except Exception:
        confidence = 0.0

    # if not confident enough, skip
    min_conf = float(cfg.get("MIN_CONFIDENCE", os.getenv("MIN_CONFIDENCE", 0.6)))
    if confidence < min_conf:
        return None

    if action == "HOLD":
        return None

    # position sizing: simple fixed fraction of notional (RISK_PER_TRADE_PCT)
    risk_pct = float(
        cfg.get("RISK_PER_TRADE_PCT", os.getenv("RISK_PER_TRADE_PCT", 0.01))
    )
    # For minimal example, set amount = 0.001 or use risk_pct on a hypothetical balance
    amount = float(cfg.get("DEFAULT_AMOUNT", 0.001))

    return {
        "symbol": cfg.get("SYMBOL"),
        "side": action,
        "amount": amount,
        "type": "market",
    }
