"""Matching engine, livro de ofertas e carteira.

Consistência: cada ativo tem seu próprio engine (lock por ativo). As ordens de um mesmo
ativo entram uma a uma (ordem total e prioridade temporal = id da ordem); ativos
diferentes são processados em paralelo. Cada ordem e as negociações que ela gera são
gravadas em uma única transação no PostgreSQL (tudo ou nada).

O que protege o dinheiro e os ativos entre ativos diferentes:
- Reserva: saldo disponível = saldo - soma das compras abertas; ativos disponíveis =
  posição - soma das vendas abertas. É calculado depois de travar a conta no banco.
- Ordem de travamento: antes de casar, o engine trava (FOR UPDATE) as contas do
  investidor e de todas as contrapartes que vão negociar, sempre em ordem crescente
  de user_id. Sem ciclo de espera, não há deadlock entre ativos.
"""
import os
import threading
from decimal import Decimal

from .db import clean, transaction
from .observability import log_event

INITIAL_BALANCE = Decimal(os.environ.get("INITIAL_BALANCE", "100000"))
NPC_BALANCE = Decimal(os.environ.get("NPC_BALANCE", "500000"))
NPC_INITIAL_SHARES = int(os.environ.get("NPC_INITIAL_SHARES", "1000"))
OPEN_STATUSES = ("OPEN", "PARTIAL")

_symbol_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _symbol_lock(symbol: str) -> threading.Lock:
    """Lock do engine do ativo. Os ativos são fixos; símbolo desconhecido é rejeitado
    (evita crescer o dicionário com símbolos inventados)."""
    with _locks_guard:
        if symbol not in _symbol_locks:
            with transaction() as cur:
                cur.execute("SELECT symbol FROM market.assets")
                for row in cur.fetchall():
                    _symbol_locks.setdefault(row["symbol"], threading.Lock())
        lock = _symbol_locks.get(symbol)
    if lock is None:
        raise MarketError("Ativo inexistente", 404)
    return lock


class MarketError(Exception):
    """Erro de regra de negócio (ordem rejeitada, ativo inexistente, etc.)."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------- consultas

def ensure_account(cur, user_id: int, username: str):
    """Cria a conta no primeiro acesso. Agentes (prefixo npc_) recebem também uma carteira inicial,
    para haver ativos à venda; o prefixo só pode ser obtido via auth-service interno."""
    is_npc = username.startswith("npc_")
    cur.execute(
        "INSERT INTO market.accounts (user_id, username, balance) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO NOTHING",
        (user_id, username, NPC_BALANCE if is_npc else INITIAL_BALANCE),
    )
    if is_npc and cur.rowcount == 1:
        cur.execute(
            "INSERT INTO market.positions (user_id, symbol, quantity, avg_price) "
            "SELECT %s, symbol, %s, open_price FROM market.assets",
            (user_id, NPC_INITIAL_SHARES),
        )


def list_assets():
    with transaction() as cur:
        cur.execute(
            "SELECT symbol, name, open_price, last_price, volume, "
            "ROUND((last_price - open_price) / open_price * 100, 2) AS change_pct "
            "FROM market.assets ORDER BY symbol"
        )
        return clean(cur.fetchall())


def get_book(symbol: str, depth: int = 10):
    """Livro agregado por nível de preço: melhores compras e vendas."""
    with transaction() as cur:
        _require_asset(cur, symbol)
        return _book(cur, symbol, depth)


def _book(cur, symbol: str, depth: int = 10):
    query = (
        "SELECT price, SUM(quantity - filled) AS quantity FROM market.orders "
        "WHERE symbol = %s AND side = %s AND status IN ('OPEN', 'PARTIAL') "
        "GROUP BY price ORDER BY price {} LIMIT %s"
    )
    cur.execute(query.format("DESC"), (symbol, "BUY", depth))
    bids = cur.fetchall()
    cur.execute(query.format("ASC"), (symbol, "SELL", depth))
    asks = cur.fetchall()
    return clean({"symbol": symbol, "bids": bids, "asks": asks})


def get_portfolio(user_id: int, username: str):
    with transaction() as cur:
        ensure_account(cur, user_id, username)
        cur.execute("SELECT balance FROM market.accounts WHERE user_id = %s", (user_id,))
        balance = cur.fetchone()["balance"]
        cur.execute(
            "SELECT COALESCE(SUM((quantity - filled) * price), 0) AS reserved "
            "FROM market.orders WHERE user_id = %s AND side = 'BUY' AND status IN ('OPEN', 'PARTIAL')",
            (user_id,),
        )
        reserved = cur.fetchone()["reserved"]
        cur.execute(
            "SELECT p.symbol, p.quantity, p.avg_price, a.last_price, "
            "p.quantity * a.last_price AS market_value, "
            "p.quantity * (a.last_price - p.avg_price) AS profit "
            "FROM market.positions p JOIN market.assets a USING (symbol) "
            "WHERE p.user_id = %s AND p.quantity > 0 ORDER BY p.symbol",
            (user_id,),
        )
        positions = cur.fetchall()
    holdings = sum((p["market_value"] for p in positions), Decimal(0))
    equity = balance + holdings
    return clean({
        "balance": balance,
        "available": balance - reserved,
        "equity": equity,
        "profit": equity - INITIAL_BALANCE,
        "positions": positions,
    })


def list_orders(user_id: int, limit: int = 50):
    with transaction() as cur:
        cur.execute("SELECT * FROM market.orders WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
        return clean(cur.fetchall())


def get_order(user_id: int, order_id: int):
    with transaction() as cur:
        cur.execute("SELECT * FROM market.orders WHERE id = %s AND user_id = %s", (order_id, user_id))
        order = cur.fetchone()
    if not order:
        raise MarketError("Ordem não encontrada", 404)
    return clean(order)


def list_trades(user_id: int, limit: int = 50):
    with transaction() as cur:
        cur.execute(
            "SELECT t.*, b.username AS buyer_name, s.username AS seller_name FROM market.trades t "
            "JOIN market.accounts b ON b.user_id = t.buyer_id JOIN market.accounts s ON s.user_id = t.seller_id "
            "WHERE t.buyer_id = %s OR t.seller_id = %s ORDER BY t.id DESC LIMIT %s",
            (user_id, user_id, limit),
        )
        return clean(cur.fetchall())


def _require_asset(cur, symbol: str):
    cur.execute("SELECT 1 FROM market.assets WHERE symbol = %s", (symbol,))
    if not cur.fetchone():
        raise MarketError("Ativo inexistente", 404)


# ------------------------------------------------------------------ ordens

def place_order(user_id: int, username: str, symbol: str, side: str, price: Decimal, quantity: int):
    """Valida, insere no livro e casa a ordem. Retorna o que mudou, para notificação."""
    log_event("ORDER_RECEIVED", user=username, symbol=symbol, side=side, price=price, quantity=quantity)
    try:
        lock = _symbol_lock(symbol)
    except MarketError as err:
        log_event("ORDER_REJECTED", user=username, symbol=symbol, reason=str(err))
        raise
    with lock:
        try:
            with transaction() as cur:
                return _place_order(cur, user_id, username, symbol, side, price, quantity)
        except MarketError as err:
            log_event("ORDER_REJECTED", user=username, symbol=symbol, reason=str(err))
            raise


def _place_order(cur, user_id, username, symbol, side, price, quantity):
    _require_asset(cur, symbol)
    ensure_account(cur, user_id, username)
    # Trava as contas (investidor e contrapartes) em ordem crescente de user_id: saldo e
    # reservas não mudam durante a validação e não há deadlock entre ativos diferentes.
    balances = _lock_accounts(cur, {user_id} | _counterparties(cur, symbol, side, user_id, price, quantity))
    balance = balances[user_id]

    if side == "BUY":
        cur.execute(
            "SELECT COALESCE(SUM((quantity - filled) * price), 0) AS reserved FROM market.orders "
            "WHERE user_id = %s AND side = 'BUY' AND status IN ('OPEN', 'PARTIAL')",
            (user_id,),
        )
        if balance - cur.fetchone()["reserved"] < price * quantity:
            raise MarketError("Saldo insuficiente")
    else:
        cur.execute("SELECT quantity FROM market.positions WHERE user_id = %s AND symbol = %s", (user_id, symbol))
        row = cur.fetchone()
        cur.execute(
            "SELECT COALESCE(SUM(quantity - filled), 0) AS reserved FROM market.orders "
            "WHERE user_id = %s AND symbol = %s AND side = 'SELL' AND status IN ('OPEN', 'PARTIAL')",
            (user_id, symbol),
        )
        owned = row["quantity"] if row else 0
        if owned - cur.fetchone()["reserved"] < quantity:
            raise MarketError("Quantidade de ativos insuficiente")

    cur.execute(
        "INSERT INTO market.orders (user_id, username, symbol, side, price, quantity) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, username, symbol, side, price, quantity),
    )
    order_id = cur.fetchone()["id"]
    log_event("ORDER_VALIDATED", order_id=order_id, user=username)
    log_event("ORDER_BOOK_INSERTED", order_id=order_id, symbol=symbol)

    trades, affected_orders = _match(cur, order_id, user_id, symbol, side, price, quantity)
    affected_orders.add(order_id)

    cur.execute("SELECT * FROM market.orders WHERE id = ANY(%s)", (list(affected_orders),))
    orders = cur.fetchall()
    cur.execute(
        "SELECT symbol, last_price, volume, ROUND((last_price - open_price) / open_price * 100, 2) AS change_pct "
        "FROM market.assets WHERE symbol = %s",
        (symbol,),
    )
    asset = cur.fetchone()
    return clean({
        "order_id": order_id,
        "orders": orders,
        "trades": trades,
        "asset": asset,
        "book": _book(cur, symbol),
    })


def _counterparties(cur, symbol, side, user_id, price, quantity) -> set:
    """Donos das ordens do livro que esta ordem vai consumir (mesma regra do _match).
    O livro do ativo não muda enquanto seguramos o lock do ativo."""
    if side == "BUY":
        cur.execute(
            "SELECT user_id, quantity - filled AS open_qty FROM market.orders WHERE symbol = %s AND side = 'SELL' "
            "AND status IN ('OPEN', 'PARTIAL') AND user_id <> %s AND price <= %s ORDER BY price ASC, id ASC",
            (symbol, user_id, price),
        )
    else:
        cur.execute(
            "SELECT user_id, quantity - filled AS open_qty FROM market.orders WHERE symbol = %s AND side = 'BUY' "
            "AND status IN ('OPEN', 'PARTIAL') AND user_id <> %s AND price >= %s ORDER BY price DESC, id ASC",
            (symbol, user_id, price),
        )
    owners, remaining = set(), quantity
    for row in cur.fetchall():
        if remaining <= 0:
            break
        owners.add(row["user_id"])
        remaining -= row["open_qty"]
    return owners


def _lock_accounts(cur, user_ids) -> dict:
    balances = {}
    for uid in sorted(user_ids):
        cur.execute("SELECT balance FROM market.accounts WHERE user_id = %s FOR UPDATE", (uid,))
        balances[uid] = cur.fetchone()["balance"]
    return balances


def _match(cur, order_id, user_id, symbol, side, price, quantity):
    """Prioridade de preço e depois de tempo; negocia ao preço da ordem que já estava no livro."""
    if side == "BUY":
        cur.execute(
            "SELECT * FROM market.orders WHERE symbol = %s AND side = 'SELL' AND status IN ('OPEN', 'PARTIAL') "
            "AND user_id <> %s AND price <= %s ORDER BY price ASC, id ASC FOR UPDATE",
            (symbol, user_id, price),
        )
    else:
        cur.execute(
            "SELECT * FROM market.orders WHERE symbol = %s AND side = 'BUY' AND status IN ('OPEN', 'PARTIAL') "
            "AND user_id <> %s AND price >= %s ORDER BY price DESC, id ASC FOR UPDATE",
            (symbol, user_id, price),
        )
    resting_orders = cur.fetchall()

    remaining = quantity
    trades, affected = [], set()
    for resting in resting_orders:
        if remaining == 0:
            break
        qty = min(remaining, resting["quantity"] - resting["filled"])
        buy_id, sell_id = (order_id, resting["id"]) if side == "BUY" else (resting["id"], order_id)
        buyer_id, seller_id = (user_id, resting["user_id"]) if side == "BUY" else (resting["user_id"], user_id)
        log_event("MATCH_FOUND", buy_order=buy_id, sell_order=sell_id, price=resting["price"], quantity=qty)
        trades.append(_execute_trade(cur, symbol, buy_id, sell_id, buyer_id, seller_id, resting["price"], qty))
        affected.add(resting["id"])
        remaining -= qty
    return trades, affected


def _execute_trade(cur, symbol, buy_id, sell_id, buyer_id, seller_id, price, qty):
    """Atualiza saldos, carteiras, ordens, histórico e preço na mesma transação."""
    total = price * qty
    cur.execute("UPDATE market.accounts SET balance = balance - %s WHERE user_id = %s", (total, buyer_id))
    cur.execute("UPDATE market.accounts SET balance = balance + %s WHERE user_id = %s", (total, seller_id))

    cur.execute(
        "INSERT INTO market.positions (user_id, symbol, quantity, avg_price) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id, symbol) DO UPDATE SET "
        "avg_price = ROUND((positions.quantity * positions.avg_price + EXCLUDED.quantity * EXCLUDED.avg_price) "
        "/ (positions.quantity + EXCLUDED.quantity), 2), "
        "quantity = positions.quantity + EXCLUDED.quantity",
        (buyer_id, symbol, qty, price),
    )
    cur.execute(
        "UPDATE market.positions SET quantity = quantity - %s WHERE user_id = %s AND symbol = %s",
        (qty, seller_id, symbol),
    )

    for order in (buy_id, sell_id):
        cur.execute(
            "UPDATE market.orders SET filled = filled + %s, "
            "status = CASE WHEN filled + %s >= quantity THEN 'FILLED' ELSE 'PARTIAL' END WHERE id = %s",
            (qty, qty, order),
        )
    cur.execute(
        "INSERT INTO market.trades (symbol, buyer_id, seller_id, buy_order, sell_order, price, quantity) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
        (symbol, buyer_id, seller_id, buy_id, sell_id, price, qty),
    )
    trade = cur.fetchone()
    cur.execute(
        "SELECT (SELECT username FROM market.accounts WHERE user_id = %s) AS buyer_name, "
        "(SELECT username FROM market.accounts WHERE user_id = %s) AS seller_name",
        (buyer_id, seller_id),
    )
    trade.update(cur.fetchone())
    cur.execute(
        "UPDATE market.assets SET last_price = %s, volume = volume + %s WHERE symbol = %s",
        (price, qty, symbol),
    )
    log_event("TRADE_EXECUTED", trade_id=trade["id"], symbol=symbol, price=price, quantity=qty)
    log_event("PORTFOLIO_UPDATED", buyer=buyer_id, seller=seller_id)
    return trade


def cancel_order(user_id: int, order_id: int):
    """Só o dono cancela; ordens de outros usuários aparecem como inexistentes."""
    with transaction() as cur:
        cur.execute("SELECT symbol FROM market.orders WHERE id = %s AND user_id = %s", (order_id, user_id))
        found = cur.fetchone()
    if not found:
        raise MarketError("Ordem não encontrada", 404)
    with _symbol_lock(found["symbol"]):  # mesmo lock do ativo: o livro não muda no meio de um casamento
        with transaction() as cur:
            cur.execute(
                "SELECT * FROM market.orders WHERE id = %s AND user_id = %s FOR UPDATE", (order_id, user_id)
            )
            order = cur.fetchone()
            if not order:
                raise MarketError("Ordem não encontrada", 404)
            if order["status"] not in OPEN_STATUSES:
                raise MarketError("Ordem não pode mais ser cancelada", 409)
            cur.execute("UPDATE market.orders SET status = 'CANCELLED' WHERE id = %s RETURNING *", (order_id,))
            order = cur.fetchone()
            book = _book(cur, order["symbol"])
    log_event("ORDER_CANCELLED", order_id=order_id, user=user_id)
    return clean({"order": order, "book": book})
