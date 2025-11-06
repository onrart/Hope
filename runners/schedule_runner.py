# runners/schedule_runner.py
import os, time, json, traceback
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from core.cooldown import is_on_cooldown, mark_trade
from core.coin_info import normalize_symbol
from core.history import log_event
from core.market_data import get_last_price, compute_atr
from core.position_sizer import suggest_qty_safe
from futures.futures_client import get_futures_client
from futures.order_router import route
from futures.futures_filters import fetch_symbol_filters
from futures.futures_balance import futures_total_usdt
from deciders.decider_gemini import decide
from utils.position_tools import (
    move_sl_to_breakeven,
    tighten_trailing_sl,
    rearm_bracket,
)
from core.config import get_working_type

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL = os.getenv("INTERVAL", "15m")
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "120"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.65"))
ATR_MULT = float(os.getenv("ATR_MULTIPLIER", "1.5"))
RR = float(os.getenv("RR", "1.2"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
LEVERAGE = int(os.getenv("LEVERAGE", "5"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "10"))
TICK_SECONDS = int(os.getenv("TICK_SECONDS", "30"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
BE_TRIGGER_USDT = float(
    os.getenv("BE_TRIGGER_USDT", "30")
)  # BE eşiği (ör: +30 USDT kâr)
TRAIL_STEP_USDT = float(os.getenv("TRAIL_STEP_USDT", "50"))  # trailing adımı

TOTAL_USDT_ENV = os.getenv("TOTAL_USDT")


def _total_usdt() -> float:
    if TOTAL_USDT_ENV:
        try:
            return float(TOTAL_USDT_ENV)
        except Exception:
            pass
    return futures_total_usdt() or 1000.0


def _orphan_cleanup(c, sym: str):
    """Pozisyon yoksa closePosition emirlerini iptal et."""
    try:
        pos = c.futures_position_information(symbol=sym)[0]
        if float(pos.get("positionAmt") or 0) != 0:
            return
        for o in c.futures_get_open_orders(symbol=sym):
            if o.get("closePosition"):
                try:
                    c.futures_cancel_order(symbol=sym, orderId=o["orderId"])
                except Exception:
                    pass
    except Exception:
        pass


def _need_rearm(c, sym: str) -> bool:
    """Açık closePosition emirleri mevcut ve workingType ≠ get_working_type() ise rearm gerekli."""
    want = get_working_type()
    try:
        for o in c.futures_get_open_orders(symbol=sym):
            if o.get("closePosition"):
                if (o.get("workingType") or "").upper() != want:
                    return True
    except Exception:
        pass
    return False


def _guards(c, sym: str):
    """Pozisyon varken BE/TRAIL ve rearm işlemleri."""
    try:
        pos = c.futures_position_information(symbol=sym)[0]
        amt = float(pos.get("positionAmt") or 0)
        if amt == 0:
            return {"status": "NO_POSITION"}

        # Çalışan closePosition emirleri farklı tetik tipinde ise bir kez tazele
        if _need_rearm(c, sym):
            re = rearm_bracket(sym, keep_tp=True)

        # Kâr/zararı hesapla (yaklaşık)
        mark = float(c.futures_mark_price(symbol=sym)["markPrice"])
        entry = float(pos.get("entryPrice") or 0)
        pnl_usdt = (mark - entry) * abs(amt)
        if amt < 0:
            pnl_usdt = -pnl_usdt

        out = {"status": "POSITION", "pnl_usdt": pnl_usdt, "mark": mark, "entry": entry}

        # BE eşiği aşıldıysa SL'yi BE'ye taşı
        if pnl_usdt >= BE_TRIGGER_USDT:
            be = move_sl_to_breakeven(sym)
            out["be"] = be

        # Her tik trailing denemesi
        tr = tighten_trailing_sl(sym, step_usdt=TRAIL_STEP_USDT)
        out["trail"] = tr
        return out
    except Exception as e:
        return {"status": "GUARD_ERROR", "error": str(e)}


def tick_once():
    sym = normalize_symbol(SYMBOL)
    c = get_futures_client()

    # Pozisyon yoksa orphan TP/SL temizliği
    _orphan_cleanup(c, sym)

    # Cooldown
    if is_on_cooldown(sym, COOLDOWN_MINUTES):
        msg = {
            "status": "COOLDOWN",
            "symbol": sym,
            "cooldown_minutes": COOLDOWN_MINUTES,
        }
        log_event(msg)
        print(json.dumps(msg, ensure_ascii=False))
        return

    # Piyasa özeti
    last = get_last_price(sym)
    atr14 = compute_atr(sym, interval=INTERVAL, limit=KLINE_LIMIT, period=14)
    snapshot = {"last_price": last, "atr": atr14}

    # Karar
    decision = decide(sym, snapshot)
    action = decision["action"]
    conf = float(decision["confidence"])

    # Güven eşiğinin altı → HOLD
    if conf < MIN_CONFIDENCE or action == "HOLD":
        out = {"status": "HOLD", "symbol": sym, "decision": decision}
        log_event(out)
        print(json.dumps(out, ensure_ascii=False))
        return

    entry = float(decision.get("entry") or last)
    if action == "BUY":
        sl = float(decision.get("stop_loss") or (entry - ATR_MULT * (atr14 or 100)))
        tp = float(decision.get("take_profit") or (entry + RR * (entry - sl)))
    else:
        sl = float(decision.get("stop_loss") or (entry + ATR_MULT * (atr14 or 100)))
        tp = float(decision.get("take_profit") or (entry - RR * (sl - entry)))

    # Boyutlandırma
    total = _total_usdt()
    risk_usdt = total * RISK_PER_TRADE
    qty, meta = suggest_qty_safe(sym, entry, LEVERAGE, risk_usdt, safety_ratio=0.9)
    if qty <= 0:
        out = {"status": "SKIP_INSUFFICIENT_MARGIN", "symbol": sym, "meta": meta}
        log_event(out)
        print(json.dumps(out, ensure_ascii=False))
        return

    # Emir → küçük bir gecikme → bracket (testnet stabilitesi)
    routed = route(sym, action, qty, tp, sl, dry_run=DRY_RUN)
    time.sleep(0.3)

    # Cooldown (sadece gerçek işlemde)
    if action in ("BUY", "SELL") and not DRY_RUN:
        mark_trade(sym)

    # Guard’lar
    guards = _guards(c, sym)

    out = {
        "status": "ROUTED",
        "symbol": sym,
        "decision": decision,
        "route": routed,
        "guards": guards,
        "dry_run": DRY_RUN,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    log_event(out)
    print(json.dumps(out, ensure_ascii=False))


def main_loop():
    while True:
        try:
            tick_once()
        except Exception as e:
            err = {
                "status": "TICK_ERROR",
                "error": str(e),
                "trace": traceback.format_exc(),
            }
            log_event(err)
            print(json.dumps(err, ensure_ascii=False))
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    print(
        "schedule_runner start — SYMBOL:",
        SYMBOL,
        "| WORKING_TYPE:",
        get_working_type(),
        "| DRY_RUN:",
        DRY_RUN,
    )
    main_loop()
