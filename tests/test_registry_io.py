"""Tests for registry_io.dump_endpoints / load_endpoints."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.registry_io import (
    SCHEMA_KIND,
    SCHEMA_VERSION,
    dump_endpoints,
    load_endpoints,
)
from llm_model_probe.store import EndpointStore


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


@pytest.fixture
def store(isolated_home: Path) -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _v1_payload(endpoints: list[dict]) -> dict:
    return {
        "kind": SCHEMA_KIND,
        "version": SCHEMA_VERSION,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": endpoints,
    }


def _row(
    name: str = "alpha",
    *,
    id: str = "ep_aaa111",
    api_key: str | None = "sk-real",
    sdk: str = "openai",
    mode: str = "discover",
    models: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "sdk": sdk,
        "base_url": "https://api.example.com/v1",
        "api_key": api_key,
        "mode": mode,
        "models": models or ["gpt-4o"],
        "tags": tags or [],
        "note": "imported",
        "created_at": "2026-05-01T10:00:00",
        "updated_at": "2026-05-06T14:22:11",
    }


def test_load_into_empty_store_inserts_everything(
    store: EndpointStore,
) -> None:
    payload = _v1_payload([_row("alpha"), _row("beta", id="ep_bbb222")])

    report = load_endpoints(payload, store, on_conflict="skip")

    assert report.imported == ["alpha", "beta"]
    assert report.replaced == []
    assert report.skipped == []
    assert report.missing_keys == []

    got = {ep.name: ep for ep in store.list_endpoints()}
    assert set(got) == {"alpha", "beta"}
    assert got["alpha"].id == "ep_aaa111"
    assert got["alpha"].api_key == "sk-real"
    assert got["alpha"].mode == "discover"
    assert got["alpha"].models == ["gpt-4o"]
    # created_at/updated_at preserved from file
    assert got["alpha"].created_at == datetime(2026, 5, 1, 10, 0, 0)
    assert got["alpha"].updated_at == datetime(2026, 5, 6, 14, 22, 11)
