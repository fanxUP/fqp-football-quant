"""Real PostgreSQL activation failures/concurrency, using only disposable local data."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

import numpy as np
import psycopg2
import pytest
from psycopg2 import sql
from sklearn.tree import DecisionTreeClassifier

from scripts import shadow_training
from scripts.feature_schema import FEATURE_SCHEMA_VERSION
from tests.test_computation.test_shadow_training_atomicity import (
    fitted,
    load_probabilities,
    snapshot,
    train,
)


@pytest.fixture
def shadow_database(tmp_path):
    dsn = os.environ.get("FQP_AUDIT_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("set FQP_AUDIT_TEST_DATABASE_URL to a disposable local audit database")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.lstrip("/").startswith("fqp_audit_test_")
    schema = f"shadow_{uuid4().hex}"

    def connection():
        conn = psycopg2.connect(dsn, options="-c statement_timeout=5000 -c lock_timeout=3000")
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        conn.commit()
        return conn

    conn = connection()
    root = Path(__file__).resolve().parents[2]
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("official_matches", "official_markets", "official_odds_snapshots"):
            cur.execute(
                sql.SQL("CREATE TABLE {} (id BIGINT PRIMARY KEY)").format(sql.Identifier(table))
            )
        cur.execute((root / "sql/03_model_research_schema.sql").read_text())
        cur.execute(
            """INSERT INTO model_versions(model_name, model_type, version, parameters_json,
                   feature_set_version, description, is_active)
               VALUES ('logistic_shadow', 'classifier', 'seed', '{}', 'fixture-v1', 'seed', true)"""
        )
    conn.commit()
    # Establish a trained baseline through the same production activation path.
    train(tmp_path, conn, store_profile=None)
    with conn.cursor() as cur:
        cur.execute("SELECT id, parameters_json FROM model_versions WHERE is_active")
        old_id, old_parameters = cur.fetchone()
        cur.execute(
            "CREATE TABLE historical_prediction (model_version_id BIGINT REFERENCES model_versions(id))"
        )
        cur.execute("INSERT INTO historical_prediction VALUES (%s)", (old_id,))
    conn.commit()
    old_path = tmp_path / old_parameters["artifact_path"]
    try:
        yield conn, connection, old_id, old_parameters, old_path
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def current(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, parameters_json FROM model_versions WHERE is_active ORDER BY id")
        return cur.fetchall()


@pytest.mark.parametrize("failure", ["insert", "commit", "interrupt"])
def test_activation_failures_preserve_previous_version(shadow_database, tmp_path, failure):
    conn, _, old_id, old_parameters, old_path = shadow_database
    old_bytes = old_path.read_bytes()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM model_versions")
        count_before = cur.fetchone()[0]
        if failure != "interrupt":
            cur.execute("""CREATE FUNCTION fail_activation() RETURNS trigger LANGUAGE plpgsql AS $$
                           BEGIN RAISE EXCEPTION 'injected activation failure'; END; $$""")
            if failure == "insert":
                cur.execute(
                    "CREATE TRIGGER fail_new_version BEFORE INSERT ON model_versions FOR EACH ROW EXECUTE FUNCTION fail_activation()"
                )
            else:
                cur.execute(
                    "CREATE CONSTRAINT TRIGGER fail_commit AFTER INSERT ON model_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_activation()"
                )
    conn.commit()
    if failure == "interrupt":

        def store(*_args):
            raise KeyboardInterrupt()
    else:
        store = None
    with pytest.raises((psycopg2.Error, KeyboardInterrupt)):
        train(tmp_path, conn, store_profile=store)
    assert current(conn) == [(old_id, old_parameters)]
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM model_versions")
        assert cur.fetchone()[0] == count_before
    assert old_path.read_bytes() == old_bytes
    assert (
        load_probabilities(old_parameters | {"artifact_path": str(old_path)}, snapshot())
        is not None
    )
    assert len(list(tmp_path.glob("*.joblib"))) == 2  # One safely unreferenced new file.


def test_new_version_retains_historical_prediction_and_can_reactivate(shadow_database, tmp_path):
    conn, _, old_id, old_parameters, old_path = shadow_database
    old_bytes = old_path.read_bytes()
    different_classifier = DecisionTreeClassifier().fit(np.ones((150, 3)), np.full(150, 2))
    train(
        tmp_path,
        conn,
        store_profile=None,
        fit_model=lambda *_: (different_classifier, fitted()[1]),
    )
    [(new_id, new_parameters)] = current(conn)
    assert new_id != old_id
    assert new_parameters["artifact_path"] != old_parameters["artifact_path"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v.id,v.parameters_json FROM historical_prediction p JOIN model_versions v ON v.id=p.model_version_id"
        )
        assert cur.fetchone() == (old_id, old_parameters)
        cur.execute(
            "SELECT model_type,feature_set_version,description FROM model_versions WHERE id=%s",
            (new_id,),
        )
        assert cur.fetchone() == ("classifier", FEATURE_SCHEMA_VERSION, "seed")
        cur.execute("UPDATE model_versions SET is_active=false WHERE id=%s", (new_id,))
        cur.execute("UPDATE model_versions SET is_active=true WHERE id=%s", (old_id,))
    conn.commit()
    assert current(conn) == [(old_id, old_parameters)]
    assert old_path.read_bytes() == old_bytes
    probabilities = []
    for parameters in (old_parameters, new_parameters):
        path = tmp_path / parameters["artifact_path"]
        probabilities.append(
            load_probabilities(parameters | {"artifact_path": str(path)}, snapshot())
        )
    assert probabilities[0] is not None
    assert probabilities[1] == {"0": 0.0, "1": 0.0, "3": 1.0}
    assert probabilities[0] != probabilities[1]


def test_concurrent_training_uses_distinct_files_and_one_active_version(shadow_database, tmp_path):
    conn, connect, old_id, old_parameters, old_path = shadow_database
    barrier = Barrier(2)

    def store(connection, parameters, dates):
        barrier.wait(timeout=5)
        shadow_training.store_active_shadow_profile(
            connection, parameters, dates, model_name="logistic_shadow", missing_message="missing"
        )

    def run():
        connection = connect()
        try:
            return train(tmp_path, connection, store_profile=store)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))
    assert all(result["status"] == "ok" for result in results)
    assert len(current(conn)) == 1
    assert current(conn)[0][0] != old_id
    with conn.cursor() as cur:
        cur.execute("SELECT parameters_json FROM model_versions WHERE version<>'seed'")
        parameters = [row[0] for row in cur.fetchall()]
    assert len(parameters) == 3
    assert len({p["artifact_path"] for p in parameters}) == 3
    assert len({p["artifact_version"] for p in parameters}) == 3
    assert old_path.is_file()
    assert old_parameters in parameters


def test_process_exit_before_commit_rolls_back_activation(shadow_database, tmp_path):
    conn, _, old_id, old_parameters, old_path = shadow_database
    # A real child exit closes its DB transaction, unlike a mocked commit exception.
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
    conn.commit()
    code = """
import os, sys
import psycopg2
from psycopg2 import sql
from tests.test_computation.test_shadow_training_atomicity import train
class ExitBeforeCommit:
    autocommit = False
    def __init__(self, conn): self.conn = conn
    def cursor(self): return self.conn.cursor()
    def rollback(self): self.conn.rollback()
    def commit(self): os._exit(86)
from pathlib import Path
conn=psycopg2.connect(os.environ['FQP_AUDIT_TEST_DATABASE_URL'])
with conn.cursor() as cur:
    cur.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(sys.argv[1])))
conn.commit()
train(Path(sys.argv[2]), ExitBeforeCommit(conn), store_profile=None)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, schema, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 86, child.stderr
    assert current(conn) == [(old_id, old_parameters)]
    assert old_path.is_file()
    assert len(list(tmp_path.glob("*.joblib"))) == 2


def test_missing_active_seed_cannot_publish_a_version(shadow_database, tmp_path):
    conn, _, _, _, old_path = shadow_database
    with conn.cursor() as cur:
        cur.execute("UPDATE model_versions SET is_active=false")
    conn.commit()
    with pytest.raises(RuntimeError, match="missing shadow model"):
        train(tmp_path, conn, store_profile=None)
    assert current(conn) == []
    assert old_path.is_file()


def test_lost_commit_acknowledgement_keeps_the_committed_file(shadow_database, tmp_path):
    conn, _, old_id, _, old_path = shadow_database

    class LostAcknowledgement:
        autocommit = False

        def cursor(self):
            return conn.cursor()

        def commit(self):
            conn.commit()
            raise psycopg2.OperationalError("lost COMMIT acknowledgement")

        def rollback(self):
            conn.rollback()

    with pytest.raises(psycopg2.OperationalError, match="lost COMMIT"):
        train(tmp_path, LostAcknowledgement(), store_profile=None)
    [(new_id, parameters)] = current(conn)
    assert new_id != old_id
    path = tmp_path / parameters["artifact_path"]
    assert path.is_file() and old_path.is_file()
    assert load_probabilities(parameters | {"artifact_path": str(path)}, snapshot()) is not None
