from unittest.mock import MagicMock

from apps.backend.src.services.model_gateway import ModelGatewayError, ModelReply
from apps.backend.src.services.report_automation import maybe_generate_post_match_report


def test_automatic_report_does_not_call_model_when_automation_is_disabled(monkeypatch) -> None:
    invoke = MagicMock()
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.is_post_match_report_automation_enabled",
        lambda _conn: False,
    )
    monkeypatch.setattr("apps.backend.src.services.report_automation.invoke_agent_model", invoke)

    result = maybe_generate_post_match_report(
        object(), source_type="post_daily", source_ref="2026-08-09", title="日报", snapshot={}
    )

    assert result == {"status": "skipped", "reason": "automation_disabled"}
    invoke.assert_not_called()


def test_automatic_report_archives_one_enabled_call_with_source_reference(monkeypatch) -> None:
    archived = {"id": 9, "sourceType": "post_daily", "sourceRef": "2026-08-09"}
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.is_post_match_report_automation_enabled",
        lambda _conn: True,
    )
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.has_workspace_task_for_source",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.invoke_agent_model",
        lambda *_args: ModelReply("openai", "gpt-5-mini", "需人工核验"),
    )
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.create_workspace_task",
        lambda *_args, **_kwargs: archived,
    )
    audit = MagicMock()
    monkeypatch.setattr("apps.backend.src.services.report_automation.record_model_invocation", audit)

    result = maybe_generate_post_match_report(
        object(),
        source_type="post_daily",
        source_ref="2026-08-09",
        title="日报：2026-08-09",
        snapshot={"dailyReview": {"reviewDate": "2026-08-09"}},
    )

    assert result == {
        "status": "completed",
        "task": archived,
        "agentCode": "post_match_report_agent",
        "providerCode": "openai",
        "model": "gpt-5-mini",
    }
    assert audit.call_args.kwargs["status"] == "succeeded"


def test_automatic_report_failure_is_recorded_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.is_post_match_report_automation_enabled",
        lambda _conn: True,
    )
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.has_workspace_task_for_source",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "apps.backend.src.services.report_automation.invoke_agent_model",
        lambda *_args: (_ for _ in ()).throw(ModelGatewayError("模型不可用")),
    )
    audit = MagicMock()
    monkeypatch.setattr("apps.backend.src.services.report_automation.record_model_invocation", audit)

    result = maybe_generate_post_match_report(
        object(), source_type="post_weekly", source_ref="2026-08-03", title="周报", snapshot={}
    )

    assert result == {"status": "failed", "reason": "model_call_failed"}
    assert audit.call_args.kwargs["status"] == "failed"
