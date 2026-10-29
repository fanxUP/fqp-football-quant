import sqlite3

from scripts.sources.titan007 import lottery


def test_normalize_name_keeps_audience_markers():
    assert lottery.normalize_name("阿森纳女足") != lottery.normalize_name("阿森纳")
    assert lottery.normalize_name("日本亚运男足") == lottery.normalize_name("日本")
    assert lottery.normalize_name("巴黎圣日尔曼") == "巴黎圣日尔曼"


def test_map_teams_and_link_matches(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO lottery_teams (lottery_team_id,name,full_name,league_name)"
        " VALUES (9001,'主队','主队','测试联赛')"
    )
    conn.execute(
        "INSERT INTO lottery_teams (lottery_team_id,name,full_name,league_name)"
        " VALUES (9002,'客队','客队','测试联赛')"
    )
    conn.execute(
        "INSERT INTO lottery_teams (lottery_team_id,name,full_name,league_name)"
        " VALUES (9003,'主队别名','主队别名','测试联赛')"
    )
    conn.execute("INSERT INTO team_aliases (lottery_name,titan_team_id) VALUES ('主队别名',100)")
    conn.execute(
        "INSERT INTO lottery_matches (lottery_match_id,match_date,match_num,"
        " home_team_id,home_full_name,away_team_id,away_full_name)"
        " VALUES (1,'2026-10-19','周一001',9001,'主队',9002,'客队')"
    )
    conn.commit()
    stats = lottery.map_teams(conn)
    assert stats["exact"] >= 2
    link = lottery.link_matches(conn, "2026-10-19", "2026-10-19")
    assert link["ids"] >= 1
    row = conn.execute(
        "SELECT titan_match_id FROM lottery_matches WHERE lottery_match_id=1"
    ).fetchone()
    assert row["titan_match_id"] == 1


def test_sync_lottery_odds(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    n = lottery.sync_lottery_odds(conn)
    assert n == 1
    row = conn.execute(
        "SELECT company_name, source, live_home FROM odds WHERE company_id=0 AND match_id=1"
    ).fetchone()
    assert row["company_name"] == "中国体育彩票竞彩"
    assert row["source"] == "lottery"
    assert row["live_home"] == 2.1
