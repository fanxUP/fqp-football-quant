from unittest.mock import MagicMock, patch

import pytest

from scripts.jobs.collect_injury_data import (
    _extract_injury_fields,
    _extract_injury_observation_metadata,
)


def test_extracts_current_fixture_injury_fields_from_player_payload():
    status, injury_type, reason = _extract_injury_fields(
        {
            "player": {
                "type": "Missing Fixture",
                "reason": "Back Bruise",
            }
        }
    )

    assert status == "injured"
    assert injury_type == "Missing Fixture"
    assert reason == "Back Bruise"


def test_marks_suspension_as_suspended():
    status, injury_type, reason = _extract_injury_fields(
        {"player": {"type": "Suspended", "reason": "Red Card"}}
    )

    assert status == "suspended"
    assert injury_type == "Suspended"
    assert reason == "Red Card"


@pytest.mark.parametrize(
    ("source_type", "reason", "expected"),
    [
        ("Missing Fixture", "Suspended 3 matches", "suspended"),
        ("Missing Fixture", "Knee Injury", "injured"),
        ("Missing Fixture", "Personal Reasons", "unknown"),
        ("Missing Fixture", "Unknown", "unknown"),
        ("Questionable", "Suspended", "doubtful"),
    ],
)
def test_classifies_actual_api_football_injury_payload(source_type, reason, expected):
    status, _, _ = _extract_injury_fields({"player": {"type": source_type, "reason": reason}})

    assert status == expected


@pytest.mark.parametrize(
    ("source_type", "reason", "expected"),
    [
        ("Questionable", "Fitness test", "doubtful"),
        ("Doubtful", "Knee", "doubtful"),
        ("Returned", "Recovered", "returned"),
        ("Returned", "Doubtful before", "returned"),
        ("Available", "", "returned"),
        ("Uninjured", "", "unknown"),
        ("Not injured", "", "unknown"),
        ("Unknown", "Questionable", "unknown"),
        ("medical review", "", "unknown"),
        ("", "", "unknown"),
    ],
)
def test_maps_only_recognized_availability_values(source_type, reason, expected):
    status, _, _ = _extract_injury_fields({"player": {"type": source_type, "reason": reason}})

    assert status == expected


def test_preserves_explicit_source_timestamps_and_expected_return_date():
    metadata = _extract_injury_observation_metadata(
        {
            "effective_at": "2026-11-08T13:00:00+01:00",
            "published_at": "2026-11-09T08:30:00Z",
            "player": {
                "type": "Doubtful",
                "reason": "Ankle",
                "expected_return_date": "2026-11-15",
            },
        }
    )

    assert metadata == {
        "availability_status": "doubtful",
        "injury_type": "Doubtful",
        "reason": "Ankle",
        "effective_at": "2026-11-08T12:00:00+00:00",
        "published_at": "2026-11-09T08:30:00+00:00",
        "expected_return_date": "2026-11-15",
    }


def test_preserves_explicit_top_level_expected_return_date():
    metadata = _extract_injury_observation_metadata(
        {
            "expected_return_date": "2026-11-20",
            "player": {"type": "Missing Fixture", "reason": "Back Bruise"},
        }
    )

    assert metadata["expected_return_date"] == "2026-11-20"


def test_missing_source_times_are_not_inferred_from_update_or_fixture_time():
    metadata = _extract_injury_observation_metadata(
        {
            "updated_at": "2026-11-09T08:30:00Z",
            "fixture": {"date": "2026-11-10T20:00:00+08:00"},
            "player": {"type": "Missing Fixture", "reason": "Back Bruise"},
        }
    )

    assert metadata["effective_at"] is None
    assert metadata["published_at"] is None
    assert metadata["expected_return_date"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("published_at", "2026-11-09T08:30:00"),
        ("effective_at", "not-a-timestamp"),
        ("expected_return_date", "2026-02-30"),
    ],
)
def test_rejects_malformed_source_temporal_values(field, value):
    if field == "expected_return_date":
        payload = {"player": {"expected_return_date": value}}
    else:
        payload = {field: value, "player": {}}

    with pytest.raises(ValueError):
        _extract_injury_observation_metadata(payload)


@pytest.mark.parametrize("mode", ["recent", "empty", "quota", "discovery_failure", "dry"])
def test_injury_job_records_checked_unknowns_and_failures_without_zero_inference(monkeypatch, mode):
    from scripts.api_football_client import ApiFootballRateLimitError
    from scripts.jobs import collect_injury_data as job

    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    match = dict(id=7, home_team_id=11, away_team_id=12, competition_season_id=1)
    client = MagicMock(last_response_meta={"errors": {}}, call_count_today=0)
    client.get_fixtures.return_value = []
    if mode == "discovery_failure":
        client.get_fixtures.side_effect = RuntimeError("fixed")
    if mode == "quota":
        client.get_injuries.side_effect = ApiFootballRateLimitError("fixed")
    else:
        client.get_injuries.return_value = []
    with (
        patch.object(job, "get_db") as db,
        patch.object(job, "ApiFootballClient", return_value=client),
        patch.object(job, "load_supported_matches", return_value=[match]),
        patch.object(job, "load_api_aliases", return_value={"Home": 11, "Away": 12}),
        patch.object(job, "find_matching_fixture", return_value={"fixture": {"id": 900}}),
        patch.object(job, "has_fresh_team_checks", return_value=mode == "recent"),
        patch.object(job, "_process_fixture_injuries", return_value=0) as store,
        patch.object(job, "record_failed_player_query", return_value=True) as failed,
    ):
        conn = db.return_value.__enter__.return_value
        result = job._run_impl(dry_run=mode == "dry")
    client.close.assert_called_once()
    if mode == "recent":
        client.get_fixtures.assert_not_called()
        client.get_injuries.assert_not_called()
        store.assert_not_called()
    elif mode in {"quota", "discovery_failure"}:
        failed.assert_called_once()
        store.assert_not_called()
        assert result["quality_status"] == "degraded"
    elif mode == "empty":
        store.assert_called_once()
        assert "coverage_evidence" not in store.call_args.kwargs
        assert result["coverage_verified"] is False
    else:
        store.assert_not_called()
        conn.commit.assert_not_called()
