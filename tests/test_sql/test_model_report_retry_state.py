from pathlib import Path


def test_report_model_retry_state_is_bounded_and_auditable() -> None:
    sql = Path("sql/101_model_report_retry_state.sql").read_text()

    assert "model_report_status" in sql
    assert "model_report_attempt_count" in sql
    assert "model_report_last_attempt_at" in sql
    assert "model_report_error_code" in sql
    assert "model_report_attempt_count >= 0" in sql
