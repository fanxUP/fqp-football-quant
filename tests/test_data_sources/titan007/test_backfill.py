import sqlite3

from scripts.sources.titan007 import backfill


def _add_match(conn, match_id: int, home_name: str, away_name: str) -> None:
    conn.execute(
        "INSERT INTO matches (match_id, match_date, kickoff, league_id, league_name,"
        " home_name, away_name, status_code, status_text)"
        " VALUES (?,?,?,25,'英超',?,?, -1,'完')",
        (match_id, f"2026-10-{20 + match_id}", "2026-10-20 20:00", home_name, away_name),
    )


def test_backfill_fills_ids_from_known_names(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _add_match(conn, 5, "主队", "客队三")
    conn.commit()

    stats = backfill.backfill_team_ids(conn)

    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=5").fetchone()
    assert (row["home_id"], row["away_id"]) == (100, 300)
    assert stats["fully_linked"] == 1


def test_backfill_dry_run_keeps_rows_untouched(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _add_match(conn, 6, "主队", "乙队")
    conn.commit()

    stats = backfill.backfill_team_ids(conn, dry_run=True)

    assert stats["fully_linked"] == 1
    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=6").fetchone()
    assert (row["home_id"], row["away_id"]) == (None, None)


def test_backfill_skips_ambiguous_names(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO league_teams (league_id,team_id,name) VALUES (25,700,'重名队')")
    conn.execute("INSERT INTO league_teams (league_id,team_id,name) VALUES (25,701,'重名队')")
    _add_match(conn, 7, "重名队", "乙队")
    conn.commit()

    stats = backfill.backfill_team_ids(conn)
    resolved, ambiguous = backfill.build_name_index(conn)

    assert stats["ambiguous_names"] >= 1
    assert "重名队" in ambiguous and "重名队" not in resolved
    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=7").fetchone()
    assert row["home_id"] is None and row["away_id"] == 600


def test_seasons_for_dates_picks_covering_season():
    seasons = ["2024-2025", "2025-2026", "2026"]

    assert backfill.seasons_for_dates(seasons, ["2025-10-01"]) == ["2025-2026"]
    assert backfill.seasons_for_dates(seasons, ["2025-02-01"]) == ["2024-2025"]
    assert backfill.seasons_for_dates(seasons, ["2026-03-01"]) == ["2025-2026", "2026"]
    assert backfill.seasons_for_dates(seasons, ["not-a-date"]) == []


def test_missing_league_seasons_reports_uncovered_years(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _add_match(conn, 8, "老队甲", "老队乙")
    conn.execute("UPDATE matches SET match_date='2024-05-01' WHERE match_id=8")
    conn.commit()

    missing = backfill.missing_league_seasons(conn)

    assert (25, 2024, 1) in missing
    assert all(year != 2026 for _lid, year, _n in missing)


def test_backfill_fuzzy_matches_renamed_club_in_same_league(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO league_teams (league_id,team_id,name) VALUES (25,800,'纳什威尔SC')")
    _add_match(conn, 9, "纳什威尔", "乙队")
    conn.commit()

    backfill.backfill_team_ids(conn, fuzzy=True)

    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=9").fetchone()
    assert (row["home_id"], row["away_id"]) == (800, 600)


def test_backfill_reads_ids_from_analysis_payloads(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO analysis_sections (match_id,section,payload) VALUES (1,'h2h',?)",
        ('[{"home_id": 900, "home_name": "新队甲", "away_id": 901, "away_name": "新队乙"}]',),
    )
    _add_match(conn, 12, "新队甲", "新队乙")
    conn.commit()

    backfill.backfill_team_ids(conn)

    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=12").fetchone()
    assert (row["home_id"], row["away_id"]) == (900, 901)


def test_backfill_strips_parenthesised_suffix(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _add_match(conn, 11, "主队(中)", "客队三")
    conn.commit()

    backfill.backfill_team_ids(conn)

    row = conn.execute("SELECT home_id, away_id FROM matches WHERE match_id=11").fetchone()
    assert (row["home_id"], row["away_id"]) == (100, 300)
