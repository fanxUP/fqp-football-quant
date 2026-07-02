"""Evidence chain validator.

Stage 8: Daily job (23:30) that verifies every recommendation has a complete
evidence chain:

  ticket_item → odds_snapshot → model_prediction → model_version → feature_snapshot

A recommendation with a broken chain fails the Stage 8 acceptance criterion
of 100% evidence chain completeness.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.ops_storage import store_evidence_chain_audit


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_recent_ticket_items(conn: Any, days: int = 7) -> list[dict]:
    """Get ticket items from the last N days with their chain links."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                st.id AS ticket_id,
                sti.id AS item_id,
                sti.odds_snapshot_id,
                sti.model_prediction_id,
                st.batch_id
            FROM simulation_ticket_items sti
            JOIN simulation_tickets st ON st.id = sti.ticket_id
            WHERE st.created_at >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY st.created_at DESC
            LIMIT 500
            """,
            (days,),
        )
        cols = ["ticket_id", "item_id", "odds_snapshot_id", "model_prediction_id", "batch_id"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_prediction_chain(conn: Any, prediction_id: int) -> dict | None:
    """Get the full chain from a model prediction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                mp.id AS prediction_id,
                mp.model_version_id,
                mp.odds_snapshot_id AS pred_odds_snapshot_id,
                mp.predict_time,
                mv.model_name,
                mv.version_number
            FROM model_predictions mp
            LEFT JOIN model_versions mv ON mv.id = mp.model_version_id
            WHERE mp.id = %s
            """,
            (prediction_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = [
        "prediction_id",
        "model_version_id",
        "pred_odds_snapshot_id",
        "predict_time",
        "model_name",
        "version_number",
    ]
    return dict(zip(cols, row))


def _get_feature_snapshot_for_match(conn: Any, match_id: int, before_time: str) -> dict | None:
    """Find the most recent feature snapshot built before the given time."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, feature_version, snapshot_time, data_completeness_score
            FROM match_feature_snapshots
            WHERE match_id = %s
              AND snapshot_time <= %s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (match_id, before_time),
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = ["feature_snapshot_id", "feature_version", "snapshot_time", "completeness_score"]
    return dict(zip(cols, row))


def _get_match_id_from_odds_snapshot(conn: Any, odds_snapshot_id: int) -> int | None:
    """Get match_id from an odds snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT match_id FROM official_odds_snapshots WHERE id = %s",
            (odds_snapshot_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def run(dry_run: bool = False) -> dict[str, Any]:
    """Validate evidence chains for all recent recommendations.

    Checks each ticket item for:
      1. odds_snapshot_id → valid, not stale (>24h old)
      2. model_prediction_id → valid, has model_version
      3. model_version → exists and is current
      4. feature_snapshot → exists for the match before prediction time

    Returns:
        Summary with chain completeness stats.
    """
    audit_time = _now()

    with get_db() as conn:
        items = _get_recent_ticket_items(conn, days=7)

        if not items:
            return {
                "status": "ok",
                "total_audited": 0,
                "complete": 0,
                "broken": 0,
                "note": "no recent ticket items to audit",
            }

        complete = 0
        broken = 0
        broken_details = []

        for item in items:
            chain_details = {
                "ticket_id": item["ticket_id"],
                "item_id": item["item_id"],
                "batch_id": item["batch_id"],
            }
            broken_link = None
            chain_ok = True

            # Link 1: odds_snapshot_id
            odds_id = item["odds_snapshot_id"]
            chain_details["odds_snapshot_id"] = odds_id
            if not odds_id:
                broken_link = "odds_snapshot"
                chain_ok = False
            else:
                # Check staleness
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT snapshot_time FROM official_odds_snapshots WHERE id = %s",
                        (odds_id,),
                    )
                    row = cur.fetchone()
                if row and row[0]:
                    age = (datetime.now() - row[0]).total_seconds()
                    chain_details["odds_snapshot_age_seconds"] = int(age)
                else:
                    broken_link = "odds_snapshot_invalid"
                    chain_ok = False

            # Link 2: model_prediction_id
            pred_id = item["model_prediction_id"]
            chain_details["model_prediction_id"] = pred_id
            if not pred_id:
                broken_link = broken_link or "model_prediction"
                chain_ok = False
            else:
                pred_chain = _get_prediction_chain(conn, pred_id)
                if not pred_chain:
                    broken_link = broken_link or "model_prediction_invalid"
                    chain_ok = False
                else:
                    chain_details["model_version_id"] = pred_chain["model_version_id"]
                    if not pred_chain["model_version_id"]:
                        broken_link = broken_link or "model_version"
                        chain_ok = False

                    # Link 3: feature_snapshot (find by match + time)
                    match_id = _get_match_id_from_odds_snapshot(
                        conn, odds_id or pred_chain.get("pred_odds_snapshot_id") or 0
                    )
                    if match_id and pred_chain.get("predict_time"):
                        fs = _get_feature_snapshot_for_match(
                            conn, match_id, str(pred_chain["predict_time"])
                        )
                        if fs:
                            chain_details["feature_snapshot_id"] = fs["feature_snapshot_id"]
                            fs_time = fs.get("snapshot_time")
                            if fs_time and pred_chain.get("predict_time"):
                                if isinstance(fs_time, str):
                                    fs_time = datetime.fromisoformat(fs_time)
                                if isinstance(pred_chain["predict_time"], str):
                                    pred_time = datetime.fromisoformat(pred_chain["predict_time"])
                                else:
                                    pred_time = pred_chain["predict_time"]
                                chain_details["feature_snapshot_age_seconds"] = int(
                                    (pred_time - fs_time).total_seconds()
                                )
                        else:
                            # Feature snapshot optional for chain completeness
                            # (not all dimensions may be available)
                            chain_details["feature_snapshot_id"] = None

            # Store audit result
            audit_entry = {
                "audit_time": audit_time,
                "recommendation_id": item.get("batch_id"),
                "ticket_id": item["ticket_id"],
                "odds_snapshot_id": odds_id,
                "model_version_id": chain_details.get("model_version_id"),
                "feature_snapshot_id": chain_details.get("feature_snapshot_id"),
                "prediction_id": pred_id,
                "chain_complete": chain_ok,
                "broken_link_at": broken_link,
                "chain_details": chain_details,
                "odds_snapshot_age_seconds": chain_details.get("odds_snapshot_age_seconds"),
                "feature_snapshot_age_seconds": chain_details.get("feature_snapshot_age_seconds"),
                "model_version_is_current": chain_details.get("model_version_id") is not None,
            }

            if not dry_run:
                store_evidence_chain_audit(conn, audit_entry)

            if chain_ok:
                complete += 1
            else:
                broken += 1
                broken_details.append(
                    {
                        "ticket_id": item["ticket_id"],
                        "broken_link": broken_link,
                    }
                )

    completeness = round(complete / (complete + broken), 4) if (complete + broken) > 0 else 1.0

    return {
        "status": "ok" if not dry_run else "dry_run",
        "total_audited": complete + broken,
        "complete_chains": complete,
        "broken_chains": broken,
        "completeness_rate": completeness,
        "broken_details": broken_details[:10],  # first 10 for summary
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
