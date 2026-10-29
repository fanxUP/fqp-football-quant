from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.errors import QueryCanceled


def test_slow_read_returns_unavailable_with_correlated_timing_and_no_sql_leak(monkeypatch, caplog):
    from apps.backend.src import db
    from apps.backend.src.services import read_performance as reads

    pool, conn = MagicMock(), MagicMock()
    pool.getconn.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur

    def execute(sql, params=None):
        if "SELECT sensitive_business_data" in sql:
            raise QueryCanceled("sensitive_business_data: private_value")

    cur.execute.side_effect = execute
    monkeypatch.setattr(db, "get_pool", lambda: pool)
    app = FastAPI()
    app.add_middleware(reads.ReadPerformanceMiddleware)

    @app.get("/api/predictions")
    def slow_read():
        with db.get_db() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT sensitive_business_data WHERE token=%s", ("private_value",))

    with caplog.at_level("INFO"):
        response = TestClient(app).get("/api/predictions?ignored=private_value")
    assert response.status_code == 503
    assert response.json()["code"] == "read_timeout"
    assert response.headers["retry-after"] == "2"
    assert len(response.headers["x-request-id"]) == 32
    assert "sql;dur=" in response.headers["server-timing"]
    app_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name == reads.__name__
    )
    assert "private_value" not in response.text + app_log
    assert "sensitive_business_data" not in app_log
    assert response.headers["x-request-id"] in app_log
    pool.putconn.assert_called_once_with(conn, close=True)
    settings = [
        call
        for call in cur.execute.call_args_list
        if "set_config('statement_timeout'" in call.args[0]
    ]
    assert settings and all(0 < int(call.args[1][0]) <= 8000 for call in settings)


def test_background_database_use_has_no_interactive_timeout(monkeypatch):
    from apps.backend.src import db

    pool, conn = MagicMock(), MagicMock()
    pool.getconn.return_value = conn
    monkeypatch.setattr(db, "get_pool", lambda: pool)
    with db.get_db() as connection:
        assert connection is conn
    assert conn.cursor.return_value.__enter__.return_value.execute.call_args.args == ("SELECT 1",)


def test_snapshot_reuses_success_but_never_turns_failure_into_empty_or_fresh_data(monkeypatch):
    from apps.backend.src.services import read_performance as reads

    now = [100.0]
    monkeypatch.setattr(reads.time, "monotonic", lambda: now[0])
    cache = reads.ReadSnapshotCache()
    calls = []

    def load():
        calls.append(1)
        return {"data": {"series": [0], "meta": {"updated_at": "original-data-time"}}}

    first = cache.get("today", load, ttl_seconds=20)
    first["data"]["series"].append(99)
    hit = cache.get("today", load, ttl_seconds=20)
    assert hit["data"]["series"] == [0]
    assert hit["data"]["meta"]["updated_at"] == "original-data-time"
    assert hit["data"]["meta"]["cache_status"] == "hit"
    now[0] += 21

    def failed():
        raise RuntimeError("read failed")

    with pytest.raises(RuntimeError, match="read failed"):
        cache.get("today", failed, ttl_seconds=20)
    recovered = cache.get("today", load, ttl_seconds=20)
    assert len(calls) == 2
    assert recovered["data"]["meta"]["cache_status"] == "miss"


def test_snapshot_coalesces_concurrent_reads():
    from apps.backend.src.services import read_performance as reads

    cache = reads.ReadSnapshotCache()
    started, release = threading.Event(), threading.Event()
    calls = []

    def load():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"data": {"series": [1]}}

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(cache.get, "models", load, ttl_seconds=20)
        assert started.wait(2)
        others = [executor.submit(cache.get, "models", load, ttl_seconds=20) for _ in range(2)]
        release.set()
        responses = [first.result(2), *(future.result(2) for future in others)]
    assert len(calls) == 1
    assert all(response["data"]["series"] == [1] for response in responses)
