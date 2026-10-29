"""Bounded, offline EPL source adaptation; publication uses the shared PostgreSQL.

The default command previews source quality. --apply additionally requires an
explicit loopback DATABASE_URL; it never trains models or writes official data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extensions import parse_dsn

from scripts.titan007_data import ROOT, open_source

CONFIG_PATH = ROOT / "configs" / "titan007" / "league_import.json"
CONTRACT = "fqp.titan007-league/v1"
SCOPES = {"total": "all", "home": "home", "away": "away"}


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def season_content_hash(data: dict) -> str:
    """Keep content idempotent across repeated acquisition of identical facts.

    Preserve v1 keys for old snapshots: acquisition was always None there.
    Transport receipts separately pin the full payload, including acquisition.
    """
    return content_hash(
        {
            **{key: value for key, value in data.items() if key != "content_sha256"},
            "source_acquired_at": None,
        }
    )


def _time(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        at = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return at.astimezone(UTC).isoformat()


def _number(value, *, positive=False, signed=False):
    if value is None:
        return None
    if type(value) is not int or (positive and value <= 0) or (not signed and value < 0):
        raise ValueError("invalid integer")
    return value


def load_season(data_dir=None, *, config=None) -> dict:
    """Freeze one SQLite read transaction; do not consult its stale count cache.

    Source update time is distinct from acquisition/availability. The old cache
    has no per-season acquisition timestamp, so that field remains unknown.
    """
    config = dict(config or json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    league_id, season = config["source_league_id"], config["season"]
    if type(league_id) is not int or league_id <= 0:
        raise ValueError("来源联赛 ID 无效")
    with open_source(data_dir) as conn:
        conn.execute("BEGIN")
        info = conn.execute(
            "SELECT * FROM league_info WHERE league_id=? AND season=?", (league_id, season)
        ).fetchone()
        if info is None:
            raise ValueError("来源缓存中没有指定赛季，未使用其他赛季替代")
        raw: dict[str, Any] = {
            "info": dict(info),
            "fixtures": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM league_results WHERE league_id=? AND season=? ORDER BY match_id LIMIT 2001",
                    (league_id, season),
                )
            ],
            "standings": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM league_standings WHERE league_id=? AND season=? ORDER BY scope,team_id LIMIT 1001",
                    (league_id, season),
                )
            ],
        }
        if len(raw["fixtures"]) > 2000 or len(raw["standings"]) > 1000:
            raise ValueError("单赛季导入超过本批上限")
        active_ids = {row[k] for row in raw["fixtures"] for k in ("home_id", "away_id")} | {
            row["team_id"] for row in raw["standings"]
        }
        teams = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM league_teams WHERE league_id=? ORDER BY team_id", (league_id,)
            )
            if row["team_id"] in active_ids
        ]
        raw["teams"] = teams
    team_rows = []
    for row in teams:
        source_id = _number(row["team_id"], positive=True)
        if source_id is None or not isinstance(row.get("name"), str) or not row["name"].strip():
            continue
        team_rows.append(
            {
                "source_id": source_id,
                "name": row["name"].strip(),
                "name_en": row.get("name_en") or None,
            }
        )
    valid_teams = {row["source_id"] for row in team_rows}
    fixtures, rejected = [], []
    start, end = date.fromisoformat(config["start_date"]), date.fromisoformat(config["end_date"])
    if config["expected_fixtures"] != config["expected_teams"] * (config["expected_teams"] - 1):
        raise ValueError("本批适配器仅支持显式配置的主客双循环联赛")
    for row in raw["fixtures"]:
        try:
            mid = _number(row["match_id"], positive=True)
            if (
                mid is None
                or row["home_id"] not in valid_teams
                or row["away_id"] not in valid_teams
                or row["home_id"] == row["away_id"]
            ):
                raise ValueError("missing_or_invalid_team_identity")
            hg, ag = _number(row["home_score"]), _number(row["away_score"])
            kickoff = _time(row["match_time"])
            if (
                kickoff
                and not start
                <= datetime.fromisoformat(kickoff).astimezone(ZoneInfo("Asia/Shanghai")).date()
                <= end
            ):
                raise ValueError("outside_configured_season")
            status = {
                -1: "finished",
                0: "scheduled",
                -14: "postponed",
                -11: "postponed",
                -10: "cancelled",
            }.get(row["status"], "live" if row["status"] in (1, 2, 3, 4, 5, 6) else "unknown")
            if status == "finished" and (hg is None or ag is None):
                status = "unknown"
            if status in ("scheduled", "postponed", "cancelled"):
                hg = ag = None
            round_no = _number(row["round"], positive=True)
            if round_no is not None and round_no > config["total_rounds"]:
                raise ValueError("outside_configured_rounds")
            fixtures.append(
                {
                    "source_id": str(mid),
                    "home_source_id": row["home_id"],
                    "away_source_id": row["away_id"],
                    "kickoff": kickoff,
                    "roundId": f"r{round_no}" if round_no else None,
                    "status": status,
                    "homeGoals": hg,
                    "awayGoals": ag,
                }
            )
        except ValueError as exc:
            rejected.append({"source_id": row["match_id"], "reason": str(exc)})
    # This declared double round-robin has one fixture per ordered team pair.
    # Conflicting external IDs are quarantined together, not arbitrarily merged.
    pairs = Counter((row["home_source_id"], row["away_source_id"]) for row in fixtures)
    conflicting = [
        row for row in fixtures if pairs[row["home_source_id"], row["away_source_id"]] > 1
    ]
    rejected.extend(
        {"source_id": row["source_id"], "reason": "conflicting_source_ids_for_season_pair"}
        for row in conflicting
    )
    fixtures = [row for row in fixtures if pairs[row["home_source_id"], row["away_source_id"]] == 1]
    standings: dict[str, list[dict]] = {}
    invalid_scopes: set[str] = set()
    fields = {
        "rank": "rank",
        "played": "played",
        "won": "win",
        "drawn": "draw",
        "lost": "loss",
        "goalsFor": "goals_for",
        "goalsAgainst": "goals_against",
        "goalDifference": "goal_diff",
        "points": "points",
    }
    for row in raw["standings"]:
        scope = SCOPES.get(row["scope"])
        if scope is None:
            continue  # Half-time tables are not full-time home/away tables.
        try:
            if row["team_id"] not in valid_teams:
                raise ValueError("unmapped team")
            values = {
                dest: _number(
                    row[src], positive=dest == "rank", signed=dest in ("goalDifference", "points")
                )
                for dest, src in fields.items()
            }
            if any(value is None for value in values.values()):
                invalid_scopes.add(scope)
            if (
                all(values[key] is not None for key in ("played", "won", "drawn", "lost"))
                and values["played"] != values["won"] + values["drawn"] + values["lost"]
            ):
                invalid_scopes.add(scope)
            if (
                all(
                    values[key] is not None
                    for key in ("goalsFor", "goalsAgainst", "goalDifference")
                )
                and values["goalDifference"] != values["goalsFor"] - values["goalsAgainst"]
            ):
                invalid_scopes.add(scope)
            standings.setdefault(scope, []).append(
                {
                    "source_team_id": row["team_id"],
                    **values,
                    "form": None,
                    "note": "积分保留来源值，含可能的扣分或判罚调整",
                }
            )
        except ValueError:
            invalid_scopes.add(scope)
    expected = config["expected_teams"]
    complete = {
        scope: scope not in invalid_scopes
        and len(rows) == expected
        and len({r["source_team_id"] for r in rows}) == expected
        and {r["rank"] for r in rows} == set(range(1, expected + 1))
        for scope, rows in standings.items()
    }
    fixture_complete = (
        not rejected
        and len(team_rows) == expected
        and len(fixtures) == config["expected_fixtures"]
        and len({(r["home_source_id"], r["away_source_id"]) for r in fixtures})
        == config["expected_fixtures"]
        and all(r["kickoff"] and r["status"] != "unknown" for r in fixtures)
    )
    result = {
        "contract": CONTRACT,
        "config": config,
        "source_as_of": _time(raw["info"].get("last_update")),
        "source_acquired_at": None,
        "teams": team_rows,
        "fixtures": fixtures,
        "standings": standings,
        "raw": raw,
        "report": {
            "source_fixture_count": len(raw["fixtures"]),
            "accepted_fixtures": len(fixtures),
            "rejected_fixtures": rejected,
            "source_team_count": len(team_rows),
            "scope_complete": complete,
            "fixture_coverage_complete": fixture_complete,
        },
    }
    result["content_sha256"] = season_content_hash(result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Publish one atomic batch to explicit loopback DATABASE_URL",
    )
    mode.add_argument(
        "--check-mapping",
        action="store_true",
        help="Plan identity/import writes then roll them back; PostgreSQL sequences may advance",
    )
    args = parser.parse_args(argv)
    data = load_season(args.data_dir, config=json.loads(args.config.read_text(encoding="utf-8")))
    if not args.apply and not args.check_mapping:
        print(
            json.dumps(
                {
                    "mode": "source_preview",
                    "sha256": data["content_sha256"],
                    "source_as_of": data["source_as_of"],
                    **data["report"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn or parse_dsn(dsn).get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("导入需要显式设置本机 DATABASE_URL；不会自动连接默认库或远程生产库")
    import psycopg2

    from scripts.league_reference_storage import import_season

    with closing(psycopg2.connect(dsn, connect_timeout=5)) as conn, conn:
        report = import_season(conn, data, dry_run=not args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
