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


def _clear_peer_migration_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(variable, raising=False)


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


def test_peer_migration_url_drops_app_credentials_and_uses_local_postgres_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_peer_migration_environment(monkeypatch)
    runner = _server_migration_runner()

    dsn = runner.peer_migration_database_url(
        "postgresql://fqp:secret-password@127.0.0.1:5432/fqp?sslmode=prefer"
    )
    parsed = runner.psycopg2.extensions.parse_dsn(dsn)

    assert parsed == {
        "dbname": "fqp",
        "user": "postgres",
        "host": "/var/run/postgresql",
        "port": "5432",
    }
    assert "secret-password" not in dsn
    assert "127.0.0.1" not in dsn


def test_peer_migration_url_rejects_unsafe_database_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_peer_migration_environment(monkeypatch)
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="simple local database"):
        runner.peer_migration_database_url("postgresql://fqp:secret@127.0.0.1:5432/not/safe")


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://fqp:secret@db.internal:5432/fqp",
        "host=127.0.0.1 hostaddr=203.0.113.15 dbname=fqp user=fqp",
        "host=127.0.0.1,db.internal dbname=fqp user=fqp",
        "service=remote dbname=fqp user=fqp",
        "dbname=fqp user=fqp",
        "host=127.0.0.1 dbname=fqp user=fqp",
        "host=127.0.0.1 hostaddr=127.0.0.1,::1 port=5432 dbname=fqp user=fqp",
    ],
)
def test_peer_migration_url_rejects_remote_or_mixed_endpoints(
    dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_peer_migration_environment(monkeypatch)
    runner = _server_migration_runner()

    with pytest.raises(
        RuntimeError,
        match="service routing|local PostgreSQL endpoint|loopback address|one valid local",
    ):
        runner.peer_migration_database_url(dsn)


@pytest.mark.parametrize("variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_peer_migration_url_rejects_ambient_routing(
    variable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_peer_migration_environment(monkeypatch)
    monkeypatch.setenv(variable, "/tmp/remote-routing.conf")
    runner = _server_migration_runner()

    with pytest.raises(RuntimeError, match="ambient libpq routing variables"):
        runner.peer_migration_database_url("host=127.0.0.1 port=5432 dbname=fqp")


def test_deploy_runner_executes_migrations_as_local_database_owner() -> None:
    deploy = (PROJECT_ROOT / "ops/server/deploy.sh").read_text(encoding="utf-8")

    assert '"sudo",\n    "-n",\n    "-u",\n    "postgres",' in deploy
    assert "peer_migration_database_url()" in deploy
    assert "FQP_MIGRATION_ROLE" not in deploy
    assert "run_migration" in deploy
    assert "run_migration --apply" in deploy
    assert ".venv/bin/python ops/server/migrate.py --apply" not in deploy
    assert "MIGRATION_APPLY_ATTEMPTED=true" in deploy
    assert "systemctl stop nginx" in deploy
    assert "nginx remain stopped" in deploy


def test_prediction_input_migrations_grant_only_runtime_required_privileges() -> None:
    updates = (PROJECT_ROOT / "sql/109_prediction_input_updates.sql").read_text(encoding="utf-8")
    revisions = (PROJECT_ROOT / "sql/110_prediction_input_revisions.sql").read_text(
        encoding="utf-8"
    )

    assert "GRANT SELECT, UPDATE ON prediction_input_dirty_matches TO fqp;" in updates
    assert "GRANT SELECT, INSERT, UPDATE ON prediction_input_consumers TO fqp;" in updates
    assert "GRANT SELECT, INSERT ON prediction_input_consumptions TO fqp;" in updates
    assert "GRANT SELECT, INSERT ON prediction_input_revisions TO fqp;" in revisions
    assert "GRANT USAGE ON SEQUENCE prediction_input_revisions_id_seq TO fqp;" in revisions
    assert "ALTER TABLE prediction_input_dirty_matches OWNER TO fqp_observation_owner;" in updates
    assert "ALTER TABLE prediction_input_consumers OWNER TO fqp_observation_owner;" in updates
    assert "ALTER TABLE prediction_input_consumptions OWNER TO fqp_observation_owner;" in updates
    assert (
        "ALTER FUNCTION notify_prediction_input_update() OWNER TO fqp_observation_owner;" in updates
    )
    assert "GRANT SELECT ON observation_streams TO fqp_observation_owner;" in updates
    assert "ALTER TABLE prediction_input_revisions OWNER TO fqp_observation_owner;" in revisions
    assert (
        "ALTER SEQUENCE prediction_input_revisions_id_seq OWNER TO fqp_observation_owner;"
        in revisions
    )
    assert (
        "ALTER FUNCTION notify_prediction_official_update() OWNER TO fqp_observation_owner;"
        in revisions
    )
    assert "GRANT UPDATE, DELETE, TRUNCATE ON prediction_input_consumptions" not in updates
    assert "GRANT UPDATE, DELETE, TRUNCATE ON prediction_input_revisions" not in revisions


def test_ci_fixture_checks_migration_owner_and_app_acl_catalogs() -> None:
    setup = (PROJECT_ROOT / "scripts/ci/init_observation_test_db.sh").read_text(encoding="utf-8")

    assert "aclexplode(c.relacl)" in setup
    assert "P105 migrations did not grant the required runtime ACLs to fqp" in setup
    assert "fqp_observation_owner" in setup
    assert "P105 append-only runtime grants include mutation privileges" in setup
    assert "P105 runtime grants include privileges outside the required ACL" in setup
    assert "P105 notification owner cannot read observation stream bindings" in setup
    assert "ALTER FUNCTION notify_prediction_input_update() OWNER TO fqp_observation_owner" in setup
    assert "Test-only elevated actor rights exercise immutable triggers" in setup


def test_local_and_docker_bootstraps_prepare_the_p105_owner() -> None:
    local_init = (PROJECT_ROOT / "ops/local/init_local_database.sh").read_text(encoding="utf-8")
    local_migrations = (PROJECT_ROOT / "ops/local/apply_local_migrations.sh").read_text(
        encoding="utf-8"
    )
    docker_bootstrap = (PROJECT_ROOT / "ops/docker-test/bootstrap-db.sh").read_text(
        encoding="utf-8"
    )

    for script in (local_init, local_migrations, docker_bootstrap):
        assert "fqp_observation_owner NOLOGIN NOSUPERUSER" in script
        assert "GRANT USAGE, CREATE ON SCHEMA public TO fqp_observation_owner" in script
        assert "fqp_observation_owner exists with unsafe role attributes" in script
    for script in (local_init, local_migrations, docker_bootstrap):
        assert '"$filename" =~ ^(109|110)_' in script
    assert 'psql_admin -d "$FQP_DATABASE_NAME" -f "$migration"' in docker_bootstrap
    assert local_migrations.index('source "$ENV_FILE"') < local_migrations.index(
        'ADMIN_USER="${FQP_POSTGRES_ADMIN_USER:-$USER}"'
    )


def test_deploy_peer_migration_clears_libpq_routing_and_secret_environment() -> None:
    deploy = (PROJECT_ROOT / "ops/server/deploy.sh").read_text(encoding="utf-8")

    for variable in (
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGPASSWORD",
        "PGOPTIONS",
    ):
        assert f'"-u",\n    "{variable}",' in deploy


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
