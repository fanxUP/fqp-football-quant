"""Database connection pool for FQP.

Uses psycopg2 ThreadedConnectionPool (already in requirements.txt).
Reads DATABASE_URL from environment.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.pool import PoolError, ThreadedConnectionPool


class BlockingThreadedConnectionPool(ThreadedConnectionPool):
    """Thread-safe pool that waits briefly when all connections are in use.

    psycopg2's standard pool raises ``PoolError`` immediately at capacity. A
    dashboard page can legitimately issue more parallel reads than the pool
    size, so short-lived bursts should queue instead of turning into HTTP 500s.
    """

    def __init__(
        self,
        minconn: int,
        maxconn: int,
        *args: Any,
        acquire_timeout: float = 15.0,
        **kwargs: Any,
    ) -> None:
        self._acquire_timeout = acquire_timeout
        self._availability = threading.Condition()
        super().__init__(minconn, maxconn, *args, **kwargs)

    def getconn(self, key: Any = None):
        deadline = time.monotonic() + self._acquire_timeout
        with self._availability:
            while True:
                try:
                    return super().getconn(key)
                except PoolError as exc:
                    if getattr(self, "closed", False):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PoolError("connection pool acquisition timed out") from exc
                    self._availability.wait(timeout=remaining)

    def putconn(self, conn: Any, key: Any = None, close: bool = False) -> None:
        super().putconn(conn, key=key, close=close)
        with self._availability:
            self._availability.notify()


_pool: BlockingThreadedConnectionPool | None = None


def _build_pool() -> BlockingThreadedConnectionPool:
    # Homebrew PostgreSQL is the project's single source of truth.
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://fqp:fqp_local_password@127.0.0.1:5432/fqp",
    )
    min_connections = int(os.getenv("FQP_DB_POOL_MIN", "2"))
    max_connections = int(os.getenv("FQP_DB_POOL_MAX", "16"))
    acquire_timeout = float(os.getenv("FQP_DB_POOL_ACQUIRE_TIMEOUT", "15"))
    if min_connections < 1 or max_connections < min_connections:
        raise ValueError("FQP database pool limits are invalid")
    return BlockingThreadedConnectionPool(
        minconn=min_connections,
        maxconn=max_connections,
        dsn=dsn,
        connect_timeout=10,
        acquire_timeout=acquire_timeout,
    )


def get_pool() -> BlockingThreadedConnectionPool:
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
            conn = None
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
