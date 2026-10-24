from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_training_manifest_migration_is_additive_and_append_only() -> None:
    migration = (ROOT / "sql/112_model_training_manifest.sql").read_text(encoding="utf-8")
    normalized = " ".join(migration.split())

    assert "CREATE TABLE IF NOT EXISTS model_training_manifests" in migration
    assert (
        "model_version_id BIGINT PRIMARY KEY REFERENCES model_versions(id) ON DELETE RESTRICT"
        in normalized
    )
    assert "manifest_json JSONB NOT NULL" in migration
    assert "manifest_canonical BYTEA NOT NULL" in migration
    assert "training_manifest_sha256" in migration
    assert "content_sha256" in migration
    assert "BEFORE INSERT OR UPDATE OR DELETE ON model_training_manifests" in normalized
    assert "GRANT SELECT, INSERT ON model_training_manifests TO fqp" in migration
    assert "REVOKE UPDATE, DELETE ON model_training_manifests FROM fqp" in migration
    assert "SET LOCAL lock_timeout = '2s'" in migration
    assert "SET LOCAL statement_timeout = '15s'" in migration
    assert "UPDATE model_versions" not in migration
    assert "UPDATE model_predictions" not in migration
    assert "INSERT INTO model_training_manifests" not in migration


def test_training_manifest_migration_uses_existing_canonical_byte_validator() -> None:
    migration = (ROOT / "sql/112_model_training_manifest.sql").read_text(encoding="utf-8")

    assert "prediction_manifest_bytes_have_unique_keys" in migration
    assert "pg_catalog.sha256(manifest_canonical)" in migration
    assert "convert_from(manifest_canonical, 'UTF8')::JSONB" in migration
