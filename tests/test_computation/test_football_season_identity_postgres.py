"""Opt-in isolated local PostgreSQL; restricted runtime role, real migrations."""

import copy
import json
import os
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.errors import InsufficientPrivilege, RaiseException, UniqueViolation
from psycopg2.extensions import parse_dsn

from scripts.football_season_identity import import_season, main, read_fixture_seasons
from tests.test_computation.test_football_season_identity import document, material

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "sql/127_football_fixture_seasons.sql"


def rows(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


@pytest.fixture
def database():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN", "")
    if not dsn:
        pytest.skip("explicit isolated history DSN required")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_history_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "season_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE model_predictions(id BIGINT PRIMARY KEY)")
            for name in (
                "01_core_official_schema.sql",
                "05_pool_reports_ops_schema.sql",
                "08_season_team_database.sql",
                "32_official_event_season_targets.sql",
                "117_pool_identity_and_snapshots.sql",
                "124_official_event_season_retention.sql",
                "125_football_fixture_identity.sql",
            ):
                cur.execute((ROOT / "sql" / name).read_text())
            cur.execute(
                "INSERT INTO competitions(id,competition_code,competition_type) VALUES (55,'premier-league','league'),(56,'other-league','league')"
            )
            cur.execute(
                "INSERT INTO seasons(id,season_code,season_name,start_date,end_date) VALUES (1,'2026','2026世界杯','2026-03-01','2026-07-19'),(2,'premier-league:2024-2025','2024-2025','2024-07-01','2025-06-30')"
            )
            cur.execute("SELECT setval('seasons_id_seq',10)")
            cur.execute(
                "INSERT INTO competition_seasons(id,competition_id,season_id) VALUES (79,55,1),(80,55,2),(81,56,1)"
            )
            cur.execute("SELECT setval('competition_seasons_id_seq',100)")
            cur.execute("INSERT INTO football_fixtures(id) VALUES (1),(2),(3)")
            cur.execute(
                "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','101',1,'{}'),('sporttery','jc.matchId','102',2,'{}'),('sporttery','uniformMatchId','101',3,'{}')"
            )
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
            cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA " + schema + " TO fqp")
            cur.execute("GRANT INSERT ON seasons,competition_seasons TO fqp")
            cur.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA " + schema + " TO fqp")
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()


@pytest.fixture
def ready(database):
    with database.cursor() as cur:
        cur.execute(MIGRATION.read_text())
        cur.execute("SET ROLE fqp")
    database.commit()
    return database


def test_real_rehearsal_commit_idempotence_and_legacy_preservation(ready):
    assert rows(ready, "SELECT current_user,rolsuper FROM pg_roles WHERE rolname=current_user") == [
        ("fqp", False)
    ]
    old = rows(ready, "SELECT to_jsonb(s) FROM seasons s ORDER BY id")
    old_cs = rows(ready, "SELECT to_jsonb(s) FROM competition_seasons s ORDER BY id")
    assert import_season(ready, material())["new_memberships"] == 1
    ready.rollback()
    assert rows(ready, "SELECT count(*) FROM football_fixture_seasons") == [(0,)]
    result = import_season(ready, material())
    assert result["competition_season_id"] == 80
    ready.commit()
    assert import_season(ready, material())["new_memberships"] == 0
    assert import_season(ready, material())["new_season_sources"] == 0
    ready.rollback()
    assert rows(ready, "SELECT to_jsonb(s) FROM seasons s ORDER BY id") == old
    assert rows(ready, "SELECT to_jsonb(s) FROM competition_seasons s ORDER BY id") == old_cs
    ready.rollback()
    with ready.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    found = read_fixture_seasons(ready, [1, 2, 3])
    assert len(found) == 1
    assert found[0]["source_season_id"] == "11817"
    assert str(found[0]["planned_start_date"]) == "2024-08-16"
    assert found[0]["season_name"] == "2024-2025"


def test_new_cross_year_season_has_no_fabricated_shared_dates(ready):
    data = material()
    data.update(
        season_code="premier-league:2025-2026",
        season_name="2025-2026",
        boundary_document=document(season=13343),
        member_documents=[],
        members=[],
    )
    assert import_season(ready, data)["new_memberships"] == 0
    assert rows(
        ready,
        "SELECT start_date,end_date FROM seasons WHERE season_code='premier-league:2025-2026'",
    ) == [(None, None)]


def test_second_member_failure_rolls_back_first_and_season(ready):
    data = material()
    data["member_documents"] = [document(members=(101, 999))]
    data["members"].append(dict(fixture_id=2, jc_match_id="999"))
    with pytest.raises(ValueError, match="existing shared fixture"):
        import_season(ready, data)
    ready.rollback()
    assert rows(ready, "SELECT count(*) FROM football_fixture_seasons") == [(0,)]
    assert rows(ready, "SELECT count(*) FROM football_competition_season_sources") == [(0,)]


def test_namespace_collision_does_not_link_other_fixture(ready):
    data = material()
    data["members"][0]["fixture_id"] = 3
    with pytest.raises(ValueError, match="existing shared fixture"):
        import_season(ready, data)


@pytest.mark.parametrize("kind", ["wrong_label", "shared_season"])
def test_preexisting_bad_canonical_season_is_not_promoted(ready, kind):
    with ready.cursor() as cur:
        cur.execute("RESET ROLE")
        if kind == "wrong_label":
            cur.execute("UPDATE seasons SET season_name='世界杯旧错误标签' WHERE id=2")
        else:
            cur.execute("INSERT INTO competition_seasons(competition_id,season_id) VALUES (56,2)")
        cur.execute("SET ROLE fqp")
    ready.commit()
    old = rows(ready, "SELECT to_jsonb(s) FROM seasons s ORDER BY id")
    with pytest.raises(ValueError, match="label conflicts|another competition"):
        import_season(ready, material())
    ready.rollback()
    assert rows(ready, "SELECT count(*) FROM football_competition_season_sources") == [(0,)]
    assert rows(ready, "SELECT to_jsonb(s) FROM seasons s ORDER BY id") == old


@pytest.mark.parametrize("kind", ["canonical", "bounds", "member"])
def test_existing_season_conflicts_rejected(ready, kind):
    import_season(ready, material())
    ready.commit()
    data = copy.deepcopy(material())
    if kind == "canonical":
        data["competition_code"] = "other-league"
    elif kind == "bounds":
        doc = data["boundary_document"]
        doc["body"] = doc["body"].replace("2025-05-26", "2025-06-30")
        import hashlib

        doc["sha256"] = hashlib.sha256(doc["body"].encode()).hexdigest()
    else:
        data.update(
            season_code="premier-league:2025-2026",
            season_name="2025-2026",
            boundary_document=document(season=13343),
            member_documents=[document(season=13343)],
        )
    with pytest.raises(ValueError, match="conflict|another competition"):
        import_season(ready, data)
    ready.rollback()
    assert read_fixture_seasons(ready, [1])[0]["source_season_id"] == "11817"


def test_concurrent_importer_lock_refused(ready):
    schema = rows(ready, "SELECT current_schema()")[0][0]
    ready.rollback()
    with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as other:
        with other.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("SET ROLE fqp")
            cur.execute("SELECT pg_advisory_xact_lock(939118,127)")
        with pytest.raises(ValueError, match="busy"):
            import_season(ready, material())
        other.rollback()


def test_autocommit_rejected_before_any_write(ready):
    ready.rollback()
    ready.autocommit = True
    try:
        with pytest.raises(ValueError, match="not autocommit"):
            import_season(ready, material())
        assert rows(ready, "SELECT count(*) FROM football_competition_season_sources") == [(0,)]
        assert rows(ready, "SELECT count(*) FROM football_fixture_seasons") == [(0,)]
    finally:
        ready.autocommit = False


def test_database_rejects_wrong_fixture_even_direct_insert(ready):
    result = import_season(ready, material())
    ready.commit()
    with pytest.raises(RaiseException, match="does not identify"):
        rows(
            ready,
            "INSERT INTO football_fixture_seasons VALUES (2,%s,'sporttery','jc.matchId','101','{\"test\":true}',clock_timestamp()) RETURNING fixture_id",
            (result["season_source_id"],),
        )


@pytest.mark.parametrize(
    "table", ["football_fixture_seasons", "football_competition_season_sources"]
)
def test_immutable_as_owner_and_restricted_role(ready, table):
    import_season(ready, material())
    ready.commit()
    with pytest.raises(InsufficientPrivilege):
        rows(ready, f"DELETE FROM {table} RETURNING 1")
    ready.rollback()
    with ready.cursor() as cur:
        cur.execute("RESET ROLE")
    ready.commit()
    for query in (
        f"UPDATE {table} SET evidence='{{}}'",
        f"DELETE FROM {table}",
        f"TRUNCATE {table} CASCADE",
    ):
        with pytest.raises(RaiseException, match="immutable"):
            with ready.cursor() as cur:
                cur.execute(query)
        ready.rollback()


def test_canonical_cannot_have_two_source_season_ids(ready):
    import_season(ready, material())
    ready.commit()
    data = material()
    data.update(boundary_document=document(season=13343), member_documents=[], members=[])
    with pytest.raises(UniqueViolation):
        import_season(ready, data)


def test_migration_rolls_back_without_altering_old_rows(database):
    old = rows(database, "SELECT to_jsonb(s) FROM seasons s ORDER BY id")
    with database.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    database.rollback()
    assert rows(database, "SELECT to_regclass('football_fixture_seasons')") == [(None,)]
    assert rows(database, "SELECT to_jsonb(s) FROM seasons s ORDER BY id") == old


def test_actual_cli_rehearsal_apply_and_failure_rollback(ready, tmp_path, monkeypatch, capsys):
    from psycopg2.extensions import make_dsn

    schema = rows(ready, "SELECT current_schema()")[0][0]
    ready.rollback()
    dsn = make_dsn(
        os.environ["FQP_HISTORY_TEST_DSN"], options=f"-c role=fqp -c search_path={schema}"
    )
    monkeypatch.setenv("DATABASE_URL", dsn)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(material()))
    assert main(["--input", str(path), "--mode", "rehearse"]) == 0
    assert json.loads(capsys.readouterr().out)["committed"] is False
    assert rows(ready, "SELECT count(*) FROM football_fixture_seasons") == [(0,)]
    ready.rollback()
    assert main(["--input", str(path), "--mode", "apply"]) == 0
    assert json.loads(capsys.readouterr().out)["committed"] is True
    assert len(read_fixture_seasons(ready, [1])) == 1
    ready.rollback()
    broken = material()
    broken["member_documents"] = [document(members=(102, 999))]
    broken["members"] = [
        dict(fixture_id=2, jc_match_id="102"),
        dict(fixture_id=3, jc_match_id="999"),
    ]
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="existing shared fixture"):
        main(["--input", str(path), "--mode", "apply"])
    assert read_fixture_seasons(ready, [2, 3]) == []


def test_127_release_ddl_acl_business_and_ledger_rollback(database):
    from ops.server.migrate import migration_body

    old_tables = [
        "seasons",
        "competition_seasons",
        "football_fixtures",
        "football_fixture_source_links",
        "official_matches",
        "official_results",
    ]
    old_rows = {t: rows(database, f"SELECT to_jsonb(t) FROM {t} t ORDER BY 1") for t in old_tables}
    schema = rows(database, "SELECT current_schema()")[0][0]
    acl_query = "SELECT relname,relacl::text FROM pg_class WHERE relnamespace=%s::regnamespace ORDER BY relname"
    before_acl = rows(database, acl_query, (schema,))
    with database.cursor() as cur:
        cur.execute(
            "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
        )
    database.commit()
    with database.cursor() as cur:
        cur.execute(migration_body(MIGRATION.read_text()))
        cur.execute(
            "INSERT INTO local_schema_migrations VALUES (%s,encode(sha256(convert_to(%s,'UTF8')),'hex'))",
            (MIGRATION.name, MIGRATION.read_text()),
        )
    assert rows(database, "SHOW lock_timeout") == [("2s",)]
    assert rows(database, "SHOW statement_timeout") == [("30s",)]
    assert rows(
        database,
        "SELECT pg_get_userbyid(relowner)='fqp' FROM pg_class WHERE oid='football_fixture_seasons'::regclass",
    ) == [(False,)]
    with database.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    assert rows(
        database, "SELECT current_user,rolsuper FROM pg_roles WHERE rolname=current_user"
    ) == [("fqp", False)]
    for table in ("football_fixture_seasons", "football_competition_season_sources"):
        for privilege in ("SELECT", "INSERT"):
            assert rows(
                database, "SELECT has_table_privilege(current_user,%s,%s)", (table, privilege)
            ) == [(True,)]
        for privilege in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
            assert rows(
                database, "SELECT has_table_privilege(current_user,%s,%s)", (table, privilege)
            ) == [(False,)]
    assert import_season(database, material())["new_memberships"] == 1
    assert len(read_fixture_seasons(database, [1])) == 1
    for table in old_tables:
        assert rows(database, f"SELECT to_jsonb(t) FROM {table} t ORDER BY 1") == old_rows[table]
    with database.cursor() as cur:
        cur.execute("RESET ROLE")
    assert rows(database, "SELECT count(*) FROM local_schema_migrations") == [(1,)]
    database.rollback()
    assert rows(
        database,
        "SELECT to_regclass('football_fixture_seasons'),to_regclass('football_competition_season_sources'),to_regclass('football_fixture_season_catalog')",
    ) == [(None, None, None)]
    assert rows(database, "SELECT count(*) FROM local_schema_migrations") == [(0,)]
    assert rows(
        database,
        "SELECT count(*) FROM pg_proc WHERE pronamespace=%s::regnamespace AND proname IN ('check_football_fixture_season_source','protect_football_season_identity')",
        (schema,),
    ) == [(0,)]
    assert [
        row
        for row in rows(database, acl_query, (schema,))
        if not row[0].startswith("local_schema_migrations")
    ] == before_acl
    for table in old_tables:
        assert rows(database, f"SELECT to_jsonb(t) FROM {table} t ORDER BY 1") == old_rows[table]
