"""Tests for real-ticket OCR upload and confirmed ticket saves."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.backend.src.routers import tickets


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ticket": None, "items": []},
        {"items": [None]},
        {"items": [{"match_id": 1, "option_code": "0", "sp_value": -1}]},
    ],
)
def test_confirmed_save_rejects_invalid_input_without_creating_a_ticket(client, monkeypatch, body):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(tickets, "get_db", lambda: conn)
    response = client.post("/api/real-tickets", json=body)
    assert response.status_code == 422
    conn.cursor.assert_not_called()
    conn.commit.assert_not_called()


def test_confirmed_ocr_save_keeps_response_and_image_metadata(client, monkeypatch):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [[42], [43]]
    monkeypatch.setattr(tickets, "get_db", lambda: conn)
    response = client.post(
        "/api/real-tickets",
        json={
            "ticket": {
                "ticket_image_url": "/uploads/tickets/ticket.jpg",
                "ocr_status": "recognized",
            },
            "items": [{"match_id": 1, "option_code": "0", "sp_value": 2.5}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ticket_id": 42, "item_count": 1}
    assert (
        cur.execute.call_args_list[0].args[1]["ticket_image_url"] == "/uploads/tickets/ticket.jpg"
    )
    assert cur.execute.call_args_list[0].args[1]["ocr_status"] == "recognized"
    conn.commit.assert_called_once()


def test_ocr_upload_persists_original_image(client, tmp_path):
    tickets.UPLOAD_ROOT = tmp_path

    with (
        patch("apps.backend.src.routers.tickets.process_ticket_image") as process_image,
        patch("apps.backend.src.routers.tickets.result_to_dict") as result_to_dict,
    ):
        process_image.return_value = object()
        result_to_dict.return_value = {
            "success": True,
            "ticket_no": "T001",
            "pass_type": "single",
            "multiple": 1,
            "total_amount": 2,
            "items": [],
            "raw_text": "",
            "ocr_engine": "mock",
            "confidence": 1,
            "warnings": [],
        }

        resp = client.post(
            "/api/tickets/ocr",
            files={"file": ("ticket sample.jpg", b"\xff\xd8\xffimage-bytes", "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticket_image_url"].startswith("/uploads/tickets/")
    stored = Path(tmp_path, "tickets", Path(data["ticket_image_url"]).name)
    assert stored.read_bytes() == b"\xff\xd8\xffimage-bytes"


def test_ocr_upload_rejects_fake_image_content(client):
    response = client.post(
        "/api/tickets/ocr",
        files={"file": ("ticket.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "不是有效" in response.json()["detail"]
