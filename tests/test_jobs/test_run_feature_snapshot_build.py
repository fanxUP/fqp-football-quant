from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.jobs.run_feature_snapshot_build import (
    _business_now_naive,
    _load_collected_weather,
    _resolve_competition_season_id,
    _snapshot_job_result,
    can_build_team_dependent_features,
    compute_full_completeness,
)


def test_feature_snapshot_reuses_collected_weather_without_external_fetch(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (
        22550,
        50,
        datetime(2026, 7, 18, 15, 0),
        datetime(2026, 7, 19, 0, 0),
        14.33,
        0.0,
        21.0,
        18.5,
        -0.0185,
        "open-meteo",
        0.85,
    )

    weather, has_weather = _load_collected_weather(conn, 22550)

    assert has_weather is True
    assert weather["temperature_2m"] == 14.33
    assert weather["goal_expectation_weather_adjustment"] == -0.0185


def test_team_enrichment_requires_both_internal_team_ids():
    assert can_build_team_dependent_features(1, 2) is True
    assert can_build_team_dependent_features(None, 2) is False
    assert can_build_team_dependent_features(1, None) is False
    assert can_build_team_dependent_features(None, None) is False


def test_competition_season_resolution_uses_league_and_kickoff_date(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (5,)

    season_id = _resolve_competition_season_id(conn, "瑞典超级联赛", datetime(2026, 7, 14, 1, 0))

    assert season_id == 5
    params = cur.execute.call_args.args[1]
    assert params["league_name"] == "瑞典超级联赛"
    assert params["kickoff_date"].isoformat() == "2026-07-14"


def test_snapshot_job_reports_failure_when_every_match_write_fails():
    result = _snapshot_job_result(
        feature_version="v2_enriched",
        matches_processed=3,
        snapshots_built=0,
        profiles_updated=0,
        completeness_total=0,
        dim_stats={},
        failed_matches=[
            {"match_id": 1, "error": "missing column"},
            {"match_id": 2, "error": "missing column"},
            {"match_id": 3, "error": "missing column"},
        ],
    )

    assert result["status"] == "failed"
    assert result["failed_count"] == 3
    assert result["failed_matches"][0]["match_id"] == 1


def test_snapshot_job_reports_degraded_quality_without_hiding_successful_writes():
    result = _snapshot_job_result(
        feature_version="v2_enriched",
        matches_processed=4,
        snapshots_built=4,
        profiles_updated=0,
        completeness_total=130,
        dim_stats={"odds": 4, "team_mapping": 4, "injury": 1},
        failed_matches=[],
    )

    assert result["status"] == "ok"
    assert result["quality_status"] == "degraded"
    assert result["dimension_rates"]["odds"] == 1.0
    assert result["dimension_rates"]["injury"] == 0.25
    assert result["dimension_rates"]["weather"] == 0.0
    assert result["average_completeness"] == 32.5


def test_snapshot_job_average_uses_real_match_scores_not_partial_entity_coverage():
    result = _snapshot_job_result(
        feature_version="v2_enriched",
        matches_processed=2,
        snapshots_built=2,
        profiles_updated=3,
        completeness_total=80,
        dim_stats={"odds": 2, "team_mapping": 2, "team_profile": 1.5},
        failed_matches=[],
    )

    assert result["dimensions_coverage"]["team_profile"] == "1.5/2"
    assert result["average_completeness"] == 40.0


def test_completeness_only_counts_real_usable_dimensions():
    result = compute_full_completeness(
        {
            "odds": True,
            "team_mapping": True,
            "injury": False,
            "motivation": False,
        }
    )

    assert result["data_completeness_score"] == 30.0
    assert result["source_confidence_score"] == 0.285
    assert "injury" in result["missing_dimensions"]
    assert "motivation" in result["missing_dimensions"]


def test_core_official_evidence_reaches_quality_gate_without_optional_enrichment():
    result = compute_full_completeness(
        {
            "odds": True,
            "team_mapping": True,
            "team_profile": True,
        }
    )

    assert result["data_completeness_score"] == 50.0


def test_feature_snapshot_clock_uses_shanghai_business_time(monkeypatch):
    monkeypatch.setenv("FQP_TIMEZONE", "Asia/Shanghai")

    now = _business_now_naive()

    assert now.tzinfo is None
    expected = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    assert abs((now - expected).total_seconds()) < 2
