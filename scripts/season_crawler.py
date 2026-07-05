"""500.com league season schedule crawler.

Uses the AJAX endpoint (index.php?c=match&a=getmatch) to fetch
all match data for every round/group in a league season.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime
from typing import Any

LEAGUE_IDS: dict[str, int] = {
    "世界杯": 19476,
    "韩国职业联赛": 19554,
    "瑞典超级联赛": 19501,
    "芬兰超级联赛": 19506,
}

AJAX_URL = "https://liansai.500.com/index.php?c=match&a=getmatch&sid={sid}&round={round}"
LEAGUE_PAGE_URL = "https://liansai.500.com/zuqiu-{league_id}/"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "",
}


def _fetch_page(url: str, referer: str = "") -> str:
    """Fetch a page (GBK)."""
    h = dict(HEADERS)
    h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("gbk", errors="ignore")


def _fetch_json(url: str, referer: str) -> Any:
    """Fetch JSON from the AJAX endpoint."""
    h = dict(HEADERS)
    h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def get_season_info(league_id: int) -> dict[str, Any]:
    """Extract seasonId, allRounds, roundType from a league page."""
    html = _fetch_page(LEAGUE_PAGE_URL.format(league_id=league_id))
    info: dict[str, Any] = {}

    m = re.search(r"var\s+seasonId\s*=\s*(\d+)", html)
    info["season_id"] = int(m.group(1)) if m else league_id

    m = re.search(r"var\s+roundCount\s*=\s*(\d+)", html)
    info["round_count"] = int(m.group(1)) if m else 0

    m = re.search(r"var\s+nowRound\s*=\s*'([^']+)'", html)
    info["now_round"] = m.group(1) if m else ""

    m = re.search(r"allRounds\s*=\s*(\[[^\]]*\])", html)
    if m:
        raw = m.group(1)
        if raw[0] == "[":
            items = re.findall(r'"([^"]*)"', raw)
            if not items:
                items = [x.strip() for x in raw[1:-1].split(",")]
            info["all_rounds"] = items

    m = re.search(r"var\s+roundType\s*=\s*'([^']+)'", html)
    info["round_type"] = m.group(1) if m else ""

    return info


def crawl_league(league_name: str, league_id: int) -> dict[str, Any]:
    """Fetch match results from 500.com for a league season.

    IMPORTANT: This ONLY updates results for matches that ALREADY EXIST
    in official_matches (imported by the sporttery crawler). It does NOT
    insert new matches — 体彩官方上架的比赛才是收录标准.
    """
    t0 = time.monotonic()
    print(f"\n[season] {league_name} (id={league_id}) — results-only mode")

    info = get_season_info(league_id)
    all_rounds = info.get("all_rounds", [])
    season_id = info["season_id"]
    round_type = info.get("round_type", "")
    print(f"  seasonId={season_id}, rounds={len(all_rounds)}, type={round_type}")

    if not all_rounds:
        print("  [warn] No rounds found, trying default round='1'")
        all_rounds = ["1"]

    referer = LEAGUE_PAGE_URL.format(league_id=league_id)
    all_matches: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for rnd in all_rounds:
        url = AJAX_URL.format(sid=season_id, round=rnd)
        try:
            data = _fetch_json(url, referer)
        except Exception as e:
            print(f"  round={rnd}: error - {e}")
            continue

        if not isinstance(data, list):
            continue

        for m in data:
            home = m.get("hname", "")
            away = m.get("gname", "")
            stime = m.get("stime", "")
            if not home or not away:
                continue
            key = (stime, home, away)
            if key in seen:
                continue
            seen.add(key)

            try:
                kt = datetime.strptime(stime, "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            # Parse scores — only trust when status=5 (完赛)
            status = m.get("status", 0)
            if status == 5:
                hs = m.get("hscore")
                gs = m.get("gscore")
                fh = int(hs) if hs not in (None, "", " ") else None
                fa = int(gs) if gs not in (None, "", " ") else None
                hhs = m.get("hhalfscore")
                ghs = m.get("ghalfscore")
                hh = int(hhs) if hhs not in (None, "", " ") else None
                ha = int(ghs) if ghs not in (None, "", " ") else None
            else:
                fh = fa = hh = ha = None

            all_matches.append({
                "match_id_500": m.get("fid"),
                "home_team": home,
                "away_team": away,
                "kickoff_time": kt,
                "ft_home_goals": fh,
                "ft_away_goals": fa,
                "ht_home_goals": hh,
                "ht_away_goals": ha,
                "round": str(rnd),
                "league_name": league_name,
                "source_url": f"{referer}?round={rnd}",
            })

        time.sleep(0.15)

    # Count stats
    finished = sum(1 for m in all_matches if m["ft_home_goals"] is not None)
    upcoming = len(all_matches) - finished
    print(f"  Total parsed: {len(all_matches)} (finished={finished}, upcoming={upcoming})")

    # Only UPDATE results for EXISTING matches — never insert
    from apps.backend.src.db import get_db

    updated, skipped, not_found = 0, 0, 0

    with get_db() as conn:
        with conn.cursor() as cur:
            for m in all_matches:
                kt = m["kickoff_time"]
                cur.execute(
                    """
                    SELECT id, match_status FROM official_matches
                    WHERE league_name = %s AND home_team_name = %s
                      AND away_team_name = %s AND kickoff_time = %s
                    """,
                    (league_name, m["home_team"], m["away_team"], kt),
                )
                existing = cur.fetchone()

                if not existing:
                    not_found += 1
                    continue

                if m["ft_home_goals"] is not None and existing[1] != "Settled":
                    # Update match status to Settled and store result
                    cur.execute(
                        """
                        UPDATE official_matches
                        SET match_status = 'Settled', updated_at = now(),
                            raw_json = raw_json || %s
                        WHERE id = %s
                        """,
                        (
                            json.dumps({
                                "500_com_result": {
                                    "fid": m["match_id_500"],
                                    "round": m["round"],
                                    "ft_home_goals": m["ft_home_goals"],
                                    "ft_away_goals": m["ft_away_goals"],
                                    "ht_home_goals": m["ht_home_goals"],
                                    "ht_away_goals": m["ht_away_goals"],
                                }
                            }, ensure_ascii=False),
                            existing[0],
                        ),
                    )
                    updated += 1
                else:
                    skipped += 1
        conn.commit()

    elapsed = int((time.monotonic() - t0) * 1000)
    return {
        "status": "ok", "league": league_name,
        "season_id": season_id, "rounds": len(all_rounds),
        "parsed": len(all_matches), "finished": finished, "upcoming": upcoming,
        "inserted": 0,  # never insert
        "updated": updated, "skipped": skipped, "not_found": not_found,
        "latency_ms": elapsed,
    }


def crawl_league_full(league_name: str, league_id: int) -> dict[str, Any]:
    """Fetch FULL season schedule from 500.com and import into official_matches.

    Unlike crawl_league() which only UPDATES existing matches, this function
    INSERTS all matches from the 500.com season schedule. Existing matches
    (matched by league+teams+kickoff) are updated with results only.
    """
    t0 = time.monotonic()
    print(f"\n[season-full] {league_name} (id={league_id}) — full import mode")

    info = get_season_info(league_id)
    all_rounds = info.get("all_rounds", [])
    season_id = info["season_id"]
    round_type = info.get("round_type", "")
    print(f"  seasonId={season_id}, rounds={len(all_rounds)}, type={round_type}")

    if not all_rounds:
        # Fallback: probe rounds 1..N until empty
        print(f"  [warn] No rounds found, probing with seasonId={season_id}")
        max_probe = info.get("round_count", 0) or 40
        all_rounds = []
        probe_referer = LEAGUE_PAGE_URL.format(league_id=league_id)
        for probe_rnd in range(1, max_probe + 1):
            probe_url = AJAX_URL.format(sid=season_id, round=probe_rnd)
            try:
                probe_data = _fetch_json(probe_url, probe_referer)
                if isinstance(probe_data, list) and len(probe_data) > 0:
                    all_rounds.append(str(probe_rnd))
                elif probe_rnd > 3:
                    break
            except Exception:
                if probe_rnd > 3:
                    break
            time.sleep(0.1)
        print(f"  Probe found {len(all_rounds)} rounds")

    referer = LEAGUE_PAGE_URL.format(league_id=league_id)
    all_matches: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for rnd in all_rounds:
        url = AJAX_URL.format(sid=season_id, round=rnd)
        try:
            data = _fetch_json(url, referer)
        except Exception as e:
            print(f"  round={rnd}: error - {e}")
            continue

        if not isinstance(data, list):
            continue

        for m in data:
            home = m.get("hname", "")
            away = m.get("gname", "")
            stime = m.get("stime", "")
            if not home or not away:
                continue
            key = (stime, home, away)
            if key in seen:
                continue
            seen.add(key)

            try:
                kt = datetime.strptime(stime, "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            status = m.get("status", 0)
            if status == 5:
                hs = m.get("hscore")
                gs = m.get("gscore")
                fh = int(hs) if hs not in (None, "", " ") else None
                fa = int(gs) if gs not in (None, "", " ") else None
                hhs = m.get("hhalfscore")
                ghs = m.get("ghalfscore")
                hh = int(hhs) if hhs not in (None, "", " ") else None
                ha = int(ghs) if ghs not in (None, "", " ") else None
            else:
                fh = fa = hh = ha = None

            fid = m.get("fid", "")
            all_matches.append({
                "match_id_500": fid,
                "home_team": home,
                "away_team": away,
                "kickoff_time": kt,
                "ft_home_goals": fh,
                "ft_away_goals": fa,
                "ht_home_goals": hh,
                "ht_away_goals": ha,
                "round": str(rnd),
                "league_name": league_name,
                "source_url": f"{referer}?round={rnd}",
            })

        time.sleep(0.15)

    finished = sum(1 for m in all_matches if m["ft_home_goals"] is not None)
    upcoming = len(all_matches) - finished
    print(f"  Total parsed: {len(all_matches)} (finished={finished}, upcoming={upcoming})")

    from apps.backend.src.db import get_db

    inserted, updated, skipped = 0, 0, 0

    with get_db() as conn:
        with conn.cursor() as cur:
            for m in all_matches:
                kt = m["kickoff_time"]
                bd = kt.strftime("%Y-%m-%d")
                # Use 500.com fid as official_match_code
                code = f"500-{m['match_id_500']}"

                # Check if match already exists by league+teams+kickoff
                cur.execute(
                    """
                    SELECT id, match_status, official_match_code FROM official_matches
                    WHERE league_name = %s AND home_team_name = %s
                      AND away_team_name = %s AND kickoff_time = %s
                    """,
                    (league_name, m["home_team"], m["away_team"], kt),
                )
                existing = cur.fetchone()

                if existing:
                    # Update results if finished and not already settled
                    if m["ft_home_goals"] is not None and existing[1] != "Settled":
                        cur.execute(
                            """
                            UPDATE official_matches
                            SET match_status = 'Settled', updated_at = now(),
                                raw_json = raw_json || %s
                            WHERE id = %s
                            """,
                            (
                                json.dumps({
                                    "500_com_result": {
                                        "fid": m["match_id_500"],
                                        "round": m["round"],
                                        "ft_home_goals": m["ft_home_goals"],
                                        "ft_away_goals": m["ft_away_goals"],
                                        "ht_home_goals": m["ht_home_goals"],
                                        "ht_away_goals": m["ht_away_goals"],
                                    }
                                }, ensure_ascii=False),
                                existing[0],
                            ),
                        )
                        # Also upsert into official_results
                        cur.execute(
                            """
                            INSERT INTO official_results (match_id, full_home_goals, full_away_goals,
                                half_home_goals, half_away_goals, result_status)
                            VALUES (%s, %s, %s, %s, %s, 'confirmed')
                            ON CONFLICT (match_id) DO UPDATE SET
                                full_home_goals = EXCLUDED.full_home_goals,
                                full_away_goals = EXCLUDED.full_away_goals,
                                half_home_goals = EXCLUDED.half_home_goals,
                                half_away_goals = EXCLUDED.half_away_goals,
                                updated_at = now()
                            """,
                            (
                                existing[0],
                                m["ft_home_goals"], m["ft_away_goals"],
                                m["ht_home_goals"], m["ht_away_goals"],
                            ),
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    # Insert new match from 500.com
                    match_status = "Settled" if m["ft_home_goals"] is not None else "Scheduled"
                    cur.execute(
                        """
                        INSERT INTO official_matches
                            (business_date, official_match_code, league_name,
                             home_team_name, away_team_name, kickoff_time,
                             match_status, source_url, raw_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (business_date, official_match_code) DO NOTHING
                        """,
                        (
                            bd, code, league_name,
                            m["home_team"], m["away_team"], kt,
                            match_status,
                            m["source_url"],
                            json.dumps({
                                "source": "500.com",
                                "fid": m["match_id_500"],
                                "round": m["round"],
                                "season_id": season_id,
                            }, ensure_ascii=False),
                        ),
                    )
                    # Get the new match ID for results
                    if match_status == "Settled":
                        cur.execute(
                            """
                            SELECT id FROM official_matches
                            WHERE business_date = %s AND official_match_code = %s
                            """,
                            (bd, code),
                        )
                        new_row = cur.fetchone()
                        if new_row:
                            cur.execute(
                                """
                                INSERT INTO official_results (match_id, full_home_goals, full_away_goals,
                                    half_home_goals, half_away_goals, result_status)
                                VALUES (%s, %s, %s, %s, %s, 'confirmed')
                                ON CONFLICT (match_id) DO UPDATE SET
                                    full_home_goals = EXCLUDED.full_home_goals,
                                    full_away_goals = EXCLUDED.full_away_goals,
                                    half_home_goals = EXCLUDED.half_home_goals,
                                    half_away_goals = EXCLUDED.half_away_goals,
                                    updated_at = now()
                                """,
                                (
                                    new_row[0],
                                    m["ft_home_goals"], m["ft_away_goals"],
                                    m["ht_home_goals"], m["ht_away_goals"],
                                ),
                            )
                    inserted += 1

        conn.commit()

    elapsed = int((time.monotonic() - t0) * 1000)
    return {
        "status": "ok", "league": league_name,
        "season_id": season_id, "rounds": len(all_rounds),
        "parsed": len(all_matches), "finished": finished, "upcoming": upcoming,
        "inserted": inserted, "updated": updated, "skipped": skipped,
        "latency_ms": elapsed,
    }


def run(league_filter: str | None = None) -> dict[str, Any]:
    """Crawl all registered leagues or a specific one."""
    if league_filter:
        if league_filter not in LEAGUE_IDS:
            return {"status": "error", "error": f"Unknown league: {league_filter}"}
        leagues = {league_filter: LEAGUE_IDS[league_filter]}
    else:
        leagues = LEAGUE_IDS

    results = []
    for name, lid in leagues.items():
        r = crawl_league(name, lid)
        results.append(r)
        time.sleep(1.0)

    ti = sum(r.get("inserted", 0) for r in results)
    tu = sum(r.get("updated", 0) for r in results)
    tp = sum(r.get("parsed", 0) for r in results)

    return {
        "status": "ok",
        "leagues": len(results),
        "total_parsed": tp, "total_inserted": ti, "total_updated": tu,
        "details": results,
    }


if __name__ == "__main__":
    import sys
    league = sys.argv[1] if len(sys.argv) > 1 else None
    result = run(league_filter=league)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
