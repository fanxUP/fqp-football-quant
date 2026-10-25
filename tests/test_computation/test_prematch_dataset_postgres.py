"""Real SQL regression on the existing explicitly isolated P106 test fixture."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from scripts import prematch_feature_dataset
from scripts.feature_schema import CURRENT_SNAPSHOT_VERSION, FEATURE_COLUMNS
from scripts.prematch_feature_dataset import load_settled_pre_kickoff_dataset
from tests.test_computation import test_prediction_run_postgres as run_tests

isolated_database = run_tests.isolated_database

CUTOFF = datetime(2026, 2, 1)


@pytest.fixture
def dataset_db(isolated_database):
    conn, _ = isolated_database
    with conn.cursor() as cur:
        numeric_columns = ", ".join(f"{column} DOUBLE PRECISION" for column in FEATURE_COLUMNS)
        cur.execute(f"""CREATE TABLE match_feature_snapshots (
            id BIGSERIAL PRIMARY KEY, match_id BIGINT, snapshot_time TIMESTAMP,
            feature_version TEXT, {numeric_columns}
        )""")
    return conn


def seed(conn, count):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches (id,kickoff_time,match_status)
            SELECT i, TIMESTAMP '2026-01-01' + i * INTERVAL '1 minute', 'settled'
            FROM generate_series(1,%s) i""",
            (count,),
        )
        cur.execute("""INSERT INTO official_results
            (match_id,official_publish_time,full_home_goals,full_away_goals,result_status)
            SELECT id,kickoff_time + INTERVAL '2 hours',1,0,'final' FROM official_matches""")
        cur.execute(
            """INSERT INTO match_feature_snapshots
            (match_id,snapshot_time,feature_version,home_rest_days)
            SELECT id,kickoff_time - INTERVAL '1 hour',%s,id FROM official_matches""",
            (CURRENT_SNAPSHOT_VERSION,),
        )


def test_latest_five_thousand_matches_reach_training_in_chronological_order(
    dataset_db, monkeypatch
):
    seed(dataset_db, 5002)
    monkeypatch.setattr(prematch_feature_dataset, "business_now_naive", lambda: CUTOFF)
    features, labels, dates = load_settled_pre_kickoff_dataset(dataset_db)
    assert features[:, FEATURE_COLUMNS.index("home_rest_days")].tolist() == list(range(3, 5003))
    assert labels.tolist() == [2] * 5000
    assert dates == sorted(dates)


def test_invalid_or_unavailable_results_are_excluded_before_recent_limit(dataset_db):
    seed(dataset_db, 8)
    with dataset_db.cursor() as cur:
        cur.execute("UPDATE official_results SET full_home_goals=NULL WHERE match_id=3")
        cur.execute("UPDATE official_results SET full_away_goals=-1 WHERE match_id=4")
        cur.execute("UPDATE official_results SET official_publish_time=NULL WHERE match_id=5")
        cur.execute(
            "UPDATE official_results SET official_publish_time=%s WHERE match_id=6", (CUTOFF,)
        )
        cur.execute("UPDATE official_results SET result_status='pending' WHERE match_id=7")
        cur.execute("UPDATE official_matches SET kickoff_time=%s WHERE id=8", (CUTOFF,))
    features, _, _ = load_settled_pre_kickoff_dataset(dataset_db, cutoff_at=CUTOFF, max_matches=2)
    assert features[:, FEATURE_COLUMNS.index("home_rest_days")].tolist() == [1, 2]


def test_latest_compatible_prematch_snapshot_wins_with_stable_tie_break(dataset_db):
    seed(dataset_db, 1)
    with dataset_db.cursor() as cur:
        for minutes, version, marker in (
            (-30, CURRENT_SNAPSHOT_VERSION, 2),
            (-30, CURRENT_SNAPSHOT_VERSION, 3),
            (-15, "v4_observed_form", 4),
            (0, CURRENT_SNAPSHOT_VERSION, 5),
        ):
            cur.execute(
                """INSERT INTO match_feature_snapshots
                (match_id,snapshot_time,feature_version,home_rest_days)
                SELECT id,kickoff_time + %s * INTERVAL '1 minute',%s,%s FROM official_matches""",
                (minutes, version, marker),
            )
    features, _, _ = load_settled_pre_kickoff_dataset(dataset_db, cutoff_at=CUTOFF)
    assert features[:, FEATURE_COLUMNS.index("home_rest_days")].tolist() == [3]


def test_same_time_matches_are_retained_and_returned_by_match_identity(dataset_db):
    seed(dataset_db, 4)
    with dataset_db.cursor() as cur:
        cur.execute("UPDATE official_matches SET kickoff_time=TIMESTAMP '2026-01-02'")
    features, _, _ = load_settled_pre_kickoff_dataset(dataset_db, cutoff_at=CUTOFF, max_matches=2)
    assert features[:, FEATURE_COLUMNS.index("home_rest_days")].tolist() == [3, 4]


def test_old_feature_semantics_are_not_used_to_fill_a_new_training_window(dataset_db):
    seed(dataset_db, 1)
    with dataset_db.cursor() as cur:
        cur.execute("UPDATE match_feature_snapshots SET feature_version='v4_observed_form'")
    assert load_settled_pre_kickoff_dataset(dataset_db, cutoff_at=CUTOFF) is None


def test_zero_score_draw_and_away_win_are_real_labels(dataset_db):
    seed(dataset_db, 3)
    with dataset_db.cursor() as cur:
        cur.execute(
            "UPDATE official_results SET full_home_goals=0,full_away_goals=0 WHERE match_id=2"
        )
        cur.execute(
            "UPDATE official_results SET full_home_goals=0,full_away_goals=1 WHERE match_id=3"
        )
    _, labels, _ = load_settled_pre_kickoff_dataset(dataset_db, cutoff_at=CUTOFF)
    assert labels.tolist() == [2, 1, 0]


@pytest.mark.parametrize("limit", [0, -1, 5001, True, 2.5])
def test_invalid_sample_limits_fail_before_querying(limit):
    conn = MagicMock()
    with pytest.raises(ValueError, match="max_matches"):
        load_settled_pre_kickoff_dataset(conn, max_matches=limit)
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("cutoff", ["2026-02-01", datetime(2026, 2, 1, tzinfo=UTC)])
def test_cutoff_must_match_the_business_timestamp_contract(cutoff):
    conn = MagicMock()
    with pytest.raises(ValueError, match="cutoff_at"):
        load_settled_pre_kickoff_dataset(conn, cutoff_at=cutoff)
    conn.cursor.assert_not_called()
