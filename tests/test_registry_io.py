"""Tests for registry_io.dump_endpoints / load_endpoints."""
from __future__ import annotations

from datetime import datetime

from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.registry_io import (
    SCHEMA_KIND,
    SCHEMA_VERSION,
    dump_endpoints,
)


def _ep(
    name: str = "alpha",
    *,
    api_key: str = "sk-secret",
    models: list[str] | None = None,
    tags: list[str] | None = None,
    mode: str = "discover",
) -> Endpoint:
    return Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key=api_key,
        mode=mode,  # type: ignore[arg-type]
        models=models or ["gpt-4o"],
        note="seed",
        tags=tags or [],
        created_at=datetime(2026, 5, 1, 10, 0, 0),
        updated_at=datetime(2026, 5, 6, 14, 22, 11),
    )


def test_dump_envelope_shape_default_excludes_keys() -> None:
    eps = [_ep("alpha", api_key="sk-real")]
    fixed = datetime(2026, 5, 7, 12, 34, 56)

    out = dump_endpoints(eps, include_keys=False, now=fixed)

    assert out["kind"] == SCHEMA_KIND
    assert out["version"] == SCHEMA_VERSION
    assert out["exported_at"] == "2026-05-07T12:34:56"
    assert len(out["endpoints"]) == 1
    row = out["endpoints"][0]
    assert row["name"] == "alpha"
    assert row["api_key"] is None
    # Non-key fields preserved verbatim:
    assert row["sdk"] == "openai"
    assert row["base_url"] == "https://api.example.com/v1"
    assert row["mode"] == "discover"
    assert row["models"] == ["gpt-4o"]
    assert row["tags"] == []
    assert row["note"] == "seed"
    assert row["created_at"] == "2026-05-01T10:00:00"
    assert row["updated_at"] == "2026-05-06T14:22:11"
    # Runtime-only fields not exported:
    assert "list_error" not in row
    assert "stale_since" not in row


def test_dump_includes_keys_when_flag_set() -> None:
    eps = [_ep("alpha", api_key="sk-real")]
    out = dump_endpoints(eps, include_keys=True)
    assert out["endpoints"][0]["api_key"] == "sk-real"


def test_dump_empty_registry_yields_empty_endpoints() -> None:
    out = dump_endpoints([], include_keys=False)
    assert out["kind"] == SCHEMA_KIND
    assert out["endpoints"] == []
