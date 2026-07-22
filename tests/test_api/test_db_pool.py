from __future__ import annotations

import threading
import time

import psycopg2
import pytest
from psycopg2.pool import PoolError, ThreadedConnectionPool

from apps.backend.src import db
from apps.backend.src.db import BlockingThreadedConnectionPool


def test_connection_pool_waits_until_a_connection_is_returned(monkeypatch):
    pool = object.__new__(BlockingThreadedConnectionPool)
    pool._acquire_timeout = 1.0
    pool._availability = threading.Condition()

    state = {"available": False}
    connection = object()

    def fake_getconn(_pool, key=None):
        if not state["available"]:
            raise PoolError("connection pool exhausted")
        state["available"] = False
        return connection

    def fake_putconn(_pool, conn, key=None, close=False):
        state["available"] = True

    monkeypatch.setattr(ThreadedConnectionPool, "getconn", fake_getconn)
    monkeypatch.setattr(ThreadedConnectionPool, "putconn", fake_putconn)

    acquired: list[object] = []
    waiter = threading.Thread(target=lambda: acquired.append(pool.getconn()))
    waiter.start()

    time.sleep(0.05)
    assert waiter.is_alive()

    pool.putconn(object())
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert acquired == [connection]


def test_connection_pool_times_out_when_no_connection_returns(monkeypatch):
    pool = object.__new__(BlockingThreadedConnectionPool)
    pool._acquire_timeout = 0.02
    pool._availability = threading.Condition()

    monkeypatch.setattr(
        ThreadedConnectionPool,
        "getconn",
        lambda _pool, key=None: (_ for _ in ()).throw(PoolError("connection pool exhausted")),
    )

    started = time.monotonic()
    try:
        pool.getconn()
    except PoolError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected the saturated connection pool to time out")

    assert time.monotonic() - started >= 0.015


def test_failed_reconnect_does_not_return_the_broken_connection_twice(monkeypatch):
    class BrokenCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            raise psycopg2.OperationalError("connection lost")

    class BrokenConnection:
        def cursor(self):
            return BrokenCursor()

    class ReconnectFailingPool:
        def __init__(self):
            self.get_count = 0
            self.returned: list[object] = []

        def getconn(self):
            self.get_count += 1
            if self.get_count == 1:
                return BrokenConnection()
            raise PoolError("connection pool acquisition timed out")

        def putconn(self, conn, close=False):
            self.returned.append(conn)

    pool = ReconnectFailingPool()
    monkeypatch.setattr(db, "get_pool", lambda: pool)

    with pytest.raises(PoolError, match="timed out"):
        with db.get_db():
            pass

    assert len(pool.returned) == 1
