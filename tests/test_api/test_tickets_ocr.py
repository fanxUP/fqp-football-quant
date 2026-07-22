"""Tests for real-ticket OCR upload behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from apps.backend.src.routers import tickets


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
