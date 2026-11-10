"""Read saved, third-party 1X2 prices for verified official matches."""

import logging
from math import isfinite

from psycopg2.errors import QueryCanceled, UndefinedTable

from apps.backend.src.db import get_db

_logger = logging.getLogger(__name__)

# Use a single company/feed for both opening and latest prices. Alternate lines
# only fill a missing brand row. Company IDs are scoped to the feed.
_BRAND_FEEDS = {
    "betfair": tuple((cid, "1x2d") for cid in (2, 1055, 988, 1036, 1599, 1600, 1601)),
    "crown": ((545, "1x2d"), (3, "vip"), (3, "feed")),
    "ysb": ((12, "vip"),),
    "macau": ((80, "1x2d"),),
    "ladbrokes": ((82, "1x2d"),),
    "william_hill": ((115, "1x2d"),),
    "pinnacle": ((177, "1x2d"),),
    "bet365": ((281, "1x2d"),),  # 537 has been returned as Bet3000.
}
_FEED_PRIORITY = {
    (str(company_id), source): (brand, rank)
    for brand, feeds in _BRAND_FEEDS.items()
    for rank, (company_id, source) in enumerate(feeds)
}

_REFERENCE_SQL = """
WITH requested AS MATERIALIZED (
    SELECT o.id, t.source_match_id AS bridge,
           CASE WHEN t.source_match_id ~ '^[1-9][0-9]{0,15}$'
                THEN t.source_match_id::bigint END AS source_id
    FROM official_matches o
    LEFT JOIN football_fixture_source_links j ON j.source_name='sporttery'
      AND j.id_system='jc.matchId' AND j.source_match_id=o.source_match_id
    LEFT JOIN football_fixture_source_links t ON t.fixture_id=j.fixture_id
      AND t.source_name='titan007' AND t.id_system='matchId'
    WHERE o.id=ANY(%s)
), candidates AS (
    SELECT r.id, r.bridge, m.batch_id, m.source_match_id, m.official_match_id
    FROM requested r JOIN football_history_matches m ON m.official_match_id=r.id
    UNION
    SELECT r.id, r.bridge, m.batch_id, m.source_match_id, m.official_match_id
    FROM requested r
    JOIN football_history_batches b ON b.state='published' AND b.source_name='titan007'
    JOIN football_history_matches m ON m.batch_id=b.id AND m.source_match_id=r.source_id
), resolved AS (
    SELECT c.id, min(c.source_match_id) AS source_match_id,
           (array_agg(c.batch_id ORDER BY b.imported_at DESC, b.id DESC))[1] AS batch_id
    FROM candidates c JOIN football_history_batches b ON b.id=c.batch_id
    WHERE b.state='published' AND b.source_name='titan007'
    GROUP BY c.id
    HAVING count(DISTINCT c.source_match_id)=1 AND bool_and(
        (c.official_match_id IS NULL OR c.official_match_id=c.id)
        AND (c.bridge IS NULL OR c.source_match_id::text=c.bridge)
    )
)
SELECT m.id, quote.value_json
FROM resolved m
CROSS JOIN LATERAL (
    SELECT r.value_json
    FROM football_history_records r
    WHERE r.batch_id=m.batch_id AND r.source_match_id=m.source_match_id
      AND r.domain='odds' AND r.value_json->>'odds_type'='europe'
      AND r.value_json->>'company_id'=ANY(%s)
    OFFSET 0
) quote
"""


def _decimal_odds(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if isfinite(number) and number > 1 else None


def read_market_reference(match_ids: list[int]) -> dict[int, dict] | None:
    """Return at most one saved quote per match/brand, or None on read failure."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='2s'")
            company_ids = sorted({str(cid) for cid, _ in _FEED_PRIORITY})
            cur.execute(_REFERENCE_SQL, (match_ids, company_ids))
            rows = cur.fetchall()
    except (QueryCanceled, UndefinedTable) as exc:
        _logger.warning("Odds market reference unavailable: %s", type(exc).__name__)
        return None

    result: dict[int, dict] = {}
    priorities: dict[tuple[int, str], int] = {}
    for match_id, quote in rows:
        feed = _FEED_PRIORITY.get((str(quote.get("company_id")), str(quote.get("source"))))
        if feed is None:
            continue
        brand, rank = feed
        previous_rank = priorities.get((match_id, brand))
        if previous_rank is not None and previous_rank <= rank:
            continue
        opening = [
            _decimal_odds(quote.get(f"initial_{option}")) for option in ("home", "line", "away")
        ]
        latest = [_decimal_odds(quote.get(f"live_{option}")) for option in ("home", "line", "away")]
        if any(value is not None for value in (*opening, *latest)):
            result.setdefault(match_id, {})[brand] = {"opening": opening, "latest": latest}
            priorities[match_id, brand] = rank
    return result
