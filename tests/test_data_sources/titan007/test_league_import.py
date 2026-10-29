"""Source-to-shared-data contracts using a tiny local SQLite fixture."""

import sqlite3

import pytest

from scripts.titan007_import import load_season


def source_cache(path):
    path.mkdir(exist_ok=True)
    with sqlite3.connect(path / "titan007.db") as conn:
        conn.executescript("""
            CREATE TABLE league_info(league_id,season,name,last_update);
            CREATE TABLE league_teams(league_id,team_id,name,name_en);
            CREATE TABLE league_results(match_id,league_id,season,round,status,match_time,
                home_id,away_id,home_score,away_score);
            CREATE TABLE league_standings(league_id,season,scope,team_id,rank,played,
                win,draw,loss,goals_for,goals_against,goal_diff,points);
            INSERT INTO league_info VALUES(36,'2026-2027','英格兰超级联赛','2026-10-29 10:00:00');
            INSERT INTO league_teams VALUES(36,19,'阿森纳','Arsenal'),(36,24,'切尔西','Chelsea');
            INSERT INTO league_results VALUES
                (101,36,'2026-2027',1,-1,'2026-10-20 20:00',19,24,0,0),
                (102,36,'2026-2027',2,0,'2026-11-20 20:00',24,19,NULL,NULL);
            INSERT INTO league_standings VALUES
                (36,'2026-2027','total',19,1,1,0,1,0,0,0,0,-2),
                (36,'2026-2027','total',24,2,1,0,1,0,0,0,0,1);
        """)
    return path


@pytest.fixture
def cache(tmp_path):
    return source_cache(tmp_path / "cache")


@pytest.fixture
def config():
    return {
        "source_league_id": 36,
        "competition_code": "premier-league",
        "competition_aliases": ["apifootball:39"],
        "competition_name": "英超",
        "country": "英格兰",
        "season": "2026-2027",
        "season_code": "premier-league:2026-2027",
        "season_aliases": ["apifootball:39:2026"],
        "start_date": "2026-07-01",
        "end_date": "2027-06-30",
        "is_current": True,
        "expected_teams": 2,
        "expected_fixtures": 2,
        "total_rounds": 2,
    }


def test_reads_selected_season_and_preserves_zero_unknown_and_deduction(cache, config):
    data = load_season(cache, config=config)
    assert len(data["fixtures"]) == 2
    assert len(data["teams"]) == 2
    assert data["fixtures"][0]["homeGoals"] == 0
    assert data["fixtures"][1]["homeGoals"] is None
    assert data["standings"]["all"][0]["points"] == -2
    assert data["source_as_of"] == "2026-10-29T02:00:00+00:00"
    assert data["source_acquired_at"] is None
    assert data["fixtures"][0]["kickoff"] == "2026-10-20T12:00:00+00:00"
    assert data["report"]["scope_complete"] == {"all": True}


def test_hash_is_stable_and_changes_on_source_correction(cache, config):
    before = load_season(cache, config=config)
    assert load_season(cache, config=config)["content_sha256"] == before["content_sha256"]
    with sqlite3.connect(cache / "titan007.db") as conn:
        conn.execute("UPDATE league_results SET home_score=1 WHERE match_id=101")
    after = load_season(cache, config=config)
    assert after["content_sha256"] != before["content_sha256"]


def test_uses_season_roster_instead_of_all_time_league_team_directory(cache, config):
    with sqlite3.connect(cache / "titan007.db") as conn:
        conn.execute("INSERT INTO league_teams VALUES(36,52,'过去参赛队','Old Team')")
    assert [team["source_id"] for team in load_season(cache, config=config)["teams"]] == [19, 24]


def test_missing_time_is_unknown_and_partial_table_never_becomes_full_ranking(cache, config):
    with sqlite3.connect(cache / "titan007.db") as conn:
        conn.execute("DELETE FROM league_standings WHERE team_id=24")
        conn.execute("UPDATE league_results SET match_time='时间待定' WHERE match_id=102")
        conn.execute("UPDATE league_info SET last_update=NULL")
    data = load_season(cache, config=config)
    assert data["fixtures"][1]["kickoff"] is None
    assert data["source_as_of"] is None
    assert data["report"]["scope_complete"]["all"] is False
    assert data["report"]["fixture_coverage_complete"] is False


def test_unmatched_or_invalid_fixture_is_quarantined_and_not_counted_as_valid(cache, config):
    with sqlite3.connect(cache / "titan007.db") as conn:
        conn.execute("UPDATE league_results SET away_id=999 WHERE match_id=102")
        conn.execute("UPDATE league_results SET home_score=-1 WHERE match_id=101")
    data = load_season(cache, config=config)
    assert data["fixtures"] == []
    assert len(data["report"]["rejected_fixtures"]) == 2
    assert data["report"]["fixture_coverage_complete"] is False


def test_missing_cache_is_not_created_and_wrong_season_cannot_fall_back(tmp_path, cache, config):
    with pytest.raises(FileNotFoundError):
        load_season(tmp_path / "missing", config=config)
    with pytest.raises(ValueError, match="赛季"):
        load_season(cache, config=dict(config, season="2025-2026"))
    assert not (tmp_path / "missing").exists()


def test_conflicting_ids_for_same_season_pair_are_quarantined_together(cache, config):
    with sqlite3.connect(cache / "titan007.db") as conn:
        conn.execute(
            "INSERT INTO league_results SELECT 103,league_id,season,round,status,match_time,home_id,away_id,home_score,away_score FROM league_results WHERE match_id=101"
        )
    data = load_season(cache, config=config)
    assert [row["source_id"] for row in data["fixtures"]] == ["102"]
    assert len(data["report"]["rejected_fixtures"]) == 2
    assert data["report"]["fixture_coverage_complete"] is False
