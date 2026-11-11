from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import numpy as np

from scripts.mle_trainer import _load_training_dataset, fit_maher_poisson
from scripts.training_manifest import (
    CURRENT_SELECTION_VERSION,
    CandidateMatch,
    ResultLabelObservation,
    build_training_dataset,
)


def _candidate(
    match_id: int,
    *,
    kickoff: str,
    result_id: int | None = None,
    home_team_id: int | None = 10,
    away_team_id: int | None = 20,
    home_goals: int | None = 1,
    away_goals: int | None = 0,
    match_status: str = "settled",
    published: str | None = "2026-01-02T00:00:00",
) -> CandidateMatch:
    return CandidateMatch(
        match_id=match_id,
        result_id=result_id if result_id is not None else match_id + 1000,
        kickoff_at=datetime.fromisoformat(kickoff),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_goals=home_goals,
        away_goals=away_goals,
        match_status=match_status,
        official_publish_time=(
            datetime.fromisoformat(published) if published is not None else None
        ),
    )


def _result_observation(
    revision_id: int,
    result_id: int,
    *,
    published_local: str,
    available_local: str | None = None,
    fact_status: str = "value",
    home_goals: int | None = 1,
    away_goals: int | None = 0,
) -> ResultLabelObservation:
    published = datetime.fromisoformat(published_local).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    acquired = published + timedelta(minutes=5)
    available = (
        datetime.fromisoformat(available_local).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        if available_local
        else acquired + timedelta(minutes=5)
    )
    return ResultLabelObservation(
        revision_id=revision_id,
        result_id=result_id,
        fact_status=fact_status,
        home_goals=home_goals,
        away_goals=away_goals,
        published_at=published,
        first_acquired_at=acquired,
        available_at=available,
    )


def test_manifest_rows_match_the_exact_maher_fit_input_and_hash_is_stable() -> None:
    candidates = [
        _candidate(2, kickoff="2026-01-02T20:00:00", home_goals=2, away_goals=1),
        _candidate(1, kickoff="2026-01-01T20:00:00", home_goals=0, away_goals=0),
        _candidate(3, kickoff="2026-01-03T20:00:00", home_goals=1, away_goals=2),
    ]
    first = build_training_dataset(candidates, min_matches=1)
    shuffled = build_training_dataset(list(reversed(candidates)), min_matches=1)

    assert [sample.match_id for sample in first.samples] == [1, 2, 3]
    assert first.manifest.included == first.samples
    assert first.manifest.sha256 == shuffled.manifest.sha256
    assert first.manifest.included == shuffled.manifest.included

    changed_label = [
        _candidate(2, kickoff="2026-01-02T20:00:00", home_goals=3, away_goals=1),
        candidates[1],
        candidates[2],
    ]
    assert build_training_dataset(changed_label, min_matches=1).manifest.sha256 != (
        first.manifest.sha256
    )


def test_current_projection_fit_manifest_does_not_claim_source_observation_selection() -> None:
    dataset = build_training_dataset([_candidate(1, kickoff="2026-01-01T20:00:00")], min_matches=1)

    assert dataset.manifest.selection_version == CURRENT_SELECTION_VERSION
    assert dataset.manifest.selection_version == "settled-official-score-team-history/v1"
    assert dataset.manifest.included[0].label_source == (
        "official_results.full_home_goals/full_away_goals"
    )
    assert dataset.manifest.included[0].result_observation_id is None


def test_cutoff_excludes_unavailable_labels_and_future_matches_without_hash_drift() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    candidates = [
        replace(
            _candidate(
                1,
                kickoff="2026-01-01T20:00:00",
                published="2026-01-02T00:00:00",
            ),
            label_observations=(
                _result_observation(91, 1001, published_local="2026-01-02T00:00:00"),
            ),
        ),
        replace(
            _candidate(2, kickoff="2026-01-02T20:00:00"),
            label_observations=(
                _result_observation(92, 1002, published_local="2026-01-06T00:00:00"),
            ),
        ),
        _candidate(3, kickoff="2026-01-06T20:00:00"),
    ]

    before_future_row = build_training_dataset(candidates[:2], min_matches=1, cutoff_at=cutoff)
    with_future_row = build_training_dataset(candidates, min_matches=1, cutoff_at=cutoff)

    assert [sample.match_id for sample in with_future_row.samples] == [1]
    assert [entry.reason for entry in with_future_row.manifest.excluded] == [
        "result_observation_missing"
    ]
    assert before_future_row.manifest.sha256 == with_future_row.manifest.sha256


def test_cutoff_uses_source_observation_label_and_records_all_availability_times() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    observation = ResultLabelObservation(
        revision_id=81,
        result_id=1081,
        fact_status="value",
        home_goals=1,
        away_goals=0,
        published_at=datetime(2026, 1, 2, 12, tzinfo=UTC),
        first_acquired_at=datetime(2026, 1, 2, 12, 5, tzinfo=UTC),
        available_at=datetime(2026, 1, 2, 12, 10, tzinfo=UTC),
    )
    candidate = CandidateMatch(
        **{
            **_candidate(
                1,
                kickoff="2026-01-01T20:00:00",
                home_goals=9,
                away_goals=9,
            ).__dict__,
            "label_observations": (observation,),
        }
    )

    dataset = build_training_dataset([candidate], min_matches=1, cutoff_at=cutoff)

    assert len(dataset.samples) == 1
    sample = dataset.samples[0]
    assert (sample.home_goals, sample.away_goals) == (1, 0)
    assert sample.result_observation_id == 81
    assert sample.result_published_at == "2026-01-02T12:00:00.000000+00:00"
    assert sample.result_first_acquired_at == "2026-01-02T12:05:00.000000+00:00"
    assert sample.result_available_at == "2026-01-02T12:10:00.000000+00:00"
    assert sample.label_source == "source_observation:sporttery/results/full_time_score"


def test_cutoff_excludes_missing_or_not_yet_available_result_observations() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    no_observation = _candidate(1, kickoff="2026-01-01T20:00:00")
    at_cutoff = CandidateMatch(
        **{
            **_candidate(2, kickoff="2026-01-02T20:00:00").__dict__,
            "label_observations": (
                ResultLabelObservation(
                    revision_id=82,
                    result_id=1082,
                    fact_status="value",
                    home_goals=2,
                    away_goals=0,
                    published_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
                    first_acquired_at=datetime(2026, 1, 4, 16, tzinfo=UTC),
                    available_at=datetime(2026, 1, 4, 16, tzinfo=UTC),
                ),
            ),
        }
    )
    unconfirmed = CandidateMatch(
        **{
            **_candidate(3, kickoff="2026-01-03T20:00:00").__dict__,
            "label_observations": (
                ResultLabelObservation(
                    revision_id=83,
                    result_id=1083,
                    fact_status="unknown",
                    home_goals=None,
                    away_goals=None,
                    published_at=datetime(2026, 1, 4, 12, tzinfo=UTC),
                    first_acquired_at=datetime(2026, 1, 4, 12, 5, tzinfo=UTC),
                    available_at=datetime(2026, 1, 4, 12, 10, tzinfo=UTC),
                ),
            ),
        }
    )

    dataset = build_training_dataset(
        [no_observation, at_cutoff, unconfirmed], min_matches=1, cutoff_at=cutoff
    )

    assert dataset.samples == ()
    assert [(row.match_id, row.reason) for row in dataset.manifest.excluded] == [
        (1, "result_observation_missing"),
        (2, "result_observation_missing"),
        (3, "result_observation_not_value"),
    ]


def test_future_result_revision_does_not_change_an_as_of_training_manifest() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    candidate_without_observation = _candidate(
        1,
        kickoff="2026-01-01T20:00:00",
        home_goals=9,
        away_goals=9,
        match_status="scheduled",
    )
    candidate_with_future_observation = replace(
        candidate_without_observation,
        match_status="settled",
        label_observations=(
            _result_observation(
                91,
                1091,
                published_local="2026-01-06T00:00:00",
                home_goals=1,
                away_goals=0,
            ),
        ),
    )

    without_future = build_training_dataset(
        [candidate_without_observation], min_matches=1, cutoff_at=cutoff
    )
    with_future = build_training_dataset(
        [candidate_with_future_observation], min_matches=1, cutoff_at=cutoff
    )

    assert without_future.manifest.sha256 == with_future.manifest.sha256
    assert with_future.manifest.excluded[0].reason == "result_observation_missing"
    assert with_future.manifest.excluded[0].result_observation_id is None
    assert with_future.manifest.excluded[0].result_published_at is None
    assert with_future.manifest.excluded[0].result_first_acquired_at is None
    assert with_future.manifest.excluded[0].result_available_at is None


def test_database_loader_applies_cutoff_before_materializing_rows() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchall.return_value = [
        (
            1,
            1001,
            datetime(2026, 1, 1, 20),
            datetime(2026, 1, 2),
            10,
            [10],
            20,
            [20],
            1,
            0,
            "settled",
            [
                {
                    "revision_id": 81,
                    "result_id": 1001,
                    "fact_status": "value",
                    "home_goals": 1,
                    "away_goals": 0,
                    "published_at": datetime(2026, 1, 2, 12, tzinfo=UTC),
                    "first_acquired_at": datetime(2026, 1, 2, 12, 5, tzinfo=UTC),
                    "available_at": datetime(2026, 1, 2, 12, 10, tzinfo=UTC),
                }
            ],
        )
    ]

    dataset = _load_training_dataset(conn, min_matches=1, cutoff_at=cutoff)

    query, params = cur.execute.call_args.args
    assert "WHERE m.kickoff_time < %s" in " ".join(query.split())
    assert "observation_streams" in query
    assert params == (cutoff,)
    assert dataset.manifest.cutoff_at == "2026-01-05T00:00:00.000000"
    assert [sample.match_id for sample in dataset.samples] == [1]


def test_manifest_assigns_stable_reasons_to_excluded_rows() -> None:
    candidates = [
        _candidate(1, kickoff="2026-01-01T20:00:00", match_status="scheduled"),
        CandidateMatch(
            match_id=2,
            result_id=None,
            kickoff_at=datetime(2026, 1, 2, 20),
            home_team_id=10,
            away_team_id=20,
            home_goals=1,
            away_goals=0,
            match_status="settled",
            official_publish_time=None,
        ),
        _candidate(3, kickoff="2026-01-03T20:00:00", home_goals=None),
        _candidate(4, kickoff="2026-01-04T20:00:00", home_team_id=None),
        _candidate(5, kickoff="2026-01-05T20:00:00"),
    ]

    dataset = build_training_dataset(candidates, min_matches=2)

    assert [(entry.match_id, entry.reason) for entry in dataset.manifest.excluded] == [
        (1, "match_not_settled"),
        (2, "result_missing"),
        (3, "official_score_missing"),
        (4, "team_unmapped"),
        (5, "team_below_minimum_history"),
    ]
    assert dataset.samples == ()


def test_ambiguous_team_candidates_remain_auditable_with_other_exclusion_reason() -> None:
    candidate = CandidateMatch(
        match_id=6,
        result_id=None,
        kickoff_at=datetime(2026, 1, 6, 20),
        home_team_id=None,
        away_team_id=20,
        home_goals=None,
        away_goals=None,
        match_status="settled",
        official_publish_time=None,
        home_team_candidate_ids=(10, 11),
        away_team_candidate_ids=(20,),
    )

    dataset = build_training_dataset([candidate], min_matches=1)

    assert [(entry.match_id, entry.reason) for entry in dataset.manifest.excluded] == [
        (6, "result_missing;team_identity_ambiguous:home=[10,11]")
    ]


def test_maher_fit_uses_the_materialized_rows_recorded_in_its_manifest() -> None:
    candidates = [
        _candidate(
            match_id,
            kickoff=f"2026-01-{match_id:02d}T20:00:00",
            home_goals=match_id % 3,
            away_goals=(match_id + 1) % 3,
        )
        for match_id in range(1, 11)
    ]
    dataset = build_training_dataset(candidates, min_matches=1)
    optimizer_result = MagicMock(
        success=True,
        x=np.zeros(6),
        fun=10.0,
        jac=np.zeros(6),
        nit=1,
        message="ok",
    )

    with (
        patch("scripts.mle_trainer._load_training_dataset", return_value=dataset),
        patch("scipy.optimize.minimize", return_value=optimizer_result) as minimize,
    ):
        result = fit_maher_poisson(MagicMock())

    fit_args = minimize.call_args.kwargs["args"]
    fit_team_ids, home_idx, away_idx, home_goals, away_goals, _ = fit_args
    fitted_rows = [
        (fit_team_ids[home], fit_team_ids[away], home_score, away_score)
        for home, away, home_score, away_score in zip(
            home_idx,
            away_idx,
            home_goals,
            away_goals,
            strict=True,
        )
    ]
    manifest_rows = [
        (
            dataset.samples[index].home_team_id,
            dataset.samples[index].away_team_id,
            dataset.samples[index].home_goals,
            dataset.samples[index].away_goals,
        )
        for index in range(len(dataset.samples))
    ]
    assert fitted_rows == manifest_rows
    assert result["training_manifest"]["sha256"] == dataset.manifest.sha256
