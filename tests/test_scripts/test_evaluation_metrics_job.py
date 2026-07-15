from scripts import evaluation_metrics


class CaptureCursor:
    def __init__(self) -> None:
        self.query = ""

    def execute(self, query: str) -> None:
        self.query = " ".join(query.split())

    def fetchall(self) -> list[tuple]:
        return []


class CaptureConnection:
    def __init__(self) -> None:
        self.cursor_instance = CaptureCursor()

    def cursor(self) -> CaptureCursor:
        return self.cursor_instance


class DatabaseContext:
    def __init__(self, conn: CaptureConnection) -> None:
        self.conn = conn

    def __enter__(self) -> CaptureConnection:
        return self.conn

    def __exit__(self, *_args) -> None:
        return None


def test_evaluation_job_only_reads_pre_match_spf_predictions(monkeypatch) -> None:
    conn = CaptureConnection()
    monkeypatch.setattr(
        "apps.backend.src.db.get_db",
        lambda: DatabaseContext(conn),
    )

    result = evaluation_metrics.run()

    assert result["evaluated"] == 0
    assert "mp.predict_time < m.kickoff_time" in conn.cursor_instance.query
    assert "mp.play_type = 'spf'" in conn.cursor_instance.query
    assert "mp.option_code IN ('3', '1', '0')" in conn.cursor_instance.query
    assert "r.result_status IN ('final', 'confirmed')" in conn.cursor_instance.query
