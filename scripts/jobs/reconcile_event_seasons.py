"""Resolve target seasons and physically purge out-of-scope official matches."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from apps.backend.src.db import get_db
from scripts.sporttery_client import SportteryClient

SPORTTERY_CATALOG_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/league/getLeagueListV1.qry"
)
SPORTTERY_SEASON_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/league/getMatchResultV1.qry"
)


@dataclass(frozen=True)
class OfficialLeagueRef:
    uniform_league_id: int
    official_name: str


@dataclass(frozen=True)
class SeasonCandidate:
    season_id: int | None
    season_name: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class SelectedSeasonWindow:
    season_name: str
    start_date: date
    end_date: date
    selection_reason: str


def _refs(*items: tuple[int, str]) -> tuple[OfficialLeagueRef, ...]:
    return tuple(OfficialLeagueRef(*item) for item in items)


OFFICIAL_LEAGUE_REFS: dict[str, tuple[OfficialLeagueRef, ...]] = {
    "U20世界杯": _refs((112, "世界杯20")),
    "U23亚洲杯": _refs((27, "亚洲杯23")),
    "世界杯": _refs((2308, "世界杯")),
    "世界杯预选赛": _refs(
        (111, "世预赛"), (942, "世预赛"), (941, "世预赛"),
        (305, "世预赛"), (1443, "世预赛"), (1758, "世预赛"),
        (1703, "世预赛"),
    ),
    "东亚锦标赛": _refs((57, "东亚锦")),
    "中北美金杯赛": _refs((90, "金杯赛")),
    "亚洲杯": _refs((42, "亚洲杯")),
    "亚运会女足": _refs((60, "亚运女足")),
    "亚运会男足": _refs((106, "亚运男足")),
    "亚洲冠军乙级联赛": _refs((1014, "亚冠乙")),
    "亚洲冠军精英联赛": _refs((41, "亚冠精英")),
    "俱乐部世界杯": _refs((2123, "俱世界杯")),
    "南美解放者杯": _refs((77, "解放者杯")),
    "国际赛": _refs((104, "国际赛"), (1498, "国际赛")),
    "女足东亚锦标赛": _refs((9, "女东亚锦")),
    "女足世界杯": _refs((1, "女世界杯")),
    "德国乙级联赛": _refs((1757, "德乙")),
    "德国杯": _refs((87, "德国杯")),
    "德国甲级联赛": _refs((1803, "德甲")),
    "德国超级杯": _refs((3, "德超杯")),
    "意大利杯": _refs((26, "意大利杯")),
    "意大利甲级联赛": _refs((73, "意甲")),
    "意大利超级杯": _refs((50, "意超杯")),
    "奥运会女足": _refs((63, "奥运女足")),
    "奥运会男足": _refs((8, "奥运男足")),
    "挪威超级联赛": _refs((1779, "挪超")),
    "日本乙级联赛": _refs((1789, "日乙")),
    "日本职业联赛": _refs((2279, "日职")),
    "日本联赛杯": _refs((84, "日联赛杯")),
    "杯赛": _refs((2178, "杯赛")),
    "欧洲冠军联赛": _refs((30, "欧冠")),
    "欧洲U21锦标赛": _refs((93, "欧锦赛21")),
    "欧洲国家联赛": _refs((69, "欧国联")),
    "欧洲杯": _refs((48, "欧洲杯")),
    "欧洲杯预选赛": _refs((103, "欧预赛")),
    "欧洲协会联赛": _refs((354, "欧协联")),
    "欧洲超级杯": _refs((110, "欧超杯")),
    "欧罗巴联赛": _refs((23, "欧罗巴")),
    "沙特职业联赛": _refs((1767, "沙职")),
    "法国乙级联赛": _refs((1049, "法乙")),
    "法国杯": _refs((18, "法国杯")),
    "法国甲级联赛": _refs((74, "法甲")),
    "澳大利亚超级联赛": _refs((70, "澳超")),
    "瑞典超级联赛": _refs((1085, "瑞超")),
    "美国职业大联盟": _refs((40, "美职")),
    "美国公开赛杯": _refs((53, "公开赛杯")),
    "美洲杯": _refs((91, "美洲杯")),
    "芬兰超级联赛": _refs((1073, "芬超")),
    "英格兰冠军联赛": _refs((71, "英冠")),
    "英格兰甲级联赛": _refs((82, "英甲")),
    "英格兰社区盾杯": _refs((102, "英社区盾")),
    "英格兰联赛杯": _refs((25, "英联赛杯")),
    "英格兰超级联赛": _refs((72, "英超")),
    "英格兰足总杯": _refs((17, "英足总杯")),
    "英格兰锦标赛": _refs((79, "英锦标赛")),
    "荷兰乙级联赛": _refs((1051, "荷乙")),
    "荷兰杯": _refs((92, "荷兰杯")),
    "荷兰甲级联赛": _refs((76, "荷甲")),
    "葡萄牙超级联赛": _refs((78, "葡超")),
    "西班牙国王杯": _refs((21, "西国王杯")),
    "西班牙甲级联赛": _refs((24, "西甲")),
    "西班牙超级杯": _refs((81, "西超杯")),
    "非洲杯": _refs((96, "非洲杯")),
    "韩国杯": _refs((35, "韩国杯")),
    "韩国职业联赛": _refs((86, "韩职")),
}

MANUAL_SEASON_CANDIDATES: dict[str, tuple[SeasonCandidate, ...]] = {
    "CONCACAF Nations League": (
        SeasonCandidate(None, "2026/2027", date(2026, 9, 21), date(2027, 3, 28)),
        SeasonCandidate(None, "2024/2025", date(2024, 9, 5), date(2025, 3, 23)),
    ),
    "FFA Cup": (
        SeasonCandidate(None, "2026", date(2026, 7, 14), date(2026, 10, 31)),
        SeasonCandidate(None, "2025", date(2025, 5, 13), date(2025, 10, 4)),
    ),
    "中北美冠军杯": (
        SeasonCandidate(None, "2026", date(2026, 2, 3), date(2026, 5, 30)),
    ),
    "俄罗斯超级联赛": (
        SeasonCandidate(None, "2025/2026", date(2025, 7, 18), date(2026, 5, 17)),
    ),
    "巴西甲级联赛": (
        SeasonCandidate(None, "2026", date(2026, 1, 28), date(2026, 12, 2)),
    ),
    "女足亚洲杯": (
        SeasonCandidate(None, "2026", date(2026, 3, 1), date(2026, 3, 21)),
    ),
    "巴西杯": (
        SeasonCandidate(None, "2026", date(2026, 2, 17), date(2026, 12, 6)),
    ),
    "挪威杯": (
        SeasonCandidate(None, "2026/2027", date(2026, 6, 5), date(2027, 5, 31)),
    ),
    "日本天皇杯": (
        SeasonCandidate(None, "2026", date(2026, 8, 19), date(2027, 1, 1)),
        SeasonCandidate(None, "2025", date(2025, 5, 24), date(2025, 11, 22)),
    ),
    "瑞典杯": (
        SeasonCandidate(None, "2026/2027", date(2026, 5, 26), date(2027, 5, 31)),
    ),
    "葡萄牙杯": (
        SeasonCandidate(None, "2025/2026", date(2025, 8, 1), date(2026, 5, 24)),
    ),
}

MANUAL_SOURCE_URLS = {
    "CONCACAF Nations League": "https://www.concacaf.com/news/fifth-edition-of-nations-league-to-begin-in-september",
    "FFA Cup": "https://australiacup.com.au/news/hahn-australia-cup-2026-round-32-entrants-and-draw-details-confirmed",
    "中北美冠军杯": "https://www.concacaf.com/competitions/champions-cup/news/concacaf-confirma-fechas-del-sorteo-y-la-final-y-detalles-clave-de-la-copa-de-campeones-concacaf-2026",
    "俄罗斯超级联赛": "https://eng.premierliga.ru/news/rfpl/news_32232.html",
    "巴西甲级联赛": "https://www.cbf.com.br/a-cbf/noticias/informes-cbf/a/cbf-anuncia-novo-calendario-do-futebol-profissional-masculino",
    "女足亚洲杯": "https://www.the-afc.com/en/national/afc_womens_asian_cup.html/news/afc-women%E2%80%99s-asian-cup-australia-2026%E2%84%A2-match-schedule-revealed",
    "巴西杯": "https://www.cbf.com.br/futebol-brasileiro/noticias/copa-brasil/a/cbf-divulga-tabela-basica-plano-geral-de-acoes-e-regulamento-especifico-da-copa-do-brasil-2026",
    "挪威杯": "https://www.fotball.no/turneringer/nm-menn/2026/nm-2026-disse-er-kvalifisert-til-1.-runde",
    "日本天皇杯": "https://www.jfa.jp/match/emperorscup_2026/",
    "瑞典杯": "https://www.svenskfotboll.se/serier-cuper/svenska-cupen/speldatum/",
    "葡萄牙杯": "https://www3.fpf.pt/pt/News/Todas-as-not%C3%ADcias/Not%C3%ADcia/news/49352/contextid/971",
}

DEPENDENT_MATCH_TABLES = (
    "simulation_ticket_items", "prediction_error_analysis",
    "model_committee_votes", "market_efficiency_metrics",
    "odds_probability_conversions", "score_distribution_snapshots",
    "real_ticket_items", "football_pool_issue_matches", "simulator_ticket_items",
    "model_predictions", "official_odds_snapshots", "official_markets",
    "official_results",
)


def select_season_window(
    candidates: list[SeasonCandidate], *, today: date
) -> SelectedSeasonWindow:
    if not candidates:
        raise ValueError("competition has no season candidates")
    ordered = sorted(candidates, key=lambda item: item.start_date, reverse=True)
    active = next((item for item in ordered if item.start_date <= today <= item.end_date), None)
    if active is not None:
        return SelectedSeasonWindow(
            active.season_name, active.start_date, active.end_date, "current_started"
        )
    completed = next((item for item in ordered if item.end_date < today), None)
    if completed is None:
        raise ValueError("competition has not started and has no completed season")
    reason = "previous_complete" if any(item.start_date > today for item in ordered) else "latest_complete"
    return SelectedSeasonWindow(
        completed.season_name, completed.start_date, completed.end_date, reason
    )


def aggregate_selected_windows(
    windows: list[SelectedSeasonWindow],
) -> SelectedSeasonWindow:
    if not windows:
        raise ValueError("competition has no selected regional windows")
    names = {item.season_name for item in windows}
    if len(names) != 1:
        raise ValueError(f"official regions selected different seasons: {sorted(names)}")
    reasons = {item.selection_reason for item in windows}
    reason = "current_started" if "current_started" in reasons else sorted(reasons)[0]
    return SelectedSeasonWindow(
        windows[0].season_name,
        min(item.start_date for item in windows),
        max(item.end_date for item in windows),
        reason,
    )


def flatten_leagues(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    value = payload.get("value") or {}
    rows = list(value.get("hot") or []) + list(value.get("other") or [])
    for area in value.get("normal") or []:
        for country in area.get("countryList") or []:
            rows.extend(country.get("leagueList") or [])
    return {int(row["uniformLeagueId"]): row for row in rows if row.get("uniformLeagueId")}


def _candidate(season: dict[str, Any], response: dict[str, Any]) -> SeasonCandidate:
    value = response.get("value") or {}
    return SeasonCandidate(
        int(season["seasonId"]), str(season["seasonName"]),
        date.fromisoformat(value["seasonStartDate"]),
        date.fromisoformat(value["seasonEndDate"]),
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def resolve_targets(
    *, today: date, artifact_root: Path, client: SportteryClient
) -> dict[str, dict[str, Any]]:
    catalog_response = client.get_uniform_league_list()
    _write_json(artifact_root / "league_catalog.json", catalog_response)
    catalog = flatten_leagues(catalog_response)
    targets: dict[str, dict[str, Any]] = {}

    for league_name, refs in OFFICIAL_LEAGUE_REFS.items():
        selected_refs: list[SelectedSeasonWindow] = []
        evidence: list[dict[str, Any]] = []
        for ref in refs:
            row = catalog.get(ref.uniform_league_id)
            if row is None or row.get("leagueAbbCnName") != ref.official_name:
                raise RuntimeError(f"Sporttery league identity mismatch: {league_name}/{ref}")
            candidates: list[SeasonCandidate] = []
            # Two entries are sufficient: a future season plus the last complete
            # one, or the currently active season plus its predecessor.
            for season in (row.get("seasonList") or [])[:2]:
                response = client.get_uniform_league_matches(
                    uniform_league_id=ref.uniform_league_id,
                    season_id=int(season["seasonId"]),
                )
                _write_json(
                    artifact_root / f"{ref.uniform_league_id}_{season['seasonId']}.json",
                    response,
                )
                candidates.append(_candidate(season, response))
            selected_refs.append(select_season_window(candidates, today=today))
            evidence.append(
                {
                    "uniform_league_id": ref.uniform_league_id,
                    "official_name": ref.official_name,
                    "candidates": [asdict(item) for item in candidates],
                }
            )
        selected = aggregate_selected_windows(selected_refs)
        targets[league_name] = {
            **asdict(selected), "boundary_source": "sporttery",
            "source_url": SPORTTERY_SEASON_URL,
            "official_league_refs": [asdict(ref) for ref in refs],
            "evidence": evidence,
        }

    for league_name, manual_candidates in MANUAL_SEASON_CANDIDATES.items():
        selected = select_season_window(list(manual_candidates), today=today)
        targets[league_name] = {
            **asdict(selected), "boundary_source": "competition_organiser",
            "source_url": MANUAL_SOURCE_URLS[league_name],
            "official_league_refs": [],
            "evidence": [asdict(item) for item in manual_candidates],
        }
    return targets


def _persist_and_purge(
    *, targets: dict[str, dict[str, Any]], today: date, dry_run: bool
) -> dict[str, Any]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT league_name FROM official_matches")
            stored_leagues = {str(row[0]) for row in cur.fetchall()}
            unknown = stored_leagues - set(targets)
            if unknown:
                raise RuntimeError(f"unresolved stored leagues: {', '.join(sorted(unknown))}")

            cur.execute(
                """
                DELETE FROM official_event_season_targets
                WHERE NOT (league_name = ANY(%s))
                """,
                (list(targets),),
            )
            for league_name, target in targets.items():
                serializable_target = json.loads(json.dumps(target, default=str))
                cur.execute(
                    """
                    INSERT INTO official_event_season_targets (
                        league_name, season_name, season_start_date, season_end_date,
                        selection_reason, boundary_source, official_league_refs,
                        source_url, as_of_date, raw_json, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                    ON CONFLICT (league_name) DO UPDATE SET
                        season_name=EXCLUDED.season_name,
                        season_start_date=EXCLUDED.season_start_date,
                        season_end_date=EXCLUDED.season_end_date,
                        selection_reason=EXCLUDED.selection_reason,
                        boundary_source=EXCLUDED.boundary_source,
                        official_league_refs=EXCLUDED.official_league_refs,
                        source_url=EXCLUDED.source_url,
                        as_of_date=EXCLUDED.as_of_date,
                        raw_json=EXCLUDED.raw_json,
                        updated_at=now()
                    """,
                    (
                        league_name, target["season_name"], target["start_date"],
                        target["end_date"], target["selection_reason"],
                        target["boundary_source"], Json(target["official_league_refs"]),
                        target["source_url"], today, Json(serializable_target),
                    ),
                )

            cur.execute(
                """
                CREATE TEMP TABLE event_season_purge_ids ON COMMIT DROP AS
                SELECT m.id
                FROM official_matches m
                LEFT JOIN official_event_season_targets target
                  ON target.league_name = m.league_name
                WHERE target.league_name IS NULL
                   OR m.business_date NOT BETWEEN target.season_start_date
                                              AND target.season_end_date
                """
            )
            cur.execute("SELECT COUNT(*) FROM event_season_purge_ids")
            matches_to_delete = int(cur.fetchone()[0])
            dependent_counts: dict[str, int] = {}
            for table in DEPENDENT_MATCH_TABLES:
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE match_id IN "
                    "(SELECT id FROM event_season_purge_ids)"
                )
                dependent_counts[table] = int(cur.fetchone()[0])
            if not dry_run:
                for table in DEPENDENT_MATCH_TABLES:
                    cur.execute(
                        f"DELETE FROM {table} WHERE match_id IN "
                        "(SELECT id FROM event_season_purge_ids)"
                    )
                cur.execute(
                    "DELETE FROM official_matches WHERE id IN "
                    "(SELECT id FROM event_season_purge_ids)"
                )
                deleted = cur.rowcount
                cur.execute("ANALYZE official_matches")
            else:
                deleted = 0
                conn.rollback()
                return {
                    "matches_to_delete": matches_to_delete,
                    "matches_deleted": deleted,
                    "dependent_rows_to_delete": dependent_counts,
                }
        conn.commit()
    return {
        "matches_to_delete": matches_to_delete,
        "matches_deleted": deleted,
        "dependent_rows_to_delete": dependent_counts,
    }


def run(
    *, today: date | None = None, dry_run: bool = False,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    business_today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    root = artifact_root or Path("data/official_season_targets") / business_today.isoformat()
    client = SportteryClient(min_interval=0.25)
    try:
        targets = resolve_targets(today=business_today, artifact_root=root, client=client)
    finally:
        client.close()
    cleanup = _persist_and_purge(targets=targets, today=business_today, dry_run=dry_run)
    summary = {
        "status": "dry_run" if dry_run else "ok",
        "business_date": business_today.isoformat(),
        "target_count": len(targets),
        "minimum_target_start": min(item["start_date"] for item in targets.values()).isoformat(),
        "maximum_target_end": max(item["end_date"] for item in targets.values()).isoformat(),
        "targets": targets,
        **cleanup,
    }
    _write_json(root / "run_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(today=args.today, dry_run=args.dry_run, artifact_root=args.artifact_root), ensure_ascii=False, default=str))
