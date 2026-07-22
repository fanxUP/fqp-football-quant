"""PostgreSQL orchestration for idempotent upset-event detection."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg2.extras import Json

from scripts.upset.detector import MarketDetection, build_market_detections
from scripts.upset.domain import UpsetRule


def rule_from_thresholds(version: str, thresholds: dict[str, Any]) -> UpsetRule:
    """Create the domain rule from one active database rule version."""
    play_thresholds = {
        play_type: (
            float(values["S"]),
            float(values["A"]),
            float(values["B"]),
            float(values["C"]),
        )
        for play_type, values in dict(thresholds.get("by_play", {})).items()
    }
    return UpsetRule(
        version=version,
        extreme_max=float(thresholds["S"]),
        major_max=float(thresholds["A"]),
        general_max=float(thresholds["B"]),
        mild_max=float(thresholds["C"]),
        favourite_min=float(thresholds["favourite_min"]),
        play_thresholds=play_thresholds,
    )


def select_primary_detection(detections: list[MarketDetection]) -> MarketDetection:
    """Use the least likely actual result as the match-level primary signal."""
    if not detections:
        raise ValueError("至少需要一个冷门市场信号")
    return min(detections, key=lambda detection: detection.signal.actual_probability)


def event_type(detection: MarketDetection) -> str:
    """Keep objective odds upsets and favourite failures distinguishable."""
    if detection.signal.upset_level and detection.signal.favourite_failed:
        return "odds_and_favourite"
    if detection.signal.upset_level:
        return "odds_upset"
    return "favourite_failed"


def _active_rule(conn: Any) -> tuple[int, UpsetRule]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, rule_key, thresholds_json
            FROM upset_rule_versions
            WHERE is_active = true
              AND valid_from <= now()
              AND (valid_to IS NULL OR valid_to > now())
            ORDER BY valid_from DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("没有生效的冷门检测规则")
    return int(row[0]), rule_from_thresholds(str(row[1]), dict(row[2]))


def _settled_matches(conn: Any, business_date: date | None, limit: int) -> list[tuple[Any, ...]]:
    date_clause = "AND m.business_date = %(business_date)s" if business_date else ""
    params: dict[str, Any] = {"limit": limit}
    if business_date:
        params["business_date"] = business_date
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT m.id, m.business_date, m.kickoff_time,
                   r.id, r.spf_result, r.rqspf_result,
                   r.total_goals_result, r.score_result, r.half_full_result,
                   EXISTS (
                       SELECT 1
                       FROM real_ticket_items item
                       JOIN real_tickets ticket ON ticket.id = item.real_ticket_id
                       WHERE item.match_id = m.id
                         AND ticket.confirm_status = 'confirmed'
                   ) AS user_bet_involved,
                   EXISTS (
                       SELECT 1
                       FROM simulation_ticket_items item
                       JOIN simulation_tickets ticket ON ticket.id = item.ticket_id
                       WHERE item.match_id = m.id
                         AND ticket.ticket_status IN ('generated', 'activated', 'settled')
                   ) AS agent_bet_involved
            FROM official_matches m
            JOIN official_results r ON r.match_id = m.id
            WHERE r.result_status IN ('final', 'confirmed')
              {date_clause}
            ORDER BY m.business_date DESC, m.kickoff_time DESC, m.id DESC
            LIMIT %(limit)s
            """,
            params,
        )
        return list(cur.fetchall())


def _prematch_odds(conn: Any, match_id: int, kickoff_time: Any) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, snapshot_time, play_type, option_code, sp_value, handicap
            FROM official_odds_snapshots
            WHERE match_id = %s
              AND snapshot_time < %s
              AND play_type IN ('spf', 'rqspf', 'bf', 'zjq', 'bqc')
              AND sp_value > 1
            ORDER BY snapshot_time, id
            """,
            (match_id, kickoff_time),
        )
        return list(cur.fetchall())


def _store_event(
    conn: Any,
    *,
    match_row: tuple[Any, ...],
    rule_id: int,
    detections: list[MarketDetection],
) -> int:
    match_id, business_date, _kickoff, result_id = match_row[:4]
    user_involved, agent_involved = bool(match_row[9]), bool(match_row[10])
    primary = select_primary_detection(detections)
    signal = primary.signal
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO upset_events (
                match_id, business_date, detect_rule_version_id, official_result_id,
                primary_play_type, primary_upset_type, actual_outcome,
                market_favourite_outcome, market_favourite_probability,
                actual_outcome_probability, surprise_bits, upset_level,
                favourite_failed, user_bet_involved, agent_bet_involved,
                detection_status, detected_at, updated_at
            ) VALUES (
                %(match_id)s, %(business_date)s, %(rule_id)s, %(result_id)s,
                %(play_type)s, %(event_type)s, %(actual_outcome)s,
                %(favourite_outcome)s, %(favourite_probability)s,
                %(actual_probability)s, %(surprise_bits)s, %(upset_level)s,
                %(favourite_failed)s, %(user_involved)s, %(agent_involved)s,
                'detected', now(), now()
            )
            ON CONFLICT (match_id, detect_rule_version_id) DO UPDATE SET
                official_result_id = EXCLUDED.official_result_id,
                primary_play_type = EXCLUDED.primary_play_type,
                primary_upset_type = EXCLUDED.primary_upset_type,
                actual_outcome = EXCLUDED.actual_outcome,
                market_favourite_outcome = EXCLUDED.market_favourite_outcome,
                market_favourite_probability = EXCLUDED.market_favourite_probability,
                actual_outcome_probability = EXCLUDED.actual_outcome_probability,
                surprise_bits = EXCLUDED.surprise_bits,
                upset_level = EXCLUDED.upset_level,
                favourite_failed = EXCLUDED.favourite_failed,
                user_bet_involved = EXCLUDED.user_bet_involved,
                agent_bet_involved = EXCLUDED.agent_bet_involved,
                detection_status = 'detected',
                updated_at = now()
            RETURNING id
            """,
            {
                "match_id": match_id,
                "business_date": business_date,
                "rule_id": rule_id,
                "result_id": result_id,
                "play_type": primary.play_type,
                "event_type": event_type(primary),
                "actual_outcome": signal.actual_option,
                "favourite_outcome": signal.market_favourite_option,
                "favourite_probability": signal.market_favourite_probability,
                "actual_probability": signal.actual_probability,
                "surprise_bits": signal.surprise_bits,
                "upset_level": signal.upset_level,
                "favourite_failed": signal.favourite_failed,
                "user_involved": user_involved,
                "agent_involved": agent_involved,
            },
        )
        event_id = int(cur.fetchone()[0])
        cur.execute("DELETE FROM upset_market_signals WHERE upset_event_id = %s", (event_id,))
        for detection in detections:
            reasons = []
            if detection.signal.upset_level:
                reasons.append("LOW_ACTUAL_OUTCOME_PROBABILITY")
            if detection.signal.favourite_failed:
                reasons.append("MARKET_FAVOURITE_FAILED")
            cur.execute(
                """
                INSERT INTO upset_market_signals (
                    upset_event_id, match_id, play_type, handicap,
                    opening_snapshot_time, closing_snapshot_time,
                    opening_odds_json, closing_odds_json, market_probabilities_json,
                    market_overround, actual_outcome, actual_outcome_probability,
                    market_favourite_outcome, market_favourite_probability,
                    odds_change_rate, surprise_bits, upset_level,
                    favourite_failed, detection_reasons_json
                ) VALUES (
                    %(event_id)s, %(match_id)s, %(play_type)s, %(handicap)s,
                    %(opening_time)s, %(closing_time)s,
                    %(opening_odds)s, %(closing_odds)s, %(market_probabilities)s,
                    %(overround)s, %(actual_outcome)s, %(actual_probability)s,
                    %(favourite_outcome)s, %(favourite_probability)s,
                    %(odds_change_rate)s, %(surprise_bits)s, %(upset_level)s,
                    %(favourite_failed)s, %(reasons)s
                )
                """,
                {
                    "event_id": event_id,
                    "match_id": match_id,
                    "play_type": detection.play_type,
                    "handicap": detection.handicap,
                    "opening_time": detection.opening_snapshot_time,
                    "closing_time": detection.closing_snapshot_time,
                    "opening_odds": Json(detection.opening_odds),
                    "closing_odds": Json(detection.closing_odds),
                    "market_probabilities": Json(detection.signal.market_probabilities),
                    "overround": detection.signal.market_overround,
                    "actual_outcome": detection.signal.actual_option,
                    "actual_probability": detection.signal.actual_probability,
                    "favourite_outcome": detection.signal.market_favourite_option,
                    "favourite_probability": detection.signal.market_favourite_probability,
                    "odds_change_rate": detection.actual_odds_change_rate,
                    "surprise_bits": detection.signal.surprise_bits,
                    "upset_level": detection.signal.upset_level,
                    "favourite_failed": detection.signal.favourite_failed,
                    "reasons": Json(reasons),
                },
            )
    return event_id


def detect_and_store(
    conn: Any,
    *,
    business_date: date | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Detect settled cold results and leave one idempotent event per rule version."""
    rule_id, rule = _active_rule(conn)
    matches = _settled_matches(conn, business_date, limit)
    detected = 0
    no_complete_market = 0
    no_upset = 0
    event_ids: list[int] = []

    for match_row in matches:
        match_id, _business_date, kickoff_time = match_row[:3]
        result_by_play = {
            "spf": match_row[4],
            "rqspf": match_row[5],
            "zjq": match_row[6],
            "bf": match_row[7],
            "bqc": match_row[8],
        }
        detections = build_market_detections(
            odds_rows=_prematch_odds(conn, int(match_id), kickoff_time),
            result_by_play=result_by_play,
            rule=rule,
        )
        if not detections:
            no_complete_market += 1
            continue
        relevant = [
            detection
            for detection in detections
            if detection.signal.upset_level or detection.signal.favourite_failed
        ]
        if not relevant:
            no_upset += 1
            continue
        event_ids.append(
            _store_event(conn, match_row=match_row, rule_id=rule_id, detections=relevant)
        )
        detected += 1

    conn.commit()
    return {
        "status": "ok",
        "rule_version": rule.version,
        "settled_matches": len(matches),
        "detected": detected,
        "no_complete_market": no_complete_market,
        "no_upset": no_upset,
        "event_ids": event_ids,
    }
