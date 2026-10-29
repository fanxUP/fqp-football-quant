import sqlite3

from scripts.sources.titan007 import derive


def test_derive_injuries_and_suspensions(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE analysis_sections SET payload=? WHERE match_id=1 AND section='injuries'",
        (
            '[{"team_name":"主队","team_id":100,"number":"9","position":"前锋",'
            '"player_name":"甲","reason":"十字韧带损伤"},'
            '{"team_name":"主队","team_id":100,"number":"5","position":"后卫",'
            '"player_name":"乙","reason":"累计黄牌停赛"}]',
        ),
    )
    conn.commit()
    n = derive.derive_injuries(conn)
    assert n == 2
    kinds = {r["player_name"]: r["kind"] for r in conn.execute("SELECT * FROM match_injuries")}
    assert kinds == {"甲": "injury", "乙": "suspension"}


def test_derive_appearance_minutes(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO lineups (match_id,side,player_name,player_id,number,position,starter)"
        " VALUES (1,'home','替补甲',1002,'10','中场',0)"
    )
    conn.execute(
        "INSERT INTO events (match_id,seq,minute,side,event_type,player_name,assist_name)"
        " VALUES (1,99,'60','home','换人','替补甲','主队前锋')"
    )
    conn.commit()
    derive.derive_appearances(conn)
    rows = {
        r["player_name"]: r["minutes"]
        for r in conn.execute("SELECT * FROM player_appearances WHERE match_id=1")
    }
    assert rows["主队前锋"] == 60
    assert rows["替补甲"] == 30


def test_player_directory_separates_squad_and_lineup_ids(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # 同名同队：阵容行并入比赛阵容ID；不同名：进入偏移区
    conn.execute(
        "INSERT INTO team_squad (team_id, player_id, name, position, nationality)"
        " VALUES (100, 7001, '前锋甲', '前锋', '中国')"
    )
    conn.execute(
        "INSERT INTO team_squad (team_id, player_id, name, position)"
        " VALUES (100, 7002, '替补乙', '中场')"
    )
    conn.execute(
        "INSERT INTO lineups (match_id, side, player_name, player_id, number, position, starter)"
        " VALUES (1,'home','前锋甲',9001,'9','前锋',1)"
    )
    conn.commit()

    derive.refresh_player_directory(conn)

    rows = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM player_directory")}
    assert rows[9001]["source"] == "lineup" and rows[9001]["squad_id"] == 7001
    assert derive.SQUAD_ID_OFFSET + 7002 in rows
    squad_row = rows[derive.SQUAD_ID_OFFSET + 7002]
    assert squad_row["source"] == "squad" and squad_row["squad_id"] == 7002


def test_player_directory_keeps_squad_details_on_merged_row(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO team_squad (team_id, player_id, name, birth, position)"
        " VALUES (100, 7001, '前锋甲', '1999-01-01', '前锋')"
    )
    conn.execute(
        "INSERT INTO lineups (match_id, side, player_name, player_id, number, position, starter)"
        " VALUES (1,'home','前锋甲',9001,'9','前锋',1)"
    )
    conn.commit()

    derive.refresh_player_directory(conn)

    row = conn.execute("SELECT * FROM player_directory WHERE player_id=9001").fetchone()
    assert row["birth"] == "1999-01-01"


def test_player_directory_counts_appearances(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO lineups (match_id, side, player_name, player_id, number, position, starter)"
        " VALUES (2,'home','主队前锋',1001,'9','前锋',1)"
    )
    conn.commit()

    derive.refresh_player_directory(conn)

    row = conn.execute("SELECT appearances FROM player_directory WHERE player_id=1001").fetchone()
    assert row["appearances"] == 2
