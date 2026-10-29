from unittest.mock import MagicMock, Mock

import pytest

from scripts.jobs import train_feature_explanation as job


@pytest.fixture
def dependencies(monkeypatch):
    start, finish, database, train = Mock(return_value=7), Mock(), MagicMock(), Mock()
    monkeypatch.setattr(job, "start_tracked_job", start)
    monkeypatch.setattr(job, "finish_tracked_job", finish)
    monkeypatch.setattr(job, "get_db", database)
    monkeypatch.setattr(job, "train_if_needed", train)
    return start, finish, database, train


def test_dry_run_has_no_audit_database_or_training_side_effect(dependencies):
    assert job.run(dry_run=True)["status"] == "dry_run"
    for dependency in dependencies:
        dependency.assert_not_called()


def test_missing_audit_id_prevents_training(dependencies):
    start, finish, database, train = dependencies
    start.return_value = None
    with pytest.raises(RuntimeError, match="audit"):
        job.run()
    database.assert_not_called()
    train.assert_not_called()
    finish.assert_not_called()


@pytest.mark.parametrize(
    "result,terminal",
    [
        ({"status": "ok", "artifact_id": "fixture"}, "ok"),
        ({"status": "skipped", "reason": "training_in_progress"}, "skipped"),
        ({"status": "error", "error": "native runtime failure"}, "failed"),
        ({"status": "error", "reason": "insufficient_data", "error": "需要100场"}, "skipped"),
        ({"status": "error", "reason": "missing_features", "error": "缺少特征"}, "skipped"),
        ({"status": "error", "reason": "insufficient_classes", "error": "缺少类别"}, "skipped"),
    ],
)
def test_trainer_records_real_result_exactly_once(dependencies, result, terminal):
    start, finish, database, train = dependencies
    train.return_value = result
    returned = job.run()
    start.assert_called_once_with(
        "train_feature_explanation", "model_agent", {"scope": "explanation_only"}
    )
    train.assert_called_once_with(database.return_value.__enter__.return_value, force=True)
    assert finish.call_count == 1
    assert finish.call_args.args[:2] == (7, terminal)
    assert returned["status"] == ("skipped" if terminal == "skipped" else result["status"])
    if terminal == "failed":
        assert finish.call_args.kwargs["error"] == "native runtime failure"


def test_unhandled_exception_is_audited_and_not_reported_as_completed(dependencies):
    _, finish, _, train = dependencies
    train.side_effect = OSError("artifact is read-only")
    with pytest.raises(OSError):
        job.run()
    finish.assert_called_once_with(7, "failed", error="artifact is read-only")
