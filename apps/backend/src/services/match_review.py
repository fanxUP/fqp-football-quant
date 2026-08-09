"""Read-only match-level review cards built from immutable business evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _as_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None


def build_match_review_cards(conn: Any, review_date: str) -> list[dict[str, Any]]:
    """Return completed official matches with pre-kickoff signals and sourced evidence.

    This function never derives a new prediction or changes a business record.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.id, m.official_match_code, m.league_name, m.home_team_name, m.away_team_name,
                      m.kickoff_time, m.match_status, r.full_home_goals, r.full_away_goals,
                      r.spf_result, r.result_status, r.official_publish_time
               FROM official_matches m
               JOIN official_results r ON r.match_id = m.id
               WHERE m.business_date = %s AND r.result_status = 'confirmed'
               ORDER BY m.kickoff_time ASC, m.id ASC""",
            (review_date,),
        )
        matches = cur.fetchall()
        if not matches:
            return []
        match_ids = [row[0] for row in matches]

        cur.execute(
            """SELECT DISTINCT ON (mp.match_id, mv.model_name, mp.play_type, mp.option_code)
                      mp.match_id, mv.model_name, mp.play_type, mp.option_code, mp.model_probability,
                      mp.market_probability, mp.ev, mp.confidence_score, mp.predict_time
               FROM model_predictions mp
               JOIN model_versions mv ON mv.id = mp.model_version_id
               JOIN official_matches m ON m.id = mp.match_id
               WHERE mp.match_id = ANY(%s) AND mp.validation_status = 'valid'
                 AND mp.predict_time < m.kickoff_time
               ORDER BY mp.match_id, mv.model_name, mp.play_type, mp.option_code, mp.predict_time DESC, mp.id DESC""",
            (match_ids,),
        )
        predictions = cur.fetchall()

        cur.execute(
            """SELECT DISTINCT ON (o.match_id, o.play_type, o.option_code)
                      o.match_id, o.play_type, o.option_code, o.option_name, o.sp_value, o.handicap, o.snapshot_time
               FROM official_odds_snapshots o
               JOIN official_matches m ON m.id = o.match_id
               WHERE o.match_id = ANY(%s) AND o.is_open = true
                 AND o.snapshot_time <= COALESCE(m.sale_stop_time, m.kickoff_time)
               ORDER BY o.match_id, o.play_type, o.option_code, o.snapshot_time DESC, o.id DESC""",
            (match_ids,),
        )
        odds = cur.fetchall()

        cur.execute(
            """SELECT match_id, evidence_phase, source_name, source_url, published_at, captured_at,
                      headline, summary, reliability
               FROM match_review_evidence
               WHERE match_id = ANY(%s)
               ORDER BY match_id, published_at ASC NULLS LAST, id ASC""",
            (match_ids,),
        )
        evidence_rows = cur.fetchall()

    prediction_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        prediction_map[row[0]].append({
            "modelName": row[1], "playType": row[2], "optionCode": row[3],
            "modelProbability": float(row[4]) if row[4] is not None else None,
            "marketProbability": float(row[5]) if row[5] is not None else None,
            "ev": float(row[6]) if row[6] is not None else None,
            "confidenceScore": float(row[7]) if row[7] is not None else None,
            "predictTime": _as_text(row[8]),
        })
    odds_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in odds:
        odds_map[row[0]].append({
            "playType": row[1], "optionCode": row[2], "optionName": row[3],
            "spValue": float(row[4]) if row[4] is not None else None,
            "handicap": float(row[5]) if row[5] is not None else None,
            "snapshotTime": _as_text(row[6]),
        })
    evidence_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        evidence_map[row[0]].append({
            "phase": row[1], "sourceName": row[2], "sourceUrl": row[3], "publishedAt": _as_text(row[4]),
            "capturedAt": _as_text(row[5]), "headline": row[6], "summary": row[7], "reliability": row[8],
        })

    cards: list[dict[str, Any]] = []
    for row in matches:
        card_evidence = evidence_map[row[0]]
        cards.append({
            "matchId": row[0], "officialCode": row[1], "leagueName": row[2],
            "homeTeamName": row[3], "awayTeamName": row[4], "kickoffTime": _as_text(row[5]),
            "result": {"homeGoals": row[7], "awayGoals": row[8], "spfResult": row[9], "status": row[10], "publishedAt": _as_text(row[11])},
            "modelSignals": prediction_map[row[0]], "oddsSignals": odds_map[row[0]], "evidence": card_evidence,
            "evidenceStatus": "已收录" if card_evidence else "未查到可靠资料",
        })
    return cards
