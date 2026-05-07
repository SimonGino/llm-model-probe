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


from llm_model_probe.registry_io import LoadFormatError


def test_load_rejects_wrong_kind(store: EndpointStore) -> None:
    bad = {
        "kind": "something-else",
        "version": 1,
        "endpoints": [],
    }
    with pytest.raises(LoadFormatError, match="expected"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_future_version(store: EndpointStore) -> None:
    bad = {"kind": SCHEMA_KIND, "version": 2, "endpoints": []}
    with pytest.raises(LoadFormatError, match="upgrade"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_missing_required_field(
    store: EndpointStore,
) -> None:
    row = _row("alpha")
    del row["sdk"]
    bad = _v1_payload([row])
    with pytest.raises(LoadFormatError, match="missing required field 'sdk'"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_invalid_sdk(store: EndpointStore) -> None:
    bad = _v1_payload([_row("alpha", sdk="cohere")])
    with pytest.raises(LoadFormatError, match="invalid sdk"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_invalid_mode(store: EndpointStore) -> None:
    bad = _v1_payload([_row("alpha", mode="invalid")])
    with pytest.raises(LoadFormatError, match="invalid mode"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_duplicate_name(store: EndpointStore) -> None:
    bad = _v1_payload([_row("dup", id="ep_a"), _row("dup", id="ep_b")])
    with pytest.raises(LoadFormatError, match="duplicate name"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_duplicate_id(store: EndpointStore) -> None:
    bad = _v1_payload([_row("a", id="ep_x"), _row("b", id="ep_x")])
    with pytest.raises(LoadFormatError, match="duplicate id"):
        load_endpoints(bad, store, on_conflict="skip")


def test_load_rejects_models_not_list(store: EndpointStore) -> None:
    row = _row("alpha")
    row["models"] = "gpt-4o"  # string, not list
    with pytest.raises(LoadFormatError, match="non-string-list"):
        load_endpoints(_v1_payload([row]), store, on_conflict="skip")


from llm_model_probe.models import Endpoint, new_endpoint_id


def _seed(store: EndpointStore, name: str = "alpha") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://local.example.com/v1",
        api_key="sk-LOCAL",
        mode="discover",
        models=["local-model"],
        note="local original",
        tags=["local"],
    )
    store.insert_endpoint(ep)
    return ep


def test_conflict_skip_leaves_existing_untouched(
    store: EndpointStore,
) -> None:
    local = _seed(store, "alpha")
    payload = _v1_payload([
        _row("alpha", api_key="sk-FILE"),
        _row("beta", id="ep_bbb222"),
    ])

    report = load_endpoints(payload, store, on_conflict="skip")

    assert report.imported == ["beta"]
    assert report.skipped == ["alpha"]
    assert report.replaced == []

    fresh = store.get_endpoint("alpha")
    assert fresh is not None
    assert fresh.id == local.id
    assert fresh.api_key == "sk-LOCAL"  # untouched
    assert fresh.base_url == "https://local.example.com/v1"


from llm_model_probe.models import ModelResult


def test_conflict_replace_overwrites_but_preserves_local_id_and_results(
    store: EndpointStore,
) -> None:
    local = _seed(store, "alpha")
    # Seed a model_result so we can assert the FK row survives.
    store.replace_model_results(
        local.id,
        [
            ModelResult(
                local.id, "local-model", "discovered", "available",
                100, last_tested_at=datetime(2026, 5, 1),
            )
        ],
    )

    payload = _v1_payload([
        _row(
            "alpha",
            id="ep_FROM_FILE",
            api_key="sk-FILE",
            mode="specified",
            models=["m-from-file"],
            tags=["from-file"],
        )
    ])

    report = load_endpoints(payload, store, on_conflict="replace")

    assert report.replaced == ["alpha"]
    assert report.imported == []
    assert report.skipped == []

    fresh = store.get_endpoint("alpha")
    assert fresh is not None
    # Local id preserved → model_results FK still valid:
    assert fresh.id == local.id
    # Other fields overwritten:
    assert fresh.api_key == "sk-FILE"
    assert fresh.mode == "specified"
    assert fresh.models == ["m-from-file"]
    assert fresh.tags == ["from-file"]

    # model_results row survived:
    results = store.list_model_results(local.id)
    assert {r.model_id for r in results} == {"local-model"}


from llm_model_probe.registry_io import LoadConflict


def test_conflict_error_aborts_and_rolls_back(
    store: EndpointStore,
) -> None:
    _seed(store, "alpha")

    payload = _v1_payload([
        _row("brand-new", id="ep_NEW1"),  # would insert if we got that far
        _row("alpha"),                     # triggers the error
    ])

    with pytest.raises(LoadConflict, match="alpha"):
        load_endpoints(payload, store, on_conflict="error")

    # 'brand-new' must NOT be in the store — the whole batch is rejected.
    assert store.get_endpoint("brand-new") is None
    # 'alpha' is unchanged.
    fresh = store.get_endpoint("alpha")
    assert fresh is not None
    assert fresh.api_key == "sk-LOCAL"


def test_load_rejects_file_id_collision_with_different_local_name(
    store: EndpointStore,
) -> None:
    # Local: name='local-thing' uses id 'ep_SHARED'
    local = Endpoint(
        id="ep_SHARED",
        name="local-thing",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-x",
        mode="discover",
        models=[],
        note="",
    )
    store.insert_endpoint(local)

    # File: a different name claims the same id.
    payload = _v1_payload([_row("file-thing", id="ep_SHARED")])

    with pytest.raises(LoadFormatError, match="local-thing"):
        load_endpoints(payload, store, on_conflict="skip")

    # Local row untouched, file row not inserted.
    assert store.get_endpoint("file-thing") is None
    assert store.get_endpoint("local-thing") is not None


def test_load_null_api_key_becomes_empty_string_and_reported(
    store: EndpointStore,
) -> None:
    payload = _v1_payload([
        _row("with-key", api_key="sk-real"),
        _row("no-key", id="ep_NK", api_key=None),
    ])

    report = load_endpoints(payload, store, on_conflict="skip")

    assert sorted(report.imported) == ["no-key", "with-key"]
    assert report.missing_keys == ["no-key"]

    no_key = store.get_endpoint("no-key")
    assert no_key is not None
    assert no_key.api_key == ""

    with_key = store.get_endpoint("with-key")
    assert with_key is not None
    assert with_key.api_key == "sk-real"


def test_load_normalizes_base_url(store: EndpointStore) -> None:
    row = _row("alpha")
    row["base_url"] = "https://api.example.com/v1/chat/completions"
    payload = _v1_payload([row])

    load_endpoints(payload, store, on_conflict="skip")

    fresh = store.get_endpoint("alpha")
    assert fresh is not None
    assert fresh.base_url == "https://api.example.com/v1"
