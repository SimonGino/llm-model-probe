"""Tests for /api/health and /api/settings."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llm_model_probe.api import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
