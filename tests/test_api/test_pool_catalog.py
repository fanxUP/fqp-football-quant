"""Four-game read catalog HTTP contract; all database access is isolated/mock."""

from contextlib import nullcontext
from datetime import date
from unittest.mock import MagicMock

import pytest

from apps.backend.src.routers import pool


@pytest.fixture
def catalog_runtime(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    return conn


def test_catalog_passes_typed_filters_and_starts_read_only_snapshot(
    client, catalog_runtime, monkeypatch
):
    reader = MagicMock(return_value={"issues": [], "total": 0, "limit": 20, "offset": 0})
    monkeypatch.setattr(pool, "read_pool_catalog", reader)
    response = client.get(
        "/api/pool/catalog?game_type=bqc6&issue_no=26001&date_from=2026-10-30&date_to=2026-10-31"
    )
    assert response.status_code == 200 and response.json()["total"] == 0
    reader.assert_called_once_with(
        catalog_runtime,
        game_type="bqc6",
        issue_no="26001",
        date_from=date(2026, 10, 30),
        date_to=date(2026, 10, 31),
        limit=20,
        offset=0,
    )
    assert any(
        "REPEATABLE READ READ ONLY" in call.args[0]
        for call in catalog_runtime.cursor.return_value.__enter__.return_value.execute.call_args_list
    )
    assert not catalog_runtime.commit.called


@pytest.mark.parametrize(
    "query",
    [
        "game_type=sf14",
        "game_type=other",
        "limit=0",
        "limit=51",
        "offset=-1",
        "offset=100001",
        "issue_no=",
        "issue_no=" + "a" * 65,
        "date_from=2026-02-30",
        "date_from=2026-11-01&date_to=2026-10-30",
        "date_to=9999-12-31",
    ],
)
def test_catalog_rejects_invalid_filters_before_database(client, catalog_runtime, query):
    response = client.get("/api/pool/catalog?" + query)
    assert response.status_code in (400, 422)
    assert not catalog_runtime.cursor.called


def test_catalog_detail_unknown_issue_is_404_not_fake_empty_issue(
    client, catalog_runtime, monkeypatch
):
    reader = MagicMock(return_value=None)
    monkeypatch.setattr(pool, "read_pool_catalog_issue", reader)
    response = client.get("/api/pool/catalog/42")
    assert response.status_code == 404
    reader.assert_called_once_with(catalog_runtime, 42)


def test_catalog_detail_keeps_pending_traditional_only_fixture(
    client, catalog_runtime, monkeypatch
):
    detail = {
        "issue": {"id": 42, "game_type": "jq4"},
        "fixtures": [
            {
                "match_order": 1,
                "fixture_id": None,
                "official_match_id": None,
                "identity_status": "pending",
            }
        ],
    }
    monkeypatch.setattr(pool, "read_pool_catalog_issue", lambda *_: detail)
    response = client.get("/api/pool/catalog/42")
    assert response.status_code == 200 and response.json() == detail
    assert not catalog_runtime.commit.called


@pytest.mark.parametrize("value", ["0", "-1", "9007199254740992", "not-an-id"])
def test_catalog_detail_validates_identifier(client, catalog_runtime, value):
    assert client.get("/api/pool/catalog/" + value).status_code == 422
    assert not catalog_runtime.cursor.called
