"""Generate the Agent's daily virtual recommendation portfolio.

The Agent recommends; the user decides whether to place a real bet.  The
¥500 bankroll in this module is virtual competition capital, so risk and EV
are displayed as evidence instead of being used as extra veto layers.

Only three hard boundaries remain:
1. the prediction has independent, valid model evidence;
2. the bound feature snapshot reaches the minimum evidence score;
3. the option has valid official odds and a currently open betting route.
"""

from __future__ import annotations

import os
from datetime import datetime
from math import floor
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.competition_storage import AGENT_DAILY_BUDGET
from scripts.daily_decision_storage import upsert_agent_daily_decision
from scripts.model_storage import store_simulation_ticket
from scripts.recommendation_prediction_loader import load_actionable_predictions
from scripts.sporttery_sales import get_sporttery_sales_window

ALL_MODELS = ["market_baseline", "elo_rating", "dixon_coles", "maher_poisson"]
MIN_EVIDENCE_QUALITY = 30
STAKE_UNIT = 2.0
MAX_OFFICIAL_MULTIPLE = 99
MAX_TICKET_STAKE = STAKE_UNIT * MAX_OFFICIAL_MULTIPLE
MAX_DAILY_SELECTIONS = 5


def _business_today():
    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone_name)).date()


def _record_daily_decision(
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    tickets = int((result or {}).get("tickets") or 0)
    total_stake = float((result or {}).get("total_stake") or 0)
    if error:
        status = "failed"
        reason = f"推荐任务执行失败：{error}"
    elif tickets > 0:
        status = "purchased"
        reason = (result or {}).get("note") or f"已生成 {tickets} 张 Agent 虚拟推荐票"
    else:
        status = "abstained"
        reason = (result or {}).get("note") or "暂无可信模型与官方赔率组合"
    with get_db() as conn:
        upsert_agent_daily_decision(
            conn,
            decision_date=_business_today(),
            status=status,
            total_stake=total_stake,
            reason=reason,
        )


def _official_stake(value: float) -> float:
    """Round virtual stake down to the official two-yuan unit."""
    return float(floor(max(0.0, value) / STAKE_UNIT) * STAKE_UNIT)


def _payout_cap(match_count: int) -> float:
    if match_count <= 1:
        return 100_000.0
    if match_count <= 3:
        return 200_000.0
    if match_count <= 5:
        return 500_000.0
    return 1_000_000.0


def _prediction_sp_value(prediction_row: tuple[Any, ...]) -> float:
    """Read SP from the fixed actionable-prediction query layout."""
    value = prediction_row[16]
    return float(value or 0) if value else 0.0


def _market_sp_quality(
    predictions: list[tuple[Any, ...]],
) -> tuple[dict[tuple[int, str], bool], int]:
    """Reject missing or obviously duplicated odds within one market."""
    market_values: dict[tuple[int, str], dict[str, float]] = {}
    for prediction in predictions:
        market_key = (prediction[1], prediction[3])
        market_values.setdefault(market_key, {})[prediction[4]] = _prediction_sp_value(prediction)

    quality: dict[tuple[int, str], bool] = {}
    for market_key, option_values in market_values.items():
        values = list(option_values.values())
        quality[market_key] = not (
            any(value <= 0 for value in values)
            or (len(values) >= 2 and len(set(values)) == 1)
        )
    valid_match_count = len(
        {match_id for (match_id, _play_type), is_valid in quality.items() if is_valid}
    )
    return quality, valid_match_count


def _load_prediction_feature_quality(
    conn: Any,
    predictions: list[tuple[Any, ...]],
) -> dict[int, float]:
    """Load only the immutable feature snapshots bound to predictions."""
    snapshot_ids = sorted({int(row[11]) for row in predictions if row[11] is not None})
    if not snapshot_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, data_completeness_score
            FROM match_feature_snapshots
            WHERE id = ANY(%s)
            """,
            (snapshot_ids,),
        )
        return {int(row[0]): float(row[1] or 0) for row in cur.fetchall()}


def _preferred_direction_by_market(
    predictions: list[tuple[Any, ...]],
) -> dict[tuple[int, str], tuple[str, float]]:
    """Return the model's strongest direction inside each play type."""
    preferred: dict[tuple[int, str], tuple[str, float]] = {}
    for prediction in predictions:
        key = (prediction[1], prediction[3])
        probability = float(prediction[5] or 0)
        if key not in preferred or probability > preferred[key][1]:
            preferred[key] = (prediction[4], probability)
    return preferred


def _select_daily_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Choose one transparent model recommendation per match.

    First retain the highest model probability within each play type, then use
    EV only to rank the remaining play types for that match. Negative EV is
    preserved instead of hidden; it is evidence for the user's own decision.
    """
    by_market: dict[tuple[int, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (candidate["match_id"], candidate["play_type"])
        current = by_market.get(key)
        if current is None or candidate["model_probability"] > current["model_probability"]:
            by_market[key] = candidate

    by_match: dict[int, dict[str, Any]] = {}
    for candidate in by_market.values():
        match_id = candidate["match_id"]
        current = by_match.get(match_id)
        candidate_rank = (candidate["ev"], candidate["model_probability"])
        current_rank = (
            (current["ev"], current["model_probability"])
            if current is not None
            else (float("-inf"), float("-inf"))
        )
        if candidate_rank > current_rank:
            by_match[match_id] = candidate
    return sorted(
        by_match.values(),
        key=lambda item: (item["ev"], item["model_probability"]),
        reverse=True,
    )


def _market_allows_pass(raw_json: dict[str, Any] | None) -> bool:
    pool = (raw_json or {}).get("_pool") or {}
    for field in ("allUp", "bettingAllup", "cbtAllUp", "intAllUp"):
        value = pool.get(field)
        if value is True or value == 1 or value == "1":
            return True
    return False


def _split_budget(total: float, count: int) -> list[float]:
    if count <= 0:
        return []
    total_units = int(_official_stake(total) / STAKE_UNIT)
    base_units, remainder = divmod(total_units, count)
    return [float((base_units + (1 if index < remainder else 0)) * STAKE_UNIT) for index in range(count)]


def _stake_chunks(stake: float) -> list[float]:
    chunks: list[float] = []
    remaining = _official_stake(stake)
    while remaining > 0:
        chunk = min(remaining, MAX_TICKET_STAKE)
        chunks.append(chunk)
        remaining = round(remaining - chunk, 2)
    return chunks


def _combined_metrics(items: list[dict[str, Any]]) -> tuple[float, float]:
    combined_sp = 1.0
    combined_ev = 1.0
    for item in items:
        combined_sp *= float(item.get("sp_value") or 0)
        combined_ev *= float(item.get("ev") or 0) + 1
    return combined_sp, combined_ev - 1


def _ticket_entry(
    items: list[dict[str, Any]],
    *,
    pass_type: str,
    stake: float,
) -> dict[str, Any]:
    combined_sp, combined_ev = _combined_metrics(items)
    match_count = len(items)
    return {
        "ticket": {
            "strategy_pool": "agent_virtual_recommendation",
            "ticket_type": "virtual_recommendation",
            "pass_type": pass_type,
            "suggested_stake": stake,
            "multiple": int(stake / STAKE_UNIT),
            "bet_count": 1,
            "estimated_return": round(min(stake * combined_sp, _payout_cap(match_count)), 2),
            "max_return": round(min(stake * combined_sp, _payout_cap(match_count)), 2),
            "expected_value": round(combined_ev, 4),
            "risk_level": "reference",
            "ticket_status": "generated",
            "rule_metadata": {
                "source": "sporttery_rules",
                "virtual_competition": True,
                "user_decides_real_purchase": True,
            },
        },
        "items": items,
    }


def _build_virtual_recommendation_tickets(
    candidates: list[dict[str, Any]],
    *,
    single_allowed: set[tuple[int, str]],
    pass_allowed: set[tuple[int, str]],
    daily_budget: float = AGENT_DAILY_BUDGET,
) -> list[dict[str, Any]]:
    """Allocate the full virtual bankroll without risk-based vetoes."""
    eligible = [candidate for candidate in candidates if float(candidate.get("sp_value") or 0) > 0]
    singles = [
        candidate
        for candidate in eligible
        if (candidate["match_id"], candidate["play_type"]) in single_allowed
    ][:MAX_DAILY_SELECTIONS]

    planned: list[dict[str, Any]] = []
    if singles:
        for candidate, allocated in zip(singles, _split_budget(daily_budget, len(singles)), strict=True):
            for chunk in _stake_chunks(allocated):
                planned.append(_ticket_entry([candidate], pass_type="single", stake=chunk))
        return planned

    pass_candidates: list[dict[str, Any]] = []
    seen_matches: set[int] = set()
    for candidate in eligible:
        key = (candidate["match_id"], candidate["play_type"])
        if key not in pass_allowed or candidate["match_id"] in seen_matches:
            continue
        pass_candidates.append(candidate)
        seen_matches.add(candidate["match_id"])
        if len(pass_candidates) == 2:
            break
    if len(pass_candidates) != 2:
        return []
    for chunk in _stake_chunks(daily_budget):
        planned.append(_ticket_entry(pass_candidates, pass_type="2x1", stake=chunk))
    return planned


def _option_label(code: str, play_type: str = "spf") -> str:
    if play_type == "bqc" and len(code) == 2:
        labels = {"3": "胜", "1": "平", "0": "负"}
        return f"{labels.get(code[0], code[0])}{labels.get(code[1], code[1])}"
    if play_type == "zjq":
        return "7+球" if code in {"7", "7+"} else f"{code}球"
    if play_type == "bf":
        return code.replace("_h", "其他胜").replace("_d", "其他平").replace("_a", "其他负")
    if play_type == "rqspf":
        return {"3": "让胜", "1": "让平", "0": "让负"}.get(code, code)
    return {"3": "主胜", "1": "平", "0": "客胜"}.get(code, code)


def _make_item(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": candidate["match_id"],
        "odds_snapshot_id": candidate["odds_snapshot_id"],
        "model_prediction_id": candidate["prediction_id"],
        "feature_snapshot_id": candidate.get("feature_snapshot_id"),
        "play_type": candidate["play_type"],
        "option_code": candidate["option_code"],
        "option_name": candidate["option_name"],
        "sp_value": candidate["sp_value"],
        "model_probability": candidate["model_probability"],
        "market_probability": candidate["market_probability"],
        "ev": candidate["ev"],
        "confidence_score": candidate["confidence_score"],
        "risk_score": candidate["risk_score"],
        "odds_source": "official",
    }


def _load_reusable_ticket_summary(conn: Any) -> tuple[int, float]:
    """Reuse only today's tickets whose evidence is still independently valid."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(st.suggested_stake), 0)
            FROM simulation_tickets st
            JOIN daily_budget_plans bp ON bp.id = st.budget_plan_id
            WHERE bp.plan_date = timezone('Asia/Shanghai', NOW())::date
              AND st.ticket_status <> 'invalid'
              AND EXISTS (
                  SELECT 1
                  FROM simulation_ticket_items sti
                  WHERE sti.ticket_id = st.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM simulation_ticket_items sti
                  JOIN model_predictions mp ON mp.id = sti.model_prediction_id
                  JOIN model_versions mv ON mv.id = mp.model_version_id
                  JOIN match_feature_snapshots mfs
                    ON mfs.id = COALESCE(sti.feature_snapshot_id, mp.feature_snapshot_id)
                  WHERE sti.ticket_id = st.id
                    AND (
                        mv.is_active IS NOT true
                        OR mp.validation_status <> 'valid'
                        OR mfs.data_completeness_score < %(min_quality)s
                        OR COALESCE(
                            (mp.uncertainty_reason->>'model_independent')::boolean,
                            false
                        ) IS NOT true
                    )
              )
            """,
            {"min_quality": MIN_EVIDENCE_QUALITY},
        )
        count, stake = cur.fetchone()
    return int(count or 0), float(stake or 0)


def _parse_candidates(
    predictions: list[tuple[Any, ...]],
    quality_map: dict[int, float],
    market_quality: dict[tuple[int, str], bool],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for prediction in predictions:
        feature_snapshot_id = prediction[11]
        quality = quality_map.get(int(feature_snapshot_id), 0) if feature_snapshot_id else 0
        match_id = prediction[1]
        play_type = prediction[3]
        if quality < MIN_EVIDENCE_QUALITY or not market_quality.get((match_id, play_type), False):
            continue
        candidates.append(
            {
                "prediction_id": prediction[0],
                "match_id": match_id,
                "play_type": play_type,
                "option_code": prediction[4],
                "option_name": _option_label(prediction[4], play_type),
                "model_probability": float(prediction[5] or 0),
                "market_probability": float(prediction[6] or 0),
                "ev": float(prediction[7] or 0),
                "confidence_score": float(prediction[8] or 0),
                "risk_score": float(prediction[9] or 0),
                "odds_snapshot_id": prediction[10],
                "feature_snapshot_id": feature_snapshot_id,
                "home_team": prediction[12],
                "away_team": prediction[13],
                "league": prediction[14],
                "sp_value": _prediction_sp_value(prediction),
                "model_name": prediction[17],
                "data_quality": quality,
            }
        )
    return candidates


def _buy_ticket(conn: Any, ticket: dict, items: list[dict]) -> int | None:
    if ticket.get("suggested_stake", 0) <= 0:
        return None
    try:
        return store_simulation_ticket(conn, ticket, items)
    except Exception as exc:
        conn.rollback()
        print(f"[_buy_ticket] error creating ticket: {exc}")
        return None


def _run_impl(dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run", "message": "recommendation candidate (dry run)"}

    sales_window = get_sporttery_sales_window()
    if not sales_window.is_open:
        return {
            "status": "ok",
            "tickets": 0,
            "quality_status": "not_due",
            "note": sales_window.message,
            "sales_window": sales_window.as_dict(),
        }

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_budget_plans (
                    plan_date, total_budget, suggested_stake,
                    unused_budget, risk_mode, status
                ) VALUES (
                    timezone('Asia/Shanghai', NOW())::date,
                    %s, 0.00, %s, 'virtual', 'active'
                ) ON CONFLICT (plan_date) DO NOTHING
                """,
                (AGENT_DAILY_BUDGET, AGENT_DAILY_BUDGET),
            )
        conn.commit()

        existing_count, existing_stake = _load_reusable_ticket_summary(conn)
        if existing_count > 0:
            return {
                "status": "ok",
                "tickets": existing_count,
                "total_stake": existing_stake,
                "reused": True,
                "note": f"今日已存在 {existing_count} 张 Agent 虚拟推荐票，本次不重复创建",
            }

        predictions = load_actionable_predictions(conn, ALL_MODELS)
        if not predictions:
            return {"status": "ok", "tickets": 0, "note": "暂无可用模型预测"}

        match_ids = sorted({prediction[1] for prediction in predictions})
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT match_id, play_type, is_single_allowed, raw_json
                FROM official_markets
                WHERE match_id = ANY(%s) AND is_open = true
                """,
                (match_ids,),
            )
            market_permissions = cur.fetchall()
        open_markets = {(row[0], row[1]) for row in market_permissions}
        predictions = [
            prediction
            for prediction in predictions
            if (prediction[1], prediction[3]) in open_markets
        ]
        if not predictions:
            return {"status": "ok", "tickets": 0, "note": "暂无官方在售推荐选项"}

        market_quality, _valid_match_count = _market_sp_quality(predictions)
        quality_map = _load_prediction_feature_quality(conn, predictions)
        parsed = _parse_candidates(predictions, quality_map, market_quality)
        candidates = _select_daily_candidates(parsed)
        if not candidates:
            return {
                "status": "ok",
                "tickets": 0,
                "note": f"模型证据完整度未达到 {MIN_EVIDENCE_QUALITY} 分，暂不生成推荐",
            }

        single_allowed = {(row[0], row[1]) for row in market_permissions if row[2]}
        pass_allowed = {
            (row[0], row[1])
            for row in market_permissions
            if _market_allows_pass(row[3])
        }
        planned = _build_virtual_recommendation_tickets(
            candidates,
            single_allowed=single_allowed,
            pass_allowed=pass_allowed,
        )
        if not planned:
            return {"status": "ok", "tickets": 0, "note": "推荐方向当前没有可用单关或过关路径"}

        tickets_created = 0
        total_stake = 0.0
        for entry in planned:
            ticket = entry["ticket"]
            items = [_make_item(candidate) for candidate in entry["items"]]
            if _buy_ticket(conn, ticket, items):
                tickets_created += 1
                total_stake += float(ticket["suggested_stake"])

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE daily_budget_plans
                SET suggested_stake = %(stake)s,
                    unused_budget = GREATEST(total_budget - %(stake)s, 0),
                    updated_at = now()
                WHERE plan_date = timezone('Asia/Shanghai', NOW())::date
                """,
                {"stake": total_stake},
            )
        conn.commit()
        return {
            "status": "ok",
            "tickets": tickets_created,
            "total_stake": round(total_stake, 2),
            "total_budget": AGENT_DAILY_BUDGET,
            "unused": round(AGENT_DAILY_BUDGET - total_stake, 2),
            "candidate_count": len(candidates),
            "note": (
                f"已用 {total_stake:.0f} 元虚拟资金生成 {tickets_created} 张 Agent 推荐票；"
                "是否真实购买由用户自行决定"
            ),
        }


def run(dry_run: bool = False) -> dict[str, Any]:
    run_id = None
    try:
        run_id = start_tracked_job(
            "recommendation_candidate",
            "recommendation_agent",
            {"dry_run": dry_run},
            dependencies=[] if dry_run else ["official_odds_snapshot", "model_prediction"],
        )
        result = _run_impl(dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        if not dry_run:
            _record_daily_decision(result=result)
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        if not dry_run:
            _record_daily_decision(error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    print(run(dry_run="--dry-run" in sys.argv))
