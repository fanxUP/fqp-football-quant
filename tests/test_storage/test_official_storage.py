from unittest.mock import MagicMock

from scripts.official_storage import record_official_collection_status


def _mock_conn(fetchone=None):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = fetchone
    return conn, cur


def test_record_official_collection_status_writes_source_artifact_hash():
    conn, cur = _mock_conn(fetchone=[42])

    row_id = record_official_collection_status(
        conn,
        business_date="2026-07-01",
        crawl_type="results",
        source_name="sporttery",
        status="blocked",
        source_url="https://www.sporttery.cn/jc/zqsgkj/",
        source_artifact_path="/tmp/result.html",
        source_artifact_hash="abc123",
        error_message="567 Restricted Access",
    )

    assert row_id == 42
    params = cur.execute.call_args[0][1]
    assert params["business_date"] == "2026-07-01"
    assert params["status"] == "blocked"
    assert params["source_artifact_hash"] == "abc123"
    assert "567" in params["error_message"]
    conn.commit.assert_called_once()
