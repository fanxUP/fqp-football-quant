"""Deterministic Maher-SPF training sample selection and manifest creation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

MANIFEST_VERSION = "fqp.maher-spf-training-manifest/v2"
SELECTION_VERSION = "settled-source-observation-score-team-history/v2"
CURRENT_SELECTION_VERSION = "settled-official-score-team-history/v1"
OFFICIAL_TIMEZONE = ZoneInfo("Asia/Shanghai")

# Revision timestamps are written before their transaction commits. An
# immutable cutoff selection proves when a separate MVCC reader could first
# see a result revision; strict point-in-time labels use that witness instead.
RESULT_REVISION_VISIBILITY_CTE = """
result_revision_visibility AS MATERIALIZED (
    SELECT visible.revision_id, MIN(visible.as_of) AS committed_available_at
    FROM (
        SELECT cutoff.as_of,
               CASE
                   WHEN selected.item->>'revision_id' ~ '^[1-9][0-9]{0,18}$'
                   THEN CASE
                       WHEN (selected.item->>'revision_id')::numeric <= 9223372036854775807
                       THEN (selected.item->>'revision_id')::bigint
                   END
               END AS revision_id
        FROM (
            SELECT as_of, selections
            FROM observation_cutoffs
            WHERE selections @> '[{"source_id":"sporttery","domain":"results","subject_key":"full_time_score"}]'::jsonb
        ) cutoff
        CROSS JOIN LATERAL jsonb_array_elements(cutoff.selections) AS selected(item)
        WHERE selected.item->>'source_id'='sporttery'
          AND selected.item->>'domain'='results'
          AND selected.item->>'subject_key'='full_time_score'
          AND jsonb_typeof(selected.item->'revision_id')='number'
    ) visible
    JOIN observation_revisions revision
      ON revision.id=visible.revision_id AND revision.available_at<=visible.as_of
    WHERE visible.revision_id IS NOT NULL
    GROUP BY visible.revision_id
)
"""


@dataclass(frozen=True)
class ResultLabelObservation:
    """One immutable P104 result revision and its source/system availability times."""

    revision_id: int
    result_id: int
    fact_status: str
    home_goals: int | None
    away_goals: int | None
    published_at: datetime | None
    first_acquired_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class CandidateMatch:
    """One materialized official-match/result row before model eligibility filters."""

    match_id: int
    result_id: int | None
    kickoff_at: datetime
    home_team_id: int | None
    away_team_id: int | None
    home_goals: int | None
    away_goals: int | None
    match_status: str | None
    official_publish_time: datetime | None
    home_team_candidate_ids: tuple[int, ...] = ()
    away_team_candidate_ids: tuple[int, ...] = ()
    label_observations: tuple[ResultLabelObservation, ...] = ()
    result_observation_id: int | None = None
    result_fact_status: str | None = None
    result_published_at: datetime | None = None
    result_first_acquired_at: datetime | None = None
    result_available_at: datetime | None = None
    result_observation_missing: bool = False


@dataclass(frozen=True)
class TrainingSample:
    """A single included match; these exact records are converted to fit arrays."""

    ordinal: int
    match_id: int
    result_id: int
    kickoff_time: str
    official_publish_time: str | None
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int
    result_observation_id: int | None
    result_published_at: str | None
    result_first_acquired_at: str | None
    result_available_at: str | None
    label_source: str = "official_results.full_home_goals/full_away_goals"


@dataclass(frozen=True)
class ExcludedSample:
    match_id: int
    result_id: int | None
    kickoff_time: str
    official_publish_time: str | None
    home_team_id: int | None
    away_team_id: int | None
    home_goals: int | None
    away_goals: int | None
    match_status: str | None
    result_observation_id: int | None
    result_fact_status: str | None
    result_published_at: str | None
    result_first_acquired_at: str | None
    result_available_at: str | None
    reason: str


@dataclass(frozen=True)
class TrainingManifest:
    version: str
    selection_version: str
    minimum_team_matches: int
    cutoff_at: str | None
    training_start: str | None
    training_end: str | None
    included: tuple[TrainingSample, ...]
    excluded: tuple[ExcludedSample, ...]
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "selection_version": self.selection_version,
            "minimum_team_matches": self.minimum_team_matches,
            "cutoff_at": self.cutoff_at,
            "training_start": self.training_start,
            "training_end": self.training_end,
            "included": [asdict(sample) for sample in self.included],
            "excluded": [asdict(sample) for sample in self.excluded],
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class TrainingDataset:
    """Manifest and fit samples derived together from one materialized selection."""

    samples: tuple[TrainingSample, ...]
    manifest: TrainingManifest


def _normalize_datetime(value: datetime | date | str, field_name: str) -> datetime:
    if isinstance(value, str):
        normalized = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        normalized = value
    elif isinstance(value, date):
        normalized = datetime.combine(value, datetime.min.time())
    else:
        raise TypeError(f"{field_name} must be a date, datetime, or ISO timestamp")
    if normalized.tzinfo is not None and normalized.utcoffset() is not None:
        raise ValueError(f"{field_name} must be timezone-naive to match TIMESTAMP columns")
    return normalized


def _normalize_aware_datetime(value: datetime | str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    elif isinstance(value, datetime):
        normalized = value
    else:
        raise TypeError(f"{field_name} must be a timezone-aware datetime or ISO timestamp")
    if normalized.tzinfo is None or normalized.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return normalized.astimezone(UTC)


def _evidence_iso(value: datetime | None, field_name: str) -> str | None:
    normalized = _normalize_aware_datetime(value, field_name)
    return normalized.isoformat(timespec="microseconds") if normalized is not None else None


def _normalize_result_observation(value: ResultLabelObservation | dict) -> ResultLabelObservation:
    if isinstance(value, ResultLabelObservation):
        row = value
    elif isinstance(value, dict):
        row = ResultLabelObservation(
            revision_id=cast(int, value.get("revision_id")),
            result_id=cast(int, value.get("result_id")),
            fact_status=cast(str, value.get("fact_status")),
            home_goals=value.get("home_goals"),
            away_goals=value.get("away_goals"),
            published_at=value.get("published_at"),
            first_acquired_at=cast(datetime, value.get("first_acquired_at")),
            available_at=cast(datetime, value.get("available_at")),
        )
    else:
        raise TypeError("label observations must be typed rows or mappings")
    if type(row.revision_id) is not int or row.revision_id <= 0:
        raise ValueError("result observation revision_id must be a positive integer")
    if type(row.result_id) is not int or row.result_id <= 0:
        raise ValueError("result observation result_id must be a positive integer")
    if row.fact_status not in {
        "value",
        "confirmed_absent",
        "unknown",
        "not_published",
        "not_covered",
        "not_applicable",
        "conflict",
        "stale",
    }:
        raise ValueError("result observation fact_status is unsupported")
    published = _normalize_aware_datetime(row.published_at, "result published_at")
    acquired = _normalize_aware_datetime(row.first_acquired_at, "result first_acquired_at")
    available = _normalize_aware_datetime(row.available_at, "result available_at")
    if acquired is None or available is None:
        raise ValueError("result observation requires acquisition and availability timestamps")
    if available < acquired or (published is not None and available < published):
        raise ValueError("result availability cannot precede its acquisition or publication")
    if row.fact_status == "value":
        if (
            type(row.home_goals) is not int
            or row.home_goals < 0
            or type(row.away_goals) is not int
            or row.away_goals < 0
        ):
            raise ValueError("value result observations require non-negative integer scores")
    elif row.home_goals is not None or row.away_goals is not None:
        raise ValueError("non-value result observations cannot carry score labels")
    return ResultLabelObservation(
        revision_id=row.revision_id,
        result_id=row.result_id,
        fact_status=row.fact_status,
        home_goals=row.home_goals,
        away_goals=row.away_goals,
        published_at=published,
        first_acquired_at=acquired,
        available_at=available,
    )


def _cutoff_utc(cutoff: datetime) -> datetime:
    """Interpret legacy naive cutoff columns as Beijing business time."""
    return cutoff.replace(tzinfo=OFFICIAL_TIMEZONE).astimezone(UTC)


def _candidate_at_cutoff(candidate: CandidateMatch, cutoff: datetime) -> CandidateMatch:
    cutoff_utc = _cutoff_utc(cutoff)
    observations = list(candidate.label_observations)
    available = [
        observation for observation in observations if observation.available_at < cutoff_utc
    ]
    if not available:
        return replace(
            candidate,
            result_id=None,
            home_goals=None,
            away_goals=None,
            match_status=None,
            official_publish_time=None,
            result_observation_id=None,
            result_fact_status=None,
            result_published_at=None,
            result_first_acquired_at=None,
            result_available_at=None,
            result_observation_missing=True,
        )
    observation = max(available, key=lambda row: (row.available_at, row.revision_id))
    assert observation.available_at is not None
    local_publication = (
        observation.published_at.astimezone(OFFICIAL_TIMEZONE).replace(tzinfo=None)
        if observation.published_at is not None
        else None
    )
    is_value = observation.fact_status == "value"
    return replace(
        candidate,
        result_id=observation.result_id,
        home_goals=observation.home_goals if is_value else None,
        away_goals=observation.away_goals if is_value else None,
        match_status="settled" if is_value else None,
        official_publish_time=local_publication,
        result_observation_id=observation.revision_id,
        result_fact_status=observation.fact_status,
        result_published_at=observation.published_at,
        result_first_acquired_at=observation.first_acquired_at,
        result_available_at=observation.available_at,
        result_observation_missing=False,
    )


def _iso(value: datetime | date | str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value, field_name).isoformat(timespec="microseconds")


def _candidate_from_row(row: CandidateMatch) -> CandidateMatch:
    observations = tuple(
        sorted(
            (_normalize_result_observation(item) for item in row.label_observations),
            key=lambda item: (item.available_at, item.revision_id),
        )
    )
    if len(observations) > 64:
        raise ValueError("a match has more than 64 result observation revisions")
    return CandidateMatch(
        match_id=int(row.match_id),
        result_id=int(row.result_id) if row.result_id is not None else None,
        kickoff_at=_normalize_datetime(row.kickoff_at, "kickoff_at"),
        home_team_id=int(row.home_team_id) if row.home_team_id is not None else None,
        away_team_id=int(row.away_team_id) if row.away_team_id is not None else None,
        home_goals=int(row.home_goals) if row.home_goals is not None else None,
        away_goals=int(row.away_goals) if row.away_goals is not None else None,
        match_status=row.match_status,
        official_publish_time=(
            _normalize_datetime(row.official_publish_time, "official_publish_time")
            if row.official_publish_time is not None
            else None
        ),
        home_team_candidate_ids=tuple(
            sorted(int(team_id) for team_id in row.home_team_candidate_ids)
        ),
        away_team_candidate_ids=tuple(
            sorted(int(team_id) for team_id in row.away_team_candidate_ids)
        ),
        label_observations=observations,
        result_observation_id=(
            int(row.result_observation_id) if row.result_observation_id is not None else None
        ),
        result_fact_status=row.result_fact_status,
        result_published_at=_normalize_aware_datetime(
            row.result_published_at, "result_published_at"
        ),
        result_first_acquired_at=_normalize_aware_datetime(
            row.result_first_acquired_at, "result_first_acquired_at"
        ),
        result_available_at=_normalize_aware_datetime(
            row.result_available_at, "result_available_at"
        ),
        result_observation_missing=bool(row.result_observation_missing),
    )


def _team_identity_ambiguity_reason(candidate: CandidateMatch) -> str:
    details = []
    for side, candidate_ids in (
        ("home", candidate.home_team_candidate_ids),
        ("away", candidate.away_team_candidate_ids),
    ):
        if len(candidate_ids) > 1:
            details.append(f"{side}=[{','.join(map(str, candidate_ids))}]")
    return "team_identity_ambiguous:" + ";".join(details)


def _excluded_sample(candidate: CandidateMatch, reason: str) -> ExcludedSample:
    if len(candidate.home_team_candidate_ids) > 1 or len(candidate.away_team_candidate_ids) > 1:
        ambiguity = _team_identity_ambiguity_reason(candidate)
        if ambiguity not in reason:
            reason = f"{reason};{ambiguity}"
    return ExcludedSample(
        match_id=candidate.match_id,
        result_id=candidate.result_id,
        kickoff_time=_iso(candidate.kickoff_at, "kickoff_at") or "",
        official_publish_time=_iso(candidate.official_publish_time, "official_publish_time"),
        home_team_id=candidate.home_team_id,
        away_team_id=candidate.away_team_id,
        home_goals=candidate.home_goals,
        away_goals=candidate.away_goals,
        match_status=candidate.match_status,
        result_observation_id=candidate.result_observation_id,
        result_fact_status=candidate.result_fact_status,
        result_published_at=_evidence_iso(candidate.result_published_at, "result_published_at"),
        result_first_acquired_at=_evidence_iso(
            candidate.result_first_acquired_at, "result_first_acquired_at"
        ),
        result_available_at=_evidence_iso(candidate.result_available_at, "result_available_at"),
        reason=reason,
    )


def build_training_dataset(
    candidates: Iterable[CandidateMatch],
    *,
    min_matches: int = 3,
    cutoff_at: datetime | date | str | None = None,
) -> TrainingDataset:
    """Select stable Maher inputs and hash their identities, labels, and policy.

    With a cutoff, only pre-cutoff fixtures and source-observed labels whose
    publication, acquisition, and system availability all precede that cutoff
    enter the fit. Team history thresholds use the same as-of set.
    """
    if min_matches < 1:
        raise ValueError("min_matches must be at least 1")
    cutoff = _normalize_datetime(cutoff_at, "cutoff_at") if cutoff_at is not None else None
    selection_version = SELECTION_VERSION if cutoff is not None else CURRENT_SELECTION_VERSION

    normalized = [_candidate_from_row(candidate) for candidate in candidates]
    match_ids = [candidate.match_id for candidate in normalized]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("candidate rows must contain each match_id at most once")

    # Future fixtures are outside the as-of dataset, so adding them cannot alter
    # a historical manifest hash or the eligible-team history counts.
    scoped = [
        candidate for candidate in normalized if cutoff is None or candidate.kickoff_at < cutoff
    ]
    if cutoff is not None:
        scoped = [_candidate_at_cutoff(candidate, cutoff) for candidate in scoped]
    scoped.sort(
        key=lambda candidate: (
            candidate.kickoff_at,
            candidate.match_id,
            candidate.result_id if candidate.result_id is not None else -1,
        )
    )

    base_valid: list[CandidateMatch] = []
    excluded: list[ExcludedSample] = []
    for candidate in scoped:
        reason: str | None = None
        if cutoff is not None and candidate.result_observation_missing:
            reason = "result_observation_missing"
        elif cutoff is not None and candidate.result_fact_status != "value":
            reason = "result_observation_not_value"
        elif (candidate.match_status or "").lower() != "settled":
            reason = "match_not_settled"
        elif cutoff is not None and candidate.result_published_at is None:
            reason = "official_publish_time_unknown"
        elif (
            cutoff is not None
            and candidate.result_published_at is not None
            and candidate.result_published_at < _cutoff_utc(candidate.kickoff_at)
        ):
            reason = "label_published_before_kickoff"
        elif (
            cutoff is not None
            and candidate.result_published_at is not None
            and candidate.result_published_at >= _cutoff_utc(cutoff)
        ):
            reason = "label_published_after_cutoff"
        elif cutoff is not None and (
            candidate.result_first_acquired_at is None or candidate.result_available_at is None
        ):
            reason = "label_system_availability_unknown"
        elif (
            cutoff is not None
            and candidate.result_first_acquired_at is not None
            and candidate.result_first_acquired_at >= _cutoff_utc(cutoff)
        ):
            reason = "label_first_acquired_at_or_after_cutoff"
        elif (
            cutoff is not None
            and candidate.result_available_at is not None
            and candidate.result_available_at >= _cutoff_utc(cutoff)
        ):
            reason = "label_available_at_or_after_cutoff"
        elif candidate.result_id is None:
            reason = "result_missing"
        elif candidate.home_goals is None or candidate.away_goals is None:
            reason = "official_score_missing"
        elif (
            len(candidate.home_team_candidate_ids) > 1 or len(candidate.away_team_candidate_ids) > 1
        ):
            reason = _team_identity_ambiguity_reason(candidate)
        elif candidate.home_team_id is None or candidate.away_team_id is None:
            reason = "team_unmapped"

        if reason is not None:
            excluded.append(_excluded_sample(candidate, reason))
        else:
            base_valid.append(candidate)

    team_counts: dict[int, int] = {}
    for candidate in base_valid:
        assert candidate.home_team_id is not None
        assert candidate.away_team_id is not None
        team_counts[candidate.home_team_id] = team_counts.get(candidate.home_team_id, 0) + 1
        team_counts[candidate.away_team_id] = team_counts.get(candidate.away_team_id, 0) + 1

    included: list[TrainingSample] = []
    for candidate in base_valid:
        assert candidate.home_team_id is not None
        assert candidate.away_team_id is not None
        assert candidate.result_id is not None
        assert candidate.home_goals is not None
        assert candidate.away_goals is not None
        if (
            team_counts[candidate.home_team_id] < min_matches
            or team_counts[candidate.away_team_id] < min_matches
        ):
            excluded.append(_excluded_sample(candidate, "team_below_minimum_history"))
            continue
        included.append(
            TrainingSample(
                ordinal=len(included),
                match_id=candidate.match_id,
                result_id=candidate.result_id,
                kickoff_time=_iso(candidate.kickoff_at, "kickoff_at") or "",
                official_publish_time=_iso(
                    candidate.official_publish_time, "official_publish_time"
                ),
                home_team_id=candidate.home_team_id,
                away_team_id=candidate.away_team_id,
                home_goals=candidate.home_goals,
                away_goals=candidate.away_goals,
                result_observation_id=candidate.result_observation_id,
                result_published_at=_evidence_iso(
                    candidate.result_published_at, "result_published_at"
                ),
                result_first_acquired_at=_evidence_iso(
                    candidate.result_first_acquired_at, "result_first_acquired_at"
                ),
                result_available_at=_evidence_iso(
                    candidate.result_available_at, "result_available_at"
                ),
                label_source=(
                    "source_observation:sporttery/results/full_time_score"
                    if candidate.result_observation_id is not None
                    else "official_results.full_home_goals/full_away_goals"
                ),
            )
        )

    excluded.sort(key=lambda sample: (sample.kickoff_time, sample.match_id, sample.reason))
    training_start = included[0].kickoff_time if included else None
    training_end = included[-1].kickoff_time if included else None
    cutoff_text = _iso(cutoff, "cutoff_at")
    hash_payload = {
        "version": MANIFEST_VERSION,
        "selection_version": selection_version,
        "minimum_team_matches": min_matches,
        "cutoff_at": cutoff_text,
        "training_start": training_start,
        "training_end": training_end,
        "included": [asdict(sample) for sample in included],
        "excluded": [asdict(sample) for sample in excluded],
    }
    canonical = json.dumps(
        hash_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest = TrainingManifest(
        version=MANIFEST_VERSION,
        selection_version=selection_version,
        minimum_team_matches=min_matches,
        cutoff_at=cutoff_text,
        training_start=training_start,
        training_end=training_end,
        included=tuple(included),
        excluded=tuple(excluded),
        sha256=hashlib.sha256(canonical).hexdigest(),
    )
    return TrainingDataset(samples=manifest.included, manifest=manifest)
