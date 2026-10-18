"""Small shared data vocabulary; no database, transport, or model side effects.

The version identifies a contract/policy, not a persisted mapping revision or
proof that historical observations can be replayed (P104 owns that evidence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

CONTRACT_VERSION = "fqp-data/v1"
MAPPING_POLICY_VERSION = "source-alias/v1"
_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


class EntityKind(StrEnum):
    TEAM = "team"
    PLAYER = "player"
    COMPETITION = "competition"
    SEASON = "season"
    COMPETITION_SEASON = "competition_season"
    FIXTURE = "fixture"
    OFFICIAL_MATCH = "official_match"


class FactStatus(StrEnum):
    VALUE = "value"
    CONFIRMED_ABSENT = "confirmed_absent"
    UNKNOWN = "unknown"
    NOT_PUBLISHED = "not_published"
    NOT_COVERED = "not_covered"
    NOT_APPLICABLE = "not_applicable"
    CONFLICT = "conflict"
    STALE = "stale"


class AcquisitionStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    QUOTA_EXHAUSTED = "quota_exhausted"
    FORBIDDEN = "forbidden"
    FAILED = "failed"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


class DataPurpose(StrEnum):
    RESEARCH = "research"
    PREDICTION = "prediction"
    DISPLAY = "display"
    SETTLEMENT = "settlement"
    OPERATIONS = "operations"
    CREDENTIAL_ADMIN = "credential_admin"


def _validate_namespace(namespace: str) -> None:
    if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
        raise ValueError("identity namespace must be an explicit registered source key")


@dataclass(frozen=True)
class ExternalIdentity:
    entity_kind: EntityKind
    namespace: str
    external_id: str

    def __post_init__(self) -> None:
        _validate_namespace(self.namespace)
        if not isinstance(self.entity_kind, EntityKind):
            raise ValueError("entity_kind must be an EntityKind")
        if not isinstance(self.external_id, str) or not self.external_id.strip():
            raise ValueError("external_id must be a non-empty provider string")
        if self.external_id != self.external_id.strip():
            raise ValueError("external_id must not have surrounding whitespace")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.entity_kind.value, self.namespace, self.external_id


@dataclass(frozen=True)
class IdentityResolution:
    entity_kind: EntityKind
    namespace: str
    requested_key: str
    candidate_ids: tuple[int, ...]
    mapping_policy_version: str = MAPPING_POLICY_VERSION
    mapping_revision: str | None = None

    def __post_init__(self) -> None:
        _validate_namespace(self.namespace)
        if not isinstance(self.entity_kind, EntityKind):
            raise ValueError("entity_kind must be an EntityKind")
        if not isinstance(self.candidate_ids, tuple) or any(
            type(candidate) is not int or candidate <= 0 for candidate in self.candidate_ids
        ):
            raise ValueError("candidate IDs must be positive database integers")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate IDs must be distinct")

    @property
    def status(self) -> ResolutionStatus:
        if not self.candidate_ids:
            return ResolutionStatus.UNRESOLVED
        if len(self.candidate_ids) == 1:
            return ResolutionStatus.RESOLVED
        return ResolutionStatus.AMBIGUOUS

    @property
    def resolved_id(self) -> int | None:
        return self.candidate_ids[0] if self.status == ResolutionStatus.RESOLVED else None


def to_utc(value: datetime, *, naive_timezone: str | None = None) -> datetime:
    """Convert with an explicit legacy producer timezone; never guess for naive time."""
    if value.tzinfo is None or value.utcoffset() is None:
        if not naive_timezone:
            raise ValueError("naive timestamp requires its producer timezone")
        zone = ZoneInfo(naive_timezone)
        first = value.replace(tzinfo=zone, fold=0)
        second = value.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("ambiguous or nonexistent local time requires an aware timestamp")
        value = first
    return value.astimezone(UTC)
