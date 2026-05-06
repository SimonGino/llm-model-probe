"""Tests for /api/settings/parser GET + PUT."""
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
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _seed_ep(store: EndpointStore, models: list[str]) -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name="parser-host",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test1234567890",
        mode="discover",
        models=models,
    )
    store.insert_endpoint(ep)
    return ep


def test_get_returns_nulls_when_unset(client: TestClient) -> None:
    r = client.get("/api/settings/parser")
    assert r.status_code == 200
    assert r.json() == {"endpoint_id": None, "model_id": None}


def test_put_then_get_roundtrip(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["gpt-4o-mini", "gpt-4o"])
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "gpt-4o-mini"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"endpoint_id": ep.id, "model_id": "gpt-4o-mini"}

    g = client.get("/api/settings/parser").json()
    assert g == {"endpoint_id": ep.id, "model_id": "gpt-4o-mini"}


def test_put_endpoint_not_found_400(client: TestClient) -> None:
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": "ep_zzzzzz", "model_id": "x"},
    )
    assert r.status_code == 400


def test_put_model_not_in_endpoint_400(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["gpt-4o-mini"])
    r = client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "not-listed"},
    )
    assert r.status_code == 400


def test_get_auto_recovers_when_endpoint_deleted(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_ep(seed_store, ["m"])
    client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "m"},
    )
    seed_store.delete_endpoint(ep.id)
    r = client.get("/api/settings/parser")
    assert r.status_code == 200
    assert r.json() == {"endpoint_id": None, "model_id": None}


def test_get_auto_recovers_when_model_dropped(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """If rediscover removed the model, GET must report null/null."""
    from llm_model_probe.api import _persist_models

    ep = _seed_ep(seed_store, ["m1", "m2"])
    client.put(
        "/api/settings/parser",
        json={"endpoint_id": ep.id, "model_id": "m2"},
    )
    _persist_models(seed_store, ep.id, ["m1"])  # m2 is now gone
    r = client.get("/api/settings/parser")
    assert r.json() == {"endpoint_id": None, "model_id": None}
