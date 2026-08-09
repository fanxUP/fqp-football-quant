from pathlib import Path


def test_probability_calibration_profiles_are_separate_from_prediction_facts() -> None:
    sql = Path("sql/75_add_probability_calibration_profiles.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS probability_calibration_profiles" in sql
    assert "model_predictions" not in sql
    assert "GRANT SELECT, INSERT, UPDATE" in sql
