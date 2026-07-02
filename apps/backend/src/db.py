"""Database connection pool for FQP.

Uses psycopg2 ThreadedConnectionPool (already in requirements.txt).
Reads DATABASE_URL from environment.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None


def _build_pool() -> ThreadedConnectionPool:
    dsn = os.getenv("DATABASE_URL", "postgresql://fqp:fqp_local_password@postgres:5432/fqp")
    return ThreadedConnectionPool(
        minconn=2,
        maxconn=8,
        dsn=dsn,
        connect_timeout=10,
    )


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = _build_pool()
    return _pool


@contextmanager
def get_db():
    """Context manager that yields a psycopg2 connection and returns it to the pool.

    Usage:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    pool = get_pool()
    conn: Any = None
    try:
        conn = pool.getconn()
        # Verify connection is alive; reconnect if not
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except psycopg2.OperationalError:
            # Connection lost — close and get a fresh one
            pool.putconn(conn, close=True)
            conn = pool.getconn()
        yield conn
    except Exception:
        if conn is not None:
            pool.putconn(conn, close=True)
        raise
    else:
        if conn is not None:
            pool.putconn(conn, close=False)


def db_health() -> dict[str, Any]:
    """Quick database health check. Returns latency in ms."""
    start = time.monotonic()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return {"status": "error", "latency_ms": latency_ms, "error": str(e)}
