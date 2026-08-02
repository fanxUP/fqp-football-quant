"""Read-only reconstruction of historical Sporttery markets for ticket entry."""

from __future__ import annotations

from datetime import datetime
from typing import Any


PLAY_TYPES = ("spf", "rqspf", "zjq", "bf", "bqc")
_WIN_DRAW_LOSS_ORDER = {"h": 0, "3": 0, "d": 1, "1": 1, "a": 2, "0": 2}


def _new_markets() -> dict[str, dict[str, Any]]:
    return {
        play_type: {
            "handicap": None,
            "is_single_allowed": False,
            "is_pass_allowed": False,
            "options": [],
        }
        for play_type in PLAY_TYPES
    }


def _option_sort_key(play_type: str, option_code: object) -> tuple[int, str]:
    """Keep win/draw/loss markets in the Sporttery home-draw-away order."""
    code = str(option_code).lower()
    if play_type in {"spf", "rqspf"}:
        return (_WIN_DRAW_LOSS_ORDER.get(code, 99), code)
    return (0, code)


def build_time_machine_matches(
    match_rows: list[tuple], odds_rows: list[tuple],
) -> list[dict[str, Any]]:
    """Build historical match cards using only snapshots captured before sale stop.

    Query callers may return a wider snapshot window for diagnostics. This
    defensive filter keeps a post-stop snapshot from ever becoming selectable.
    """
    matches: dict[int, dict[str, Any]] = {}
    sale_stops: dict[int, datetime] = {}
    for row in match_rows:
        match_id, code, league, home, away, kickoff, sale_stop, _raw_json = row
        stop_at = sale_stop or kickoff
        sale_stops[int(match_id)] = stop_at
        matches[int(match_id)] = {
            "match_id": int(match_id),
            "business_date": kickoff.date().isoformat() if hasattr(kickoff, "date") else "",
            "league_name": league,
            "home_team_name": home,
            "away_team_name": away,
            "kickoff_time": kickoff.isoformat() if hasattr(kickoff, "isoformat") else str(kickoff),
            "match_status": "historical",
            "match_num_str": code,
            "sale_stop_time": stop_at.isoformat() if hasattr(stop_at, "isoformat") else str(stop_at),
            "odds": _new_markets(),
        }

    latest: dict[tuple[int, str, str], tuple] = {}
    for row in odds_rows:
        match_id, snapshot_id, snapshot_time, play_type, option_code, option_name, sp_value, handicap, is_single = row
        match_id = int(match_id)
        if match_id not in matches or play_type not in PLAY_TYPES:
            continue
        if snapshot_time > sale_stops[match_id]:
            continue
        key = (match_id, str(play_type), str(option_code))
        existing = latest.get(key)
        if existing is None or snapshot_time > existing[2] or (
            snapshot_time == existing[2] and int(snapshot_id) > int(existing[1])
        ):
            latest[key] = row

    for row in latest.values():
        match_id, snapshot_id, snapshot_time, play_type, option_code, option_name, sp_value, handicap, is_single = row
        market = matches[int(match_id)]["odds"][str(play_type)]
        if handicap is not None:
            market["handicap"] = float(handicap)
        market["is_single_allowed"] = market["is_single_allowed"] or bool(is_single)
        # Historical official snapshots do not always carry pool permissions;
        # entries are still validated by the same canonical pass calculator.
        market["is_pass_allowed"] = True
        market["options"].append(
            {
                "option_code": option_code,
                "option_name": option_name,
                "sp_value": float(sp_value),
                "odds_snapshot_id": int(snapshot_id),
                "snapshot_time": snapshot_time.isoformat()
                if hasattr(snapshot_time, "isoformat")
                else str(snapshot_time),
            }
        )

    for match in matches.values():
        for play_type, market in match["odds"].items():
            market["options"].sort(key=lambda item: _option_sort_key(play_type, item["option_code"]))
    return list(matches.values())
