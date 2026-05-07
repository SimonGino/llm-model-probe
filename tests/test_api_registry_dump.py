"""Tests for GET /api/registry/dump."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seeded_store(isolated_home: Path) -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    s.insert_endpoint(Endpoint(
        id=new_endpoint_id(),
        name="alpha",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-real",
        mode="discover",
        models=["gpt-4o"],
        note="seed",
    ))
    return s


def test_dump_default_excludes_keys(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "llm-model-probe-registry"
    assert body["version"] == 1
    assert body["endpoints"][0]["name"] == "alpha"
    assert body["endpoints"][0]["api_key"] is None


def test_dump_include_keys_includes_keys(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump?include_keys=true")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoints"][0]["api_key"] == "sk-real"


def test_dump_sets_content_disposition(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "llm-model-probe-registry-" in cd
    assert ".json" in cd


def test_dump_requires_token_when_set(
    client: TestClient,
    seeded_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    r = client.get("/api/registry/dump")
    assert r.status_code == 401

    r2 = client.get(
        "/api/registry/dump",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r2.status_code == 200
