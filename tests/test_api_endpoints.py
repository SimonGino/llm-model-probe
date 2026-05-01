"""Tests for /api/endpoints CRUD."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, ModelResult, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _seed_endpoint(store: EndpointStore, name: str = "alpha") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-1234567890wxyz",
        mode="discover",
        models=[],
        note="seeded",
    )
    store.insert_endpoint(ep)
    store.replace_model_results(ep.id, [
        ModelResult(ep.id, "gpt-4", "discovered", "available", 100,
                    response_preview="hi", last_tested_at=datetime.now()),
        ModelResult(ep.id, "gpt-3.5", "discovered", "failed", 50,
                    error_type="AuthError", error_message="bad",
                    last_tested_at=datetime.now()),
    ])
    return ep


def test_list_endpoints_empty(client: TestClient) -> None:
    r = client.get("/api/endpoints")
    assert r.status_code == 200
    assert r.json() == []


def test_list_endpoints_with_summary(
    client: TestClient, seed_store: EndpointStore
) -> None:
    _seed_endpoint(seed_store, "alpha")
    r = client.get("/api/endpoints")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    item = body[0]
    assert item["name"] == "alpha"
    assert item["available"] == 1
    assert item["failed"] == 1
    assert "api_key" not in item


def test_get_endpoint_detail_by_name(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "beta")
    r = client.get(f"/api/endpoints/beta")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ep.id
    assert body["api_key_masked"] == "sk-1...wxyz"
    assert "api_key" not in body
    assert {res["model_id"] for res in body["results"]} == {"gpt-4", "gpt-3.5"}


def test_get_endpoint_detail_by_id(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "gamma")
    r = client.get(f"/api/endpoints/{ep.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "gamma"


def test_get_endpoint_detail_not_found(client: TestClient) -> None:
    r = client.get("/api/endpoints/nope")
    assert r.status_code == 404
