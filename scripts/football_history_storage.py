"""Bounded shared-database reference reads; no acquisition or model activation."""

from typing import Literal

from psycopg2.extras import RealDictCursor

HistoryDomain = Literal[
    "match_stats", "events", "lineups", "predicted_lineups", "match_injuries", "odds_history"
]
HISTORY_DOMAINS = (
    "match_stats",
    "events",
    "lineups",
    "predicted_lineups",
    "match_injuries",
    "odds_history",
)
_TIME_FIELDS = (
    "change_at",
    "time_basis",
    "time_resolution_reason",
    "timeline_usable",
    "change_timezone_basis",
    "effective_kickoff_at",
    "kickoff_time_basis",
    "time_resolution_version",
)


def match_history_reference(
    conn,
    match_id: int,
    *,
    domain: HistoryDomain = "match_stats",
    batch_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Pin one published match/batch before counts, pagination or timeline windows."""
    if (
        domain not in HISTORY_DOMAINS
        or not 1 <= match_id <= 9007199254740991
        or (batch_id is not None and not 1 <= batch_id <= 9007199254740991)
        or not 1 <= limit <= 100
        or not 0 <= offset <= 10000
    ):
        raise ValueError("Invalid history reference scope")
    result: dict = {
        "match_id": match_id,
        "domain": domain,
        "status": "unmatched",
        "batch": None,
        "source_match": None,
        "counts": {},
        "rows": [],
        "limit": limit,
        "offset": offset,
        "total": 0,
        "has_more": False,
    }
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id FROM official_matches WHERE id=%s", (match_id,))
        if cur.fetchone() is None:
            raise LookupError("所选比赛不存在")
        cur.execute(
            """SELECT m.*, b.source_name, b.imported_at, b.content_sha256,
                      b.normalization_version
               FROM football_history_matches m
               JOIN football_history_batches b ON b.id=m.batch_id AND b.state='published'
               WHERE m.official_match_id=%s AND b.source_name='titan007'
                 AND (%s::bigint IS NULL OR m.batch_id=%s)
               ORDER BY b.imported_at DESC,b.id DESC,m.source_match_id LIMIT 2""",
            (match_id, batch_id, batch_id),
        )
        candidates = cur.fetchall()
        if not candidates:
            if batch_id is not None:
                raise LookupError("所选批次没有该比赛的已发布历史资料")
            return result
        selected = candidates[0]
        if len(candidates) > 1 and candidates[1]["batch_id"] == selected["batch_id"]:
            return {**result, "status": "ambiguous"}
        batch = selected["batch_id"]
        source_match = selected["source_match_id"]
        result.update(
            status="available",
            batch={
                "id": batch,
                "source_name": selected["source_name"],
                "imported_at": selected["imported_at"],
                "content_sha256": selected["content_sha256"],
                "normalization_version": selected["normalization_version"],
            },
            source_match={
                "id": source_match,
                "home_name": selected["home_name"],
                "away_name": selected["away_name"],
                "kickoff_at": selected["kickoff_at"],
                "season": selected["source_season"],
                "status": selected["match_status"],
            },
        )
        cur.execute(
            """SELECT domain,count(*) AS n FROM football_history_records
               WHERE batch_id=%s AND source_match_id=%s AND domain=ANY(%s)
               GROUP BY domain""",
            (batch, source_match, list(HISTORY_DOMAINS)),
        )
        counts = {row["domain"]: row["n"] for row in cur.fetchall()}
        total = counts.get(domain, 0)
        result.update(counts=counts, total=total, has_more=offset + limit < total)
        if domain == "odds_history":
            cur.execute(
                """SELECT source_record_key,side,origin,value_json,change_at,time_basis,
                          time_resolution_reason,timeline_usable,change_timezone_basis,
                          effective_kickoff_at,kickoff_time_basis,time_resolution_version
                   FROM football_history_odds_timeline
                   WHERE batch_id=%s AND source_match_id=%s
                   ORDER BY value_json->>'company_id',value_json->>'odds_type',
                     value_json->>'source',
                     CASE WHEN value_json->>'seq' ~ '^[0-9]{1,9}$'
                       THEN (value_json->>'seq')::bigint END,source_record_key
                   LIMIT %s OFFSET %s""",
                (batch, source_match, limit, offset),
            )
        else:
            cur.execute(
                """SELECT source_record_key,side,origin,value_json FROM football_history_records
                   WHERE batch_id=%s AND source_match_id=%s AND domain=%s
                   ORDER BY CASE WHEN value_json->>'seq' ~ '^[0-9]{1,9}$'
                       THEN (value_json->>'seq')::bigint END,source_record_key
                   LIMIT %s OFFSET %s""",
                (batch, source_match, domain, limit, offset),
            )
        result["rows"] = [
            {
                "key": row["source_record_key"],
                "side": row["side"],
                "origin": row["origin"],
                "value": row["value_json"],
                "timeline": {key: row[key] for key in _TIME_FIELDS}
                if domain == "odds_history"
                else None,
            }
            for row in cur.fetchall()
        ]
    return result
