"""Opt-in loopback-only reference import and read integration, never production."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

from scripts.league_reference_storage import (
    import_season,
    league_catalog,
    league_fixtures,
    league_season,
)
from scripts.titan007_import import load_season
from tests.test_data_sources.titan007.test_refresh import website as website

pytest_plugins = ("tests.test_data_sources.titan007.test_league_import",)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database():
    dsn = os.environ.get("FQP_LEAGUE_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Explicit isolated league test database not configured")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_league_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        conn.autocommit = True
        schema = "league_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
            )
            assert cur.fetchone() == ("fqp-league-isolated-fixtures/v1",)
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute((ROOT / "sql/08_season_team_database.sql").read_text())
                cur.execute((ROOT / "sql/118_league_reference_data.sql").read_text())
                cur.execute(
                    "CREATE TABLE official_matches(id bigserial PRIMARY KEY, raw_json jsonb)"
                )
                cur.execute(
                    "INSERT INTO official_matches(raw_json) VALUES ('{\"untouched\":true}')"
                )
            conn.commit()
            yield conn, dsn, schema
        finally:
            conn.rollback()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return cur.fetchone()[0]


def publish(database, cache, config):
    conn = database[0]
    result = import_season(conn, load_season(cache, config=config))
    conn.commit()
    return result


def test_refresh_publishes_atomic_batch_and_resumes_without_http(
    database, tmp_path, config, website, monkeypatch
):
    from psycopg2.extensions import make_dsn

    from scripts.titan007_refresh import refresh_league

    conn, dsn, schema = database
    monkeypatch.setenv("DATABASE_URL", make_dsn(dsn, options=f"-c search_path={schema}"))
    result = refresh_league(tmp_path, config=config, apply=True)
    assert result["status"] == "published" and result["business_database_imported"]
    assert count(conn, "league_reference_batches") == 1
    assert count(conn, "league_reference_fixtures") == 2
    assert count(conn, "league_reference_standings") == 6
    assert count(conn, "official_matches") == 1
    with conn.cursor() as cur:
        cur.execute("SELECT source_acquired_at FROM league_reference_batches")
        from datetime import datetime

        assert cur.fetchone()[0] == datetime.fromisoformat(result["source_acquired_at"])
    again = refresh_league(tmp_path, config=config, resume=result["run_id"], apply=True)
    assert again["status"] == "unchanged" and again["requests_this_attempt"] == 0
    assert again["publication"]["batch_id"] == result["publication"]["batch_id"]
    assert count(conn, "league_reference_batches") == 1 and len(website[0]) == 2


def test_refresh_unverified_identity_rolls_back_the_whole_publication(
    database, tmp_path, config, website, monkeypatch
):
    from psycopg2.extensions import make_dsn

    from scripts.titan007_refresh import refresh_league

    conn, dsn, schema = database
    with conn.cursor() as cur:
        cur.execute("INSERT INTO teams(team_name_cn) VALUES ('阿森纳')")
    conn.commit()
    monkeypatch.setenv("DATABASE_URL", make_dsn(dsn, options=f"-c search_path={schema}"))
    result = refresh_league(tmp_path, config=config, apply=True)
    assert result["status"] == "publish_failed" and not result["business_database_imported"]
    assert count(conn, "teams") == count(conn, "official_matches") == 1
    assert count(conn, "competitions") == count(conn, "league_reference_batches") == 0
    assert count(conn, "football_team_source_links") == 0
    assert (tmp_path / "runs" / f"refresh-{result['run_id']}.payload.json").is_file()


def test_idempotent_publish_preserves_official_and_legacy_standings(database, cache, config):
    conn = database[0]
    first = publish(database, cache, config)
    again = publish(database, cache, config)
    assert again["status"] == "unchanged"
    assert again["batch_id"] == first["batch_id"]
    assert count(conn, "teams") == 2
    assert count(conn, "football_team_source_links") == 2
    assert count(conn, "league_reference_batches") == 1
    assert count(conn, "league_reference_fixtures") == 2
    assert count(conn, "season_standings_snapshots") == 0
    with conn.cursor() as cur:
        cur.execute("SELECT raw_json FROM official_matches")
        assert cur.fetchall() == [({"untouched": True},)]
    data = league_season(conn, first["competition_season_id"])
    assert data["overview"]["goals"] == 0
    assert data["overview"]["draws"] == 1
    assert data["standings"]["all"]["rows"][0]["points"] == -2
    assert data["standings"]["all"]["rows"][0]["form"] == ["D"]
    assert "home" not in data["standings"]
    assert data["evidence"]["completeness"] == "complete"


def test_corrections_preserve_old_revision_and_pagination_batch(database, cache, config):
    conn = database[0]
    first = publish(database, cache, config)
    with sqlite3.connect(cache / "titan007.db") as source:
        source.execute("UPDATE league_results SET home_score=2 WHERE match_id=101")
    second = publish(database, cache, config)
    assert second["batch_id"] != first["batch_id"]
    assert count(conn, "league_reference_batches") == 2
    old = league_fixtures(conn, first["competition_season_id"], batch_id=first["batch_id"])
    latest = league_fixtures(conn, second["competition_season_id"])
    assert old["rows"][0]["homeGoals"] == 0
    assert latest["rows"][0]["homeGoals"] == 2
    assert old["rows"][0]["id"] == latest["rows"][0]["id"]
    assert latest["rows"][0]["officialMatch"] is None


def test_unverified_same_name_is_quarantined_not_silently_merged_or_duplicated(
    database, cache, config
):
    conn = database[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams(team_code,team_name_cn) VALUES('existing-a','阿森纳'),('existing-b','阿森纳')"
        )
    conn.commit()
    result = publish(database, cache, config)
    assert len(result["unmapped_teams"]) == 1
    assert result["imported_fixtures"] == 0
    assert count(conn, "teams") == 3
    data = league_season(conn, result["competition_season_id"])
    assert data["evidence"]["completeness"] == "partial"
    assert data["standings"]["all"]["rows"] == []


def test_reviewed_alias_reuses_existing_canonical_team(database, cache, config):
    conn = database[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams(team_code,team_name_cn) VALUES('existing-a','官方阿森纳') RETURNING id"
        )
        tid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO team_aliases(team_id,source_name,alias_name,is_verified) VALUES(%s,'titan007','阿森纳',true)",
            (tid,),
        )
    result = publish(database, cache, config)
    assert result["unmapped_teams"] == []
    assert count(conn, "teams") == 2
    page = league_fixtures(conn, result["competition_season_id"], team_id=tid, limit=1)
    assert page["total"] == 2 and len(page["rows"]) == 1
    assert page["rows"][0]["home"]["id"] == tid


def test_verified_team_with_only_english_name_remains_displayable(database, cache, config):
    conn = database[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO teams(team_code,team_name_en) VALUES('existing-en','Arsenal') RETURNING id"
        )
        tid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO team_aliases(team_id,source_name,alias_name,is_verified) VALUES(%s,'titan007','阿森纳',true)",
            (tid,),
        )
    result = publish(database, cache, config)
    data = league_season(conn, result["competition_season_id"])
    assert next(team for team in data["teams"] if team["id"] == tid)["name"] == "Arsenal"


def test_registered_competition_and_season_are_reused(database, cache, config):
    conn = database[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions(competition_code,competition_name_cn,competition_type) VALUES('apifootball:39','英超','league') RETURNING id"
        )
        cid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO seasons(season_code,season_name,start_date,end_date) VALUES('apifootball:39:2026','2026/27','2026-08-01','2027-06-01') RETURNING id"
        )
        sid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO competition_seasons(competition_id,season_id,total_teams) VALUES(%s,%s,2) RETURNING id",
            (cid, sid),
        )
        csid = cur.fetchone()[0]
    result = publish(database, cache, config)
    assert result["competition_season_id"] == csid
    assert count(conn, "competitions") == count(conn, "seasons") == 1


def test_unregistered_same_name_competition_requires_explicit_mapping(database, cache, config):
    conn = database[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions(competition_code,competition_name_cn,competition_type) VALUES('legacy-epl','英超','league')"
        )
    conn.commit()
    with pytest.raises(ValueError, match="同名赛事"):
        import_season(conn, load_season(cache, config=config))
    assert count(conn, "competitions") == 1
    assert count(conn, "league_reference_batches") == 0


def test_failure_rolls_back_every_new_identity_and_fact(database, cache, config):
    conn = database[0]
    with patch(
        "scripts.league_reference_storage.execute_values",
        side_effect=RuntimeError("fixture failure"),
    ):
        with pytest.raises(RuntimeError, match="fixture failure"):
            import_season(conn, load_season(cache, config=config))
    conn.commit()
    for table in (
        "teams",
        "competitions",
        "seasons",
        "competition_seasons",
        "football_team_source_links",
        "league_reference_batches",
        "league_reference_fixtures",
        "league_reference_standings",
    ):
        assert count(conn, table) == 0


def test_preview_rolls_back_and_reapplying_migration_keeps_rows(database, cache, config):
    conn = database[0]
    report = import_season(conn, load_season(cache, config=config), dry_run=True)
    assert report["dry_run"] is True
    assert count(conn, "teams") == count(conn, "league_reference_batches") == 0
    first = publish(database, cache, config)
    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/118_league_reference_data.sql").read_text())
    conn.commit()
    assert count(conn, "league_reference_batches") == 1
    assert (
        league_catalog(conn)["competitions"][0]["seasons"][0]["id"]
        == first["competition_season_id"]
    )


def test_cli_checks_mapping_rolls_back_then_applies_idempotently(
    database, cache, config, tmp_path, monkeypatch, capsys
):
    from psycopg2.extensions import make_dsn

    from scripts.titan007_import import main

    conn, dsn, schema = database
    config_path = tmp_path / "import.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("DATABASE_URL", make_dsn(dsn, options=f"-c search_path={schema}"))
    args = ["--data-dir", str(cache), "--config", str(config_path)]
    assert main([*args, "--check-mapping"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert count(conn, "league_reference_batches") == count(conn, "teams") == 0
    assert main([*args, "--apply"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "published"
    assert main([*args, "--apply"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "unchanged" and second["batch_id"] == first["batch_id"]


def test_existing_application_role_can_import_and_read_with_new_table_grants(
    database, cache, config
):
    conn, _, schema = database
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname='fqp'")
        if cur.fetchone() is None:
            pytest.skip("Fixture cluster has no application role")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            "GRANT SELECT,INSERT ON competitions,seasons,competition_seasons,teams,team_aliases TO fqp"
        )
        cur.execute(
            "GRANT USAGE ON SEQUENCE competitions_id_seq,seasons_id_seq,competition_seasons_id_seq,teams_id_seq,team_aliases_id_seq TO fqp"
        )
        cur.execute("SET LOCAL ROLE fqp")
    result = publish(database, cache, config)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    assert league_season(conn, result["competition_season_id"])["coverage"]["fixtures"] == 2
    conn.rollback()


def test_filters_totals_missing_team_and_cross_season_batch_are_checked(database, cache, config):
    conn = database[0]
    result = publish(database, cache, config)
    csid = result["competition_season_id"]
    page = league_fixtures(conn, csid, status="upcoming", round_id="r2", limit=1)
    assert page["total"] == 1 and page["rows"][0]["status"] == "scheduled"
    assert league_fixtures(conn, csid, status="postponed")["total"] == 0
    assert league_fixtures(conn, csid, offset=2)["rows"] == []
    with pytest.raises(LookupError):
        league_fixtures(conn, csid, team_id=999999)
    with pytest.raises(LookupError):
        league_fixtures(conn, csid + 1, batch_id=result["batch_id"])


def test_unknown_time_is_stale_and_incomplete_rank_rows_not_exposed(database, cache, config):
    conn = database[0]
    with sqlite3.connect(cache / "titan007.db") as source:
        source.execute("UPDATE league_info SET last_update=NULL")
        source.execute("DELETE FROM league_standings WHERE team_id=24")
    result = publish(database, cache, config)
    data = league_season(conn, result["competition_season_id"])
    assert data["evidence"]["asOf"] is None
    assert data["evidence"]["stale"] is True
    assert data["standings"]["all"]["evidence"]["completeness"] == "partial"
    assert data["standings"]["all"]["rows"] == []


def test_older_source_revision_cannot_replace_newer_current_data(database, cache, config):
    conn = database[0]
    first = publish(database, cache, config)
    with sqlite3.connect(cache / "titan007.db") as source:
        source.execute("UPDATE league_info SET last_update='2026-10-20 10:00:00'")
        source.execute("UPDATE league_results SET home_score=9 WHERE match_id=101")
    older = publish(database, cache, config)
    assert older["batch_id"] != first["batch_id"]
    assert league_fixtures(conn, first["competition_season_id"])["rows"][0]["homeGoals"] == 0


def test_partial_refresh_keeps_whole_previous_standing_batch_with_its_own_evidence(
    database, cache, config
):
    conn = database[0]
    first = publish(database, cache, config)
    with sqlite3.connect(cache / "titan007.db") as source:
        source.execute("DELETE FROM league_standings WHERE team_id=24")
        source.execute("UPDATE league_info SET last_update='2026-10-29 11:00:00'")
    second = publish(database, cache, config)
    data = league_season(conn, second["competition_season_id"])
    assert data["evidence"]["batchId"] == str(second["batch_id"])
    assert data["standings"]["all"]["evidence"]["batchId"] == str(first["batch_id"])
    assert len(data["standings"]["all"]["rows"]) == 2
    assert data["standings"]["all"]["rows"][0]["points"] == -2


def test_concurrent_importers_publish_once(database, cache, config):
    from concurrent.futures import ThreadPoolExecutor

    conn, dsn, schema = database
    data = load_season(cache, config=config)

    def write(_):
        with closing(psycopg2.connect(dsn)) as other:
            with other.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            report = import_season(other, data)
            other.commit()
            return report

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, range(2)))
    assert {item["status"] for item in results} == {"published", "unchanged"}
    assert results[0]["batch_id"] == results[1]["batch_id"]
    assert count(conn, "league_reference_batches") == 1
    assert count(conn, "teams") == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE league_reference_batches SET source_as_of=now() WHERE id=%s",
        "DELETE FROM league_reference_batches WHERE id=%s",
        "UPDATE league_reference_fixtures SET home_goals=9 WHERE batch_id=%s",
        "DELETE FROM league_reference_standings WHERE batch_id=%s",
        "INSERT INTO league_reference_fixtures SELECT batch_id,'injected',home_team_id,away_team_id,kickoff,round_id,status,home_goals,away_goals FROM league_reference_fixtures WHERE batch_id=%s LIMIT 1",
    ],
)
def test_published_batches_cannot_be_mutated_or_extended(database, cache, config, statement):
    conn = database[0]
    result = publish(database, cache, config)
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(statement, (result["batch_id"],))
    conn.rollback()
    assert count(conn, "league_reference_fixtures") == 2


def test_whole_batch_is_invisible_before_commit_and_reads_through_real_http(
    database, cache, config, client, monkeypatch
):
    conn, dsn, schema = database

    @contextmanager
    def read_db():
        with closing(psycopg2.connect(dsn)) as other:
            with other.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            yield other

    monkeypatch.setattr("apps.backend.src.routers.league_data.get_db", read_db)
    result = import_season(conn, load_season(cache, config=config))
    assert client.get("/api/league-data/catalog").json()["status"] == "not_connected"
    conn.commit()
    response = client.get(f"/api/league-data/seasons/{result['competition_season_id']}")
    assert response.status_code == 200
    assert response.json()["overview"]["draws"] == 1
    page = client.get(
        f"/api/league-data/seasons/{result['competition_season_id']}/fixtures",
        params={"batch_id": result["batch_id"], "limit": 1},
    )
    assert page.status_code == 200 and page.json()["total"] == 2
    assert page.json()["evidence"]["batchId"] == str(result["batch_id"])


def test_real_cache_roundtrip_when_explicitly_requested(database):
    path = os.environ.get("FQP_LEAGUE_REAL_CACHE")
    if not path:
        pytest.skip("Real-cache smoke is opt-in; fixture regressions remain independent")
    conn = database[0]
    report = import_season(conn, load_season(path))
    conn.commit()
    again = import_season(conn, load_season(path))
    conn.commit()
    data = league_season(conn, report["competition_season_id"])
    assert report["imported_fixtures"] == 380
    assert report["imported_teams"] == 20
    assert again["status"] == "unchanged"
    assert len(data["standings"]["all"]["rows"]) == 20
    assert data["coverage"]["fixtures"] == 380
    print(
        json.dumps(
            {
                "real_cache": path,
                "import": report,
                "repeat_status": again["status"],
                "overview": data["overview"],
                "coverage": data["coverage"],
            },
            ensure_ascii=False,
        )
    )
