"""Shared pytest fixtures for FQP tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.backend.src.app import create_app


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient using the app factory."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_conn():
    """Create a MagicMock that simulates a psycopg2 connection with cursor.

    Returns (conn, cursor) tuple. The cursor is a MagicMock that can be
    configured with side_effect for specific test scenarios.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.description = []
    return conn, cursor
