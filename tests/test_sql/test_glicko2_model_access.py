from pathlib import Path


def test_existing_installations_grant_runtime_role_access_to_glicko2_tables() -> None:
    source = Path("sql/73_grant_glicko2_model_access.sql").read_text()

    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON team_glicko2_ratings TO fqp" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON glicko2_update_logs TO fqp" in source
    assert "GRANT USAGE, SELECT ON SEQUENCE team_glicko2_ratings_id_seq TO fqp" in source
    assert "GRANT USAGE, SELECT ON SEQUENCE glicko2_update_logs_id_seq TO fqp" in source
