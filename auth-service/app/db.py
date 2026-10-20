"""Acesso ao PostgreSQL com pool de conexões e transações."""
import os
from contextlib import contextmanager

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

_pool = ThreadedConnectionPool(1, 10, os.environ["DATABASE_URL"])


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
