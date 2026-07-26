from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_football_season_repair_preserves_competition_season_ids():
    sql = (ROOT / "sql" / "50_repair_api_football_seasons.sql").read_text()

    assert "apifootball:292:2026" in sql
    assert "UPDATE competition_seasons" in sql
    assert "DELETE FROM competition_seasons" not in sql
    assert "DELETE FROM seasons" not in sql
