"""Unit tests for app_settings K/V store methods."""
from __future__ import annotations

from pathlib import Path

from llm_model_probe.store import EndpointStore


def test_get_setting_returns_none_when_unset(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    assert store.get_setting("parser.endpoint_id") is None


def test_set_then_get_setting(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.endpoint_id", "ep_abc123")
    assert store.get_setting("parser.endpoint_id") == "ep_abc123"


def test_set_setting_upserts(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.model_id", "gpt-4o-mini")
    store.set_setting("parser.model_id", "gpt-4o")
    assert store.get_setting("parser.model_id") == "gpt-4o"


def test_delete_setting_removes_row(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    store.set_setting("parser.endpoint_id", "ep_abc")
    store.delete_setting("parser.endpoint_id")
    assert store.get_setting("parser.endpoint_id") is None


def test_init_schema_idempotent_with_app_settings(isolated_home: Path) -> None:
    """Calling init_schema twice on an existing DB must not error."""
    store = EndpointStore()
    store.init_schema()
    store.set_setting("k", "v")
    store.init_schema()  # second call
    assert store.get_setting("k") == "v"


def test_delete_nonexistent_is_noop(isolated_home: Path) -> None:
    store = EndpointStore()
    store.init_schema()
    # Should not raise even though the key was never inserted.
    store.delete_setting("never.set")
    assert store.get_setting("never.set") is None


def test_set_setting_populates_updated_at(isolated_home: Path) -> None:
    import sqlite3

    store = EndpointStore()
    store.init_schema()
    store.set_setting("k", "v")
    with sqlite3.connect(store._path) as c:
        row = c.execute(
            "SELECT updated_at FROM app_settings WHERE key = 'k'"
        ).fetchone()
    assert row is not None
    assert row[0]  # non-null, non-empty string
