"""PostgreSQL dirty-match consumption, used explicitly by existing task runners.

No scheduler, provider requests, cache writes, prediction promotion or settlement.
Callers commit a claim before computing, then complete in a short DB transaction.
Input versions fence updates; exact model inputs still require P104 cutoff/batch IDs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from scripts.observation_storage import _canonical, _transaction

_CONSUMER = re.compile(r"[a-z][a-z0-9_./-]{0,63}\Z")


class InputUpdateLeaseLost(RuntimeError):
    """An expired or replaced claim cannot publish or acknowledge results."""


class InputUpdateSuperseded(RuntimeError):
    """New observations require computing a new input version."""


@dataclass(frozen=True)
class InputUpdateClaim:
    consumer_key: str
    match_id: int
    input_version: int
    token: str
    lease_until: datetime
    attempt_count: int

    def __post_init__(self) -> None:
        _consumer(self.consumer_key)
        if any(
            type(v) is not int or v <= 0
            for v in (self.match_id, self.input_version, self.attempt_count)
        ):
            raise ValueError("claim requires positive integer identities/version/attempt")
        if not isinstance(self.token, str) or str(UUID(self.token)) != self.token:
            raise ValueError("claim requires a canonical UUID token")
        if (
            not isinstance(self.lease_until, datetime)
            or self.lease_until.tzinfo is None
            or self.lease_until.utcoffset() is None
        ):
            raise ValueError("claim lease requires an aware datetime")


def _consumer(value: str) -> None:
    if not isinstance(value, str) or not _CONSUMER.fullmatch(value):
        raise ValueError("consumer requires an explicit stable versioned key")


def _claim(value: InputUpdateClaim) -> None:
    if not isinstance(value, InputUpdateClaim):
        raise ValueError("claim requires its persisted lease identity")


def _match_filter(match_id: int | None) -> None:
    if match_id is not None and (type(match_id) is not int or match_id <= 0):
        raise ValueError("match filter requires a positive integer")


def claim_input_updates(
    conn: Any,
    *,
    consumer_key: str,
    limit: int = 8,
    lease_seconds: int = 120,
    match_id: int | None = None,
) -> list[InputUpdateClaim]:
    """Claim at most 32 latest pending versions; caller must commit promptly.

    Expired claims may be replaced. Consumers have independent progress; use a
    bounded, trusted configured key, never one key per request/user/model run.
    """
    _consumer(consumer_key)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("claim limit must be 1..32")
    if type(lease_seconds) is not int or not 10 <= lease_seconds <= 900:
        raise ValueError("lease_seconds must be 10..900")
    _match_filter(match_id)
    _transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH candidates AS MATERIALIZED (
                SELECT d.match_id,d.input_version
                FROM prediction_input_dirty_matches d
                LEFT JOIN prediction_input_consumers c
                    ON c.match_id=d.match_id AND c.consumer_key=%(consumer)s
                WHERE (%(match)s::bigint IS NULL OR d.match_id=%(match)s)
                    AND d.input_version>COALESCE(c.completed_version,0)
                    AND (c.lease_until IS NULL OR c.lease_until<=clock_timestamp())
                ORDER BY d.changed_at,d.match_id
                LIMIT %(limit)s FOR UPDATE OF d SKIP LOCKED
            )
            INSERT INTO prediction_input_consumers AS c
                (consumer_key,match_id,lease_version,lease_token,lease_until,attempt_count)
            SELECT %(consumer)s,match_id,input_version,%(token)s,
                clock_timestamp()+%(seconds)s*INTERVAL '1 second',1 FROM candidates
            ON CONFLICT (consumer_key,match_id) DO UPDATE SET
                lease_version=EXCLUDED.lease_version,lease_token=EXCLUDED.lease_token,
                lease_until=EXCLUDED.lease_until,attempt_count=c.attempt_count+1
            WHERE (c.lease_until IS NULL OR c.lease_until<=clock_timestamp())
                AND c.completed_version<EXCLUDED.lease_version
            RETURNING consumer_key,match_id,lease_version,lease_token::text,lease_until,attempt_count
            """,
            dict(
                consumer=consumer_key,
                limit=limit,
                seconds=lease_seconds,
                token=str(uuid4()),
                match=match_id,
            ),
        )
        return [InputUpdateClaim(*row) for row in cur.fetchall()]


def release_input_update(conn: Any, claim: InputUpdateClaim) -> bool:
    """Release only this token; leave pending version untouched for a later run.

    Task runners own bounded retry/backoff. This helper never retries in a loop.
    """
    _claim(claim)
    _transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE prediction_input_consumers
               SET lease_version=NULL,lease_token=NULL,lease_until=NULL
               WHERE consumer_key=%s AND match_id=%s AND lease_version=%s AND lease_token=%s
               RETURNING match_id""",
            (claim.consumer_key, claim.match_id, claim.input_version, claim.token),
        )
        return cur.fetchone() is not None


def complete_input_update(
    conn: Any,
    claim: InputUpdateClaim,
    publish: Callable[[Any, InputUpdateClaim], dict],
) -> dict:
    """Fence and atomically persist a trusted DB-only callback and its receipt.

    Duplicate completion returns the original receipt without calling publish.
    The callback must not commit/rollback, write observations, perform network or
    cache I/O, or invoke financial/ticket/settlement operations. Compute before
    entering this short transaction; return only bounded JSON result references.
    A savepoint removes partial callback writes on failure; caller owns commit.
    """
    _claim(claim)
    if not callable(publish):
        raise ValueError("publish requires a trusted DB-only callback")
    _transaction(conn)
    params = (claim.consumer_key, claim.match_id, claim.input_version)
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT prediction_input_publish")
        try:
            cur.execute(
                "SELECT input_version FROM prediction_input_dirty_matches "
                "WHERE match_id=%s FOR UPDATE",
                (claim.match_id,),
            )
            head = cur.fetchone()
            cur.execute(
                "SELECT completed_version FROM prediction_input_consumers "
                "WHERE consumer_key=%s AND match_id=%s FOR UPDATE",
                params[:2],
            )
            progress = cur.fetchone()
            if head is None or progress is None:
                raise InputUpdateLeaseLost("claim no longer exists")
            cur.execute(
                "SELECT result_refs FROM prediction_input_consumptions "
                "WHERE consumer_key=%s AND match_id=%s AND input_version=%s",
                params,
            )
            receipt = cur.fetchone()
            if receipt is not None:
                result = dict(
                    status="already_completed",
                    input_version=claim.input_version,
                    result_refs=receipt[0],
                )
            else:
                _fence(cur, claim)
                refs = publish(conn, claim)
                if not isinstance(refs, dict):
                    raise ValueError("publication requires bounded JSON reference object")
                payload = _canonical(refs, 16384)
                # Also fence after the callback: an expired lease or accidental
                # input mutation must roll back all of this publication.
                _fence(cur, claim)
                cur.execute(
                    "INSERT INTO prediction_input_consumptions"
                    "(consumer_key,match_id,input_version,claim_token,result_refs) "
                    "VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (*params, claim.token, payload),
                )
                cur.execute(
                    "UPDATE prediction_input_consumers SET completed_version=%s,"
                    "lease_version=NULL,lease_token=NULL,lease_until=NULL "
                    "WHERE consumer_key=%s AND match_id=%s",
                    (claim.input_version, *params[:2]),
                )
                result = dict(
                    status="completed",
                    input_version=claim.input_version,
                    result_refs=json.loads(payload),
                )
        except BaseException:
            cur.execute("ROLLBACK TO SAVEPOINT prediction_input_publish")
            cur.execute("RELEASE SAVEPOINT prediction_input_publish")
            raise
        cur.execute("RELEASE SAVEPOINT prediction_input_publish")
    return result


def _fence(cur: Any, claim: InputUpdateClaim) -> None:
    cur.execute(
        "SELECT d.input_version,c.lease_version,c.lease_token::text,"
        "c.lease_until>clock_timestamp() "
        "FROM prediction_input_dirty_matches d JOIN prediction_input_consumers c "
        "ON c.match_id=d.match_id WHERE d.match_id=%s AND c.consumer_key=%s",
        (claim.match_id, claim.consumer_key),
    )
    row = cur.fetchone()
    if row is None or row[1:] != (claim.input_version, claim.token, True):
        raise InputUpdateLeaseLost("claim expired or was replaced")
    if row[0] != claim.input_version:
        raise InputUpdateSuperseded("new observation input version is pending")
