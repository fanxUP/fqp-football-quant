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
    assert "output_manifest_canonical BYTEA NOT NULL" in migration
    assert "output_summary JSONB NOT NULL" in migration
    assert "prediction_manifest_bytes_have_unique_keys" in migration
    assert "counts_complete" in migration
    assert "FOR UPDATE" in migration
    assert "prediction run manifest is immutable after output begins" in migration
    assert "pg_catalog.sha256(NEW.output_manifest_canonical)" in migration
    assert "ALTER TABLE model_predictions" not in migration
    assert "UPDATE model_predictions" not in migration
    assert "DROP TABLE IF EXISTS model_prediction_group_options" in down
    assert "DROP TABLE IF EXISTS model_prediction_groups" in down
    assert "DROP TABLE IF EXISTS model_prediction_runs" in down
    assert "DROP FUNCTION IF EXISTS prediction_manifest_bytes_have_unique_keys(BYTEA)" in down


def test_migration_has_bounded_lock_and_statement_timeouts() -> None:
    migration = (ROOT / "sql/111_prediction_run_identity.sql").read_text(encoding="utf-8")

    assert "SET LOCAL lock_timeout = '2s'" in migration
    assert "SET LOCAL statement_timeout = '15s'" in migration


def test_prediction_view_uses_explicit_matching_column_order_for_union() -> None:
    migration = (ROOT / "sql/111_prediction_run_identity.sql").read_text(encoding="utf-8")
    normalized = " ".join(migration.split())

    assert (
        "SELECT mp.id, mp.match_id, mp.model_version_id, mp.odds_snapshot_id, "
        "mp.feature_snapshot_id, mp.predict_time, mp.play_type, mp.option_code, "
        "mp.raw_model_probability, mp.model_probability, mp.market_probability, "
        "mp.probability_lower_bound, mp.probability_upper_bound, mp.uncertainty_score, "
        "mp.adjusted_probability, mp.fair_odds, mp.ev, mp.confidence_score, mp.risk_score, "
        "mp.break_even_probability, mp.market_edge, mp.breakeven_edge, mp.validation_status, "
        "mp.validation_errors, mp.calculation_version, mp.uncertainty_reason, mp.created_at, "
        "g.run_id AS prediction_run_id, g.id AS prediction_group_id, "
        "g.provenance_status AS group_provenance_status FROM latest_groups latest"
    ) in normalized
