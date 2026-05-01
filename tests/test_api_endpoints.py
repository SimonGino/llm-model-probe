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


def test_create_no_probe(client: TestClient, isolated_home: Path) -> None:
    payload = {
        "name": "delta",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-1111222233334444",
        "models": ["gpt-4o"],
        "note": "test",
        "no_probe": True,
    }
    r = client.post("/api/endpoints", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "delta"
    assert body["mode"] == "specified"
    assert "api_key" not in body
    assert body["api_key_masked"].endswith("4444")


def test_create_duplicate_name_409(
    client: TestClient, isolated_home: Path
) -> None:
    payload = {
        "name": "dup",
        "sdk": "openai",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-1234567890aaaa",
        "no_probe": True,
    }
    assert client.post("/api/endpoints", json=payload).status_code == 201
    r = client.post("/api/endpoints", json=payload)
    assert r.status_code == 409


def test_create_invalid_sdk_422(
    client: TestClient, isolated_home: Path
) -> None:
    r = client.post(
        "/api/endpoints",
        json={
            "name": "bad",
            "sdk": "cohere",
            "base_url": "https://x/v1",
            "api_key": "sk-x",
        },
    )
    assert r.status_code == 422


def test_create_with_probe_uses_runner(
    client: TestClient, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke: when no_probe=False the API calls ProbeRunner."""
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "fake-model", "specified", "available", 42,
                            response_preview="hi", last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "probed",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa11112222bbbb",
            "models": ["fake-model"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["available"] == 1
    assert body["results"][0]["model_id"] == "fake-model"


def test_delete_endpoint(client: TestClient, seed_store: EndpointStore) -> None:
    ep = _seed_endpoint(seed_store, "to-delete")
    r = client.delete(f"/api/endpoints/{ep.id}")
    assert r.status_code == 204
    assert client.get(f"/api/endpoints/{ep.id}").status_code == 404


def test_delete_not_found(client: TestClient) -> None:
    assert client.delete("/api/endpoints/nope").status_code == 404


def test_retest_single(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    ep = _seed_endpoint(seed_store, "epsilon")

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "new-model", "discovered", "available", 9,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post(f"/api/endpoints/{ep.id}/retest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(res["model_id"] == "new-model" for res in body["results"])


def test_retest_all(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome

    _seed_endpoint(seed_store, "ep-a")
    _seed_endpoint(seed_store, "ep-b")

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "m", "discovered", "available", 1,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    r = client.post("/api/retest-all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retested"] == 2
