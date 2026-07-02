"""Tests for health check and root endpoints."""
from __future__ import annotations


class TestHealth:
    def test_health_endpoint_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "fqp-from-scratch"

    def test_root_returns_name_and_boundary(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "FQP From Scratch"
        assert "boundary" in data
