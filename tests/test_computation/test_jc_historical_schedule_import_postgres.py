"""Safety contract for the append-only JC historical schedule importer."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

from scripts.jc_historical_schedule_import import (
    CandidateFile,
    CandidateFileError,
    import_schedule_batch,
    load_candidate_file,
)
from scripts.official_history_importer import derive_business_date_from_match_date

ROOT = Path(__file__).resolve().parents[2]
CSV_FIELDS = (
    "source_namespace",
    "lottery_match_id",
    "source_match_date",
    "business_date",
    "official_match_code",
    "league_source_id",
    "league_name",
    "home_source_team_id",
    "home_team",
    "home_full_name",
    "away_source_team_id",
    "away_team",
    "away_full_name",
    "linked_titan_match_id",
    "link_method",
    "titan_match_date",
    "titan_kickoff_local_candidate",
    "titan_timezone",
    "mapped_home_titan_team_id",
    "mapped_away_titan_team_id",
    "mapped_team_ids_match",
    "direct_jc_code_matches",
    "linked_titan_id_unique",
    "readiness",
)


def candidate_row(
    match_id: int = 101,
    day: str = "2022-01-01",
    code: str = "周六001",
    readiness: str = "mapped_team_ids_date_time_candidate",
) -> dict[str, str]:
    return {
        "source_namespace": "titan007.lottery_matches",
        "lottery_match_id": str(match_id),
        "source_match_date": day,
        "business_date": derive_business_date_from_match_date(day, code),
        "official_match_code": code,
        "league_source_id": "36",
        "league_name": "联赛",
        "home_source_team_id": "10",
        "home_team": "甲队",
        "home_full_name": "甲队足球俱乐部",
        "away_source_team_id": "20",
        "away_team": "乙队",
        "away_full_name": "乙队足球俱乐部",
        "linked_titan_match_id": str(match_id + 1000),
        "link_method": "mapped_team_ids",
        "titan_match_date": day,
        "titan_kickoff_local_candidate": f"{day} 16:45",
        "titan_timezone": "Asia/Shanghai",
        "mapped_home_titan_team_id": "10",
        "mapped_away_titan_team_id": "20",
        "mapped_team_ids_match": "true",
        "direct_jc_code_matches": "false",
        "linked_titan_id_unique": "true",
        "readiness": readiness,
    }


def write_candidate_file(tmp_path: Path, rows: list[dict[str, str]]):
    csv_path = tmp_path / "candidates.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    payload = csv_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact": "football-jc-schedule-import-candidate-manifest/v2",
                "cutoff_inclusive": "2026-10-31",
                "candidate_rows": len(rows),
                "csv_sha256": digest,
                "business_date_rule": "official_code_weekday_on_or_before_source_match_date",
                "scope": "JC schedule rows only; no score, result, odds, odds history or statistics columns are included.",
            }
        ),
        encoding="utf-8",
    )
    return load_candidate_file(csv_path, manifest_path, expected_csv_sha256=digest)


@pytest.fixture
def isolated_pg():
    dsn = (
        os.environ.get("FQP_JC_HISTORY_TEST_DSN") or os.environ.get("FQP_HISTORY_TEST_DSN", "")
    ).strip()
    if not dsn:
        pytest.skip("set a disposable loopback PostgreSQL history test DSN")
    params = parse_dsn(dsn)
    assert params.get("host") in {"127.0.0.1", "localhost"}
    assert params.get("dbname", "").startswith("fqp_history_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "jc_history_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            for filename in (
                "01_core_official_schema.sql",
                "32_official_event_season_targets.sql",
                "124_official_event_season_retention.sql",
            ):
                cur.execute((ROOT / "sql" / filename).read_text(encoding="utf-8"))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()


def add_retained_window(conn, start="2022-01-01", end="2022-12-31"):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_event_season_retention (
                   league_name,season_name,season_start_date,season_end_date,
                   selection_reason,boundary_source,source_url,as_of_date
               ) VALUES ('联赛','2022',%s,%s,'verified','sporttery','test://season','2022-01-01')""",
            (start, end),
        )
    conn.commit()


def insert_existing(conn, *, source_id="101", day="2022-01-01", code="周六001"):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches (
                   business_date,official_match_code,source_match_id,league_name,
                   home_team_name,away_team_name,kickoff_time,match_status,raw_json
               ) VALUES (%s,%s,%s,'联赛','旧主队','旧客队',%s,'settled','{"source":"old"}')
               RETURNING id""",
            (day, code, source_id, f"{day} 20:00"),
        )
        match_id = cur.fetchone()[0]
    conn.commit()
    return match_id


def test_candidate_artifact_is_hash_pinned_and_schedule_only(tmp_path):
    artifact = write_candidate_file(tmp_path, [candidate_row()])
    assert artifact.csv_sha256 == hashlib.sha256(artifact.csv_path.read_bytes()).hexdigest()
    assert len(artifact.candidates) == 1

    artifact.manifest_path.write_text(
        artifact.manifest_path.read_text(encoding="utf-8").replace(artifact.csv_sha256, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(CandidateFileError, match="SHA-256"):
        load_candidate_file(
            artifact.csv_path,
            artifact.manifest_path,
            expected_csv_sha256=artifact.csv_sha256,
        )


def test_rewritten_csv_and_manifest_still_need_the_independently_approved_hash(tmp_path):
    artifact = write_candidate_file(tmp_path, [candidate_row()])
    approved_hash = artifact.csv_sha256
    rows = [candidate_row()]
    rows[0]["home_team"] = "被替换的球队"
    with artifact.csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    changed_hash = hashlib.sha256(artifact.csv_path.read_bytes()).hexdigest()
    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    manifest["csv_sha256"] = changed_hash
    artifact.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CandidateFileError, match="approved SHA-256"):
        load_candidate_file(
            artifact.csv_path,
            artifact.manifest_path,
            expected_csv_sha256=approved_hash,
        )


def test_business_date_is_derived_from_weekday_code_for_after_midnight_match(tmp_path):
    artifact = write_candidate_file(
        tmp_path,
        [candidate_row(day="2022-01-04", code="周一001")],
    )
    assert artifact.candidates[0].source_match_date == date(2022, 1, 4)
    assert artifact.candidates[0].business_date == date(2022, 1, 3)


def test_dry_run_rolls_back_and_inserted_rows_keep_unknown_facts(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    artifact = write_candidate_file(tmp_path, [candidate_row()])

    preview = import_schedule_batch(
        isolated_pg, artifact, batch_id="dry-run-001", offset=0, limit=10, apply=False
    )
    assert preview["status"] == "dry_run"
    assert preview["counts"]["planned_insert"] == 1
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0
    isolated_pg.rollback()

    applied = import_schedule_batch(
        isolated_pg, artifact, batch_id="apply-001", offset=0, limit=10, apply=True
    )
    assert applied["counts"]["inserted"] == 1
    with isolated_pg.cursor() as cur:
        cur.execute(
            """SELECT match_status,sale_status,sale_stop_time,source_match_id,
                      raw_json->>'source',raw_json->'backfill'->>'batch_id'
               FROM official_matches WHERE source_match_id='101'"""
        )
        assert cur.fetchone() == (
            "unknown",
            "unknown",
            None,
            "101",
            "titan007_historical_jc_schedule_backfill",
            "apply-001",
        )
        cur.execute("SELECT count(*) FROM official_results")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM official_markets")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM official_odds_snapshots")
        assert cur.fetchone()[0] == 0


def test_apply_requires_independently_approved_artifact_hash(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    artifact = replace(
        write_candidate_file(tmp_path, [candidate_row()]),
        approved_csv_sha256="",
    )

    with pytest.raises(RuntimeError, match="independently approved SHA-256"):
        import_schedule_batch(
            isolated_pg,
            artifact,
            batch_id="missing-pin-001",
            offset=0,
            limit=10,
            apply=True,
        )
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


def test_apply_rejects_forged_candidate_object_with_matching_hash_fields(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    loaded = write_candidate_file(tmp_path, [candidate_row()])
    forged = CandidateFile(
        csv_path=loaded.csv_path,
        manifest_path=loaded.manifest_path,
        csv_sha256=loaded.csv_sha256,
        approved_csv_sha256=loaded.approved_csv_sha256,
        cutoff_inclusive=loaded.cutoff_inclusive,
        candidates=(replace(loaded.candidates[0], home_team="伪造球队"),),
    )

    with pytest.raises(RuntimeError, match="loader-validated"):
        import_schedule_batch(
            isolated_pg,
            forged,
            batch_id="forged-artifact-001",
            offset=0,
            limit=10,
            apply=True,
        )
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("apply", [False, True])
def test_empty_retention_table_fails_closed(isolated_pg, tmp_path, apply):
    artifact = write_candidate_file(tmp_path, [candidate_row()])

    with pytest.raises(RuntimeError, match="retention window.*missing or empty"):
        import_schedule_batch(
            isolated_pg,
            artifact,
            batch_id=f"empty-window-{int(apply)}",
            offset=0,
            limit=10,
            apply=apply,
        )
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("apply", [False, True])
def test_missing_retention_tables_fail_closed(isolated_pg, tmp_path, apply):
    with isolated_pg.cursor() as cur:
        cur.execute("DROP TABLE official_event_season_retention CASCADE")
        cur.execute("DROP TABLE official_event_season_targets CASCADE")
    isolated_pg.commit()
    artifact = write_candidate_file(tmp_path, [candidate_row()])

    with pytest.raises(RuntimeError, match="retention window.*missing or empty"):
        import_schedule_batch(
            isolated_pg,
            artifact,
            batch_id="missing-window-001",
            offset=0,
            limit=10,
            apply=apply,
        )
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


def test_conflicts_are_isolated_and_existing_rows_are_never_updated(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    existing_id = insert_existing(isolated_pg)
    official_key_id = insert_existing(isolated_pg, source_id="999", code="周六003")
    present_artifact = write_candidate_file(tmp_path, [candidate_row()])
    present_result = import_schedule_batch(
        isolated_pg,
        present_artifact,
        batch_id="present-001",
        offset=0,
        limit=10,
        apply=True,
    )
    assert present_result["counts"]["already_present"] == 1, present_result

    rows = [
        candidate_row(match_id=101, code="周六002"),
        candidate_row(match_id=103, code="周六003"),
    ]
    artifact = write_candidate_file(tmp_path, rows)

    result = import_schedule_batch(
        isolated_pg, artifact, batch_id="conflicts-001", offset=0, limit=10, apply=True
    )
    assert result["counts"]["already_present"] == 0
    assert result["counts"]["source_id_conflict"] == 1
    assert result["counts"]["official_key_conflict"] == 1
    assert result["counts"]["inserted"] == 0
    with isolated_pg.cursor() as cur:
        cur.execute(
            "SELECT id,home_team_name,match_status,raw_json->>'source' FROM official_matches"
        )
        assert cur.fetchall() == [
            (existing_id, "旧主队", "settled", "old"),
            (official_key_id, "旧主队", "settled", "old"),
        ]


def test_retention_miss_is_reported_without_attempted_insert(isolated_pg, tmp_path):
    add_retained_window(isolated_pg, start="2023-01-01", end="2023-12-31")
    artifact = write_candidate_file(tmp_path, [candidate_row()])

    result = import_schedule_batch(
        isolated_pg, artifact, batch_id="retention-001", offset=0, limit=10, apply=True
    )
    assert result["counts"]["outside_retention_window"] == 1
    assert result["counts"]["inserted"] == 0
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


def test_failed_insert_rolls_back_entire_batch(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    artifact = write_candidate_file(
        tmp_path,
        [candidate_row(), candidate_row(match_id=102, day="2022-01-02", code="周日001")],
    )
    with isolated_pg.cursor() as cur:
        cur.execute(
            """CREATE FUNCTION reject_second_schedule() RETURNS trigger AS $$
               BEGIN
                   IF NEW.official_match_code='周日001' THEN
                       RAISE EXCEPTION 'test failure';
                   END IF;
                   RETURN NEW;
               END $$ LANGUAGE plpgsql"""
        )
        cur.execute(
            "CREATE TRIGGER reject_second_schedule BEFORE INSERT ON official_matches "
            "FOR EACH ROW EXECUTE FUNCTION reject_second_schedule()"
        )
    isolated_pg.commit()

    with pytest.raises(psycopg2.Error, match="test failure"):
        import_schedule_batch(
            isolated_pg, artifact, batch_id="rollback-001", offset=0, limit=10, apply=True
        )
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0


def test_candidate_manifest_and_csv_validate_against_pinned_hash(tmp_path):
    artifact = write_candidate_file(tmp_path, [candidate_row()])
    assert artifact.cutoff_inclusive == date(2026, 10, 31)
    assert artifact.csv_sha256 == artifact.approved_csv_sha256
    assert len(artifact.candidates) == 1


def test_fixed_candidate_first_batch_dry_run_is_read_only(isolated_pg, tmp_path):
    add_retained_window(isolated_pg)
    artifact = write_candidate_file(
        tmp_path,
        [
            candidate_row(match_id=101),
            candidate_row(match_id=102, day="2022-01-02", code="周日001"),
        ],
    )
    result = import_schedule_batch(
        isolated_pg, artifact, batch_id="fixed-preview-001", offset=0, limit=100, apply=False
    )
    assert result["counts"]["planned_insert"] == 2
    assert result["counts"]["inserted"] == 0
    with isolated_pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone()[0] == 0
