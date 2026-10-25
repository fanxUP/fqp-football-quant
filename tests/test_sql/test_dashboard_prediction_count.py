"""Exercise the homepage count on PostgreSQL with connection-local fixtures."""

import os
from contextlib import closing

import psycopg2
import pytest

from scripts.prediction_statistics import compute_prediction_count


@pytest.mark.integration
def test_prediction_count_preserves_global_eligibility_without_evidence_joins():
    dsn = os.getenv("FQP_AUDIT_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly configured isolated test database")
    database = psycopg2.extensions.parse_dsn(dsn).get("dbname", "")
    assert database.endswith("_test") or database.startswith("fqp_audit_test_"), (
        "Only run synthetic fixtures in a test database"
    )
    with closing(psycopg2.connect(dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE model_versions (id bigint PRIMARY KEY)")
            cur.execute(
                "CREATE TEMP TABLE official_matches (id bigint PRIMARY KEY, kickoff_time timestamp)"
            )
            cur.execute("""CREATE TEMP TABLE model_predictions (
                id bigint PRIMARY KEY, match_id bigint, model_version_id bigint,
                predict_time timestamp, validation_status text, ev numeric)""")

            assert compute_prediction_count(conn)["total"] == 0
            cur.execute("INSERT INTO model_versions VALUES (1), (2)")
            cur.execute("INSERT INTO official_matches VALUES (10, '2026-10-16 20:00')")
            cur.execute("""INSERT INTO model_predictions VALUES
                    (1,10,1,'2026-10-16 19:00','valid',-1),
                    (2,10,2,'2026-10-16 19:00','valid',0),
                    (3,10,1,'2026-10-16 19:00','valid',1),
                    (4,10,1,'2026-10-16 20:00','valid',1),
                    (5,10,1,'2026-10-16 21:00','valid',1),
                    (6,10,1,'2026-10-16 19:00','rejected',1),
                    (7,10,99,'2026-10-16 19:00','valid',1),
                    (8,99,1,'2026-10-16 19:00','valid',1),
                    (9,10,1,NULL,'valid',1),
                    (10,10,1,'2026-10-16 19:00',NULL,1)""")
            assert compute_prediction_count(conn)["total"] == 3
            cur.execute("DELETE FROM model_predictions WHERE id = 2")
            assert compute_prediction_count(conn)["total"] == 2
            cur.execute("UPDATE official_matches SET kickoff_time = '2026-10-16 18:00'")
            assert compute_prediction_count(conn)["total"] == 0
