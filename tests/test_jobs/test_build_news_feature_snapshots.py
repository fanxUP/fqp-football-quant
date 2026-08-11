from datetime import UTC, datetime

from scripts.jobs.build_news_feature_snapshots import due_snapshot_labels


def test_due_labels_include_only_cutoffs_that_have_passed() -> None:
    kickoff = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    now = datetime(2026, 8, 12, 6, 30, tzinfo=UTC)

    assert due_snapshot_labels(kickoff, now) == ["T24H", "T6H"]


def test_post_match_label_waits_for_evidence_window() -> None:
    kickoff = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    assert "POST120" not in due_snapshot_labels(kickoff, datetime(2026, 8, 12, 13, 59, tzinfo=UTC))
    assert "POST120" in due_snapshot_labels(kickoff, datetime(2026, 8, 12, 14, 0, tzinfo=UTC))
