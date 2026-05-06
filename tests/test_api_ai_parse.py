"""Tests for POST /api/ai-parse."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.providers import CompleteResult
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seed_store(isolated_home: Path) -> EndpointStore:
    store = EndpointStore()
    store.init_schema()
    return store


def _setup_parser(store: EndpointStore, model: str = "gpt-4o-mini") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name="parser-host",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test1234567890",
        mode="discover",
        models=[model],
    )
    store.insert_endpoint(ep)
    store.set_setting("parser.endpoint_id", ep.id)
    store.set_setting("parser.model_id", model)
    return ep


def test_412_when_no_default_parser(client: TestClient) -> None:
    r = client.post("/api/ai-parse", json={"blob": "anything"})
    assert r.status_code == 412


def test_success_full_extraction(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text=(
                '{"base_url":"https://x.example.com/v1",'
                '"api_key":"sk-extracted","sdk":"openai","name":"Bob GLM"}'
            ),
            latency_ms=120,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post(
        "/api/ai-parse",
        json={"blob": "Bob said use https://x.example.com/v1 with sk-extracted"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_url"] == "https://x.example.com/v1"
    assert body["api_key"] == "sk-extracted"
    assert body["sdk"] == "openai"
    assert body["name"] == "Bob GLM"
    assert body["confidence"] == 1.0
    assert body["latency_ms"] == 120


def test_partial_extraction_confidence_half(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text='{"base_url":"https://x/v1","api_key":null,"sdk":null,"name":null}',
            latency_ms=88,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://x/v1"
    assert body["api_key"] is None
    assert body["confidence"] == 0.5


def test_unparseable_response_confidence_zero(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(text="I don't know what you mean.", latency_ms=12)

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == 0.0
    assert body["base_url"] is None
    assert body["api_key"] is None


def test_extracts_first_json_block_when_wrapped_in_prose(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some models return ```json\\n{...}\\n``` instead of bare JSON."""
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        return CompleteResult(
            text=(
                "Sure! Here you go:\n```json\n"
                '{"base_url":"https://y/v1","api_key":"sk-y",'
                '"sdk":"openai","name":"y"}\n```\nDone."'
            ),
            latency_ms=200,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://y/v1"
    assert body["api_key"] == "sk-y"
    assert body["confidence"] == 1.0


def test_provider_error_502(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        raise TimeoutError("timed out talking to upstream")

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    r = client.post("/api/ai-parse", json={"blob": "X"})
    assert r.status_code == 502
    body = r.json()
    assert "TimeoutError" in body["detail"]


def test_blob_truncated_before_prompt(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm_model_probe.parser_prompt import MAX_BLOB_CHARS
    from llm_model_probe.providers import OpenAIProvider

    _setup_parser(seed_store)
    seen_prompt: dict[str, str] = {}

    async def fake_complete(self, model, prompt, max_tokens):  # noqa: ARG001
        seen_prompt["p"] = prompt
        return CompleteResult(
            text='{"base_url":null,"api_key":null,"sdk":null,"name":null}',
            latency_ms=10,
        )

    monkeypatch.setattr(OpenAIProvider, "complete", fake_complete)

    big = "X" * (MAX_BLOB_CHARS + 1000)
    r = client.post("/api/ai-parse", json={"blob": big})
    assert r.status_code == 200
    assert "[truncated]" in seen_prompt["p"]
    assert seen_prompt["p"].count("X") == MAX_BLOB_CHARS
