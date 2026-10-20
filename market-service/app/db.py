"""Acesso ao PostgreSQL com pool de conexões e transações."""
import os
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

_pool = ThreadedConnectionPool(1, 20, os.environ["DATABASE_URL"])


@contextmanager
def transaction():
    """Entrega um cursor; faz commit no sucesso e rollback em qualquer erro."""
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def clean(value):
    """Converte Decimal/datetime (de linhas do banco) em tipos serializáveis em JSON."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
