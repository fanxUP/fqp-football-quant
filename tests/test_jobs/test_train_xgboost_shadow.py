"""Regression tests for XGBoost shadow-training boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.jobs.train_xgboost_shadow import load_training_dataset


def test_training_loader_requires_pre_kickoff_settled_feature_rows() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []

    assert load_training_dataset(conn) is None
    query = cursor.execute.call_args.args[0]
    assert "fs.snapshot_time < m.kickoff_time" in query
    assert "r.result_status IN ('final', 'confirmed')" in query
