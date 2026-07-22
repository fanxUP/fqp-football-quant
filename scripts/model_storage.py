"""Model and recommendation storage layer.

CRUD for Stage 4 tables:
  - model_predictions
  - model_committee_votes
  - simulation_tickets + simulation_ticket_items

Same psycopg2 pattern as official_storage.py and feature_storage.py.
"""

from __future__ import annotations

import json
from typing import Any

from scripts.agents.human_review_gate import assert_recommendation_publishable
from scripts.business_time import business_now


def _now() -> str:
    return business_now().replace(tzinfo=None).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# model_predictions (append-only — each run creates new predictions)
# ---------------------------------------------------------------------------


def store_model_prediction(conn: Any, pred: dict) -> int | None:
    """Insert a single model prediction row. Returns the new id."""
    sql = """
        INSERT INTO model_predictions (
            match_id, model_version_id, odds_snapshot_id, feature_snapshot_id, predict_time,
            play_type, option_code,
            raw_model_probability, model_probability, market_probability,
            probability_lower_bound, probability_upper_bound,
            uncertainty_score, adjusted_probability,
            fair_odds, ev, confidence_score, risk_score,
            break_even_probability, market_edge, breakeven_edge,
            validation_status, validation_errors, calculation_version,
            uncertainty_reason, created_at
        ) VALUES (
            %(match_id)s, %(model_version_id)s, %(odds_snapshot_id)s, %(feature_snapshot_id)s, %(predict_time)s,
            %(play_type)s, %(option_code)s,
            %(raw_model_probability)s, %(model_probability)s, %(market_probability)s,
            %(probability_lower_bound)s, %(probability_upper_bound)s,
            %(uncertainty_score)s, %(adjusted_probability)s,
            %(fair_odds)s, %(ev)s, %(confidence_score)s, %(risk_score)s,
            %(break_even_probability)s, %(market_edge)s, %(breakeven_edge)s,
            %(validation_status)s, %(validation_errors)s, %(calculation_version)s,
            %(uncertainty_reason)s, now()
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "match_id": pred["match_id"],
                "model_version_id": pred["model_version_id"],
                "odds_snapshot_id": pred.get("odds_snapshot_id"),
                "feature_snapshot_id": pred.get("feature_snapshot_id"),
                "predict_time": pred.get("predict_time", _now()),
                "play_type": pred["play_type"],
                "option_code": pred["option_code"],
                "raw_model_probability": pred.get(
                    "raw_model_probability", pred.get("model_probability")
                ),
                "model_probability": pred.get("model_probability"),
                "market_probability": pred.get("market_probability"),
                "probability_lower_bound": pred.get("probability_lower_bound"),
                "probability_upper_bound": pred.get("probability_upper_bound"),
                "uncertainty_score": pred.get("uncertainty_score"),
                "adjusted_probability": pred.get("adjusted_probability"),
                "fair_odds": pred.get("fair_odds"),
                "ev": pred.get("ev"),
                "confidence_score": pred.get("confidence_score"),
                "risk_score": pred.get("risk_score"),
                "break_even_probability": pred.get("break_even_probability"),
                "market_edge": pred.get("market_edge"),
                "breakeven_edge": pred.get("breakeven_edge"),
                "validation_status": pred.get("validation_status", "valid"),
                "validation_errors": json.dumps(
                    pred.get("validation_errors", []), ensure_ascii=False
                ),
                "calculation_version": pred.get("calculation_version", "legacy"),
                "uncertainty_reason": json.dumps(
                    pred.get("uncertainty_reason", {}), ensure_ascii=False
                ),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# model_committee_votes
# ---------------------------------------------------------------------------


def store_committee_vote(conn: Any, vote: dict) -> int | None:
    """Insert a committee vote row. Returns the new id."""
    sql = """
        INSERT INTO model_committee_votes (
            match_id, play_type, option_code, prediction_time,
            model_version_id, model_name,
            model_probability, vote_direction, vote_weight, created_at
        ) VALUES (
            %(match_id)s, %(play_type)s, %(option_code)s, %(prediction_time)s,
            %(model_version_id)s, %(model_name)s,
            %(model_probability)s, %(vote_direction)s, %(vote_weight)s, now()
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "match_id": vote["match_id"],
                "play_type": vote["play_type"],
                "option_code": vote["option_code"],
                "prediction_time": vote.get("prediction_time", _now()),
                "model_version_id": vote.get("model_version_id"),
                "model_name": vote["model_name"],
                "model_probability": vote.get("model_probability"),
                "vote_direction": vote.get("vote_direction"),
                "vote_weight": vote.get("vote_weight", 1.0),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# simulation_tickets + simulation_ticket_items
# ---------------------------------------------------------------------------


def store_simulation_ticket(conn: Any, ticket: dict, items: list[dict]) -> int | None:
    """Insert a simulation ticket with its items. Returns the ticket id."""
    with conn.cursor() as cur:
        # 1. Get today's budget plan
        cur.execute(
            """SELECT id FROM daily_budget_plans
               WHERE plan_date = timezone('Asia/Shanghai', NOW())::date
               LIMIT 1"""
        )
        plan_row = cur.fetchone()
        budget_plan_id = plan_row[0] if plan_row else None

        # 2. Insert ticket
        cur.execute(
            """
            INSERT INTO simulation_tickets (
                budget_plan_id, strategy_pool, ticket_type, pass_type,
                suggested_stake, multiple, estimated_return, max_return,
                expected_value, risk_level, ticket_status, bet_count, rule_metadata, created_at
            ) VALUES (
                %(budget_plan_id)s, %(strategy_pool)s, %(ticket_type)s, %(pass_type)s,
                %(suggested_stake)s, %(multiple)s, %(estimated_return)s, %(max_return)s,
                %(expected_value)s, %(risk_level)s, %(ticket_status)s, %(bet_count)s, %(rule_metadata)s, now()
            )
            RETURNING id
            """,
            {
                "budget_plan_id": budget_plan_id,
                "strategy_pool": ticket.get("strategy_pool", "main"),
                "ticket_type": ticket.get("ticket_type", "single"),
                "pass_type": ticket.get("pass_type", "single"),
                "suggested_stake": ticket["suggested_stake"],
                "multiple": ticket.get("multiple", 1),
                "estimated_return": ticket.get("estimated_return"),
                "max_return": ticket.get("max_return"),
                "expected_value": ticket.get("expected_value"),
                "risk_level": ticket.get("risk_level", "medium"),
                "ticket_status": ticket.get("ticket_status", "generated"),
                "bet_count": ticket.get("bet_count", 1),
                "rule_metadata": json.dumps(ticket.get("rule_metadata", {}), ensure_ascii=False),
            },
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None
        ticket_id = row[0]

        # 3. Insert ticket items
        for item in items:
            cur.execute(
                """
                INSERT INTO simulation_ticket_items (
                    ticket_id, match_id, odds_snapshot_id, model_prediction_id, feature_snapshot_id,
                    play_type, option_code, option_name,
                    sp_value, model_probability, market_probability,
                    ev, confidence_score, risk_score, odds_source, created_at
                ) VALUES (
                    %(ticket_id)s, %(match_id)s, %(odds_snapshot_id)s, %(model_prediction_id)s, %(feature_snapshot_id)s,
                    %(play_type)s, %(option_code)s, %(option_name)s,
                    %(sp_value)s, %(model_probability)s, %(market_probability)s,
                    %(ev)s, %(confidence_score)s, %(risk_score)s, %(odds_source)s, now()
                )
                """,
                {
                    "ticket_id": ticket_id,
                    "match_id": item["match_id"],
                    "odds_snapshot_id": item.get("odds_snapshot_id"),
                    "model_prediction_id": item.get("model_prediction_id"),
                    "feature_snapshot_id": item.get("feature_snapshot_id"),
                    "play_type": item["play_type"],
                    "option_code": item["option_code"],
                    "option_name": item.get("option_name", item["option_code"]),
                    "sp_value": item["sp_value"],
                    "model_probability": item.get("model_probability"),
                    "market_probability": item.get("market_probability"),
                    "ev": item.get("ev"),
                    "confidence_score": item.get("confidence_score"),
                    "risk_score": item.get("risk_score"),
                    "odds_source": item.get(
                        "odds_source",
                        "official" if item.get("odds_snapshot_id") else "synthetic_model",
                    ),
                },
            )

    conn.commit()
    return ticket_id


def activate_simulation_ticket(conn: Any, ticket_id: int, review_status: str | None) -> bool:
    """Activate a generated ticket only after Risk/human approval."""
    assert_recommendation_publishable(review_status)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE simulation_tickets
               SET ticket_status = 'activated'
               WHERE id = %s AND ticket_status = 'generated'
               RETURNING id""",
            (ticket_id,),
        )
        row = cur.fetchone()
    conn.commit()
    return bool(row)
