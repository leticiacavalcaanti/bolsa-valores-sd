"""Log estruturado (uma linha JSON por evento) para rastrear a vida de uma ordem."""
import json
import logging
import sys
import time

_logger = logging.getLogger("market")
_logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)
_logger.propagate = False


def log_event(event: str, **fields):
    """Eventos do fluxo: ORDER_RECEIVED, ORDER_VALIDATED, ORDER_BOOK_INSERTED,
    MATCH_FOUND, TRADE_EXECUTED, PORTFOLIO_UPDATED, CLIENTS_NOTIFIED, ORDER_REJECTED."""
    _logger.info(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}, default=str))


# ---------------------------------------------------------------- métricas
import threading
from collections import defaultdict, deque

_lock = threading.Lock()
_started = time.time()
_requests = defaultdict(int)          # "METHOD rota status" -> contagem
_latencies = defaultdict(lambda: deque(maxlen=2000))  # "METHOD rota" -> últimas latências (ms)
_events = defaultdict(int)            # contadores de negócio (ordens, trades, rejeições)


def record_request(method: str, route: str, status: int, ms: float):
    with _lock:
        _requests[f"{method} {route} {status}"] += 1
        _latencies[f"{method} {route}"].append(ms)


def count_event(name: str, n: int = 1):
    with _lock:
        _events[name] += n


def _pct(values, p):
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p / 100))], 2) if s else 0.0


def snapshot() -> dict:
    """Métricas em JSON: uptime, requisições por rota/status, latência p50/p95/p99 e contadores de negócio."""
    with _lock:
        lat = {k: {"count": len(v), "p50_ms": _pct(v, 50), "p95_ms": _pct(v, 95), "p99_ms": _pct(v, 99)}
               for k, v in _latencies.items()}
        up = time.time() - _started
        return {"uptime_s": round(up, 1), "requests": dict(_requests), "latency": lat,
                "events": dict(_events),
                "orders_per_s": round(_events.get("orders_received", 0) / up, 3) if up else 0}
