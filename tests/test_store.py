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


def test_init_schema_backfills_models_from_results(
    isolated_home: Path,
) -> None:
    """Pre-redesign endpoints with empty models_json should get backfilled
    from model_results on the next init_schema()."""
    s = EndpointStore()
    s.init_schema()
    ep = _ep("legacy", mode="discover")
    s.insert_endpoint(ep)
    # Simulate pre-redesign state: model_results filled but models_json empty
    s.replace_model_results(ep.id, [
        ModelResult(ep.id, "gpt-4", "discovered", "available", 100,
                    last_tested_at=datetime.now()),
        ModelResult(ep.id, "gpt-3.5", "discovered", "failed", 50,
                    last_tested_at=datetime.now()),
    ])
    # endpoints.models stays empty because _ep created with []
    assert s.get_endpoint("legacy").models == []  # type: ignore[union-attr]

    # Re-init triggers backfill
    s2 = EndpointStore()
    s2.init_schema()
    refreshed = s2.get_endpoint("legacy")
    assert refreshed is not None
    assert sorted(refreshed.models) == ["gpt-3.5", "gpt-4"]


def test_endpoint_persists_tags(isolated_home: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    ep = Endpoint(
        id=new_endpoint_id(),
        name="tagged",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test123",
        mode="specified",
        models=["a"],
        note="",
        tags=["bob", "trial"],
    )
    s.insert_endpoint(ep)
    got = s.get_endpoint("tagged")
    assert got is not None
    assert got.tags == ["bob", "trial"]


def test_endpoint_default_tags_empty(isolated_home: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    ep = Endpoint(
        id=new_endpoint_id(),
        name="notags",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test123",
        mode="specified",
        models=[],
        note="",
    )
    s.insert_endpoint(ep)
    got = s.get_endpoint("notags")
    assert got is not None
    assert got.tags == []


def test_set_tags_replaces(isolated_home: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    ep = Endpoint(
        id=new_endpoint_id(),
        name="rep",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test123",
        mode="specified",
        models=[],
        note="",
        tags=["x"],
    )
    s.insert_endpoint(ep)
    s.set_tags(ep.id, ["y", "z"])
    got = s.get_endpoint("rep")
    assert got is not None
    assert got.tags == ["y", "z"]


def test_init_schema_adds_tags_column_idempotently(
    isolated_home: Path,
) -> None:
    """Old DB without tags_json column - init_schema adds it idempotently."""
    import sqlite3

    from llm_model_probe.paths import db_path, ensure_home

    ensure_home()
    path = db_path()
    with sqlite3.connect(path) as c:
        c.executescript(
            """
            CREATE TABLE endpoints (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                sdk TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                mode TEXT NOT NULL,
                models_json TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                list_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE model_results (
                endpoint_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                error_type TEXT,
                error_message TEXT,
                response_preview TEXT,
                last_tested_at TEXT NOT NULL,
                PRIMARY KEY (endpoint_id, model_id),
                FOREIGN KEY (endpoint_id) REFERENCES endpoints(id) ON DELETE CASCADE
            );
            INSERT INTO endpoints
            (id, name, sdk, base_url, api_key, mode, created_at, updated_at)
            VALUES
            ('ep_legacy', 'legacy', 'openai', 'https://x/v1', 'sk-x', 'specified',
             '2026-05-01T00:00:00', '2026-05-01T00:00:00');
            """
        )
        c.commit()

    s = EndpointStore()
    s.init_schema()
    legacy = s.get_endpoint("legacy")
    assert legacy is not None
    assert legacy.tags == []


def test_init_schema_backfill_is_idempotent(isolated_home: Path) -> None:
    """Endpoints with non-empty models_json must not be touched by backfill."""
    s = EndpointStore()
    s.init_schema()
    ep = Endpoint(
        id=new_endpoint_id(),
        name="new-style",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-test123",
        mode="specified",
        models=["m1", "m2"],
        note="",
    )
    s.insert_endpoint(ep)
    # Re-init: backfill must not clobber the explicitly-set list
    EndpointStore().init_schema()
    refreshed = s.get_endpoint("new-style")
    assert refreshed is not None
    assert refreshed.models == ["m1", "m2"]


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


def test_stale_since_roundtrip(store: EndpointStore) -> None:
    ep = _ep("stalecheck")
    ep.stale_since = datetime(2026, 5, 6, 10, 0, 0)
    store.insert_endpoint(ep)
    got = store.get_endpoint("stalecheck")
    assert got is not None
    assert got.stale_since == datetime(2026, 5, 6, 10, 0, 0)


def test_stale_since_default_none(store: EndpointStore) -> None:
    ep = _ep("freshep")
    store.insert_endpoint(ep)
    got = store.get_endpoint("freshep")
    assert got is not None
    assert got.stale_since is None


def test_migration_adds_stale_since_idempotent(isolated_home: Path) -> None:
    """Old DB with no stale_since column gets the column added on init,
    and re-running init_schema is a no-op."""
    s1 = EndpointStore()
    s1.init_schema()
    s2 = EndpointStore()
    s2.init_schema()  # second run: must not raise
    ep = _ep("post-migrate")
    s2.insert_endpoint(ep)
    got = s2.get_endpoint("post-migrate")
    assert got is not None
    assert got.stale_since is None
