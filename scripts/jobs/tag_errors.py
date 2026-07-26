"""Post-settlement error tagging（框架 §13 错因标签体系）.

Analyzes settled simulation tickets, identifies error patterns, and writes
tags to prediction_error_analysis for continuous improvement.

Runs after settle_tickets (e.g., at 22:30 or as part of snapshot_competition).
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db

# ── 错因标签映射（框架 §13） ──

ERROR_TAG_RULES: list[dict[str, Any]] = [
    {
        "tag": "赔率过热",
        "description": "SP过低（<1.30）的热门方向输球",
        "condition": lambda item, result, sp: item["option_code"] != result and sp < 1.30,
    },
    {
        "tag": "热门赢不穿",
        "description": "低SP主胜被打平（SPF胜但RQSPF不穿）",
        "condition": lambda item, result, sp: (
            item["option_code"] == "3" and result == "1" and sp < 1.50
        ),
    },
    {
        "tag": "平局风险低估",
        "description": "模型低估平局概率（<25%）但实际打平",
        "condition": lambda item, result, sp: (
            result == "1" and item.get("model_probability", 0) < 0.25
        ),
    },
    {
        "tag": "模型概率偏高",
        "description": "模型概率显著高于市场（>10%）但预测错误",
        "condition": lambda item, result, sp: (
            item["option_code"] != result
            and (item.get("model_probability", 0) - item.get("market_probability", 0)) > 0.10
        ),
    },
    {
        "tag": "市场概率判断错误",
        "description": "市场最看好方向（>50%隐含概率）打不出",
        "condition": lambda item, result, sp: (
            item["option_code"] != result and item.get("market_probability", 0) > 0.50
        ),
    },
    {
        "tag": "冷门未识别",
        "description": "高SP（>4.00）方向预测错误",
        "condition": lambda item, result, sp: item["option_code"] != result and sp > 4.00,
    },
]


def run(dry_run: bool = False) -> dict[str, Any]:
    """Tag errors for simulation tickets settled today."""
    if dry_run:
        return {"status": "dry_run", "message": "error tagging (dry run)"}

    with get_db() as conn:
        # ── 1. Find simulation tickets settled today that lost ──
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ts.id AS settlement_id,
                    ts.ticket_id,
                    ts.is_won,
                    ts.roi,
                    sti.id AS item_id,
                    sti.match_id,
                    sti.model_prediction_id,
                    sti.option_code,
                    sti.model_probability,
                    sti.market_probability,
                    sti.sp_value,
                    r.spf_result,
                    r.full_home_goals,
                    r.full_away_goals
                FROM ticket_settlements ts
                JOIN simulation_ticket_items sti ON sti.ticket_id = ts.ticket_id
                JOIN official_results r ON r.match_id = sti.match_id
                WHERE ts.ticket_source = 'simulation'
                  AND (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                      = timezone('Asia/Shanghai', NOW())::date
                  AND ts.is_won = false
                  AND r.result_status = 'confirmed'
                """,
            )
            lost_items = [
                {
                    "settlement_id": r[0],
                    "ticket_id": r[1],
                    "is_won": r[2],
                    "roi": float(r[3] or 0),
                    "item_id": r[4],
                    "match_id": r[5],
                    "prediction_id": r[6],
                    "option_code": r[7],
                    "model_probability": float(r[8] or 0),
                    "market_probability": float(r[9] or 0),
                    "sp_value": float(r[10] or 0),
                    "spf_result": r[11],
                    "home_goals": r[12],
                    "away_goals": r[13],
                }
                for r in cur.fetchall()
            ]

        if not lost_items:
            return {"status": "ok", "tagged": 0, "note": "no losing tickets to analyze"}

        # ── 2. Apply error tag rules ──
        tags_written = 0

        for item in lost_items:
            result = item["spf_result"]
            sp = item["sp_value"]
            if not result:
                continue

            matched_tags: list[str] = []
            for rule in ERROR_TAG_RULES:
                try:
                    if rule["condition"](item, result, sp):
                        matched_tags.append(rule["tag"])
                except Exception:
                    continue

            if not matched_tags:
                matched_tags.append("其他")

            # ── 3. One atomic upsert per prediction ──
            goal_info = (
                f"({item['home_goals']}-{item['away_goals']})"
                if item["home_goals"] is not None
                else ""
            )
            root_cause = (
                f"SP={sp:.2f} model_prob={item['model_probability']:.3f} "
                f"market_prob={item['market_probability']:.3f} "
                f"actual={result}{goal_info}"
            )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prediction_error_analysis (
                        prediction_id, match_id, error_type, error_level,
                        root_cause, model_probability, market_probability,
                        actual_result
                    ) VALUES (
                        %(pid)s, %(mid)s, %(tag)s, %(level)s,
                        %(cause)s, %(mp)s, %(mkp)s, %(actual)s
                    )
                    ON CONFLICT (prediction_id)
                    WHERE prediction_id IS NOT NULL
                    DO UPDATE SET
                        match_id = EXCLUDED.match_id,
                        error_type = EXCLUDED.error_type,
                        error_level = EXCLUDED.error_level,
                        root_cause = EXCLUDED.root_cause,
                        model_probability = EXCLUDED.model_probability,
                        market_probability = EXCLUDED.market_probability,
                        actual_result = EXCLUDED.actual_result,
                        created_at = NOW()
                    """,
                    {
                        "pid": item["prediction_id"],
                        "mid": item["match_id"],
                        "tag": "、".join(matched_tags),
                        "level": "warning",
                        "cause": root_cause,
                        "mp": item["model_probability"],
                        "mkp": item["market_probability"],
                        "actual": f"{result}{goal_info}",
                    },
                )
                tags_written += 1

        # ── 4. Summary ──
        tag_counts: dict[str, int] = {}
        for item in lost_items:
            result = item["spf_result"]
            sp = item["sp_value"]
            if not result:
                continue
            for rule in ERROR_TAG_RULES:
                try:
                    if rule["condition"](item, result, sp):
                        tag_counts[rule["tag"]] = tag_counts.get(rule["tag"], 0) + 1
                except Exception:
                    continue

        return {
            "status": "ok",
            "lost_items": len(lost_items),
            "tagged": tags_written,
            "tag_breakdown": tag_counts,
        }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
