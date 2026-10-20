"""Real legacy prediction/recommendation entrances on isolated synthetic PG16."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import psycopg2
import pytest

from scripts.jobs import run_recommendation_candidate as recommendation
from scripts.model_storage import store_model_prediction
from scripts.prediction_input_fence import (
    PredictionInputFence,
    capture_prediction_input_fence,
)
from scripts.prediction_input_updates import InputUpdateSuperseded
from scripts.recommendation_prediction_loader import load_actionable_predictions
from tests.test_computation import test_observed_pipeline_postgres as pipeline
from tests.test_computation import test_prediction_input_revisions_postgres as revisions

connect = pipeline.connect
pg = pipeline.pg
match_id = pipeline.match_id
match = pipeline.match
query = revisions.query


@pytest.fixture
def prediction(pg, match):
    return seed_prediction(pg, match)


def seed_prediction(pg, match):
    at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=8)
    query(
        pg,
        "UPDATE official_matches SET kickoff_time=%s,sale_stop_time=%s,sale_status='selling',"
        "match_status='scheduled' WHERE id=%s",
        (at + timedelta(hours=3), at + timedelta(hours=2), match["id"]),
    )
    version = query(
        pg,
        "INSERT INTO model_versions(model_name,model_type,version,is_active) "
        "VALUES ('maher_poisson','test',%s,true) RETURNING id",
        (uuid4().hex,),
    )[0][0]
    feature = query(
        pg,
        "INSERT INTO match_feature_snapshots(match_id,snapshot_time,feature_version,"
        "home_team_id,away_team_id,data_completeness_score) VALUES (%s,%s,'test',%s,%s,80) "
        "RETURNING id",
        (match["id"], at, match["home_team_id"], match["away_team_id"]),
    )[0][0]
    odds = query(
        pg,
        "INSERT INTO official_odds_snapshots(match_id,play_type,option_code,option_name,"
        "sp_value,snapshot_time) VALUES (%s,'spf','h','home',2,%s) RETURNING id",
        (match["id"], at),
    )[0][0]
    pg.commit()
    return dict(
        match_id=match["id"],
        model_version_id=version,
        feature_snapshot_id=feature,
        odds_snapshot_id=odds,
        predict_time=at.isoformat(),
        play_type="spf",
        option_code="3",
        model_probability=0.5,
        market_probability=0.5,
        break_even_probability=0.5,
        market_edge=0,
        breakeven_edge=0,
        ev=0,
        validation_status="valid",
        calculation_version="market_metrics_v2",
        uncertainty_reason={"model_independent": True},
    )


def observed(pg, match):
    pipeline.weather(pg, match)


def write(pg, prediction):
    token = capture_prediction_input_fence(pg, prediction["match_id"])
    identifier = store_model_prediction(pg, {**prediction, "input_fence": token})
    return identifier, token


def test_current_bound_prediction_passes_actual_candidate_loader(pg, match, prediction):
    observed(pg, match)
    identifier, token = write(pg, prediction)
    assert token.input_version > 0
    row = next(r for r in load_actionable_predictions(pg, ["maher_poisson"]) if r[0] == identifier)
    assert len(row) == 18 and row[1] == match["id"]
    saved = query(
        pg, "SELECT uncertainty_reason FROM model_predictions WHERE id=%s", (identifier,)
    )[0][0]
    assert saved["input_fence"]["input_version"] == token.input_version
    assert saved["model_independent"] is True


def test_new_observation_hides_old_prediction_without_deleting_history(pg, match, prediction):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    observed(pg, match)
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]
    assert query(pg, "SELECT count(*) FROM model_predictions WHERE id=%s", (identifier,)) == [(1,)]


def test_update_during_computation_rejects_write(pg, match, prediction):
    observed(pg, match)
    token = capture_prediction_input_fence(pg, match["id"])
    observed(pg, match)
    with pytest.raises(InputUpdateSuperseded):
        store_model_prediction(pg, {**prediction, "input_fence": token})
    assert query(
        pg,
        "SELECT count(*) FROM model_predictions WHERE model_version_id=%s",
        (prediction["model_version_id"],),
    ) == [(0,)]


def test_unbound_observed_prediction_cannot_bypass_gate(pg, match, prediction):
    observed(pg, match)
    identifier = store_model_prediction(pg, prediction)
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def test_unobserved_legacy_prediction_stays_compatible(pg, prediction):
    identifier = store_model_prediction(pg, prediction)
    assert identifier in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def test_first_observation_invalidates_previously_unobserved_token(pg, match, prediction):
    identifier, token = write(pg, prediction)
    assert token.input_version is None
    observed(pg, match)
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]
    with pytest.raises(InputUpdateSuperseded):
        store_model_prediction(pg, {**prediction, "input_fence": token})


@pytest.mark.parametrize(
    "value", [None, {}, True, {"input_version": "1"}, ["bad"], {"match_id": 1, "input_version": 1}]
)
def test_malformed_retained_json_only_blocks_affected_prediction(pg, match, prediction, value):
    observed(pg, match)
    identifier = store_model_prediction(pg, prediction)
    query(
        pg,
        "UPDATE model_predictions SET uncertainty_reason=jsonb_build_object('model_independent',true,'input_fence',%s::jsonb) WHERE id=%s",
        (json.dumps(value), identifier),
    )
    pg.commit()
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


@pytest.mark.parametrize(
    "change",
    [
        "sale_status='closed'",
        "match_status='cancelled'",
        "source_match_id=source_match_id || '-new'",
    ],
)
def test_official_changes_invalidate_bound_output(pg, match, prediction, change):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    query(pg, "UPDATE official_matches SET " + change + " WHERE id=%s", (match["id"],))
    pg.commit()
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def test_token_cannot_be_used_for_another_match(pg, match, prediction):
    token = capture_prediction_input_fence(pg, match["id"])
    with pytest.raises(ValueError, match="match"):
        store_model_prediction(
            pg, {**prediction, "input_fence": replace(token, match_id=match["id"] + 1)}
        )


@pytest.mark.parametrize("identifier", [True, 0, -1, "1"])
def test_capture_requires_positive_match_id(pg, identifier):
    with pytest.raises(ValueError):
        capture_prediction_input_fence(pg, identifier)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_current_capture_rejects_stale_mvcc(pg, match, isolation):
    pg.rollback()
    query(pg, "SET TRANSACTION ISOLATION LEVEL " + isolation)
    with pytest.raises(ValueError, match="READ COMMITTED"):
        capture_prediction_input_fence(pg, match["id"])


def test_write_fence_serializes_against_new_observation(pg, match, prediction, connect):
    observed(pg, match)
    token = capture_prediction_input_fence(pg, match["id"])
    # Hold the exact same publication check used by store_model_prediction.
    from scripts.prediction_input_fence import bind_prediction_input_fence

    bind_prediction_input_fence(pg, match["id"], token)

    def update():
        with closing(connect()) as other:
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                observed(other, match)
            other.rollback()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(update).result()
    pg.rollback()
    identifier = store_model_prediction(pg, {**prediction, "input_fence": token})
    assert identifier is not None
    observed(pg, match)
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def ticket(pg, prediction, identifier):
    plan = query(
        pg,
        "INSERT INTO daily_budget_plans(plan_date,total_budget,suggested_stake,unused_budget,risk_mode,status) VALUES (timezone('Asia/Shanghai',NOW())::date,500,0,500,'virtual','active') ON CONFLICT (plan_date) DO UPDATE SET updated_at=now() RETURNING id",
    )[0][0]
    tid = query(
        pg,
        "INSERT INTO simulation_tickets(budget_plan_id,strategy_pool,ticket_type,pass_type,suggested_stake,multiple,ticket_status) VALUES (%s,'agent_virtual_recommendation','single','single',20,1,'generated') RETURNING id",
        (plan,),
    )[0][0]
    query(
        pg,
        "INSERT INTO simulation_ticket_items(ticket_id,match_id,play_type,option_code,option_name,model_prediction_id,feature_snapshot_id,sp_value) VALUES (%s,%s,'spf','3','home',%s,%s,2)",
        (tid, prediction["match_id"], identifier, prediction["feature_snapshot_id"]),
    )
    pg.commit()
    return tid


@pytest.fixture
def clean_agent_tickets(pg):
    # Only this module creates Agent tickets in the synthetic fixture. Remove
    # its own records even after a failed assertion, so reruns remain isolated.
    yield
    pg.rollback()
    query(
        pg,
        "DELETE FROM simulation_ticket_items WHERE ticket_id IN (SELECT id FROM simulation_tickets WHERE strategy_pool='agent_virtual_recommendation')",
    )
    query(pg, "DELETE FROM simulation_tickets WHERE strategy_pool='agent_virtual_recommendation'")
    pg.commit()


def test_stale_daily_ticket_stops_regeneration_without_changing_ledger(
    pg, match, prediction, clean_agent_tickets
):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    tid = ticket(pg, prediction, identifier)
    assert not recommendation._has_outdated_ticket_inputs(pg)
    observed(pg, match)
    assert recommendation._has_outdated_ticket_inputs(pg)
    with (
        patch.object(recommendation, "get_db") as db,
        patch.object(recommendation, "get_sporttery_sales_window") as sales,
        patch.object(recommendation, "_buy_ticket") as buy,
    ):
        sales.return_value.is_open = True
        db.return_value.__enter__.return_value = pg
        result = recommendation._run_impl()
    assert result["quality_status"] == "input_invalidated" and result["tickets"] == 0
    buy.assert_not_called()
    assert query(
        pg, "SELECT suggested_stake,ticket_status FROM simulation_tickets WHERE id=%s", (tid,)
    ) == [(20, "generated")]


def test_internal_token_is_frozen():
    from dataclasses import FrozenInstanceError

    token = PredictionInputFence(1, None)
    with pytest.raises(FrozenInstanceError):
        token.input_version = 2


def test_actual_candidate_read_fails_closed_on_old_mvcc_snapshot(pg, match, prediction, connect):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    pg.rollback()
    query(pg, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    query(
        pg,
        "SELECT input_version FROM prediction_input_dirty_matches WHERE match_id=%s",
        (match["id"],),
    )
    with closing(connect()) as other:
        observed(other, match)
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def test_json_token_cannot_be_injected_through_uncertainty_reason(pg, match, prediction):
    observed(pg, match)
    payload = capture_prediction_input_fence(pg, match["id"]).payload()
    with pytest.raises(ValueError, match="reserved"):
        store_model_prediction(pg, {**prediction, "uncertainty_reason": {"input_fence": payload}})


def test_one_match_update_leaves_other_candidate_available(pg, match, prediction):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    other_id = query(pg, "SELECT nextval('official_matches_id_seq')")[0][0]
    query(
        pg,
        "INSERT INTO official_matches(id,business_date,official_match_code,source_match_id,"
        "league_name,home_team_name,away_team_name,kickoff_time) VALUES "
        "(%s,%s,%s,%s,'test','home','away',timezone('Asia/Shanghai',NOW())+interval '3h')",
        (
            other_id,
            datetime(2026, 10, 20).date() + timedelta(days=other_id // 1000),
            f"周二{other_id % 1000:03}",
            uuid4().hex,
        ),
    )
    other_match = {**match, "id": other_id}
    other_prediction = seed_prediction(pg, other_match)
    observed(pg, other_match)
    other_identifier, _ = write(pg, other_prediction)
    observed(pg, match)
    ids = [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]
    assert identifier not in ids and other_identifier in ids


def test_removed_head_cannot_revive_a_bound_prediction(pg, match, prediction):
    observed(pg, match)
    identifier, _ = write(pg, prediction)
    query(pg, "DELETE FROM prediction_input_dirty_matches WHERE match_id=%s", (match["id"],))
    pg.commit()
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


@pytest.mark.parametrize("version", [True, 0, -1, "1"])
def test_invalid_internal_token_version_is_rejected(version):
    with pytest.raises(ValueError):
        PredictionInputFence(1, version)


def test_caller_payload_is_not_mutated_when_binding(pg, prediction):
    token = capture_prediction_input_fence(pg, prediction["match_id"])
    store_model_prediction(pg, {**prediction, "input_fence": token})
    assert prediction["uncertainty_reason"] == {"model_independent": True}


@pytest.mark.parametrize("field", ["sale_stop_time", "kickoff_time"])
def test_actual_candidate_clock_advances_within_open_transaction(pg, match, prediction, field):
    observed(pg, match)
    query(
        pg,
        "UPDATE official_matches SET "
        + field
        + "=timezone('Asia/Shanghai',clock_timestamp())+interval '1 second' WHERE id=%s",
        (match["id"],),
    )
    pg.commit()
    identifier, _ = write(pg, prediction)
    query(pg, "SELECT now()")
    query(pg, "SELECT pg_sleep(1.05)")
    assert identifier not in [r[0] for r in load_actionable_predictions(pg, ["maher_poisson"])]


def test_publication_lock_wait_is_bounded_even_with_larger_caller_timeout(
    pg, match, prediction, connect
):
    observed(pg, match)
    token = capture_prediction_input_fence(pg, match["id"])
    query(pg, "SET LOCAL lock_timeout='2s'")
    with closing(connect()) as other:
        query(
            other,
            "SELECT input_version FROM prediction_input_dirty_matches WHERE match_id=%s FOR UPDATE",
            (match["id"],),
        )
        started = time.monotonic()
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            store_model_prediction(pg, {**prediction, "input_fence": token})
        elapsed = time.monotonic() - started
        pg.rollback()
        other.rollback()
    assert elapsed < 1.2
    assert store_model_prediction(pg, {**prediction, "input_fence": token}) is not None
