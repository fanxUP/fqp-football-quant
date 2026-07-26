"""Official data crawler for sporttery.cn (竞彩网).

Orchestrates: fetch → parse → validate → store.
Every crawl records raw_json + raw_hash.

Data quality rules (from docs/04):
  - match_code must not be null
  - team names must not be null
  - SP values must be > 0
  - handicap play must have a handicap value
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_now, business_today
from scripts.official_storage import (
    log_crawl,
    record_official_collection_status,
    store_markets,
    store_matches,
    store_pool_issue,
    store_pool_issue_matches,
    store_results,
    update_health,
)
from scripts.play_type_registry import (
    OPTION_LABELS,
    TRADITIONAL_GAME_TYPES,
)
from scripts.play_type_registry import (
    SPORTTERY_POOL_MAP as POOL_CODE_MAP,
)
from scripts.result_status import is_void_official_result
from scripts.sporttery_client import SportteryClient


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Parser: sporttery JSON → normalized internal dicts
# ---------------------------------------------------------------------------

# Map sporttery saleStatus codes
_SALE_STATUS_MAP: dict[int, str] = {
    0: "not_started",
    1: "selling",
    2: "selling",
    3: "stopped",
    4: "finished",
}

_DIRECT_ODDS_NODES: dict[str, str] = {
    "HAD": "had",
    "HHAD": "hhad",
    "CRS": "crs",
    "TTG": "ttg",
    "HAFU": "hafu",
}

_HAFU_OPTIONS: dict[str, tuple[str, str]] = {
    "hh": ("33", "胜胜"),
    "hd": ("31", "胜平"),
    "ha": ("30", "胜负"),
    "dh": ("13", "平胜"),
    "dd": ("11", "平平"),
    "da": ("10", "平负"),
    "ah": ("03", "负胜"),
    "ad": ("01", "负平"),
    "aa": ("00", "负负"),
}


def _pool_enabled(pool: dict[str, Any], *fields: str) -> bool:
    return any(pool.get(field, 0) == 1 for field in fields)


def _pool_is_open(pool: dict[str, Any] | None, has_odds: bool) -> bool:
    if not pool or not pool.get("poolStatus"):
        return has_odds
    return str(pool["poolStatus"]).lower() == "selling"


def _market_status(pool: dict[str, Any] | None, is_open: bool) -> str:
    if is_open:
        return "open"
    status = str((pool or {}).get("poolStatus") or "closed").strip().lower()
    return status or "closed"


def _odds_by_pool(match_raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return odds nodes from either match-list or calculator payloads."""
    odds_by_pool: dict[str, dict[str, Any]] = {}
    for odds in match_raw.get("oddsList", []) or []:
        pool_code = odds.get("poolCode", "")
        if pool_code and pool_code not in odds_by_pool:
            odds_by_pool[pool_code] = odds
    for pool_code, node_name in _DIRECT_ODDS_NODES.items():
        node = match_raw.get(node_name)
        if isinstance(node, dict) and node:
            odds_by_pool[pool_code] = node
    return odds_by_pool


def parse_matches_from_response(
    raw: dict[str, Any],
    business_date: str,
) -> list[dict[str, Any]]:
    """Parse Sporttery match-list or calculator responses into normalized matches.

    Real API structure (2026-07 observed):
      value.matchInfoList[].businessDate   — betting publish date
      value.matchInfoList[].subMatchList[] — array of matches
        matchDate + matchTime → kickoff_time
        oddsList[] has HAD/HHAD; calculator payloads additionally expose
        had/hhad/crs/ttg/hafu nodes with complete current odds.
    """
    matches: list[dict] = []
    match_info_list = raw.get("value", {}).get("matchInfoList", [])
    if not match_info_list:
        match_info_list = raw.get("matchInfoList", [])

    for day_block in match_info_list:
        bdate = day_block.get("businessDate", business_date)
        for sub in day_block.get("subMatchList", []):
            # Keep Sporttery's display code (e.g. 周五098) as the canonical
            # official identifier. The numeric matchNum is only an internal
            # Sporttery id and is not what users see on the ticket.
            match_code = str(sub.get("matchNumStr") or sub.get("matchNum", ""))
            if not match_code:
                continue

            home_name = sub.get("homeTeamAllName", "")
            away_name = sub.get("awayTeamAllName", "") or sub.get("awayTeamAbbName", "")
            if not home_name or not away_name:
                continue

            league = sub.get("leagueAllName", "") or sub.get("leagueAbbName", "")

            # Combine matchDate + matchTime → kickoff_time
            match_date = sub.get("matchDate", "")
            match_time = sub.get("matchTime", "")
            kickoff: str | None
            if match_date and match_time:
                kickoff = f"{match_date}T{match_time}"
            else:
                kickoff = match_date or match_time or None

            # saleStatus is a number in real API
            sale_status_raw = sub.get("saleStatus", sub.get("sellStatus"))
            if isinstance(sale_status_raw, int) or (
                isinstance(sale_status_raw, str) and sale_status_raw.isdigit()
            ):
                sale_status = _SALE_STATUS_MAP.get(int(sale_status_raw), "unknown")
            else:
                sale_status = str(sale_status_raw) if sale_status_raw else "unknown"

            # The match-list endpoint exposes HAD/HHAD in oddsList, while
            # poolList is authoritative for all five available play types.
            # The calculator endpoint additionally exposes direct had/hhad/
            # crs/ttg/hafu nodes with the complete current odds.
            markets: list[dict] = []
            odds_by_pool = _odds_by_pool(sub)
            pools_by_code = {
                pool.get("poolCode", ""): pool
                for pool in sub.get("poolList", []) or []
                if pool.get("poolCode")
            }
            pool_codes = list(dict.fromkeys([*pools_by_code, *odds_by_pool]))
            for pool_code in pool_codes:
                odds = odds_by_pool.get(pool_code, {})
                pool = pools_by_code.get(pool_code)
                play_type = POOL_CODE_MAP.get(pool_code, pool_code.lower())
                handicap = odds.get("goalLine")
                if handicap is not None and handicap != "":
                    try:
                        handicap_val = float(handicap)
                    except ValueError, TypeError:
                        handicap_val = None
                else:
                    handicap_val = None

                is_open = _pool_is_open(pool, bool(odds))
                raw_market = {**odds, "_pool": pool or {}}
                markets.append(
                    {
                        "play_type": play_type,
                        "handicap": handicap_val,
                        "is_open": is_open,
                        "is_single_allowed": is_open
                        and _pool_enabled(
                            pool or {}, "single", "bettingSingle", "cbtSingle", "intSingle"
                        ),
                        "is_pass_allowed": is_open
                        and _pool_enabled(
                            pool or {}, "allUp", "bettingAllup", "cbtAllUp", "intAllUp"
                        ),
                        "market_status": _market_status(pool, is_open),
                        "raw_json": raw_market,
                    }
                )

            source_endpoint = (
                "getMatchCalculatorV1.qry"
                if any(node in sub for node in _DIRECT_ODDS_NODES.values())
                else "getMatchListV1.qry"
            )

            matches.append(
                {
                    "sport_type": "football",
                    "business_date": bdate,
                    "official_match_code": match_code,
                    "league_name": league,
                    "home_team_name": home_name,
                    "away_team_name": away_name,
                    "kickoff_time": kickoff,
                    "sale_stop_time": None,  # sporttery API doesn't expose this directly
                    "sale_status": sale_status,
                    "match_status": "scheduled",
                    "source_url": f"https://webapi.sporttery.cn/gateway/uniform/football/{source_endpoint}",
                    "raw_json": sub,
                    "_markets": markets,
                }
            )

    return matches


def parse_odds_snapshots_from_match(
    match_raw: dict[str, Any],
    snapshot_time: str | None = None,
) -> list[dict[str, Any]]:
    """Parse a single match's current odds into snapshot dicts.

    Each snapshot = one option (e.g., 主胜 at SP 1.50).
    A match with HAD + HHAD = 6 snapshot rows (3 options × 2 play types).
    """
    snapshots: list[dict] = []
    snap_time = snapshot_time or _now()
    match_raw.get("kickoffTime") or match_raw.get("matchTime")
    sale_stop = match_raw.get("stopSaleTime") or match_raw.get("saleStopTime")

    # Calculate minutes before sale stop
    minutes_before_stop: int | None = None
    if sale_stop:
        try:
            if isinstance(sale_stop, str) and "T" in sale_stop:
                stop_dt = datetime.fromisoformat(sale_stop.replace("Z", "+00:00"))
                now_dt = datetime.fromisoformat(snap_time.replace("Z", "+00:00"))
                minutes_before_stop = int((stop_dt - now_dt).total_seconds() / 60)
        except ValueError, TypeError:
            pass

    odds_by_pool = _odds_by_pool(match_raw)
    pools_by_code = {
        pool.get("poolCode", ""): pool
        for pool in match_raw.get("poolList", []) or []
        if pool.get("poolCode")
    }
    for pool_code, odds in odds_by_pool.items():
        play_type = POOL_CODE_MAP.get(pool_code, pool_code.lower())
        pool = pools_by_code.get(pool_code)
        is_open = _pool_is_open(pool, True)
        if not is_open:
            continue
        is_single = _pool_enabled(pool or {}, "single", "bettingSingle", "cbtSingle", "intSingle")
        is_pass = _pool_enabled(pool or {}, "allUp", "bettingAllup", "cbtAllUp", "intAllUp")
        handicap = odds.get("goalLine")
        if handicap is not None and handicap != "":
            try:
                handicap_val = float(handicap)
            except ValueError, TypeError:
                handicap_val = None
        else:
            handicap_val = None

        option_rows: list[tuple[str, str, Any]] = []
        if pool_code in {"HAD", "HHAD"}:
            labels = OPTION_LABELS[play_type]
            option_rows = [(code, labels[code], odds.get(code)) for code in ("h", "d", "a")]
        elif pool_code == "CRS":
            other = {
                "s1sh": ("other_h", "胜其他"),
                "s1sd": ("other_d", "平其他"),
                "s1sa": ("other_a", "负其他"),
            }
            for source_code, sp_value in odds.items():
                if source_code.endswith("f"):
                    continue
                if source_code in other:
                    option_code, option_name = other[source_code]
                elif match := re.fullmatch(r"s(\d{1,2})s(\d{1,2})", source_code):
                    option_code = f"{int(match.group(1))}:{int(match.group(2))}"
                    option_name = option_code
                else:
                    continue
                option_rows.append((option_code, option_name, sp_value))
        elif pool_code == "TTG":
            option_rows = [
                (str(goals), "7+" if goals == 7 else f"{goals}球", odds.get(f"s{goals}"))
                for goals in range(8)
            ]
        elif pool_code == "HAFU":
            option_rows = [
                (option_code, option_name, odds.get(source_code))
                for source_code, (option_code, option_name) in _HAFU_OPTIONS.items()
            ]

        for option_code, option_name, sp_value in option_rows:
            try:
                sp_val = float(sp_value)
            except ValueError, TypeError:
                continue
            if sp_val <= 0:
                continue  # rule: SP must be positive

            snapshots.append(
                {
                    "snapshot_time": snap_time,
                    "snapshot_label": f"{play_type}_{option_code}",
                    "minutes_before_stop": minutes_before_stop,
                    "play_type": play_type,
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_val,
                    "handicap": handicap_val,
                    "is_open": True,
                    "is_single_allowed": is_single,
                    "is_pass_allowed": is_pass,
                    "raw_json": {**odds, "_pool": pool or {}},
                }
            )

    return snapshots


def _derive_official_handicap_result(
    home_goals: int | None, away_goals: int | None, handicap: Any
) -> str | None:
    if home_goals is None or away_goals is None or handicap in (None, ""):
        return None
    try:
        adjusted_home = home_goals + float(handicap)
    except TypeError, ValueError:
        return None
    if adjusted_home > away_goals:
        return "3"
    if adjusted_home == away_goals:
        return "1"
    return "0"


def parse_results_from_response(
    raw: dict[str, Any],
) -> list[dict[str, Any]]:
    """Parse sporttery getMatchResultV1 response into normalized result dicts.

    Returns a list of result dicts ready for store_results().
    Each result is keyed by match_id (resolved later via official_match_code lookup).
    """
    results: list[dict] = []
    result_list = raw.get("value", {}).get("matchResultList", [])
    if not result_list:
        result_list = raw.get("value", {}).get("matchInfoList", [])
    if not result_list:
        result_list = raw.get("value", {}).get("matchResult", [])
    if not result_list:
        result_list = raw.get("matchResultList", [])
    if not result_list:
        result_list = raw.get("matchInfoList", [])
    if not result_list:
        result_list = raw.get("matchResult", [])

    for item in result_list:
        # ``matchNumStr`` is the ticket-visible identifier (for example
        # 周五098). ``matchNum`` may be a numeric Sporttery internal value in
        # some responses and must not replace the display code.
        match_code = item.get("matchNumStr") or item.get("matchCode") or item.get("matchNum", "")
        if not match_code:
            continue

        # Goals
        def _first_present(row: dict[str, Any], *keys: str) -> Any:
            for key in keys:
                value = row.get(key)
                if value is not None and value != "":
                    return value
            return None

        def _score_parts(value: Any) -> tuple[Any, Any]:
            if not isinstance(value, str):
                return None, None
            parts = value.replace("：", ":").split(":", 1)
            return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, None)

        section_half_home, section_half_away = _score_parts(item.get("sectionsNo1"))
        section_full_home, section_full_away = _score_parts(item.get("sectionsNo999"))
        half_home = _first_present(item, "halfHomeGoals", "halfHomeScore")
        half_away = _first_present(item, "halfAwayGoals", "halfAwayScore")
        full_home = _first_present(item, "fullHomeGoals", "fullHomeScore", "homeGoals")
        full_away = _first_present(item, "fullAwayGoals", "fullAwayScore", "awayGoals")
        half_home = section_half_home if half_home is None else half_home
        half_away = section_half_away if half_away is None else half_away
        full_home = section_full_home if full_home is None else full_home
        full_away = section_full_away if full_away is None else full_away

        # Convert to int if present
        def _to_int(v: Any) -> int | None:
            if v is None:
                return None
            try:
                return int(v)
            except ValueError, TypeError:
                return None

        # Build win/draw/loss result codes from scores
        fh = _to_int(full_home)
        fa = _to_int(full_away)
        hh = _to_int(half_home)
        ha = _to_int(half_away)

        spf = None
        if fh is not None and fa is not None:
            spf = "3" if fh > fa else ("1" if fh == fa else "0")

        # Score result as string
        score = None
        if fh is not None and fa is not None:
            score = f"{fh}:{fa}"

        # Half/full result
        half_full = None
        if hh is not None and ha is not None:
            h_code = "3" if hh > ha else ("1" if hh == ha else "0")
            f_code = (
                "3"
                if (fh is not None and fa is not None and fh > fa)
                else ("1" if (fh is not None and fa is not None and fh == fa) else "0")
            )
            half_full = f"{h_code}-{f_code}"

        results.append(
            {
                "_source_match_id": str(item.get("matchId") or ""),
                "_match_code": match_code,
                "_match_date": item.get("matchDate"),
                "half_home_goals": hh,
                "half_away_goals": ha,
                "full_home_goals": fh,
                "full_away_goals": fa,
                "spf_result": spf,
                "rqspf_result": _derive_official_handicap_result(fh, fa, item.get("goalLine")),
                "total_goals_result": fh + fa if fh is not None and fa is not None else None,
                "score_result": score,
                "half_full_result": half_full,
                "result_status": (
                    "void"
                    if is_void_official_result(item, item.get("resultStatus"))
                    else (
                        "confirmed"
                        if str(item.get("matchResultStatus") or "") == "2"
                        or item.get("poolStatus") == "Payout"
                        else item.get("resultStatus") or "pending"
                    )
                ),
                "official_publish_time": item.get("publishTime") or item.get("officialPublishTime"),
                "raw_json": item,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Orchestration: crawl functions
# ---------------------------------------------------------------------------


def crawl_official_schedule(business_date: str) -> dict[str, Any]:
    """Fetch today's match schedule + markets from sporttery.cn and store.

    Returns a summary dict with counts and status.
    """
    started = _now()
    client = SportteryClient()
    try:
        # 1. Fetch
        t0 = time.monotonic()
        raw = client.get_daily_matches(business_date)
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 2. Parse
        matches = parse_matches_from_response(raw, business_date)
        if not matches:
            client.close()
            with get_db() as conn:
                log_crawl(
                    conn,
                    source_name="sporttery",
                    crawl_type="schedule",
                    status="ok",
                    records_found=0,
                    started_at=started,
                )
                update_health(conn, "sporttery", "schedule", "ok", latency_ms)
            return {
                "status": "ok",
                "matches_found": 0,
                "matches_stored": 0,
                "note": "no matches in response",
            }

        # 3. Store matches
        with get_db() as conn:
            match_result = store_matches(conn, matches)
            total_inserted = match_result["inserted"]
            total_updated = match_result["updated"]

            # 4. Store markets for each match
            # We need match IDs from the DB. Query back by official_match_code.
            for m in matches:
                code = m["official_match_code"]
                bdate = m["business_date"]
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM official_matches "
                        "WHERE official_match_code = %s AND business_date = %s",
                        (code, bdate),
                    )
                    row = cur.fetchone()
                if row is None:
                    continue
                match_id = row[0]
                store_markets(conn, match_id, m.get("_markets", []))

            # 5. Log
            total_markets = sum(len(m.get("_markets", [])) for m in matches)
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="schedule",
                status="ok",
                records_found=len(matches),
                records_inserted=total_inserted,
                records_updated=total_updated,
                started_at=started,
            )
            update_health(conn, "sporttery", "schedule", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "matches_found": len(matches),
            "matches_inserted": total_inserted,
            "matches_updated": total_updated,
            "markets_processed": total_markets,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        latency_ms = 0
        with get_db() as conn:
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="schedule",
                status="error",
                error_message=str(e),
                started_at=started,
            )
            update_health(conn, "sporttery", "schedule", "error", latency_ms, str(e))
        return {"status": "error", "error": str(e)}


def crawl_official_odds_snapshot(business_date: str) -> dict[str, Any]:
    """Compatibility wrapper around the durable due-capture dispatcher."""
    from scripts.official_odds_capture import collect_due_official_odds

    return collect_due_official_odds()


def crawl_official_results(begin_date: str, end_date: str) -> dict[str, Any]:
    """Fetch and store match results for a date range.

    Results come only from the China Sports Lottery result page's Uniform API.
    A blocked official source is reported as an error and never replaced.
    """
    started = _now()
    client = SportteryClient()

    # ── Attempt 1: Sporttery API ──────────────────────────────────────
    try:
        t0 = time.monotonic()
        raw = client.get_uniform_match_results(begin_date, end_date)
        latency_ms = int((time.monotonic() - t0) * 1000)

        results = parse_results_from_response(raw)
        if not results:
            client.close()
            with get_db() as conn:
                log_crawl(
                    conn,
                    source_name="sporttery",
                    crawl_type="results",
                    status="ok",
                    records_found=0,
                    started_at=started,
                )
                update_health(conn, "sporttery", "results", "ok", latency_ms)
            return {
                "status": "ok",
                "source": "sporttery",
                "source_type": "official",
                "results_found": 0,
                "results_stored": 0,
            }

        # Resolve match_code → match_id
        with get_db() as conn:
            resolved = 0
            for r in results:
                source_match_id = r.pop("_source_match_id", "")
                code = r.pop("_match_code", "")
                match_date = r.pop("_match_date", None)
                if not code:
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id
                           FROM official_matches
                           WHERE (
                                  %(source_match_id)s <> ''
                                  AND source_match_id = %(source_match_id)s
                              )
                              OR (
                                  official_match_code = %(match_code)s
                                  AND kickoff_time::date = %(match_date)s::date
                              )
                           ORDER BY (source_match_id = %(source_match_id)s) DESC, id DESC
                           LIMIT 1""",
                        {
                            "source_match_id": source_match_id,
                            "match_code": code,
                            "match_date": match_date,
                        },
                    )
                    row = cur.fetchone()
                if row:
                    r["match_id"] = row[0]
                    raw_json = dict(r.get("raw_json") or {})
                    raw_json.update(
                        {
                            "source_name": "sporttery",
                            "source_type": "official",
                            "source_url": ("https://www.lottery.gov.cn/jc/zqsgkj/"),
                        }
                    )
                    r["raw_json"] = raw_json
                    resolved += 1
                # Results without a match_id are skipped (no match in DB yet)

            valid_results = [r for r in results if "match_id" in r]
            if valid_results:
                store_result = store_results(conn, valid_results)
            else:
                store_result = {"inserted": 0, "updated": 0, "errors": []}

            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="results",
                status="ok",
                records_found=len(results),
                records_inserted=store_result["inserted"],
                records_updated=store_result["updated"],
                started_at=started,
            )
            update_health(conn, "sporttery", "results", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "source": "sporttery",
            "source_type": "official",
            "results_found": len(results),
            "results_matched": resolved,
            "results_inserted": store_result["inserted"],
            "results_updated": store_result["updated"],
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        error_msg = str(e)

        with get_db() as conn:
            collection_status = (
                "blocked"
                if "403" in error_msg or "567" in error_msg or "blocked" in error_msg.lower()
                else "error"
            )
            record_official_collection_status(
                conn,
                business_date=begin_date,
                crawl_type="results",
                source_name="sporttery",
                status=collection_status,
                source_url="https://www.lottery.gov.cn/jc/zqsgkj/",
                records_found=0,
                error_message=error_msg,
                raw_json={"begin_date": begin_date, "end_date": end_date},
            )
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="results",
                status=collection_status,
                error_message=error_msg,
                started_at=started,
            )
            update_health(conn, "sporttery", "results", "error", 0, error_msg)
        return {
            "status": "error",
            "source": "sporttery",
            "source_type": "official",
            "error": error_msg,
        }


# ---------------------------------------------------------------------------
# V2: Uniform API (no WAF) — match schedule + odds
# ---------------------------------------------------------------------------


def crawl_official_schedule_v2(business_date: str | None = None) -> dict[str, Any]:
    """Fetch match and market metadata using the uniform API (WAF-free).

    Odds snapshots are intentionally written only by the dedicated odds
    collector, which prevents duplicate :10/:40 history rows.
    """
    started = _now()
    client = SportteryClient()

    try:
        # 1. Fetch match list from uniform API
        t0 = time.monotonic()
        raw = client.get_uniform_match_list()
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 2. Parse using existing parsers (same JSON structure)
        match_bdate = business_date or business_today().isoformat()
        matches = parse_matches_from_response(raw, match_bdate)
        if not matches:
            client.close()
            with get_db() as conn:
                log_crawl(
                    conn,
                    source_name="sporttery_v2",
                    crawl_type="schedule",
                    status="ok",
                    records_found=0,
                    started_at=started,
                )
                update_health(conn, "sporttery_v2", "schedule", "ok", latency_ms)
            return {"status": "ok", "matches_found": 0, "note": "no matches in response"}

        # 3. Store matches
        total_inserted, total_updated = 0, 0
        with get_db() as conn:
            match_result = store_matches(conn, matches)
            total_inserted = match_result.get("inserted", 0)
            total_updated = match_result.get("updated", 0)

            # 4. Store market availability and permissions for each match.
            for m in matches:
                code = m["official_match_code"]
                bdate = m["business_date"]
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM official_matches "
                        "WHERE official_match_code = %s AND business_date = %s",
                        (code, bdate),
                    )
                    row = cur.fetchone()
                if row is None:
                    continue
                match_id = row[0]

                # Store markets
                store_markets(conn, match_id, m.get("_markets", []))

            # 5. Log
            log_crawl(
                conn,
                source_name="sporttery_v2",
                crawl_type="schedule",
                status="ok",
                records_found=len(matches),
                records_inserted=total_inserted,
                records_updated=total_updated,
                started_at=started,
            )
            update_health(conn, "sporttery_v2", "schedule", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "matches_found": len(matches),
            "matches_inserted": total_inserted,
            "matches_updated": total_updated,
            "snapshots_inserted": 0,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        print(f"[crawl_official_schedule_v2] error: {e}, falling back to V1…")
        # Fallback to original crawler
        return crawl_official_schedule(business_date or business_today().isoformat())


# ---------------------------------------------------------------------------
# Traditional lottery (传统足彩 14场/任九)
# ---------------------------------------------------------------------------


def parse_traditional_lottery_response(
    raw: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Parse traditional lottery draw response into normalized pool/issue dicts.

    The response from getFootBallDrawInfoV2.qry has separate sections for
    each game type (90=t14c, 91=r9, 98=bqc6, 99=jq4).

    Returns a list of dicts with keys:
      game_type, issue_no, sale_start, sale_stop, total_matches,
      official_status, matches (list of match dicts)
    """
    value = raw.get("value", {})
    # Map game codes to sections in the response
    game_sections = {
        "sfcDetail": 90,  # 胜负彩 → t14c
        "rjDetail": 91,  # 任九
        "bqcDetail": 98,  # 半全场
        "jqcDetail": 99,  # 进球彩
    }

    results = []
    for section_key, game_code in game_sections.items():
        game_type = TRADITIONAL_GAME_TYPES.get(game_code)
        if not game_type:
            continue

        section = value.get(section_key, {})
        if not section or not section.get("matchList"):
            continue

        issue_no = section.get("lotteryDrawNum", "")
        if not issue_no:
            continue

        match_list = section.get("matchList", [])
        matches = []
        for i, m in enumerate(match_list):
            matches.append(
                {
                    "match_order": i + 1,
                    "match_id": m.get("infohubMatchId") or m.get("matchId"),
                    "league_name": m.get("matchName", ""),
                    "home_team_name": m.get("masterTeamAllName")
                    or m.get("masterTeamName")
                    or m.get("homeTeam", ""),
                    "away_team_name": m.get("guestTeamAllName")
                    or m.get("guestTeamName")
                    or m.get("awayTeam", ""),
                    "kickoff_time": m.get("startTime", ""),
                    "home_win_prob": m.get("homeWinProb"),
                    "draw_prob": m.get("drawProb"),
                    "away_win_prob": m.get("awayWinProb"),
                    "upset_score": m.get("upsetScore"),
                    "public_heat_home": m.get("homeRate"),
                    "public_heat_draw": m.get("drawRate"),
                    "public_heat_away": m.get("awayRate"),
                }
            )

        sale_start = section.get("saleStartTime") or section.get("lotterySaleBeginTime")
        sale_stop = (
            section.get("saleEndTime")
            or section.get("lotterySaleEndtime")
            or section.get("lotterySaleEndTime")
            or section.get("estimateDrawTime")
        )
        on_sale = section.get("onSale")
        if on_sale in (0, 1, True, False):
            official_status = "selling" if on_sale == 1 or on_sale is True else "closed"
        else:
            # Some current Sporttery responses omit onSale while still
            # returning the official stop time. Do not treat a missing field
            # as closed when the official sale window has not ended.
            official_status = "closed"
            if sale_stop:
                try:
                    stop_text = str(sale_stop).replace("Z", "+00:00")
                    stop_dt = datetime.fromisoformat(stop_text)
                    if stop_dt.tzinfo is not None:
                        stop_dt = stop_dt.astimezone(business_now(now).tzinfo).replace(tzinfo=None)
                    current = business_now(now).replace(tzinfo=None)
                    official_status = "selling" if stop_dt > current else "closed"
                except ValueError:
                    pass

        results.append(
            {
                "game_type": game_type,
                "issue_no": issue_no,
                "sale_start": sale_start,
                "sale_stop": sale_stop,
                "total_matches": len(match_list),
                "official_status": official_status,
                "matches": matches,
                "raw_json": section,
            }
        )

    return results


def crawl_traditional_lottery() -> dict[str, Any]:
    """Crawl traditional football lottery (14场/任九) data via Playwright.

    Fetches current issue + match pool and stores in
    football_pool_issues + football_pool_issue_matches.
    """
    started = _now()
    client = SportteryClient()

    try:
        t0 = time.monotonic()
        raw = client.get_traditional_lottery_draw()
        latency_ms = int((time.monotonic() - t0) * 1000)

        pools = parse_traditional_lottery_response(raw)
        if not pools:
            client.close()
            with get_db() as conn:
                log_crawl(
                    conn,
                    source_name="sporttery",
                    crawl_type="traditional_lottery",
                    status="ok",
                    records_found=0,
                    started_at=started,
                )
            return {"status": "ok", "pools_found": 0, "note": "no traditional lottery data"}

        total_issues = 0
        total_matches = 0
        with get_db() as conn:
            for pool in pools:
                issue_id = store_pool_issue(
                    conn,
                    issue_no=pool["issue_no"],
                    game_type=pool["game_type"],
                    sale_start=pool["sale_start"],
                    sale_stop=pool["sale_stop"],
                    total_matches=pool["total_matches"],
                    official_status=pool["official_status"],
                    raw_json=pool.get("raw_json"),
                )
                if issue_id:
                    total_issues += 1
                    if pool.get("matches"):
                        n = store_pool_issue_matches(conn, issue_id, pool["matches"])
                        total_matches += n

            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="traditional_lottery",
                status="ok",
                records_found=len(pools),
                records_inserted=total_issues,
                started_at=started,
            )
            update_health(conn, "sporttery", "traditional_lottery", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "pools_found": len(pools),
            "issues_stored": total_issues,
            "matches_stored": total_matches,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        latency_ms = 0
        with get_db() as conn:
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="traditional_lottery",
                status="error",
                error_message=str(e),
                started_at=started,
            )
            update_health(conn, "sporttery", "traditional_lottery", "error", 0, str(e))
        return {"status": "error", "error": str(e)}
