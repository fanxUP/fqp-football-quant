from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np

from scripts.mle_trainer import _load_training_dataset, fit_maher_poisson
from scripts.training_manifest import CandidateMatch, build_training_dataset


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


def test_cutoff_excludes_unavailable_labels_and_future_matches_without_hash_drift() -> None:
    cutoff = datetime.fromisoformat("2026-01-05T00:00:00")
    candidates = [
        _candidate(
            1,
            kickoff="2026-01-01T20:00:00",
            published="2026-01-02T00:00:00",
        ),
        _candidate(
            2,
            kickoff="2026-01-02T20:00:00",
            published="2026-01-06T00:00:00",
        ),
        _candidate(3, kickoff="2026-01-06T20:00:00"),
    ]

    before_future_row = build_training_dataset(candidates[:2], min_matches=1, cutoff_at=cutoff)
    with_future_row = build_training_dataset(candidates, min_matches=1, cutoff_at=cutoff)

    assert [sample.match_id for sample in with_future_row.samples] == [1]
    assert [entry.reason for entry in with_future_row.manifest.excluded] == [
        "label_published_after_cutoff"
    ]
    assert before_future_row.manifest.sha256 == with_future_row.manifest.sha256


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
        )
    ]

    dataset = _load_training_dataset(conn, min_matches=1, cutoff_at=cutoff)

    query, params = cur.execute.call_args.args
    assert "WHERE m.kickoff_time < %s" in " ".join(query.split())
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
