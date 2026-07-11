from unittest.mock import patch
from pathlib import Path

from scripts.jobs.refresh_supplemental_seasons import run


def test_refresh_supplemental_seasons_runs_each_registered_league():
    with patch("scripts.jobs.refresh_supplemental_seasons.crawl_league_full") as crawl:
        crawl.side_effect = lambda name, league_id: {"league": name, "status": "ok"}
        with patch("scripts.jobs.refresh_supplemental_seasons.build_standings", return_value={"written": 1}):
            result = run()

    assert result["status"] == "ok"
    assert len(result["leagues"]) == 5
    assert result["standings"]["written"] == 1


def test_refresh_sql_scopes_season_backfill_to_league_name():
    source = Path("scripts/season_crawler.py").read_text()
    assert "c.competition_name_cn = sm.league_name" in source


def test_refresh_skips_when_another_process_holds_the_lock(tmp_path, monkeypatch):
    import fcntl
    import scripts.jobs.refresh_supplemental_seasons as refresh

    lock_path = tmp_path / "refresh.lock"
    monkeypatch.setattr(refresh, "LOCK_PATH", lock_path)
    with lock_path.open("w") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert refresh.run() == {"status": "skipped", "reason": "refresh_already_running"}
