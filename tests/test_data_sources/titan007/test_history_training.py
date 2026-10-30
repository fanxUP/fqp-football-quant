"""Historical labels keep their source identity and conservative availability."""

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from scripts.football_history_training import (
    build_history_training_manifest,
    load_history_training_manifest,
    verify_history_training_manifest,
)

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


def row(mid=1, **changes):
    return {
        "batch_id": 1,
        "source_match_id": mid,
        "source_competition_id": 36,
        "source_season": None,
        "kickoff_at": datetime(2026, 8, mid, tzinfo=UTC),
        "match_status": "finished",
        "source_home_team_id": 100,
        "source_away_team_id": 200,
        "home_team_id": 10,
        "away_team_id": 20,
        "official_match_id": None,
        "home_goals": 0,
        "away_goals": 1,
        "source_metadata": {"score_scope": "source_reported_full_match"},
        **changes,
    }


def build(rows, **changes):
    return build_history_training_manifest(BATCH, rows, **{**SCOPE, **changes})


def test_unknown_publication_is_kept_unknown_and_current_candidates_are_not_official_labels():
    result = build([row()])
    assert len(result["included"]) == 1
    sample = result["included"][0]
    assert sample["home_goals"] == 0
    assert sample["source_season"] is None
    assert sample["source_match_id"] == 1 and sample["official_match_id"] is None
    assert "result_id" not in sample
    assert sample["label_source"] == "football_history_matches.home_goals/away_goals"
    assert sample["label_available_by"] is None
    assert result["batch"]["imported_at"] == "2026-10-29T00:00:00.000000+00:00"
    assert sample["source_published_at"] is None
    assert result["usage"]["production_ready"] is False
    assert result["usage"]["point_in_time_replay_verified"] is False
    assert result["usage"]["spf_regulation_score_verified"] is False
    assert result["summary"]["source_season_unknown"] == 1
    verify_history_training_manifest(result)


def test_canonical_hash_is_stable_but_covers_labels_batch_scope_and_restrictions():
    original = build([row(2), row(1)])
    assert original == build([row(1), row(2)])
    assert [r["source_match_id"] for r in original["included"]] == [1, 2]
    assert original["sha256"] != build([row(1), row(2, home_goals=2)])["sha256"]
    assert original["sha256"] != build([row(1), row(2)], season="different")["sha256"]
    for key in ("included", "batch", "usage"):
        changed = deepcopy(original)
        if key == "included":
            changed[key][0]["home_goals"] = 9
        elif key == "batch":
            changed[key]["content_sha256"] = "b" * 64
        else:
            changed[key]["production_ready"] = True
        with pytest.raises(ValueError, match="SHA-256"):
            verify_history_training_manifest(changed)


@pytest.mark.parametrize("as_of", ["2024-01-01T00:00:00Z", "2026-10-28T23:59:59Z"])
def test_batch_cannot_be_replayed_before_actual_import(as_of):
    window = (
        {"window_start": "2023-07-01T00:00:00Z", "window_end": "2024-07-01T00:00:00Z"}
        if as_of.startswith("2024")
        else {}
    )
    with pytest.raises(ValueError, match="not available"):
        build([row()], as_of=as_of, **window)


def test_time_window_is_half_open_and_future_rows_do_not_change_manifest():
    baseline = build([row()])
    outside = [
        row(2, kickoff_at=datetime(2026, 6, 30, 15, 59, tzinfo=UTC)),
        row(3, kickoff_at=datetime(2027, 6, 30, 16, tzinfo=UTC)),
        row(4, kickoff_at=datetime(2026, 10, 29, 16, tzinfo=UTC)),
    ]
    assert build([row(), *outside]) == baseline
    at_start = row(kickoff_at=datetime(2026, 6, 30, 16, tzinfo=UTC))
    assert len(build([at_start])["included"]) == 1


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"match_status": "scheduled"}, "match_not_finished"),
        ({"home_goals": None}, "score_invalid"),
        ({"home_goals": -1}, "score_invalid"),
        ({"home_goals": True}, "score_invalid"),
        ({"away_goals": 1.5}, "score_invalid"),
        ({"home_team_id": None}, "team_unmapped"),
        ({"home_team_id": 20}, "same_canonical_team"),
        ({"source_season": "2025-2026"}, "source_season_conflict"),
        ({"source_metadata": {}}, "score_scope_unknown"),
        (
            {"source_metadata": {"score_scope": "source_reported_full_match", "home_extra": 0}},
            "extra_time_or_penalties_reported",
        ),
        (
            {"source_metadata": {"score_scope": "source_reported_full_match", "away_penalties": 0}},
            "extra_time_or_penalties_reported",
        ),
        ({"kickoff_at": datetime(2026, 10, 29, 1, tzinfo=UTC)}, "finished_after_batch_import"),
    ],
)
def test_bad_labels_and_uncertain_identity_have_explicit_exclusion(changes, reason):
    result = build([row(**changes)])
    assert not result["included"]
    assert result["excluded"][0]["reason"] == reason
    assert result["summary"]["excluded_by_reason"] == {reason: 1}


@pytest.mark.parametrize("official", [None, 1000])
def test_duplicate_event_identity_is_excluded_instead_of_double_counted(official):
    result = build(
        [
            row(1, official_match_id=official),
            row(2, kickoff_at=row()["kickoff_at"], official_match_id=official),
        ]
    )
    assert not result["included"]
    assert {r["reason"] for r in result["excluded"]} == {"duplicate_match_identity"}


def test_different_source_matches_linked_to_same_official_match_are_ambiguous():
    result = build([row(1, official_match_id=100), row(2, official_match_id=100)])
    assert not result["included"]
    assert result["summary"]["excluded_by_reason"] == {"duplicate_match_identity": 2}


def test_minimum_history_is_rechecked_after_removing_sparse_opponents():
    # A chain A-B-C-D has two interior teams initially meeting the threshold.
    # Removing endpoints requires a second pass to remove the middle edge.
    result = build(
        [
            row(1),
            row(2, home_team_id=20, away_team_id=30),
            row(3, home_team_id=30, away_team_id=40),
        ],
        min_team_matches=2,
    )
    assert not result["included"]
    assert result["summary"]["excluded_by_reason"] == {"team_below_minimum_history": 3}
    assert build([row(1), row(2)], min_team_matches=2)["summary"]["team_match_counts"] == {
        "10": 2,
        "20": 2,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"competition_id": True},
        {"competition_id": 0},
        {"season": ""},
        {"window_start": "2026-01-01"},
        {"window_end": "2026-07-01T00:00:00+08:00"},
        {"window_end": "2028-07-01T00:00:00+08:00"},
        {"as_of": "2026-10-30"},
        {"min_team_matches": 0},
        {"max_matches": 5001},
        {"max_matches": True},
    ],
)
def test_scope_requires_explicit_aware_bounded_values(changes):
    with pytest.raises(ValueError):
        build([row()], **changes)


@pytest.mark.parametrize(
    "changes", [{"state": "building"}, {"source_name": "other"}, {"content_sha256": "invalid"}]
)
def test_unpublished_or_unverified_source_batch_is_rejected(changes):
    with pytest.raises(ValueError):
        build_history_training_manifest({**BATCH, **changes}, [row()], **SCOPE)


def test_row_cap_is_a_failure_not_a_silent_partial_training_set():
    with pytest.raises(ValueError, match="exceeds"):
        build([row(1), row(2)], max_matches=1)


def test_loader_does_not_rollback_or_hijack_callers_existing_transaction():
    conn = MagicMock()
    conn.get_transaction_status.return_value = 2
    with pytest.raises(ValueError, match="idle"):
        load_history_training_manifest(conn, batch_id=1, **SCOPE)
    conn.cursor.assert_not_called()
    conn.rollback.assert_not_called()


def test_conflicting_duplicate_is_not_hidden_by_an_invalid_score():
    result = build([row(1), row(2, kickoff_at=row()["kickoff_at"], home_goals=None)])
    assert not result["included"]
    assert result["summary"]["excluded_by_reason"] == {"duplicate_match_identity": 2}


def test_other_competitions_do_not_drift_cohort_and_legacy_timestamps_are_not_publication():
    original = row()
    original["source_metadata"].update(
        published_at="2024-01-01",
        source_acquired_at="2024-01-01",
        source_first_fetched_text="2024-01-01",
        source_updated_text="2024-01-01",
    )
    result = build([original, row(2, source_competition_id=37)])
    assert result == build([row()])


def test_equivalent_timezones_have_same_hash():
    assert build([row()]) == build([row()], as_of="2026-10-29T16:00:00Z")


def test_mixed_batches_cannot_be_hidden_outside_window():
    with pytest.raises(ValueError, match="Mixed"):
        build([row(batch_id=2)])


def test_autocommit_connection_is_rejected_before_any_query():
    conn = MagicMock()
    conn.get_transaction_status.return_value = 0
    conn.autocommit = True
    with pytest.raises(ValueError, match="autocommit"):
        load_history_training_manifest(conn, batch_id=1, **SCOPE)
    conn.cursor.assert_not_called()
    conn.rollback.assert_not_called()
