"""Ingest the official upcoming traditional pool separately from draw results."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_now
from scripts.football_fixture_identity import IDENTITY_LOCK, TRADITIONAL_MATCH_COUNTS
from scripts.official_crawler import parse_traditional_lottery_response
from scripts.official_storage import store_pool_issue, store_pool_issue_matches
from scripts.play_type_registry import TRADITIONAL_SCHEDULE_GAME_CODES
from scripts.pool_issue_state import pool_time
from scripts.prematch_schedule import PREMATCH_NOTICE_LOCK
from scripts.sporttery_client import SportteryClient

logger = logging.getLogger(__name__)
SCHEDULE_SOURCE = "sporttery_live_schedule"
_DRAW_SECTIONS = {"t14c": "sfcDetail", "r9": "rjDetail", "bqc6": "bqcDetail", "jq4": "jqcDetail"}
SCHEDULE_GAMES = {
    code: (game, _DRAW_SECTIONS[game]) for game, code in TRADITIONAL_SCHEDULE_GAME_CODES.items()
}
_HEAD_REQUEST_LIMIT = 8
_EXTRA_ISSUE_LIMIT = 2
_HEAD_TTL = 20 * 60
_heads: dict[str, tuple[float, dict]] = {}
_issue_checks: dict[tuple[int, str], float] = {}
_EXACT_CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?")


def parse_current_issue(code: int, payload: dict, now: datetime) -> dict | None:
    """Only complete, explicitly typed, current lists can replace issue slots."""
    game, section = SCHEDULE_GAMES[code]
    value = payload.get("value")
    if not isinstance(value, dict):
        return None
    draw = value.get("drawMatch")
    issue_numbers = value.get("drawNumList")
    if not isinstance(draw, dict) or not isinstance(issue_numbers, list):
        return None
    issue_no = str(draw.get("lotteryDrawNum", ""))
    if (
        not re.fullmatch(r"\d{5,8}", issue_no)
        or issue_no not in {str(n) for n in issue_numbers}
        or str(draw.get("lotteryGameNum")) != str(code)
    ):
        return None
    matches = draw.get("matchList")
    if not isinstance(matches, list) or len(matches) != TRADITIONAL_MATCH_COUNTS[game]:
        return None
    if any(
        not isinstance(row, dict) or str(row.get("matchNum")) != str(order)
        for order, row in enumerate(matches, 1)
    ):
        return None
    source_ids = [str(row["gmMatchId"]) for row in matches if _positive_id(row.get("gmMatchId"))]
    if len(source_ids) != len(set(source_ids)):
        return None
    pool = parse_traditional_lottery_response({"value": {section: draw}}, now=now)[0]
    if pool["total_matches"] is None or pool["official_status"] == "conflict":
        return None
    if not any(
        row["kickoff_date"] and row["kickoff_date"] >= now.date().isoformat()
        for row in pool["matches"]
    ):
        return None
    if any(
        not isinstance(m[key], str) or not m[key].strip()
        for m in pool["matches"]
        for key in ("home_team_name", "away_team_name")
    ):
        return None
    # Keep the actual schedule code in the original JSON. 900129 cannot fit the
    # legacy draw code column, whose source/code constraints are draw-specific.
    pool["source_game_no"] = pool["source_game_no_source"] = None
    pool["raw_json"] = {**draw, "_source": SCHEDULE_SOURCE}
    for member in pool["matches"]:
        raw = member["raw_json"] = {**member["raw_json"], "_source": SCHEDULE_SOURCE}
        match_id = _positive_id(raw.get("gmMatchId"))
        if match_id:
            member["source_match_id"] = match_id
            member["source_ids"]["gmMatchId"] = match_id
        member["kickoff_evidence"]["source"] = SCHEDULE_SOURCE
    return pool


def _positive_id(value: Any) -> str | None:
    value = str(value)
    return value if re.fullmatch(r"[1-9]\d{0,17}", value) else None


def _team_matches(reported: Any, short: Any, full: str) -> bool:
    # The two official endpoints truncate some Chinese team names at different lengths.
    if not isinstance(reported, str) or not reported:
        return False
    return reported in (short, full) or (len(reported) >= 3 and full.startswith(reported))


def apply_match_head(member: dict, head: dict) -> bool:
    """Require the same official ID, teams, competition and selection date."""
    raw = member["raw_json"]
    kickoff_raw = head.get("matchDateTime")
    if (
        not member["source_ids"].get("gmMatchId")
        or _positive_id(head.get("sportteryMatchId")) != member["source_ids"]["gmMatchId"]
        or not isinstance(kickoff_raw, str)
        or not _EXACT_CLOCK.fullmatch(kickoff_raw)
        or str(head.get("sportteryTournamentId")) != str(raw.get("leagueId"))
        or head.get("sportteryTournamentId") is None
        or not _team_matches(
            head.get("homeTeamShortName"), raw.get("masterTeamName"), member["home_team_name"]
        )
        or not _team_matches(
            head.get("awayTeamShortName"), raw.get("guestTeamName"), member["away_team_name"]
        )
    ):
        return False
    kickoff = pool_time(kickoff_raw)
    if kickoff is None or kickoff.date().isoformat() != member["kickoff_date"]:
        return False
    if member["kickoff_time"] and pool_time(member["kickoff_time"]) != kickoff:
        return False
    member.update(
        kickoff_time=kickoff.isoformat(),
        kickoff_time_precision="second" if len(kickoff_raw) == 19 else "minute",
        kickoff_evidence={
            "source": "sporttery_match_head",
            "field": "matchDateTime",
            "raw_value": kickoff_raw,
            "sporttery_match_id": str(head["sportteryMatchId"]),
            "schedule_date": member["kickoff_date"],
        },
    )
    raw["_schedule_head"] = {
        key: head[key]
        for key in (
            "sportteryMatchId",
            "sportteryTournamentId",
            "matchDateTime",
            "homeTeamShortName",
            "awayTeamShortName",
        )
    }
    return True


def _mark_head_conflict(member: dict, head: dict) -> None:
    member["identity_block_reason"] = "schedule_head_conflict"
    member["kickoff_time"] = None
    member["kickoff_time_precision"] = "date_only" if member["kickoff_date"] else "unknown"
    member["kickoff_evidence"]["conflict"] = "sporttery_match_head"
    member["raw_json"]["_schedule_head_conflict"] = {
        key: head.get(key)
        for key in (
            "sportteryMatchId",
            "matchDateTime",
            "sportteryTournamentId",
            "homeTeamShortName",
            "awayTeamShortName",
        )
    }


def _store_current_issue(conn: Any, pool: dict) -> tuple[int, int]:
    # Pool identity writers share this lock. Keep issue and changed slots atomic.
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", PREMATCH_NOTICE_LOCK)
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        cur.execute(
            """SELECT i.id,i.raw_json,i.official_status,m.match_order,m.source_raw_json,
                      m.source_result_source,m.match_id
               FROM football_pool_issues i
               LEFT JOIN football_pool_issue_matches m ON m.issue_id=i.id
               WHERE i.game_type=%s AND i.issue_no=%s""",
            (pool["game_type"], pool["issue_no"]),
        )
        rows = cur.fetchall()
        if rows and any(row[5] for row in rows):
            # Result-bearing issue records remain owned by the draw/history path.
            return 0, 0
        existing = {row[3]: (row[4], row[6]) for row in rows}
        for member in pool["matches"]:
            raw = member["raw_json"]
            previous = existing.get(member["match_order"], (None, None))[0] or {}
            if (
                "_schedule_head" not in raw
                and "_schedule_head_conflict" not in raw
                and {k: v for k, v in previous.items() if not k.startswith("_schedule_head")} == raw
            ):
                if head := previous.get("_schedule_head"):
                    apply_match_head(member, head)
                elif conflict := previous.get("_schedule_head_conflict"):
                    _mark_head_conflict(member, conflict)
        changed = [
            member
            for member in pool["matches"]
            if existing.get(member["match_order"], (None, None))[0] != member["raw_json"]
        ]
        # Revisit a verified head if the JC collector has since stored that ID.
        bridge_candidates = {
            m["source_ids"]["gmMatchId"]
            for m in pool["matches"]
            if m["raw_json"].get("_schedule_head")
            and not existing.get(m["match_order"], (None, None))[1]
        }
        if bridge_candidates:
            cur.execute(
                """SELECT source_match_id,league_name,home_team_name,away_team_name,kickoff_time
                   FROM official_matches WHERE source_match_id=ANY(%s)""",
                (sorted(bridge_candidates),),
            )
            linked_matches = set(cur.fetchall())
            changed_orders = {m["match_order"] for m in changed}
            changed.extend(
                m
                for m in pool["matches"]
                if m["match_order"] not in changed_orders
                and not existing.get(m["match_order"], (None, None))[1]
                and m["raw_json"].get("_schedule_head")
                and (
                    m["source_ids"]["gmMatchId"],
                    m["league_name"],
                    m["home_team_name"],
                    m["away_team_name"],
                    pool_time(m["kickoff_time"]).replace(tzinfo=None),
                )
                in linked_matches
            )
        header_changed = not rows or rows[0][1:3] != (pool["raw_json"], pool["official_status"])
        if not header_changed and not changed:
            return 0, 0
        issue_id = (
            store_pool_issue(conn, **{k: v for k, v in pool.items() if k != "matches"})
            if header_changed
            else rows[0][0]
        )
        return int(header_changed), store_pool_issue_matches(
            conn, issue_id, changed
        ) if changed else 0


def refresh_current_pool_schedule() -> dict:
    """Refresh current issues and rotate through additionally listed issues."""
    now = business_now()
    started = time.monotonic()
    client = SportteryClient(timeout=6, max_retries=1)
    pools = []
    failed = 0

    def read_issue(code: int, issue_no: str | None = None) -> dict:
        nonlocal failed
        try:
            payload = client.get_traditional_lottery_schedule(code, issue_no)
            pool = parse_current_issue(code, payload, now)
            if pool and (issue_no is None or pool["issue_no"] == issue_no):
                pools.append(pool)
            value = payload.get("value")
            return value if isinstance(value, dict) else {}
        except (RuntimeError, ValueError) as exc:
            logger.warning("Traditional schedule source unavailable (%s): %s", code, exc)
            failed += 1
            return {}

    try:
        extra = set()
        for code in SCHEDULE_GAMES:
            value = read_issue(code)
            draw = value.get("drawMatch")
            numbers = value.get("drawNumList")
            current = str(draw.get("lotteryDrawNum")) if isinstance(draw, dict) else None
            if isinstance(numbers, list):
                extra.update(
                    (code, str(n))
                    for n in numbers[:10]
                    if str(n) != current and re.fullmatch(r"\d{5,8}", str(n))
                )
        for key in set(_issue_checks) - extra:
            del _issue_checks[key]
        for key in sorted(extra, key=lambda item: (_issue_checks.get(item, 0), item))[
            :_EXTRA_ISSUE_LIMIT
        ]:
            _issue_checks[key] = started
            read_issue(*key)

        members = sorted(
            (
                m
                for pool in pools
                for m in pool["matches"]
                if m["source_ids"].get("gmMatchId")
                and (m["kickoff_date"] or "") >= now.date().isoformat()
            ),
            key=lambda m: m["kickoff_date"],
        )
        ids = dict.fromkeys(member["source_ids"]["gmMatchId"] for member in members)
        for key in set(_heads) - ids.keys():
            del _heads[key]
        candidates = sorted(ids, key=lambda key: _heads.get(key, (0, {}))[0])
        requests = [key for key in candidates if _heads.get(key, (0, {}))[0] <= started]
        requests = requests[:_HEAD_REQUEST_LIMIT]
        for match_id in requests:
            try:
                response = client.get_match_head(match_id).get("value")
            except RuntimeError as exc:
                logger.warning(
                    "Traditional schedule match head unavailable (%s): %s", match_id, exc
                )
                response = None
                failed += 1
            _heads[match_id] = (started + _HEAD_TTL, response if isinstance(response, dict) else {})
        for member in members:
            _, head = _heads.get(member["source_ids"]["gmMatchId"], (0, {}))
            if head and not apply_match_head(member, head):
                _mark_head_conflict(member, head)
    finally:
        client.close()

    issues_written = matches_written = 0
    if pools:
        with get_db() as conn:
            for pool in pools:
                i, m = _store_current_issue(conn, pool)
                issues_written += i
                matches_written += m
            conn.commit()
    return {
        "status": "partial" if failed else "ok",
        "pools_found": len(pools),
        "issues_written": issues_written,
        "matches_written": matches_written,
        "head_requests": len(requests),
        "source_failures": failed,
    }
