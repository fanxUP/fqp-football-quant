"""Collect a pre-kickoff 1X2 market reference for a traditional-only fixture."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.football_fixture_identity import IDENTITY_LOCK
from scripts.odds_conversion import normalize_probabilities
from scripts.prematch_schedule import beijing_time, pool_schedule_basis, prediction_target
from scripts.sources.titan007.client import (
    AcquisitionStopped,
    TitanClient,
    acquisition_session,
    decode_body,
)
from scripts.sources.titan007.odds import parse_1x2d, parse_1x2d_time
from scripts.sources.titan007.parsers import parse_history_page
from scripts.sporttery_pool_schedule import SCHEDULE_SOURCE
from scripts.titan007_data import cache_lock, data_directory

logger = logging.getLogger(__name__)
MAX_CHECKS = 4
QUOTE_MAX_AGE = timedelta(minutes=45)
PAGE_TTL_SECONDS = 10 * 60
NEXT_URL = "https://bf.titan007.com/football/Next_{:%Y%m%d}.htm"
ODDS_URL = "https://1x2d.titan007.com/{}.js"
ODDS_PAGE = "https://1x2.titan007.com/oddslist/{}.htm"
_pages: dict[date, tuple[float, list[dict], str]] = {}
_RETRY_READY = """r.published_at IS NULL AND r.checks<%s
    AND r.last_checked_at + LEAST(
        INTERVAL '15 minutes'*r.checks,
        GREATEST(INTERVAL '3 minutes',(r.kickoff_at-r.last_checked_at)/2)
    )<=%s"""


@dataclass(frozen=True)
class MarketTarget:
    fixture_id: int
    kickoff: datetime
    target: datetime
    sporttery_id: str
    league: str
    home: str
    away: str
    titan_id: str | None = None

    @property
    def key(self) -> tuple[int, datetime, datetime]:
        return self.fixture_id, self.kickoff, self.target


def _name(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def match_titan_fixture(target: MarketTarget, rows: list[dict]) -> dict | None:
    """Match complete names, ordered teams, the league and exact kickoff minute."""
    identity = tuple(_name(value) for value in (target.league, target.home, target.away))
    minute = target.kickoff.strftime("%Y-%m-%d %H:%M")
    matching = [
        row
        for row in rows
        if row["kickoff"] == minute
        and tuple(_name(row[key]) for key in ("league_name", "home_name", "away_name")) == identity
    ]
    ids = {(row["match_id"], row["league_id"]) for row in matching}
    if not all(identity) or len(ids) != 1:
        return None
    first = matching[0]
    if any(type(value) is not int or value <= 0 for value in next(iter(ids))) or (
        target.titan_id is not None and str(first["match_id"]) != target.titan_id
    ):
        return None
    if any(
        row["status_code"] not in (0, None)
        or (row["status_code"] is None and row.get("status_text"))
        or row.get("home_score") is not None
        or row.get("away_score") is not None
        for row in matching
    ):
        return None
    return first


def _source_clock(value: str | None) -> datetime | None:
    if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def read_current_quote(
    target: MarketTarget, row: dict, payload: dict, observed_at: datetime
) -> dict | None:
    """Cross-check the odds response and pick the freshest complete company."""
    meta = payload["meta"]
    kickoff = _source_clock(parse_1x2d_time(meta.get("MatchTime", "")))
    if (
        not target.target <= observed_at < target.kickoff
        or kickoff != target.kickoff
        or meta.get("ScheduleID") != str(row["match_id"])
        or meta.get("sclassId") != str(row["league_id"])
        or _name(meta.get("hometeam_cn", "")) != _name(row["home_name"])
        or _name(meta.get("guestteam_cn", "")) != _name(row["away_name"])
    ):
        return None
    companies = payload["companies"]
    counts = Counter(company["company_id"] for company in companies)
    quotes = []
    for company in companies:
        company_id = company["company_id"]
        company_name = company["company_name"].strip()
        quoted_at = _source_clock(company["change_time"])
        odds = {
            "h": company["live_home"],
            "d": company["live_draw"],
            "a": company["live_away"],
        }
        if (
            company_id > 0
            and counts[company_id] == 1
            and company_name
            and quoted_at is not None
            and observed_at - QUOTE_MAX_AGE <= quoted_at <= observed_at
            and all(
                value is not None and math.isfinite(value) and value > 1 for value in odds.values()
            )
        ):
            quotes.append((quoted_at, company_id, company_name, odds))
    if not quotes:
        return None
    quoted_at, company_id, company_name, odds = max(quotes, key=lambda item: (item[0], -item[1]))
    return {
        "method": "market_1x2_proportional/v1",
        "source": "titan007",
        "source_match_id": str(row["match_id"]),
        "company_id": company_id,
        "company_name": company_name,
        "quote_at": quoted_at.isoformat(),
        "odds": odds,
        "probabilities": normalize_probabilities(odds),
    }


def _current_targets(
    conn: Any, now: datetime, fixture_id: int | None = None
) -> dict[MarketTarget, list[dict]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.fixture_id,c.kickoff_time,c.source_match_id,c.league_name,
                      c.home_team_name,c.away_team_name,titan.source_match_id,
                      c.issue_id,i.sale_stop_time,c.game_type,c.issue_no,c.match_order
               FROM football_pool_fixture_catalog c
               JOIN football_pool_issues i ON i.id=c.issue_id
               LEFT JOIN football_fixture_source_links titan ON titan.fixture_id=c.fixture_id
                 AND titan.source_name='titan007' AND titan.id_system='matchId'
               WHERE c.kickoff_date BETWEEN %s AND %s AND c.kickoff_time>%s
                 AND (%s IS NULL OR c.fixture_id=%s)
                 AND c.official_match_id IS NULL AND c.identity_status='linked'
                 AND c.kickoff_time_precision IN ('minute','second')
                 AND c.source_result_source IS NULL AND c.source_game_type=c.game_type
                 AND c.source_raw_json->>'_source'=%s AND i.raw_json->>'_source'=%s
                 AND i.official_status IS DISTINCT FROM 'conflict'
                 AND c.source_match_id=c.source_raw_json->>'gmMatchId'
                 AND NOT EXISTS (
                   SELECT 1 FROM official_matches m WHERE m.source_match_id=c.source_match_id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM football_fixture_source_links jc WHERE jc.fixture_id=c.fixture_id
                     AND jc.source_name='sporttery' AND jc.id_system='jc.matchId'
                 )
               ORDER BY c.fixture_id,c.game_type,c.issue_id,c.match_order""",
            (
                now.date(),
                now.date() + timedelta(days=7),
                now.replace(tzinfo=None),
                fixture_id,
                fixture_id,
                SCHEDULE_SOURCE,
                SCHEDULE_SOURCE,
            ),
        )
        rows = cur.fetchall()
        if not rows:
            return {}
        cur.execute(
            """SELECT evidence FROM sporttery_schedule_notices
               WHERE published_at BETWEEN %s AND %s AND evidence->>'kind'='pool_schedule'
               ORDER BY published_at DESC, observed_at DESC""",
            (now - timedelta(days=14), now),
        )
        revisions: dict[tuple[str, str], tuple[dict, str]] = {}
        for (evidence,) in cur.fetchall():
            for issue in evidence["issues"]:
                revisions.setdefault(
                    (issue["game_type"], issue["issue_no"]), (issue, evidence["source_url"])
                )
    targets: dict[MarketTarget, list[dict]] = {}
    for fid, wall, sid, league, home, away, titan, issue, close, game, number, order in rows:
        kickoff = beijing_time(wall)
        basis = pool_schedule_basis(
            issue, close, game, order, kickoff, home, away, revisions.get((game, number))
        )
        if basis is None:
            continue
        cutoff, source = basis
        target, rule = prediction_target(kickoff, cutoff)
        if target <= now:
            market = MarketTarget(fid, kickoff, target, sid, league, home, away, titan)
            targets.setdefault(market, []).append(
                {
                    "issue_id": issue,
                    "issue_no": number,
                    "game_type": game,
                    "match_order": order,
                    "rule": rule,
                    "source": source,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                }
            )
    # Contradictory current memberships for the same physical slot require review.
    counts = Counter(target.key for target in targets)
    return {target: basis for target, basis in targets.items() if counts[target.key] == 1}


def _claim(conn: Any, target: MarketTarget, basis: list[dict], now: datetime) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO football_fixture_market_references AS r
                 (fixture_id,kickoff_at,target_at,schedule_basis)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (fixture_id,kickoff_at,target_at) DO UPDATE
               SET checks=r.checks+1,last_checked_at=clock_timestamp()
               WHERE """
            + _RETRY_READY
            + " RETURNING last_checked_at",
            (
                *target.key,
                Json({"sporttery_match_id": target.sporttery_id, "scopes": basis}),
                MAX_CHECKS,
                now,
            ),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _finish(
    target: MarketTarget,
    claimed: datetime,
    observed: datetime,
    reference: dict | None,
    reason: str | None,
) -> bool:
    with get_db() as conn, conn.cursor() as cur:
        if reference is None:
            cur.execute(
                """UPDATE football_fixture_market_references SET last_error=%s
                   WHERE (fixture_id,kickoff_at,target_at)=(%s,%s,%s)
                     AND last_checked_at=%s AND published_at IS NULL""",
                (reason, *target.key, claimed),
            )
            conn.commit()
            return False
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        if not cur.fetchone()[0]:
            return False
        now = beijing_time(datetime.now(UTC))
        basis = _current_targets(conn, now, target.fixture_id).get(target)
        if not basis:
            return False
        cur.execute(
            """SELECT COALESCE(a.canonical_fixture_id,l.fixture_id)
               FROM football_fixture_source_links l LEFT JOIN football_fixture_identity_aliases a
                 ON a.alias_fixture_id=l.fixture_id
               WHERE l.source_name='titan007' AND l.id_system='matchId' AND l.source_match_id=%s""",
            (reference["source_match_id"],),
        )
        binding = cur.fetchone()
        if binding and binding[0] != target.fixture_id:
            return False
        cur.execute(
            """WITH stamp AS MATERIALIZED (SELECT clock_timestamp() AS published)
               UPDATE football_fixture_market_references r
               SET quote_at=%s,observed_at=%s,published_at=stamp.published,
                   reference=%s,last_error=NULL,schedule_basis=%s
               FROM stamp WHERE (r.fixture_id,r.kickoff_at,r.target_at)=(%s,%s,%s)
                 AND r.last_checked_at=%s AND r.published_at IS NULL
                 AND stamp.published<r.kickoff_at""",
            (
                reference["quote_at"],
                observed,
                Json({key: value for key, value in reference.items() if key != "quote_at"}),
                Json(
                    {
                        "sporttery_match_id": target.sporttery_id,
                        "scopes": basis,
                        "timing": "late_dispatch"
                        if observed >= target.target + timedelta(minutes=1)
                        else "on_time",
                    }
                ),
                *target.key,
                claimed,
            ),
        )
        stored = cur.rowcount == 1
        conn.commit()
        return stored


def _collect(client: TitanClient, target: MarketTarget) -> tuple[dict | None, datetime, str | None]:
    candidates = []
    pages = {}
    day = target.kickoff.date()
    # The site's previous evening page contains post-midnight fixtures.
    days = (day - timedelta(days=1), day) if target.kickoff.hour < 12 else (day,)
    for page_day in days:
        url = NEXT_URL.format(page_day)
        if page_day not in _pages:
            raw, content_type = client.get_bytes(url)
            rows = parse_history_page(decode_body(raw, content_type), page_day)
            _pages[page_day] = (time.monotonic(), rows, hashlib.sha256(raw).hexdigest())
        _, rows, digest = _pages[page_day]
        candidates.extend(rows)
        pages[url] = digest
    match = match_titan_fixture(target, candidates)
    if match is None:
        return None, datetime.now(UTC), "fixture_unverified"
    source_id = match["match_id"]
    url = ODDS_URL.format(source_id)
    raw, content_type = client.get_bytes(url, referer=ODDS_PAGE.format(source_id))
    observed = datetime.now(UTC)
    reference = read_current_quote(
        target, match, parse_1x2d(decode_body(raw, content_type)), observed
    )
    if reference is None:
        return None, observed, "quote_unavailable"
    reference.update(
        source_url=url,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        fixture_pages=pages,
        source_league_id=match["league_id"],
        source_home=match["home_name"],
        source_away=match["away_name"],
    )
    return reference, observed, None


def run_due() -> dict:
    """Called only by the opted-in scheduler. Never hold a DB transaction over HTTP."""
    now = beijing_time(datetime.now(UTC))
    with get_db() as conn, conn.cursor() as cur:
        targets = _current_targets(conn, now)
        if targets:
            cur.execute(
                """SELECT fixture_id,kickoff_at,target_at
                   FROM football_fixture_market_references r
                   WHERE fixture_id=ANY(%s) AND NOT ("""
                + _RETRY_READY
                + ")",
                (sorted({target.fixture_id for target in targets}), MAX_CHECKS, now),
            )
            blocked = set(cur.fetchall())
            targets = {
                target: basis for target, basis in targets.items() if target.key not in blocked
            }
        if not targets:
            return {"status": "ok", "checked": 0, "published": 0}
    checked = published = 0
    run_id = None
    status = "ok"
    path = data_directory()
    try:
        with cache_lock(path):
            path.mkdir(parents=True, exist_ok=True)
            with acquisition_session(path, max_requests=6) as budget:
                client = TitanClient(timeout=8)
                for day, (loaded, _, _) in list(_pages.items()):
                    if time.monotonic() - loaded >= PAGE_TTL_SECONDS:
                        del _pages[day]
                for target in sorted(targets, key=lambda item: (item.kickoff, item.target)):
                    # Up to two page requests and one odds request for a cold fixture.
                    if checked == 2 or budget.requests > budget.max_requests - 3:
                        break
                    with get_db() as conn:
                        claimed = _claim(conn, target, targets[target], now)
                        conn.commit()
                    if claimed is None:
                        continue
                    if not checked:
                        run_id = start_tracked_job(
                            "traditional_market_reference", "crawler_agent", {}
                        )
                    checked += 1
                    try:
                        reference, observed, reason = _collect(client, target)
                    except AcquisitionStopped:
                        _finish(target, claimed, datetime.now(UTC), None, "source_unavailable")
                        raise
                    except (httpx.HTTPError, ValueError) as exc:
                        logger.info(
                            "Traditional market source unavailable for #%s: %s",
                            target.fixture_id,
                            exc,
                        )
                        reference, observed, reason = None, datetime.now(UTC), "source_unavailable"
                    published += _finish(target, claimed, observed, reference, reason)
    except AcquisitionStopped as exc:
        logger.info("Traditional market acquisition deferred: %s", exc)
        status = "partial"
    except Exception as exc:
        if isinstance(exc, RuntimeError) and isinstance(exc.__cause__, BlockingIOError):
            return {"status": "skipped", "checked": 0, "published": 0}
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
    result = {"status": status, "checked": checked, "published": published}
    finish_tracked_job(run_id, "completed" if status == "ok" else "failed", result)
    if checked:
        logger.info("Traditional market reference: checked=%s, published=%s", checked, published)
    return result
