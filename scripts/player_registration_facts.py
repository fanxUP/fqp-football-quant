"""Store and read reviewed, effective-dated player registration facts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from scripts.data_contracts import to_utc


class RegistrationFactError(ValueError):
    """A registration fact violates its evidence or time contract."""


class RegistrationFactConflict(RegistrationFactError):
    """A source revision was replayed with different normalized content."""


_SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_STATUSES = {"unknown", "confirmed"}
_AUTHORITIES = {
    "unknown",
    "competition_registry",
    "governing_body_notice",
    "official_club_registration",
}
_FACT_FIELDS = (
    "source_name",
    "external_player_id",
    "source_competition_id",
    "source_season",
    "competition_season_id",
    "source_record_key",
    "source_revision",
    "content_sha256",
    "status",
    "eligible",
    "source_authority",
    "valid_from",
    "valid_to",
    "source_published_at",
    "acquired_at",
    "evidence_refs",
    "reviewed_by",
    "reviewed_at",
)
_RETURNING_FIELDS = ("id", *_FACT_FIELDS)
_RETURNING = ", ".join(_RETURNING_FIELDS)


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise RegistrationFactError(f"{field} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or "\x00" in normalized:
        raise RegistrationFactError(f"{field} must be non-empty text no longer than {limit}")
    return normalized


def _date(value: Any, field: str, *, required: bool) -> date | None:
    if value is None and not required:
        return None
    if isinstance(value, datetime):
        raise RegistrationFactError(f"{field} must be a calendar date, not a timestamp")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    if value is None and required:
        raise RegistrationFactError(f"{field} is required")
    raise RegistrationFactError(f"{field} must be an ISO calendar date")


def _timestamp(value: Any, field: str, *, required: bool) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, datetime):
        raise RegistrationFactError(f"{field} must be a timezone-aware timestamp")
    try:
        return to_utc(value)
    except ValueError as exc:
        raise RegistrationFactError(f"{field} must be timezone-aware") from exc


def _identity_key(source_name: Any, external_player_id: Any) -> tuple[str, str]:
    source = _required_text(source_name, "source_name", 64).casefold()
    external_id = _required_text(external_player_id, "external_player_id", 128)
    if not _SOURCE_NAME.fullmatch(source):
        raise RegistrationFactError("source_name must be a lowercase ASCII source key")
    return source, external_id


def validate_registration_fact(fact: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and validate one source revision without touching a database."""
    if not isinstance(fact, Mapping):
        raise RegistrationFactError("fact must be a mapping")
    source, external_id = _identity_key(fact.get("source_name"), fact.get("external_player_id"))
    source_competition_id = _required_text(
        fact.get("source_competition_id"), "source_competition_id", 128
    )
    source_season = _required_text(fact.get("source_season"), "source_season", 64)
    competition_season_id = fact.get("competition_season_id")
    if competition_season_id is not None and (
        type(competition_season_id) is not int or competition_season_id <= 0
    ):
        raise RegistrationFactError("competition_season_id must be a positive integer or None")
    source_record_key = _required_text(fact.get("source_record_key"), "source_record_key", 512)
    source_revision = _required_text(fact.get("source_revision"), "source_revision", 128)
    content_sha256 = fact.get("content_sha256")
    if not isinstance(content_sha256, str) or not _SHA256.fullmatch(content_sha256):
        raise RegistrationFactError("content_sha256 must be a lowercase SHA-256 digest")

    status = fact.get("status")
    if not isinstance(status, str) or status not in _STATUSES:
        raise RegistrationFactError("status must be unknown or confirmed")
    eligible = fact.get("eligible")
    if status == "unknown":
        if eligible is not None:
            raise RegistrationFactError("unknown facts cannot assert eligibility")
    elif type(eligible) is not bool:
        raise RegistrationFactError("confirmed facts require an explicit eligibility boolean")

    source_authority = fact.get("source_authority")
    if not isinstance(source_authority, str) or source_authority not in _AUTHORITIES:
        raise RegistrationFactError("unsupported source_authority")
    valid_from = _date(fact.get("valid_from"), "valid_from", required=status == "confirmed")
    valid_to = _date(fact.get("valid_to"), "valid_to", required=status == "confirmed")
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise RegistrationFactError("valid_to is exclusive and must be after valid_from")

    acquired_at = _timestamp(fact.get("acquired_at"), "acquired_at", required=True)
    assert acquired_at is not None
    source_published_at = _timestamp(
        fact.get("source_published_at"), "source_published_at", required=False
    )
    reviewed_by_raw = fact.get("reviewed_by")
    reviewed_by = (
        _required_text(reviewed_by_raw, "reviewed_by", 128) if reviewed_by_raw is not None else None
    )
    reviewed_at = _timestamp(fact.get("reviewed_at"), "reviewed_at", required=False)
    if (reviewed_by is None) != (reviewed_at is None):
        raise RegistrationFactError("reviewer and review timestamp must be provided together")

    evidence_refs = fact.get("evidence_refs")
    if not isinstance(evidence_refs, (list, tuple)) or not 1 <= len(evidence_refs) <= 64:
        raise RegistrationFactError("one to 64 evidence references are required")
    normalized_refs = [_required_text(ref, "evidence reference", 1024) for ref in evidence_refs]
    if len(set(normalized_refs)) != len(normalized_refs):
        raise RegistrationFactError("evidence references must be unique")

    if status == "confirmed":
        if competition_season_id is None:
            raise RegistrationFactError("confirmed facts require a canonical competition season")
        if source_authority == "unknown":
            raise RegistrationFactError("confirmed facts require a declared authoritative source")
        if reviewed_by is None or reviewed_at is None:
            raise RegistrationFactError("confirmed facts require human review")
        if reviewed_at < acquired_at:
            raise RegistrationFactError(
                "confirmed facts cannot be reviewed before they are acquired"
            )

    return {
        "source_name": source,
        "external_player_id": external_id,
        "source_competition_id": source_competition_id,
        "source_season": source_season,
        "competition_season_id": competition_season_id,
        "source_record_key": source_record_key,
        "source_revision": source_revision,
        "content_sha256": content_sha256,
        "status": status,
        "eligible": eligible,
        "source_authority": source_authority,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_published_at": source_published_at,
        "acquired_at": acquired_at,
        "evidence_refs": normalized_refs,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
    }


def _row_to_fact(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_RETURNING_FIELDS, row, strict=True))


def record_registration_fact(
    conn: Any, fact: Mapping[str, Any], *, commit: bool = True
) -> dict[str, Any]:
    """Append one reviewed source revision; exact replays are idempotent.

    This administrative writer does not bypass PostgreSQL grants. Runtime role
    ``fqp`` remains SELECT-only and cannot call it successfully to persist rows.
    """
    normalized = validate_registration_fact(fact)
    values = tuple(
        json.dumps(normalized[key], ensure_ascii=False, separators=(",", ":"))
        if key == "evidence_refs"
        else normalized[key]
        for key in _FACT_FIELDS
    )
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO player_registration_facts (
                   source_name,external_player_id,source_competition_id,source_season,
                   competition_season_id,source_record_key,source_revision,content_sha256,
                   status,eligible,source_authority,valid_from,valid_to,source_published_at,
                   acquired_at,evidence_refs,reviewed_by,reviewed_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
               ON CONFLICT (source_name,external_player_id,source_competition_id,source_season,
                            source_record_key,source_revision) DO NOTHING
               RETURNING id""",
            values,
        )
        inserted = cur.fetchone()
        if inserted is not None:
            result = {"id": int(inserted[0]), "inserted": True, "fact": normalized}
        else:
            key = tuple(
                normalized[name]
                for name in (
                    "source_name",
                    "external_player_id",
                    "source_competition_id",
                    "source_season",
                    "source_record_key",
                    "source_revision",
                )
            )
            cur.execute(
                f"SELECT {_RETURNING} FROM player_registration_facts "
                "WHERE source_name=%s AND external_player_id=%s AND source_competition_id=%s "
                "AND source_season=%s AND source_record_key=%s AND source_revision=%s",
                key,
            )
            existing_raw = cur.fetchone()
            if existing_raw is None:
                raise RegistrationFactConflict(
                    "source revision disappeared during idempotent insert"
                )
            existing = _row_to_fact(existing_raw)
            comparable = {name: existing[name] for name in _FACT_FIELDS}
            if comparable != normalized:
                raise RegistrationFactConflict(
                    "same source revision was replayed with conflicting fact or evidence"
                )
            result = {"id": int(existing["id"]), "inserted": False, "fact": normalized}
    if commit:
        conn.commit()
    return result


def _lookup_key(source_name: Any, external_player_id: Any) -> tuple[str, str]:
    return _identity_key(source_name, external_player_id)


def _valid_day(value: Any) -> date:
    parsed = _date(value, "valid_at", required=True)
    assert parsed is not None
    return parsed


def _canonical_player_at_cutoff(
    conn: Any, source_name: str, external_player_id: str, known_at: datetime
) -> tuple[int | None, datetime | None, datetime | None]:
    """Resolve only a verified mapping whose current revision was known by the cutoff.

    If a mapping was later changed or revoked, this deliberately returns unknown
    for earlier cutoffs rather than attempting to reconstruct a hidden audit row.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT player_id,status,updated_at,reviewed_at FROM player_identity_links
               WHERE source_name=%s AND external_player_id=%s""",
            (source_name, external_player_id),
        )
        row = cur.fetchone()
    if row is None:
        return None, None, None
    player_id, status, updated_at, reviewed_at = row
    if (
        status != "verified"
        or player_id is None
        or updated_at > known_at
        or reviewed_at is None
        or reviewed_at > known_at
    ):
        return None, updated_at, reviewed_at
    return int(player_id), updated_at, reviewed_at


def _authority_at_cutoff(conn: Any, source_name: str, known_at: datetime) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT authority,status,revision,created_at,reviewed_at
               FROM player_registration_authority_sources
               WHERE source_name=%s AND created_at <= %s AND reviewed_at <= %s
               ORDER BY revision DESC
               LIMIT 1""",
            (source_name, known_at, known_at),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return dict(
        zip(
            ("authority", "status", "revision", "created_at", "reviewed_at"),
            row,
            strict=True,
        )
    )


def get_registration_eligibility(
    conn: Any,
    *,
    source_name: str,
    external_player_id: str,
    source_competition_id: str,
    source_season: str,
    competition_season_id: int,
    valid_at: date | str,
    known_at: datetime,
) -> dict[str, Any]:
    """Resolve eligibility at a system-knowledge cutoff.

    A fact is visible only after acquisition, database insertion, and any required
    human review. Authority revisions are likewise invisible before insertion
    and review. This prevents late backfills or future reviews from rewriting
    what the system could have known at an earlier cutoff.
    """
    source, external_id = _lookup_key(source_name, external_player_id)
    source_competition = _required_text(source_competition_id, "source_competition_id", 128)
    season = _required_text(source_season, "source_season", 64)
    if type(competition_season_id) is not int or competition_season_id <= 0:
        raise RegistrationFactError("competition_season_id must be a positive integer")
    effective_day = _valid_day(valid_at)
    cutoff = _timestamp(known_at, "known_at", required=True)
    assert cutoff is not None

    with conn.cursor() as cur:
        cur.execute(
            """SELECT id,status,eligible,source_authority,valid_from,valid_to,acquired_at,
                      created_at,source_published_at,source_record_key,source_revision,
                      content_sha256,evidence_refs,reviewed_by,reviewed_at
               FROM player_registration_facts
               WHERE source_name=%s AND external_player_id=%s
                 AND source_competition_id=%s AND source_season=%s
                 AND competition_season_id=%s AND acquired_at <= %s AND created_at <= %s
                 AND (reviewed_at IS NULL OR reviewed_at <= %s)
               ORDER BY acquired_at DESC,id DESC
               LIMIT 1""",
            (
                source,
                external_id,
                source_competition,
                season,
                competition_season_id,
                cutoff,
                cutoff,
                cutoff,
            ),
        )
        row = cur.fetchone()

    if row is None:
        return {
            "status": "unknown",
            "eligible": None,
            "reason": "no_fact_known_at_cutoff",
            "fact_id": None,
            "canonical_player_resolved": False,
        }

    fields = (
        "id",
        "status",
        "eligible",
        "source_authority",
        "valid_from",
        "valid_to",
        "acquired_at",
        "created_at",
        "source_published_at",
        "source_record_key",
        "source_revision",
        "content_sha256",
        "evidence_refs",
        "reviewed_by",
        "reviewed_at",
    )
    fact = dict(zip(fields, row, strict=True))
    evidence = {name: fact[name] for name in fields if name != "eligible" and name != "status"}
    evidence.update({"status": fact["status"], "eligible": fact["eligible"]})
    if fact["status"] == "unknown":
        return {
            "status": "unknown",
            "eligible": None,
            "reason": "source_reports_unknown",
            "fact_id": int(fact["id"]),
            "canonical_player_resolved": False,
            "evidence": evidence,
        }
    authority = _authority_at_cutoff(conn, source, cutoff)
    if (
        authority is None
        or authority["status"] != "approved"
        or authority["authority"] != fact["source_authority"]
    ):
        return {
            "status": "unknown",
            "eligible": None,
            "reason": "authority_not_approved_at_cutoff",
            "fact_id": int(fact["id"]),
            "canonical_player_resolved": False,
            "evidence": evidence,
            "authority": authority,
        }
    if (
        fact["valid_from"] is None
        or fact["valid_from"] > effective_day
        or fact["valid_to"] is None
        or effective_day >= fact["valid_to"]
    ):
        return {
            "status": "unknown",
            "eligible": None,
            "reason": "outside_validity_interval",
            "fact_id": int(fact["id"]),
            "canonical_player_resolved": False,
            "evidence": evidence,
            "authority": authority,
        }
    canonical_player_id, mapping_updated_at, mapping_reviewed_at = _canonical_player_at_cutoff(
        conn, source, external_id, cutoff
    )
    return {
        "status": "confirmed",
        "eligible": fact["eligible"],
        "reason": "confirmed_effective_fact",
        "fact_id": int(fact["id"]),
        "canonical_player_resolved": canonical_player_id is not None,
        "evidence": evidence,
        "authority": authority,
        "canonical_player_id": canonical_player_id,
        "identity_mapping_updated_at": mapping_updated_at,
        "identity_mapping_reviewed_at": mapping_reviewed_at,
    }
