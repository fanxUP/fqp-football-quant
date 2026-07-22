from unittest.mock import MagicMock, patch

from psycopg2.extras import Json

from scripts.mle_trainer import _load_match_data, run


def test_mle_run_adapts_parameter_dicts_for_jsonb_without_missing_updated_at_column():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1},
            "defense": {1: -0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 20,
            "n_teams": 2,
            "nll": 10.0,
            "converged": True,
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 5.0, "n_low_score_matches": 6},
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=db_context),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
    ):
        result = run()

    assert result["status"] == "ok"
    assert cur.execute.call_count == 2
    for call in cur.execute.call_args_list:
        query, params = call.args
        assert "updated_at" not in query
        assert isinstance(params[0], Json)
    conn.commit.assert_called_once()


def test_training_data_excludes_unmapped_teams_and_applies_minimum_history() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchall.return_value = [(10, 20, 2, 1), (20, 10, 0, 0)]

    team_ids, _, home_idx, away_idx, home_goals, away_goals = _load_match_data(
        conn,
        min_matches=2,
    )

    query, params = cur.execute.call_args.args
    normalized = " ".join(query.split())
    assert "JOIN teams t1" in normalized
    assert "JOIN teams t2" in normalized
    assert "COALESCE(t1.id, 0)" not in normalized
    assert "HAVING COUNT(*) >= %s" in normalized
    assert params == (2,)
    assert team_ids == [10, 20]
    assert home_idx == [0, 1]
    assert away_idx == [1, 0]
    assert home_goals == [2, 0]
    assert away_goals == [1, 0]
