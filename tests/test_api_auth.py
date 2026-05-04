"""Authentication middleware tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app


def test_no_token_env_means_no_auth_required(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/api/endpoints")
    assert r.status_code == 200


def test_token_set_blocks_unauthenticated(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/endpoints")
    assert r.status_code == 401


def test_token_set_allows_correct_bearer(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


def test_token_set_rejects_wrong_bearer(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_token_set_rejects_missing_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/endpoints",
        headers={"Authorization": "s3cret"},
    )
    assert r.status_code == 401


def test_health_no_auth_even_with_token_set(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """/api/health is exempt - reverse proxy health check needs it."""
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_non_api_path_no_auth_even_with_token_set(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Static files (HTML/JS) must be reachable so login page can load."""
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/")
    # No static mount in test env, so 404 is fine - just must NOT be 401
    assert r.status_code != 401


def test_auth_check_with_valid_token(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get(
        "/api/auth/check",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_auth_check_without_token(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    client = TestClient(app)
    r = client.get("/api/auth/check")
    assert r.status_code == 401


def test_auth_check_when_disabled(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Auth disabled = always returns ok (frontend uses this to decide
    whether to skip the login screen)."""
    monkeypatch.delenv("LLM_MODEL_PROBE_TOKEN", raising=False)
    client = TestClient(app)
    r = client.get("/api/auth/check")
    assert r.status_code == 200
