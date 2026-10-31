"""Shared, source-labelled league revisions. Caller owns commit/rollback.

Only canonical identity tables and the reference tables are written. Published
batches are immutable; neither official matches nor model inputs are updated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from psycopg2.extras import Json, RealDictCursor, execute_values

from scripts.titan007_import import content_hash

SOURCE = "titan007"
ID_SYSTEM = "league_team"


def _unique_identity(cur, table, column, codes):
    # Identifiers are constants at the two call sites, values are parameterized.
    cur.execute(f"SELECT id FROM {table} WHERE {column}=ANY(%s) ORDER BY id", (codes,))
    rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError("规范身份存在多个候选，需核实赛事/赛季映射")
    return rows[0][0] if rows else None


def _competition_season(cur, config):
    cid = _unique_identity(
        cur,
        "competitions",
        "competition_code",
        [config["competition_code"], *config.get("competition_aliases", [])],
    )
    if cid is None:
        cur.execute(
            "SELECT id FROM competitions WHERE competition_name_cn=ANY(%s) OR (%s IS NOT NULL AND competition_name_en=%s)",
            (
                [config["competition_name"], *config.get("competition_name_aliases", [])],
                config.get("competition_name_en"),
                config.get("competition_name_en"),
            ),
        )
        if cur.fetchall():
            raise ValueError("已有同名赛事，需在配置中核实其规范代码，未重复新建")
        cur.execute(
            "INSERT INTO competitions(competition_code,competition_name_cn,competition_name_en,country,competition_type,is_league) VALUES (%s,%s,%s,%s,'league',true) RETURNING id",
            (
                config["competition_code"],
                config["competition_name"],
                config.get("competition_name_en"),
                config["country"],
            ),
        )
        cid = cur.fetchone()[0]
    cur.execute("SELECT competition_type,is_cup FROM competitions WHERE id=%s", (cid,))
    kind, cup = cur.fetchone()
    if kind != "league" or cup:
        raise ValueError("规范赛事类型与联赛导入配置冲突")
    sid = _unique_identity(
        cur, "seasons", "season_code", [config["season_code"], *config.get("season_aliases", [])]
    )
    if sid is None:
        cur.execute(
            "INSERT INTO seasons(season_code,season_name,start_date,end_date,is_current) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (
                config["season_code"],
                config["season"],
                config["start_date"],
                config["end_date"],
                config["is_current"],
            ),
        )
        sid = cur.fetchone()[0]
    cur.execute("SELECT start_date,end_date FROM seasons WHERE id=%s", (sid,))
    start, end = cur.fetchone()
    if (start and start.isoformat() > config["end_date"]) or (
        end and end.isoformat() < config["start_date"]
    ):
        raise ValueError("规范赛季日期与来源赛季冲突")
    cur.execute(
        "INSERT INTO competition_seasons(competition_id,season_id,total_teams,total_rounds,stage_format) VALUES (%s,%s,%s,%s,'double_round_robin') ON CONFLICT(competition_id,season_id) DO NOTHING",
        (cid, sid, config["expected_teams"], config["total_rounds"]),
    )
    cur.execute(
        "SELECT id,total_teams FROM competition_seasons WHERE competition_id=%s AND season_id=%s",
        (cid, sid),
    )
    csid, count = cur.fetchone()
    if count not in (None, config["expected_teams"]):
        raise ValueError("已存赛季的参赛队数与导入配置冲突")
    return csid


def _team(cur, team, config):
    source_id = str(team["source_id"])
    cur.execute(
        "SELECT team_id FROM football_team_source_links WHERE source_name=%s AND id_system=%s AND source_team_id=%s",
        (SOURCE, ID_SYSTEM, source_id),
    )
    row = cur.fetchone()
    if row:
        return row[0], None
    manual = config.get("team_links", {}).get(source_id)
    if manual:
        cur.execute("SELECT id FROM teams WHERE team_code=%s", (manual["team_code"],))
        row = cur.fetchone()
        if not row or not manual.get("evidence"):
            raise ValueError("人工球队映射必须指定已有规范球队与核实依据")
        tid, method = row[0], "manual"
    else:
        cur.execute(
            "SELECT DISTINCT team_id FROM team_aliases WHERE source_name=%s AND alias_name=%s AND is_verified ORDER BY team_id",
            (SOURCE, team["name"]),
        )
        aliases = cur.fetchall()
        if len(aliases) > 1:
            return None, "ambiguous_verified_alias"
        if aliases:
            tid, method = aliases[0][0], "verified_alias"
        else:
            cur.execute(
                "SELECT id FROM teams WHERE team_name_cn=%s OR (%s IS NOT NULL AND team_name_en=%s) ORDER BY id",
                (team["name"], team["name_en"], team["name_en"]),
            )
            if cur.fetchall():
                return None, "existing_name_requires_verified_link"
            cur.execute(
                "INSERT INTO teams(team_code,team_name_cn,team_name_en,country) VALUES (%s,%s,%s,%s) ON CONFLICT(team_code) DO NOTHING RETURNING id",
                (f"titan007:team:{source_id}", team["name"], team["name_en"], config["country"]),
            )
            row = cur.fetchone()
            if not row:
                # A code without its source link is not silently reclaimed.
                return None, "existing_source_code_requires_verified_link"
            tid, method = row[0], "source_entity"
    cur.execute(
        "INSERT INTO football_team_source_links(source_name,id_system,source_team_id,team_id,resolution_method,evidence) VALUES (%s,%s,%s,%s,%s,%s)",
        (
            SOURCE,
            ID_SYSTEM,
            source_id,
            tid,
            method,
            Json(
                {"source_name": team["name"], "source_name_en": team["name_en"], "manual": manual}
            ),
        ),
    )
    return tid, None


def import_season(conn, data, *, dry_run=False):
    """Publish one complete transaction; failures roll back this call's writes.

    Dry runs roll back all rows (PostgreSQL sequences may still advance). The
    bounded per-source transaction lock serializes overlapping manual importers.
    """
    if conn.autocommit:
        raise ValueError("导入要求事务连接")
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT league_reference_import")
        try:
            cur.execute("SET LOCAL lock_timeout='2s'")
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT pg_advisory_xact_lock(939118,36)")
            config = data["config"]
            csid = _competition_season(cur, config)
            team_ids, unmapped = {}, []
            for team in data["teams"]:
                tid, reason = _team(cur, team, config)
                if tid is None:
                    unmapped.append(
                        {
                            "source_team_id": team["source_id"],
                            "name": team["name"],
                            "reason": reason,
                        }
                    )
                else:
                    team_ids[team["source_id"]] = tid
            fixtures = [
                row
                for row in data["fixtures"]
                if row["home_source_id"] in team_ids and row["away_source_id"] in team_ids
            ]
            quality = {
                **data["report"],
                "imported_fixtures": len(fixtures),
                "imported_teams": len(set(team_ids.values())),
                "unmapped_teams": unmapped,
                "team_ids": sorted(set(team_ids.values())),
                "fixture_coverage_complete": data["report"]["fixture_coverage_complete"]
                and not unmapped,
                "scope_complete": {
                    scope: complete and not unmapped
                    for scope, complete in data["report"]["scope_complete"].items()
                },
                "config": config,
                "source_content_sha256": data["content_sha256"],
            }
            # Resolve identities into the batch key; a newly reviewed mapping
            # creates a new revision even if source bytes did not change.
            digest = content_hash(
                {"source": data["content_sha256"], "teams": sorted(team_ids.items())}
            )
            cur.execute(
                "SELECT id FROM league_reference_batches WHERE competition_season_id=%s AND source_name=%s AND content_sha256=%s AND state='published'",
                (csid, SOURCE, digest),
            )
            previous = cur.fetchone()
            if previous:
                report = {
                    "status": "unchanged",
                    "batch_id": previous[0],
                    "competition_season_id": csid,
                    **quality,
                }
            else:
                cur.execute(
                    "INSERT INTO league_reference_batches(competition_season_id,source_name,source_competition_id,source_season,content_sha256,source_as_of,source_acquired_at,quality,raw_payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (
                        csid,
                        SOURCE,
                        str(config["source_league_id"]),
                        config["season"],
                        digest,
                        data["source_as_of"],
                        data["source_acquired_at"],
                        Json(quality),
                        Json(data["raw"]),
                    ),
                )
                bid = cur.fetchone()[0]
                if fixtures:
                    execute_values(
                        cur,
                        "INSERT INTO league_reference_fixtures(batch_id,source_match_id,home_team_id,away_team_id,kickoff,round_id,status,home_goals,away_goals) VALUES %s",
                        [
                            (
                                bid,
                                row["source_id"],
                                team_ids[row["home_source_id"]],
                                team_ids[row["away_source_id"]],
                                row["kickoff"],
                                row["roundId"],
                                row["status"],
                                row["homeGoals"],
                                row["awayGoals"],
                            )
                            for row in fixtures
                        ],
                    )
                rows = [
                    (
                        bid,
                        scope,
                        team_ids[row["source_team_id"]],
                        row["rank"],
                        row["played"],
                        row["won"],
                        row["drawn"],
                        row["lost"],
                        row["goalsFor"],
                        row["goalsAgainst"],
                        row["goalDifference"],
                        row["points"],
                        row["note"],
                    )
                    for scope, records in data["standings"].items()
                    for row in records
                    if row["source_team_id"] in team_ids
                ]
                if rows:
                    execute_values(
                        cur,
                        "INSERT INTO league_reference_standings(batch_id,scope,team_id,rank,played,won,drawn,lost,goals_for,goals_against,goal_difference,points,note) VALUES %s",
                        rows,
                    )
                cur.execute(
                    "UPDATE league_reference_batches SET state='published' WHERE id=%s", (bid,)
                )
                report = {
                    "status": "published",
                    "batch_id": bid,
                    "competition_season_id": csid,
                    **quality,
                }
            if dry_run:
                cur.execute("ROLLBACK TO SAVEPOINT league_reference_import")
                report["dry_run"] = True
            cur.execute("RELEASE SAVEPOINT league_reference_import")
            return report
        except BaseException:
            cur.execute("ROLLBACK TO SAVEPOINT league_reference_import")
            cur.execute("RELEASE SAVEPOINT league_reference_import")
            raise


def league_catalog(conn, *, dataset="reference"):
    if dataset not in ("reference", "verified"):
        raise ValueError("联赛资料范围无效")
    if dataset == "verified":
        return _verified_catalog(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT DISTINCT ON (b.competition_season_id) b.competition_season_id,
            b.quality->'config' AS config FROM league_reference_batches b
            WHERE b.state='published' AND b.source_name=%s
            ORDER BY b.competition_season_id,b.source_as_of DESC NULLS LAST,b.imported_at DESC,b.id DESC""",
            (SOURCE,),
        )
        records = cur.fetchall()
    competitions: dict[str, dict] = {}
    for row in records:
        conf = row["config"]
        competition = competitions.setdefault(
            conf["competition_code"],
            {
                "code": conf["competition_code"],
                "name": conf["competition_name"],
                "country": conf["country"],
                "seasons": [],
            },
        )
        competition["seasons"].append(
            {
                "id": row["competition_season_id"],
                "label": conf["season"],
                "isCurrent": conf["is_current"],
            }
        )
    for item in competitions.values():
        item["seasons"].sort(key=lambda row: row["label"], reverse=True)
    return {
        "status": "connected" if records else "not_connected",
        "competitions": list(competitions.values())
        or [{"code": "premier-league", "name": "英超", "country": "英格兰", "seasons": []}],
    }


def _batch(cur, season_id, batch_id=None):
    cur.execute(
        """SELECT * FROM league_reference_batches WHERE competition_season_id=%s
        AND state='published' AND source_name=%s AND (%s::bigint IS NULL OR id=%s)
        ORDER BY source_as_of DESC NULLS LAST,imported_at DESC,id DESC LIMIT 1""",
        (season_id, SOURCE, batch_id, batch_id),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError("所选联赛赛季或批次暂无覆盖")
    return row


def _evidence(batch, *, scope=None):
    at = batch["source_as_of"]
    quality = batch["quality"]
    complete = (
        quality["fixture_coverage_complete"]
        if scope is None
        else quality["scope_complete"].get(scope, False)
    )
    return {
        "sourceName": "球探（titan007）",
        "asOf": at.isoformat() if at else None,
        "batchId": str(batch["id"]),
        "completeness": "complete" if complete else "partial",
        "stale": at is None or datetime.now(UTC) - at > timedelta(hours=24),
    }


def _teams(cur, ids):
    cur.execute(
        "SELECT id,COALESCE(NULLIF(BTRIM(team_name_cn),''),NULLIF(BTRIM(team_name_en),''),'名称待补充') AS team_name_cn FROM teams WHERE id=ANY(%s) ORDER BY id",
        (ids,),
    )
    return {
        row["id"]: {"id": row["id"], "name": row["team_name_cn"], "manager": None, "stadium": None}
        for row in cur.fetchall()
    }


def _standing_batch(cur, current, scope):
    """Select one whole complete table, never splice individual latest rows."""
    cur.execute(
        """SELECT * FROM league_reference_batches
        WHERE competition_season_id=%s AND source_name=%s AND state='published'
          AND quality->'scope_complete'->>%s='true'
          AND quality->'team_ids'=%s::jsonb
          AND imported_at<=%s
          AND (source_as_of<=%s OR (source_as_of IS NULL AND %s::timestamptz IS NULL))
        ORDER BY source_as_of DESC NULLS LAST,imported_at DESC,id DESC LIMIT 1""",
        (
            current["competition_season_id"],
            SOURCE,
            scope,
            Json(current["quality"]["team_ids"]),
            current["imported_at"],
            current["source_as_of"],
            current["source_as_of"],
        ),
    )
    return cur.fetchone()


def _form(cur, batch, team_ids, scope):
    forms: dict[int, list[str]] = {tid: [] for tid in team_ids}
    cur.execute(
        """SELECT * FROM league_reference_fixtures WHERE batch_id=%s
        AND status='finished' AND kickoff IS NOT NULL
        AND (%s::timestamptz IS NULL OR kickoff<=%s)
        ORDER BY kickoff,source_match_id""",
        (batch["id"], batch["source_as_of"], batch["source_as_of"]),
    )
    for row in cur.fetchall():
        hg, ag = row["home_goals"], row["away_goals"]
        if scope in ("all", "home"):
            forms[row["home_team_id"]].append("W" if hg > ag else "D" if hg == ag else "L")
        if scope in ("all", "away"):
            forms[row["away_team_id"]].append("W" if ag > hg else "D" if hg == ag else "L")
    return forms


def league_season(conn, season_id, *, dataset="reference"):
    if dataset not in ("reference", "verified"):
        raise ValueError("联赛资料范围无效")
    if dataset == "verified":
        return _verified_season_data(conn, season_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        batch = _batch(cur, season_id)
        quality = batch["quality"]
        teams = _teams(cur, quality["team_ids"])
        cur.execute(
            "SELECT * FROM league_reference_fixtures WHERE batch_id=%s ORDER BY kickoff NULLS LAST,source_match_id",
            (batch["id"],),
        )
        fixtures = cur.fetchall()
        finished = [row for row in fixtures if row["status"] == "finished"]
        standings: dict[str, dict] = {}
        fields = {
            "rank": "rank",
            "played": "played",
            "won": "won",
            "drawn": "drawn",
            "lost": "lost",
            "goalsFor": "goals_for",
            "goalsAgainst": "goals_against",
            "goalDifference": "goal_difference",
            "points": "points",
            "note": "note",
        }
        for scope in ("all", "home", "away"):
            chosen = _standing_batch(cur, batch, scope)
            if chosen is None:
                if scope in quality["scope_complete"]:
                    standings[scope] = {"evidence": _evidence(batch, scope=scope), "rows": []}
                continue
            group = {"evidence": _evidence(chosen, scope=scope), "rows": []}
            forms = _form(cur, chosen, teams, scope)
            cur.execute(
                "SELECT * FROM league_reference_standings WHERE batch_id=%s AND scope=%s ORDER BY rank,team_id",
                (chosen["id"], scope),
            )
            group["rows"] = [
                {
                    "team": teams[row["team_id"]],
                    **{dest: row[src] for dest, src in fields.items()},
                    "form": forms[row["team_id"]][-5:] or None,
                }
                for row in cur.fetchall()
            ]
            standings[scope] = group
    played = len(finished)
    goals = sum(row["home_goals"] + row["away_goals"] for row in finished)
    overview = (
        {
            "played": played,
            "goals": goals,
            "goalsPerMatch": goals / played if played else None,
            "homeWins": sum(row["home_goals"] > row["away_goals"] for row in finished),
            "draws": sum(row["home_goals"] == row["away_goals"] for row in finished),
            "awayWins": sum(row["home_goals"] < row["away_goals"] for row in finished),
        }
        if fixtures
        else None
    )
    rounds = sorted(
        {row["round_id"] for row in fixtures if row["round_id"]}, key=lambda key: int(key[1:])
    )
    return {
        "competitionSeasonId": season_id,
        "evidence": _evidence(batch),
        "coverage": {
            "teams": len(teams),
            "expectedTeams": quality["config"]["expected_teams"],
            "fixtures": len(fixtures),
            "expectedFixtures": quality["config"]["expected_fixtures"],
        },
        "overview": overview,
        "teams": list(teams.values()),
        "rounds": [{"id": key, "label": f"第{key[1:]}轮"} for key in rounds],
        "standings": standings,
    }


def league_fixtures(
    conn,
    season_id,
    *,
    round_id=None,
    status="all",
    team_id=None,
    limit=20,
    offset=0,
    batch_id=None,
    dataset="reference",
):
    if (
        dataset not in ("reference", "verified")
        or status not in ("all", "finished", "upcoming", "postponed")
        or type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or offset < 0
    ):
        raise ValueError("赛程筛选或分页参数无效")
    if dataset == "verified":
        if batch_id is not None or round_id is not None or team_id is not None:
            raise ValueError("核实归属赛程不支持联赛资料批次、轮次或规范球队筛选")
        return _verified_fixtures(conn, season_id, status=status, limit=limit, offset=offset)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        batch = _batch(cur, season_id, batch_id)
        if team_id is not None and team_id not in batch["quality"]["team_ids"]:
            raise LookupError("该赛季未找到所选球队")
        where = "batch_id=%s AND (%s::text IS NULL OR round_id=%s) AND (%s::bigint IS NULL OR home_team_id=%s OR away_team_id=%s)"
        values = [batch["id"], round_id, round_id, team_id, team_id, team_id]
        if status != "all":
            where += " AND status=%s"
            values.append("scheduled" if status == "upcoming" else status)
        cur.execute(
            "SELECT count(*) AS total FROM league_reference_fixtures WHERE " + where, values
        )
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT * FROM league_reference_fixtures WHERE "
            + where
            + " ORDER BY kickoff NULLS LAST,source_match_id LIMIT %s OFFSET %s",
            [*values, limit, offset],
        )
        rows = cur.fetchall()
        teams = _teams(cur, batch["quality"]["team_ids"])
    return {
        "competitionSeasonId": season_id,
        "evidence": _evidence(batch),
        "total": total,
        "rows": [
            {
                "id": f"{SOURCE}:match:{row['source_match_id']}",
                "home": teams[row["home_team_id"]],
                "away": teams[row["away_team_id"]],
                "kickoff": row["kickoff"].isoformat() if row["kickoff"] else None,
                "roundId": row["round_id"],
                "status": row["status"],
                "homeGoals": row["home_goals"],
                "awayGoals": row["away_goals"],
                "officialMatch": None,
            }
            for row in rows
        ],
    }


# This subset joins immutable, explicit memberships, never the planned dates or
# provider season labels. Source IDs are meaningful only in their namespaces.
_VERIFIED_SEASONS = """FROM football_competition_season_sources s
    JOIN competition_seasons cs ON cs.id=s.competition_season_id
    JOIN competitions c ON c.id=cs.competition_id
    JOIN seasons y ON y.id=cs.season_id
    WHERE s.source_name='sporttery' AND s.id_system='uniform.leagueId+seasonId'
      AND c.competition_type='league' AND NOT COALESCE(c.is_cup,false)"""
_VERIFIED_FIXTURES = """FROM football_fixture_season_catalog m
    JOIN football_fixture_source_links j ON j.fixture_id=m.fixture_id
      AND j.source_name='sporttery' AND j.id_system='jc.matchId'
    JOIN official_matches o ON o.source_match_id=j.source_match_id AND o.sport_type='football'
    LEFT JOIN official_results r ON r.match_id=o.id
    WHERE m.competition_season_id=%s AND m.season_source_name='sporttery'
      AND m.season_id_system='uniform.leagueId+seasonId'"""
_CONFIRMED_SCORE = (
    """r.result_status='confirmed' AND r.full_home_goals>=0 AND r.full_away_goals>=0"""
)
_VERIFIED_STATUS = f"""CASE WHEN {_CONFIRMED_SCORE} THEN 'finished'
    WHEN o.match_status IN ('scheduled','live','finished','postponed','cancelled') THEN o.match_status
    ELSE 'unknown' END"""


def _verified_evidence():
    # Neither the membership capture nor this request time is the official facts'
    # publication/as-of time. No reference batch or full-league claim is invented.
    return dict(
        sourceName="中国体育彩票（已核实竞彩归属）",
        asOf=None,
        batchId=None,
        completeness="partial",
        stale=True,
    )


def _verified_catalog(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT s.competition_season_id,c.competition_code,c.competition_name_cn,c.country,y.season_name "
            + _VERIFIED_SEASONS
            + " ORDER BY c.competition_code,y.season_name DESC,s.competition_season_id"
        )
        records = cur.fetchall()
    competitions = {}
    for row in records:
        item = competitions.setdefault(
            row["competition_code"],
            dict(
                code=row["competition_code"],
                name=row["competition_name_cn"],
                country=row["country"] or "未知",
                seasons=[],
            ),
        )
        item["seasons"].append(
            dict(id=row["competition_season_id"], label=row["season_name"], isCurrent=False)
        )
    return dict(
        dataset="verified",
        status="connected" if records else "not_connected",
        competitions=list(competitions.values()),
    )


def _verified_season(cur, season_id):
    cur.execute(
        "SELECT s.source_season_id,s.planned_start_date,s.planned_end_date,s.source_timezone,y.season_name "
        + _VERIFIED_SEASONS
        + " AND s.competition_season_id=%s",
        (season_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise LookupError("所选赛季尚无已核实的体彩赛季来源")
    return row


def _verified_season_data(conn, season_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        season = _verified_season(cur, season_id)
        cur.execute("SELECT count(*) AS total " + _VERIFIED_FIXTURES, (season_id,))
        count = cur.fetchone()["total"]
    return dict(
        dataset="verified",
        competitionSeasonId=season_id,
        evidence=_verified_evidence(),
        coverage=dict(teams=None, expectedTeams=None, fixtures=count, expectedFixtures=None),
        overview=None,
        standings={},
        teams=[],
        rounds=[],
        seasonIdentity=dict(
            label=season["season_name"],
            sourceSeasonId=season["source_season_id"],
            plannedStartDate=season["planned_start_date"].isoformat(),
            plannedEndDate=season["planned_end_date"].isoformat(),
            timeZone=season["source_timezone"],
        ),
    )


def _verified_fixtures(conn, season_id, *, status, limit, offset):
    where = _VERIFIED_FIXTURES
    values = [season_id]
    if status != "all":
        where += " AND (" + _VERIFIED_STATUS + ")=%s"
        values.append("scheduled" if status == "upcoming" else status)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _verified_season(cur, season_id)
        cur.execute("SELECT count(*) AS total " + where, values)
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT m.fixture_id,o.id AS official_id,o.home_team_name,o.away_team_name,"
            "o.kickoff_time AT TIME ZONE 'Asia/Shanghai' AS kickoff,"
            + _VERIFIED_STATUS
            + " AS status,CASE WHEN "
            + _CONFIRMED_SCORE
            + " THEN r.full_home_goals END AS home_goals,CASE WHEN "
            + _CONFIRMED_SCORE
            + " THEN r.full_away_goals END AS away_goals "
            + where
            + " ORDER BY o.kickoff_time,m.fixture_id LIMIT %s OFFSET %s",
            [*values, limit, offset],
        )
        rows = cur.fetchall()
    return dict(
        dataset="verified",
        competitionSeasonId=season_id,
        evidence=_verified_evidence(),
        total=total,
        rows=[
            dict(
                id=f"fqp:fixture:{row['fixture_id']}",
                home=dict(id=None, name=row["home_team_name"], manager=None, stadium=None),
                away=dict(id=None, name=row["away_team_name"], manager=None, stadium=None),
                kickoff=row["kickoff"].isoformat(),
                roundId=None,
                status=row["status"],
                homeGoals=row["home_goals"],
                awayGoals=row["away_goals"],
                officialMatch=dict(id=row["official_id"], verification="verified"),
            )
            for row in rows
        ],
    )
