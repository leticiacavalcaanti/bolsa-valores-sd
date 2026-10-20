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
