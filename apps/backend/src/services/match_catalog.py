"""One bounded current/history contract for match-center reads."""

from datetime import date, timedelta
from typing import Any, Literal

from scripts.business_time import business_now

RECENT_MATCH_HOURS = 48
FINAL_STATUSES = ("finished", "settled", "completed", "cancelled", "canceled", "stopped")


def read_match_catalog(
    conn: Any,
    *,
    scope: Literal["current", "history"],
    date_from: date | None,
    date_to: date | None,
    q: str,
    league: str,
    status: str,
    sort: Literal["asc", "desc"],
    limit: int,
    offset: int,
    selected_id: int | None,
    upcoming_only: bool,
) -> dict:
    now = business_now().replace(tzinfo=None)
    since = now - timedelta(hours=RECENT_MATCH_HOURS)
    current = """m.kickoff_time >= %(since)s
        AND LOWER(COALESCE(m.match_status,'')) NOT IN %(final)s
        AND COALESCE(r.result_status,'') <> 'confirmed'"""
    scope_filter = (
        f"({current})"
        if scope == "current"
        else f"NOT ({current}) AND m.business_date BETWEEN %(date_from)s AND %(date_to)s"
    )
    direction = "DESC" if sort == "desc" else "ASC"
    search = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    params = {
        "now": now,
        "since": since,
        "final": FINAL_STATUSES,
        "date_from": date_from,
        "date_to": date_to,
        "q": f"%{search}%",
        "league": league,
        "status": status,
        "limit": limit,
        "offset": offset,
        "selected_id": selected_id,
        "upcoming_only": upcoming_only,
    }
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH scoped AS MATERIALIZED (
                SELECT m.id AS match_id, m.league_name, m.home_team_name,
                       m.away_team_name, m.kickoff_time, m.business_date,
                       COALESCE(NULLIF(m.match_status,''),'unknown') AS match_status,
                       COALESCE(m.raw_json->>'matchNumStr',m.official_match_code) AS match_num_str,
                       COALESCE(r.result_status,'missing') AS result_status,
                       CASE WHEN r.result_status='confirmed'
                            AND LOWER(COALESCE(m.match_status,'')) NOT IN %(final)s
                            THEN '已收录确认赛果，来源比赛状态待同步'
                            WHEN m.kickoff_time <= %(now)s
                            AND LOWER(COALESCE(m.match_status,''))
                                IN ('','scheduled','selling','not_started')
                            AND COALESCE(r.result_status,'') <> 'confirmed'
                            THEN '开球时间已过，实际状态待核实' ELSE NULL END AS status_note
                FROM official_matches m
                LEFT JOIN official_results r ON r.match_id=m.id
                WHERE m.sport_type='football'
                  AND m.official_match_code ~ '^周[一二三四五六日][0-9]{{3}}$'
                  AND {scope_filter}
            ), filtered AS MATERIALIZED (
                SELECT *, ROW_NUMBER() OVER (ORDER BY kickoff_time {direction},match_id) AS ordinal
                FROM scoped
                WHERE (%(league)s='' OR league_name=%(league)s)
                  AND (%(status)s='' OR match_status=%(status)s)
                  AND CONCAT_WS(' ',match_id,match_num_str,league_name,
                                home_team_name,away_team_name) ILIKE %(q)s
                  AND (NOT %(upcoming_only)s OR kickoff_time > %(now)s)
            ), page_info AS (
                SELECT COUNT(*) AS total,
                    COALESCE(
                        (SELECT ((ordinal-1)/%(limit)s)*%(limit)s FROM filtered
                         WHERE match_id=%(selected_id)s),
                        LEAST(%(offset)s,GREATEST((COUNT(*)-1)/%(limit)s,0)*%(limit)s)
                    ) AS page_offset
                FROM filtered
            )
            SELECT COALESCE((
                       SELECT JSONB_AGG(TO_JSONB(p)-'ordinal' ORDER BY ordinal)
                       FROM (SELECT * FROM filtered
                             WHERE ordinal > page_info.page_offset
                               AND ordinal <= page_info.page_offset+%(limit)s) p
                   ),'[]'::jsonb), total, page_offset,
                   ARRAY(SELECT DISTINCT league_name FROM scoped ORDER BY league_name),
                   ARRAY(SELECT DISTINCT match_status FROM scoped ORDER BY match_status),
                   EXISTS(SELECT 1 FROM scoped WHERE match_id=%(selected_id)s),
                   EXISTS(SELECT 1 FROM filtered WHERE match_id=%(selected_id)s),
                   (SELECT COUNT(*) FROM scoped WHERE kickoff_time <= %(now)s)
            FROM page_info
            """,
            params,
        )
        rows, total, effective_offset, leagues, statuses, in_scope, in_filter, started = (
            cur.fetchone()
        )
    return {
        "matches": rows,
        "total": total,
        "offset": effective_offset,
        "limit": limit,
        "scope": scope,
        "leagues": leagues,
        "statuses": statuses,
        "selected_in_scope": in_scope,
        "selected_in_filter": in_filter,
        "started_total": started,
        "as_of": now.isoformat(),
        "current_since": since.isoformat(),
    }
