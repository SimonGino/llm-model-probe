# Registry Export/Import (dump/load) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cross-machine export/import for the endpoints registry: `probe dump` and `probe load` CLI commands, a dump-only `GET /api/registry/dump` endpoint, and a UI download button.

**Architecture:** A new module `src/llm_model_probe/registry_io.py` holds two pure-ish functions (`dump_endpoints`, `load_endpoints`) plus `LoadReport`, `LoadFormatError`, `LoadConflict`. CLI and API both call them. JSON IO and file IO are owned by the callers, keeping the core logic easily testable. Load uses raw `sqlite3` with a single connection so the whole batch is atomic; reads still go through `EndpointStore`.

**Tech Stack:** Python 3.12, FastAPI, Typer, SQLite, pytest, React + Vite + TypeScript.

**Spec:** `docs/specs/2026-05-07-registry-export-import-design.md`

---

## File Structure

**Create:**
- `src/llm_model_probe/registry_io.py` — `dump_endpoints`, `load_endpoints`, `LoadReport`, `LoadFormatError`, `LoadConflict`
- `tests/test_registry_io.py` — pure-function tests for dump/load
- `tests/test_cli_dump_load.py` — Typer CliRunner tests for `probe dump` / `probe load`
- `tests/test_api_registry_dump.py` — FastAPI TestClient tests for `GET /api/registry/dump`
- `frontend/src/components/ExportRegistryButton.tsx` — button + popover with `Include API keys` toggle

**Modify:**
- `src/llm_model_probe/cli.py` — add `dump` and `load` typer commands
- `src/llm_model_probe/api.py` — add `dump_registry` route
- `frontend/src/lib/api.ts` — add `downloadRegistry` helper (binary blob, not JSON)
- `frontend/src/App.tsx` — render `<ExportRegistryButton>` in `TopBar`
- `README.md` — short section on `probe dump` / `probe load` plus the UI button

---

## Constants and Module Layout

`registry_io.py` must export at module scope:

- `SCHEMA_KIND = "llm-model-probe-registry"`
- `SCHEMA_VERSION = 1`
- `dump_endpoints(...)`, `load_endpoints(...)`
- `LoadReport`, `LoadFormatError`, `LoadConflict`

These names are referenced by `cli.py`, `api.py`, and tests — keep them stable across tasks.

---

### Task 1: Create `registry_io.py` skeleton + `dump_endpoints` (without keys)

**Files:**
- Create: `src/llm_model_probe/registry_io.py`
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test for dump shape (no keys)**

Create `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: FAIL — module `llm_model_probe.registry_io` not found.

- [ ] **Step 3: Create the module with dump_endpoints (no-keys path only)**

Create `src/llm_model_probe/registry_io.py`:

```python
"""Cross-machine registry serialization (dump / load).

Pure-ish module: functions accept an EndpointStore for load, but JSON
serialization and file IO live in the callers (cli, api). This keeps unit
tests simple and the surface narrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .models import Endpoint

SCHEMA_KIND = "llm-model-probe-registry"
SCHEMA_VERSION = 1


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def dump_endpoints(
    endpoints: list[Endpoint],
    *,
    include_keys: bool,
    now: datetime | None = None,
) -> dict:
    """Build a JSON-serializable envelope for the registry.

    `include_keys=False` writes `api_key: null`; True writes the plaintext key.
    `now` is overridable for deterministic tests.
    """
    when = now or datetime.now()
    return {
        "kind": SCHEMA_KIND,
        "version": SCHEMA_VERSION,
        "exported_at": _iso(when),
        "endpoints": [
            {
                "id": ep.id,
                "name": ep.name,
                "sdk": ep.sdk,
                "base_url": ep.base_url,
                "api_key": ep.api_key if include_keys else None,
                "mode": ep.mode,
                "models": list(ep.models),
                "tags": list(ep.tags),
                "note": ep.note,
                "created_at": _iso(ep.created_at),
                "updated_at": _iso(ep.updated_at),
            }
            for ep in endpoints
        ],
    }


@dataclass
class LoadReport:
    imported: list[str] = field(default_factory=list)   # newly inserted names
    replaced: list[str] = field(default_factory=list)   # existing names overwritten
    skipped: list[str] = field(default_factory=list)    # conflict, on_conflict=skip
    missing_keys: list[str] = field(default_factory=list)  # api_key empty after load


class LoadFormatError(ValueError):
    """The payload doesn't match the v1 registry envelope schema."""


class LoadConflict(Exception):
    """on_conflict='error' and a name conflict was found."""


def load_endpoints(
    payload: dict,
    store,  # EndpointStore — type-annotated softly to avoid circular imports
    *,
    on_conflict: Literal["skip", "replace", "error"],
) -> LoadReport:
    """Stub — implemented in later tasks."""
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — `test_dump_envelope_shape_default_excludes_keys`.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/registry_io.py tests/test_registry_io.py
git commit -m "feat(registry-io): scaffold + dump_endpoints (no keys)"
```

---

### Task 2: `dump_endpoints` with `include_keys=True`

**Files:**
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
def test_dump_includes_keys_when_flag_set() -> None:
    eps = [_ep("alpha", api_key="sk-real")]
    out = dump_endpoints(eps, include_keys=True)
    assert out["endpoints"][0]["api_key"] == "sk-real"


def test_dump_empty_registry_yields_empty_endpoints() -> None:
    out = dump_endpoints([], include_keys=False)
    assert out["kind"] == SCHEMA_KIND
    assert out["endpoints"] == []
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — both new tests already pass with the existing implementation (verifying behavior, not driving change).

If they don't pass, the implementation in Task 1 has a bug — fix it now.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): cover dump include_keys + empty registry"
```

---

### Task 3: `load_endpoints` happy path (insert into empty store)

**Files:**
- Modify: `src/llm_model_probe/registry_io.py`
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
from pathlib import Path

import pytest

from llm_model_probe.registry_io import load_endpoints
from llm_model_probe.store import EndpointStore


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry_io.py::test_load_into_empty_store_inserts_everything -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `load_endpoints` happy path**

Replace the stub in `src/llm_model_probe/registry_io.py` with a working implementation. Add the imports at the top:

```python
import json
import sqlite3
```

Then replace the `load_endpoints` stub with:

```python
_VALID_SDKS = {"openai", "anthropic"}
_VALID_MODES = {"discover", "specified"}
_REQUIRED_FIELDS = (
    "id", "name", "sdk", "base_url", "api_key", "mode",
    "models", "tags", "note",
)


@dataclass
class _Row:
    id: str
    name: str
    sdk: str
    base_url: str
    api_key: str | None
    mode: str
    models: list[str]
    tags: list[str]
    note: str
    created_at: str | None
    updated_at: str | None


def _parse_row(raw: dict, idx: int) -> _Row:
    """Validate one endpoint dict and return a typed _Row.

    `idx` is the position in the file for nicer error messages.
    """
    if not isinstance(raw, dict):
        raise LoadFormatError(f"endpoints[{idx}] is not an object")
    for field_name in _REQUIRED_FIELDS:
        if field_name not in raw:
            raise LoadFormatError(
                f"endpoints[{idx}] missing required field '{field_name}'"
            )
    name = raw["name"]
    if not isinstance(name, str) or not name:
        raise LoadFormatError(
            f"endpoints[{idx}] has invalid name {raw['name']!r}"
        )
    if raw["sdk"] not in _VALID_SDKS:
        raise LoadFormatError(
            f"endpoint '{name}' has invalid sdk={raw['sdk']!r}"
        )
    if raw["mode"] not in _VALID_MODES:
        raise LoadFormatError(
            f"endpoint '{name}' has invalid mode={raw['mode']!r}"
        )
    if not isinstance(raw["models"], list) or not all(
        isinstance(m, str) for m in raw["models"]
    ):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string-list models"
        )
    if not isinstance(raw["tags"], list) or not all(
        isinstance(t, str) for t in raw["tags"]
    ):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string-list tags"
        )
    api_key = raw["api_key"]
    if api_key is not None and not isinstance(api_key, str):
        raise LoadFormatError(
            f"endpoint '{name}' has non-string api_key"
        )
    return _Row(
        id=str(raw["id"]),
        name=name,
        sdk=raw["sdk"],
        base_url=str(raw["base_url"]),
        api_key=api_key,
        mode=raw["mode"],
        models=list(raw["models"]),
        tags=list(raw["tags"]),
        note=str(raw["note"]),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def _validate_envelope(payload: dict) -> list[_Row]:
    if not isinstance(payload, dict):
        raise LoadFormatError("file is not a JSON object")
    if payload.get("kind") != SCHEMA_KIND:
        raise LoadFormatError(
            f"file kind={payload.get('kind')!r}; expected {SCHEMA_KIND!r}"
        )
    version = payload.get("version")
    if not isinstance(version, int):
        raise LoadFormatError("file version missing or not an integer")
    if version > SCHEMA_VERSION:
        raise LoadFormatError(
            f"file version {version} not supported; please upgrade probe"
        )
    if version < 1:
        raise LoadFormatError(f"file version {version} not supported")
    rows_raw = payload.get("endpoints")
    if not isinstance(rows_raw, list):
        raise LoadFormatError("file 'endpoints' must be an array")
    rows = [_parse_row(r, i) for i, r in enumerate(rows_raw)]
    # Same name twice in the file — corrupted.
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for r in rows:
        if r.name in seen_names:
            raise LoadFormatError(
                f"duplicate name {r.name!r} in file"
            )
        seen_names.add(r.name)
        if r.id in seen_ids:
            raise LoadFormatError(f"duplicate id {r.id!r} in file")
        seen_ids.add(r.id)
    return rows


def load_endpoints(
    payload: dict,
    store,
    *,
    on_conflict: Literal["skip", "replace", "error"],
) -> LoadReport:
    """Validate envelope, then apply to the store inside a single transaction.

    Conflict matching is by `name` (the DB UNIQUE column). File `id` is used
    on insert (round-trip stability); on replace, the existing local id is
    kept so model_results FK rows survive.
    """
    if on_conflict not in ("skip", "replace", "error"):
        raise ValueError(
            f"on_conflict must be skip|replace|error, got {on_conflict!r}"
        )
    rows = _validate_envelope(payload)

    existing_by_name = {ep.name: ep for ep in store.list_endpoints()}
    report = LoadReport()
    plan: list[tuple[str, _Row, str | None]] = []  # (action, row, existing_id)

    for r in rows:
        existing = existing_by_name.get(r.name)
        if existing is None:
            plan.append(("insert", r, None))
            report.imported.append(r.name)
        else:
            if on_conflict == "skip":
                report.skipped.append(r.name)
            elif on_conflict == "replace":
                plan.append(("update", r, existing.id))
                report.replaced.append(r.name)
            else:  # "error"
                raise LoadConflict(
                    f"endpoint {r.name!r} already exists "
                    "(use --on-conflict=replace to override)"
                )

    now_iso = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(store._path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            for action, r, existing_id in plan:
                key = r.api_key if r.api_key is not None else ""
                if not key:
                    report.missing_keys.append(r.name)
                if action == "insert":
                    conn.execute(
                        """INSERT INTO endpoints
                           (id, name, sdk, base_url, api_key, mode,
                            models_json, note, list_error, tags_json,
                            stale_since, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            r.id, r.name, r.sdk, r.base_url, key, r.mode,
                            json.dumps(r.models), r.note, None,
                            json.dumps(r.tags), None,
                            r.created_at or now_iso,
                            r.updated_at or now_iso,
                        ),
                    )
                else:  # "update" — replace path
                    conn.execute(
                        """UPDATE endpoints SET
                              name = ?, sdk = ?, base_url = ?,
                              api_key = ?, mode = ?, models_json = ?,
                              note = ?, tags_json = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            r.name, r.sdk, r.base_url, key, r.mode,
                            json.dumps(r.models), r.note,
                            json.dumps(r.tags), now_iso, existing_id,
                        ),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return report
```

Then in `tests/test_registry_io.py`, ensure the `isolated_home` fixture is importable. It's defined in `tests/conftest.py` so it auto-imports — no extra setup needed.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — all four tests so far.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/registry_io.py tests/test_registry_io.py
git commit -m "feat(registry-io): load happy path with envelope/row validation"
```

---

### Task 4: Validation errors (envelope and row level)

**Files:**
- Test: `tests/test_registry_io.py`
- (No code change — validation already implemented in Task 3.)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — all 8 new tests, the validation logic from Task 3 covers them.

If any test fails, the validator missed a case — fix it in `_validate_envelope` or `_parse_row` before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): cover format-validation error paths"
```

---

### Task 5: Conflict policy = `skip`

**Files:**
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
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
        _row("beta"),
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
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_registry_io.py::test_conflict_skip_leaves_existing_untouched -v`
Expected: PASS — Task 3's `load_endpoints` already handles `skip`. If FAIL, fix Task 3.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): conflict=skip preserves local"
```

---

### Task 6: Conflict policy = `replace` (preserves local id and model_results)

**Files:**
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_registry_io.py::test_conflict_replace_overwrites_but_preserves_local_id_and_results -v`
Expected: PASS — Task 3's UPDATE path already covers this. If FAIL, fix Task 3.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): conflict=replace preserves id + model_results"
```

---

### Task 7: Conflict policy = `error` rolls back the batch

**Files:**
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_registry_io.py::test_conflict_error_aborts_and_rolls_back -v`
Expected: PASS — Task 3's planning phase raises before any DB write happens. If FAIL, fix the ordering in Task 3 so the conflict check happens before the SQLite connection is opened.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): conflict=error rolls back batch"
```

---

### Task 8: Reject file id that collides with a different local name

**Spec edge case:** if the file says `name="brand-new", id="ep_X"` but local DB has a row with the same id under a different name (`name="something-else", id="ep_X"`), inserting would hit the SQLite primary key constraint with an opaque error. Spec says treat as a format error.

**Files:**
- Modify: `src/llm_model_probe/registry_io.py`
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry_io.py::test_load_rejects_file_id_collision_with_different_local_name -v`
Expected: FAIL — currently the INSERT raises `sqlite3.IntegrityError`, which doesn't match `LoadFormatError`.

- [ ] **Step 3: Add the planning-phase id collision check**

In `src/llm_model_probe/registry_io.py`, inside `load_endpoints`, after the line that builds `existing_by_name`, add `existing_by_id` and the check inside the planning loop:

```python
    existing_by_name = {ep.name: ep for ep in store.list_endpoints()}
    existing_by_id = {ep.id: ep for ep in existing_by_name.values()}
    report = LoadReport()
    plan: list[tuple[str, _Row, str | None]] = []

    for r in rows:
        existing = existing_by_name.get(r.name)
        if existing is None:
            id_owner = existing_by_id.get(r.id)
            if id_owner is not None:
                raise LoadFormatError(
                    f"file id {r.id!r} (for endpoint {r.name!r}) is already "
                    f"used locally by endpoint {id_owner.name!r}; "
                    "remove that endpoint or edit the file's id"
                )
            plan.append(("insert", r, None))
            report.imported.append(r.name)
        else:
            ...  # existing skip/replace/error branches unchanged
```

The replace branch is unaffected — when `existing is not None`, we reuse `existing.id` and never try to write the file's id.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — including the new collision test and all previous tests.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/registry_io.py tests/test_registry_io.py
git commit -m "feat(registry-io): reject file id colliding with different local name"
```

---

### Task 9: api_key handling (null becomes empty string + missing_keys report)

**Files:**
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
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
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_registry_io.py::test_load_null_api_key_becomes_empty_string_and_reported -v`
Expected: PASS — Task 3's logic handles this. If FAIL, fix Task 3.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry_io.py
git commit -m "test(registry-io): null api_key → empty string + missing_keys list"
```

---

### Task 10: `base_url` re-normalized on load

**Rationale:** A file edited by hand or coming from a pre-normalize-era export can have `…/v1/chat/completions` as `base_url`. Spec calls for `normalize_base_url` to run on load.

**Files:**
- Modify: `src/llm_model_probe/registry_io.py`
- Test: `tests/test_registry_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_io.py`:

```python
def test_load_normalizes_base_url(store: EndpointStore) -> None:
    row = _row("alpha")
    row["base_url"] = "https://api.example.com/v1/chat/completions"
    payload = _v1_payload([row])

    load_endpoints(payload, store, on_conflict="skip")

    fresh = store.get_endpoint("alpha")
    assert fresh is not None
    assert fresh.base_url == "https://api.example.com/v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry_io.py::test_load_normalizes_base_url -v`
Expected: FAIL — load currently writes the raw URL.

- [ ] **Step 3: Wire `normalize_base_url` into the load path**

In `src/llm_model_probe/registry_io.py`, inside `load_endpoints` after `rows = _validate_envelope(payload)`, add a function-local import (deliberately not at module top — `api.py` imports from `registry_io` after Task 12, and a function-local import keeps the dependency one-way at module-eval time):

```python
from .api import normalize_base_url

for r in rows:
    r.base_url = normalize_base_url(r.base_url)
```

(`_Row` is a dataclass — its fields are mutable, so the in-place reassignment works.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_registry_io.py -v`
Expected: PASS — all tests including the new one.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/registry_io.py tests/test_registry_io.py
git commit -m "feat(registry-io): re-normalize base_url on load"
```

---

### Task 11: CLI `probe dump`

**Files:**
- Modify: `src/llm_model_probe/cli.py`
- Create: `tests/test_cli_dump_load.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_dump_load.py`:

```python
"""End-to-end CLI tests for `probe dump` and `probe load`."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_model_probe.cli import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.store import EndpointStore

runner = CliRunner()


def _seed(store: EndpointStore, name: str = "alpha", api_key: str = "sk-real") -> Endpoint:
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key=api_key,
        mode="discover",
        models=["gpt-4o"],
        note="seed",
    )
    store.insert_endpoint(ep)
    return ep


def test_dump_writes_file_without_keys(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-secret")
    out = tmp_path / "reg.json"

    result = runner.invoke(app, ["dump", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["kind"] == "llm-model-probe-registry"
    assert payload["endpoints"][0]["name"] == "alpha"
    assert payload["endpoints"][0]["api_key"] is None


def test_dump_file_chmod_0600(isolated_home: Path, tmp_path: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")
    out = tmp_path / "reg.json"

    runner.invoke(app, ["dump", "--output", str(out)])

    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600


def test_dump_to_stdout_when_no_output(isolated_home: Path) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")

    result = runner.invoke(app, ["dump"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["name"] == "alpha"


def test_dump_include_keys_writes_real_key(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-real")
    out = tmp_path / "reg.json"

    result = runner.invoke(
        app, ["dump", "--include-keys", "--output", str(out)]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text())
    assert payload["endpoints"][0]["api_key"] == "sk-real"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_dump_load.py -v`
Expected: FAIL — `dump` is not a known typer command.

- [ ] **Step 3: Implement the `dump` command**

In `src/llm_model_probe/cli.py`, add at the top of the existing imports:

```python
import json
from pathlib import Path
```

(`json` and `Path` may already be imported — check first; the file only imports `Path` lazily inside `export()` and `ui()`.)

After the existing `export` command (around line 260), append:

```python
from .registry_io import dump_endpoints


@app.command()
def dump(
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file; default stdout"
    ),
    include_keys: bool = typer.Option(
        False, "--include-keys",
        help="Include api_key in the output. WARNING: keys are written in plaintext.",
    ),
) -> None:
    """Dump the registry to JSON for re-import on another machine."""
    store = _store()
    payload = dump_endpoints(
        store.list_endpoints(),
        include_keys=include_keys,
    )
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        out_path = Path(output)
        out_path.write_text(text, encoding="utf-8")
        try:
            out_path.chmod(0o600)
        except OSError:
            pass  # best effort on platforms without chmod
        console.print(
            f"[green]✓[/green] wrote {output} "
            f"({len(payload['endpoints'])} endpoints)"
        )
        if include_keys:
            console.print(
                "[yellow]![/yellow] file contains plaintext API keys; "
                "chmod 0600 applied"
            )
    else:
        print(text)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cli_dump_load.py -v`
Expected: PASS — all four `test_dump_*` tests.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/cli.py tests/test_cli_dump_load.py
git commit -m "feat(cli): probe dump command"
```

---

### Task 12: CLI `probe load`

**Files:**
- Modify: `src/llm_model_probe/cli.py`
- Test: `tests/test_cli_dump_load.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_dump_load.py`:

```python
def test_load_imports_from_file(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "preexisting")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_NEW",
            "name": "new-one",
            "sdk": "openai",
            "base_url": "https://other.example.com/v1",
            "api_key": "sk-x",
            "mode": "specified",
            "models": ["m1"],
            "tags": [],
            "note": "",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-01T10:00:00",
        }],
    }))

    result = runner.invoke(app, ["load", str(file)])

    assert result.exit_code == 0, result.output
    assert "imported" in result.output.lower()
    fresh = EndpointStore()
    fresh.init_schema()
    names = {ep.name for ep in fresh.list_endpoints()}
    assert names == {"preexisting", "new-one"}


def test_load_with_conflict_replace(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha", api_key="sk-LOCAL")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_FROM_FILE",
            "name": "alpha",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-FROM-FILE",
            "mode": "discover",
            "models": ["gpt-4o"],
            "tags": [],
            "note": "from file",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-06T14:00:00",
        }],
    }))

    result = runner.invoke(
        app, ["load", str(file), "--on-conflict", "replace"]
    )

    assert result.exit_code == 0, result.output
    fresh = EndpointStore()
    fresh.init_schema()
    alpha = fresh.get_endpoint("alpha")
    assert alpha is not None
    assert alpha.api_key == "sk-FROM-FILE"


def test_load_with_conflict_error_exits_2(
    isolated_home: Path, tmp_path: Path
) -> None:
    s = EndpointStore()
    s.init_schema()
    _seed(s, "alpha")

    file = tmp_path / "reg.json"
    file.write_text(json.dumps({
        "kind": "llm-model-probe-registry",
        "version": 1,
        "exported_at": "2026-05-07T12:00:00",
        "endpoints": [{
            "id": "ep_X",
            "name": "alpha",
            "sdk": "openai",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-x",
            "mode": "discover",
            "models": [],
            "tags": [],
            "note": "",
            "created_at": "2026-05-01T10:00:00",
            "updated_at": "2026-05-01T10:00:00",
        }],
    }))

    result = runner.invoke(
        app, ["load", str(file), "--on-conflict", "error"]
    )

    assert result.exit_code == 2, result.output
    assert "alpha" in result.output


def test_load_nonexistent_file_friendly_error(
    isolated_home: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "no-such.json"
    result = runner.invoke(app, ["load", str(missing)])

    assert result.exit_code != 0
    # Should be a helpful one-liner, not a Python traceback.
    assert "Traceback" not in result.output


def test_load_garbage_file_friendly_error(
    isolated_home: Path, tmp_path: Path
) -> None:
    garbage = tmp_path / "junk.txt"
    garbage.write_text("this is not JSON")

    result = runner.invoke(app, ["load", str(garbage)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "json" in result.output.lower() or "valid" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify failures**

Run: `uv run pytest tests/test_cli_dump_load.py -v`
Expected: the new `test_load_*` tests FAIL — command not registered.

- [ ] **Step 3: Implement the `load` command**

In `src/llm_model_probe/cli.py`, append after the `dump` command:

```python
from .registry_io import (
    LoadConflict,
    LoadFormatError,
    LoadReport,
    load_endpoints,
)


def _print_load_report(report: LoadReport) -> None:
    total_written = len(report.imported) + len(report.replaced)
    detail = ""
    if report.replaced:
        detail = f" (new {len(report.imported)}, replaced {len(report.replaced)})"
    console.print(
        f"[green]✓[/green] imported {total_written} endpoints{detail}"
    )
    if report.skipped:
        names = ", ".join(report.skipped)
        console.print(
            f"  · skipped {len(report.skipped)} conflict(s): {names} "
            "(use --on-conflict=replace to override)"
        )
    if report.missing_keys:
        names = ", ".join(report.missing_keys)
        console.print(
            f"  · {len(report.missing_keys)} endpoint(s) have no api_key: "
            f"{names} — fill in via the web UI's edit dialog"
        )


@app.command()
def load(
    path: str = typer.Argument(..., metavar="FILE"),
    on_conflict: str = typer.Option(
        "skip", "--on-conflict",
        help="Strategy when an endpoint name already exists: skip | replace | error",
    ),
) -> None:
    """Load endpoints from a `probe dump` file."""
    if on_conflict not in ("skip", "replace", "error"):
        raise typer.BadParameter("--on-conflict must be skip | replace | error")

    file = Path(path)
    if not file.exists():
        console.print(f"[red]✗[/red] file not found: {path}")
        raise typer.Exit(1)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as e:
        console.print(f"[red]✗[/red] cannot read {path}: {e}")
        raise typer.Exit(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] not valid JSON: {e}")
        raise typer.Exit(1)

    store = _store()
    try:
        report = load_endpoints(payload, store, on_conflict=on_conflict)
    except LoadFormatError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except LoadConflict as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(2)

    _print_load_report(report)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cli_dump_load.py -v`
Expected: PASS — all dump + load tests.

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/cli.py tests/test_cli_dump_load.py
git commit -m "feat(cli): probe load command with --on-conflict"
```

---

### Task 13: API endpoint `GET /api/registry/dump`

**Files:**
- Modify: `src/llm_model_probe/api.py`
- Create: `tests/test_api_registry_dump.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_registry_dump.py`:

```python
"""Tests for GET /api/registry/dump."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_model_probe.api import app
from llm_model_probe.models import Endpoint, new_endpoint_id
from llm_model_probe.store import EndpointStore


@pytest.fixture
def client(isolated_home: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def seeded_store(isolated_home: Path) -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    s.insert_endpoint(Endpoint(
        id=new_endpoint_id(),
        name="alpha",
        sdk="openai",
        base_url="https://api.example.com/v1",
        api_key="sk-real",
        mode="discover",
        models=["gpt-4o"],
        note="seed",
    ))
    return s


def test_dump_default_excludes_keys(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "llm-model-probe-registry"
    assert body["version"] == 1
    assert body["endpoints"][0]["name"] == "alpha"
    assert body["endpoints"][0]["api_key"] is None


def test_dump_include_keys_includes_keys(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump?include_keys=true")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoints"][0]["api_key"] == "sk-real"


def test_dump_sets_content_disposition(
    client: TestClient, seeded_store: EndpointStore
) -> None:
    r = client.get("/api/registry/dump")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "llm-model-probe-registry-" in cd
    assert ".json" in cd


def test_dump_requires_token_when_set(
    client: TestClient,
    seeded_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL_PROBE_TOKEN", "s3cret")
    r = client.get("/api/registry/dump")
    assert r.status_code == 401

    r2 = client.get(
        "/api/registry/dump",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r2.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_registry_dump.py -v`
Expected: FAIL — route not registered, returns 404.

- [ ] **Step 3: Implement the route**

In `src/llm_model_probe/api.py`, find the existing `_apply_outcome` definition (around line 476). Anywhere after that and before the static-mount block at the end of the file, add:

```python
from .registry_io import dump_endpoints


@app.get("/api/registry/dump")
def dump_registry(include_keys: bool = False) -> JSONResponse:
    """Return the registry as a downloadable JSON file."""
    store = _store()
    payload = dump_endpoints(
        store.list_endpoints(),
        include_keys=include_keys,
    )
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"llm-model-probe-registry-{today}.json"
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
```

`JSONResponse` is already imported at the top of the file; `datetime` too.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_api_registry_dump.py -v`
Expected: PASS — all four tests.

- [ ] **Step 5: Run the whole backend test suite**

Run: `uv run pytest -q`
Expected: PASS — full suite green; the new code shouldn't have broken anything else.

- [ ] **Step 6: Commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_registry_dump.py
git commit -m "feat(api): GET /api/registry/dump"
```

---

### Task 14: Frontend — `downloadRegistry` API helper

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the helper**

The shared `req<T>` does `r.json()`; for a binary download we need a separate path. Append a top-level export to `frontend/src/lib/api.ts` (alongside the existing `api` object):

```typescript
export async function downloadRegistry(
  includeKeys: boolean,
): Promise<{ blob: Blob; filename: string }> {
  const token = auth.get();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const url = `/api/registry/dump?include_keys=${includeKeys ? "true" : "false"}`;
  const r = await fetch(url, { headers });
  if (r.status === 401) {
    auth.clear();
    throw new UnauthorizedError();
  }
  if (!r.ok) {
    throw new Error(`HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") ?? "";
  const m = cd.match(/filename="([^"]+)"/);
  const filename =
    m?.[1] ??
    `llm-model-probe-registry-${new Date().toISOString().slice(0, 10)}.json`;
  return { blob, filename };
}
```

- [ ] **Step 2: Build to confirm types compile**

Run: `cd frontend && npm run build`
Expected: build succeeds; no new TypeScript errors.
(If the build script is unfamiliar, run `npm run build --silent` from `frontend/` after `npm install` if needed.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(ui): downloadRegistry api helper"
```

---

### Task 15: Frontend — `ExportRegistryButton` component

**Files:**
- Create: `frontend/src/components/ExportRegistryButton.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/ExportRegistryButton.tsx`:

```tsx
import { useState } from "react";
import { downloadRegistry } from "@/lib/api";
import { Icon } from "@/components/atoms";

export default function ExportRegistryButton() {
  const [open, setOpen] = useState(false);
  const [includeKeys, setIncludeKeys] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onDownload() {
    if (busy) return;
    setBusy(true);
    try {
      const { blob, filename } = await downloadRegistry(includeKeys);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch (e) {
      alert(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <button
        className="btn"
        onClick={() => setOpen((v) => !v)}
        title="Export registry to JSON"
      >
        <Icon name="download" size={12} /> Export
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 6px)",
            zIndex: 50,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 12,
            minWidth: 260,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
          }}
        >
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={includeKeys}
              onChange={(e) => setIncludeKeys(e.target.checked)}
            />
            Include API keys
          </label>
          {includeKeys && (
            <p
              style={{
                margin: "6px 0 0",
                fontSize: 11,
                color: "var(--bad)",
              }}
            >
              Plaintext keys will be written to the file.
            </p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn"
              onClick={() => setOpen(false)}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={onDownload}
              disabled={busy}
            >
              {busy ? "Downloading…" : "Download"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

If the `download` icon isn't already in `@/components/atoms` `Icon`, check first by reading that file:

```bash
grep -n "name === " frontend/src/components/atoms.tsx | head -30
```

If `download` is missing, add it to the icon switch in `atoms.tsx` (using the same SVG-path pattern as the existing icons — copy a Heroicons / Phosphor "arrow-down-tray" or "download" path, e.g.:

```tsx
case "download":
  return (
    <path
      d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  );
```

— matching whatever inline pattern the existing icons use). If you're unsure of the exact pattern, reuse an existing icon name like `refresh` instead so styling stays consistent. The visual choice is not load-bearing for the feature.

- [ ] **Step 2: Build to verify the component compiles**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ExportRegistryButton.tsx frontend/src/components/atoms.tsx
git commit -m "feat(ui): ExportRegistryButton component"
```

(Skip `atoms.tsx` from the add list if you didn't end up modifying it.)

---

### Task 16: Wire `ExportRegistryButton` into `TopBar`

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Import and render the button**

In `frontend/src/App.tsx`, add this import alongside the other component imports (near the top):

```tsx
import ExportRegistryButton from "@/components/ExportRegistryButton";
```

In the `TopBar` JSX (around line 282 onwards, between `ThemeToggle` and the `Retest all` button), insert the new button:

```tsx
      <ThemeToggle />
      <ExportRegistryButton />
      <button
        className="btn"
        onClick={onRetestAll}
        ...
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build`
Expected: success, no TypeScript errors.

- [ ] **Step 3: Manual smoke test**

Run the backend in dev mode and the frontend dev server in two terminals:

```bash
# Terminal 1
uv run probe ui --dev --no-browser

# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:5173. Confirm:
- The `Export` button appears in the top bar
- Clicking it opens the popover with the `Include API keys` checkbox
- Clicking `Download` triggers a file download named `llm-model-probe-registry-YYYY-MM-DD.json`
- Opening the downloaded file shows `api_key: null` for every endpoint
- Repeating with `Include API keys` checked produces a file with real keys

If you can't run a browser in this environment, say so explicitly in the task hand-off — the test suite alone doesn't validate UI behavior end-to-end.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(ui): mount ExportRegistryButton in topbar"
```

---

### Task 17: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a section after the existing `## Web UI` block**

In `README.md`, find the `## Docker` section header. Just before it, insert:

```markdown
## Migrating between machines (dump / load)

The registry (endpoints + their api keys) lives in `~/.llm-model-probe/probes.db`. To move it to another machine — for example, when your test box and prod box drifted — use `probe dump` and `probe load`:

```bash
# On the source machine
probe dump --include-keys -o registry.json
scp registry.json prod-box:/tmp/

# On the destination
probe load /tmp/registry.json                       # default: skip name conflicts
probe load /tmp/registry.json --on-conflict=replace # overwrite local on conflict
probe load /tmp/registry.json --on-conflict=error   # abort if any conflict
```

By default `probe dump` writes `api_key: null` for every endpoint — safe to commit, share, or sync. Pass `--include-keys` to include plaintext keys; the output file is `chmod 0600`.

The web UI has a matching `Export` button (with the same `Include API keys` checkbox). There is no UI import — load is a CLI-only operation.

The dump format is endpoints-only: probe results, the discover-time filter list, and machine-local settings are not included. Run `probe retest --all` after a load to re-derive results.
```

- [ ] **Step 2: Verify Markdown renders cleanly**

Run a quick check:

```bash
grep -n "^## " README.md | head -20
```

Expected: the new `## Migrating between machines (dump / load)` heading appears between `## Web UI` (or its surrounding sections) and `## Docker`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: probe dump/load for cross-machine migration"
```

---

### Task 18: Final integration check

- [ ] **Step 1: Run full backend suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Round-trip smoke test (manual)**

```bash
# In an isolated home, end-to-end verify dump → load is lossless when no conflicts
LLM_MODEL_PROBE_HOME=/tmp/probe-test-A uv run probe add \
    --name smoke --sdk openai \
    --base-url https://api.example.com/v1 \
    --api-key sk-fake \
    --no-probe
LLM_MODEL_PROBE_HOME=/tmp/probe-test-A uv run probe dump --include-keys -o /tmp/reg.json
LLM_MODEL_PROBE_HOME=/tmp/probe-test-B uv run probe load /tmp/reg.json
LLM_MODEL_PROBE_HOME=/tmp/probe-test-B uv run probe show smoke
# Expected: 'smoke' appears with the same base_url and (masked) api key.
rm -rf /tmp/probe-test-A /tmp/probe-test-B /tmp/reg.json
```

- [ ] **Step 3: Verify frontend build**

Run: `cd frontend && npm run build`
Expected: clean build, no warnings beyond the existing baseline.

- [ ] **Step 4: No commit needed**

This task is verification only. If any check fails, go back to the responsible task.

---

## Out of scope (unchanged from spec)

- UI import flow
- File-level encryption
- Selective dump (`--tag`, `--name`)
- Exporting `model_results` / `app_settings`
- v2 schema work
- CLI `probe edit` (referenced from load output messaging — `missing_keys` text directs users to the UI)
