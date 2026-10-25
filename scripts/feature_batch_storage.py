"""Immutable feature attempts, complete publications and exact observation inputs.

Completeness means every declared P102 field is explained, including unknowns;
this is not a model capability decision, artifact/run manifest, or source grant.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from scripts.data_contracts import FactStatus
from scripts.feature_schema import FEATURE_SCHEMA_VERSION, valid_feature_columns
from scripts.observation_storage import (
    ObservationCutoff,
    _canonical,
    _transaction,
    load_cutoff_observations,
    load_observation_cutoff,
    load_observation_selection,
)

_BUILDER = re.compile(r"[a-z0-9][a-z0-9_./-]{0,63}\Z")
MAX_BATCH_BYTES = 262144


def _contract(
    builder_version: str,
    required_fields: Any,
    feature_schema_version: str,
    *,
    retained: bool = False,
) -> str:
    if not isinstance(builder_version, str) or not _BUILDER.fullmatch(builder_version):
        raise ValueError("builder requires an explicit bounded version")
    # v2 and v3 retain the same ordered numeric fields. Exact historical reads
    # must validate their original schema/hash; new writes and latest lookup
    # still require the current schema and never upgrade old facts implicitly.
    supported = (
        (FEATURE_SCHEMA_VERSION, "observed-form/v2") if retained else (FEATURE_SCHEMA_VERSION,)
    )
    if feature_schema_version not in supported or not valid_feature_columns(required_fields):
        raise ValueError("batch requires a supported P102 schema and unique ordered fields")
    return hashlib.sha256(_canonical(list(required_fields), MAX_BATCH_BYTES).encode()).hexdigest()


def _validate(
    conn: Any,
    *,
    match_id: int,
    cutoff: ObservationCutoff,
    builder_version: str,
    required_fields: Any,
    features: dict,
    status: str,
    feature_schema_version: str,
    retained: bool = False,
) -> tuple[dict, list[dict | None]]:
    _contract(builder_version, required_fields, feature_schema_version, retained=retained)
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("batch requires a canonical match")
    if not isinstance(features, dict) or status not in {"running", "partial", "complete"}:
        raise ValueError("invalid batch features/status")
    if cutoff.include_reconstruction:
        raise ValueError("research cutoffs cannot publish runtime feature batches")
    selections = load_observation_selection(conn, cutoff)
    if any(item["match_id"] != match_id for item in selections):
        raise ValueError("batch cutoff must contain only this match")
    if not set(features) <= set(required_fields) or (
        status == "complete" and set(features) != set(required_fields)
    ):
        raise ValueError("complete batch requires all and only its declared fields")
    observations = load_cutoff_observations(conn, cutoff)
    for field in features.values():
        keys = {"fact_status", "value", "observation_indexes"}
        if not isinstance(field, dict) or set(field) not in (keys, keys | {"derivation"}):
            raise ValueError("feature requires explicit status/value/evidence references")
        derivation = field.get("derivation")
        if "derivation" in field and (not isinstance(derivation, dict) or not derivation):
            raise ValueError("feature derivation requires bounded object metadata")
        if derivation is not None:
            _canonical(derivation, 32768)
        fact = FactStatus(field["fact_status"])
        value = field["value"]
        if (fact == FactStatus.VALUE) != (value is not None):
            raise ValueError("only value features carry values; unknown is not zero")
        try:
            finite = value is None or (type(value) in (int, float, bool) and math.isfinite(value))
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("P102 numeric feature must be finite")
        refs = field["observation_indexes"]
        unexplained = not refs and not (
            fact == FactStatus.UNKNOWN
            and derivation
            == {
                "version": "observed-input/v1",
                "kind": "unavailable",
                "reason": "no_point_in_time_derivation",
            }
        )
        if (
            not isinstance(refs, list)
            or unexplained
            or len(refs) > len(selections)
            or any(type(index) is not int or not 0 <= index < len(selections) for index in refs)
            or len(set(refs)) != len(refs)
        ):
            raise ValueError("feature requires valid distinct cutoff evidence indexes")
        evidence_statuses = {
            observation["fact_status"]
            if (observation := observations[i]) is not None
            else FactStatus.UNKNOWN.value
            for i in refs
        }
        if fact in (FactStatus.VALUE, FactStatus.CONFIRMED_ABSENT) and evidence_statuses != {
            fact.value
        }:
            raise ValueError("feature value/absence lacks compatible evidence")
    payload = dict(
        match_id=match_id,
        cutoff_id=cutoff.id,
        builder_version=builder_version,
        feature_schema_version=feature_schema_version,
        required_fields=list(required_fields),
        features=features,
        status=status,
    )
    _canonical(payload, MAX_BATCH_BYTES)
    return payload, observations


def store_feature_batch(
    conn: Any,
    *,
    match_id: int,
    cutoff: ObservationCutoff,
    builder_version: str,
    required_fields: Any,
    features: dict,
    status: str = "complete",
    feature_schema_version: str = FEATURE_SCHEMA_VERSION,
) -> int:
    """Insert the entire attempt/publication; caller owns commit and rollback.

    Field builders own the named derivation. Compatible source evidence is
    checked here; a citation alone does not prove its derived numeric value.
    """
    _transaction(conn)
    payload, _ = _validate(
        conn,
        match_id=match_id,
        cutoff=cutoff,
        builder_version=builder_version,
        required_fields=required_fields,
        features=features,
        status=status,
        feature_schema_version=feature_schema_version,
    )
    params = dict(payload)
    params.update(
        cutoff_as_of=cutoff.as_of,
        required_fields=_canonical(payload["required_fields"], MAX_BATCH_BYTES),
        fields_hash=_contract(builder_version, required_fields, feature_schema_version),
        features=_canonical(features, MAX_BATCH_BYTES),
        content_hash=hashlib.sha256(_canonical(payload, MAX_BATCH_BYTES).encode()).hexdigest(),
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feature_batches(match_id,cutoff_id,cutoff_as_of,builder_version,
                feature_schema_version,required_fields,fields_hash,features,status,content_hash)
            VALUES (%(match_id)s,%(cutoff_id)s,%(cutoff_as_of)s,%(builder_version)s,
                %(feature_schema_version)s,%(required_fields)s::jsonb,%(fields_hash)s,
                %(features)s::json,%(status)s,%(content_hash)s) RETURNING id
            """,
            params,
        )
        return int(cur.fetchone()[0])


def load_feature_batch(conn: Any, batch_id: int) -> dict | None:
    """Read one exact complete batch, validating references rather than using latest."""
    if type(batch_id) is not int or batch_id <= 0:
        raise ValueError("batch requires a positive integer ID")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT match_id,cutoff_id::text,builder_version,feature_schema_version,"
            "required_fields,features,status,content_hash,fields_hash,cutoff_as_of,created_at "
            "FROM feature_batches WHERE id=%s AND status='complete'",
            (batch_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    (
        match_id,
        cutoff_id,
        builder,
        schema,
        fields,
        features,
        status,
        checksum,
        fields_hash,
        at,
        created,
    ) = row
    cutoff = load_observation_cutoff(conn, cutoff_id)
    payload, observations = _validate(
        conn,
        match_id=match_id,
        cutoff=cutoff,
        builder_version=builder,
        required_fields=fields,
        features=features,
        status=status,
        feature_schema_version=schema,
        retained=True,
    )
    if (
        cutoff.as_of != at
        or fields_hash != _contract(builder, fields, schema, retained=True)
        or hashlib.sha256(_canonical(payload, MAX_BATCH_BYTES).encode()).hexdigest() != checksum
    ):
        raise ValueError("feature batch content hash/contract mismatch")
    return dict(
        payload,
        id=batch_id,
        cutoff=cutoff,
        observations=observations,
        content_hash=checksum,
        created_at=created,
        usable_value_fields=[
            field for field in fields if features[field]["fact_status"] == "value"
        ],
    )


def load_latest_feature_batch(
    conn: Any,
    *,
    match_id: int,
    builder_version: str,
    required_fields: Any,
    feature_schema_version: str = FEATURE_SCHEMA_VERSION,
) -> dict:
    """Current lookup with explicit previous-complete/no-complete explanation.

    Ordering is by captured input cutoff, then attempt ID, never late completion
    time. This is not historical run replay: callers retain their exact batch ID.
    """
    fields_hash = _contract(builder_version, required_fields, feature_schema_version)
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("batch requires a canonical match")
    params = dict(
        match_id=match_id,
        builder=builder_version,
        schema=feature_schema_version,
        fields=_canonical(list(required_fields), MAX_BATCH_BYTES),
        fields_hash=fields_hash,
    )
    where = """match_id=%(match_id)s AND builder_version=%(builder)s
        AND feature_schema_version=%(schema)s AND fields_hash=%(fields_hash)s
        AND required_fields=%(fields)s::jsonb"""
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT a.id,a.status,c.id FROM (
                SELECT id,status FROM feature_batches WHERE {where}
                ORDER BY cutoff_as_of DESC,id DESC LIMIT 1
            ) a LEFT JOIN LATERAL (
                SELECT id FROM feature_batches WHERE {where} AND status='complete'
                ORDER BY cutoff_as_of DESC,id DESC LIMIT 1
            ) c ON true""",
            params,
        )
        row = cur.fetchone()
    newest, status, complete = row if row else (None, None, None)
    return dict(
        batch=load_feature_batch(conn, complete) if complete else None,
        newest_attempt_id=newest,
        newest_attempt_status=status,
        selection_reason="no_complete_batch"
        if complete is None
        else "latest_complete"
        if newest == complete
        else "previous_complete",
    )
