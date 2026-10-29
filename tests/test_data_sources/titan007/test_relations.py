import sqlite3

from scripts.sources.titan007 import relations


def test_previous_season():
    assert relations.previous_season("2026-2027") == "2025-2026"
    assert relations.previous_season("2026") == "2025"
    assert relations.previous_season("") is None


def test_build_promotion_relation(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO leagues (league_id,name_simplified,kind) VALUES (500,'测试乙级',1)")
    conn.execute(
        "INSERT INTO league_categories (league_id,region,country,type,audience,tier,priority)"
        " VALUES (500,'欧洲','英格兰','league','men',2,'B')"
    )
    conn.execute(
        "INSERT INTO league_standings (league_id,season,scope,period,team_id,rank,played,"
        " win,draw,loss,goals_for,goals_against,goal_diff,points)"
        " VALUES (500,'2025-2026','total','total',100,1,10,8,1,1,20,5,15,25)"
    )
    conn.commit()
    relations.build_seasons(conn)
    moves = relations.build_movements(conn)
    assert moves["promotion"] >= 1
    relations.build_relations(conn)
    row = conn.execute(
        "SELECT direction, team_count FROM league_relations"
        " WHERE from_league_id=500 AND to_league_id=25"
    ).fetchone()
    assert row["direction"] == "promotion"
