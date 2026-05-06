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


def test_create_no_probe_discover_populates_models(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """no_probe=true in discover mode should call list_models() and persist
    the result onto endpoints.models — without probing."""
    from llm_model_probe.providers import OpenAIProvider

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4", "gpt-3.5", "text-embedding-3"]

    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "discover-only",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa1111bbbb2222",
            "no_probe": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "discover"
    assert body["models"] == ["gpt-4", "gpt-3.5", "text-embedding-3"]
    assert body["results"] == []  # no probing
    assert body["total_models"] == 3
    # text-embedding-3 should land in excluded_by_filter
    assert "text-embedding-3" in body["excluded_by_filter"]
    assert "gpt-4" not in body["excluded_by_filter"]


def test_create_no_probe_discover_list_error(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    async def fail_list_models(self):  # noqa: ARG001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(OpenAIProvider, "list_models", fail_list_models)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "broken-discover",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa1111bbbb2222",
            "no_probe": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["models"] == []
    assert body["list_error"] is not None
    assert "kaboom" in body["list_error"]
    assert body["total_models"] == 0


def test_endpoint_summary_includes_total_models(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """total_models should reflect endpoints.models length."""
    ep2 = Endpoint(
        id=new_endpoint_id(),
        name="counted",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-1234567890aaaa",
        mode="specified",
        models=["a", "b", "c"],
        note="",
    )
    seed_store.insert_endpoint(ep2)
    r = client.get("/api/endpoints")
    item = next(x for x in r.json() if x["name"] == "counted")
    assert item["total_models"] == 3


def test_probe_model_writes_result(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /probe-model probes one model and stores its row."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4"]

    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    create = client.post(
        "/api/endpoints",
        json={
            "name": "probe-test",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa1111bbbb2222",
            "no_probe": True,
        },
    )
    assert create.status_code == 201
    ep_id = create.json()["id"]

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=True,
            latency_ms=42,
            response_preview="hello",
        )

    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    r = client.post(
        f"/api/endpoints/{ep_id}/probe-model",
        json={"model": "gpt-4"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_id"] == "gpt-4"
    assert body["status"] == "available"
    assert body["latency_ms"] == 42

    detail = client.get(f"/api/endpoints/{ep_id}").json()
    assert len(detail["results"]) == 1
    assert detail["results"][0]["model_id"] == "gpt-4"
    assert detail["available"] == 1


def test_probe_model_unknown_model_400(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probing a model not in endpoint.models is rejected."""
    from llm_model_probe.providers import OpenAIProvider

    async def fake_list_models(self):  # noqa: ARG001
        return ["gpt-4"]

    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    create = client.post(
        "/api/endpoints",
        json={
            "name": "scope-test",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa1111bbbb2222",
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]

    r = client.post(
        f"/api/endpoints/{ep_id}/probe-model",
        json={"model": "not-listed"},
    )
    assert r.status_code == 400


def test_probe_model_endpoint_not_found_404(client: TestClient) -> None:
    r = client.post(
        "/api/endpoints/ep_zzzzzz/probe-model",
        json={"model": "anything"},
    )
    assert r.status_code == 404


def test_probe_model_replaces_prior_result(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second probe for the same model overwrites the first row."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    async def fake_list_models(self):  # noqa: ARG001
        return ["m1"]

    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    create = client.post(
        "/api/endpoints",
        json={
            "name": "replay",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-aaaa1111bbbb2222",
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]

    call_count = {"n": 0}

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        call_count["n"] += 1
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=call_count["n"] == 2,
            latency_ms=10 * call_count["n"],
            error_type=None if call_count["n"] == 2 else "X",
            error_message=None if call_count["n"] == 2 else "fail",
        )

    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    r1 = client.post(
        f"/api/endpoints/{ep_id}/probe-model", json={"model": "m1"}
    ).json()
    assert r1["status"] == "failed"
    r2 = client.post(
        f"/api/endpoints/{ep_id}/probe-model", json={"model": "m1"}
    ).json()
    assert r2["status"] == "available"
    detail = client.get(f"/api/endpoints/{ep_id}").json()
    assert len(detail["results"]) == 1
    assert detail["results"][0]["status"] == "available"


def test_create_with_tags_persists(
    client: TestClient, isolated_home: Path
) -> None:
    r = client.post(
        "/api/endpoints",
        json={
            "name": "tagged",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1234567890aaaa",
            "models": ["m"],
            "tags": ["bob", "trial"],
            "no_probe": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tags"] == ["bob", "trial"]


def test_create_default_tags_empty(
    client: TestClient, isolated_home: Path
) -> None:
    r = client.post(
        "/api/endpoints",
        json={
            "name": "notags",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1234567890aaaa",
            "models": ["m"],
            "no_probe": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["tags"] == []


def test_summary_includes_tags(
    client: TestClient, isolated_home: Path
) -> None:
    """list 接口也要返回 tags（不是只 detail 才有）。"""
    client.post(
        "/api/endpoints",
        json={
            "name": "in-summary",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1234567890aaaa",
            "models": ["m"],
            "tags": ["a", "b"],
            "no_probe": True,
        },
    )
    items = client.get("/api/endpoints").json()
    item = next(x for x in items if x["name"] == "in-summary")
    assert item["tags"] == ["a", "b"]


def test_set_tags_replaces(
    client: TestClient, isolated_home: Path
) -> None:
    create = client.post(
        "/api/endpoints",
        json={
            "name": "rep",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1234567890aaaa",
            "models": ["m"],
            "tags": ["old"],
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]

    r = client.put(
        f"/api/endpoints/{ep_id}/tags",
        json={"tags": ["new1", "new2", "  new1  ", "", "new3"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tags"] == ["new1", "new2", "new3"]


def test_set_tags_unknown_endpoint_404(client: TestClient) -> None:
    r = client.put(
        "/api/endpoints/ep_zzzzzz/tags",
        json={"tags": ["x"]},
    )
    assert r.status_code == 404


def test_get_api_key_returns_full_plaintext(
    client: TestClient, isolated_home: Path
) -> None:
    """The dedicated endpoint returns the full plaintext key."""
    raw_key = "sk-FULL-PLAINTEXT-1234567890"
    create = client.post(
        "/api/endpoints",
        json={
            "name": "fullkey",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]
    r = client.get(f"/api/endpoints/{ep_id}/api-key")
    assert r.status_code == 200, r.text
    assert r.json() == {"api_key": raw_key}


def test_get_api_key_unknown_endpoint_404(client: TestClient) -> None:
    r = client.get("/api/endpoints/ep_zzzzzz/api-key")
    assert r.status_code == 404


def test_detail_still_masks_api_key(
    client: TestClient, isolated_home: Path
) -> None:
    """Regression: detail endpoint must NOT return the plaintext key
    just because the dedicated /api-key endpoint exists."""
    raw_key = "sk-MUST-NOT-LEAK-IN-DETAIL-1234"
    create = client.post(
        "/api/endpoints",
        json={
            "name": "mask-test",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]
    detail_text = client.get(f"/api/endpoints/{ep_id}").text
    assert raw_key not in detail_text
    detail_json = client.get(f"/api/endpoints/{ep_id}").json()
    assert "api_key" not in detail_json
    assert detail_json["api_key_masked"].startswith("sk-M")
    assert detail_json["api_key_masked"].endswith("1234")


def test_create_endpoint_normalizes_base_url(
    client: TestClient,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/endpoints strips known completion-endpoint suffixes."""
    # Stub list_models so create doesn't hit the network
    from llm_model_probe.providers import OpenAIProvider

    async def _stub_list_models(self):  # noqa: ARG001
        return ["gpt-4"]

    monkeypatch.setattr(OpenAIProvider, "list_models", _stub_list_models)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "zhipu",
            "sdk": "openai",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "api_key": "k",
            "no_probe": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
