"""Tests for /api/health and /api/settings."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llm_model_probe.api import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_settings_endpoint(isolated_home) -> None:
    client = TestClient(app)
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["concurrency"] >= 1
    assert "exclude_patterns" in body


def test_no_api_key_leak_in_any_response(
    isolated_home, monkeypatch
) -> None:
    """Regression: api_key plaintext must never appear in any response."""
    from llm_model_probe import api as api_mod
    from llm_model_probe.models import ModelResult
    from llm_model_probe.probe import ProbeOutcome
    from datetime import datetime

    async def fake_probe(self, ep, *, allow_partial=False):
        return ProbeOutcome(
            list_error=None,
            new_results=[
                ModelResult(ep.id, "m", "specified", "available", 1,
                            last_tested_at=datetime.now())
            ],
            skipped=[],
        )

    monkeypatch.setattr(api_mod.ProbeRunner, "probe_endpoint", fake_probe)

    client = TestClient(app)
    raw_key = "sk-SECRET-9999-DO-NOT-LEAK"
    client.post(
        "/api/endpoints",
        json={
            "name": "leakcheck",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "models": ["m"],
        },
    )
    payloads = [
        client.get("/api/endpoints").text,
        client.get("/api/endpoints/leakcheck").text,
        client.post("/api/endpoints/leakcheck/retest").text,
    ]
    for p in payloads:
        assert raw_key not in p, "api_key plaintext leaked!"


def test_no_api_key_leak_in_probe_model_response(
    isolated_home, monkeypatch
) -> None:
    """Regression: api_key plaintext must never appear in probe-model output."""
    from llm_model_probe.providers import OpenAIProvider, ProbeResult

    async def fake_list_models(self):  # noqa: ARG001
        return ["m"]

    monkeypatch.setattr(OpenAIProvider, "list_models", fake_list_models)

    async def fake_probe(self, model, prompt, max_tokens):  # noqa: ARG001
        return ProbeResult(
            endpoint=self.name,
            sdk=self.sdk,
            model=model,
            available=True,
            latency_ms=1,
        )

    monkeypatch.setattr(OpenAIProvider, "probe", fake_probe)

    client = TestClient(app)
    raw_key = "sk-LEAK-CHECK-PROBE-MODEL-9999"
    create = client.post(
        "/api/endpoints",
        json={
            "name": "leakcheck-pm",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": raw_key,
            "no_probe": True,
        },
    )
    ep_id = create.json()["id"]
    pm = client.post(
        f"/api/endpoints/{ep_id}/probe-model", json={"model": "m"}
    ).text
    assert raw_key not in pm
