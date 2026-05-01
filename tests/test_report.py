"""Tests for Reporter rendering helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from llm_model_probe.models import Endpoint, ModelResult
from llm_model_probe.report import (
    EndpointSnapshot,
    mask_api_key,
    relative_time,
    render_json,
    render_markdown,
)


def _snap(name: str = "test") -> EndpointSnapshot:
    ep = Endpoint(
        id="ep_aaa",
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-1234567890wxyz",
        mode="discover",
        models=[],
        note="hello",
        list_error=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    results = [
        ModelResult(ep.id, "gpt-4", "discovered", "available", 120,
                    response_preview="hi there", last_tested_at=datetime.now()),
        ModelResult(ep.id, "gpt-3.5", "discovered", "failed", 90,
                    error_type="AuthError", error_message="bad key",
                    last_tested_at=datetime.now()),
    ]
    return EndpointSnapshot(endpoint=ep, results=results)


def test_mask_api_key_basic() -> None:
    assert mask_api_key("sk-1234567890wxyz") == "sk-1...wxyz"
    assert mask_api_key("short") == "*****"


def test_relative_time_formats() -> None:
    now = datetime.now()
    assert relative_time(now - timedelta(seconds=5)) == "just now"
    assert "m ago" in relative_time(now - timedelta(minutes=3))
    assert "h ago" in relative_time(now - timedelta(hours=2))
    assert "d ago" in relative_time(now - timedelta(days=2))


def test_render_markdown_contains_models() -> None:
    md = render_markdown([_snap("alpha")])
    assert "# LLM Model Probe" in md
    assert "alpha" in md
    assert "gpt-4" in md
    assert "AuthError" in md


def test_render_json_roundtrips() -> None:
    out = render_json([_snap("alpha")])
    data = json.loads(out)
    assert data["endpoints"][0]["name"] == "alpha"
    assert any(r["model"] == "gpt-4" for r in data["endpoints"][0]["results"])
