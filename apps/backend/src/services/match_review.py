"""Read-only match-level review cards built from immutable business evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from scripts.prediction_statistics import canonical_prediction_rows_ctes


def _as_text(value: Any) -> str | None:
    return (
        value.isoformat()
        if hasattr(value, "isoformat")
        else str(value)
        if value is not None
        else None
    )


def build_match_review_cards(conn: Any, review_date: str) -> list[dict[str, Any]]:
    """Return completed official matches with pre-kickoff signals and sourced evidence.

    This function never derives a new prediction or changes a business record.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.id, m.official_match_code, m.league_name, m.home_team_name, m.away_team_name,
                      m.kickoff_time, m.match_status, r.full_home_goals, r.full_away_goals,
                      r.spf_result, r.rqspf_result, r.total_goals_result,
                      r.score_result, r.half_full_result, r.result_status,
                      r.official_publish_time, m.sale_stop_time
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
            f"""WITH RECURSIVE review_match_scope AS MATERIALIZED (
                   SELECT unnest(%(match_ids)s::bigint[]) AS match_id
               ), {canonical_prediction_rows_ctes(match_scope="review_match_scope")}
               SELECT DISTINCT ON (
                          source_mp.match_id, source_mv.model_name,
                          source_mp.play_type, source_mp.option_code
                      )
                      source_mp.match_id, source_mv.model_name, source_mp.play_type,
                      source_mp.option_code, source_mp.model_probability,
                      source_mp.market_probability, source_mp.ev,
                      source_mp.confidence_score, source_mp.predict_time,
                      original_odds.sp_value, original_odds.snapshot_time, original_odds.id
               FROM canonical_prediction_rows source_mp
               JOIN model_versions source_mv ON source_mv.id = source_mp.model_version_id
               JOIN official_matches source_match ON source_match.id = source_mp.match_id
               LEFT JOIN official_odds_snapshots original_odds
                 ON original_odds.id=source_mp.odds_snapshot_id
                 AND original_odds.match_id=source_mp.match_id
                 AND original_odds.snapshot_time<=source_mp.predict_time
               WHERE source_mp.validation_status = 'valid'
                 AND source_mp.predict_time < source_match.kickoff_time
               ORDER BY source_mp.match_id, source_mv.model_name,
                        source_mp.play_type, source_mp.option_code,
                        source_mp.predict_time DESC, source_mp.id DESC""",
            {"match_ids": match_ids},
        )
        predictions = cur.fetchall()

        cur.execute(
            """WITH eligible AS MATERIALIZED (
                 SELECT DISTINCT ON (o.match_id,o.play_type,o.snapshot_time,o.handicap,o.raw_hash,o.option_code)
                        o.match_id,o.play_type,o.option_code,o.option_name,o.sp_value,
                        o.handicap,o.snapshot_time,o.id,o.raw_hash
                 FROM official_odds_snapshots o JOIN official_matches m ON m.id=o.match_id
                 WHERE o.match_id=ANY(%s) AND o.is_open AND o.raw_hash IS NOT NULL
                   AND m.sale_stop_time IS NOT NULL
                   AND o.snapshot_time<m.kickoff_time AND o.snapshot_time<m.sale_stop_time
                   AND o.sp_value>1 AND o.sp_value<'Infinity'::numeric
                 ORDER BY o.match_id,o.play_type,o.snapshot_time,o.handicap,o.raw_hash,o.option_code,o.id DESC
               ), latest AS (
                 SELECT DISTINCT ON (match_id,play_type) match_id,play_type,snapshot_time,handicap,raw_hash
                 FROM eligible GROUP BY match_id,play_type,snapshot_time,handicap,raw_hash
                 HAVING count(*)=CASE play_type WHEN 'spf' THEN 3 WHEN 'rqspf' THEN 3
                    WHEN 'bf' THEN 31 WHEN 'zjq' THEN 8 WHEN 'bqc' THEN 9 END
                 ORDER BY match_id,play_type,snapshot_time DESC,max(id) DESC
               ) SELECT o.match_id,o.play_type,o.option_code,o.option_name,o.sp_value,o.handicap,o.snapshot_time
                 FROM eligible o JOIN latest l USING (match_id,play_type,snapshot_time,raw_hash)
                 WHERE o.handicap IS NOT DISTINCT FROM l.handicap
                 ORDER BY o.match_id,o.play_type,o.option_code""",
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

        cur.execute(
            """WITH ranked AS (
                   SELECT event.match_id,
                          CASE WHEN evidence.evidence_phase = 'prematch'
                               THEN 'pre_match' ELSE 'post_match' END AS evidence_phase,
                          evidence.source_type, evidence.source_reference,
                          evidence.published_at, evidence.observed_at,
                          COALESCE(
                              evidence.factor_value_json->>'text', evidence.factor_code
                          ) AS headline,
                          evidence.factor_value_json->>'summary' AS summary,
                          evidence.verification_status,
                          ROW_NUMBER() OVER (
                              PARTITION BY event.match_id, evidence.evidence_phase
                              ORDER BY evidence.available_at DESC NULLS LAST, evidence.id DESC
                          ) AS evidence_rank
                   FROM upset_factor_evidence evidence
                   JOIN upset_events event ON event.id = evidence.upset_event_id
                   WHERE event.match_id = ANY(%s)
                     AND evidence.source_type = 'api_football_match_data'
                     AND evidence.verification_status = 'verified'
               )
               SELECT match_id, evidence_phase, source_type, source_reference,
                      published_at, observed_at, headline, summary, verification_status
               FROM ranked
               WHERE evidence_rank <= 4
               ORDER BY match_id, evidence_phase, evidence_rank""",
            (match_ids,),
        )
        provider_evidence_rows = cur.fetchall()

    prediction_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        prediction_map[row[0]].append(
            {
                "modelName": row[1],
                "playType": row[2],
                "optionCode": row[3],
                "modelProbability": float(row[4]) if row[4] is not None else None,
                "marketProbability": float(row[5]) if row[5] is not None else None,
                "ev": float(row[6]) if row[6] is not None else None,
                "confidenceScore": float(row[7]) if row[7] is not None else None,
                "predictTime": _as_text(row[8]),
                "predictionOdds": float(row[9]) if row[9] is not None else None,
                "predictionOddsTime": _as_text(row[10]),
                "predictionOddsSnapshotId": row[11],
            }
        )
    odds_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in odds:
        odds_map[row[0]].append(
            {
                "playType": row[1],
                "optionCode": row[2],
                "optionName": row[3],
                "spValue": float(row[4]) if row[4] is not None else None,
                "handicap": float(row[5]) if row[5] is not None else None,
                "snapshotTime": _as_text(row[6]),
            }
        )
    evidence_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        evidence_map[row[0]].append(
            {
                "phase": row[1],
                "sourceType": "external_reference",
                "sourceName": row[2],
                "sourceReference": row[3],
                "sourceUrl": row[3],
                "publishedAt": _as_text(row[4]),
                "capturedAt": _as_text(row[5]),
                "headline": row[6],
                "summary": row[7],
                "reliability": row[8],
            }
        )
    for row in provider_evidence_rows:
        reference = str(row[3] or "")
        evidence_map[row[0]].append(
            {
                "phase": row[1],
                "sourceType": row[2],
                "sourceName": "API-Football 比赛资料",
                "sourceReference": reference or None,
                "sourceUrl": reference if reference.startswith(("http://", "https://")) else None,
                "publishedAt": _as_text(row[4]),
                "capturedAt": _as_text(row[5]),
                "headline": row[6],
                "summary": row[7],
                "reliability": "verified" if row[8] == "verified" else "unverified",
            }
        )

    cards: list[dict[str, Any]] = []
    for row in matches:
        card_evidence = evidence_map[row[0]]
        cards.append(
            {
                "matchId": row[0],
                "officialCode": row[1],
                "leagueName": row[2],
                "homeTeamName": row[3],
                "awayTeamName": row[4],
                "kickoffTime": _as_text(row[5]),
                "result": {
                    "homeGoals": row[7],
                    "awayGoals": row[8],
                    "spfResult": row[9],
                    "rqspfResult": row[10],
                    "totalGoalsResult": row[11],
                    "scoreResult": row[12],
                    "halfFullResult": row[13],
                    "status": row[14],
                    "publishedAt": _as_text(row[15]),
                },
                "modelSignals": prediction_map[row[0]],
                "oddsSignals": odds_map[row[0]],
                "officialSaleStopTime": _as_text(row[16]),
                "oddsComparisonStatus": (
                    "available"
                    if odds_map[row[0]]
                    else "snapshot_missing"
                    if row[16]
                    else "cutoff_unknown"
                ),
                "evidence": card_evidence,
                "evidenceStatus": "已收录" if card_evidence else "未查到可靠资料",
            }
        )
    return cards
