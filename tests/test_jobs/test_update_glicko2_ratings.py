from unittest.mock import MagicMock, patch

from scripts.jobs.update_glicko2_ratings import run


def _db_context(conn: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__enter__.return_value = conn
    return context


def test_glicko2_job_uses_canonical_team_mapping_and_continues_after_one_failure() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = [
        (1, 10, 20, "2026-07-20", 2, 1, "主队A", "客队A", "测试联赛"),
        (2, 30, 40, "2026-07-21", 0, 0, "主队B", "客队B", "测试联赛"),
    ]

    with (
        patch("scripts.jobs.update_glicko2_ratings.get_db", return_value=_db_context(conn)),
        patch("scripts.jobs.update_glicko2_ratings.ensure_official_match_teams", return_value=3),
        patch(
            "scripts.jobs.update_glicko2_ratings.update_glicko2_ratings",
            side_effect=[RuntimeError("bad match"), {"match_id": 2}],
        ),
    ):
        result = run()

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "JOIN LATERAL" in query
    assert "glicko2_update_logs" in query
    assert result["status"] == "partial"
    assert result["updated"] == 1
    assert result["errors"] == 1
    conn.rollback.assert_called_once()


def test_glicko2_job_uses_confirmed_scores_instead_of_legacy_match_status() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = []

    with (
        patch("scripts.jobs.update_glicko2_ratings.get_db", return_value=_db_context(conn)),
        patch("scripts.jobs.update_glicko2_ratings.ensure_official_match_teams", return_value=0),
    ):
        run()

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "m.kickoff_time < timezone('Asia/Shanghai', NOW())" in query
    assert "m.match_status = 'Settled'" not in query
