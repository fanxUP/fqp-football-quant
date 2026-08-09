from pathlib import Path


def test_glicko2_schema_keeps_rating_state_and_idempotent_match_log() -> None:
    source = Path("sql/72_add_glicko2_rating_model.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS team_glicko2_ratings" in source
    assert "rating_deviation" in source
    assert "volatility" in source
    assert "CREATE TABLE IF NOT EXISTS glicko2_update_logs" in source
    assert "match_id BIGINT NOT NULL UNIQUE" in source
    assert '"rollout_mode":"shadow"' in source
