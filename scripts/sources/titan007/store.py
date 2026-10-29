"""SQLite storage for titan007 data."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from .parsers import status_text

MATCH_COLUMNS = [
    "match_id",
    "source",
    "match_date",
    "kickoff",
    "league_id",
    "sub_league_id",
    "league_name",
    "league_color",
    "country_id",
    "home_id",
    "home_name",
    "away_id",
    "away_name",
    "status_code",
    "status_text",
    "home_score",
    "away_score",
    "home_half",
    "away_half",
    "home_red",
    "away_red",
    "home_yellow",
    "away_yellow",
    "home_rank",
    "away_rank",
    "ah_line",
    "ou_line",
    "ah_text",
    "ou_text",
    "home_corners",
    "away_corners",
    "has_odds",
    "has_animation",
    "is_hot",
    "lottery_jc",
    "lottery_bf",
    "lottery_dc",
    "venue",
    "weather",
    "temperature",
    "round_name",
    "raw",
    "updated_at",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id     INTEGER PRIMARY KEY,
    source       TEXT,
    match_date   TEXT,
    kickoff      TEXT,
    league_id    INTEGER,
    sub_league_id INTEGER,
    league_name  TEXT,
    league_color TEXT,
    country_id   INTEGER,
    home_id      INTEGER,
    home_name    TEXT,
    away_id      INTEGER,
    away_name    TEXT,
    status_code  INTEGER,
    status_text  TEXT,
    home_score   INTEGER,
    away_score   INTEGER,
    home_half    INTEGER,
    away_half    INTEGER,
    home_red     INTEGER,
    away_red     INTEGER,
    home_yellow  INTEGER,
    away_yellow  INTEGER,
    home_rank    INTEGER,
    away_rank    INTEGER,
    ah_line      REAL,
    ou_line      REAL,
    ah_text      TEXT,
    ou_text      TEXT,
    home_corners INTEGER,
    away_corners INTEGER,
    has_odds     INTEGER,
    has_animation INTEGER,
    is_hot       INTEGER,
    lottery_jc   TEXT,
    lottery_bf   TEXT,
    lottery_dc   TEXT,
    venue        TEXT,
    weather      TEXT,
    temperature  TEXT,
    round_name   TEXT,
    raw          TEXT,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_id, match_date);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_id, match_date);

CREATE TABLE IF NOT EXISTS leagues (
    league_id       INTEGER PRIMARY KEY,
    name_simplified TEXT,
    name_traditional TEXT,
    kind            INTEGER,
    info_url        TEXT,
    has_hd_live     INTEGER
);

CREATE TABLE IF NOT EXISTS league_teams (
    league_id        INTEGER NOT NULL,
    team_id          INTEGER NOT NULL,
    name             TEXT,
    name_traditional TEXT,
    name_en          TEXT,
    logo             TEXT,
    PRIMARY KEY (league_id, team_id)
);

CREATE TABLE IF NOT EXISTS league_categories (
    league_id  INTEGER PRIMARY KEY,
    region     TEXT,
    country    TEXT,
    type       TEXT,
    audience   TEXT,
    tier       INTEGER,
    priority   TEXT,
    tags_json  TEXT,
    source     TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS lottery_matches (
    lottery_match_id INTEGER PRIMARY KEY,
    match_date       TEXT,
    match_num        TEXT,
    league_id        INTEGER,
    league_name      TEXT,
    home_team_id     INTEGER,
    home_team        TEXT,
    home_full_name   TEXT,
    away_team_id     INTEGER,
    away_team        TEXT,
    away_full_name   TEXT,
    home_score       INTEGER,
    away_score       INTEGER,
    half_score       TEXT,
    odds_h           REAL,
    odds_d           REAL,
    odds_a           REAL,
    goal_line        REAL,
    win_flag         TEXT,
    status           TEXT,
    pool_status      TEXT,
    titan_match_id   INTEGER,
    link_type        TEXT,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_lottery_date ON lottery_matches(match_date);
CREATE INDEX IF NOT EXISTS idx_lottery_num ON lottery_matches(match_num);
CREATE INDEX IF NOT EXISTS idx_lottery_titan ON lottery_matches(titan_match_id);

CREATE TABLE IF NOT EXISTS lottery_teams (
    lottery_team_id INTEGER PRIMARY KEY,
    name             TEXT,
    full_name        TEXT,
    league_name      TEXT,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS team_mapping (
    lottery_team_id INTEGER PRIMARY KEY,
    titan_team_id   INTEGER,
    lottery_name    TEXT,
    titan_name      TEXT,
    confidence      REAL,
    method          TEXT,
    status          TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_name  TEXT UNIQUE,
    titan_team_id INTEGER,
    note          TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS team_league_seasons (
    team_id   INTEGER NOT NULL,
    league_id INTEGER NOT NULL,
    season    TEXT NOT NULL,
    team_name TEXT,
    rank      INTEGER,
    points    INTEGER,
    PRIMARY KEY (team_id, league_id, season)
);
CREATE INDEX IF NOT EXISTS idx_tls_season ON team_league_seasons(season, league_id);

CREATE TABLE IF NOT EXISTS team_movements (
    team_id         INTEGER NOT NULL,
    season_from     TEXT NOT NULL,
    season_to       TEXT NOT NULL,
    from_league_id  INTEGER,
    to_league_id    INTEGER,
    direction       TEXT,
    team_name       TEXT,
    PRIMARY KEY (team_id, season_from, season_to)
);

CREATE TABLE IF NOT EXISTS league_relations (
    from_league_id  INTEGER NOT NULL,
    to_league_id    INTEGER NOT NULL,
    direction       TEXT NOT NULL,
    season_from     TEXT,
    season_to       TEXT,
    team_count      INTEGER,
    sample_teams_json TEXT,
    source          TEXT,
    confidence      REAL,
    PRIMARY KEY (from_league_id, to_league_id, direction, season_from, season_to)
);

CREATE TABLE IF NOT EXISTS team_catalog (
    titan_team_id   INTEGER PRIMARY KEY,
    lottery_team_id INTEGER,
    display_name    TEXT,
    titan_name      TEXT,
    logo_path       TEXT,
    jc_matches      INTEGER,
    lineup_players  INTEGER,
    squad_players   INTEGER,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS match_injuries (
    match_id   INTEGER NOT NULL,
    team_id    INTEGER,
    team_name  TEXT,
    number     TEXT,
    position   TEXT,
    player_name TEXT,
    reason     TEXT,
    kind       TEXT,
    PRIMARY KEY (match_id, team_id, player_name)
);

CREATE TABLE IF NOT EXISTS player_appearances (
    match_id   INTEGER NOT NULL,
    team_id    INTEGER,
    side       TEXT,
    player_id  INTEGER NOT NULL,
    player_name TEXT,
    starter    INTEGER,
    minutes    INTEGER,
    position   TEXT,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS match_context (
    match_id        INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    side            TEXT,
    rest_days       INTEGER,
    consecutive_away INTEGER,
    is_neutral      INTEGER,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE IF NOT EXISTS data_provenance (
    entity_type      TEXT NOT NULL,
    entity_id        INTEGER NOT NULL,
    source           TEXT,
    published_at     TEXT,
    first_fetched_at TEXT,
    last_verified_at TEXT,
    revision         INTEGER,
    missing_reason   TEXT,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS player_directory (
    player_id   INTEGER PRIMARY KEY,
    source      TEXT NOT NULL DEFAULT 'lineup',
    squad_id    INTEGER,
    name        TEXT,
    team_id     INTEGER,
    birth       TEXT,
    position    TEXT,
    nationality TEXT,
    appearances INTEGER,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_player_directory_name ON player_directory(name);

CREATE TABLE IF NOT EXISTS data_counts (
    table_name   TEXT PRIMARY KEY,
    row_count    INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_transfers (
    player_id      INTEGER NOT NULL,
    season         TEXT NOT NULL,
    from_team_id   INTEGER,
    to_team_id     INTEGER,
    transfer_date  TEXT,
    end_date       TEXT,
    from_name      TEXT,
    to_name        TEXT,
    from_name_en   TEXT,
    to_name_en     TEXT,
    fee            TEXT,
    flag           INTEGER,
    updated_at     TEXT,
    PRIMARY KEY (player_id, season, from_team_id, to_team_id, transfer_date)
);

CREATE TABLE IF NOT EXISTS team_coaches (
    team_id         INTEGER PRIMARY KEY,
    coach_name      TEXT,
    coach_player_id INTEGER,
    coach_name_en   TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS player_transfer_checked (
    player_id  INTEGER PRIMARY KEY,
    checked_at TEXT
);

CREATE TABLE IF NOT EXISTS cup_ties (
    league_id   INTEGER NOT NULL,
    season      TEXT NOT NULL,
    round       INTEGER,
    team_a      INTEGER NOT NULL,
    team_b      INTEGER NOT NULL,
    legs        INTEGER,
    score_a     INTEGER,
    score_b     INTEGER,
    winner_team_id INTEGER,
    updated_at  TEXT,
    PRIMARY KEY (league_id, season, round, team_a, team_b)
);

CREATE TABLE IF NOT EXISTS competition_formats (
    league_id        INTEGER NOT NULL,
    season           TEXT NOT NULL,
    format           TEXT,
    promotion_slots  INTEGER,
    relegation_slots INTEGER,
    notes            TEXT,
    updated_at       TEXT,
    PRIMARY KEY (league_id, season)
);

CREATE TABLE IF NOT EXISTS predicted_checked (
    match_id  INTEGER PRIMARY KEY,
    checked_at TEXT
);

CREATE TABLE IF NOT EXISTS predicted_lineups (
    match_id    INTEGER NOT NULL,
    side        TEXT NOT NULL,
    player_name TEXT NOT NULL,
    number      TEXT,
    position    TEXT,
    coach_name  TEXT,
    source      TEXT,
    updated_at  TEXT,
    PRIMARY KEY (match_id, side, player_name)
);

CREATE TABLE IF NOT EXISTS match_stats (
    match_id   INTEGER NOT NULL,
    stat_key   TEXT NOT NULL,
    home_value TEXT,
    away_value TEXT,
    PRIMARY KEY (match_id, stat_key)
);

CREATE TABLE IF NOT EXISTS events (
    match_id    INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    minute      TEXT,
    side        TEXT,
    event_type  TEXT,
    player_name TEXT,
    assist_name TEXT,
    raw         TEXT,
    PRIMARY KEY (match_id, seq)
);

CREATE TABLE IF NOT EXISTS lineups (
    match_id    INTEGER NOT NULL,
    side        TEXT NOT NULL,
    player_name TEXT NOT NULL,
    player_id   INTEGER,
    number      TEXT,
    position    TEXT,
    starter     INTEGER,
    birth       TEXT,
    height      TEXT,
    value       TEXT,
    nationality TEXT,
    raw         TEXT,
    PRIMARY KEY (match_id, side, player_name)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task       TEXT,
    target     TEXT,
    status     TEXT,
    message    TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS odds (
    match_id        INTEGER NOT NULL,
    company_id      INTEGER NOT NULL,
    company_name    TEXT,
    odds_type       TEXT NOT NULL,
    source          TEXT NOT NULL,
    initial_home    REAL,
    initial_line    REAL,
    initial_away    REAL,
    live_home       REAL,
    live_line       REAL,
    live_away       REAL,
    initial_return  REAL,
    live_return     REAL,
    initial_kelly_home REAL,
    initial_kelly_draw REAL,
    initial_kelly_away REAL,
    live_kelly_home REAL,
    live_kelly_draw REAL,
    live_kelly_away REAL,
    updated_at      TEXT,
    PRIMARY KEY (match_id, company_id, odds_type, source)
);

CREATE TABLE IF NOT EXISTS odds_companies (
    company_id  INTEGER PRIMARY KEY,
    name        TEXT,
    name_full   TEXT,
    tier        TEXT,          -- tier1 / tier2 / china_lottery
    category    TEXT,          -- sharp / exchange / mainstream / asian / lottery
    brand       TEXT,
    region      TEXT,
    is_exchange INTEGER DEFAULT 0,
    note        TEXT,
    updated_at  TEXT
);

CREATE VIEW IF NOT EXISTS odds_tiered AS
SELECT o.*, c.tier, c.brand
FROM odds o LEFT JOIN odds_companies c ON c.company_id = o.company_id;

CREATE TABLE IF NOT EXISTS odds_history (
    match_id    INTEGER NOT NULL,
    company_id  INTEGER NOT NULL,
    odds_type   TEXT NOT NULL,
    source      TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    minute      TEXT,
    score       TEXT,
    home        REAL,
    line        TEXT,
    away        REAL,
    change_time TEXT,
    status      TEXT,
    PRIMARY KEY (match_id, company_id, odds_type, source, seq)
);

CREATE TABLE IF NOT EXISTS analysis_sections (
    match_id   INTEGER NOT NULL,
    section    TEXT NOT NULL,
    payload    TEXT,
    updated_at TEXT,
    PRIMARY KEY (match_id, section)
);

CREATE TABLE IF NOT EXISTS team_profiles (
    team_id        INTEGER PRIMARY KEY,
    name           TEXT,
    name_traditional TEXT,
    name_en        TEXT,
    logo           TEXT,
    city           TEXT,
    city_traditional TEXT,
    city_en        TEXT,
    stadium        TEXT,
    stadium_traditional TEXT,
    stadium_en     TEXT,
    capacity       INTEGER,
    founded        TEXT,
    website        TEXT,
    description    TEXT,
    address        TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS team_squad (
    team_id      INTEGER NOT NULL,
    player_id    INTEGER NOT NULL,
    number       TEXT,
    name         TEXT,
    name_traditional TEXT,
    name_en      TEXT,
    "group"      TEXT,
    birth        TEXT,
    height       TEXT,
    weight       TEXT,
    position     TEXT,
    nationality  TEXT,
    nationality_traditional TEXT,
    contract_end TEXT,
    appearances  INTEGER,
    goals        INTEGER,
    extra_json   TEXT,
    PRIMARY KEY (team_id, player_id)
);

CREATE TABLE IF NOT EXISTS team_league_stats (
    team_id   INTEGER NOT NULL,
    scope     TEXT NOT NULL,
    played    INTEGER,
    win       INTEGER,
    draw      INTEGER,
    loss      INTEGER,
    goals_for INTEGER,
    goals_against INTEGER,
    goal_diff INTEGER,
    win_rate  TEXT,
    draw_rate TEXT,
    loss_rate TEXT,
    goals_for_avg REAL,
    goals_against_avg REAL,
    points    INTEGER,
    PRIMARY KEY (team_id, scope)
);

CREATE TABLE IF NOT EXISTS team_honors (
    team_id        INTEGER NOT NULL,
    competition    TEXT NOT NULL,
    competition_traditional TEXT,
    years          TEXT,
    competition_id INTEGER,
    PRIMARY KEY (team_id, competition)
);

CREATE TABLE IF NOT EXISTS team_cups (
    team_id   INTEGER NOT NULL,
    league_id INTEGER NOT NULL,
    name      TEXT,
    name_traditional TEXT,
    season    TEXT,
    PRIMARY KEY (team_id, league_id)
);

CREATE TABLE IF NOT EXISTS league_info (
    league_id  INTEGER NOT NULL,
    season     TEXT NOT NULL,
    name       TEXT,
    name_traditional TEXT,
    name_en    TEXT,
    color      TEXT,
    logo       TEXT,
    short_name TEXT,
    short_name_traditional TEXT,
    rules      TEXT,
    sub_leagues_json TEXT,
    score_colors_json TEXT,
    last_update TEXT,
    PRIMARY KEY (league_id, season)
);

CREATE TABLE IF NOT EXISTS league_results (
    match_id   INTEGER PRIMARY KEY,
    league_id  INTEGER,
    season     TEXT,
    round      INTEGER,
    status     INTEGER,
    match_time TEXT,
    home_id    INTEGER,
    away_id    INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    home_half  INTEGER,
    away_half  INTEGER,
    home_rank  INTEGER,
    away_rank  INTEGER,
    ah_full    REAL,
    ah_half    REAL,
    ou_full    TEXT,
    ou_half    TEXT,
    home_red   INTEGER,
    away_red   INTEGER,
    note       TEXT,
    flags_json TEXT
);

CREATE TABLE IF NOT EXISTS league_standings (
    league_id INTEGER NOT NULL,
    season    TEXT NOT NULL,
    scope     TEXT NOT NULL,
    period    TEXT,
    team_id   INTEGER NOT NULL,
    rank      INTEGER,
    played    INTEGER,
    win       INTEGER,
    draw      INTEGER,
    loss      INTEGER,
    goals_for INTEGER,
    goals_against INTEGER,
    goal_diff INTEGER,
    win_rate  TEXT,
    draw_rate TEXT,
    loss_rate TEXT,
    goals_for_avg REAL,
    goals_against_avg REAL,
    points    INTEGER,
    PRIMARY KEY (league_id, season, scope, team_id)
);

CREATE TABLE IF NOT EXISTS scorers (
    league_id   INTEGER NOT NULL,
    season      TEXT NOT NULL,
    scope       TEXT NOT NULL,
    player_id   INTEGER NOT NULL,
    rank        INTEGER,
    name        TEXT,
    name_traditional TEXT,
    name_en     TEXT,
    nationality TEXT,
    nationality_traditional TEXT,
    nationality_en TEXT,
    team_id     INTEGER,
    goals       INTEGER,
    home_goals  INTEGER,
    away_goals  INTEGER,
    penalties   INTEGER,
    extra_json  TEXT,
    PRIMARY KEY (league_id, season, scope, player_id)
);

CREATE TABLE IF NOT EXISTS team_matches (
    team_id    INTEGER NOT NULL,
    match_id   INTEGER NOT NULL,
    raw_json   TEXT,
    PRIMARY KEY (team_id, match_id)
);

CREATE TABLE IF NOT EXISTS odds_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id     INTEGER,
    company_id   INTEGER,
    company_name TEXT,
    odds_type    TEXT,
    source       TEXT,
    field        TEXT,
    old_value    TEXT,
    new_value    TEXT,
    change_time  TEXT,
    detected_at  TEXT,
    match_date   TEXT,
    league_name  TEXT,
    home_name    TEXT,
    away_name    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_unique
    ON odds_alerts(match_id, company_id, odds_type, source, field, new_value, change_time);
CREATE INDEX IF NOT EXISTS idx_alert_time ON odds_alerts(detected_at);

CREATE TABLE IF NOT EXISTS assets (
    asset_type TEXT NOT NULL,
    entity_id  INTEGER NOT NULL,
    name       TEXT,
    url        TEXT,
    path       TEXT,
    bytes      INTEGER,
    status     TEXT,
    fetched_at TEXT,
    PRIMARY KEY (asset_type, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(asset_type, status);

CREATE TABLE IF NOT EXISTS player_stats (
    match_id INTEGER NOT NULL,
    side     TEXT NOT NULL,
    seq      INTEGER NOT NULL,
    number   TEXT,
    player   TEXT,
    player_id INTEGER,
    position TEXT,
    rating   REAL,
    data_json TEXT,
    PRIMARY KEY (match_id, side, seq)
);
CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_stats(player);
CREATE INDEX IF NOT EXISTS idx_player_stats_pid ON player_stats(player_id);

CREATE TABLE IF NOT EXISTS jc_odds (
    match_id   INTEGER NOT NULL,
    market     TEXT NOT NULL,
    phase      TEXT NOT NULL,
    home       REAL,
    draw       REAL,
    away       REAL,
    line       REAL,
    payload_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (match_id, market, phase)
);

CREATE TABLE IF NOT EXISTS text_live (
    match_id   INTEGER PRIMARY KEY,
    title      TEXT,
    content    TEXT,
    fetched_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_id, match_date);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_id, match_date);
CREATE INDEX IF NOT EXISTS idx_events_match ON events(match_id);
CREATE INDEX IF NOT EXISTS idx_stats_match ON match_stats(match_id);
CREATE INDEX IF NOT EXISTS idx_lineups_player ON lineups(player_id);
CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id);
CREATE INDEX IF NOT EXISTS idx_league_results_ls ON league_results(league_id, season);
"""


_CONNECTIONS: ContextVar[list | None] = ContextVar("titan007_connections", default=None)


@contextmanager
def connection_scope():
    connections = []
    token = _CONNECTIONS.set(connections)
    try:
        yield
    finally:
        for conn in connections:
            conn.close()
        _CONNECTIONS.reset(token)


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    connections = _CONNECTIONS.get()
    if connections is not None:
        connections.append(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB page cache
    conn.execute("PRAGMA mmap_size=268435456")  # 256 MB mmap
    conn.execute("PRAGMA temp_store=MEMORY")
    # 先迁移旧表结构，再执行 SCHEMA：SCHEMA 中的索引可能引用新增列。
    _migrate(conn)
    conn.executescript(SCHEMA)
    _migrate(conn)  # New caches also need the metadata columns absent from base DDL.
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """为旧数据库补充新增列。"""
    wanted = {
        "matches": {
            "round_name": "TEXT",
            "season": "TEXT",
            "home_score_rt": "INTEGER",
            "away_score_rt": "INTEGER",
            "home_score_et": "INTEGER",
            "away_score_et": "INTEGER",
            "home_pen": "INTEGER",
            "away_pen": "INTEGER",
            "result_confirmed_at": "TEXT",
            "is_neutral": "INTEGER",
            "first_fetched_at": "TEXT",
            "source_published_at": "TEXT",
            "last_verified_at": "TEXT",
            "revision": "INTEGER",
            "missing_reason": "TEXT",
            "timezone": "TEXT",
            "source_record_id": "TEXT",
        },
        "team_squad": {"roster_effective_at": "TEXT"},
        "match_injuries": {
            "occurred_at": "TEXT",
            "expected_return": "TEXT",
            "missing_reason": "TEXT",
        },
        "predicted_lineups": {"announced_at": "TEXT"},
        "player_transfer_checked": {"status": "TEXT", "missing_reason": "TEXT"},
        "lineups": {
            "player_id": "INTEGER",
            "birth": "TEXT",
            "height": "TEXT",
            "value": "TEXT",
            "nationality": "TEXT",
            "raw": "TEXT",
        },
        "player_stats": {"player_id": "INTEGER"},
        "player_directory": {"appearances": "INTEGER"},
    }
    for table, columns in wanted.items():
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            # 新数据库：表由 SCHEMA 创建，已包含新列。
            continue
        existing = {r["name"] for r in rows}
        for col, typ in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(player_directory)")}
    if cols and "source" not in cols:
        # 旧结构的球员目录混用了两套球员ID，直接丢掉由 derive 重建。
        conn.execute("DROP TABLE player_directory")
    conn.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_matches(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    rows = [r for r in rows if r.get("match_id")]
    if not rows:
        return 0
    for r in rows:
        r.setdefault("updated_at", _now())
    cols = [c for c in MATCH_COLUMNS]
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=COALESCE(excluded.{c}, matches.{c})" for c in cols if c != "match_id")
    sql = (
        f"INSERT INTO matches ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(match_id) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    conn.commit()
    return len(rows)


def update_from_change(conn: sqlite3.Connection, changes: Iterable[dict[str, Any]]) -> int:
    """增量只更新已存在的比赛，避免产生缺少队名的“幽灵行”。"""
    fields = [
        "status_code",
        "home_score",
        "away_score",
        "home_half",
        "away_half",
        "home_red",
        "away_red",
        "home_yellow",
        "away_yellow",
        "home_corners",
        "away_corners",
        "updated_at",
    ]
    updated = 0
    for c in changes:
        row = {k: c.get(k) for k in fields}
        row["updated_at"] = row.get("updated_at") or _now()
        sets = ", ".join(f"{k}=COALESCE(?,{k})" for k in fields)
        cur = conn.execute(
            f"UPDATE matches SET {sets} WHERE match_id=?",
            [row[k] for k in fields] + [c["match_id"]],
        )
        updated += cur.rowcount
    conn.commit()
    return updated


def upsert_leagues(conn: sqlite3.Connection, leagues: Iterable[dict[str, Any]]) -> int:
    leagues = [league for league in leagues if league.get("league_id")]
    if not leagues:
        return 0
    conn.executemany(
        """INSERT INTO leagues (league_id,name_simplified,name_traditional,kind,info_url,has_hd_live)
           VALUES (:league_id,:name_simplified,:name_traditional,:kind,:info_url,:has_hd_live)
           ON CONFLICT(league_id) DO UPDATE SET
             name_simplified=COALESCE(excluded.name_simplified,leagues.name_simplified),
             name_traditional=COALESCE(excluded.name_traditional,leagues.name_traditional),
             kind=COALESCE(excluded.kind,leagues.kind),
             info_url=COALESCE(excluded.info_url,leagues.info_url),
             has_hd_live=COALESCE(excluded.has_hd_live,leagues.has_hd_live)""",
        leagues,
    )
    conn.commit()
    return len(leagues)


def save_detail(conn: sqlite3.Connection, match_id: int, detail: dict[str, Any]) -> None:
    stats = detail.get("stats") or {}
    if stats:
        conn.execute("DELETE FROM match_stats WHERE match_id=?", (match_id,))
        conn.executemany(
            "INSERT INTO match_stats (match_id,stat_key,home_value,away_value) VALUES (?,?,?,?)",
            [(match_id, k, v.get("home"), v.get("away")) for k, v in stats.items()],
        )

    events = detail.get("events") or []
    conn.execute("DELETE FROM events WHERE match_id=?", (match_id,))
    conn.executemany(
        "INSERT INTO events (match_id,seq,minute,side,event_type,player_name,assist_name,raw) VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                match_id,
                e.get("seq"),
                e.get("minute"),
                e.get("side"),
                e.get("event_type"),
                e.get("player_name"),
                e.get("assist_name"),
                e.get("raw"),
            )
            for e in events
        ],
    )

    lineups = detail.get("lineups") or []
    if lineups:
        conn.execute("DELETE FROM lineups WHERE match_id=?", (match_id,))
        conn.executemany(
            """INSERT OR IGNORE INTO lineups
               (match_id,side,player_name,player_id,number,position,starter,birth,height,value,nationality,raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    match_id,
                    lineup.get("side"),
                    lineup.get("player_name"),
                    lineup.get("player_id"),
                    lineup.get("number"),
                    lineup.get("position"),
                    lineup.get("starter"),
                    lineup.get("birth"),
                    lineup.get("height"),
                    lineup.get("value"),
                    lineup.get("nationality"),
                    lineup.get("raw"),
                )
                for lineup in lineups
                if lineup.get("player_name")
            ],
        )

    header = detail.get("header") or {}
    kickoff = header.get("kickoff")
    patch = {
        "match_id": match_id,
        "home_id": header.get("home_id"),
        "away_id": header.get("away_id"),
        "home_name": header.get("home_name"),
        "away_name": header.get("away_name"),
        "home_rank": header.get("home_rank"),
        "away_rank": header.get("away_rank"),
        "league_id": header.get("league_id"),
        "league_name": header.get("league_name"),
        "kickoff": kickoff,
        "match_date": kickoff[:10] if kickoff and len(kickoff) >= 10 else None,
        "venue": header.get("venue"),
        "weather": header.get("weather"),
        "temperature": header.get("temperature"),
        "round_name": header.get("round"),
        "home_score": detail.get("home_score"),
        "away_score": detail.get("away_score"),
    }
    if header.get("state") is not None:
        patch["status_code"] = header.get("state")
        patch["status_text"] = status_text(header.get("state"))
    upsert_matches(conn, [patch])
    conn.commit()


def match_ids_for_date(
    conn: sqlite3.Connection, match_date: str, only_missing: bool = False, limit: int | None = None
) -> list[int]:
    sql = "SELECT match_id FROM matches WHERE match_date=?"
    if only_missing:
        sql += " AND match_id NOT IN (SELECT DISTINCT match_id FROM match_stats)"
    sql += " ORDER BY kickoff, match_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r["match_id"] for r in conn.execute(sql, (match_date,))]


def log(conn: sqlite3.Connection, task: str, target: str, status: str, message: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_log (task,target,status,message,created_at) VALUES (?,?,?,?,?)",
        (task, target, status, message, _now()),
    )
    conn.commit()


def save_odds(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    rows = [r for r in rows if r.get("match_id") and r.get("company_id") is not None]
    if not rows:
        return 0
    cols = [
        "match_id",
        "company_id",
        "company_name",
        "odds_type",
        "source",
        "initial_home",
        "initial_line",
        "initial_away",
        "live_home",
        "live_line",
        "live_away",
        "initial_return",
        "live_return",
        "initial_kelly_home",
        "initial_kelly_draw",
        "initial_kelly_away",
        "live_kelly_home",
        "live_kelly_draw",
        "live_kelly_away",
        "updated_at",
    ]
    for r in rows:
        r.setdefault("updated_at", _now())
    updates = ",".join(f"{c}=COALESCE(excluded.{c},odds.{c})" for c in cols[5:])
    sql = (
        f"INSERT INTO odds ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
        f"ON CONFLICT(match_id,company_id,odds_type,source) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    conn.commit()
    return len(rows)


def save_odds_history(
    conn: sqlite3.Connection,
    match_id: int,
    company_id: int,
    odds_type: str,
    source: str,
    rows: Iterable[dict[str, Any]],
) -> int:
    rows = list(rows)
    conn.execute(
        "DELETE FROM odds_history WHERE match_id=? AND company_id=? AND odds_type=? AND source=?",
        (match_id, company_id, odds_type, source),
    )
    conn.executemany(
        """INSERT INTO odds_history
           (match_id,company_id,odds_type,source,seq,minute,score,home,line,away,change_time,status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                match_id,
                company_id,
                odds_type,
                source,
                r.get("seq"),
                r.get("minute"),
                r.get("score"),
                r.get("home"),
                r.get("line"),
                r.get("away"),
                r.get("change_time"),
                r.get("status"),
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def save_analysis(conn: sqlite3.Connection, match_id: int, sections: dict[str, Any]) -> None:
    for section, payload in sections.items():
        conn.execute(
            """INSERT INTO analysis_sections (match_id,section,payload,updated_at) VALUES (?,?,?,?)
               ON CONFLICT(match_id,section) DO UPDATE SET
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (match_id, section, json.dumps(payload, ensure_ascii=False), _now()),
        )
    conn.commit()


def save_team(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    profile = data.get("profile") or {}
    team_id = profile.get("team_id")
    if not team_id:
        return
    profile["updated_at"] = _now()
    conn.execute(
        """INSERT INTO team_profiles
           (team_id,name,name_traditional,name_en,logo,city,city_traditional,city_en,
            stadium,stadium_traditional,stadium_en,capacity,founded,website,description,address,updated_at)
           VALUES (:team_id,:name,:name_traditional,:name_en,:logo,:city,:city_traditional,:city_en,
                   :stadium,:stadium_traditional,:stadium_en,:capacity,:founded,:website,:description,:address,:updated_at)
           ON CONFLICT(team_id) DO UPDATE SET
             name=excluded.name, name_traditional=excluded.name_traditional, name_en=excluded.name_en,
             logo=excluded.logo, city=excluded.city, city_traditional=excluded.city_traditional,
             city_en=excluded.city_en, stadium=excluded.stadium,
             stadium_traditional=excluded.stadium_traditional, stadium_en=excluded.stadium_en,
             capacity=excluded.capacity, founded=excluded.founded, website=excluded.website,
             description=excluded.description, address=excluded.address, updated_at=excluded.updated_at""",
        profile,
    )

    conn.execute("DELETE FROM team_squad WHERE team_id=?", (team_id,))
    conn.executemany(
        """INSERT OR REPLACE INTO team_squad
           (team_id,player_id,number,name,name_traditional,name_en,"group",birth,height,weight,
            position,nationality,nationality_traditional,contract_end,appearances,goals,extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                p.get("team_id"),
                p.get("player_id"),
                p.get("number"),
                p.get("name"),
                p.get("name_traditional"),
                p.get("name_en"),
                p.get("group"),
                p.get("birth"),
                p.get("height"),
                p.get("weight"),
                p.get("position"),
                p.get("nationality"),
                p.get("nationality_traditional"),
                p.get("contract_end"),
                p.get("appearances"),
                p.get("goals"),
                json.dumps(p.get("extra_json") or [], ensure_ascii=False),
            )
            for p in data.get("squad") or []
            if p.get("player_id")
        ],
    )

    conn.execute("DELETE FROM team_league_stats WHERE team_id=?", (team_id,))
    conn.executemany(
        """INSERT OR REPLACE INTO team_league_stats
           (team_id,scope,played,win,draw,loss,goals_for,goals_against,goal_diff,
            win_rate,draw_rate,loss_rate,goals_for_avg,goals_against_avg,points)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                s.get("team_id"),
                s.get("scope"),
                s.get("played"),
                s.get("win"),
                s.get("draw"),
                s.get("loss"),
                s.get("goals_for"),
                s.get("goals_against"),
                s.get("goal_diff"),
                s.get("win_rate"),
                s.get("draw_rate"),
                s.get("loss_rate"),
                s.get("goals_for_avg"),
                s.get("goals_against_avg"),
                s.get("points"),
            )
            for s in data.get("league_stats") or []
        ],
    )

    conn.execute("DELETE FROM team_honors WHERE team_id=?", (team_id,))
    conn.executemany(
        "INSERT OR REPLACE INTO team_honors (team_id,competition,competition_traditional,years,competition_id) VALUES (?,?,?,?,?)",
        [
            (
                h.get("team_id"),
                h.get("competition"),
                h.get("competition_traditional"),
                h.get("years"),
                h.get("competition_id"),
            )
            for h in data.get("honors") or []
            if h.get("competition")
        ],
    )

    conn.execute("DELETE FROM team_cups WHERE team_id=?", (team_id,))
    conn.executemany(
        "INSERT OR REPLACE INTO team_cups (team_id,league_id,name,name_traditional,season) VALUES (?,?,?,?,?)",
        [
            (
                c.get("team_id"),
                c.get("league_id"),
                c.get("name"),
                c.get("name_traditional"),
                c.get("season"),
            )
            for c in data.get("cups") or []
            if c.get("league_id")
        ],
    )

    conn.execute("DELETE FROM team_matches WHERE team_id=?", (team_id,))
    conn.executemany(
        "INSERT OR REPLACE INTO team_matches (team_id,match_id,raw_json) VALUES (?,?,?)",
        [
            (team_id, m[0], json.dumps(m, ensure_ascii=False))
            for m in data.get("matches") or []
            if isinstance(m, list) and m
        ],
    )
    conn.commit()


def save_league(
    conn: sqlite3.Connection,
    league_id: int,
    season: str,
    data: dict[str, Any],
    results: Iterable[dict[str, Any]],
    standings: Iterable[dict[str, Any]],
    scorers: dict[str, Iterable[dict[str, Any]]],
) -> None:
    info = data.get("league") or []
    if len(info) >= 10:
        conn.execute(
            """INSERT INTO league_info
               (league_id,season,name,name_traditional,name_en,color,logo,short_name,
                short_name_traditional,rules,sub_leagues_json,score_colors_json,last_update)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(league_id,season) DO UPDATE SET
                 name=excluded.name, name_traditional=excluded.name_traditional, name_en=excluded.name_en,
                 color=excluded.color, logo=excluded.logo, short_name=excluded.short_name,
                 short_name_traditional=excluded.short_name_traditional, rules=excluded.rules,
                 sub_leagues_json=excluded.sub_leagues_json, score_colors_json=excluded.score_colors_json,
                 last_update=excluded.last_update""",
            (
                league_id,
                season,
                info[1],
                info[2],
                info[3],
                info[5],
                info[6],
                info[7],
                info[8],
                info[9] if len(info) > 9 else None,
                json.dumps(data.get("sub_leagues") or [], ensure_ascii=False),
                json.dumps(data.get("score_colors") or [], ensure_ascii=False),
                data.get("last_update"),
            ),
        )
        conn.execute(
            """INSERT INTO leagues (league_id,name_simplified,name_traditional,kind,info_url,has_hd_live)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(league_id) DO UPDATE SET
                 name_simplified=excluded.name_simplified,
                 name_traditional=excluded.name_traditional""",
            (league_id, info[1], info[2], 1, None, None),
        )

    team_rows = []
    for row in data.get("teams") or []:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            team_id = int(str(row[0]).strip())
        except TypeError, ValueError:
            continue
        team_rows.append(
            (
                league_id,
                team_id,
                row[1],
                row[2] if len(row) > 2 else None,
                row[3] if len(row) > 3 else None,
                row[5] if len(row) > 5 else None,
            )
        )
    if team_rows:
        conn.executemany(
            """INSERT INTO league_teams
               (league_id,team_id,name,name_traditional,name_en,logo)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(league_id,team_id) DO UPDATE SET
                 name=excluded.name, name_traditional=excluded.name_traditional,
                 name_en=excluded.name_en, logo=excluded.logo""",
            team_rows,
        )

    conn.executemany(
        """INSERT INTO league_results
           (match_id,league_id,season,round,status,match_time,home_id,away_id,
            home_score,away_score,home_half,away_half,home_rank,away_rank,
            ah_full,ah_half,ou_full,ou_half,home_red,away_red,note,flags_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id) DO UPDATE SET
             league_id=excluded.league_id, season=excluded.season, round=excluded.round,
             status=excluded.status, match_time=excluded.match_time, home_id=excluded.home_id,
             away_id=excluded.away_id, home_score=excluded.home_score, away_score=excluded.away_score,
             home_half=excluded.home_half, away_half=excluded.away_half, home_rank=excluded.home_rank,
             away_rank=excluded.away_rank, ah_full=excluded.ah_full, ah_half=excluded.ah_half,
             ou_full=excluded.ou_full, ou_half=excluded.ou_half, home_red=excluded.home_red,
             away_red=excluded.away_red, note=excluded.note, flags_json=excluded.flags_json""",
        [
            (
                r.get("match_id"),
                r.get("league_id"),
                r.get("season"),
                r.get("round"),
                r.get("status"),
                r.get("match_time"),
                r.get("home_id"),
                r.get("away_id"),
                r.get("home_score"),
                r.get("away_score"),
                r.get("home_half"),
                r.get("away_half"),
                r.get("home_rank"),
                r.get("away_rank"),
                r.get("ah_full"),
                r.get("ah_half"),
                r.get("ou_full"),
                r.get("ou_half"),
                r.get("home_red"),
                r.get("away_red"),
                r.get("note"),
                json.dumps(r.get("flags") or [], ensure_ascii=False),
            )
            for r in results
            if r.get("match_id")
        ],
    )

    conn.execute("DELETE FROM league_standings WHERE league_id=? AND season=?", (league_id, season))
    conn.executemany(
        """INSERT OR REPLACE INTO league_standings
           (league_id,season,scope,period,team_id,rank,played,win,draw,loss,goals_for,
            goals_against,goal_diff,win_rate,draw_rate,loss_rate,goals_for_avg,
            goals_against_avg,points)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                league_id,
                season,
                s.get("scope"),
                s.get("period"),
                s.get("team_id"),
                s.get("rank"),
                s.get("played"),
                s.get("win"),
                s.get("draw"),
                s.get("loss"),
                s.get("goals_for"),
                s.get("goals_against"),
                s.get("goal_diff"),
                s.get("win_rate"),
                s.get("draw_rate"),
                s.get("loss_rate"),
                s.get("goals_for_avg"),
                s.get("goals_against_avg"),
                s.get("points"),
            )
            for s in standings
            if s.get("team_id")
        ],
    )

    conn.execute("DELETE FROM scorers WHERE league_id=? AND season=?", (league_id, season))
    all_scorers = []
    for scope, rows in scorers.items():
        for s in rows:
            all_scorers.append(
                (
                    league_id,
                    season,
                    scope,
                    s.get("player_id"),
                    s.get("rank"),
                    s.get("name"),
                    s.get("name_traditional"),
                    s.get("name_en"),
                    s.get("nationality"),
                    s.get("nationality_traditional"),
                    s.get("nationality_en"),
                    s.get("team_id"),
                    s.get("goals"),
                    s.get("home_goals"),
                    s.get("away_goals"),
                    s.get("penalties"),
                    json.dumps(s.get("extra") or [], ensure_ascii=False),
                )
            )
    conn.executemany(
        """INSERT OR REPLACE INTO scorers
           (league_id,season,scope,player_id,rank,name,name_traditional,name_en,
            nationality,nationality_traditional,nationality_en,team_id,goals,
            home_goals,away_goals,penalties,extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [row for row in all_scorers if row[3] is not None],
    )
    conn.commit()


def get_odds(conn: sqlite3.Connection, match_id: int, company_id: int, odds_type: str, source: str):
    row = conn.execute(
        "SELECT * FROM odds WHERE match_id=? AND company_id=? AND odds_type=? AND source=?",
        (match_id, company_id, odds_type, source),
    ).fetchone()
    return dict(row) if row else None


def get_latest_history(
    conn: sqlite3.Connection, match_id: int, company_id: int, odds_type: str, source: str
):
    row = conn.execute(
        """SELECT * FROM odds_history
           WHERE match_id=? AND company_id=? AND odds_type=? AND source=?
             AND (home IS NOT NULL OR (line IS NOT NULL AND line != '') OR away IS NOT NULL)
           ORDER BY seq ASC LIMIT 1""",
        (match_id, company_id, odds_type, source),
    ).fetchone()
    return dict(row) if row else None


def get_match_info(conn: sqlite3.Connection, match_id: int):
    row = conn.execute(
        "SELECT match_id,match_date,league_name,home_name,away_name,kickoff FROM matches WHERE match_id=?",
        (match_id,),
    ).fetchone()
    return dict(row) if row else {}


def insert_alerts(conn: sqlite3.Connection, alerts: Iterable[dict[str, Any]]) -> int:
    alerts = list(alerts)
    if not alerts:
        return 0
    cols = [
        "match_id",
        "company_id",
        "company_name",
        "odds_type",
        "source",
        "field",
        "old_value",
        "new_value",
        "change_time",
        "detected_at",
        "match_date",
        "league_name",
        "home_name",
        "away_name",
    ]
    before = conn.total_changes
    conn.executemany(
        f"INSERT OR IGNORE INTO odds_alerts ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [[a.get(c) for c in cols] for a in alerts],
    )
    conn.commit()
    return conn.total_changes - before


def recent_alerts(conn: sqlite3.Connection, limit: int = 50, since: str | None = None):
    sql = "SELECT * FROM odds_alerts"
    params: list[Any] = []
    if since:
        sql += " WHERE detected_at >= ?"
        params.append(since)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for table in (
        "matches",
        "leagues",
        "match_stats",
        "events",
        "lineups",
        "odds",
        "odds_history",
        "analysis_sections",
        "team_profiles",
        "team_squad",
        "league_results",
        "league_teams",
        "league_categories",
        "league_standings",
        "scorers",
        "odds_alerts",
        "odds_companies",
        "lottery_matches",
        "lottery_teams",
        "team_mapping",
        "team_aliases",
        "team_league_seasons",
        "team_movements",
        "league_relations",
        "team_catalog",
        "match_injuries",
        "player_appearances",
        "match_context",
        "data_provenance",
        "player_transfers",
        "team_coaches",
        "player_transfer_checked",
        "cup_ties",
        "competition_formats",
        "predicted_lineups",
        "predicted_checked",
        "assets",
        "player_stats",
        "jc_odds",
        "text_live",
    ):
        out[table] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    return out


def upsert_assets(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO assets (asset_type,entity_id,name,url,path,bytes,status,fetched_at)
           VALUES (:asset_type,:entity_id,:name,:url,:path,:bytes,:status,:fetched_at)
           ON CONFLICT(asset_type,entity_id) DO UPDATE SET
             name=COALESCE(excluded.name,assets.name),
             url=COALESCE(excluded.url,assets.url),
             path=COALESCE(excluded.path,assets.path),
             bytes=COALESCE(excluded.bytes,assets.bytes),
             status=excluded.status,
             fetched_at=COALESCE(excluded.fetched_at,assets.fetched_at)""",
        rows,
    )
    conn.commit()
    return len(rows)


def save_player_stats(conn: sqlite3.Connection, match_id: int, data: dict[str, Any]) -> int:
    rows = []
    for side in ("home", "away"):
        for seq, p in enumerate(data.get(side) or [], 1):
            rows.append(
                (
                    match_id,
                    side,
                    seq,
                    p.get("号码"),
                    p.get("球员"),
                    p.get("player_id"),
                    p.get("位置"),
                    _to_float(p.get("评分")),
                    json.dumps(p, ensure_ascii=False),
                )
            )
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO player_stats (match_id,side,seq,number,player,player_id,position,rating,data_json)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id,side,seq) DO UPDATE SET
             number=excluded.number, player=excluded.player, player_id=excluded.player_id,
             position=excluded.position, rating=excluded.rating, data_json=excluded.data_json""",
        rows,
    )
    conn.commit()
    return len(rows)


def save_jc_odds(conn: sqlite3.Connection, match_id: int, rows: Iterable[dict[str, Any]]) -> int:
    payload = [
        (
            match_id,
            r["market"],
            r["phase"],
            r.get("home"),
            r.get("draw"),
            r.get("away"),
            r.get("line"),
            json.dumps(r.get("payload") or {}, ensure_ascii=False),
            _now(),
        )
        for r in rows
    ]
    if not payload:
        return 0
    conn.executemany(
        """INSERT INTO jc_odds (match_id,market,phase,home,draw,away,line,payload_json,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id,market,phase) DO UPDATE SET
             home=excluded.home, draw=excluded.draw, away=excluded.away,
             line=excluded.line, payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
        payload,
    )
    conn.commit()
    return len(payload)


def save_text_live(conn: sqlite3.Connection, match_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO text_live (match_id,title,content,fetched_at) VALUES (?,?,?,?)
           ON CONFLICT(match_id) DO UPDATE SET
             title=excluded.title, content=excluded.content, fetched_at=excluded.fetched_at""",
        (match_id, data.get("title"), data.get("content"), _now()),
    )
    conn.commit()


def _to_float(value):
    try:
        return float(str(value).strip())
    except TypeError, ValueError:
        return None


def assets_by_type(conn: sqlite3.Connection, asset_type: str) -> dict[int, sqlite3.Row]:
    return {
        r["entity_id"]: r
        for r in conn.execute("SELECT * FROM assets WHERE asset_type=?", (asset_type,))
    }


def export_table(conn: sqlite3.Connection, table: str, out_path: str) -> int:
    if not table.isidentifier():
        raise ValueError("invalid table name")
    cur = conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    n = 0
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        for row in cur:
            writer.writerow([row[c] for c in cols])
            n += 1
    return n
