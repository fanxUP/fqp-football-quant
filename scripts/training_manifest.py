"""Deterministic Maher-SPF training sample selection and manifest creation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime

MANIFEST_VERSION = "fqp.maher-spf-training-manifest/v1"
SELECTION_VERSION = "settled-official-score-team-history/v1"


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


def _iso(value: datetime | date | str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value, field_name).isoformat(timespec="microseconds")


def _candidate_from_row(row: CandidateMatch) -> CandidateMatch:
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
        reason=reason,
    )


def build_training_dataset(
    candidates: Iterable[CandidateMatch],
    *,
    min_matches: int = 3,
    cutoff_at: datetime | date | str | None = None,
) -> TrainingDataset:
    """Select stable Maher inputs and hash their identities, labels, and policy.

    With a cutoff, only pre-cutoff fixtures enter the manifest. Labels count as
    available only when their official publish time is known and no later than
    the cutoff. Team history thresholds are calculated from that same as-of set.
    """
    if min_matches < 1:
        raise ValueError("min_matches must be at least 1")
    cutoff = _normalize_datetime(cutoff_at, "cutoff_at") if cutoff_at is not None else None

    normalized = [_candidate_from_row(candidate) for candidate in candidates]
    match_ids = [candidate.match_id for candidate in normalized]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("candidate rows must contain each match_id at most once")

    # Future fixtures are outside the as-of dataset, so adding them cannot alter
    # a historical manifest hash or the eligible-team history counts.
    scoped = [
        candidate for candidate in normalized if cutoff is None or candidate.kickoff_at < cutoff
    ]
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
        if (candidate.match_status or "").lower() != "settled":
            reason = "match_not_settled"
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
        elif cutoff is not None and candidate.official_publish_time is None:
            reason = "official_publish_time_unknown"
        elif (
            cutoff is not None
            and candidate.official_publish_time is not None
            and candidate.official_publish_time > cutoff
        ):
            reason = "label_published_after_cutoff"

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
            )
        )

    excluded.sort(key=lambda sample: (sample.kickoff_time, sample.match_id, sample.reason))
    training_start = included[0].kickoff_time if included else None
    training_end = included[-1].kickoff_time if included else None
    cutoff_text = _iso(cutoff, "cutoff_at")
    hash_payload = {
        "version": MANIFEST_VERSION,
        "selection_version": SELECTION_VERSION,
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
        selection_version=SELECTION_VERSION,
        minimum_team_matches=min_matches,
        cutoff_at=cutoff_text,
        training_start=training_start,
        training_end=training_end,
        included=tuple(included),
        excluded=tuple(excluded),
        sha256=hashlib.sha256(canonical).hexdigest(),
    )
    return TrainingDataset(samples=manifest.included, manifest=manifest)
