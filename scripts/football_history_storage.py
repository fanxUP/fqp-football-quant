"""Bounded shared-database reference reads; no acquisition or model activation."""

from typing import Literal

from psycopg2.extras import RealDictCursor

from scripts.football_fixture_identity import history_identity_conflicts
from scripts.football_season_identity import read_fixture_seasons

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
        "fixture_season": None,
        "counts": {},
        "rows": [],
        "limit": limit,
        "offset": offset,
        "total": 0,
        "has_more": False,
    }
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT source_match_id FROM official_matches WHERE id=%s", (match_id,))
        official = cur.fetchone()
        if official is None:
            raise LookupError("所选比赛不存在")
        cur.execute(
            """SELECT j.fixture_id,t.source_match_id FROM football_fixture_source_links j
               LEFT JOIN football_fixture_source_links t ON t.fixture_id=j.fixture_id
                 AND t.source_name='titan007' AND t.id_system='matchId'
               WHERE j.source_name='sporttery' AND j.id_system='jc.matchId'
                 AND j.source_match_id=%s""",
            (official["source_match_id"],),
        )
        linked = cur.fetchone()
        source_id = None
        if linked is not None:
            seasons = read_fixture_seasons(conn, [linked["fixture_id"]])
            if seasons:
                season = seasons[0]
                result["fixture_season"] = {
                    **{
                        key: season[key]
                        for key in (
                            "fixture_id",
                            "competition_id",
                            "competition_season_id",
                            "season_id",
                            "competition_code",
                            "season_code",
                            "season_name",
                            "planned_start_date",
                            "planned_end_date",
                            "source_timezone",
                            "source_competition_id",
                            "source_season_id",
                        )
                    },
                    "competition_name": season["competition_name_cn"],
                    "source_name": season["season_source_name"],
                    **{
                        target: {
                            key: season[source].get(key) for key in ("url", "sha256", "captured_at")
                        }
                        for target, source in (
                            ("boundary_evidence", "season_evidence"),
                            ("membership_evidence", "membership_evidence"),
                        )
                    },
                }
        if linked is not None and linked["source_match_id"] is not None:
            raw = linked["source_match_id"]
            if not (
                raw.isascii()
                and raw.isdecimal()
                and 1 <= len(raw) <= 16
                and 1 <= int(raw) <= 9007199254740991
                and str(int(raw)) == raw
            ):
                return {**result, "status": "ambiguous"}
            source_id = int(raw)
            if history_identity_conflicts(cur, match_id, source_id, batch_id=batch_id):
                return {**result, "status": "ambiguous"}
        cur.execute(
            """WITH candidates AS (
                 SELECT batch_id,source_match_id FROM football_history_matches
                 WHERE official_match_id=%s AND (%s::bigint IS NULL OR batch_id=%s)
                 UNION
                 SELECT m.batch_id,m.source_match_id FROM football_history_batches b
                 JOIN football_history_matches m ON m.batch_id=b.id AND m.source_match_id=%s
                 WHERE b.state='published' AND b.source_name='titan007'
                   AND (%s::bigint IS NULL OR m.batch_id=%s)
               )
               SELECT m.*, b.source_name, b.imported_at, b.content_sha256,
                      b.normalization_version
               FROM candidates c JOIN football_history_matches m
                 ON m.batch_id=c.batch_id AND m.source_match_id=c.source_match_id
               JOIN football_history_batches b ON b.id=m.batch_id AND b.state='published'
               WHERE b.source_name='titan007'
               ORDER BY b.imported_at DESC,b.id DESC,m.source_match_id LIMIT 2""",
            (match_id, batch_id, batch_id, source_id, batch_id, batch_id),
        )
        candidates = cur.fetchall()
        if not candidates:
            if batch_id is not None:
                raise LookupError("所选批次没有该比赛的已发布历史资料")
            return result
        selected = candidates[0]
        if (
            source_id is not None
            and any(
                row["source_match_id"] != source_id
                or row["official_match_id"] not in (None, match_id)
                for row in candidates
            )
            or len(candidates) > 1
            and candidates[1]["batch_id"] == selected["batch_id"]
        ):
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
