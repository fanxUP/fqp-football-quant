from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_prediction_run_migration_is_additive_and_has_group_publication_view() -> None:
    migration = (ROOT / "sql/111_prediction_run_identity.sql").read_text(encoding="utf-8")
    down = (ROOT / "sql/down/111_prediction_run_identity.down.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS model_prediction_runs" in migration
    assert "CREATE TABLE IF NOT EXISTS model_prediction_groups" in migration
    assert "CREATE TRIGGER trg_immutable_prediction_run" in migration
    assert "CREATE TRIGGER trg_prediction_group_must_start_building" in migration
    assert "CREATE TABLE IF NOT EXISTS model_prediction_group_options" in migration
    assert "CREATE OR REPLACE VIEW model_prediction_latest_rows" in migration
    assert "ALTER TABLE model_predictions" not in migration
    assert "UPDATE model_predictions" not in migration
    assert "DROP TABLE IF EXISTS model_prediction_group_options" in down
    assert "DROP TABLE IF EXISTS model_prediction_groups" in down
    assert "DROP TABLE IF EXISTS model_prediction_runs" in down


def test_migration_has_bounded_lock_and_statement_timeouts() -> None:
    migration = (ROOT / "sql/111_prediction_run_identity.sql").read_text(encoding="utf-8")

    assert "SET LOCAL lock_timeout = '2s'" in migration
    assert "SET LOCAL statement_timeout = '15s'" in migration
