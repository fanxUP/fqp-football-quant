"""Official traditional-lottery analysis and explicit immutable research plans."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from psycopg2.extras import Json
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from apps.backend.src.db import get_db
from scripts.business_time import business_now
from scripts.football_pool_catalog import read_pool_catalog, read_pool_catalog_issue
from scripts.market_metric_validation import spf_probability_vector
from scripts.model_prediction_run_identity import content_sha256
from scripts.model_prediction_run_loader import load_pool_prediction_groups
from scripts.pool_combination_optimizer import (
    PoolMatch,
    analyze_pool,
    pool_analysis_to_dict,
    validate_budget,
)
from scripts.pool_issue_state import pool_time, sale_window

router = APIRouter(tags=["pool"])


def _read_pool_model_consensus(conn: Any, cutoffs: dict, *, historical: bool) -> dict[int, dict]:
    groups = load_pool_prediction_groups(conn, cutoffs=cutoffs, historical=historical)
    by_match: dict[int, list] = defaultdict(list)
    rejected: dict[int, list] = defaultdict(list)
    for g in groups:
        vector = spf_probability_vector(g["probability_vector"])
        if (
            g["status"] != "complete"
            or not g["eligible"]
            or vector is None
            or g["provenance_status"] != "complete"
            or g["run_provenance_status"] != "complete"
        ):
            rejected[g["match_id"]].append(
                {
                    "model_name": g["model_name"],
                    "status": g["status"],
                    "group_id": str(g["group_id"]),
                    "reason": "完整性、独立模型用途或来源证据未通过",
                }
            )
            continue
        by_match[g["match_id"]].append((g, vector))
    result = {}
    for mid in set(by_match) | set(rejected):
        valid = by_match[mid]
        result[mid] = {
            "vector": {o: sum(v[o] for _, v in valid) / len(valid) for o in "310"}
            if valid
            else None,
            "model_count": len(valid),
            "disagreement": max(
                max(v[o] for _, v in valid) - min(v[o] for _, v in valid) for o in "310"
            )
            if len(valid) > 1
            else None,
            "models": [
                {
                    "model_name": g["model_name"],
                    "model_version_id": g["model_version_id"],
                    "group_id": str(g["group_id"]),
                    "run_id": str(g["run_id"]),
                    "predict_time": dt.isoformat()
                    if (dt := pool_time(g["predict_time"]))
                    else None,
                    "output_sha256": g["output_sha256"],
                    "raw_vector": v,
                    "manifest_hashes": g["manifest_hashes"],
                }
                for g, v in valid
            ],
            "rejected": rejected[mid],
        }
    return result


def _issue_headers(conn, issue_id=None):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id,issue_no,game_type,total_matches,raw_json,raw_hash,source_game_type,
                   (SELECT count(*) FROM football_pool_issue_matches im WHERE im.issue_id=football_pool_issues.id)
            FROM football_pool_issues WHERE game_type IN ('t14c','r9')
              AND (%s IS NULL OR id::text=%s OR issue_no=%s
                   OR issue_no=(SELECT issue_no FROM football_pool_issues WHERE id::text=%s))
            ORDER BY updated_at DESC,id DESC LIMIT 100""",
            (issue_id, issue_id, issue_id, issue_id),
        )
        return [
            dict(
                zip(
                    (
                        "id",
                        "issue_no",
                        "game_type",
                        "total_matches",
                        "raw_json",
                        "raw_hash",
                        "source_game_type",
                        "stored_matches",
                    ),
                    r,
                    strict=True,
                ),
                fixtures=[],
            )
            for r in cur.fetchall()
        ]


def _choose_issue(issues, issue_id, now):
    candidates = [i for i in issues if i["game_type"] == "t14c"]
    if not candidates:
        return None
    if issue_id is not None:
        requested = next((i for i in issues if str(i["id"]) == issue_id), None)
        issue_no = requested["issue_no"] if requested else issue_id
        return next((i for i in candidates if i["issue_no"] == issue_no), None)
    return max(
        candidates,
        key=lambda i: (sale_window(i["raw_json"] or {}, now=now)["state"] == "selling", i["id"]),
    )


def _catalogue(conn, issue_id=None, now=None):
    issues = _issue_headers(conn, issue_id)
    selected = _choose_issue(issues, issue_id, now or business_now())
    if selected is None:
        return issues
    # Resolve only the selected period's fixtures, never every historical issue.
    by_id = {i["id"]: i for i in issues if i["issue_no"] == selected["issue_no"]}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT im.issue_id,im.match_order,im.home_team_name,im.away_team_name,
                    im.league_name,im.kickoff_time,resolved.match_id
            FROM football_pool_issue_matches im
            LEFT JOIN LATERAL (
                SELECT CASE WHEN count(*)=1 THEN min(m.id) END AS match_id
                FROM official_matches m
                WHERE m.home_team_name=im.home_team_name AND m.away_team_name=im.away_team_name
                  AND m.kickoff_time=im.kickoff_time
                  AND (im.match_id IS NULL OR m.id=im.match_id)
            ) resolved ON true
            WHERE im.issue_id=ANY(%s::bigint[]) ORDER BY im.issue_id,im.match_order""",
            (list(by_id),),
        )
        for r in cur.fetchall():
            by_id[r[0]]["fixtures"].append(
                {
                    "match_order": r[1],
                    "match_id": r[6],
                    "home_team": r[2] or "",
                    "away_team": r[3] or "",
                    "league": r[4] or "",
                    "match_date": pool_time(r[5]).isoformat() if pool_time(r[5]) else "",
                }
            )
    return issues


def _fixture_signature(issue):
    return [
        (m["match_order"], m["home_team"], m["away_team"], m["match_date"])
        for m in issue["fixtures"]
    ]


def _complete_catalogue(issue):
    fixtures = issue["fixtures"]
    ids = [m["match_id"] for m in fixtures]
    return (
        issue["total_matches"] == 14
        and [m["match_order"] for m in fixtures] == list(range(1, 15))
        and None not in ids
        and len(set(ids)) == 14
        and all(m["match_date"] for m in fixtures)
    )


def _game_analysis(conn, issue, *, now, budget, strategy, pins, excludes):
    window = sale_window(issue["raw_json"] or {}, now=now)
    stop = pool_time(window["sale_stop"])
    # Unknown/conflicting deadlines permit bounded research, never a current plan.
    boundary = min(now, stop) if stop else now
    cutoffs = {
        m["match_id"]: min(boundary, pool_time(m["match_date"]))
        for m in issue["fixtures"]
        if m["match_id"] is not None and pool_time(m["match_date"])
    }
    historical = window["state"] != "selling"
    consensus = _read_pool_model_consensus(conn, cutoffs, historical=historical)
    matches = []
    for fixture in issue["fixtures"]:
        evidence = consensus.get(fixture["match_id"], {})
        vector = evidence.get("vector") or {}
        matches.append(
            PoolMatch(
                **fixture,
                prob_home=vector.get("3"),
                prob_draw=vector.get("1"),
                prob_away=vector.get("0"),
                evidence=evidence,
                missing_reason="比赛身份未唯一核实" if fixture["match_id"] is None else None,
            )
        )
    try:
        result = pool_analysis_to_dict(
            analyze_pool(
                matches,
                budget=budget,
                strategy=strategy,
                period_id=f"{issue['issue_no']}-{issue['game_type']}",
                pinned_orders=pins,
                excluded_orders=excludes,
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    catalogue_ok = (
        _complete_catalogue(issue) and issue.get("source_game_type") == issue["game_type"]
    )
    if issue.get("source_game_type") != issue["game_type"]:
        result["warnings"].append(
            "旧记录的玩法来源尚未重新核实，需官方采集按玩法更新后再生成方案。"
        )
    if not catalogue_ok:
        result["sf14_status"] = result["rx9_status"] = "identity_pending"
    elif window["state"] in {"unknown", "conflict", "suspended", "not_started"}:
        result["sf14_status"] = result["rx9_status"] = (
            "cutoff_pending" if window["state"] == "unknown" else window["state"]
        )
    result["issue_state"] = window["state"]
    result["issue"] = {k: issue[k] for k in ["id", "issue_no", "game_type"]}
    result["issue"].update(
        status=window["state"],
        sale_stop=window["sale_stop"],
        sale_start=window["sale_start"],
        sale_stop_source=window["sale_stop_source"],
        source="sporttery",
        raw_hash=issue["raw_hash"],
    )
    result["data_as_of"] = boundary.isoformat()
    result["analysis_mode"] = (
        "current"
        if window["state"] == "selling"
        else ("historical" if window["state"] == "closed" else "research")
    )
    result["warnings"].append(
        "未提供的天气、伤停、阵容和市场证据均为未知，不由彩池额外阻断合法模型。"
    )
    if historical:
        result["warnings"].append(
            "历史重建参考：按当时可用预测组恢复，不等同当时保存的原始方案；模型集合按留存组重建。"
        )
    if not catalogue_ok or window["state"] not in {"selling", "closed"}:
        # The table still exposes research vectors, but no actionable portfolio.
        result["full_combinations"] = {"count": 0, "total_cost": 0, "combinations": []}
        result["rx9"].update(combinations_count=0, total_cost=0, combinations=[])
        result["probabilities"] = dict.fromkeys(result["probabilities"])
    return result


def _analysis(conn, *, budget, strategy, issue_id, pins, excludes):
    now = business_now()
    issues = _catalogue(conn, issue_id, now)
    full_issues = [i for i in issues if i["game_type"] == "t14c"]
    if not full_issues:
        return {
            "schema_version": "football-pool/v2",
            "issue": None,
            "issue_state": "missing_issue",
            "sf14_status": "missing_issue",
            "rx9_status": "missing_issue",
            "matches": [],
            "missing_inputs": [{"reason": "暂无已采集的体彩官方14场彩池"}],
            "warnings": [],
        }
    selected = _choose_issue(issues, issue_id, now)
    if selected is None:
        raise HTTPException(404, "未找到指定14场期次")
    result = _game_analysis(
        conn, selected, now=now, budget=budget, strategy=strategy, pins=[], excludes=[]
    )
    rx_issue = next(
        (i for i in issues if i["game_type"] == "r9" and i["issue_no"] == selected["issue_no"]),
        None,
    )
    if rx_issue and _fixture_signature(rx_issue) == _fixture_signature(selected):
        nine = _game_analysis(
            conn, rx_issue, now=now, budget=budget, strategy=strategy, pins=pins, excludes=excludes
        )
        result["rx9"], result["rx9_status"] = nine["rx9"], nine["rx9_status"]
        result["rx9"]["issue"] = nine["issue"]
        result["rx9"]["data_as_of"] = nine["data_as_of"]
        result["rx9"]["missing_inputs"] = nine["missing_inputs"]
        result["rx9"]["candidate_matches"] = nine["matches"]
        result["probabilities"]["rx9_prob"] = nine["probabilities"]["rx9_prob"]
        result["warnings"] = list(dict.fromkeys(result["warnings"] + nine["warnings"]))
    else:
        result["rx9_status"] = "issue_pending" if rx_issue is None else "identity_pending"
        result["rx9"].update(
            selected_matches=[],
            combinations_count=0,
            total_cost=0,
            combinations=[],
            missing_inputs=[],
        )
        result["probabilities"]["rx9_prob"] = None
        result["warnings"].append(
            "任九须有独立官方期次及一致的14场对阵证据，不能复制14场截止时间。"
        )
    result["parameters"].update(
        issue_id=str(selected["id"]), pinned_orders=pins, excluded_orders=excludes
    )
    # Stable evidence identity excludes wall-clock display fields; unchanged
    # groups, issue evidence, parameters and engine yield the same hash.
    identity = {
        k: result[k]
        for k in [
            "schema_version",
            "calculation_version",
            "parameters",
            "issue",
            "matches",
            "rx9",
            "sf14_status",
            "rx9_status",
        ]
    }
    identity["rx9"] = {k: v for k, v in result["rx9"].items() if k != "data_as_of"}
    result["input_hash"] = content_sha256(identity)
    return result


def _start_snapshot(conn, *, read_only=True):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ "
            + ("READ ONLY" if read_only else "READ WRITE")
        )
        cur.execute("SET LOCAL jit = off")


def _orders(value: str | None) -> list[int]:
    try:
        orders = [] if not value else [int(x) for x in value.split(",")]
        if len(set(orders)) != len(orders) or any(not 1 <= n <= 14 for n in orders):
            raise ValueError()
        return sorted(orders)
    except ValueError as exc:
        raise HTTPException(400, "场序须为1至14且不重复，以逗号分隔") from exc


@router.get("/api/pool/analyze")
def run_pool_analysis(
    budget: int = Query(256, ge=2, le=10000),
    strategy: str = "balanced",
    issue_id: str | None = None,
    pinned_orders: str | None = None,
    excluded_orders: str | None = None,
):
    try:
        validate_budget(budget)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if strategy not in {"conservative", "balanced", "aggressive"}:
        raise HTTPException(400, "未知组合策略")
    pins, excludes = _orders(pinned_orders), _orders(excluded_orders)
    if len(pins) > 9 or set(pins) & set(excludes):
        raise HTTPException(400, "固定场次最多9场，不能同时排除")
    with get_db() as conn:
        _start_snapshot(conn)
        return _analysis(
            conn, budget=budget, strategy=strategy, issue_id=issue_id, pins=pins, excludes=excludes
        )


@router.get("/api/pool/issues")
def list_pool_issues():
    with get_db() as conn:
        _start_snapshot(conn)
        issues = _issue_headers(conn)
    result = [
        {
            **{k: i[k] for k in ["id", "issue_no", "game_type", "total_matches", "stored_matches"]},
            **sale_window(i["raw_json"] or {}),
        }
        for i in issues
    ]
    return {"issues": result, "total": len(result)}


@router.get("/api/pool/catalog")
def pool_catalog(
    game_type: Literal["t14c", "r9", "bqc6", "jq4"] | None = None,
    issue_no: str | None = Query(None, min_length=1, max_length=64),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=100000),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "起始日期不能晚于结束日期")
    if date_to == date.max:
        raise HTTPException(400, "结束日期超出支持范围")
    with get_db() as conn:
        _start_snapshot(conn)
        return read_pool_catalog(
            conn,
            game_type=game_type,
            issue_no=issue_no,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )


@router.get("/api/pool/catalog/{issue_id}")
def pool_catalog_issue(issue_id: int = Path(gt=0, le=9007199254740991)):
    with get_db() as conn:
        _start_snapshot(conn)
        result = read_pool_catalog_issue(conn, issue_id)
    if result is None:
        raise HTTPException(404, "未找到该官方期次")
    return result


@lru_cache(maxsize=1)
def _build_pool_sample():
    matches = [
        PoolMatch(
            match_id=i + 1,
            match_order=i + 1,
            home_team=f"示例主队{i + 1}",
            away_team=f"示例客队{i + 1}",
            prob_home=0.4,
            prob_draw=0.35,
            prob_away=0.25,
        )
        for i in range(14)
    ]
    result = pool_analysis_to_dict(analyze_pool(matches, period_id="synthetic-example"))
    result["synthetic"] = True
    return result


@router.get("/api/pool/sample")
def get_pool_sample():
    return _build_pool_sample()


@router.post("/api/pool/issues/{issue_id}/generate-combinations")
def generate_pool_issue_combinations(
    issue_id: str, budget: int = Query(256, ge=2, le=10000), strategy: str = "balanced"
):
    return run_pool_analysis(budget=budget, strategy=strategy, issue_id=issue_id)


def _snapshot_digest(snapshot):
    canonical = {
        k: v
        for k, v in snapshot.items()
        if k not in {"snapshot_hash", "generated_at", "data_as_of"}
    }
    canonical["rx9"] = {k: v for k, v in snapshot["rx9"].items() if k != "data_as_of"}
    return content_sha256(canonical)


class SavePoolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_id: str
    budget: StrictInt = Field(ge=2, le=10000)
    strategy: str
    pinned_orders: list[StrictInt] = Field(default_factory=list, max_length=9)
    excluded_orders: list[StrictInt] = Field(default_factory=list, max_length=14)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/api/pool/plans")
def save_pool_plan(body: SavePoolPlan):
    # Recompute server-side from canonical evidence. Never trust client tickets,
    # probabilities or costs, and never create betting/ledger transactions.
    for values in [body.pinned_orders, body.excluded_orders]:
        _orders(",".join(map(str, values)))
    if set(body.pinned_orders) & set(body.excluded_orders):
        raise HTTPException(400, "固定场次不能同时排除")
    try:
        validate_budget(body.budget)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.strategy not in {"conservative", "balanced", "aggressive"}:
        raise HTTPException(400, "未知组合策略")
    with get_db() as conn:
        # READ COMMITTED INSERT handles concurrent idempotent saves. Analysis is
        # captured in a repeatable snapshot first; insert does not reread inputs.
        _start_snapshot(conn)
        snapshot = _analysis(
            conn,
            budget=body.budget,
            strategy=body.strategy,
            issue_id=body.issue_id,
            pins=body.pinned_orders,
            excludes=body.excluded_orders,
        )
        if snapshot.get("input_hash") != body.input_hash:
            raise HTTPException(409, "来源或参数已变化，请刷新后保存")
        if not snapshot["full_combinations"]["count"] and not snapshot["rx9"]["combinations_count"]:
            raise HTTPException(409, "当前没有可保存的完整方案")
        snapshot["snapshot_hash"] = _snapshot_digest(snapshot)
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO football_pool_combinations
                (issue_id,strategy_name,combination_type,total_units,total_cost,
                 estimated_hit_14_prob,estimated_hit_13_prob,combination_json)
                VALUES (%s,%s,'research-comparison',%s,%s,%s,%s,%s)
                ON CONFLICT ((combination_json->>'snapshot_hash'))
                    WHERE combination_json->>'schema_version'='football-pool/v2' DO NOTHING
                RETURNING id""",
                (
                    snapshot["issue"]["id"],
                    body.strategy,
                    snapshot["full_combinations"]["count"] or snapshot["rx9"]["combinations_count"],
                    snapshot["full_combinations"]["total_cost"]
                    or snapshot["rx9"].get("total_cost", 0),
                    snapshot["probabilities"]["hit14_prob"],
                    snapshot["probabilities"]["hit13_or_more_prob"],
                    Json(snapshot),
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT id FROM football_pool_combinations WHERE combination_json->>'snapshot_hash'=%s AND combination_json->>'schema_version'='football-pool/v2'",
                    (snapshot["snapshot_hash"],),
                )
                row = cur.fetchone()
        conn.commit()
    return {"id": row[0], "snapshot_hash": snapshot["snapshot_hash"]}


@router.get("/api/pool/plans")
def list_pool_plans():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,combination_json->'issue',combination_json->'parameters',created_at
                FROM football_pool_combinations WHERE combination_json->>'schema_version'='football-pool/v2'
                ORDER BY id DESC LIMIT 50""")
            rows = cur.fetchall()
    return {
        "plans": [
            {"id": r[0], "issue": r[1], "parameters": r[2], "created_at": r[3].isoformat()}
            for r in rows
        ]
    }


@router.get("/api/pool/plans/{plan_id}")
def read_pool_plan(plan_id: int):
    with get_db() as conn:
        _start_snapshot(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT combination_json FROM football_pool_combinations WHERE id=%s AND combination_json->>'schema_version'='football-pool/v2'",
                (plan_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "方案不存在")
        snapshot = row[0]
        if snapshot.get("snapshot_hash") != _snapshot_digest(snapshot):
            raise HTTPException(409, "保存快照完整性校验失败")
        params = snapshot["parameters"]
        current = _analysis(
            conn,
            budget=params["budget"],
            strategy=params["strategy"],
            issue_id=params["issue_id"],
            pins=params["pinned_orders"],
            excludes=params["excluded_orders"],
        )
    return {
        "id": plan_id,
        "stale": current.get("input_hash") != snapshot["input_hash"],
        "snapshot": snapshot,
    }
