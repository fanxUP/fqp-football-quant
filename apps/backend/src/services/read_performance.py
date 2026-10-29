"""Interactive read budgets, correlated timings and short-lived read snapshots.

Budgets live in the request context, never in scheduler/worker connections.
Snapshots are process-local transport reuse, not a second facts store.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg2.errors import QueryCanceled
from psycopg2.pool import PoolError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_logger = logging.getLogger(__name__)
READ_BUDGET_SECONDS = 8.0
_BOUNDED_PATHS = {
    "/api/predictions",
    "/api/models/predictions",
    "/api/models/overview",
    "/api/teams",
    "/api/analysis/evaluation/summary",
    "/api/analysis/evaluation/calibration",
    "/api/analysis/evaluation/by-condition",
    "/api/analysis/models/compare",
    "/api/dashboard/today",
    "/api/dashboard/model-performance",
}


class ReadBudgetExceeded(TimeoutError):
    """An interactive read exhausted its shared request budget."""


@dataclass
class ReadProbe:
    request_id: str
    deadline: float | None
    pool_ms: float = 0
    sql_ms: float = 0
    statements: int = 0
    cache: str = "none"

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic() if self.deadline is not None else 15.0
        if remaining <= 0:
            raise ReadBudgetExceeded("interactive read budget exhausted")
        return remaining


current_read: ContextVar[ReadProbe | None] = ContextVar("fqp_read_probe", default=None)


class TimedCursor:
    def __init__(self, cursor: Any, probe: ReadProbe) -> None:
        self._cursor, self._probe = cursor, probe

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def __enter__(self) -> TimedCursor:
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._cursor.__exit__(*args)

    def __iter__(self):
        return iter(self._cursor)

    def execute(self, query: Any, params: Any = None) -> Any:
        if self._probe.deadline is not None:
            milliseconds = max(1, int(self._probe.remaining() * 1000))
            self._cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(milliseconds),)
            )
        started = time.monotonic()
        try:
            return (
                self._cursor.execute(query, params)
                if params is not None
                else self._cursor.execute(query)
            )
        finally:
            elapsed = (time.monotonic() - started) * 1000
            self._probe.sql_ms += elapsed
            self._probe.statements += 1
            # Never log SQL text, query strings or bound values. The digest and
            # request-specific application_name correlate with pg_stat_activity.
            digest = hashlib.sha256(str(query).encode()).hexdigest()[:12]
            _logger.info(
                "read_sql request_id=%s query_id=%s duration_ms=%.2f",
                self._probe.request_id,
                digest,
                elapsed,
            )


class TimedConnection:
    def __init__(self, connection: Any, probe: ReadProbe) -> None:
        self._connection, self._probe = connection, probe

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def cursor(self, *args: Any, **kwargs: Any) -> TimedCursor:
        return TimedCursor(self._connection.cursor(*args, **kwargs), self._probe)


class ReadPerformanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "GET"
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        path = scope["path"]
        bounded = path in _BOUNDED_PATHS or re.fullmatch(r"/api/matches/[0-9]+/detail", path)
        if not bounded:
            await self.app(scope, receive, send)
            return
        probe = ReadProbe(uuid.uuid4().hex, started + READ_BUDGET_SECONDS)
        token, status, sent = current_read.set(probe), 500, False

        async def timed_send(message: Any) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                sent, status = True, message["status"]
                elapsed = (time.monotonic() - started) * 1000
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", probe.request_id.encode()),
                        (
                            b"server-timing",
                            (
                                f"total;dur={elapsed:.2f}, pool;dur={probe.pool_ms:.2f}, "
                                f"sql;dur={probe.sql_ms:.2f}"
                            ).encode(),
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            try:
                await self.app(scope, receive, timed_send)
            except ReadBudgetExceeded, QueryCanceled, PoolError:
                if sent or not bounded:
                    raise
                response = JSONResponse(
                    {
                        "code": "read_timeout",
                        "detail": "数据读取暂时超时，请稍后重试；已有数据仍可查看。",
                    },
                    status_code=503,
                    headers={"Retry-After": "2"},
                )
                await response(scope, receive, timed_send)
        finally:
            _logger.info(
                "read_request request_id=%s path=%s status=%s total_ms=%.2f "
                "pool_ms=%.2f sql_ms=%.2f statements=%s cache=%s",
                probe.request_id,
                path,
                status,
                (time.monotonic() - started) * 1000,
                probe.pool_ms,
                probe.sql_ms,
                probe.statements,
                probe.cache,
            )
            current_read.reset(token)


class ReadSnapshotCache:
    """Coalesce bounded GET statistics; failed reads never replace a success.

    Expired snapshots are not served as fresh or replaced by empty results.
    Existing frontend refresh guards keep the last rendered success on HTTP errors.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._pending: set[str] = set()

    def get(
        self, key: str, load: Callable[[], dict[str, Any]], *, ttl_seconds: int
    ) -> dict[str, Any]:
        probe = current_read.get()
        wait_until = time.monotonic() + (probe.remaining() if probe else READ_BUDGET_SECONDS)
        with self._condition:
            while True:
                entry = self._entries.get(key)
                if entry and time.monotonic() - entry[0] < ttl_seconds:
                    if probe:
                        probe.cache = "hit"
                    payload = copy.deepcopy(entry[1])
                    payload["data"]["meta"]["cache_status"] = "hit"
                    return payload
                if key not in self._pending:
                    self._pending.add(key)
                    break
                remaining = wait_until - time.monotonic()
                if remaining <= 0:
                    raise ReadBudgetExceeded("snapshot refresh is already running")
                self._condition.wait(remaining)
        try:
            if probe:
                probe.cache = "miss"
            data_as_of = datetime.now(UTC).isoformat()
            payload = copy.deepcopy(load())
            meta = payload["data"].setdefault("meta", {})
            meta.update(data_as_of=data_as_of, cache_status="miss", cache_ttl_seconds=ttl_seconds)
            with self._condition:
                self._entries[key] = (time.monotonic(), copy.deepcopy(payload))
                self._entries.move_to_end(key)
                while len(self._entries) > 16:
                    self._entries.popitem(last=False)
            return payload
        finally:
            with self._condition:
                self._pending.discard(key)
                self._condition.notify_all()
