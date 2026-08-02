from unittest.mock import MagicMock, patch

from scripts.jobs import tag_errors


def test_tag_errors_uses_atomic_upsert_for_concurrent_runs():
    conn = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = conn
    select_cursor = MagicMock()
    write_cursor = MagicMock()
    conn.cursor.return_value.__enter__.side_effect = [select_cursor, write_cursor]
    select_cursor.fetchall.return_value = [
        (1, 2, False, -1, 3, 4, 5, "3", 0.6, 0.45, 1.2, "0", 0, 1)
    ]

    with patch.object(tag_errors, "get_db", return_value=context):
        result = tag_errors.run()

    query = " ".join(write_cursor.execute.call_args.args[0].split())
    params = write_cursor.execute.call_args.args[1]
    assert "ON CONFLICT (prediction_id) WHERE prediction_id IS NOT NULL DO UPDATE" in query
    assert params["tag"] == "赔率过热、模型概率偏高"
    assert result["tagged"] == 1
