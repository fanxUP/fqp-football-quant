"""Compute Beijing prediction targets and persist only due work in PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from scripts.prediction_input_updates import InputUpdateSuperseded
from scripts.sporttery_sales import WEEKDAY_CLOSE_TIME, WEEKEND_CLOSE_TIME

BEIJING = ZoneInfo("Asia/Shanghai")
PREDICTION_TIME = time(20, 30)
RETRY_INTERVAL = timedelta(minutes=5)
QUOTE_LEAD = timedelta(minutes=4)
BATCH_SIZE = 24
ACTIVE_STATES = ("scheduled", "selling", "not_started")
PREMATCH_NOTICE_LOCK = (20261109, 1)
PREMATCH_NOTICE_WRITE_LOCK_TIMEOUT = "45s"


def acquire_prematch_notice_write_lock(cur: Any) -> None:
    """Wait up to 45 seconds for the schedule fence, then restore the prior timeout.

    The production role uses a 2-second lock timeout and a 60-second statement
    timeout. Prediction scans may hold this fence while waiting on mechanical-disk
    reads, so official schedule writers need a longer but still bounded wait.
    Other locks and writes in the transaction retain their original lock timeout.
    """
    cur.execute("SELECT current_setting('lock_timeout')")
    previous_timeout = cur.fetchone()[0]
    cur.execute(
        "SELECT set_config('lock_timeout', %s, true)", (PREMATCH_NOTICE_WRITE_LOCK_TIMEOUT,)
    )
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", PREMATCH_NOTICE_LOCK)
    cur.execute("SELECT set_config('lock_timeout', %s, true)", (previous_timeout,))


def beijing_time(value: datetime) -> datetime:
    return value.replace(tzinfo=BEIJING) if value.tzinfo is None else value.astimezone(BEIJING)


def jc_sales_cutoff(business_date: date) -> datetime:
    # Published sales hours are a scheduling reference, never a per-match close fact.
    close = WEEKEND_CLOSE_TIME if business_date.weekday() >= 5 else WEEKDAY_CLOSE_TIME
    return datetime.combine(business_date, close, BEIJING)


def prediction_target(kickoff: datetime, cutoff: datetime | None) -> tuple[datetime, str]:
    kickoff = beijing_time(kickoff)
    if cutoff is None:
        return kickoff - timedelta(hours=2), "schedule_cutoff_unknown"
    cutoff = beijing_time(cutoff)
    if kickoff <= cutoff:
        reason = "kickoff_equals_cutoff" if kickoff == cutoff else "kickoff_before_cutoff"
        return kickoff - timedelta(hours=2), reason
    target = datetime.combine(cutoff.date(), PREDICTION_TIME, BEIJING)
    if target >= kickoff:
        return target - timedelta(days=1), "previous_evening_before_kickoff"
    return target, "sales_day_2030"


def pool_schedule_basis(
    issue_id: int,
    issue_close: datetime | None,
    game_type: str,
    match_order: int,
    kickoff: datetime,
    home: str,
    away: str,
    revision: tuple[dict, str] | None,
) -> tuple[datetime | None, str] | None:
    """Return the latest valid schedule scope, or reject a superseded selection."""
    if revision is not None:
        issue, source = revision
        member = next((m for m in issue["matches"] if m["match_order"] == match_order), None)
        if not member or member["match_date"] != kickoff.date().isoformat():
            return None
        same_teams = (member["home_team_name"], member["away_team_name"]) == (home, away)
        if not same_teams and (
            game_type != "jq4" or set(member["team_names_in_source_order"]) != {home, away}
        ):
            return None
        if issue.get("sale_stop"):
            return datetime.fromisoformat(issue["sale_stop"]), source
    return (beijing_time(issue_close) if issue_close else None, f"football_pool_issue:{issue_id}")


@dataclass(frozen=True)
class PredictionTask:
    match_id: int
    play_type: str
    kickoff_at: datetime
    target_at: datetime
    basis: dict[str, Any]

    @property
    def key(self) -> str:
        material = [
            self.match_id,
            self.play_type,
            self.kickoff_at.isoformat(),
            self.target_at.isoformat(),
            self.basis["source_match_id"],
            self.basis["home"],
            self.basis["away"],
        ]
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def manifest(self, started_at: datetime) -> dict[str, Any]:
        reason = (
            "added_after_target"
            if self.basis.get("match_first_seen_after_target")
            else "late_dispatch"
            if started_at >= self.target_at + timedelta(minutes=1)
            else "on_time"
        )
        return {
            "task_key": self.key,
            "match_id": self.match_id,
            "play_type": self.play_type,
            "kickoff_at": self.kickoff_at.isoformat(),
            "target_at": self.target_at.isoformat(),
            "basis": self.basis,
            "timing": reason,
        }


def due_prediction_tasks(conn: Any, now: datetime) -> tuple[list[PredictionTask], list[dict]]:
    """Read current schedule versions; old revisions never become executable by retry."""
    now = beijing_time(now)
    today = now.date()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.id, m.business_date, m.kickoff_time, m.source_match_id,
                      m.home_team_name, m.away_team_name, m.created_at,
                      k.play_type, p.id, p.sale_stop_time, m.official_match_code,
                      p.game_type, p.issue_no, p.match_order, p.home_team_name, p.away_team_name,
                      EXISTS (SELECT 1 FROM official_matches prior
                              WHERE prior.business_date=m.business_date
                                AND prior.created_at<m.created_at-INTERVAL '1 minute')
               FROM official_matches m
               JOIN LATERAL (
                   SELECT DISTINCT play_type FROM official_markets
                   WHERE match_id=m.id AND play_type IN ('spf','rqspf')
               ) k ON TRUE
               LEFT JOIN LATERAL (
                   SELECT i.id, i.sale_stop_time, i.game_type, i.issue_no, c.match_order,
                          c.home_team_name, c.away_team_name
                   FROM football_pool_fixture_catalog c
                   JOIN football_pool_issues i ON i.id=c.issue_id
                   WHERE c.official_match_id=m.id AND c.identity_status='linked'
                     AND c.kickoff_time=m.kickoff_time AND k.play_type='spf'
                     AND c.kickoff_time_precision IN ('minute','second')
                     AND c.source_game_type=c.game_type
               ) p ON TRUE
               WHERE m.business_date BETWEEN %s AND %s
                 AND m.sport_type='football' AND m.kickoff_time>%s
                 AND LOWER(COALESCE(m.match_status,''))=ANY(%s)
               ORDER BY m.kickoff_time, m.id, k.play_type, p.id""",
            (
                today - timedelta(days=2),
                today + timedelta(days=7),
                now.replace(tzinfo=None),
                list(ACTIVE_STATES),
            ),
        )
        rows = cur.fetchall()
        cur.execute(
            """SELECT published_at, evidence
               FROM sporttery_schedule_notices
               WHERE published_at BETWEEN %s AND %s
               ORDER BY published_at DESC, observed_at DESC""",
            (now - timedelta(days=14), now),
        )
        notices = cur.fetchall()

    adjustments: dict[str, dict] = {}
    fixture_changes: dict[tuple, list[tuple]] = {}
    pool_revisions: dict[tuple, tuple] = {}
    for published, evidence in notices:
        if evidence["kind"] == "jc_sales_window":
            adjustments.setdefault(evidence["business_date"], evidence)
        elif evidence["kind"] == "jc_fixture_change":
            identity = (evidence["match_code"], evidence["home"], evidence["away"])
            fixture_changes.setdefault(identity, []).append((published, evidence))
        elif evidence["kind"] == "pool_schedule":
            for issue in evidence["issues"]:
                pool_revisions.setdefault(
                    (issue["game_type"], issue["issue_no"]), (issue, evidence["source_url"])
                )

    tasks: dict[tuple[int, str, datetime], PredictionTask] = {}
    for (
        mid,
        business_date,
        kickoff,
        source_id,
        home,
        away,
        created,
        play,
        issue_id,
        issue_close,
        code,
        game_type,
        issue_no,
        match_order,
        pool_home,
        pool_away,
        day_already_seen,
    ) in rows:
        kickoff_at = beijing_time(kickoff)
        adjustment = adjustments.get(business_date.isoformat())
        cutoff = (
            datetime.fromisoformat(adjustment["cutoff"])
            if adjustment
            else jc_sales_cutoff(business_date)
        )
        changes = fixture_changes.get((code, home, away), [])
        change = next(
            (
                e
                for published, e in changes
                if abs(beijing_time(published).date() - business_date) <= timedelta(days=3)
            ),
            None,
        )
        if change and (
            change["state"] == "withdrawn"
            or (
                change["state"] == "changed"
                and change["kickoff"] != kickoff.isoformat(timespec="seconds")
            )
        ):
            continue
        scopes = [(cutoff, adjustment["source_url"] if adjustment else "sporttery_jc_sales_hours")]
        if issue_id is not None:
            basis = pool_schedule_basis(
                issue_id,
                issue_close,
                game_type,
                match_order,
                kickoff,
                pool_home,
                pool_away,
                pool_revisions.get((game_type, issue_no)),
            )
            if basis and basis[0] is not None:
                scopes.append((basis[0], basis[1]))
        for cutoff, source in scopes:
            target, rule = prediction_target(kickoff_at, cutoff)
            if target > now + QUOTE_LEAD:
                continue
            key = (mid, play, target)
            # JC rows come first. An identical traditional window can use the same forecast.
            if key in tasks:
                continue
            tasks[key] = PredictionTask(
                mid,
                play,
                kickoff_at,
                target,
                {
                    "rule": rule,
                    "cutoff": cutoff.isoformat(),
                    "source": source,
                    "source_match_id": source_id,
                    "home": home,
                    "away": away,
                    "match_first_seen_after_target": bool(
                        day_already_seen
                        and created
                        and created.replace(tzinfo=UTC) >= target + timedelta(minutes=1)
                    ),
                },
            )

    selected: list[PredictionTask] = []
    manifest: list[dict] = []
    ordered = sorted(
        tasks.values(),
        key=lambda task: (task.kickoff_at, task.target_at, task.match_id, task.play_type),
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT task_key, last_attempt_at, completed_at, attempts "
            "FROM prematch_prediction_tasks WHERE task_key=ANY(%s)",
            ([task.key for task in ordered],),
        )
        receipts = {
            key: (attempted, complete, attempts)
            for key, attempted, complete, attempts in cur.fetchall()
        }
        used: set[tuple[int, str]] = set()
        for task in ordered:
            market = (task.match_id, task.play_type)
            attempted, complete, attempts = receipts.get(task.key, (None, None, 0))
            if complete or attempts >= 5 or (attempted and attempted + RETRY_INTERVAL > now):
                continue
            if task.key not in receipts:
                cur.execute(
                    """INSERT INTO prematch_prediction_tasks
                         (task_key, match_id, play_type, kickoff_at, target_at, schedule_basis)
                       VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (task_key) DO NOTHING""",
                    (
                        task.key,
                        task.match_id,
                        task.play_type,
                        task.kickoff_at,
                        task.target_at,
                        Json(task.basis),
                    ),
                )
            if task.target_at > now or market in used:
                continue
            if not current_official_quote(
                conn, task.match_id, task.play_type, now.replace(tzinfo=None).isoformat()
            ):
                continue
            selected.append(task)
            manifest.append(task.manifest(now))
            used.add(market)
            if len(selected) >= BATCH_SIZE:
                break
    conn.commit()
    return selected, manifest


def attach_prediction_tasks(conn: Any, tasks: list[PredictionTask], run_id: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE prematch_prediction_tasks SET run_id=%s,
                      last_attempt_at=clock_timestamp(), attempts=attempts+1
               WHERE task_key=ANY(%s)""",
            (str(run_id), [task.key for task in tasks]),
        )
    conn.commit()


def complete_prediction_tasks(conn: Any, run_id: Any) -> None:
    """Complete a match/play receipt when its run publishes at least one group.

    A partial run may still provide a usable forecast; missing model groups stay
    visible on the run audit and do not turn this one-shot schedule receipt into
    repeated model executions.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE prematch_prediction_tasks t SET completed_at=r.finished_at
               FROM model_prediction_runs r
               WHERE r.id=%s AND t.run_id=r.id AND r.run_status IN ('completed','partial')
                 AND r.finished_at<t.kickoff_at AND EXISTS (
                   SELECT 1 FROM model_prediction_groups g
                   WHERE g.run_id=r.id AND g.match_id=t.match_id AND g.play_type=t.play_type
                     AND g.group_status='complete' AND g.completed_at<t.kickoff_at
                 )""",
            (str(run_id),),
        )


def fence_scheduled_match(conn: Any, task: PredictionTask) -> None:
    """Fence publication against a concurrent change of match or kickoff."""
    with conn.cursor() as cur:
        # Notice ingestion takes the same transaction lock before publishing a change.
        # This makes the final schedule check linearizable with bulletin persistence.
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", PREMATCH_NOTICE_LOCK)
        cur.execute(
            """SELECT m.business_date FROM official_matches m
               WHERE id=%s AND kickoff_time=%s AND kickoff_time>timezone('Asia/Shanghai', clock_timestamp())
                 AND source_match_id=%s AND home_team_name=%s AND away_team_name=%s
                 AND LOWER(COALESCE(match_status,''))=ANY(%s)
                 AND NOT COALESCE((
                    SELECT n.evidence->>'state'='withdrawn' OR
                           (n.evidence->>'state'='changed' AND n.evidence->>'kickoff' IS DISTINCT FROM
                            to_char(m.kickoff_time,'YYYY-MM-DD"T"HH24:MI:SS'))
                    FROM sporttery_schedule_notices n
                    WHERE n.evidence->>'kind'='jc_fixture_change'
                      AND n.evidence->>'match_code'=m.official_match_code
                      AND n.evidence->>'home'=m.home_team_name AND n.evidence->>'away'=m.away_team_name
                      AND n.published_at<=clock_timestamp()
                      AND n.published_at>=((m.business_date-3)::timestamp AT TIME ZONE 'Asia/Shanghai')
                      AND n.published_at<((m.business_date+4)::timestamp AT TIME ZONE 'Asia/Shanghai')
                    ORDER BY n.published_at DESC,n.observed_at DESC LIMIT 1
                 ), false)
               FOR SHARE NOWAIT""",
            (
                task.match_id,
                task.kickoff_at.replace(tzinfo=None),
                task.basis["source_match_id"],
                task.basis["home"],
                task.basis["away"],
                list(ACTIVE_STATES),
            ),
        )
        match = cur.fetchone()
        if match is None:
            raise InputUpdateSuperseded("schedule changed or kickoff reached")
        source = str(task.basis.get("source") or "")
        if source == "sporttery_jc_sales_hours" or source.startswith(
            "https://www.sporttery.cn/ssgg/"
        ):
            cur.execute(
                """SELECT evidence->>'cutoff' FROM sporttery_schedule_notices
                   WHERE evidence->>'kind'='jc_sales_window'
                     AND evidence->>'business_date'=%s
                     AND published_at<=clock_timestamp()
                     AND published_at>=clock_timestamp()-INTERVAL '14 days'
                   ORDER BY published_at DESC,observed_at DESC LIMIT 1""",
                (match[0].isoformat(),),
            )
            latest_cutoff = cur.fetchone()
            if latest_cutoff and latest_cutoff[0] != task.basis.get("cutoff"):
                raise InputUpdateSuperseded("sales window changed")


def current_official_quote(conn: Any, match_id: int, play: str, as_of: str) -> list[tuple]:
    """Return one complete, fresh, same-handicap calculator capture."""
    with conn.cursor() as cur:
        cur.execute(
            """WITH options AS (
                 SELECT DISTINCT ON (snapshot_time, handicap, raw_hash, option_code)
                        id, option_code, sp_value, snapshot_time, handicap, raw_hash
                 FROM official_odds_snapshots o
                 WHERE match_id=%s AND play_type=%s
                   AND (play_type NOT IN ('spf','rqspf') OR option_code IN ('h','d','a'))
                   AND sp_value>1 AND sp_value<'Infinity'::numeric
                   AND snapshot_time<=%s::timestamp
                   AND snapshot_time>=%s::timestamp-INTERVAL '45 minutes'
                   AND created_at<=timezone('UTC', %s::timestamp AT TIME ZONE 'Asia/Shanghai')
                   AND raw_hash IS NOT NULL
                   AND raw_json->>'_collector_timezone'='Asia/Shanghai'
                   AND EXISTS (SELECT 1 FROM official_matches m WHERE m.id=o.match_id
                      AND COALESCE(o.raw_json->>'_sporttery_match_id',m.source_match_id)=m.source_match_id
                      AND COALESCE(o.raw_json->>'_scheduled_kickoff',to_char(m.kickoff_time,'YYYY-MM-DD"T"HH24:MI:SS'))
                          =to_char(m.kickoff_time,'YYYY-MM-DD"T"HH24:MI:SS'))
                   AND (is_open OR raw_json->>'_capture_purpose'='prediction_quote')
                   AND ((play_type<>'rqspf' AND handicap IS NULL) OR
                        (play_type='rqspf' AND handicap IS NOT NULL AND handicap=trunc(handicap)))
                 ORDER BY snapshot_time, handicap, raw_hash, option_code, id DESC
               ), latest AS (
                 SELECT snapshot_time, handicap, raw_hash FROM options
                 GROUP BY snapshot_time, handicap, raw_hash HAVING count(*)=%s
                 ORDER BY snapshot_time DESC, max(id) DESC LIMIT 1
               )
               SELECT o.id, o.option_code, o.sp_value, o.snapshot_time, o.handicap
               FROM options o JOIN latest l ON l.snapshot_time=o.snapshot_time
                 AND l.handicap IS NOT DISTINCT FROM o.handicap AND l.raw_hash=o.raw_hash""",
            (
                match_id,
                play,
                as_of,
                as_of,
                as_of,
                {"spf": 3, "rqspf": 3, "bf": 31, "zjq": 8, "bqc": 9}[play],
            ),
        )
        return cur.fetchall()


def reserve_prediction_quotes(conn: Any, now: datetime) -> list[tuple]:
    """Reserve upcoming missing quotes for the existing odds dispatch owner."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT t.task_key, m.id, m.business_date, m.official_match_code,
                      m.source_match_id, m.kickoff_time, m.home_team_name, m.away_team_name,
                      t.play_type
               FROM prematch_prediction_tasks t JOIN official_matches m ON m.id=t.match_id
               WHERE t.completed_at IS NULL AND t.attempts<5 AND t.target_at<=%s
                 AND t.kickoff_at>%s AND t.kickoff_at=m.kickoff_time AT TIME ZONE 'Asia/Shanghai'
                 AND t.schedule_basis->>'source_match_id'=m.source_match_id
                 AND t.schedule_basis->>'home'=m.home_team_name
                 AND t.schedule_basis->>'away'=m.away_team_name
                 AND LOWER(COALESCE(m.match_status,''))=ANY(%s)
                 AND (t.quote_checked_at IS NULL OR t.quote_checked_at<=%s)
               ORDER BY t.target_at, t.kickoff_at, t.task_key LIMIT %s
               FOR UPDATE OF t SKIP LOCKED""",
            (now + QUOTE_LEAD, now, list(ACTIVE_STATES), now - RETRY_INTERVAL, BATCH_SIZE * 2),
        )
        rows = cur.fetchall()
        if rows:
            cur.execute(
                "UPDATE prematch_prediction_tasks SET quote_checked_at=%s WHERE task_key=ANY(%s)",
                (now, [row[0] for row in rows]),
            )
    as_of = beijing_time(now).replace(tzinfo=None).isoformat()
    wanted = [row[1:] for row in rows if not current_official_quote(conn, row[1], row[-1], as_of)]
    conn.commit()
    return wanted
