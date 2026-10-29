import sqlite3

from scripts.sources.titan007 import store


def test_connect_migrates_old_player_stats(tmp_path):
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE player_stats ("
        "match_id INTEGER NOT NULL, side TEXT NOT NULL, seq INTEGER NOT NULL,"
        " number TEXT, player TEXT, position TEXT, rating REAL, data_json TEXT,"
        " PRIMARY KEY (match_id, side, seq))"
    )
    conn.execute(
        "INSERT INTO player_stats (match_id, side, seq, player, rating)"
        " VALUES (1, 'home', 1, '旧球员', 7.0)"
    )
    conn.commit()
    conn.close()

    conn = store.connect(path)
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(player_stats)")}
        assert "player_id" in columns
        row = conn.execute(
            "SELECT player, rating, player_id FROM player_stats WHERE match_id=1"
        ).fetchone()
        assert row["player"] == "旧球员"
        assert row["rating"] == 7.0
        assert row["player_id"] is None
    finally:
        conn.close()
