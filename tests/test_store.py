"""Tests for EndpointStore SQLite layer."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from llm_model_probe.models import Endpoint, ModelResult, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def store(isolated_home: Path) -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _ep(name: str = "test", mode: str = "discover", models: list[str] | None = None) -> Endpoint:
    return Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test123",
        mode=mode,  # type: ignore[arg-type]
        models=models or [],
        note="",
    )


def test_insert_and_get_by_name(store: EndpointStore) -> None:
    ep = _ep("alpha")
    store.insert_endpoint(ep)
    got = store.get_endpoint("alpha")
    assert got is not None
    assert got.id == ep.id
    assert got.sdk == "openai"
    assert got.mode == "discover"


def test_get_by_id_and_name(store: EndpointStore) -> None:
    ep = _ep("beta")
    store.insert_endpoint(ep)
    by_id = store.get_endpoint(ep.id)
    by_name = store.get_endpoint("beta")
    assert by_id is not None and by_name is not None
    assert by_id.id == by_name.id


def test_insert_unique_name(store: EndpointStore) -> None:
    store.insert_endpoint(_ep("dup"))
    with pytest.raises(ValueError):
        store.insert_endpoint(_ep("dup"))


def test_replace_model_results(store: EndpointStore) -> None:
    ep = _ep("gamma")
    store.insert_endpoint(ep)
    now = datetime.now()
    results_v1 = [
        ModelResult(ep.id, "m1", "discovered", "available", 100, last_tested_at=now),
        ModelResult(ep.id, "m2", "discovered", "failed", 50, error_type="X",
                    error_message="boom", last_tested_at=now),
    ]
    store.replace_model_results(ep.id, results_v1)
    got = store.list_model_results(ep.id)
    assert {r.model_id for r in got} == {"m1", "m2"}

    # Replace with new set — old rows gone
    results_v2 = [
        ModelResult(ep.id, "m3", "discovered", "available", 80, last_tested_at=now),
    ]
    store.replace_model_results(ep.id, results_v2)
    got = store.list_model_results(ep.id)
    assert {r.model_id for r in got} == {"m3"}


def test_delete_cascades(store: EndpointStore) -> None:
    ep = _ep("delta")
    store.insert_endpoint(ep)
    store.replace_model_results(ep.id, [
        ModelResult(ep.id, "m1", "specified", "available", 10, last_tested_at=datetime.now())
    ])
    store.delete_endpoint(ep.id)
    assert store.get_endpoint("delta") is None
    assert store.list_model_results(ep.id) == []


def test_set_list_error(store: EndpointStore) -> None:
    ep = _ep("epsilon")
    store.insert_endpoint(ep)
    store.set_list_error(ep.id, "AuthError: bad key")
    got = store.get_endpoint("epsilon")
    assert got is not None and got.list_error == "AuthError: bad key"
    store.set_list_error(ep.id, None)
    got = store.get_endpoint("epsilon")
    assert got is not None and got.list_error is None


def test_list_endpoints(store: EndpointStore) -> None:
    store.insert_endpoint(_ep("a"))
    store.insert_endpoint(_ep("b"))
    rows = store.list_endpoints()
    names = sorted(ep.name for ep in rows)
    assert names == ["a", "b"]


def test_last_tested_at(store: EndpointStore) -> None:
    ep = _ep("zeta")
    store.insert_endpoint(ep)
    assert store.last_tested_at(ep.id) is None
    now = datetime.now().replace(microsecond=0)
    store.replace_model_results(ep.id, [
        ModelResult(ep.id, "m1", "discovered", "available", 10, last_tested_at=now),
        ModelResult(ep.id, "m2", "discovered", "failed", 10, last_tested_at=now - timedelta(seconds=5)),
    ])
    latest = store.last_tested_at(ep.id)
    assert latest is not None
    assert abs((latest - now).total_seconds()) < 1
