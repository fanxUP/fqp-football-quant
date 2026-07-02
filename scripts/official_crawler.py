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

import time
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.official_storage import (
    log_crawl,
    store_markets,
    store_matches,
    store_odds_snapshots,
    store_results,
    update_health,
)
from scripts.sporttery_client import SportteryClient

# ---------------------------------------------------------------------------
# Play-type mapping: sporttery poolCode → internal play_type
# ---------------------------------------------------------------------------
POOL_CODE_MAP: dict[str, str] = {
    "HAD": "spf",  # 胜平负
    "HHAD": "rqspf",  # 让球胜平负
    "CRS": "score",  # 比分
    "TTG": "total_goals",  # 总进球
    "HAFU": "half_full",  # 半全场
}

# Option labels for each play type
OPTION_LABELS: dict[str, dict[str, str]] = {
    "spf": {"h": "主胜", "d": "平", "a": "客胜"},
    "rqspf": {"h": "让球主胜", "d": "让球平", "a": "让球客胜"},
}


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


def parse_matches_from_response(
    raw: dict[str, Any],
    business_date: str,
) -> list[dict[str, Any]]:
    """Parse sporttery getMatchCalculatorV1 response into normalized match dicts.

    Real API structure (2026-07 observed):
      value.matchInfoList[].businessDate   — betting publish date
      value.matchInfoList[].subMatchList[] — array of matches
        matchDate + matchTime → kickoff_time
        oddsList[] has HAD/HHAD (duplicated by poolId, dedup by poolCode)
    """
    matches: list[dict] = []
    match_info_list = raw.get("value", {}).get("matchInfoList", [])
    if not match_info_list:
        match_info_list = raw.get("matchInfoList", [])

    for day_block in match_info_list:
        bdate = day_block.get("businessDate", business_date)
        for sub in day_block.get("subMatchList", []):
            match_code = str(sub.get("matchNum", ""))
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
            sale_status_raw = sub.get("saleStatus")
            if isinstance(sale_status_raw, int):
                sale_status = _SALE_STATUS_MAP.get(sale_status_raw, "unknown")
            else:
                sale_status = str(sale_status_raw) if sale_status_raw else "unknown"

            # Parse markets from oddsList, deduplicated by poolCode
            markets: list[dict] = []
            seen_pool_codes: set[str] = set()
            odds_list = sub.get("oddsList", [])
            for odds in odds_list:
                pool_code = odds.get("poolCode", "")
                if pool_code in seen_pool_codes:
                    continue  # oddsList has duplicate entries by poolId
                seen_pool_codes.add(pool_code)

                play_type = POOL_CODE_MAP.get(pool_code, pool_code.lower())
                handicap = odds.get("goalLine")
                if handicap is not None and handicap != "":
                    try:
                        handicap_val = float(handicap)
                    except (ValueError, TypeError):
                        handicap_val = None
                else:
                    handicap_val = None

                markets.append(
                    {
                        "play_type": play_type,
                        "handicap": handicap_val,
                        "is_open": True,  # odds presence implies market is open
                        "is_single_allowed": False,  # determined from poolList
                        "raw_json": odds,
                    }
                )

            # Also check poolList for single-allowed status
            pool_list = sub.get("poolList", [])
            for pl in pool_list:
                pl_code = pl.get("poolCode", "")
                pl_play_type = POOL_CODE_MAP.get(pl_code, pl_code.lower())
                pl_single = pl.get("single", 0) == 1 or pl.get("bettingSingle", 0) == 1
                for mkt in markets:
                    if mkt["play_type"] == pl_play_type:
                        mkt["is_single_allowed"] = pl_single

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
                    "match_status": sub.get("matchStatus", "scheduled"),
                    "source_url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry",
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
        except (ValueError, TypeError):
            pass

    odds_list = match_raw.get("oddsList", [])
    seen_pool_codes: set[str] = set()
    for odds in odds_list:
        pool_code = odds.get("poolCode", "")
        if pool_code in seen_pool_codes:
            continue  # dedup by poolCode
        seen_pool_codes.add(pool_code)

        play_type = POOL_CODE_MAP.get(pool_code, pool_code.lower())
        handicap = odds.get("goalLine")
        if handicap is not None and handicap != "":
            try:
                handicap_val = float(handicap)
            except (ValueError, TypeError):
                handicap_val = None
        else:
            handicap_val = None

        labels = OPTION_LABELS.get(play_type, {"h": "胜", "d": "平", "a": "负"})

        for option_code in ("h", "d", "a"):
            sp_value = odds.get(option_code)
            if sp_value is None:
                continue
            try:
                sp_val = float(sp_value)
            except (ValueError, TypeError):
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
                    "option_name": labels.get(option_code, option_code),
                    "sp_value": sp_val,
                    "handicap": handicap_val,
                    "is_open": odds.get("isOpen", True),
                    "is_single_allowed": odds.get("isSingleAllowed", False),
                    "raw_json": odds,
                }
            )

    return snapshots


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
        result_list = raw.get("matchResultList", [])
    if not result_list:
        result_list = raw.get("matchInfoList", [])

    for item in result_list:
        match_code = item.get("matchNum") or item.get("matchCode", "")
        if not match_code:
            continue

        # Goals
        half_home = item.get("halfHomeGoals") or item.get("halfHomeScore")
        half_away = item.get("halfAwayGoals") or item.get("halfAwayScore")
        full_home = item.get("fullHomeGoals") or item.get("fullHomeScore") or item.get("homeGoals")
        full_away = item.get("fullAwayGoals") or item.get("fullAwayScore") or item.get("awayGoals")

        # Convert to int if present
        def _to_int(v: Any) -> int | None:
            if v is None:
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
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
                "_match_code": match_code,
                "half_home_goals": hh,
                "half_away_goals": ha,
                "full_home_goals": fh,
                "full_away_goals": fa,
                "spf_result": spf,
                "rqspf_result": None,  # requires handicap + score, computed later
                "total_goals_result": fh + fa if fh is not None and fa is not None else None,
                "score_result": score,
                "half_full_result": half_full,
                "result_status": item.get("resultStatus", "confirmed"),
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
                update_health(conn, "sporttery", "official", "ok", latency_ms)
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
            update_health(conn, "sporttery", "official", "ok", latency_ms)

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
            update_health(conn, "sporttery", "official", "error", latency_ms, str(e))
        return {"status": "error", "error": str(e)}


def crawl_official_odds_snapshot(business_date: str) -> dict[str, Any]:
    """Take an odds snapshot for all active matches on the given date.

    Called by the scheduler every 30 min and by the worker's polling loop.
    """
    started = _now()
    client = SportteryClient()
    try:
        t0 = time.monotonic()
        raw = client.get_daily_matches(business_date)
        latency_ms = int((time.monotonic() - t0) * 1000)

        matches = parse_matches_from_response(raw, business_date)
        if not matches:
            client.close()
            return {"status": "ok", "matches_processed": 0, "snapshots_inserted": 0}

        total_snapshots = 0
        snap_time = _now()

        with get_db() as conn:
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

                snapshots = parse_odds_snapshots_from_match(
                    m.get("raw_json", {}), snapshot_time=snap_time
                )
                if snapshots:
                    result = store_odds_snapshots(
                        conn, match_id=match_id, market_id=None, snapshots=snapshots
                    )
                    total_snapshots += result["inserted"]

            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="odds_snapshot",
                status="ok",
                records_found=len(matches),
                records_inserted=total_snapshots,
                started_at=started,
            )
            update_health(conn, "sporttery", "official", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "matches_processed": len(matches),
            "snapshots_inserted": total_snapshots,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        with get_db() as conn:
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="odds_snapshot",
                status="error",
                error_message=str(e),
                started_at=started,
            )
            update_health(conn, "sporttery", "official", "error", 0, str(e))
        return {"status": "error", "error": str(e)}


def crawl_official_results(begin_date: str, end_date: str) -> dict[str, Any]:
    """Fetch and store match results for a date range."""
    started = _now()
    client = SportteryClient()
    try:
        t0 = time.monotonic()
        raw = client.get_match_results(begin_date, end_date)
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
            return {"status": "ok", "results_found": 0, "results_stored": 0}

        # Resolve match_code → match_id
        with get_db() as conn:
            resolved = 0
            for r in results:
                code = r.pop("_match_code", "")
                if not code:
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM official_matches WHERE official_match_code = %s "
                        "ORDER BY business_date DESC LIMIT 1",
                        (code,),
                    )
                    row = cur.fetchone()
                if row:
                    r["match_id"] = row[0]
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
            update_health(conn, "sporttery", "official", "ok", latency_ms)

        client.close()
        return {
            "status": "ok",
            "results_found": len(results),
            "results_matched": resolved,
            "results_inserted": store_result["inserted"],
            "results_updated": store_result["updated"],
            "latency_ms": latency_ms,
        }

    except Exception as e:
        client.close()
        with get_db() as conn:
            log_crawl(
                conn,
                source_name="sporttery",
                crawl_type="results",
                status="error",
                error_message=str(e),
                started_at=started,
            )
            update_health(conn, "sporttery", "official", "error", 0, str(e))
        return {"status": "error", "error": str(e)}
