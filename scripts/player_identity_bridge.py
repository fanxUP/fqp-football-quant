"""Auditable source player ID mappings into the canonical FQP player catalog."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


class IdentityLinkError(ValueError):
    """The requested source identity mapping violates the bridge contract."""


class VerifiedIdentityConflict(IdentityLinkError):
    """A verified external identity is being pointed at another canonical player."""


_SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_STATUSES = {"unresolved", "candidate", "verified", "rejected"}
_RETURNING_FIELDS = (
    "source_name",
    "external_player_id",
    "player_id",
    "status",
    "evidence_refs",
    "matching_method",
    "confidence",
    "reviewed_by",
    "reviewed_at",
    "revision",
    "created_at",
    "updated_at",
)
_RETURNING = ", ".join(_RETURNING_FIELDS)


def _validate_identity(source_name: str, external_player_id: str) -> tuple[str, str]:
    if not isinstance(source_name, str) or not isinstance(external_player_id, str):
        raise IdentityLinkError("source name and external player ID must be strings")
    source = source_name.strip().casefold()
    external_id = external_player_id.strip()
    if not _SOURCE_NAME.fullmatch(source):
        raise IdentityLinkError("source name must be a lowercase source key")
    if not external_id or len(external_id) > 128 or "\x00" in external_id:
        raise IdentityLinkError("external player ID must be non-empty and at most 128 characters")
    return source, external_id


def _validate_fields(
    *,
    source_name: str,
    external_player_id: str,
    player_id: int | None,
    status: str,
    evidence_refs: list[str] | tuple[str, ...],
    matching_method: str,
    confidence: int | float | Decimal,
    reviewed_by: str | None,
    reviewed_at: datetime | None,
) -> dict[str, Any]:
    source, external_id = _validate_identity(source_name, external_player_id)
    if not isinstance(status, str) or status not in _STATUSES:
        raise IdentityLinkError(f"unsupported mapping status: {status!r}")
    if player_id is not None and (type(player_id) is not int or player_id <= 0):
        raise IdentityLinkError("canonical player ID must be a positive integer or None")
    if status == "unresolved" and player_id is not None:
        raise IdentityLinkError("unresolved mapping cannot point to a canonical player")
    if not isinstance(evidence_refs, (list, tuple)):
        raise IdentityLinkError("evidence references must be a list or tuple")
    refs = sorted({ref.strip() for ref in evidence_refs if isinstance(ref, str) and ref.strip()})
    if len(refs) != len(evidence_refs) or not refs or len(refs) > 64:
        raise IdentityLinkError("one to 64 non-empty evidence references are required")
    if any(len(ref) > 1024 for ref in refs):
        raise IdentityLinkError("evidence references may not exceed 1024 characters")
    if (
        not isinstance(matching_method, str)
        or not matching_method.strip()
        or len(matching_method.strip()) > 64
    ):
        raise IdentityLinkError("matching method must be non-empty and at most 64 characters")
    try:
        score = Decimal(str(confidence))
    except InvalidOperation, ValueError:
        raise IdentityLinkError("confidence must be a finite number from 0 to 1") from None
    if not score.is_finite() or score < 0 or score > 1:
        raise IdentityLinkError("confidence must be a finite number from 0 to 1")
    try:
        score = score.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise IdentityLinkError(
            "confidence cannot be represented with five decimal places"
        ) from None
    if reviewed_by is not None and not isinstance(reviewed_by, str):
        raise IdentityLinkError("reviewer name must be a string or None")
    reviewer = reviewed_by.strip() if isinstance(reviewed_by, str) else None
    if reviewer == "":
        reviewer = None
    if reviewer is not None and len(reviewer) > 128:
        raise IdentityLinkError("reviewer name may not exceed 128 characters")
    if reviewed_at is not None:
        if not isinstance(reviewed_at, datetime) or reviewed_at.utcoffset() is None:
            raise IdentityLinkError("review timestamp must be a timezone-aware datetime")
    if (reviewer is None) != (reviewed_at is None):
        raise IdentityLinkError("reviewer and review timestamp must be provided together")
    if status in {"verified", "rejected"}:
        if player_id is None and status == "verified":
            raise IdentityLinkError("verified mapping requires a canonical player ID")
        if reviewer is None or reviewed_at is None:
            raise IdentityLinkError(f"{status} mapping requires reviewer and review timestamp")
    return {
        "source_name": source,
        "external_player_id": external_id,
        "player_id": player_id,
        "status": status,
        "evidence_refs": refs,
        "matching_method": matching_method.strip(),
        "confidence": score,
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
    }


def _row_to_mapping(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_RETURNING_FIELDS, row, strict=True))


def upsert_player_identity_link(
    conn: Any,
    *,
    source_name: str,
    external_player_id: str,
    player_id: int | None,
    status: str,
    evidence_refs: list[str] | tuple[str, ...],
    matching_method: str,
    confidence: int | float | Decimal,
    reviewed_by: str | None = None,
    reviewed_at: datetime | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Create or revise an identity mapping and append an audit event atomically.

    This is an administrative import/review helper. The production `fqp` database
    role is deliberately read-only for these tables.
    """
    fields = _validate_fields(
        source_name=source_name,
        external_player_id=external_player_id,
        player_id=player_id,
        status=status,
        evidence_refs=evidence_refs,
        matching_method=matching_method,
        confidence=confidence,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_RETURNING} FROM player_identity_links "
            "WHERE source_name=%s AND external_player_id=%s FOR UPDATE",
            (fields["source_name"], fields["external_player_id"]),
        )
        existing_raw = cur.fetchone()
        inserted_raw = None
        if existing_raw is None:
            cur.execute(
                """INSERT INTO player_identity_links (
                       source_name, external_player_id, player_id, status, evidence_refs,
                       matching_method, confidence, reviewed_by, reviewed_at, revision
                   ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,1)
                   ON CONFLICT (source_name, external_player_id) DO NOTHING
                   RETURNING """
                + _RETURNING,
                (
                    fields["source_name"],
                    fields["external_player_id"],
                    fields["player_id"],
                    fields["status"],
                    json.dumps(fields["evidence_refs"], ensure_ascii=False),
                    fields["matching_method"],
                    fields["confidence"],
                    fields["reviewed_by"],
                    fields["reviewed_at"],
                ),
            )
            inserted_raw = cur.fetchone()
            if inserted_raw is None:
                cur.execute(
                    f"SELECT {_RETURNING} FROM player_identity_links "
                    "WHERE source_name=%s AND external_player_id=%s FOR UPDATE",
                    (fields["source_name"], fields["external_player_id"]),
                )
                existing_raw = cur.fetchone()
                if existing_raw is None:
                    raise IdentityLinkError("identity mapping disappeared during concurrent upsert")
        if inserted_raw is not None:
            result = _row_to_mapping(inserted_raw)
        else:
            existing = _row_to_mapping(existing_raw)
            comparable = (
                "player_id",
                "status",
                "evidence_refs",
                "matching_method",
                "confidence",
                "reviewed_by",
                "reviewed_at",
            )
            if all(existing[key] == fields[key] for key in comparable):
                if commit:
                    conn.commit()
                return existing
            if existing["status"] == "verified":
                if fields["status"] == "verified" and existing["player_id"] != fields["player_id"]:
                    raise VerifiedIdentityConflict(
                        "verified player identity cannot be remapped directly"
                    )
                if fields["status"] not in {"verified", "rejected", "unresolved"}:
                    raise VerifiedIdentityConflict(
                        "verified player identity must be rejected or unresolved before remapping"
                    )
                if fields["status"] == "rejected" and existing["player_id"] != fields["player_id"]:
                    raise VerifiedIdentityConflict(
                        "rejected identity must retain its prior canonical player"
                    )
                if fields["status"] == "unresolved" and fields["player_id"] is not None:
                    raise VerifiedIdentityConflict(
                        "unresolved identity cannot retain a canonical player"
                    )
            cur.execute(
                """UPDATE player_identity_links SET
                       player_id=%s, status=%s, evidence_refs=%s::jsonb,
                       matching_method=%s, confidence=%s, reviewed_by=%s,
                       reviewed_at=%s, revision=revision+1, updated_at=clock_timestamp()
                   WHERE source_name=%s AND external_player_id=%s
                   RETURNING """
                + _RETURNING,
                (
                    fields["player_id"],
                    fields["status"],
                    json.dumps(fields["evidence_refs"], ensure_ascii=False),
                    fields["matching_method"],
                    fields["confidence"],
                    fields["reviewed_by"],
                    fields["reviewed_at"],
                    fields["source_name"],
                    fields["external_player_id"],
                ),
            )
            result = _row_to_mapping(cur.fetchone())
    if commit:
        conn.commit()
    return result


def resolve_player_identity(conn: Any, source_name: str, external_player_id: str) -> int | None:
    """Return a canonical ID only for verified links, with exact API-Football legacy fallback."""
    source, external_id = _validate_identity(source_name, external_player_id)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT player_id,status FROM player_identity_links
               WHERE source_name=%s AND external_player_id=%s""",
            (source, external_id),
        )
        row = cur.fetchone()
        if row is not None:
            player_id, status = row
            return int(player_id) if status == "verified" and player_id is not None else None
        if source == "apifootball":
            cur.execute(
                "SELECT id FROM players WHERE player_code=%s", (f"apifootball:{external_id}",)
            )
            legacy = cur.fetchone()
            return int(legacy[0]) if legacy else None
    return None
