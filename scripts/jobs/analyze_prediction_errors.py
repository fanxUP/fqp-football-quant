"""Prediction error analysis job.

Compares model predictions against confirmed match results and classifies
errors using the 9-tag system from docs/10.

Initial implementation covers 4 model-level tags. The remaining 5
(INJURY_DATA_MISSING, PARLAY_CORRELATION_HIGH, USER_CHANGED_OPTION,
USER_OVER_STAKED, USER_CHASED_LOSS) require data not yet available.

Runs daily at 23:45, after settlement and daily review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.real_ticket_storage import create_error_analyses_batch


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run(dry_run: bool = False) -> dict[str, Any]:
    """Analyze prediction errors for all predictions with confirmed results."""
    if dry_run:
        return {"status": "dry_run", "message": "analyze prediction errors (dry run)"}

    with get_db() as conn:
        # 1. Find predictions with confirmed results that haven't been analyzed yet
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mp.id, mp.match_id, mp.model_version_id,
                       mp.play_type, mp.option_code,
                       mp.model_probability, mp.market_probability,
                       mp.ev, mp.confidence_score, mp.risk_score,
                       mp.predict_time,
                       r.spf_result, r.full_home_goals, r.full_away_goals,
                       mv.model_name
                FROM model_predictions mp
                JOIN official_results r ON r.match_id = mp.match_id
                JOIN model_versions mv ON mv.id = mp.model_version_id
                WHERE mp.play_type = 'spf'
                  AND r.result_status = 'confirmed'
                  AND r.spf_result IS NOT NULL
                  AND mp.id NOT IN (
                      SELECT prediction_id FROM prediction_error_analysis
                      WHERE prediction_id IS NOT NULL
                  )
                ORDER BY mp.predict_time DESC
                LIMIT 500
                """
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "status": "ok",
                "analyzed": 0,
                "errors_found": 0,
                "note": "no new predictions to analyze",
            }

        # 2. Classify each prediction
        errors = []
        correct_count = 0
        error_types: dict[str, int] = {}

        for row in rows:
            pred_id = row[0]
            match_id = row[1]
            option_code = row[4]  # predicted "3"/"1"/"0"
            model_prob = float(row[5] or 0)
            market_prob = float(row[6] or 0)
            ev = float(row[7] or 0)
            spf_result = row[12]  # actual "3"/"1"/"0"
            home_goals = row[13]
            away_goals = row[14]

            is_correct = option_code == spf_result

            if is_correct:
                correct_count += 1
                continue  # only create error records for wrong predictions

            # ---- Error classification ----
            error_type = None
            error_level = None
            root_cause = None
            suggested_fix = None

            # 1) MODEL_OVERCONFIDENCE: high confidence but wrong
            if model_prob > 0.60:
                error_type = "MODEL_OVERCONFIDENCE"
                error_level = "high"
                root_cause = f"模型概率 {model_prob:.1%} 但预测 {option_code}，实际 {spf_result}"
                suggested_fix = f"降低 {option_code} 概率，检查是否有未建模的利好因素"

            # 2) DRAW_UNDERESTIMATED: actual draw, model predicted not-draw
            elif spf_result == "1" and option_code != "1":
                error_type = "DRAW_UNDERESTIMATED"
                error_level = "medium"
                root_cause = f"预测 {option_code}，实际平局（{home_goals}:{away_goals}）"
                suggested_fix = "提高平局先验概率，检查低比分场景的 Dixon-Coles 修正"

            # 3) FAVOURITE_OVERVALUED: home/away direction reversed
            elif (option_code == "3" and spf_result == "0") or (
                option_code == "0" and spf_result == "3"
            ):
                error_type = "FAVOURITE_OVERVALUED"
                error_level = "high"
                root_cause = f"预测胜负方向完全反向：预测 {option_code}，实际 {spf_result}（{home_goals}:{away_goals}）"
                suggested_fix = "检查球队实力评估是否偏差，审查 odds 隐含概率的 overround 去除方法"

            # 4) ODDS_DROP_AFTER_RECOMMENDATION: positive EV but wrong
            elif ev > 0.03:
                error_type = "ODDS_DROP_AFTER_RECOMMENDATION"
                error_level = "medium"
                root_cause = f"正 EV（{ev:+.4f}）但预测错误"
                suggested_fix = "检查赔率快照是否为临场跳变前的过期数据"

            # Default fallback
            else:
                error_type = "MODEL_OVERCONFIDENCE"
                error_level = "low"
                root_cause = f"预测 {option_code} 实际 {spf_result}，模型概率 {model_prob:.1%}"
                suggested_fix = "累积更多赛果后进行参数重新估计"

            errors.append(
                {
                    "prediction_id": pred_id,
                    "match_id": match_id,
                    "error_type": error_type,
                    "error_level": error_level,
                    "root_cause": root_cause,
                    "model_probability": model_prob,
                    "market_probability": market_prob,
                    "actual_result": spf_result,
                    "suggested_fix": suggested_fix,
                }
            )

            error_types[error_type] = error_types.get(error_type, 0) + 1

        # 3. Batch insert errors
        inserted = 0
        if errors:
            inserted = create_error_analyses_batch(conn, errors)

        return {
            "status": "ok",
            "analyzed": len(rows),
            "correct": correct_count,
            "errors_found": len(errors),
            "inserted": inserted,
            "error_types": error_types,
            "accuracy": round(correct_count / len(rows), 4) if len(rows) > 0 else None,
        }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
