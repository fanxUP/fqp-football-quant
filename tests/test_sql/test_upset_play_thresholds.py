from pathlib import Path

MIGRATION = Path("sql/49_upset_play_specific_thresholds.sql")


def test_new_rule_version_uses_play_specific_thresholds():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "upset-v2" in source
    assert '"by_play"' in source
    assert '"bf"' in source
    assert '"zjq"' in source
    assert '"bqc"' in source
    assert "SET is_active = false" in source
