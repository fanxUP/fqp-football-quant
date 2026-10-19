"""Append-only source evidence. Callers own commit/rollback and authorization.

Cutoffs freeze bounded, declared streams into portable immutable ID selections.
This module does not resolve competing sources or prove that a
provider claim is true. A source_observation is a checked source response;
candidate/reconstruction are excluded by the default historical reader.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from scripts.data_catalog import get_data_source
from scripts.data_contracts import AcquisitionStatus, FactStatus, to_utc

_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_KINDS = {"source_observation", "candidate", "research_reconstruction"}
MAX_CONTENT_BYTES = 65536


@dataclass(frozen=True)
class ObservationCutoff:
    id: str
    as_of: datetime
    include_reconstruction: bool = False


def _canonical(value: Any, limit: int) -> str:
    text = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(text.encode()) > limit:
        raise ValueError("canonical content exceeds size limit")
    return text


def capture_observation_cutoff(
    conn: Any, *, streams: list[dict], include_reconstruction: bool = False
) -> ObservationCutoff:
    """Freeze one MVCC view, then persist its exact references in this transaction.

    1..128 declared streams, including missing ones; caller owns commit/rollback.
    No native XID or snapshot token is needed to replay the persisted selection.
    """
    if not isinstance(streams, list) or not 1 <= len(streams) <= 128:
        raise ValueError("cutoff requires 1..128 declared streams")
    if type(include_reconstruction) is not bool:
        raise ValueError("cutoff research policy requires a boolean")
    if any(
        not isinstance(item, dict)
        or set(item) != {"match_id", "source_id", "domain", "subject_key"}
        for item in streams
    ):
        raise ValueError("cutoff streams require explicit identities")
    identities = [_identity(**item) for item in streams]
    if len({_canonical(item, 2048) for item in identities}) != len(identities):
        raise ValueError("cutoff streams must be distinct")
    _transaction(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH stamp AS MATERIALIZED (
                SELECT clock_timestamp() AS at, pg_current_xact_id_if_assigned() AS own_write
            ), inputs AS (
                SELECT x.*, e.ordinal FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY AS e(item,ordinal)
                CROSS JOIN LATERAL jsonb_to_record(e.item) AS x(
                    match_id bigint, source_id text, source_family text, domain text, subject_key text)
            )
            SELECT stamp.at, stamp.own_write, jsonb_agg(jsonb_build_object(
                'match_id', i.match_id, 'source_id', i.source_id, 'source_family', i.source_family,
                'domain', i.domain, 'subject_key', i.subject_key,
                'revision_id', r.id, 'latest_check_id', c.id, 'freshness_check_id', fresh.id)
                ORDER BY i.ordinal), bool_or(s.source_family IS DISTINCT FROM i.source_family
                    AND s.id IS NOT NULL)
            FROM stamp CROSS JOIN inputs i
            LEFT JOIN observation_streams s ON s.match_id=i.match_id AND s.source_id=i.source_id
                AND s.domain=i.domain AND s.subject_key=i.subject_key
            LEFT JOIN LATERAL (
                SELECT id FROM observation_revisions WHERE stream_id=s.id AND available_at<=stamp.at
                AND (evidence_kind='source_observation' OR
                     (%s AND evidence_kind='research_reconstruction'))
                ORDER BY revision DESC LIMIT 1
            ) r ON true
            LEFT JOIN LATERAL (
                SELECT id FROM observation_checks WHERE stream_id=s.id AND available_at<=stamp.at
                ORDER BY id DESC LIMIT 1
            ) c ON true
            LEFT JOIN LATERAL (
                SELECT id FROM observation_checks WHERE revision_id=r.id AND available_at<=stamp.at
                ORDER BY id DESC LIMIT 1
            ) fresh ON true
            GROUP BY stamp.at,stamp.own_write
            """,
            (_canonical(identities, 131072), include_reconstruction),
        )
        at, own_write, selections, family_mismatch = cur.fetchone()
        if own_write is not None:
            raise ValueError("capture observation cutoff before assigning a write transaction")
        if family_mismatch:
            raise ValueError("observation source family changed; explicit migration required")
        manifest = _canonical(selections, 131072)
        cutoff = ObservationCutoff(str(uuid4()), _aware(at, "as_of"), include_reconstruction)
        cur.execute(
            "INSERT INTO observation_cutoffs(id,as_of,include_reconstruction,selections,content_hash) "
            "VALUES (%s,%s,%s,%s::jsonb,%s)",
            (
                cutoff.id,
                cutoff.as_of,
                include_reconstruction,
                manifest,
                hashlib.sha256(manifest.encode()).hexdigest(),
            ),
        )
    return cutoff


def load_observation_cutoff(conn: Any, cutoff_id: str) -> ObservationCutoff:
    cutoff, _ = _cutoff_selection(conn, cutoff_id)
    return cutoff


def _cutoff_selection(conn: Any, cutoff_id: str) -> tuple[ObservationCutoff, list[dict]]:
    if not isinstance(cutoff_id, str) or str(UUID(cutoff_id)) != cutoff_id:
        raise ValueError("cutoff requires a canonical UUID")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT as_of,include_reconstruction,selections,content_hash "
            "FROM observation_cutoffs WHERE id=%s",
            (cutoff_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("cutoff is absent; commit/copy its original record before replay")
    at, research, selections, checksum = row
    if not isinstance(selections, list) or not 1 <= len(selections) <= 128:
        raise ValueError("invalid cutoff selection")
    if hashlib.sha256(_canonical(selections, 131072).encode()).hexdigest() != checksum:
        raise ValueError("cutoff content hash mismatch")
    seen = set()
    for item in selections:
        if not isinstance(item, dict) or set(item) != {
            "match_id",
            "source_id",
            "source_family",
            "domain",
            "subject_key",
            "revision_id",
            "latest_check_id",
            "freshness_check_id",
        }:
            raise ValueError("invalid cutoff reference shape")
        identity = _identity(
            **{key: item[key] for key in ("match_id", "source_id", "domain", "subject_key")}
        )
        key = _canonical(identity, 2048)
        if (
            key in seen
            or not isinstance(item["source_family"], str)
            or not _KEY.fullmatch(item["source_family"])
        ):
            raise ValueError("invalid cutoff identity/family")
        seen.add(key)
        for key in ("revision_id", "latest_check_id", "freshness_check_id"):
            if item[key] is not None and (type(item[key]) is not int or item[key] <= 0):
                raise ValueError("invalid cutoff reference ID")
        if (item["revision_id"] is None) != (item["freshness_check_id"] is None):
            raise ValueError("cutoff revision requires its success receipt")
    return ObservationCutoff(cutoff_id, _aware(at, "as_of"), research), selections


def load_observation_selection(conn: Any, cutoff: ObservationCutoff) -> list[dict]:
    if not isinstance(cutoff, ObservationCutoff):
        raise ValueError("cutoff requires its persisted identity/time/policy")
    actual, selections = _cutoff_selection(conn, cutoff.id)
    if (
        actual.as_of != _aware(cutoff.as_of, "as_of")
        or actual.include_reconstruction != cutoff.include_reconstruction
    ):
        raise ValueError("cutoff time/policy differs from its persisted record")
    return selections


def load_cutoff_observations(conn: Any, cutoff: ObservationCutoff) -> list[dict | None]:
    return [_load_selected(conn, cutoff, item) for item in load_observation_selection(conn, cutoff)]


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} requires an aware datetime")
    return to_utc(value)


def _identity(match_id: int, source_id: str, domain: str, subject_key: str) -> dict:
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("match_id requires a canonical positive integer")
    if not isinstance(domain, str) or not _KEY.fullmatch(domain):
        raise ValueError("domain requires a stable key")
    if not isinstance(subject_key, str) or not 0 < len(subject_key) <= 256:
        raise ValueError("subject_key requires a bounded stable key")
    source = get_data_source(source_id)
    return dict(
        match_id=match_id,
        source_id=source_id,
        source_family=source["family"],
        domain=domain,
        subject_key=subject_key,
    )


def _transaction(conn: Any) -> None:
    if conn.autocommit is True:
        raise ValueError("observation writes require a caller-owned transaction")


def _stream(cur: Any, identity: dict) -> int:
    # Stable cross-process serialization; hash collisions only serialize extras.
    key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    cur.execute(
        """
        INSERT INTO observation_streams(match_id, source_id, source_family, domain, subject_key)
        VALUES (%(match_id)s, %(source_id)s, %(source_family)s, %(domain)s, %(subject_key)s)
        ON CONFLICT (match_id, source_id, domain, subject_key) DO NOTHING
        """,
        identity,
    )
    cur.execute(
        """
        SELECT id, source_family FROM observation_streams
        WHERE match_id=%(match_id)s AND source_id=%(source_id)s
          AND domain=%(domain)s AND subject_key=%(subject_key)s
        """,
        identity,
    )
    row = cur.fetchone()
    if row is None or row[1] != identity["source_family"]:
        raise ValueError("observation source family changed; explicit migration required")
    return int(row[0])


def append_observation(
    conn: Any,
    *,
    match_id: int,
    source_id: str,
    domain: str,
    subject_key: str,
    fact_status: FactStatus,
    value: Any,
    acquired_at: datetime,
    verified_at: datetime,
    effective_at: datetime | None = None,
    published_at: datetime | None = None,
    valid_until: datetime | None = None,
    evidence: dict | None = None,
    evidence_kind: str = "source_observation",
) -> dict:
    """Append a revision only if content changed; always append a success check.

    The service's ingestion clock is a lower bound for availability. Passing an
    old publication/acquisition timestamp never creates retroactive knowledge.
    Repeated content after an intervening change (A/B/A) is a new revision.
    No commit, implicit fallback, network I/O, or source enablement occurs here.
    """
    identity = _identity(match_id, source_id, domain, subject_key)
    acquired = _aware(acquired_at, "acquired_at")
    verified = _aware(verified_at, "verified_at")
    effective = _aware(effective_at, "effective_at") if effective_at is not None else None
    published = _aware(published_at, "published_at") if published_at is not None else None
    expires = _aware(valid_until, "valid_until") if valid_until is not None else None
    evidence = {} if evidence is None else evidence
    if not isinstance(fact_status, FactStatus) or evidence_kind not in _KINDS:
        raise ValueError("unknown fact status or evidence kind")
    if (fact_status == FactStatus.VALUE) != (value is not None):
        raise ValueError("only value facts carry values; zero and false are valid values")
    if not isinstance(evidence, dict):
        raise ValueError("evidence requires an object")
    if fact_status == FactStatus.CONFIRMED_ABSENT and evidence.get("coverage_complete") is not True:
        raise ValueError("confirmed absence requires complete coverage evidence")
    if verified < acquired or (expires is not None and expires < acquired):
        raise ValueError("verification/expiration cannot precede acquisition")
    content = dict(
        fact_status=fact_status.value,
        value=value,
        evidence=evidence,
        evidence_kind=evidence_kind,
        effective_at=effective.isoformat() if effective else None,
        published_at=published.isoformat() if published else None,
    )
    serialized = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(serialized.encode()) > MAX_CONTENT_BYTES:
        raise ValueError("observation content exceeds 64KiB")
    checksum = hashlib.sha256(serialized.encode()).hexdigest()
    _transaction(conn)
    with conn.cursor() as cur:
        stream_id = _stream(cur, identity)
        cur.execute(
            "SELECT id, revision, content_hash, available_at FROM observation_revisions "
            "WHERE stream_id=%s ORDER BY revision DESC LIMIT 1",
            (stream_id,),
        )
        previous = cur.fetchone()
        if previous is not None and previous[2] == checksum:
            revision_id, revision, _, available_at = previous
        else:
            revision = int(previous[1]) + 1 if previous else 1
            cur.execute(
                """
                WITH stamp AS (SELECT clock_timestamp() AS now)
                INSERT INTO observation_revisions(
                    stream_id, revision, content_hash, fact_status, value_json,
                    evidence_json, evidence_kind, effective_at, published_at,
                    first_acquired_at, first_verified_at, ingested_at, available_at)
                SELECT %s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,stamp.now,
                       greatest(stamp.now,%s,%s,%s) FROM stamp
                RETURNING id, available_at
                """,
                (
                    stream_id,
                    revision,
                    checksum,
                    fact_status.value,
                    json.dumps(value, ensure_ascii=False, allow_nan=False)
                    if value is not None
                    else None,
                    json.dumps(evidence, ensure_ascii=False, allow_nan=False),
                    evidence_kind,
                    effective,
                    published,
                    acquired,
                    verified,
                    acquired,
                    verified,
                    published,
                ),
            )
            revision_id, available_at = cur.fetchone()
        cur.execute(
            """
            WITH stamp AS (SELECT clock_timestamp() AS now)
            INSERT INTO observation_checks(stream_id, revision_id, acquisition_status,
                acquired_at, ingested_at, available_at, valid_until)
            SELECT %s,%s,'success',%s,stamp.now,greatest(stamp.now,%s,%s,%s),%s FROM stamp
            RETURNING id
            """,
            (stream_id, revision_id, acquired, acquired, verified, published, expires),
        )
        check_id = cur.fetchone()[0]
    return dict(
        revision_id=int(revision_id),
        revision=int(revision),
        check_id=int(check_id),
        content_hash=checksum,
        available_at=available_at,
    )


def record_acquisition_failure(
    conn: Any,
    *,
    match_id: int,
    source_id: str,
    domain: str,
    subject_key: str,
    status: AcquisitionStatus,
    acquired_at: datetime,
) -> int:
    """Record only a sanitized status, never provider errors/credentials or zero facts."""
    identity = _identity(match_id, source_id, domain, subject_key)
    acquired = _aware(acquired_at, "acquired_at")
    if not isinstance(status, AcquisitionStatus) or status == AcquisitionStatus.SUCCESS:
        raise ValueError("failure receipt requires a non-success acquisition status")
    _transaction(conn)
    with conn.cursor() as cur:
        stream_id = _stream(cur, identity)
        cur.execute(
            """
            WITH stamp AS (SELECT clock_timestamp() AS now)
            INSERT INTO observation_checks(stream_id, acquisition_status, acquired_at,
                ingested_at, available_at)
            SELECT %s,%s,%s,stamp.now,greatest(stamp.now,%s) FROM stamp RETURNING id
            """,
            (stream_id, status.value, acquired, acquired),
        )
        return int(cur.fetchone()[0])


def load_observation_as_of(
    conn: Any,
    *,
    match_id: int,
    source_id: str,
    domain: str,
    subject_key: str,
    cutoff: ObservationCutoff,
) -> dict | None:
    """Read only the frozen selection; never substitute latest or overwritten rows."""
    identity = _identity(match_id, source_id, domain, subject_key)
    for item in load_observation_selection(conn, cutoff):
        if all(item[key] == value for key, value in identity.items() if key != "source_family"):
            return _load_selected(conn, cutoff, item)
    raise ValueError("stream was not declared in this cutoff")


def _load_selected(conn: Any, cutoff: ObservationCutoff, item: dict) -> dict | None:
    if item["revision_id"] is None and item["latest_check_id"] is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.revision, r.fact_status, r.value_json, r.evidence_json,
                   r.evidence_kind, r.effective_at, r.published_at, r.first_acquired_at,
                   r.first_verified_at, r.ingested_at, r.available_at, r.content_hash,
                   c.id, c.acquisition_status, fresh.id, fresh.valid_until,
                   r.available_at, c.available_at, fresh.available_at,
                   fresh.revision_id, fresh.acquisition_status, fresh.acquired_at
            FROM observation_streams s
            LEFT JOIN observation_revisions r ON r.id=%(revision_id)s AND r.stream_id=s.id
            LEFT JOIN observation_checks c ON c.id=%(latest_check_id)s AND c.stream_id=s.id
            LEFT JOIN observation_checks fresh ON fresh.id=%(freshness_check_id)s AND fresh.stream_id=s.id
            WHERE s.match_id=%(match_id)s AND s.source_id=%(source_id)s AND s.source_family=%(source_family)s
              AND s.domain=%(domain)s AND s.subject_key=%(subject_key)s
            """,
            item,
        )
        row = cur.fetchone()
    if row is None or any(
        row[pos] != item[key]
        for pos, key in ((0, "revision_id"), (13, "latest_check_id"), (15, "freshness_check_id"))
    ):
        raise ValueError("cutoff references are absent or belong to a different stream")
    if any(at is not None and at > cutoff.as_of for at in row[17:20]):
        raise ValueError("cutoff references unavailable evidence")
    if row[0] is not None and (
        row[20] != row[0]
        or row[21] != "success"
        or row[5]
        not in (
            {"source_observation", "research_reconstruction"}
            if cutoff.include_reconstruction
            else {"source_observation"}
        )
    ):
        raise ValueError("cutoff references incompatible evidence")
    columns = (
        "revision_id",
        "revision",
        "original_fact_status",
        "value",
        "evidence",
        "evidence_kind",
        "effective_at",
        "published_at",
        "first_acquired_at",
        "first_verified_at",
        "ingested_at",
        "available_at",
        "content_hash",
        "latest_check_id",
        "acquisition_status",
        "freshness_check_id",
        "valid_until",
    )
    result = dict(zip(columns, row[:17], strict=True))
    result["last_success_acquired_at"] = row[22]
    result["fact_status"] = (
        FactStatus.STALE.value
        if row[0] is not None and row[16] is not None and row[16] <= cutoff.as_of
        else row[2] or FactStatus.UNKNOWN.value
    )
    return result
