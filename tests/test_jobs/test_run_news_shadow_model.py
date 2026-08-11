from pathlib import Path


def test_news_shadow_job_never_writes_formal_prediction_table() -> None:
    source = Path("scripts/news_shadow_storage.py").read_text()

    assert "INSERT INTO news_shadow_predictions" in source
    assert "INSERT INTO model_predictions" not in source
