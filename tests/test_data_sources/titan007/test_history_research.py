"""Published season evidence and real official identities precede offline fitting."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scripts.football_history_research import (
    build_history_official_dataset,
    fit_history_official_research,
    load_history_official_inputs,
)
from scripts.football_history_training import build_history_training_manifest

BATCH = {
    "id": 1,
    "source_name": "titan007",
    "state": "published",
    "content_sha256": "a" * 64,
    "normalization_version": "titan007-history/v1",
    "imported_at": datetime(2026, 10, 29, tzinfo=UTC),
}
SCOPE = {
    "competition_id": 36,
    "season": "2026-2027",
    "window_start": "2026-07-01T00:00:00+08:00",
    "window_end": "2027-07-01T00:00:00+08:00",
    "as_of": "2026-10-30T00:00:00+08:00",
    "min_team_matches": 1,
}


def match(mid=1, **changes):
    return {
        "batch_id": 1,
        "source_match_id": mid,
        "source_competition_id": 36,
        "source_season": "2026",
        "kickoff_at": datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=mid),
        "match_status": "finished",
        "source_home_team_id": 100,
        "source_away_team_id": 200,
        "home_team_id": 10,
        "away_team_id": 20,
        "official_match_id": mid + 1000,
        "home_goals": 0,
        "away_goals": 1,
        "source_metadata": {"score_scope": "source_reported_full_match"},
        **changes,
    }


def reference(rows):
    return {
        "batch": {
            "id": 2,
            "source_name": "titan007",
            "state": "published",
            "source_competition_id": "36",
            "source_season": "2026-2027",
            "content_sha256": "b" * 64,
            "imported_at": BATCH["imported_at"],
        },
        "fixtures": [
            {
                "batch_id": 2,
                "source_match_id": str(r["source_match_id"]),
                "home_team_id": r["home_team_id"],
                "away_team_id": r["away_team_id"],
                "kickoff": r["kickoff_at"],
            }
            for r in rows
        ],
    }


def history(rows=None, **scope):
    rows = rows if rows is not None else [match()]
    return build_history_training_manifest(
        BATCH, rows, season_reference=reference(rows), **{**SCOPE, **scope}
    )


def official(mid=1, **changes):
    r = match(mid)
    return {
        "source_match_id": mid,
        "match_id": r["official_match_id"],
        "result_match_id": r["official_match_id"],
        "result_id": mid + 2000,
        "kickoff_at": r["kickoff_at"].replace(tzinfo=None) + timedelta(hours=8),
        "match_status": "Settled",
        "home_team_id": 10,
        "away_team_id": 20,
        "home_team_candidate_ids": [10],
        "away_team_candidate_ids": [20],
        "home_goals": 0,
        "away_goals": 1,
        "official_publish_time": None,
        **changes,
    }


def test_exact_reference_resolves_membership_without_overwriting_source_season():
    result = history()
    sample = result["included"][0]
    assert sample["source_season"] == "2026"
    assert sample["study_season"] == "2026-2027"
    assert sample["season_reference"]["batch_id"] == 2
    assert sample["season_reference"]["content_sha256"] == "b" * 64
    assert sample["label_available_by"] is None
    assert result["usage"]["spf_regulation_score_verified"] is False


@pytest.mark.parametrize(
    "change",
    [{"home_team_id": 30}, {"away_team_id": 10}, {"kickoff": "2026-08-02T00:01:00Z"}],
)
def test_season_evidence_must_match_exact_fixture_identity(change):
    r = match()
    evidence = reference([r])
    evidence["fixtures"][0].update(change)
    result = build_history_training_manifest(BATCH, [r], season_reference=evidence, **SCOPE)
    assert not result["included"]
    assert result["excluded"][0]["reason"] == "season_reference_identity_conflict"


@pytest.mark.parametrize(
    "change",
    [
        {"state": "building"},
        {"source_season": "2025-2026"},
        {"source_competition_id": "37"},
        {"imported_at": datetime(2026, 11, 1, tzinfo=UTC)},
    ],
)
def test_unpublished_wrong_or_future_season_reference_is_rejected(change):
    evidence = reference([match()])
    evidence["batch"].update(change)
    with pytest.raises(ValueError, match="season reference"):
        build_history_training_manifest(BATCH, [match()], season_reference=evidence, **SCOPE)


def test_season_is_not_a_global_year_alias_and_evidence_is_hash_covered():
    r = match()
    without = build_history_training_manifest(BATCH, [r], **SCOPE)
    assert without["excluded"][0]["reason"] == "source_season_conflict"
    evidence = reference([r])
    evidence["fixtures"] = []
    missing = build_history_training_manifest(BATCH, [r], season_reference=evidence, **SCOPE)
    assert missing["excluded"][0]["reason"] == "season_reference_missing"
    evidence = reference([r])
    evidence["batch"]["content_sha256"] = "c" * 64
    changed = build_history_training_manifest(BATCH, [r], season_reference=evidence, **SCOPE)
    assert changed["sha256"] != history()["sha256"]


def test_adapter_preserves_real_official_ids_labels_and_unknown_publication():
    dataset, review = build_history_official_dataset(history(), [official()])
    sample = dataset.samples[0]
    assert (sample.match_id, sample.result_id) == (1001, 2001)
    assert sample.label_source == "official_results.full_home_goals/full_away_goals"
    assert sample.kickoff_time == "2026-08-02T08:00:00.000000"
    assert sample.official_publish_time is None
    assert dataset.manifest.cutoff_at is None
    assert review["included"][0]["source_match_id"] == 1
    assert review["included"][0]["official_result_id"] == 2001


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"match_id": 999}, "official_identity_mismatch"),
        ({"result_match_id": 999}, "official_identity_mismatch"),
        ({"result_id": None}, "official_result_missing"),
        ({"home_team_id": 30}, "official_identity_mismatch"),
        ({"home_team_candidate_ids": [10, 30]}, "official_identity_mismatch"),
        ({"kickoff_at": datetime(2026, 8, 2)}, "official_identity_mismatch"),
        ({"home_goals": 1}, "official_score_conflict"),
        ({"home_goals": True}, "official_score_invalid"),
        ({"match_status": "Scheduled"}, "official_not_settled"),
        ({"official_publish_time": datetime(2026, 11, 1)}, "official_label_after_review"),
    ],
)
def test_uncorroborated_or_conflicting_labels_do_not_reach_fitter(changes, reason):
    dataset, review = build_history_official_dataset(history(), [official(**changes)])
    assert not dataset.samples
    assert review["excluded"][0]["reason"] == reason


def test_missing_official_link_is_not_fabricated_and_duplicate_evidence_is_rejected():
    dataset, review = build_history_official_dataset(history([match(official_match_id=None)]), [])
    assert not dataset.samples
    assert review["excluded"][0]["reason"] == "official_link_missing"
    with pytest.raises(ValueError, match="unique"):
        build_history_official_dataset(history(), [official(), official()])


def test_candidate_hash_is_verified_before_adaptation():
    tampered = deepcopy(history())
    tampered["included"][0]["home_goals"] = 9
    with pytest.raises(ValueError, match="SHA-256"):
        build_history_official_dataset(tampered, [official()])


def test_final_official_subset_rechecks_minimum_team_history():
    rows = [match(1), match(2)]
    dataset, review = build_history_official_dataset(
        history(rows, min_team_matches=2), [official(1)]
    )
    assert not dataset.samples
    assert {r["reason"] for r in review["excluded"]} == {
        "official_result_missing",
        "team_below_minimum_history",
    }


def test_real_offline_fit_reuses_existing_fitter_and_keeps_research_restrictions():
    rows = [match(i) for i in range(1, 13)]
    result = fit_history_official_research(history(rows), [official(i) for i in range(1, 13)])
    assert result["fit"]["n_matches"] == 12
    assert result["fit"]["converged"] is True
    assert result["usage"]["production_ready"] is False
    assert result["usage"]["point_in_time_replay_verified"] is False
    assert result["usage"]["source_only_labels_supported"] is False
    assert "_artifact_identity" not in result["fit"]
    assert result["training_manifest"]["included"][0]["result_id"] == 2001
    assert result["summary"]["official_publication_unknown"] == 12
    assert result["source_fingerprints"]["scripts/mle_trainer.py"]


def test_insufficient_data_is_reported_as_unfitted_instead_of_completed():
    result = fit_history_official_research(history(), [official()])
    assert result["summary"]["eligible_matches"] == 1
    assert result["summary"]["fitted_matches"] == 0
    assert result["fit_status"] == "insufficient_data"


def test_loader_does_not_take_over_autocommit_or_active_transaction():
    for transaction, autocommit in [(2, False), (0, True)]:
        conn = MagicMock()
        conn.get_transaction_status.return_value = transaction
        conn.autocommit = autocommit
        with pytest.raises(ValueError):
            load_history_official_inputs(conn, batch_id=1, reference_batch_id=2, **SCOPE)
        conn.cursor.assert_not_called()
        conn.rollback.assert_not_called()
