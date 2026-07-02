"""Recommendation candidate job.

Reads latest model predictions → checks shutdown rules → computes EV →
composes simulation tickets → stores them.

Stage 4: simulation-only mode. All tickets are "generated" status,
not actionable. Uses conservative bankroll sizing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.bankroll import StakeLimits, suggested_stake
from scripts.model_storage import store_simulation_ticket
from scripts.recommendation_shutdown import evaluate_shutdown


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run(dry_run: bool = False) -> dict[str, Any]:
    """Generate simulation ticket candidates from latest predictions."""
    if dry_run:
        return {"status": "dry_run", "message": "recommendation candidate (dry run)"}

    with get_db() as conn:
        # 1. Get latest prediction run time
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(predict_time) FROM model_predictions")
            row = cur.fetchone()
        if not row or not row[0]:
            return {"status": "ok", "tickets": 0, "note": "no predictions available"}
        latest_time = row[0]

        # 2. Load latest predictions with odds and match info
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    mp.id, mp.match_id, mp.model_version_id,
                    mp.play_type, mp.option_code,
                    mp.model_probability, mp.market_probability,
                    mp.ev, mp.confidence_score, mp.risk_score,
                    mp.odds_snapshot_id,
                    m.home_team_name, m.away_team_name, m.league_name,
                    os.sp_value,
                    mv.model_name
                FROM model_predictions mp
                JOIN official_matches m ON m.id = mp.match_id
                JOIN model_versions mv ON mv.id = mp.model_version_id
                LEFT JOIN official_odds_snapshots os ON os.id = mp.odds_snapshot_id
                WHERE mp.predict_time = %s
                  AND mp.play_type = 'spf'
                  AND mv.model_name = 'market_baseline'
                ORDER BY mp.ev DESC
                """,
                (latest_time,),
            )
            predictions = cur.fetchall()

        if not predictions:
            return {"status": "ok", "tickets": 0, "note": "no market_baseline predictions"}

        # 3. Get data quality from latest feature snapshots
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT match_id, data_completeness_score
                FROM match_feature_snapshots
                WHERE (match_id, snapshot_time) IN (
                    SELECT match_id, MAX(snapshot_time)
                    FROM match_feature_snapshots
                    GROUP BY match_id
                )
                """
            )
            quality_map = {row[0]: float(row[1] or 0) for row in cur.fetchall()}

        # 4. Filter predictions: EV > -0.03, confidence > 0.3, quality >= 60
        candidates = []
        for p in predictions:
            pred_id, match_id, mv_id, play_type, opt_code = p[0], p[1], p[2], p[3], p[4]
            model_prob, market_prob, ev = float(p[5] or 0), float(p[6] or 0), float(p[7] or 0)
            confidence, risk = float(p[8] or 0), float(p[9] or 0)
            snap_id, home, away, _league = p[10], p[11], p[12], p[13]
            sp_value = float(p[14]) if p[14] else 0
            p[15]

            # Quality gate
            quality = quality_map.get(match_id, 0)

            # Shutdown check
            shutdown_result = evaluate_shutdown(
                {
                    "official_source_ok": True,
                    "data_quality_score": quality,
                    "committee_disagreement": float(risk or 0),
                    "adjusted_ev": ev,
                }
            )
            if shutdown_result:
                continue  # blocked by shutdown rules

            if ev > -0.03 and confidence > 0.3 and quality >= 60:
                candidates.append(
                    {
                        "prediction_id": pred_id,
                        "match_id": match_id,
                        "model_version_id": mv_id,
                        "play_type": play_type,
                        "option_code": opt_code,
                        "option_name": _option_label(opt_code),
                        "model_probability": model_prob,
                        "market_probability": market_prob,
                        "ev": ev,
                        "confidence_score": confidence,
                        "risk_score": risk,
                        "odds_snapshot_id": snap_id,
                        "sp_value": sp_value,
                        "home_team": home,
                        "away_team": away,
                    }
                )

        if not candidates:
            return {"status": "ok", "tickets": 0, "note": "no candidates passed quality gates"}

        # 5. Compose single-match tickets (no parlays for simulation)
        limits = StakeLimits()  # defaults: 500 daily, 100 per ticket
        tickets_created = 0
        total_stake = 0.0

        for c in candidates:
            # Bankroll sizing
            stake = suggested_stake(c["model_probability"], c["sp_value"], limits)
            if stake < 2:  # minimum 2 yuan
                continue

            est_return = stake * c["sp_value"]
            risk_level = (
                "low" if c["risk_score"] < 0.1 else ("medium" if c["risk_score"] < 0.25 else "high")
            )

            ticket = {
                "strategy_pool": _assign_pool(c["ev"], c["confidence_score"]),
                "ticket_type": "single",
                "pass_type": "single",
                "suggested_stake": stake,
                "multiple": 1,
                "estimated_return": round(est_return, 2),
                "max_return": round(est_return, 2),
                "expected_value": round(c["ev"], 4),
                "risk_level": risk_level,
                "ticket_status": "generated",
            }

            items = [
                {
                    "match_id": c["match_id"],
                    "odds_snapshot_id": c["odds_snapshot_id"],
                    "model_prediction_id": c["prediction_id"],
                    "play_type": c["play_type"],
                    "option_code": c["option_code"],
                    "option_name": c["option_name"],
                    "sp_value": c["sp_value"],
                    "model_probability": c["model_probability"],
                    "market_probability": c["market_probability"],
                    "ev": c["ev"],
                    "confidence_score": c["confidence_score"],
                    "risk_score": c["risk_score"],
                }
            ]

            tid = store_simulation_ticket(conn, ticket, items)
            if tid:
                tickets_created += 1
                total_stake += stake

        return {
            "status": "ok",
            "tickets": tickets_created,
            "total_stake": round(total_stake, 2),
            "candidates_evaluated": len(candidates),
        }


def _option_label(code: str) -> str:
    return {"3": "主胜", "1": "平", "0": "客胜"}.get(code, code)


def _assign_pool(ev: float, confidence: float) -> str:
    """Assign to strategy pool based on EV and confidence."""
    if ev > 0.05 and confidence > 0.7:
        return "value"
    elif confidence > 0.5:
        return "main"
    elif ev > 0.02:
        return "experiment"
    return "defensive"


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
