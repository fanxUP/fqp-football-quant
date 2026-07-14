from datetime import datetime

from scripts.jobs.run_feature_snapshot_build import (
    _resolve_competition_season_id,
    can_build_team_dependent_features,
)


def test_team_enrichment_requires_both_internal_team_ids():
    assert can_build_team_dependent_features(1, 2) is True
    assert can_build_team_dependent_features(None, 2) is False
    assert can_build_team_dependent_features(1, None) is False
    assert can_build_team_dependent_features(None, None) is False


def test_competition_season_resolution_uses_league_and_kickoff_date(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (5,)

    season_id = _resolve_competition_season_id(
        conn, "瑞典超级联赛", datetime(2026, 7, 14, 1, 0)
    )

    assert season_id == 5
    params = cur.execute.call_args.args[1]
    assert params["league_name"] == "瑞典超级联赛"
    assert params["kickoff_date"].isoformat() == "2026-07-14"
