from datetime import datetime

from scripts.features.populate_teams_leagues import (
    _competition_code,
    _infer_country,
    _upsert_competition_season,
)


def test_infer_country_covers_current_official_leagues():
    assert _infer_country("Brann", "挪威超级联赛") == "Norway"
    assert _infer_country("HJK", "芬兰超级联赛") == "Finland"
    assert _infer_country("울산", "韩国职业联赛") == "South Korea"
    assert _infer_country("阿根廷", "世界杯") == "Argentina"


def test_competition_code_is_stable_and_namespaced():
    code = _competition_code("巴西甲级联赛")

    assert code.startswith("sporttery:")
    assert code == _competition_code("巴西甲级联赛")
    assert code != _competition_code("美国职业大联盟")


def test_upsert_competition_season_reuses_known_competition(mock_conn):
    _conn, cur = mock_conn
    cur.fetchone.side_effect = [(7,), (9,), (11,)]

    created = _upsert_competition_season(
        cur,
        league_name="瑞典超级联赛",
        kickoff_time=datetime(2026, 7, 16, 19, 0),
    )

    assert created == {"competitions_created": 0, "competition_seasons_created": 1}
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert any("FROM competitions" in sql for sql in sql_calls)
    assert any("FROM seasons" in sql for sql in sql_calls)
    assert any("INSERT INTO competition_seasons" in sql for sql in sql_calls)
