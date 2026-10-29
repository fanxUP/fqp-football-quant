import sqlite3

from scripts.sources.titan007 import team_sync


def test_build_catalog_uses_lottery_name(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO lottery_teams (lottery_team_id,name,full_name) VALUES (9001,'主队竞彩','主队竞彩')"
    )
    conn.execute(
        "INSERT INTO team_mapping (lottery_team_id,titan_team_id,lottery_name,titan_name,"
        " confidence,method,status) VALUES (9001,100,'主队竞彩','主队',0.99,'exact','mapped')"
    )
    conn.commit()
    stats = team_sync.build_catalog(conn)
    assert stats["teams"] == 1
    row = conn.execute("SELECT display_name FROM team_catalog WHERE titan_team_id=100").fetchone()
    assert row["display_name"] == "主队竞彩"
