"""Local-only migration, real published group cutoffs and saved plan flow."""

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from psycopg2.errors import RaiseException

from apps.backend.src.routers import pool
from scripts.business_time import business_now
from scripts.model_prediction_run_identity import content_sha256
from scripts.model_prediction_run_loader import load_pool_prediction_groups
from scripts.model_prediction_run_storage import (
    create_prediction_run,
    finalize_prediction_run,
    store_prediction_group,
)
from scripts.official_storage import store_pool_issue, store_pool_issue_matches
from tests.test_computation.test_prediction_run_postgres import (
    isolated_database,  # noqa: F401, F811
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database(isolated_database):  # noqa: F811
    conn, schema = isolated_database
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute("ALTER TABLE model_versions ADD COLUMN is_active BOOLEAN DEFAULT true")
        cur.execute((ROOT / "sql/05_pool_reports_ops_schema.sql").read_text())
        cur.execute((ROOT / "sql/117_pool_identity_and_snapshots.sql").read_text())
    conn.commit()
    return conn, schema


def publish(conn, *, match_id, model_id, when=None, vector=(0.4, 0.35, 0.25), independent=True):
    identity = {
        "model_version_id": model_id,
        "model_name": "pool-test",
        "provenance_status": "complete",
        "parameters_sha256": "a" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 1,
            "sha256": "a" * 64,
        },
    }
    run = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run,
        ai_job_run_id=None,
        release_id="pool-test",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[identity],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
    )
    when = (
        when
        or (business_now() - timedelta(hours=1)).replace(tzinfo=None, microsecond=0).isoformat()
    )
    metadata = {
        "match_id": match_id,
        "model_version_id": model_id,
        "play_type": "spf",
        "predict_time": when,
        "expected_options": ["3", "1", "0"],
        "artifact_identity": identity,
        "provenance_status": "complete",
    }
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_id,
            "play_type": "spf",
            "predict_time": when,
            "option_code": o,
            "model_probability": p,
            "market_probability": p,
            "odds_snapshot_id": 1,
            "feature_snapshot_id": 77,
            "break_even_probability": p,
            "market_edge": 0,
            "breakeven_edge": 0,
            "ev": 0,
            "validation_status": "valid",
            "calculation_version": "pool-test",
            "uncertainty_reason": {"model_independent": independent},
        }
        for o, p in zip("310", vector, strict=True)
    ]
    group = store_prediction_group(conn, run_id=run, metadata=metadata, predictions=predictions)
    finalize_prediction_run(
        conn,
        run_id=run,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )
    conn.commit()
    return group


def seed_match(conn, name="A"):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('pool-test') RETURNING id")
        model = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO official_matches(home_team_name,away_team_name,kickoff_time) VALUES (%s,'B',%s) RETURNING id",
            (name, (business_now() + timedelta(days=2)).replace(tzinfo=None)),
        )
        match = cur.fetchone()[0]
    conn.commit()
    return match, model


def test_asof_uses_publication_not_backdated_predict_time_and_versions_are_not_votes(database):
    conn, _ = database
    mid, model = seed_match(conn)
    older = publish(conn, match_id=mid, model_id=model)
    cutoff = datetime.now(UTC)
    newer = publish(conn, match_id=mid, model_id=model, vector=(0.5, 0.3, 0.2))
    past = load_pool_prediction_groups(conn, cutoffs={mid: cutoff})
    assert len(past) == 1 and past[0]["group_id"] == str(older)
    assert past[0]["eligible"] is True
    latest = load_pool_prediction_groups(
        conn, cutoffs={mid: datetime.now(UTC) + timedelta(seconds=1)}
    )
    assert latest[0]["group_id"] == str(newer)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('pool-test') RETURNING id")
        version2 = cur.fetchone()[0]
    publish(conn, match_id=mid, model_id=version2, vector=(0.6, 0.2, 0.2))
    current = pool._read_pool_model_consensus(
        conn, {mid: datetime.now(UTC) + timedelta(seconds=1)}, historical=False
    )
    assert current[mid]["model_count"] == 1
    assert current[mid]["vector"] == {"3": 0.6, "1": 0.2, "0": 0.2}
    with conn.cursor() as cur:
        cur.execute("UPDATE model_versions SET is_active=false")
    assert not load_pool_prediction_groups(
        conn, cutoffs={mid: datetime.now(UTC) + timedelta(seconds=1)}
    )
    assert load_pool_prediction_groups(
        conn, cutoffs={mid: datetime.now(UTC) + timedelta(seconds=1)}, historical=True
    )


def test_unbound_and_market_only_vectors_are_not_silently_actionable(database):
    conn, _ = database
    mid, model = seed_match(conn)
    publish(conn, match_id=mid, model_id=model, independent=False)
    group = load_pool_prediction_groups(
        conn, cutoffs={mid: datetime.now(UTC) + timedelta(seconds=1)}
    )[0]
    assert group["status"] == "complete" and group["eligible"] is False
    assert (
        pool._read_pool_model_consensus(
            conn, {mid: datetime.now(UTC) + timedelta(seconds=1)}, historical=False
        )[mid]["vector"]
        is None
    )


def test_storage_separates_game_issue_and_never_accepts_external_fk_collision(database):
    conn, _ = database
    mid, _ = seed_match(conn)
    raw = {"saleEndTime": "2026-10-28 20:00"}
    sf = store_pool_issue(conn, "26100", "t14c", None, "2026-10-28 20:00", 14, "selling", raw)
    rx = store_pool_issue(conn, "26100", "r9", None, "2026-10-28 21:00", 14, "selling", raw)
    assert sf != rx
    store_pool_issue_matches(
        conn,
        sf,
        [
            {
                "match_order": 1,
                "match_id": mid,
                "source_match_id": str(mid),
                "home_team_name": "Different",
                "away_team_name": "B",
                "kickoff_time": "2026-10-28 03:00",
            }
        ],
    )
    with conn.cursor() as cur:
        cur.execute("SELECT match_id,source_match_id FROM football_pool_issue_matches")
        assert cur.fetchone() == (None, str(mid))
        cur.execute("SELECT issue_no,game_type FROM football_pool_issues ORDER BY id")
        assert cur.fetchall() == [("26100", "t14c"), ("26100", "r9")]


def test_ambiguous_exact_identity_stays_unbound(database):
    conn, _ = database
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO official_matches(home_team_name,away_team_name,kickoff_time) VALUES ('A','B','2026-10-28 03:00'),('A','B','2026-10-28 03:00')"
        )
    issue = store_pool_issue(conn, "26101", "t14c", None, None, 14, "unknown", {})
    store_pool_issue_matches(
        conn,
        issue,
        [
            {
                "match_order": 1,
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2026-10-28 03:00",
            }
        ],
    )
    with conn.cursor() as cur:
        cur.execute("SELECT match_id FROM football_pool_issue_matches")
        assert cur.fetchone() == (None,)


def test_save_read_full_snapshot_immutable_and_stale_detection(database, monkeypatch):
    conn, _ = database
    mid, model = seed_match(conn)
    raw = {"saleEndTime": (business_now() + timedelta(days=1)).isoformat()}
    issue = store_pool_issue(conn, "26100", "t14c", None, raw["saleEndTime"], 14, "selling", raw)
    conn.commit()
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    snapshot = {
        "schema_version": "football-pool/v2",
        "input_hash": "a" * 64,
        "issue": {"id": issue},
        "parameters": {
            "budget": 256,
            "strategy": "balanced",
            "issue_id": str(issue),
            "pinned_orders": [],
            "excluded_orders": [],
        },
        "full_combinations": {
            "count": 128,
            "total_cost": 256,
            "combinations": [{"selections": ["3"] * 14}] * 128,
        },
        "rx9": {"combinations_count": 0},
        "probabilities": {"hit14_prob": 0.01, "hit13_or_more_prob": 0.1},
    }
    monkeypatch.setattr(pool, "_analysis", lambda *a, **k: snapshot.copy())
    body = pool.SavePoolPlan(**snapshot["parameters"], input_hash="a" * 64)
    first = pool.save_pool_plan(body)
    assert pool.save_pool_plan(body) == first
    restored = pool.read_pool_plan(first["id"])
    assert restored["stale"] is False
    assert len(restored["snapshot"]["full_combinations"]["combinations"]) == 128
    conn.rollback()
    with pytest.raises(RaiseException, match="immutable"):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE football_pool_combinations SET total_cost=0 WHERE id=%s", (first["id"],)
            )
    conn.rollback()
    monkeypatch.setattr(pool, "_analysis", lambda *a, **k: {"input_hash": "b" * 64})
    assert pool.read_pool_plan(first["id"])["stale"] is True


def test_migration_retains_ids_references_and_audits_estimated_cutoff(isolated_database):  # noqa: F811
    conn, _ = isolated_database
    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/05_pool_reports_ops_schema.sql").read_text())
        cur.execute(
            "INSERT INTO football_pool_issues(issue_no,game_type,sale_stop_time,raw_json) VALUES ('26100','t14c','2026-10-27 20:00','{\"estimateDrawTime\":\"2026-10-27 20:00\"}') RETURNING id"
        )
        iid = cur.fetchone()[0]
        cur.execute("INSERT INTO football_pool_combinations(issue_id) VALUES (%s)", (iid,))
        cur.execute((ROOT / "sql/117_pool_identity_and_snapshots.sql").read_text())
        cur.execute((ROOT / "sql/117_pool_identity_and_snapshots.sql").read_text())
        cur.execute("SELECT id,sale_stop_time,raw_json FROM football_pool_issues")
        row = cur.fetchone()
        assert row[0] == iid and row[1] is None
        assert row[2]["_pool_correction_v1"]["old_sale_stop_time"] is not None
        cur.execute("SELECT issue_id FROM football_pool_combinations")
        assert cur.fetchone()[0] == iid


def seed_catalogue(conn, predictions=10):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('pool-test') RETURNING id")
        model = cur.fetchone()[0]
    kickoff = (business_now() + timedelta(days=2)).replace(tzinfo=None, microsecond=0).isoformat()
    fixtures = []
    for order in range(1, 15):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO official_matches(home_team_name,away_team_name,kickoff_time) VALUES (%s,%s,%s) RETURNING id",
                (f"H{order}", f"A{order}", kickoff),
            )
            mid = cur.fetchone()[0]
        fixtures.append(
            {
                "match_order": order,
                "home_team_name": f"H{order}",
                "away_team_name": f"A{order}",
                "kickoff_time": kickoff,
            }
        )
        if order <= predictions:
            publish(conn, match_id=mid, model_id=model)
    raw = {"saleEndTime": (business_now() + timedelta(days=1)).replace(microsecond=0).isoformat()}
    for game in ["t14c", "r9"]:
        iid = store_pool_issue(conn, "26111", game, None, raw["saleEndTime"], 14, "selling", raw)
        store_pool_issue_matches(conn, iid, fixtures)
    conn.commit()


def test_real_partial_analysis_save_and_export_reproduce_original_snapshot(database, monkeypatch):
    conn, _ = database
    seed_catalogue(conn)
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    current = pool.run_pool_analysis(budget=256, strategy="balanced")
    assert current["rx9_status"] == "ready" and current["sf14_status"] == "missing_predictions"
    assert current["rx9"]["combinations_count"] == 128
    assert [m["match_order"] for m in current["rx9"]["selected_matches"]] == list(range(1, 10))
    saved = pool.save_pool_plan(
        pool.SavePoolPlan(**current["parameters"], input_hash=current["input_hash"])
    )
    restored = pool.read_pool_plan(saved["id"])
    assert restored["stale"] is False
    assert restored["snapshot"]["rx9"]["combinations"] == current["rx9"]["combinations"]
    assert restored["snapshot"]["snapshot_hash"] == pool._snapshot_digest(restored["snapshot"])
    with conn.cursor() as cur:
        cur.execute(
            "SELECT total_units,total_cost,expected_prize,expected_value FROM football_pool_combinations"
        )
        assert cur.fetchone() == (128, 256, None, None)


def test_repeatable_read_retains_model_eligibility_across_collector_commit(database, monkeypatch):
    import os

    import psycopg2
    from psycopg2 import sql

    conn, schema = database
    seed_catalogue(conn, predictions=1)
    changed = False

    class Cursor:
        def __enter__(self):
            self.cur = conn.cursor()
            return self

        def __exit__(self, *_):
            self.cur.close()

        def execute(self, query, params=None):
            self.query = query
            return self.cur.execute(query, params)

        def fetchall(self):
            nonlocal changed
            rows = self.cur.fetchall()
            if "FROM football_pool_issues WHERE" in self.query and not changed:
                other = psycopg2.connect(os.environ["FQP_P106_TEST_DATABASE_URL"])
                with other.cursor() as cur:
                    cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                    cur.execute("UPDATE model_versions SET is_active=false")
                other.commit()
                other.close()
                changed = True
            return rows

    class Connection:
        def rollback(self):
            return conn.rollback()

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(Connection()))
    data = pool.run_pool_analysis(budget=256, strategy="balanced")
    assert changed and data["matches"][0]["prob_home"] == 0.4
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT is_active FROM model_versions")
        assert cur.fetchone()[0] is False


@pytest.mark.parametrize("prefer_merge_join", [False, True])
@pytest.mark.parametrize("analyze_options", [False, True])
def test_batch_group_reads_do_not_scan_unbound_prediction_archive(
    database, prefer_merge_join, analyze_options
):
    conn, _ = database
    mid, model = seed_match(conn)
    publish(conn, match_id=mid, model_id=model)
    for _ in range(150):
        publish(conn, match_id=mid, model_id=model)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO model_predictions(match_id,model_version_id,predict_time,play_type,option_code,model_probability)
            SELECT %s,%s,'2020-01-01'::timestamp+n*interval '1 second','spf','3',.4
            FROM generate_series(1,100000) n""",
            (mid, model),
        )
        cur.execute("ANALYZE model_predictions")
        cur.execute("ANALYZE model_prediction_groups")
        cur.execute("ANALYZE model_prediction_runs")
        cur.execute("ANALYZE model_versions")
        if analyze_options:
            cur.execute("ANALYZE model_prediction_group_options")
    conn.commit()
    queries = []

    class Cursor:
        def __enter__(self):
            self.cur = conn.cursor()
            return self

        def __exit__(self, *_):
            self.cur.close()

        def execute(self, q, p):
            queries.append((q, p))
            self.cur.execute(q, p)

        def fetchall(self):
            return self.cur.fetchall()

    class Connection:
        def cursor(self):
            return Cursor()

    actual = load_pool_prediction_groups(
        Connection(), cutoffs={mid: datetime.now(UTC) + timedelta(seconds=1)}
    )
    assert actual[0]["status"] == "complete"
    assert len(queries) == 2
    with conn.cursor() as cur:
        if prefer_merge_join:
            # Exercise another legal cost choice without depending on ANALYZE's
            # random sample or the machine's relative index/merge costs.
            cur.execute("SET LOCAL enable_nestloop = off")
            cur.execute("SET LOCAL enable_hashjoin = off")
        cur.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + queries[1][0], queries[1][1])
        plan = cur.fetchone()[0][0]
        if prefer_merge_join:
            cur.execute("SET LOCAL enable_nestloop = on")
            cur.execute("SET LOCAL enable_hashjoin = on")
        cur.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + queries[0][0], queries[0][1])
        group_plan = cur.fetchone()[0][0]

    def work(node):
        n = (
            (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node["Actual Loops"]
            if node.get("Relation Name") == "model_predictions"
            else 0
        )
        return n + sum(work(child) for child in node.get("Plans", []))

    # Keep the actual plan in captured output when a different planner strategy
    # exceeds the work bound; row counts alone do not identify the access path.
    print({"prediction_option_plan": plan})
    assert work(plan["Plan"]) <= 3, plan

    def group_work(node):
        n = (
            (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node["Actual Loops"]
            if node.get("Relation Name") == "model_prediction_groups"
            else 0
        )
        return n + sum(group_work(child) for child in node.get("Plans", []))

    assert group_work(group_plan["Plan"]) < 20
    print(
        {
            "legacy_archive_rows": 100000,
            "option_rows_examined": work(plan["Plan"]),
            "option_query_execution_ms": plan["Execution Time"],
        }
    )


def test_predict_time_after_stop_before_kickoff_is_excluded_without_losing_older_group(database):
    conn, _ = database
    mid, model = seed_match(conn)
    old = publish(conn, match_id=mid, model_id=model)
    stop = business_now() + timedelta(minutes=1)
    publish(
        conn,
        match_id=mid,
        model_id=model,
        when=(stop + timedelta(minutes=1)).replace(tzinfo=None, microsecond=0).isoformat(),
        vector=(0.6, 0.2, 0.2),
    )
    groups = load_pool_prediction_groups(conn, cutoffs={mid: stop})
    assert len(groups) == 1 and groups[0]["group_id"] == str(old)


def test_snapshot_digest_covers_full_sf14_output(database, monkeypatch):
    conn, _ = database
    seed_catalogue(conn, predictions=14)
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    analysis = pool.run_pool_analysis(budget=2, strategy="balanced")
    saved = pool.save_pool_plan(
        pool.SavePoolPlan(**analysis["parameters"], input_hash=analysis["input_hash"])
    )
    snapshot = pool.read_pool_plan(saved["id"])["snapshot"]
    snapshot["full_combinations"]["combinations"][0]["selections"][0] = "0"
    assert snapshot["snapshot_hash"] != pool._snapshot_digest(snapshot)


def test_issue_list_counts_fixtures_without_resolving_all_archived_matches(database, monkeypatch):
    conn, _ = database
    seed_catalogue(conn, predictions=0)
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    issues = pool.list_pool_issues()["issues"]
    assert len(issues) == 2
    assert all(i["stored_matches"] == 14 for i in issues)


def test_legacy_cross_game_raw_payload_stays_unverified_until_typed_collection(
    database, monkeypatch
):
    conn, _ = database
    seed_catalogue(conn, predictions=14)
    with conn.cursor() as cur:
        cur.execute("UPDATE football_pool_issues SET source_game_type=NULL WHERE game_type='t14c'")
    conn.commit()
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    result = pool.run_pool_analysis(budget=2, strategy="balanced")
    assert result["sf14_status"] == "identity_pending"
    assert result["full_combinations"]["count"] == 0
    assert result["rx9_status"] == "ready"
