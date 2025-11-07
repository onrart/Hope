from __future__ import annotations
import threading
import time
import socket
import os
import json
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Tuple, Any


_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_HISTOGRAMS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Dict[str, Any]] = {}
_LOCK = threading.RLock()
_SERVER_THREAD: threading.Thread | None = None
_SERVER: HTTPServer | None = None
_HEALTH: Dict[str, Any] = {}

_SYSTEM_THREAD: threading.Thread | None = None
_SYSTEM_STOP_EVENT = threading.Event()
_SYSTEM_LOCK = threading.RLock()
_SYSTEM_HISTORY_LIMIT = 20
_SYSTEM_STATE: Dict[str, Any] = {
    "running": False,
    "last_run": None,
    "last_error": None,
    "history": [],
}

_SYSTEM_SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
_SYSTEM_INTERVAL = os.getenv("INTERVAL", "15m")
_SYSTEM_KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "120"))
_SYSTEM_MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.65"))
_SYSTEM_ATR_MULT = float(os.getenv("ATR_MULTIPLIER", "1.5"))
_SYSTEM_RR = float(os.getenv("RR", "1.2"))
_SYSTEM_RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
_SYSTEM_LEVERAGE = float(os.getenv("LEVERAGE", "5"))
_SYSTEM_TOTAL_USDT_ENV = os.getenv("TOTAL_USDT")
_SYSTEM_DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")


def _labels_tuple(labels: Dict[str, str] | None) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def inc_counter(name: str, inc: float = 1.0, labels: Dict[str, str] | None = None) -> None:
    key = (name, _labels_tuple(labels))
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0.0) + float(inc)


def observe_histogram(name: str, value_seconds: float, labels: Dict[str, str] | None = None) -> None:
    """
    Basit histogram: sabit bucket seti (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5)
    Prometheus formatında export.
    """
    buckets = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
    key = (name, _labels_tuple(labels))
    with _LOCK:
        h = _HISTOGRAMS.get(key)
        if not h:
            h = {"buckets": buckets, "counts": [0] * (len(buckets) + 1), "sum": 0.0}
            _HISTOGRAMS[key] = h
        # hangi bucket
        idx = len(buckets)
        for i, b in enumerate(buckets):
            if value_seconds <= b:
                idx = i
                break
        h["counts"][idx] += 1
        h["sum"] += float(value_seconds)


def _system_total_usdt() -> float:
    if _SYSTEM_TOTAL_USDT_ENV:
        try:
            return float(_SYSTEM_TOTAL_USDT_ENV)
        except Exception:
            pass
    try:
        from futures.futures_balance import futures_total_usdt

        total = futures_total_usdt()
        if total:
            return float(total)
    except Exception:
        pass
    return 1000.0


def _system_record(entry: Dict[str, Any]) -> None:
    with _SYSTEM_LOCK:
        history = _SYSTEM_STATE.setdefault("history", [])
        history.insert(0, entry)
        if len(history) > _SYSTEM_HISTORY_LIMIT:
            del history[_SYSTEM_HISTORY_LIMIT:]
        _SYSTEM_STATE["last_run"] = entry.get("ts")


def _system_snapshot(symbol: str) -> Dict[str, Any]:
    from core.market_data import (
        get_last_price,
        compute_atr,
        get_klines,
        klines_to_ohlc,
    )

    last_price = get_last_price(symbol)
    atr_val = compute_atr(
        symbol,
        interval=_SYSTEM_INTERVAL,
        limit=_SYSTEM_KLINE_LIMIT,
        period=14,
    )
    klines = get_klines(symbol, interval=_SYSTEM_INTERVAL, limit=_SYSTEM_KLINE_LIMIT)
    ohlc = klines_to_ohlc(klines)
    recent_window = ohlc[-10:] if len(ohlc) > 10 else ohlc
    return {
        "source": "binance",
        "symbol": symbol,
        "interval": _SYSTEM_INTERVAL,
        "kline_limit": _SYSTEM_KLINE_LIMIT,
        "last_price": last_price,
        "atr": atr_val,
        "recent_ohlc": recent_window,
    }


def _system_tick() -> Dict[str, Any]:
    from core.coin_info import normalize_symbol
    from core.position_sizer import compute_position_qty_with_filters
    from futures.futures_filters import fetch_symbol_filters
    from futures.order_router import route
    from deciders.decider_gemini import decide

    symbol = normalize_symbol(_SYSTEM_SYMBOL)
    snapshot = _system_snapshot(symbol)
    decision = decide(symbol, snapshot, dry_run=_SYSTEM_DRY_RUN)

    now_iso = datetime.now(timezone.utc).isoformat()
    action = (decision.get("action") or "HOLD").upper()
    confidence = float(decision.get("confidence") or 0.0)

    result: Dict[str, Any] = {
        "ts": now_iso,
        "symbol": symbol,
        "snapshot": snapshot,
        "decision": decision,
        "action": action,
        "confidence": confidence,
        "status": "HOLD",
        "dry_run": _SYSTEM_DRY_RUN,
        "gemini_text": decision.get("_raw_text"),
    }

    if action not in {"BUY", "SELL"} or confidence < _SYSTEM_MIN_CONFIDENCE:
        result["reason"] = "low_confidence" if confidence < _SYSTEM_MIN_CONFIDENCE else "action_hold"
        return result

    last_price = float(snapshot.get("last_price") or 0.0)
    entry = float(decision.get("entry") or last_price)
    atr_val = float(snapshot.get("atr") or 0.0)

    if action == "BUY":
        stop_loss = float(
            decision.get("stop_loss")
            or (entry - _SYSTEM_ATR_MULT * atr_val if atr_val else entry * 0.99)
        )
        take_profit = float(
            decision.get("take_profit")
            or (entry + _SYSTEM_RR * abs(entry - stop_loss))
        )
    else:
        stop_loss = float(
            decision.get("stop_loss")
            or (entry + _SYSTEM_ATR_MULT * atr_val if atr_val else entry * 1.01)
        )
        take_profit = float(
            decision.get("take_profit")
            or (entry - _SYSTEM_RR * abs(stop_loss - entry))
        )

    result.update({
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    })

    total_usdt = _system_total_usdt()
    risk_usdt = total_usdt * _SYSTEM_RISK_PER_TRADE
    filters = fetch_symbol_filters(symbol)
    qty, reason = compute_position_qty_with_filters(
        balance_usdt=total_usdt,
        risk_usdt=risk_usdt,
        entry_price=entry,
        stop_price=stop_loss,
        side=action,
        leverage=_SYSTEM_LEVERAGE,
        fetch_filters=lambda _: filters,
        symbol=symbol,
        allow_inverse_stop=True,
    )

    result["sizing"] = {
        "qty": qty,
        "reason": reason,
        "risk_usdt": risk_usdt,
        "balance_usdt": total_usdt,
    }

    if qty <= 0:
        result["status"] = "SKIP_SIZING"
        result["reason"] = reason
        return result

    routed = route(symbol, action, qty, take_profit, stop_loss, dry_run=_SYSTEM_DRY_RUN)
    summary = routed.get("summary") if isinstance(routed, dict) else None
    result["status"] = "ROUTED"
    result["route_summary"] = summary
    return result


def _system_loop() -> None:
    global _SYSTEM_THREAD
    while not _SYSTEM_STOP_EVENT.is_set():
        start = time.time()
        try:
            tick_result = _system_tick()
            _system_record(tick_result)
            with _SYSTEM_LOCK:
                _SYSTEM_STATE["last_error"] = None
        except Exception as exc:  # pragma: no cover - defensive guard
            err = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
                "trace": traceback.format_exc(),
            }
            _system_record({"status": "ERROR", "details": err, "ts": err["ts"]})
            with _SYSTEM_LOCK:
                _SYSTEM_STATE["last_error"] = err
        finally:
            elapsed = time.time() - start
            wait = max(0.0, 60.0 - elapsed)
            if _SYSTEM_STOP_EVENT.wait(wait):
                break

    with _SYSTEM_LOCK:
        _SYSTEM_STATE["running"] = False
        _SYSTEM_THREAD = None


def start_system_loop() -> Dict[str, Any]:
    global _SYSTEM_THREAD
    with _SYSTEM_LOCK:
        if _SYSTEM_STATE.get("running") and _SYSTEM_THREAD and _SYSTEM_THREAD.is_alive():
            return {"started": False, "running": True}
        _SYSTEM_STOP_EVENT.clear()
        _SYSTEM_STATE["running"] = True
        _SYSTEM_THREAD = threading.Thread(
            target=_system_loop, name="monitor-system-loop", daemon=True
        )
        _SYSTEM_THREAD.start()
        return {"started": True, "running": True}


def get_system_status() -> Dict[str, Any]:
    with _SYSTEM_LOCK:
        state = json.loads(json.dumps(_SYSTEM_STATE, default=str))
        running = bool(_SYSTEM_THREAD and _SYSTEM_THREAD.is_alive())
        state["running"] = running
        return state


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # type: ignore[override]
        if self.path == "/metrics":
            content = _render_prometheus()
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/health":
            import time as _t
            body = {
                "status": "ok",
                "health": _HEALTH,
                "now": _t.time(),
            }
            b = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if self.path == "/system/status":
            status = get_system_status()
            payload = json.dumps(status, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/dashboard.json":
            try:
                from futures.account_snapshot import (
                    fetch_balance_usdt,
                    fetch_open_positions,
                    fetch_open_orders,
                )
                bal = fetch_balance_usdt()
                pos = fetch_open_positions()
                ords = fetch_open_orders()
                body = {
                    "balance_usdt": bal,
                    "open_positions": pos,
                    "open_orders": ords,
                }
                b = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            except Exception as e:
                msg = json.dumps({"error": repr(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            return
        if self.path == "/dashboard":
            html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hope Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root { color-scheme: dark; }
    body { font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    table { border-collapse: collapse }
    th,td{ border-bottom: 1px solid rgba(148, 163, 184, 0.2) }
    .glass { background: linear-gradient(135deg, rgba(148,163,184,0.12), rgba(51,65,85,0.35)); backdrop-filter: blur(14px); border: 1px solid rgba(148,163,184,0.15); }
  </style>
  </head>
<body class="min-h-screen bg-slate-950 text-slate-100">
  <div class="relative overflow-hidden">
    <div class="absolute inset-0 -z-10 opacity-60">
      <div class="absolute -top-32 -left-10 h-64 w-64 bg-blue-600/40 rounded-full blur-3xl"></div>
      <div class="absolute -bottom-20 right-0 h-72 w-72 bg-emerald-500/30 rounded-full blur-3xl"></div>
    </div>
    <div class="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-10">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="text-sm uppercase tracking-[0.25em] text-slate-400">Monitoring</p>
          <h1 class="text-3xl font-semibold">Hope Trading Control Room</h1>
        </div>
        <div class="flex flex-col items-end gap-2 text-sm text-slate-300">
          <div class="flex items-center gap-4">
            <a class="transition hover:text-white" href="/metrics">Metrics</a>
            <span class="text-slate-600">|</span>
            <a class="transition hover:text-white" href="/health">Health</a>
          </div>
          <div class="flex items-center gap-3">
            <button id="startSystem" class="inline-flex items-center gap-2 rounded-full bg-emerald-500/70 px-4 py-2 font-medium text-white shadow-lg shadow-emerald-950/40 transition hover:-translate-y-[1px] hover:bg-emerald-500">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" viewBox="0 0 24 24">
                <path d="M5 12h14" />
                <path d="M12 5l7 7-7 7" />
              </svg>
              <span>Sistemi Başlat</span>
            </button>
            <span id="systemStatus" class="rounded-full bg-slate-900/80 px-3 py-1 text-xs">
              Pasif
            </span>
          </div>
        </div>
      </header>

      <section class="grid grid-cols-1 gap-4 md:grid-cols-3">
        <article class="glass rounded-2xl p-6 shadow-lg shadow-slate-950/40">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-slate-300">Balance</span>
            <span class="rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold text-emerald-300">USDT</span>
          </div>
          <p id="balance" class="mt-4 text-4xl font-semibold tracking-tight">--</p>
          <p class="mt-2 text-xs text-slate-400">Toplam mevcut bakiyeniz</p>
        </article>
        <article class="glass rounded-2xl p-6 shadow-lg shadow-slate-950/40">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-slate-300">Açık Pozisyon</span>
            <span id="posDirection" class="rounded-full bg-blue-500/15 px-3 py-1 text-xs font-semibold text-blue-300">--</span>
          </div>
          <p id="posCount" class="mt-4 text-4xl font-semibold tracking-tight">--</p>
          <p class="mt-2 text-xs text-slate-400">Toplam pozisyon adedi</p>
        </article>
        <article class="glass rounded-2xl p-6 shadow-lg shadow-slate-950/40">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-slate-300">Açık Emirler</span>
            <span class="rounded-full bg-purple-500/15 px-3 py-1 text-xs font-semibold text-purple-300">Spot &amp; Futures</span>
          </div>
          <p id="ordCount" class="mt-4 text-4xl font-semibold tracking-tight">--</p>
          <p class="mt-2 text-xs text-slate-400">Bekleyen emirleriniz</p>
        </article>
      </section>

      <section class="glass rounded-3xl p-6 shadow-xl shadow-slate-950/30">
        <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-xl font-semibold">Canlı Durum</h2>
            <p class="text-sm text-slate-400">10 saniyede bir otomatik güncellenir</p>
          </div>
          <div class="flex items-center gap-3 text-sm text-slate-300">
            <button id="refresh" class="inline-flex items-center gap-2 rounded-full bg-blue-500/70 px-4 py-2 font-medium text-white shadow-lg shadow-blue-950/40 transition hover:-translate-y-[1px] hover:bg-blue-500">
              <span>Şimdi Yenile</span>
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" viewBox="0 0 24 24">
                <path d="M21 12a9 9 0 1 1-9-9" />
                <path d="M21 3v6h-6" />
              </svg>
            </button>
            <span class="flex items-center gap-2 rounded-full bg-slate-900/80 px-3 py-1 text-xs text-slate-300">
              <span class="relative flex h-2 w-2">
                <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
              </span>
              <span id="ts">--</span>
            </span>
          </div>
        </div>

        <div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div class="glass rounded-2xl border border-slate-800/80 bg-slate-900/40">
            <header class="flex items-center justify-between border-b border-slate-800/70 px-5 py-4">
              <h3 class="text-base font-semibold">Pozisyonlar</h3>
              <span id="posSummary" class="text-xs text-slate-400">--</span>
            </header>
            <div class="max-h-80 overflow-auto">
              <table class="min-w-full text-sm">
                <thead class="bg-slate-900/60 text-slate-400">
                  <tr>
                    <th class="px-4 py-2 text-left">Sembol</th>
                    <th class="px-4 py-2 text-left">Yön</th>
                    <th class="px-4 py-2 text-right">Miktar</th>
                    <th class="px-4 py-2 text-right">Giriş</th>
                    <th class="px-4 py-2 text-right">Gerç. Kar</th>
                    <th class="px-4 py-2 text-right">Kaldıraç</th>
                  </tr>
                </thead>
                <tbody id="posBody"></tbody>
              </table>
            </div>
          </div>

          <div class="glass rounded-2xl border border-slate-800/80 bg-slate-900/40">
            <header class="flex items-center justify-between border-b border-slate-800/70 px-5 py-4">
              <h3 class="text-base font-semibold">Açık Emirler</h3>
              <span id="ordSummary" class="text-xs text-slate-400">--</span>
            </header>
            <div class="max-h-80 overflow-auto">
              <table class="min-w-full text-sm">
                <thead class="bg-slate-900/60 text-slate-400">
                  <tr>
                    <th class="px-4 py-2 text-left">Sembol</th>
                    <th class="px-4 py-2 text-left">Tip</th>
                    <th class="px-4 py-2 text-left">Yön</th>
                    <th class="px-4 py-2 text-right">Fiyat</th>
                    <th class="px-4 py-2 text-right">Durum</th>
                  </tr>
                </thead>
                <tbody id="ordBody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section class="glass rounded-3xl border border-slate-800/70 bg-slate-900/40 p-6 shadow-xl shadow-slate-950/30">
        <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-xl font-semibold">Gemini Karar Akışı</h2>
            <p class="text-sm text-slate-400">Sistem her 1 dakikada bir yeni karar üretir</p>
          </div>
          <div class="text-right text-xs text-slate-400">
            <p>Son Çalışma: <span id="systemLastRun">--</span></p>
            <p>Son Hata: <span id="systemLastError">Yok</span></p>
          </div>
        </div>

        <div class="mt-6 max-h-96 overflow-auto">
          <table class="min-w-full text-sm">
            <thead class="bg-slate-900/60 text-slate-400">
              <tr>
                <th class="px-4 py-2 text-left">Zaman</th>
                <th class="px-4 py-2 text-left">Aksiyon</th>
                <th class="px-4 py-2 text-right">Güven</th>
                <th class="px-4 py-2 text-left">Durum</th>
                <th class="px-4 py-2 text-right">Miktar</th>
                <th class="px-4 py-2 text-left">Gemini Yanıtı</th>
              </tr>
            </thead>
            <tbody id="systemBody"></tbody>
          </table>
        </div>
      </section>

      <footer class="pb-6 text-xs text-slate-500/90">
        <p>© __YEAR__ Hope Trading · İzleme ekranı __HOST__ üzerinde çalışıyor.</p>
      </footer>
    </div>
  </div>
  <script>
    const posBody = () => document.getElementById('posBody');
    const ordBody = () => document.getElementById('ordBody');
    const tsEl = () => document.getElementById('ts');
    const balanceEl = () => document.getElementById('balance');
    const posCountEl = () => document.getElementById('posCount');
    const ordCountEl = () => document.getElementById('ordCount');
    const posSummaryEl = () => document.getElementById('posSummary');
    const ordSummaryEl = () => document.getElementById('ordSummary');
    const posDirectionEl = () => document.getElementById('posDirection');
    const systemStatusEl = () => document.getElementById('systemStatus');
    const systemLastRunEl = () => document.getElementById('systemLastRun');
    const systemLastErrorEl = () => document.getElementById('systemLastError');
    const systemBody = () => document.getElementById('systemBody');
    const startButton = () => document.getElementById('startSystem');

    function formatUsd(value) {
      const val = Number(value || 0);
      return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function directionFromAmt(amount) {
      const v = Number(amount || 0);
      if (!v) return 'Flat';
      return v > 0 ? 'Long' : 'Short';
    }

    function colorForDirection(dir) {
      if (dir === 'Long') return 'bg-emerald-500/15 text-emerald-300';
      if (dir === 'Short') return 'bg-rose-500/15 text-rose-300';
      return 'bg-slate-500/20 text-slate-300';
    }

    function colorForPnl(value) {
      const v = Number(value || 0);
      if (v > 0) return 'text-emerald-400';
      if (v < 0) return 'text-rose-400';
      return 'text-slate-300';
    }

    function escapeHtml(str) {
      return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function formatConfidence(value) {
      const v = Number(value || 0);
      return `${(v * 100).toFixed(1)}%`;
    }

    function formatTs(ts) {
      if (!ts) return '--';
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return String(ts);
      return d.toLocaleString();
    }

    function systemStatusClass(running) {
      return running
        ? 'rounded-full bg-emerald-500/20 px-3 py-1 text-xs font-semibold text-emerald-300'
        : 'rounded-full bg-slate-900/80 px-3 py-1 text-xs text-slate-300';
    }

    async function load() {
      try {
        const r = await fetch('/dashboard.json');
        const d = await r.json();
        balanceEl().textContent = formatUsd(d.balance_usdt || 0);

        const positions = Array.isArray(d.open_positions) ? d.open_positions : [];
        const orders = Array.isArray(d.open_orders) ? d.open_orders : [];

        posCountEl().textContent = positions.length;
        ordCountEl().textContent = orders.length;

        const direction = positions.length ? directionFromAmt(positions[0].positionAmt) : 'Flat';
        const directionTag = posDirectionEl();
        directionTag.textContent = direction;
        directionTag.className = `rounded-full px-3 py-1 text-xs font-semibold ${colorForDirection(direction)}`;

        posSummaryEl().textContent = positions.length
          ? `${positions.length} aktif pozisyon`
          : 'Aktif pozisyon yok';
        ordSummaryEl().textContent = orders.length
          ? `${orders.length} bekleyen emir`
          : 'Bekleyen emir yok';

        const pb = posBody();
        pb.innerHTML = '';
        positions.forEach((p) => {
          const tr = document.createElement('tr');
          const up = Number(p.unRealizedProfit || 0);
          const dir = directionFromAmt(p.positionAmt);
          tr.innerHTML = `
            <td class="px-4 py-2 font-medium text-slate-200">${p.symbol}</td>
            <td class="px-4 py-2">
              <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${colorForDirection(dir)}">${dir}</span>
            </td>
            <td class="px-4 py-2 text-right text-slate-200">${Number(p.positionAmt).toFixed(4)}</td>
            <td class="px-4 py-2 text-right text-slate-200">${Number(p.entryPrice).toFixed(2)}</td>
            <td class="px-4 py-2 text-right ${colorForPnl(up)}">${up.toFixed(2)}</td>
            <td class="px-4 py-2 text-right text-slate-200">${p.leverage || ''}</td>`;
          pb.appendChild(tr);
        });

        const ob = ordBody();
        ob.innerHTML = '';
        orders.forEach((o) => {
          const price = o.stopPrice || o.price || 0;
          const side = o.side || '';
          const sideColor = side === 'BUY' ? 'bg-emerald-500/15 text-emerald-300' : side === 'SELL' ? 'bg-rose-500/15 text-rose-300' : 'bg-slate-500/20 text-slate-300';
          ob.innerHTML += `
            <tr>
              <td class="px-4 py-2 font-medium text-slate-200">${o.symbol || ''}</td>
              <td class="px-4 py-2 text-slate-300">${o.origType || o.type || ''}</td>
              <td class="px-4 py-2">
                <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${sideColor}">${side || '—'}</span>
              </td>
              <td class="px-4 py-2 text-right text-slate-200">${Number(price).toFixed(2)}</td>
              <td class="px-4 py-2 text-right text-slate-300">${o.status || ''}</td>
            </tr>`;
        });

        tsEl().textContent = new Date().toLocaleString();
      } catch (error) {
        console.error('Dashboard güncelleme hatası', error);
        tsEl().textContent = 'Veri alınamadı';
      }
    }

    async function renderSystemStatus() {
      try {
        const res = await fetch('/system/status');
        const data = await res.json();
        const running = Boolean(data.running);
        const statusEl = systemStatusEl();
        statusEl.textContent = running ? 'Çalışıyor' : 'Pasif';
        statusEl.className = systemStatusClass(running);
        systemLastRunEl().textContent = data.last_run ? formatTs(data.last_run) : '--';
        if (data.last_error && data.last_error.error) {
          systemLastErrorEl().textContent = data.last_error.error;
          systemLastErrorEl().className = 'text-rose-400';
        } else {
          systemLastErrorEl().textContent = 'Yok';
          systemLastErrorEl().className = '';
        }

        const body = systemBody();
        body.innerHTML = '';
        const history = Array.isArray(data.history) ? data.history : [];
        history.forEach((item) => {
          const tr = document.createElement('tr');
          const qty = item.sizing && typeof item.sizing.qty !== 'undefined' ? Number(item.sizing.qty) : null;
          const qtyText = Number.isFinite(qty) ? qty.toFixed(4) : '—';
          const preview = (item.gemini_text || '').toString();
          const shortPreview = preview.length > 120 ? `${preview.slice(0, 117)}…` : preview;
          tr.innerHTML = `
            <td class="px-4 py-2 text-slate-300">${escapeHtml(formatTs(item.ts))}</td>
            <td class="px-4 py-2 font-medium text-slate-200">${escapeHtml(item.action || '')}</td>
            <td class="px-4 py-2 text-right text-slate-300">${escapeHtml(formatConfidence(item.confidence))}</td>
            <td class="px-4 py-2 text-slate-300">${escapeHtml(item.status || '')}${item.reason ? ` <span class="text-xs text-slate-500">(${escapeHtml(item.reason)})</span>` : ''}</td>
            <td class="px-4 py-2 text-right text-slate-200">${qtyText}</td>
            <td class="px-4 py-2 text-slate-300" title="${escapeHtml(preview)}">${escapeHtml(shortPreview) || '—'}</td>`;
          body.appendChild(tr);
        });
      } catch (error) {
        console.error('Sistem durumu alınamadı', error);
      }
    }

    async function startSystem() {
      try {
        startButton().disabled = true;
        await fetch('/system/start', { method: 'POST' });
        await renderSystemStatus();
      } catch (error) {
        console.error('Sistem başlatma hatası', error);
      } finally {
        startButton().disabled = false;
      }
    }

    document.getElementById('refresh').addEventListener('click', load);
    startButton().addEventListener('click', startSystem);
    load();
    renderSystemStatus();
    setInterval(load, 10000);
    setInterval(renderSystemStatus, 10000);
  </script>
</body>
</html>"""
            html = html.replace("__YEAR__", time.strftime("%Y")).replace(
                "__HOST__", socket.gethostname()
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # type: ignore[override]
        if self.path == "/system/start":
            res = start_system_loop()
            payload = json.dumps(res, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # no server logs
        return


def _escape_label_value(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _render_prometheus() -> str:
    lines: list[str] = []
    with _LOCK:
        # counters
        for (name, labels_t), value in _COUNTERS.items():
            # HELP/TYPE (opsiyonel minimal)
            lines.append(f"# TYPE {name} counter")
            if labels_t:
                labels = ",".join(f"{k}=\"{_escape_label_value(v)}\"" for k, v in labels_t)
                lines.append(f"{name}{{{labels}}} {value}")
            else:
                lines.append(f"{name} {value}")
        # histograms
        for (name, labels_t), h in _HISTOGRAMS.items():
            buckets = h["buckets"]
            counts = h["counts"]
            acc = 0
            for i, b in enumerate(buckets):
                acc += counts[i]
                base = f"{name}_bucket"
                base_labels = list(labels_t)
                base_labels.append(("le", str(b)))
                labels = ",".join(f"{k}=\"{_escape_label_value(v)}\"" for k, v in sorted(base_labels))
                lines.append(f"{base}{{{labels}}} {acc}")
            # +Inf bucket
            acc += counts[-1]
            base_labels = list(labels_t)
            base_labels.append(("le", "+Inf"))
            labels = ",".join(f"{k}=\"{_escape_label_value(v)}\"" for k, v in sorted(base_labels))
            lines.append(f"{name}_bucket{{{labels}}} {acc}")

            # sum / count
            if labels_t:
                labels = ",".join(f"{k}=\"{_escape_label_value(v)}\"" for k, v in labels_t)
                lines.append(f"{name}_sum{{{labels}}} {h['sum']}")
                lines.append(f"{name}_count{{{labels}}} {acc}")
            else:
                lines.append(f"{name}_sum {h['sum']}")
                lines.append(f"{name}_count {acc}")
    return "\n".join(lines) + "\n"


def start_http_server(port: int = 0) -> int:
    """
    Metrics HTTP sunucusunu başlatır. port=0 verilirse sistem port atar.
    Dönüşte gerçek portu verir.
    """
    global _SERVER_THREAD, _SERVER
    if _SERVER is not None:
        return _SERVER.server_port

    # 0 portu desteklemek için önce soket ile bağlayıp gerçek portu alalım
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    actual_port = sock.getsockname()[1]
    sock.close()

    _SERVER = HTTPServer(("0.0.0.0", actual_port), _Handler)
    _SERVER_THREAD = threading.Thread(target=_SERVER.serve_forever, name="metrics-http", daemon=True)
    _SERVER_THREAD.start()
    return actual_port


def stop_http_server() -> None:
    global _SERVER, _SERVER_THREAD
    if _SERVER is not None:
        try:
            _SERVER.shutdown()
        except Exception:
            pass
        _SERVER.server_close()
    _SERVER = None
    _SERVER_THREAD = None


def set_health(data: Dict[str, Any]) -> None:
    with _LOCK:
        _HEALTH.update(data)


