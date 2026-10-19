import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _server_migration_runner():
    runner_path = PROJECT_ROOT / "ops/server/migrate.py"
    spec = importlib.util.spec_from_file_location("server_migration_runner", runner_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_migration_runner_executes_outer_transaction_markers_inside_ledger_tx() -> None:
    runner = _server_migration_runner()
    for name in ("107_source_observations.sql", "108_complete_feature_batches.sql"):
        source = (PROJECT_ROOT / "sql" / name).read_text(encoding="utf-8")

        body = runner.migration_body(source)

        assert "CREATE TABLE IF NOT EXISTS" in body
        assert not any(
            line.strip().upper() in {"BEGIN;", "COMMIT;", "ROLLBACK;"} for line in body.splitlines()
        )


def test_server_migration_runner_strips_same_line_outer_transaction_statements() -> None:
    runner = _server_migration_runner()

    body = runner.migration_body("BEGIN; CREATE TABLE p104_probe(id int); COMMIT;\n")

    assert body.strip() == "CREATE TABLE p104_probe(id int);"


@pytest.mark.parametrize(
    "source",
    [
        "BEGIN; SELECT 1; COMMIT AND CHAIN;\n",
        "BEGIN; SELECT 1; COMMIT; SELECT 2;\n",
        "BEGIN; SELECT 1; COMMIT; BEGIN;\n",
        r"CREATE TABLE p104_probe(id int); SELECT '\'; COMMIT; SELECT $$'--$$;",
        "CREATE TABLE p104_probe(id int); SELECT 1 AS x$$; COMMIT; SELECT 2 AS y$$;",
        "CREATE TABLE p104_probe(id int); SELECT 1 AS 名$$; COMMIT; SELECT 2 AS x$$;",
        "SELECT $é$'$é$; COMMIT; SELECT $$'--$$;",
    ],
)
def test_server_migration_runner_rejects_unsafe_transaction_control_variants(source: str) -> None:
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="transaction boundary"):
        runner.migration_body(source)


def test_server_migration_runner_ignores_begin_inside_dollar_quoted_sql() -> None:
    runner = _server_migration_runner()
    source = "DO $$ BEGIN; PERFORM 1; END $$; SELECT 2;\n"

    assert runner.migration_body(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "SET LOCAL standard_conforming_strings = off;",
        "RESET standard_conforming_strings;",
        "RESET ALL;",
        "SELECT set_config('standard_conforming_strings', 'off', true);",
    ],
)
def test_server_migration_runner_rejects_changes_to_string_lexing(source: str) -> None:
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="cannot change standard_conforming_strings"):
        runner.migration_body(source)


@pytest.mark.parametrize(
    "source",
    [
        "BEGIN;\nSELECT 1;\n",
        "SELECT 1;\nCOMMIT;\n",
        "BEGIN;\nSELECT 1;\nCOMMIT;\nBEGIN;\n",
    ],
)
def test_server_migration_runner_rejects_partial_or_nested_transaction_markers(source: str) -> None:
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="transaction boundary"):
        runner.migration_body(source)


def test_server_migration_runner_allows_noop_after_database_ownership_transfer() -> None:
    runner = _server_migration_runner()

    runner.require_migration_authority(
        role="fqp",
        database_owner="fqp_observation_owner",
        superuser=False,
        has_pending=False,
        apply=True,
    )


def test_server_migration_runner_requires_owner_or_admin_for_pending_apply() -> None:
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="database owner or PostgreSQL administrator"):
        runner.require_migration_authority(
            role="fqp",
            database_owner="fqp_observation_owner",
            superuser=False,
            has_pending=True,
            apply=True,
        )

    runner.require_migration_authority(
        role="postgres",
        database_owner="fqp_observation_owner",
        superuser=True,
        has_pending=True,
        apply=True,
    )


def test_host_ports_use_the_canonical_local_endpoints() -> None:
    manager = (PROJECT_ROOT / "ops/local/manage_local_stack.sh").read_text(encoding="utf-8")
    dev_script = (PROJECT_ROOT / "ops/local/run_local_dev.sh").read_text(encoding="utf-8")
    vite_config = (PROJECT_ROOT / "apps/frontend/vite.config.ts").read_text(encoding="utf-8")

    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in manager
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8080}"' in manager
    assert 'FRONTEND_PORT="${FQP_FRONTEND_PORT:-8066}"' in dev_script
    assert 'BACKEND_PORT="${FQP_BACKEND_PORT:-8080}"' in dev_script
    assert "port: 8066" in vite_config
    assert "http://127.0.0.1:8080" in vite_config


def test_incremental_migrations_track_applied_files() -> None:
    script = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(encoding="utf-8")

    assert "local_schema_migrations" in script
    assert "ON_ERROR_STOP=1" in script
    assert "BASELINE_VERSION=32" in script
    assert "SELECT checksum_sha256" in script
    assert "WHERE filename = :'filename'" in script
    assert "FQP_PSQL_BIN" in script
    assert "command -v psql" in script
    assert "docker compose" not in script


def test_incremental_migrations_are_sorted_by_numeric_version() -> None:
    script = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(encoding="utf-8")

    assert "ordered_migrations" in script
    assert "sort -n -k1,1" in script
    assert script.count('for migration in "$PROJECT_ROOT"/sql/*.sql') == 1


def test_native_database_sessions_store_utc_timestamps() -> None:
    init_script = (PROJECT_ROOT / "ops/local/init_local_database.sh").read_text(encoding="utf-8")
    migration_script = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(
        encoding="utf-8"
    )

    assert "ALTER DATABASE %I SET timezone TO %L" in init_script
    assert "ALTER DATABASE %I SET timezone TO %L" in migration_script
    assert "SET timezone TO 'UTC'" in migration_script


def test_prediction_time_migration_normalizes_existing_rows_to_shanghai() -> None:
    migration = (PROJECT_ROOT / "sql/36_normalize_prediction_business_time.sql").read_text(
        encoding="utf-8"
    )

    assert "UPDATE model_predictions" in migration
    assert "UPDATE model_committee_votes" in migration
    assert "AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai'" in migration
    assert "ABS(EXTRACT(EPOCH FROM (predict_time - created_at))) < 300" in migration


def test_prediction_review_integrity_migration_cleans_derived_contamination() -> None:
    migration = (PROJECT_ROOT / "sql/37_repair_prediction_review_integrity.sql").read_text(
        encoding="utf-8"
    )

    assert "DELETE FROM prediction_error_analysis" in migration
    assert "mp.predict_time < m.kickoff_time" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in migration
    assert "UPDATE daily_reviews" in migration


def test_post_kickoff_derivative_migration_preserves_ticket_evidence() -> None:
    migration = (PROJECT_ROOT / "sql/38_purge_post_kickoff_model_derivatives.sql").read_text(
        encoding="utf-8"
    )

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
    migration = (PROJECT_ROOT / "sql/47_prediction_read_path_indexes.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(migration.split())

    assert "idx_predictions_valid_recent" in migration
    assert "predict_time DESC, ev DESC, id DESC" in normalized
    assert "idx_predictions_valid_positive_ev" in migration
    assert "ev DESC, id DESC" in normalized
    assert "mp.validation_status = 'valid'" in migration
    assert "mp.predict_time < m.kickoff_time" in migration


def test_invalid_prediction_cleanup_blocks_future_agent_ticket_references() -> None:
    migration = (PROJECT_ROOT / "sql/44_purge_invalid_prediction_derivatives.sql").read_text(
        encoding="utf-8"
    )

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
    migration = (PROJECT_ROOT / "sql/45_purge_orphan_prediction_derivatives.sql").read_text(
        encoding="utf-8"
    )

    assert "DELETE FROM model_committee_votes" in migration
    assert "DELETE FROM market_efficiency_metrics" in migration
    assert "DELETE FROM score_distribution_snapshots" in migration
    assert "enforce_valid_committee_vote_reference" in migration
    assert "prediction.validation_status = 'valid'" in migration


def test_evidence_less_agent_tickets_are_purged_and_statistics_rebuilt() -> None:
    migration = (PROJECT_ROOT / "sql/46_purge_evidence_less_agent_tickets.sql").read_text(
        encoding="utf-8"
    )

    assert "NOT EXISTS" in migration
    assert "simulation_ticket_items" in migration
    assert "DELETE FROM ticket_settlements" in migration
    assert "DELETE FROM simulation_tickets" in migration
    assert "refresh_agent_statistics_after_cleanup" in migration
    assert "competition_daily_snapshots" in migration
    assert "daily_reviews" in migration


def test_local_migration_runner_detects_applied_file_drift() -> None:
    runner = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(encoding="utf-8")

    assert "checksum_sha256" in runner
    assert "migration_checksum" in runner
    assert "applied migration was modified" in runner
