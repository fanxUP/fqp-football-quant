from unittest.mock import MagicMock, patch

from scripts.jobs.update_elo_ratings import run


def _db_context(conn: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__enter__.return_value = conn
    return context


def test_elo_job_uses_canonical_team_mapping_and_continues_after_one_failure():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [
        (1, 10, 20, "2026-07-20", 2, 1, "主队A", "客队A", "测试联赛", None),
        (2, 30, 40, "2026-07-21", 0, 0, "主队B", "客队B", "测试联赛", None),
    ]

    with (
        patch("scripts.jobs.update_elo_ratings.get_db", return_value=_db_context(conn)),
        patch(
            "scripts.jobs.update_elo_ratings.ensure_official_match_teams",
            return_value=3,
        ),
        patch(
            "scripts.jobs.update_elo_ratings.update_elo_ratings",
            side_effect=[RuntimeError("bad match"), {"match_id": 2}],
        ),
    ):
        result = run()

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "JOIN LATERAL" in query
    assert "COALESCE(t1.id, 0)" not in query
    assert result["status"] == "partial"
    assert result["updated"] == 1
    assert result["errors"] == 1
    assert result["teams_created"] == 3
    assert result["error_samples"][0]["match_id"] == 1
    conn.rollback.assert_called_once()


def test_elo_job_fails_when_every_pending_match_errors():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [
        (1, 10, 20, "2026-07-20", 2, 1, "主队A", "客队A", "测试联赛", None),
    ]

    with (
        patch("scripts.jobs.update_elo_ratings.get_db", return_value=_db_context(conn)),
        patch(
            "scripts.jobs.update_elo_ratings.ensure_official_match_teams",
            return_value=0,
        ),
        patch(
            "scripts.jobs.update_elo_ratings.update_elo_ratings",
            side_effect=RuntimeError("database error"),
        ),
    ):
        result = run()

    assert result["status"] == "error"
    assert result["updated"] == 0
    assert result["errors"] == 1
