from pathlib import Path


def test_competition_coverage_matches_seasons_by_date_range():
    migration = Path("sql/55_fix_competition_coverage_season_dates.sql")

    assert migration.exists()
    sql = " ".join(migration.read_text(encoding="utf-8").split())
    assert "emc.kickoff_time::date BETWEEN s.start_date AND s.end_date" in sql
    assert "s.season_code::int" not in sql


def test_competition_coverage_allows_timezone_rollover_at_season_boundaries():
    migration = Path("sql/57_fix_competition_coverage_timezone_boundary.sql")

    assert migration.exists()
    sql = " ".join(migration.read_text(encoding="utf-8").split())
    assert "s.start_date - INTERVAL '1 day'" in sql
    assert "s.end_date + INTERVAL '1 day'" in sql
