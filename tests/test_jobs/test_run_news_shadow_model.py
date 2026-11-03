from pathlib import Path


def test_news_shadow_job_never_writes_formal_prediction_table() -> None:
    source = Path("scripts/news_shadow_storage.py").read_text()

    assert "INSERT INTO news_shadow_predictions" in source
    assert "INSERT INTO model_predictions" not in source


def test_news_shadow_baseline_uses_feature_scoped_canonical_predictions() -> None:
    source = Path("scripts/news_shadow_storage.py").read_text()

    assert "model_prediction_latest_rows" not in source
    assert "canonical_prediction_rows_ctes(" in source
    assert 'match_scope="latest_feature"' in source
    assert "FROM canonical_prediction_rows" in source
