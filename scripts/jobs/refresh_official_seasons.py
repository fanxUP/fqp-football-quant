"""Refresh league-season fixtures from the official Sporttery league archive."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.sporttery_client import SportteryClient

OFFICIAL_SOURCE_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/league/getMatchResultV1.qry"
)

TARGET_LEAGUES: dict[str, dict[str, Any]] = {
    "挪威超级联赛": {"official_name": "挪超", "uniform_league_id": 1779},
    "芬兰超级联赛": {"official_name": "芬超", "uniform_league_id": 1073},
    "瑞典超级联赛": {"official_name": "瑞超", "uniform_league_id": 1085},
    "韩国职业联赛": {"official_name": "韩职", "uniform_league_id": 86},
}


@dataclass(frozen=True)
class SeasonCandidate:
    season_id: int
    season_name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class SelectedSeasonWindow:
    season_id: int
    season_name: str
    season_start: date
    season_end: date
    fetch_start: date
    fetch_end: date
    selection_reason: str


def select_season_window(candidates: list[SeasonCandidate], *, today: date) -> SelectedSeasonWindow:
    """Apply the user-defined per-league current/previous season rule."""
    if not candidates:
        raise ValueError("official league has no season candidates")
    ordered = sorted(candidates, key=lambda item: item.start_date, reverse=True)
    active = next(
        (item for item in ordered if item.start_date <= today <= item.end_date),
        None,
    )
    if active is not None:
        return SelectedSeasonWindow(
            active.season_id,
            active.season_name,
            active.start_date,
            active.end_date,
            active.start_date,
            today,
            "current_started",
        )

    completed = next((item for item in ordered if item.end_date < today), None)
    if completed is None:
        raise ValueError("official league has not started and has no completed season")
    has_future = any(item.start_date > today for item in ordered)
    return SelectedSeasonWindow(
        completed.season_id,
        completed.season_name,
        completed.start_date,
        completed.end_date,
        completed.start_date,
        completed.end_date,
        "previous_complete" if has_future else "latest_complete",
    )


def iter_date_windows(start: date, end: date) -> Iterable[tuple[date, date]]:
    """Yield inclusive windows because the official page requests seven days at a time."""
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=6), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _score(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or ":" not in value:
        return None, None
    home, away = value.split(":", 1)
    try:
        return int(home), int(away)
    except ValueError:
        return None, None


def normalize_match(
    raw: dict[str, Any],
    *,
    uniform_league_id: int,
    league_name: str,
    season_id: int,
    season_name: str,
) -> dict[str, Any]:
    """Normalize one official league fixture without inventing a betting code."""
    kickoff = datetime.fromisoformat(f"{raw['matchDate']}T{raw.get('matchTime') or '00:00'}")
    half_home, half_away = _score(raw.get("sectionsNo1"))
    full_home, full_away = _score(raw.get("sectionsNo999"))
    gm_match_id = raw.get("gmMatchId")
    if gm_match_id in (None, "", 0, "0"):
        gm_match_id = None
    return {
        "uniform_match_id": int(raw["uniformMatchId"]),
        "gm_match_id": str(gm_match_id) if gm_match_id is not None else None,
        "official_match_code": None,
        "uniform_league_id": uniform_league_id,
        "season_id": season_id,
        "season_name": season_name,
        "league_name": league_name,
        "uniform_home_team_id": raw.get("uniformHomeTeamId"),
        "uniform_away_team_id": raw.get("uniformAwayTeamId"),
        "home_team_name": raw.get("homeAbbCnName") or "",
        "away_team_name": raw.get("awayAbbCnName") or "",
        "kickoff_time": kickoff,
        "round_name": raw.get("gameweek") or raw.get("phaseName"),
        "phase_name": raw.get("phaseName"),
        "match_status": raw.get("wbsjMatchSc") or raw.get("wbsjMatchScDesc") or "scheduled",
        "half_home_goals": half_home,
        "half_away_goals": half_away,
        "full_home_goals": full_home,
        "full_away_goals": full_away,
        "source_name": "sporttery",
        "source_url": OFFICIAL_SOURCE_URL,
        "raw_json": raw,
    }


def flatten_leagues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the official hot/normal/other league catalog without duplicates."""
    value = payload.get("value") or {}
    rows: list[dict[str, Any]] = []
    rows.extend(value.get("hot") or [])
    rows.extend(value.get("other") or [])
    for area in value.get("normal") or []:
        for country in area.get("countryList") or []:
            rows.extend(country.get("leagueList") or [])
    unique: dict[int, dict[str, Any]] = {}
    for row in rows:
        league_id = row.get("uniformLeagueId")
        if league_id is not None:
            unique[int(league_id)] = row
    return list(unique.values())


def _candidate_from_response(
    season: dict[str, Any], response: dict[str, Any]
) -> SeasonCandidate | None:
    value = response.get("value") or {}
    start = value.get("seasonStartDate")
    end = value.get("seasonEndDate")
    if not start or not end:
        return None
    return SeasonCandidate(
        season_id=int(season["seasonId"]),
        season_name=str(season["seasonName"]),
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
    )


def _response_matches(response: dict[str, Any]) -> list[dict[str, Any]]:
    groups = (response.get("value") or {}).get("matchList") or []
    return [match for group in groups for match in (group.get("subMatchList") or [])]


def _artifact(
    *,
    response: dict[str, Any],
    params: dict[str, Any],
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "source_name": "sporttery",
        "source_url": OFFICIAL_SOURCE_URL,
        "request_params": params,
        "retrieved_at": retrieved_at,
        "response": response,
    }


def _write_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _competition_season_id(conn: Any, league_name: str, season_name: str) -> int | None:
    season_codes = [season_name, season_name.replace("/20", "/")]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cs.id
            FROM competition_seasons cs
            JOIN competitions c ON c.id = cs.competition_id
            JOIN seasons s ON s.id = cs.season_id
            WHERE c.competition_name_cn = %s
              AND s.season_code = ANY(%s)
            LIMIT 1
            """,
            (league_name, season_codes),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def _upsert_league(
    conn: Any,
    *,
    fixtures: list[dict[str, Any]],
    selected: SelectedSeasonWindow,
) -> dict[str, int]:
    if not fixtures:
        raise RuntimeError(
            "official season response contained no fixtures; refusing reconciliation"
        )
    competition_season_id = _competition_season_id(
        conn, fixtures[0]["league_name"], selected.season_name
    )
    written = 0
    with conn.cursor() as cur:
        for item in fixtures:
            cur.execute(
                """
                INSERT INTO official_season_matches (
                    uniform_match_id, gm_match_id, official_match_id,
                    uniform_league_id, season_id, season_name,
                    season_start_date, season_end_date, selection_reason,
                    competition_season_id, uniform_home_team_id,
                    uniform_away_team_id, league_name, home_team_name,
                    away_team_name, kickoff_time, round_name, phase_name,
                    match_status, half_home_goals, half_away_goals,
                    full_home_goals, full_away_goals, source_name, source_url,
                    raw_json
                ) VALUES (
                    %(uniform_match_id)s, %(gm_match_id)s,
                    (SELECT id FROM official_matches
                     WHERE source_match_id = %(gm_match_id)s LIMIT 1),
                    %(uniform_league_id)s, %(season_id)s, %(season_name)s,
                    %(season_start)s, %(season_end)s, %(selection_reason)s,
                    %(competition_season_id)s, %(uniform_home_team_id)s,
                    %(uniform_away_team_id)s, %(league_name)s,
                    %(home_team_name)s, %(away_team_name)s, %(kickoff_time)s,
                    %(round_name)s, %(phase_name)s, %(match_status)s,
                    %(half_home_goals)s, %(half_away_goals)s,
                    %(full_home_goals)s, %(full_away_goals)s, %(source_name)s,
                    %(source_url)s, %(raw_json)s
                )
                ON CONFLICT (uniform_league_id, season_id, uniform_match_id)
                DO UPDATE SET
                    gm_match_id = EXCLUDED.gm_match_id,
                    official_match_id = EXCLUDED.official_match_id,
                    season_start_date = EXCLUDED.season_start_date,
                    season_end_date = EXCLUDED.season_end_date,
                    selection_reason = EXCLUDED.selection_reason,
                    competition_season_id = EXCLUDED.competition_season_id,
                    uniform_home_team_id = EXCLUDED.uniform_home_team_id,
                    uniform_away_team_id = EXCLUDED.uniform_away_team_id,
                    home_team_name = EXCLUDED.home_team_name,
                    away_team_name = EXCLUDED.away_team_name,
                    kickoff_time = EXCLUDED.kickoff_time,
                    round_name = EXCLUDED.round_name,
                    phase_name = EXCLUDED.phase_name,
                    match_status = EXCLUDED.match_status,
                    half_home_goals = EXCLUDED.half_home_goals,
                    half_away_goals = EXCLUDED.half_away_goals,
                    full_home_goals = EXCLUDED.full_home_goals,
                    full_away_goals = EXCLUDED.full_away_goals,
                    source_url = EXCLUDED.source_url,
                    raw_json = EXCLUDED.raw_json,
                    updated_at = now()
                """,
                {
                    **item,
                    "season_start": selected.season_start,
                    "season_end": selected.season_end,
                    "selection_reason": selected.selection_reason,
                    "competition_season_id": competition_season_id,
                    "raw_json": Json(item["raw_json"]),
                },
            )
            written += 1

        league_id = fixtures[0]["uniform_league_id"]
        seen_ids = [item["uniform_match_id"] for item in fixtures]
        cur.execute(
            "DELETE FROM official_season_matches WHERE uniform_league_id = %s AND season_id <> %s",
            (league_id, selected.season_id),
        )
        removed_other_seasons = cur.rowcount
        cur.execute(
            """
            DELETE FROM official_season_matches
            WHERE uniform_league_id = %s
              AND season_id = %s
              AND (
                  kickoff_time::date NOT BETWEEN %s AND %s
                  OR uniform_match_id <> ALL(%s)
              )
            """,
            (
                league_id,
                selected.season_id,
                selected.fetch_start,
                selected.fetch_end,
                seen_ids,
            ),
        )
        removed_stale = cur.rowcount
    return {
        "written": written,
        "removed_other_seasons": removed_other_seasons,
        "removed_stale": removed_stale,
    }


def run(
    *,
    today: date | None = None,
    league_names: list[str] | None = None,
    dry_run: bool = False,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Refresh the configured official leagues using their own season dates."""
    business_today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    selected_names = league_names or list(TARGET_LEAGUES)
    unknown = sorted(set(selected_names) - set(TARGET_LEAGUES))
    if unknown:
        raise ValueError(f"unsupported configured leagues: {', '.join(unknown)}")
    root = artifact_root or Path("data/official_seasons") / business_today.isoformat()
    client = SportteryClient(min_interval=1.0)
    catalog_response = client.get_uniform_league_list()
    retrieved_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    _write_artifact(
        root / "league_catalog.json",
        {
            "source_name": "sporttery",
            "source_url": client.UNIFORM_BASE_URL + "league/getLeagueListV1.qry",
            "request_params": {},
            "retrieved_at": retrieved_at,
            "response": catalog_response,
        },
    )
    catalog = {int(row["uniformLeagueId"]): row for row in flatten_leagues(catalog_response)}
    reports: list[dict[str, Any]] = []

    for league_name in selected_names:
        config = TARGET_LEAGUES[league_name]
        league_id = int(config["uniform_league_id"])
        league = catalog.get(league_id)
        if league is None or league.get("leagueAbbCnName") != config["official_name"]:
            raise RuntimeError(f"official league identity mismatch: {league_name} ({league_id})")

        candidates: list[SeasonCandidate] = []
        for season in (league.get("seasonList") or [])[:3]:
            params = {"uniformLeagueId": league_id, "seasonId": int(season["seasonId"])}
            response = client.get_uniform_league_matches(
                uniform_league_id=league_id,
                season_id=int(season["seasonId"]),
            )
            _write_artifact(
                root / f"{league_id}_{season['seasonId']}_metadata.json",
                _artifact(response=response, params=params, retrieved_at=retrieved_at),
            )
            candidate = _candidate_from_response(season, response)
            if candidate is not None:
                candidates.append(candidate)
        selected = select_season_window(candidates, today=business_today)

        by_id: dict[int, dict[str, Any]] = {}
        for start, end in iter_date_windows(selected.fetch_start, selected.fetch_end):
            params = {
                "uniformLeagueId": league_id,
                "seasonId": selected.season_id,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
            }
            response = client.get_uniform_league_matches(
                uniform_league_id=league_id,
                season_id=selected.season_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
            _write_artifact(
                root / f"{league_id}_{selected.season_id}_{start}_{end}.json",
                _artifact(response=response, params=params, retrieved_at=retrieved_at),
            )
            for raw in _response_matches(response):
                normalized = normalize_match(
                    raw,
                    uniform_league_id=league_id,
                    league_name=league_name,
                    season_id=selected.season_id,
                    season_name=selected.season_name,
                )
                by_id[normalized["uniform_match_id"]] = normalized

        fixtures = sorted(by_id.values(), key=lambda item: item["kickoff_time"])
        write_report = {"written": 0, "removed_other_seasons": 0, "removed_stale": 0}
        if not dry_run:
            with get_db() as conn:
                write_report = _upsert_league(conn, fixtures=fixtures, selected=selected)
                conn.commit()
        reports.append(
            {
                "league_name": league_name,
                "official_league_name": config["official_name"],
                "uniform_league_id": league_id,
                "season_id": selected.season_id,
                "season_name": selected.season_name,
                "season_start": selected.season_start.isoformat(),
                "season_end": selected.season_end.isoformat(),
                "fetch_start": selected.fetch_start.isoformat(),
                "fetch_end": selected.fetch_end.isoformat(),
                "selection_reason": selected.selection_reason,
                "fixtures_found": len(fixtures),
                **write_report,
            }
        )

    summary = {
        "status": "dry_run" if dry_run else "ok",
        "business_date": business_today.isoformat(),
        "source_name": "sporttery",
        "artifact_root": str(root.resolve()),
        "leagues": reports,
    }
    _write_artifact(root / "run_summary.json", summary)
    client.close()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", action="append", choices=sorted(TARGET_LEAGUES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--today", type=date.fromisoformat)
    args = parser.parse_args()
    print(run(today=args.today, league_names=args.league, dry_run=args.dry_run))
