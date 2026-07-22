"""Idempotent evidence collection and structured review persistence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from scripts.upset.evidence import evidence_record
from scripts.upset.review import build_review_payload


def _json(value: Any) -> Json:
    return Json(value, dumps=lambda payload: json.dumps(payload, default=str, ensure_ascii=False))


def normalized_fraction(value: Any) -> float | None:
    """Normalize legacy 0-100 scores and current 0-1 scores to one fraction."""
    if value is None:
        return None
    number = float(value)
    return number / 100.0 if number > 1 else number


def _events(conn: Any, limit: int) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT event.*, match.kickoff_time, match.home_team_name,
                   match.away_team_name, match.official_match_code,
                   result.full_home_goals, result.full_away_goals,
                   result.result_status, result.official_publish_time,
                   result.updated_at AS result_updated_at
            FROM upset_events event
            JOIN official_matches match ON match.id = event.match_id
            JOIN official_results result ON result.id = event.official_result_id
            WHERE event.detection_status = 'detected'
            ORDER BY event.business_date DESC, event.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def _market_evidence(conn: Any, event: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, play_type, closing_snapshot_time, actual_outcome,
                   actual_outcome_probability, market_favourite_outcome,
                   market_favourite_probability
            FROM upset_market_signals
            WHERE upset_event_id = %s
            ORDER BY id
            """,
            (event["id"],),
        )
        rows = [dict(row) for row in cur.fetchall()]
    records = []
    for row in rows:
        probability = float(row["actual_outcome_probability"])
        text = (
            f"{row['play_type'].upper()}实际结果{row['actual_outcome']}的"
            f"临场去水概率为{probability:.1%}"
        )
        records.append(
            evidence_record(
                event_id=int(event["id"]),
                category="market",
                code=f"closing_probability:{row['play_type']}:{row['id']}",
                value={"text": text, **row},
                phase="prematch",
                source_type="official_odds_snapshot",
                source_reference=f"upset_market_signal:{row['id']}",
                observed_at=row["closing_snapshot_time"],
                available_at=row["closing_snapshot_time"],
                kickoff_time=event["kickoff_time"],
            )
        )
    return records


def _result_evidence(event: dict[str, Any]) -> dict[str, Any]:
    available_at = (
        event["official_publish_time"] or event["result_updated_at"] or datetime.now()
    )
    score = f"{event['full_home_goals']}:{event['full_away_goals']}"
    return evidence_record(
        event_id=int(event["id"]),
        category="official_result",
        code="final_score",
        value={
            "text": (
                f"官方赛果为{event['home_team_name']} {score} "
                f"{event['away_team_name']}"
            ),
            "score": score,
            "status": event["result_status"],
        },
        phase="postmatch",
        source_type="sporttery_official_result",
        source_reference=f"official_result:{event['official_result_id']}",
        observed_at=available_at,
        available_at=available_at,
        kickoff_time=event["kickoff_time"],
    )


def _feature_evidence(conn: Any, event: dict[str, Any]) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, snapshot_time, feature_version, data_completeness_score,
                   source_confidence_score, uncertainty_score,
                   home_lineup_confirmed, away_lineup_confirmed
            FROM match_feature_snapshots
            WHERE match_id = %s AND snapshot_time < %s
            ORDER BY snapshot_time DESC, id DESC
            LIMIT 1
            """,
            (event["match_id"], event["kickoff_time"]),
        )
        row = cur.fetchone()
    if not row:
        return None
    feature = dict(row)
    completeness = normalized_fraction(feature.get("data_completeness_score"))
    text = "赛前多维特征快照已绑定"
    if completeness is not None:
        text += f"，数据完整度为{float(completeness):.1%}"
    return evidence_record(
        event_id=int(event["id"]),
        category="feature",
        code="prematch_feature_snapshot",
        value={"text": text, **feature},
        phase="prematch",
        source_type="match_feature_snapshot",
        source_reference=f"match_feature_snapshot:{feature['id']}",
        observed_at=feature["snapshot_time"],
        available_at=feature["snapshot_time"],
        kickoff_time=event["kickoff_time"],
        confidence=normalized_fraction(feature.get("source_confidence_score")) or 0.5,
    )


def _prediction_evidence(conn: Any, event: dict[str, Any]) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT prediction.id, prediction.predict_time, prediction.option_code,
                   prediction.model_probability, prediction.market_probability,
                   prediction.ev, prediction.validation_status,
                   version.model_name, version.version
            FROM model_predictions prediction
            JOIN model_versions version ON version.id = prediction.model_version_id
            WHERE prediction.match_id = %s
              AND prediction.play_type = %s
              AND prediction.predict_time < %s
              AND prediction.validation_status = 'valid'
              AND COALESCE(
                    (prediction.uncertainty_reason->>'model_independent')::boolean,
                    false
                  ) = true
            ORDER BY prediction.predict_time DESC,
                     prediction.model_probability DESC, prediction.id DESC
            LIMIT 1
            """,
            (event["match_id"], event["primary_play_type"], event["kickoff_time"]),
        )
        row = cur.fetchone()
    if not row:
        return None
    prediction = dict(row)
    text = (
        f"赛前{prediction['model_name']}模型最高概率选项为"
        f"{prediction['option_code']}（{float(prediction['model_probability']):.1%}）"
    )
    return evidence_record(
        event_id=int(event["id"]),
        category="model",
        code="latest_independent_prediction",
        value={"text": text, **prediction},
        phase="prematch",
        source_type="model_prediction",
        source_reference=f"model_prediction:{prediction['id']}",
        observed_at=prediction["predict_time"],
        available_at=prediction["predict_time"],
        kickoff_time=event["kickoff_time"],
    )


def _insert_evidence(conn: Any, record: dict[str, Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM upset_factor_evidence
            WHERE upset_event_id=%(upset_event_id)s
              AND factor_code=%(factor_code)s
              AND source_type=%(source_type)s
              AND source_reference IS NOT DISTINCT FROM %(source_reference)s
              AND raw_payload_hash IS DISTINCT FROM %(raw_payload_hash)s
            """,
            record,
        )
        cur.execute(
            """
            INSERT INTO upset_factor_evidence (
                upset_event_id, factor_category, factor_code, factor_value_json,
                factor_direction, evidence_phase, available_before_kickoff,
                source_type, source_reference, published_at, observed_at,
                available_at, confidence, verification_status, raw_payload_hash
            ) VALUES (
                %(upset_event_id)s, %(factor_category)s, %(factor_code)s,
                %(factor_value_json)s, %(factor_direction)s, %(evidence_phase)s,
                %(available_before_kickoff)s, %(source_type)s, %(source_reference)s,
                %(published_at)s, %(observed_at)s, %(available_at)s, %(confidence)s,
                %(verification_status)s, %(raw_payload_hash)s
            ) ON CONFLICT DO NOTHING
            RETURNING id
            """,
            {**record, "factor_value_json": _json(record["factor_value_json"])},
        )
        return cur.fetchone() is not None


def collect_evidence(conn: Any, *, limit: int = 500) -> dict[str, int]:
    """Collect official, market, feature, and independent-model evidence."""
    events = _events(conn, limit)
    inserted = 0
    for event in events:
        records = [_result_evidence(event), *_market_evidence(conn, event)]
        for optional in (_feature_evidence(conn, event), _prediction_evidence(conn, event)):
            if optional:
                records.append(optional)
        inserted += sum(_insert_evidence(conn, record) for record in records)
    conn.commit()
    return {"events": len(events), "inserted": inserted}


def _model_postmortem(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    model_rows = [row for row in evidence if row["factor_category"] == "model"]
    if not model_rows:
        return {"status": "unavailable", "reason": "NO_VALID_INDEPENDENT_PREMATCH_MODEL"}
    value = dict(model_rows[-1]["factor_value_json"])
    return {
        "status": "available",
        "prediction_id": value.get("id"),
        "model_name": value.get("model_name"),
        "model_version": value.get("version"),
        "predicted_option": value.get("option_code"),
        "model_probability": value.get("model_probability"),
    }


def generate_reviews(conn: Any, *, limit: int = 500) -> dict[str, int]:
    """Generate one conservative, evidence-linked review per detected event."""
    events = _events(conn, limit)
    written = 0
    for event in events:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM upset_factor_evidence
                   WHERE upset_event_id = %s ORDER BY available_at, id""",
                (event["id"],),
            )
            evidence = [dict(row) for row in cur.fetchall()]
        payload = build_review_payload(
            event=event,
            evidence=evidence,
            kickoff_time=event["kickoff_time"],
            model_postmortem=_model_postmortem(evidence),
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO upset_reviews (
                    upset_event_id, review_version, prompt_version, model_name,
                    summary, facts_json, prematch_signals_json,
                    in_match_turning_points_json, inferences_json, hypotheses_json,
                    randomness_json, model_postmortem_json, actionable_lessons_json,
                    data_completeness, confidence, validation_status,
                    validation_errors_json, generated_at, published_at, updated_at
                ) VALUES (
                    %(event_id)s, 'review-v1', 'evidence-grounded-v1',
                    'deterministic-evidence-review-v1', %(summary)s, %(facts)s,
                    %(prematch)s, %(turning)s, %(inferences)s, %(hypotheses)s,
                    %(randomness)s, %(postmortem)s, %(lessons)s, %(completeness)s,
                    %(confidence)s, %(status)s, %(errors)s, now(),
                    CASE WHEN %(status)s = 'validated' THEN now() END, now()
                ) ON CONFLICT (upset_event_id, review_version) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    facts_json = EXCLUDED.facts_json,
                    prematch_signals_json = EXCLUDED.prematch_signals_json,
                    in_match_turning_points_json = EXCLUDED.in_match_turning_points_json,
                    inferences_json = EXCLUDED.inferences_json,
                    hypotheses_json = EXCLUDED.hypotheses_json,
                    randomness_json = EXCLUDED.randomness_json,
                    model_postmortem_json = EXCLUDED.model_postmortem_json,
                    actionable_lessons_json = EXCLUDED.actionable_lessons_json,
                    data_completeness = EXCLUDED.data_completeness,
                    confidence = EXCLUDED.confidence,
                    validation_status = EXCLUDED.validation_status,
                    validation_errors_json = EXCLUDED.validation_errors_json,
                    generated_at = now(), published_at = EXCLUDED.published_at,
                    updated_at = now()
                """,
                {
                    "event_id": event["id"],
                    "summary": payload["summary"],
                    "facts": _json(payload["facts_json"]),
                    "prematch": _json(payload["prematch_signals_json"]),
                    "turning": _json(payload["in_match_turning_points_json"]),
                    "inferences": _json(payload["inferences_json"]),
                    "hypotheses": _json(payload["hypotheses_json"]),
                    "randomness": _json(payload["randomness_json"]),
                    "postmortem": _json(payload["model_postmortem_json"]),
                    "lessons": _json(payload["actionable_lessons_json"]),
                    "completeness": payload["data_completeness"],
                    "confidence": payload["confidence"],
                    "status": payload["validation_status"],
                    "errors": _json(payload["validation_errors_json"]),
                },
            )
        written += 1
    conn.commit()
    return {"events": len(events), "written": written}
