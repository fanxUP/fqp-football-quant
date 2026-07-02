"""Human review gate for high-risk Codex agent tasks."""

HIGH_RISK_TYPES = {
    "recommendation_publish",
    "bankroll_rule_change",
    "production_migration",
    "real_ticket_edit",
    "model_activation",
}


def need_review(task_type: str, risk_level: str) -> bool:
    return risk_level in {"L4", "L5"} or task_type in HIGH_RISK_TYPES


def assert_reviewed(task_type: str, risk_level: str, review_status: str | None) -> None:
    if need_review(task_type, risk_level) and review_status != "approved":
        raise PermissionError(f"Human review required for {task_type} / {risk_level}")
