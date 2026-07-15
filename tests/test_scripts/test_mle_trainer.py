from unittest.mock import MagicMock, patch

from psycopg2.extras import Json

from scripts.mle_trainer import run


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
