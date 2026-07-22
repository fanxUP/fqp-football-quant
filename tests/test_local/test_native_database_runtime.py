from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_host_ports_use_the_canonical_local_endpoints() -> None:
    manager = (PROJECT_ROOT / "ops/local/manage_local_stack.sh").read_text(encoding="utf-8")
    dev_script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")
    vite_config = (PROJECT_ROOT / "apps/frontend/vite.config.ts").read_text(encoding="utf-8")

    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in manager
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"' in manager
    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in dev_script
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8006}"' in dev_script
    assert "port: 8066" in vite_config
    assert "http://127.0.0.1:8006" in vite_config


def test_incremental_migrations_track_applied_files() -> None:
    script = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(encoding="utf-8")

    assert "local_schema_migrations" in script
    assert "ON_ERROR_STOP=1" in script
    assert "BASELINE_VERSION=32" in script
    assert "SELECT filename FROM local_schema_migrations ORDER BY filename" in script
    assert "SELECT 1 FROM local_schema_migrations WHERE filename" not in script
    assert "FQP_PSQL_BIN" in script
    assert "docker compose" not in script


def test_native_database_sessions_store_utc_timestamps() -> None:
    init_script = (PROJECT_ROOT / "ops/local/init_local_database.sh").read_text(
        encoding="utf-8"
    )
    migration_script = (
        PROJECT_ROOT / "ops/local/apply_local_migrations.sh"
    ).read_text(encoding="utf-8")

    assert "ALTER DATABASE %I SET timezone TO %L" in init_script
    assert "ALTER DATABASE %I SET timezone TO %L" in migration_script
    assert "SET timezone TO 'UTC'" in migration_script


def test_prediction_time_migration_normalizes_existing_rows_to_shanghai() -> None:
    migration = (
        PROJECT_ROOT / "sql/36_normalize_prediction_business_time.sql"
    ).read_text(encoding="utf-8")

    assert "UPDATE model_predictions" in migration
    assert "UPDATE model_committee_votes" in migration
    assert "AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'" in migration
    assert "ABS(EXTRACT(EPOCH FROM (predict_time - created_at))) < 300" in migration


def test_prediction_review_integrity_migration_cleans_derived_contamination() -> None:
    migration = (
        PROJECT_ROOT / "sql/37_repair_prediction_review_integrity.sql"
    ).read_text(encoding="utf-8")

    assert "DELETE FROM prediction_error_analysis" in migration
    assert "mp.predict_time < m.kickoff_time" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in migration
    assert "UPDATE daily_reviews" in migration


def test_post_kickoff_derivative_migration_preserves_ticket_evidence() -> None:
    migration = (
        PROJECT_ROOT / "sql/38_purge_post_kickoff_model_derivatives.sql"
    ).read_text(encoding="utf-8")

    assert "DELETE FROM model_predictions" in migration
    assert "DELETE FROM model_committee_votes" in migration
    assert "DELETE FROM market_efficiency_metrics" in migration
    assert "predict_time >= m.kickoff_time" in migration
    assert "simulation_ticket_items" in migration


def test_live_recommendation_indexes_cover_latest_prediction_and_handicap_lookup() -> None:
    migration = (PROJECT_ROOT / "sql/41_live_recommendation_query_indexes.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.split())

    assert "idx_predictions_live_latest" in migration
    assert "match_id, model_version_id, play_type, option_code" in normalized
    assert "predict_time DESC, id DESC" in normalized
    assert "idx_odds_handicap_latest" in migration
    assert "match_id, play_type, snapshot_time DESC" in normalized
    assert "WHERE handicap IS NOT NULL" in migration


def test_prediction_read_indexes_only_expose_valid_pre_kickoff_evidence() -> None:
    migration = (
        PROJECT_ROOT / "sql/47_prediction_read_path_indexes.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.split())

    assert "idx_predictions_valid_recent" in migration
    assert "predict_time DESC, ev DESC, id DESC" in normalized
    assert "idx_predictions_valid_positive_ev" in migration
    assert "ev DESC, id DESC" in normalized
    assert "mp.validation_status = 'valid'" in migration
    assert "mp.predict_time < m.kickoff_time" in migration


def test_invalid_prediction_cleanup_blocks_future_agent_ticket_references() -> None:
    migration = (
        PROJECT_ROOT / "sql/44_purge_invalid_prediction_derivatives.sql"
    ).read_text(encoding="utf-8")

    assert "validation_status = 'invalid'" in migration
    assert "DELETE FROM ticket_settlements" in migration
    assert "DELETE FROM simulation_ticket_items" in migration
    assert "DELETE FROM simulation_tickets" in migration
    assert "DELETE FROM prediction_error_analysis" in migration
    assert "DELETE FROM model_committee_votes" in migration
    assert "DELETE FROM evidence_chain_audit_logs" in migration
    assert "DELETE FROM model_predictions" in migration
    assert "enforce_valid_model_prediction_reference" in migration
    assert "validation_status = 'valid'" in migration


def test_orphan_prediction_derivatives_are_removed_and_guarded() -> None:
    migration = (
        PROJECT_ROOT / "sql/45_purge_orphan_prediction_derivatives.sql"
    ).read_text(encoding="utf-8")

    assert "DELETE FROM model_committee_votes" in migration
    assert "DELETE FROM market_efficiency_metrics" in migration
    assert "DELETE FROM score_distribution_snapshots" in migration
    assert "enforce_valid_committee_vote_reference" in migration
    assert "prediction.validation_status = 'valid'" in migration


def test_evidence_less_agent_tickets_are_purged_and_statistics_rebuilt() -> None:
    migration = (
        PROJECT_ROOT / "sql/46_purge_evidence_less_agent_tickets.sql"
    ).read_text(encoding="utf-8")

    assert "NOT EXISTS" in migration
    assert "simulation_ticket_items" in migration
    assert "DELETE FROM ticket_settlements" in migration
    assert "DELETE FROM simulation_tickets" in migration
    assert "refresh_agent_statistics_after_cleanup" in migration
    assert "competition_daily_snapshots" in migration
    assert "daily_reviews" in migration
