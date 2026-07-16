"""500.com match results client.

Fallback data source when Sporttery API is blocked.
500.com/wanchang.php provides clean, structured HTML with match results
that can be reliably parsed.

Data extracted per match:
  - League name, round
  - Home/away team names (Chinese)
  - Full-time score (home + away goals)
  - Half-time score
  - Match status (完/中/推迟/取消)
"""

from __future__ import annotations

import re
import time
import urllib.request
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

BASE_URL = "https://live.500.com/wanchang.php"
REQUEST_TIMEOUT = 15


def _normalize_team_name(value: str) -> str:
    return re.sub(r"[\s·•\-_]", "", value or "").replace("足球俱乐部", "")


def _team_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, _normalize_team_name(left), _normalize_team_name(right)
    ).ratio()


def _select_official_match(
    home_team: str,
    away_team: str,
    candidates: list[tuple[int, str, str]],
) -> int | None:
    """Resolve a unique same-kickoff fixture without guessing through ambiguity."""
    scored: list[tuple[float, int]] = []
    for match_id, official_home, official_away in candidates:
        home_score = _team_similarity(home_team, official_home)
        away_score = _team_similarity(away_team, official_away)
        one_exact = home_score == 1.0 or away_score == 1.0
        translated_pair = max(home_score, away_score) >= 0.85 and min(
            home_score, away_score
        ) >= 0.40
        if (one_exact and home_score + away_score >= 1.20) or translated_pair:
            scored.append((home_score + away_score, match_id))

    scored.sort(reverse=True)
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.25:
        return None
    return scored[0][1]


def _fetch_page(date_str: str) -> str:
    """Fetch 500.com wanchang.php page for a given date.

    Returns the raw HTML (GBK-decoded).
    """
    url = f"{BASE_URL}?e={date_str}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        return r.read().decode("gbk", errors="ignore")


def parse_match_results(html: str) -> list[dict[str, Any]]:
    """Parse 500.com wanchang.php HTML into structured match results.

    HTML structure per match row:
      <tr id="a1359190" gy="世界杯,西班牙,奥地利" ...>
        <td>世界杯</td>                                    -- league
        <td align="center">1/16决赛</td>                   -- round
        <td align="center">07-03 03:00</td>                -- datetime
        <td><span class="red">完</span></td>               -- status
        <td><span class="mainName">西班牙</span></td>     -- home team
        <td><a class="clt1">3</a><a class="clt3">0</a></td> -- FT goals
        <td><span class="clientName">奥地利</span></td>   -- away team
        <td class="red">1 - 0</td>                         -- HT score
      </tr>

    Returns list of dicts with:
      home_team, away_team, ft_home_goals, ft_away_goals,
      ht_home_goals, ht_away_goals, league, datetime, status
    """
    results: list[dict] = []

    # Find all match rows
    tr_pattern = re.compile(
        r'<tr\s+id="(a\d+)"\s+gy="([^"]*)"[^>]*>(.*?)</tr>', re.DOTALL
    )
    for match_id, gy, content in tr_pattern.findall(html):
        # Extract league name (first link in the row)
        league_m = re.search(r"<a[^>]*>([^<]+)</a>", content)
        league = league_m.group(1).strip() if league_m else ""

        # Extract datetime cells (2nd td align="center")
        td_centers = re.findall(r'<td align="center">([^<]*)</td>', content)
        round_name = td_centers[0] if len(td_centers) > 0 else ""
        match_datetime = td_centers[1] if len(td_centers) > 1 else ""

        # Extract status
        status_m = re.search(
            r'<span class="[^"]*">(完|中|推迟|取消|待)</span>', content
        )
        status = status_m.group(1) if status_m else ""

        # Extract home team (span.mainName)
        home_m = re.search(r'<span class="mainName">([^<]+)</span>', content)
        home_team = home_m.group(1).strip() if home_m else ""
        if not home_team:
            continue

        # Extract away team (span.clientName)
        away_m = re.search(r'<span class="clientName">([^<]+)</span>', content)
        away_team = away_m.group(1).strip() if away_m else ""
        if not away_team:
            continue

        # Extract full-time goals (a.clt1 and a.clt3)
        ft_home_m = re.search(r'class="clt1"\s*>(\d+)</a>', content)
        ft_away_m = re.search(r'class="clt3"\s*>(\d+)</a>', content)

        # Extract half-time score
        ht_m = re.search(
            r'<td align="center" class="[^"]*">(\d+)\s*-\s*(\d+)</td>', content
        )

        ft_home = int(ft_home_m.group(1)) if ft_home_m else None
        ft_away = int(ft_away_m.group(1)) if ft_away_m else None

        ht_home = int(ht_m.group(1)) if ht_m else None
        ht_away = int(ht_m.group(2)) if ht_m else None

        # Parse datetime to date
        match_date = None
        if match_datetime:
            # Format: "MM-DD HH:MM"
            parts = match_datetime.split()
            if len(parts) >= 1:
                mmdd = parts[0]  # "07-03"
                # Determine year from context (current year)
                year = datetime.now().year
                try:
                    match_date = f"{year}-{mmdd}"
                except ValueError:
                    pass

        results.append(
            {
                "_500_id": match_id,
                "league": league,
                "round": round_name,
                "match_datetime": match_datetime,
                "match_date": match_date,
                "status": status,
                "home_team": home_team,
                "away_team": away_team,
                "ft_home_goals": ft_home,
                "ft_away_goals": ft_away,
                "ht_home_goals": ht_home,
                "ht_away_goals": ht_away,
                "_gy": gy,
            }
        )

    return results


def _to_result_dict(match: dict) -> dict[str, Any]:
    """Convert a 500.com match dict to the standard result format
    expected by store_results() (same as parse_results_from_response output).
    """
    fh = match.get("ft_home_goals")
    fa = match.get("ft_away_goals")
    hh = match.get("ht_home_goals")
    ha = match.get("ht_away_goals")

    # SPF result
    spf = None
    if fh is not None and fa is not None:
        spf = "3" if fh > fa else ("1" if fh == fa else "0")

    # Score result
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

    total_goals = (fh + fa) if (fh is not None and fa is not None) else None

    return {
        "half_home_goals": hh,
        "half_away_goals": ha,
        "full_home_goals": fh,
        "full_away_goals": fa,
        "spf_result": spf,
        "rqspf_result": None,
        "total_goals_result": total_goals,
        "score_result": score,
        "half_full_result": half_full,
        "result_status": "confirmed" if match.get("status") == "完" else "pending",
        "official_publish_time": datetime.now().isoformat(timespec="seconds"),
        "raw_json": match,
    }


def get_match_results(
    begin_date: str,
    end_date: str,
    db_conn: Any = None,
) -> list[dict[str, Any]]:
    """Fetch and resolve match results from 500.com for a date range.

    Because 500.com assigns early-morning matches to the previous day's page,
    we fetch a wider range (2 days before to 1 day after) and match by team name.

    Each result is resolved to a match_id from official_matches via
    (kickoff_date, home_team_name, away_team_name).

    Args:
        begin_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        db_conn: Optional DB connection for resolving match_ids.
                 If None, results won't have match_id set.

    Returns:
        List of result dicts with match_id field set (if db_conn provided).
    """
    # Fetch a wider date range to catch early-morning matches
    start_dt = datetime.strptime(begin_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    fetch_start = start_dt - timedelta(days=2)
    fetch_end = end_dt + timedelta(days=1)

    all_matches: list[dict] = []
    seen: set[tuple[str, str, str]] = set()  # (date, home, away) dedup

    current = fetch_start
    while current <= fetch_end:
        date_str = current.strftime("%Y-%m-%d")
        try:
            html = _fetch_page(date_str)
            matches = parse_match_results(html)
            for m in matches:
                if m.get("status") != "完":
                    continue  # only finished matches
                if m.get("ft_home_goals") is None or m.get("ft_away_goals") is None:
                    continue  # no score data

                key = (m["match_date"] or "", m["home_team"], m["away_team"])
                if key in seen:
                    continue
                seen.add(key)
                all_matches.append(m)

        except Exception as e:
            print(f"[five100] fetch {date_str} error: {e}")

        current += timedelta(days=1)
        time.sleep(0.3)  # be gentle to the server

    # Resolve match_ids from DB
    if db_conn is None:
        return [_to_result_dict(m) for m in all_matches]

    results: list[dict] = []
    with db_conn.cursor() as cur:
        for m in all_matches:
            home = m["home_team"]
            away = m["away_team"]
            match_date = m.get("match_date", "")
            match_datetime = m.get("match_datetime", "")

            kickoff = None
            try:
                kickoff = datetime.strptime(
                    f"{match_date[:4]}-{match_datetime}", "%Y-%m-%d %H:%M"
                )
            except (TypeError, ValueError):
                pass

            match_id = None
            if kickoff is not None:
                cur.execute(
                    """
                    SELECT id, home_team_name, away_team_name
                    FROM official_matches
                    WHERE kickoff_time BETWEEN %s - INTERVAL '15 minutes'
                                           AND %s + INTERVAL '15 minutes'
                    ORDER BY kickoff_time, id
                    """,
                    (kickoff, kickoff),
                )
                match_id = _select_official_match(home, away, list(cur.fetchall()))

            if match_id is not None:
                result = _to_result_dict(m)
                result["match_id"] = match_id
                result["raw_json"]["official_match_resolution"] = {
                    "method": "kickoff_and_team_similarity",
                    "provider_home_team": home,
                    "provider_away_team": away,
                }
                results.append(result)

    return results


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if date_arg is None:
        date_arg = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"Fetching 500.com results for {date_arg}...")
    html = _fetch_page(date_arg)
    matches = parse_match_results(html)
    finished = [m for m in matches if m["status"] == "完" and m["ft_home_goals"] is not None]

    print(f"Total matches: {len(matches)}, Finished with scores: {len(finished)}")
    for m in finished[:15]:
        score = f"{m['ft_home_goals']}-{m['ft_away_goals']}"
        ht = f"{m['ht_home_goals']}-{m['ht_away_goals']}" if m['ht_home_goals'] is not None else '?-?'
        print(f"  {m['match_datetime']} [{m['league']}] {m['home_team']} {score} {m['away_team']} (HT: {ht})")
