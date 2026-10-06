"""Pure, side-effect-free planner for startup recovery dry-runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RecoveryPolicy:
    task_code: str
    strategy: str
    cadence: timedelta | None
    reason: str


DEFAULT_POLICIES = (
    RecoveryPolicy("official_schedule", "latest_only", timedelta(minutes=30), "refresh current official facts"),
    RecoveryPolicy("current_odds", "latest_only", timedelta(minutes=1), "refresh current odds only"),
    RecoveryPolicy("build_feature_snapshots", "latest_only", timedelta(hours=6), "rebuild future-match features"),
    RecoveryPolicy("run_model_prediction", "latest_only", timedelta(minutes=30), "predict future matches only"),
    RecoveryPolicy("run_recommendation_candidate", "latest_only", timedelta(days=1), "honor daily decision guard"),
    RecoveryPolicy("daily_review", "each_window", timedelta(days=1), "rebuild missing business dates"),
    RecoveryPolicy("settle_tickets", "each_window", timedelta(hours=1), "settle from stored facts"),
    RecoveryPolicy("minute_odds", "mark_gap", None, "historical minute snapshots cannot be fabricated"),
    RecoveryPolicy("heavy_training", "skip", None, "avoid boot-time resource storm"),
)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _latest_only(
    policy: RecoveryPolicy,
    outage_end: datetime,
    last_success: datetime | None,
) -> dict:
    if last_success is not None and outage_end - last_success <= policy.cadence:  # type: ignore[operator]
        return {
            "task_code": policy.task_code,
            "strategy": policy.strategy,
            "windows": [],
            "execute": False,
            "reason": "already_fresh",
        }
    return {
        "task_code": policy.task_code,
        "strategy": policy.strategy,
        "windows": [None],
        "execute": True,
        "reason": policy.reason,
    }


def _each_window(
    policy: RecoveryPolicy,
    outage_start: datetime,
    outage_end: datetime,
    last_success: datetime | None,
) -> dict:
    cursor = last_success or outage_start - policy.cadence  # type: ignore[operator]
    windows: list[datetime] = []
    while cursor + policy.cadence <= outage_end:  # type: ignore[operator]
        cursor += policy.cadence  # type: ignore[operator]
        if cursor >= outage_start:
            windows.append(cursor)
    return {
        "task_code": policy.task_code,
        "strategy": policy.strategy,
        "windows": windows,
        "execute": bool(windows),
        "reason": policy.reason if windows else "no_missing_window",
    }


def build_recovery_plan(
    outage_start: datetime,
    outage_end: datetime,
    last_success_by_task: Mapping[str, datetime | None],
    policies: tuple[RecoveryPolicy, ...] = DEFAULT_POLICIES,
) -> list[dict]:
    """Build a deterministic plan; this function never writes or executes jobs."""
    _require_aware(outage_start, "outage_start")
    _require_aware(outage_end, "outage_end")
    if outage_end <= outage_start:
        raise ValueError("outage_end must be after outage_start")

    plan: list[dict] = []
    for policy in policies:
        last_success = last_success_by_task.get(policy.task_code)
        if last_success is not None:
            _require_aware(last_success, f"last_success_by_task[{policy.task_code}]")
        if policy.strategy == "latest_only":
            plan.append(_latest_only(policy, outage_end, last_success))
        elif policy.strategy == "each_window":
            plan.append(_each_window(policy, outage_start, outage_end, last_success))
        elif policy.strategy == "mark_gap":
            plan.append(
                {
                    "task_code": policy.task_code,
                    "strategy": policy.strategy,
                    "windows": [],
                    "execute": False,
                    "reason": policy.reason,
                    "gap": {"start": outage_start, "end": outage_end},
                }
            )
        elif policy.strategy == "skip":
            plan.append(
                {
                    "task_code": policy.task_code,
                    "strategy": policy.strategy,
                    "windows": [],
                    "execute": False,
                    "reason": policy.reason,
                }
            )
        else:
            raise ValueError(f"unsupported recovery strategy: {policy.strategy}")
    return plan
