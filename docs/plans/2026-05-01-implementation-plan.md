# LLM Model Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CLI tool described in `docs/specs/2026-05-01-design.md`: register OpenAI/Anthropic API endpoints into a local SQLite registry and probe per-model availability on demand.

**Architecture:** Typer CLI dispatches to command handlers. Handlers use `EndpointStore` (SQLite) for persistence and `ProbeRunner` (asyncio + OpenAI/Anthropic async SDKs) for probing. Output goes through `Reporter` for terminal tables (`rich`), markdown, or JSON.

**Tech Stack:** Python 3.11+, uv, typer, rich, openai (async), anthropic (async), tomllib (stdlib), sqlite3 (stdlib), pytest, pytest-asyncio.

---

## File Structure

```
src/llm_model_probe/
  __init__.py        # exports main()
  paths.py           # ~/.llm-model-probe resolution + env override
  settings.py        # config.toml loader (probe + filters sections)
  models.py          # Endpoint, ModelResult dataclasses + id helpers
  store.py           # EndpointStore: SQLite CRUD
  providers.py       # async OpenAI/Anthropic providers (already exists)
  probe.py           # ProbeRunner: list/filter/probe orchestration
  report.py          # rich table + markdown + json renderers
  cli.py             # typer app: add/list/show/retest/rm/export

tests/
  conftest.py        # tmp HOME fixture
  test_paths.py
  test_settings.py
  test_store.py
  test_probe_filter.py
  test_report.py
```

---

## Task 1: Setup test scaffolding & dependency cleanup

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`

- [ ] **Step 1: Remove unused pyyaml, add pytest deps**

```bash
cd ~/Code/Tools/llm-model-probe
uv remove pyyaml
uv add --dev pytest pytest-asyncio
```

- [ ] **Step 2: Configure pytest in pyproject.toml**

Add this block to `pyproject.toml` (append at end):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create test scaffolding**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ~/.llm-model-probe to a tmp dir for the test."""
    home = tmp_path / "probe-home"
    monkeypatch.setenv("LLM_MODEL_PROBE_HOME", str(home))
    return home
```

Create `tests/test_smoke.py`:

```python
def test_package_importable() -> None:
    import llm_model_probe  # noqa: F401
```

- [ ] **Step 4: Run smoke test**

Run: `uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/
git commit -m "chore: 配置 pytest + 移除未使用的 pyyaml"
```

---

## Task 2: paths.py — directory resolution

**Files:**
- Create: `src/llm_model_probe/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_paths.py`:

```python
"""Tests for paths module."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from llm_model_probe.paths import (
    config_path,
    db_path,
    ensure_home,
    resolve_home,
)


def test_resolve_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL_PROBE_HOME", raising=False)
    assert resolve_home() == Path.home() / ".llm-model-probe"


def test_resolve_home_env_override(isolated_home: Path) -> None:
    assert resolve_home() == isolated_home


def test_ensure_home_creates_dir_with_0700(isolated_home: Path) -> None:
    ensure_home()
    assert isolated_home.exists()
    mode = stat.S_IMODE(isolated_home.stat().st_mode)
    assert mode == 0o700


def test_db_and_config_paths(isolated_home: Path) -> None:
    assert db_path() == isolated_home / "probes.db"
    assert config_path() == isolated_home / "config.toml"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_paths.py -q`
Expected: `ImportError: cannot import name '...' from 'llm_model_probe.paths'`

- [ ] **Step 3: Implement paths.py**

Create `src/llm_model_probe/paths.py`:

```python
"""Filesystem path resolution for the probe tool."""
from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "LLM_MODEL_PROBE_HOME"
DEFAULT_DIR_NAME = ".llm-model-probe"
DB_FILENAME = "probes.db"
CONFIG_FILENAME = "config.toml"


def resolve_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIR_NAME


def ensure_home() -> Path:
    home = resolve_home()
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    return home


def db_path() -> Path:
    return resolve_home() / DB_FILENAME


def config_path() -> Path:
    return resolve_home() / CONFIG_FILENAME
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_paths.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/paths.py tests/test_paths.py
git commit -m "feat(paths): 解析数据目录路径并强制 0700 权限"
```

---

## Task 3: settings.py + models.py — config loader and dataclasses

**Files:**
- Create: `src/llm_model_probe/settings.py`, `src/llm_model_probe/models.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settings.py`:

```python
"""Tests for settings loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from llm_model_probe.settings import Settings, load_settings


def test_load_creates_default_when_missing(isolated_home: Path) -> None:
    cfg_path = isolated_home / "config.toml"
    assert not cfg_path.exists()
    settings = load_settings()
    assert cfg_path.exists()
    assert settings.concurrency == 5
    assert settings.timeout_seconds == 30
    assert settings.prompt == "Hi"
    assert "*embedding*" in settings.exclude_patterns


def test_load_respects_overrides(isolated_home: Path) -> None:
    isolated_home.mkdir(parents=True, exist_ok=True)
    (isolated_home / "config.toml").write_text(
        '[probe]\nconcurrency = 12\nprompt = "ping"\n'
        '[filters]\nexclude = ["*foo*"]\n',
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.concurrency == 12
    assert settings.prompt == "ping"
    assert settings.exclude_patterns == ["*foo*"]
    # Other defaults still apply
    assert settings.timeout_seconds == 30


def test_settings_dataclass_defaults() -> None:
    s = Settings()
    assert s.max_tokens == 8
    assert s.retest_cooldown_hours == 24
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_settings.py -q`
Expected: `ImportError`

- [ ] **Step 3: Implement models.py (dataclasses used elsewhere)**

Create `src/llm_model_probe/models.py`:

```python
"""Domain dataclasses."""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SdkType = Literal["openai", "anthropic"]
Mode = Literal["discover", "specified"]
Status = Literal["available", "failed"]
ResultSource = Literal["discovered", "specified"]


def new_endpoint_id() -> str:
    return f"ep_{secrets.token_hex(3)}"


@dataclass
class Endpoint:
    id: str
    name: str
    sdk: SdkType
    base_url: str
    api_key: str
    mode: Mode
    models: list[str] = field(default_factory=list)
    note: str = ""
    list_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ModelResult:
    endpoint_id: str
    model_id: str
    source: ResultSource
    status: Status
    latency_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_preview: str | None = None
    last_tested_at: datetime | None = None
```

- [ ] **Step 4: Implement settings.py**

Create `src/llm_model_probe/settings.py`:

```python
"""Loader for ~/.llm-model-probe/config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import config_path, ensure_home

DEFAULT_EXCLUDE = [
    "*embedding*",
    "*embed*",
    "*whisper*",
    "*tts*",
    "*audio*",
    "*dall-e*",
    "*image*",
    "*moderation*",
    "*rerank*",
]

DEFAULT_TOML = """\
# llm-model-probe configuration
[probe]
concurrency = 5
timeout_seconds = 30
max_tokens = 8
prompt = "Hi"
retest_cooldown_hours = 24

[filters]
exclude = [
    "*embedding*", "*embed*",
    "*whisper*", "*tts*", "*audio*",
    "*dall-e*", "*image*",
    "*moderation*", "*rerank*",
]
"""


@dataclass
class Settings:
    concurrency: int = 5
    timeout_seconds: int = 30
    max_tokens: int = 8
    prompt: str = "Hi"
    retest_cooldown_hours: int = 24
    exclude_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))


def _write_default(path: Path) -> None:
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    path.chmod(0o600)


def load_settings() -> Settings:
    ensure_home()
    path = config_path()
    if not path.exists():
        _write_default(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    probe = data.get("probe") or {}
    filters = data.get("filters") or {}
    return Settings(
        concurrency=int(probe.get("concurrency", 5)),
        timeout_seconds=int(probe.get("timeout_seconds", 30)),
        max_tokens=int(probe.get("max_tokens", 8)),
        prompt=str(probe.get("prompt", "Hi")),
        retest_cooldown_hours=int(probe.get("retest_cooldown_hours", 24)),
        exclude_patterns=list(filters.get("exclude") or DEFAULT_EXCLUDE),
    )
```

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest tests/test_settings.py -q`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add src/llm_model_probe/settings.py src/llm_model_probe/models.py tests/test_settings.py
git commit -m "feat(settings): TOML 配置加载与领域模型 dataclass"
```

---

## Task 4: store.py — SQLite endpoint store

**Files:**
- Create: `src/llm_model_probe/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_store.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_store.py -q`
Expected: `ImportError`

- [ ] **Step 3: Implement store.py**

Create `src/llm_model_probe/store.py`:

```python
"""SQLite-backed registry for endpoints and per-model probe results."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Endpoint, ModelResult
from .paths import db_path, ensure_home

SCHEMA = """
CREATE TABLE IF NOT EXISTS endpoints (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sdk         TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    models_json TEXT NOT NULL DEFAULT '[]',
    note        TEXT NOT NULL DEFAULT '',
    list_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_results (
    endpoint_id      TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    source           TEXT NOT NULL,
    status           TEXT NOT NULL,
    latency_ms       INTEGER,
    error_type       TEXT,
    error_message    TEXT,
    response_preview TEXT,
    last_tested_at   TEXT NOT NULL,
    PRIMARY KEY (endpoint_id, model_id),
    FOREIGN KEY (endpoint_id) REFERENCES endpoints(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_model_results_endpoint
    ON model_results(endpoint_id);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _from_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class EndpointStore:
    def __init__(self, path: Path | None = None) -> None:
        ensure_home()
        self._path = path or db_path()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
        # tighten file perms after first creation
        try:
            self._path.chmod(0o600)
        except FileNotFoundError:
            pass

    # --- endpoints --------------------------------------------------

    def insert_endpoint(self, ep: Endpoint) -> None:
        now = datetime.now()
        ep.created_at = ep.created_at or now
        ep.updated_at = now
        try:
            with self._conn() as c:
                c.execute(
                    """INSERT INTO endpoints
                       (id, name, sdk, base_url, api_key, mode, models_json,
                        note, list_error, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ep.id, ep.name, ep.sdk, ep.base_url, ep.api_key,
                        ep.mode, json.dumps(ep.models), ep.note,
                        ep.list_error, _iso(ep.created_at), _iso(ep.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"endpoint name '{ep.name}' already exists") from e

    def get_endpoint(self, name_or_id: str) -> Endpoint | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM endpoints WHERE id = ? OR name = ?",
                (name_or_id, name_or_id),
            ).fetchone()
        return self._row_to_endpoint(row) if row else None

    def list_endpoints(self) -> list[Endpoint]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM endpoints ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_endpoint(r) for r in rows]

    def delete_endpoint(self, ep_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM endpoints WHERE id = ?", (ep_id,))

    def set_list_error(self, ep_id: str, error: str | None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE endpoints SET list_error = ?, updated_at = ? WHERE id = ?",
                (error, _iso(datetime.now()), ep_id),
            )

    # --- model_results ---------------------------------------------

    def replace_model_results(
        self, ep_id: str, results: list[ModelResult]
    ) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM model_results WHERE endpoint_id = ?", (ep_id,))
            c.executemany(
                """INSERT INTO model_results
                   (endpoint_id, model_id, source, status, latency_ms,
                    error_type, error_message, response_preview, last_tested_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        r.endpoint_id, r.model_id, r.source, r.status,
                        r.latency_ms, r.error_type, r.error_message,
                        r.response_preview, _iso(r.last_tested_at),
                    )
                    for r in results
                ],
            )
            c.execute(
                "UPDATE endpoints SET updated_at = ? WHERE id = ?",
                (_iso(datetime.now()), ep_id),
            )

    def list_model_results(self, ep_id: str) -> list[ModelResult]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM model_results WHERE endpoint_id = ? ORDER BY model_id",
                (ep_id,),
            ).fetchall()
        return [
            ModelResult(
                endpoint_id=r["endpoint_id"],
                model_id=r["model_id"],
                source=r["source"],
                status=r["status"],
                latency_ms=r["latency_ms"],
                error_type=r["error_type"],
                error_message=r["error_message"],
                response_preview=r["response_preview"],
                last_tested_at=_from_iso(r["last_tested_at"]),
            )
            for r in rows
        ]

    def last_tested_at(self, ep_id: str) -> datetime | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(last_tested_at) AS m FROM model_results WHERE endpoint_id = ?",
                (ep_id,),
            ).fetchone()
        return _from_iso(row["m"]) if row and row["m"] else None

    def summary(self, ep_id: str) -> tuple[int, int]:
        """Return (available_count, failed_count)."""
        with self._conn() as c:
            row = c.execute(
                """SELECT
                       SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END) AS bad
                   FROM model_results WHERE endpoint_id = ?""",
                (ep_id,),
            ).fetchone()
        return (int(row["ok"] or 0), int(row["bad"] or 0))

    # --- mapping ----------------------------------------------------

    @staticmethod
    def _row_to_endpoint(row: sqlite3.Row) -> Endpoint:
        return Endpoint(
            id=row["id"],
            name=row["name"],
            sdk=row["sdk"],
            base_url=row["base_url"],
            api_key=row["api_key"],
            mode=row["mode"],
            models=json.loads(row["models_json"]),
            note=row["note"],
            list_error=row["list_error"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_store.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/store.py tests/test_store.py
git commit -m "feat(store): SQLite endpoint + model_results CRUD"
```

---

## Task 5: probe.py — ProbeRunner orchestration

**Files:**
- Modify: `src/llm_model_probe/providers.py` (fix import after config.py removal)
- Create: `src/llm_model_probe/probe.py`
- Test: `tests/test_probe_filter.py`

- [ ] **Step 1: Fix providers.py import**

Edit `src/llm_model_probe/providers.py`: change

```python
from .config import Endpoint
```

to

```python
from .models import Endpoint
```

- [ ] **Step 2: Write failing test for filter**

Create `tests/test_probe_filter.py`:

```python
"""Filter logic tests for probe orchestration."""
from llm_model_probe.probe import filter_models


def test_filter_excludes_patterns() -> None:
    models = ["gpt-4", "text-embedding-3-small", "whisper-1", "gpt-4-turbo"]
    kept, skipped = filter_models(models, exclude=["*embedding*", "*whisper*"])
    assert kept == ["gpt-4", "gpt-4-turbo"]
    assert skipped == ["text-embedding-3-small", "whisper-1"]


def test_filter_no_excludes_keeps_all() -> None:
    models = ["a", "b", "c"]
    kept, skipped = filter_models(models, exclude=[])
    assert kept == ["a", "b", "c"]
    assert skipped == []


def test_filter_case_insensitive() -> None:
    models = ["Embedding-3", "gpt-4"]
    kept, skipped = filter_models(models, exclude=["*embedding*"])
    assert kept == ["gpt-4"]
    assert "Embedding-3" in skipped
```

- [ ] **Step 3: Run test — expect failure**

Run: `uv run pytest tests/test_probe_filter.py -q`
Expected: `ImportError: cannot import name 'filter_models'`

- [ ] **Step 4: Implement probe.py**

Create `src/llm_model_probe/probe.py`:

```python
"""Probing orchestration: list, filter, and concurrently probe models."""
from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass
from datetime import datetime

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .models import Endpoint, ModelResult
from .providers import make_provider
from .settings import Settings


def filter_models(
    models: list[str], exclude: list[str]
) -> tuple[list[str], list[str]]:
    """Return (kept, skipped) preserving original order, case-insensitive."""
    if not exclude:
        return list(models), []
    patterns = [p.lower() for p in exclude]
    kept: list[str] = []
    skipped: list[str] = []
    for m in models:
        if any(fnmatch.fnmatchcase(m.lower(), p) for p in patterns):
            skipped.append(m)
        else:
            kept.append(m)
    return kept, skipped


@dataclass
class ProbeOutcome:
    """Result of probing one endpoint.

    new_results=None means: don't replace prior results (used when
    list_models() fails on a discover-mode retest).
    """
    list_error: str | None
    new_results: list[ModelResult] | None
    skipped: list[str]


class ProbeRunner:
    def __init__(self, settings: Settings, console: Console | None = None) -> None:
        self._settings = settings
        self._console = console or Console()

    async def probe_endpoint(
        self, ep: Endpoint, *, allow_partial: bool = False
    ) -> ProbeOutcome:
        """Probe one endpoint.

        allow_partial=True is set by retest callers: on list_models() failure,
        return new_results=None so the store keeps the prior snapshot.
        """
        provider = make_provider(ep, self._settings.timeout_seconds)
        try:
            if ep.mode == "discover":
                try:
                    discovered = await provider.list_models()
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:200]}"
                    self._console.print(f"[red][{ep.name}] list models failed: {err}[/red]")
                    return ProbeOutcome(
                        list_error=err,
                        new_results=None if allow_partial else [],
                        skipped=[],
                    )
                kept, skipped = filter_models(discovered, self._settings.exclude_patterns)
                source = "discovered"
            else:
                kept = list(ep.models)
                skipped = []
                source = "specified"

            self._console.print(
                f"[cyan][{ep.name}][/cyan] probing {len(kept)} models "
                f"(skipped {len(skipped)} by filter)"
            )
            results = await self._probe_concurrent(ep, kept, source)
            ok = sum(1 for r in results if r.status == "available")
            self._console.print(
                f"[cyan][{ep.name}][/cyan] "
                f"[green]✓ {ok}[/green] / [red]✗ {len(results) - ok}[/red]"
            )
            return ProbeOutcome(list_error=None, new_results=results, skipped=skipped)
        finally:
            await provider.aclose()

    async def _probe_concurrent(
        self, ep: Endpoint, models: list[str], source: str
    ) -> list[ModelResult]:
        if not models:
            return []
        provider = make_provider(ep, self._settings.timeout_seconds)
        sem = asyncio.Semaphore(self._settings.concurrency)

        async def one(model_id: str) -> ModelResult:
            async with sem:
                pr = await provider.probe(
                    model_id, self._settings.prompt, self._settings.max_tokens
                )
            return ModelResult(
                endpoint_id=ep.id,
                model_id=pr.model,
                source=source,  # type: ignore[arg-type]
                status="available" if pr.available else "failed",
                latency_ms=pr.latency_ms,
                error_type=pr.error_type,
                error_message=pr.error_message,
                response_preview=pr.response_preview,
                last_tested_at=datetime.now(),
            )

        try:
            results: list[ModelResult] = []
            with Progress(
                SpinnerColumn(),
                TextColumn(f"[cyan]{ep.name}[/cyan]"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self._console,
                transient=True,
            ) as progress:
                task = progress.add_task("", total=len(models))
                tasks = [asyncio.create_task(one(m)) for m in models]
                for fut in asyncio.as_completed(tasks):
                    results.append(await fut)
                    progress.advance(task)
            results.sort(key=lambda r: r.model_id)
            return results
        finally:
            await provider.aclose()
```

Note: `_probe_concurrent` opens its own provider for clarity. The outer `probe_endpoint` is fine to also create one for `list_models()` — both are async-closed via try/finally.

Actually for cleanliness, let me consolidate: pass the outer provider into `_probe_concurrent` to avoid double-creation. Restructure:

Replace the body of `probe_endpoint` and `_probe_concurrent` with a single integrated version:

```python
    async def probe_endpoint(
        self, ep: Endpoint, *, allow_partial: bool = False
    ) -> ProbeOutcome:
        provider = make_provider(ep, self._settings.timeout_seconds)
        try:
            if ep.mode == "discover":
                try:
                    discovered = await provider.list_models()
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:200]}"
                    self._console.print(f"[red][{ep.name}] list models failed: {err}[/red]")
                    return ProbeOutcome(
                        list_error=err,
                        new_results=None if allow_partial else [],
                        skipped=[],
                    )
                kept, skipped = filter_models(discovered, self._settings.exclude_patterns)
                source: str = "discovered"
            else:
                kept = list(ep.models)
                skipped = []
                source = "specified"

            self._console.print(
                f"[cyan][{ep.name}][/cyan] probing {len(kept)} models "
                f"(skipped {len(skipped)} by filter)"
            )

            results: list[ModelResult] = []
            if kept:
                sem = asyncio.Semaphore(self._settings.concurrency)

                async def one(model_id: str) -> ModelResult:
                    async with sem:
                        pr = await provider.probe(
                            model_id, self._settings.prompt, self._settings.max_tokens
                        )
                    return ModelResult(
                        endpoint_id=ep.id,
                        model_id=pr.model,
                        source=source,  # type: ignore[arg-type]
                        status="available" if pr.available else "failed",
                        latency_ms=pr.latency_ms,
                        error_type=pr.error_type,
                        error_message=pr.error_message,
                        response_preview=pr.response_preview,
                        last_tested_at=datetime.now(),
                    )

                with Progress(
                    SpinnerColumn(),
                    TextColumn(f"[cyan]{ep.name}[/cyan]"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    console=self._console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("", total=len(kept))
                    tasks = [asyncio.create_task(one(m)) for m in kept]
                    for fut in asyncio.as_completed(tasks):
                        results.append(await fut)
                        progress.advance(task)
                results.sort(key=lambda r: r.model_id)

            ok = sum(1 for r in results if r.status == "available")
            self._console.print(
                f"[cyan][{ep.name}][/cyan] "
                f"[green]✓ {ok}[/green] / [red]✗ {len(results) - ok}[/red]"
            )
            return ProbeOutcome(list_error=None, new_results=results, skipped=skipped)
        finally:
            await provider.aclose()
```

Use this single-method version. Drop `_probe_concurrent`.

- [ ] **Step 5: Run filter test — expect pass**

Run: `uv run pytest tests/test_probe_filter.py -q`
Expected: `3 passed`

- [ ] **Step 6: Run full suite to ensure no regression**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/llm_model_probe/probe.py src/llm_model_probe/providers.py tests/test_probe_filter.py
git commit -m "feat(probe): ProbeRunner 编排 + 模型过滤"
```

---

## Task 6: report.py — terminal table & exports

**Files:**
- Create: `src/llm_model_probe/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_report.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/test_report.py -q`
Expected: `ImportError`

- [ ] **Step 3: Implement report.py**

Create `src/llm_model_probe/report.py`:

```python
"""Terminal table + markdown + json rendering."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from rich.console import Console
from rich.table import Table

from .models import Endpoint, ModelResult


@dataclass
class EndpointSnapshot:
    endpoint: Endpoint
    results: list[ModelResult]


def mask_api_key(key: str) -> str:
    if len(key) < 12:
        return "*****"
    return f"{key[:4]}...{key[-4:]}"


def relative_time(when: datetime | None) -> str:
    if not when:
        return "never"
    delta = datetime.now() - when
    seconds = int(delta.total_seconds())
    if seconds < 30:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def render_list_table(
    snapshots: Iterable[EndpointSnapshot], console: Console | None = None
) -> None:
    """Render the `probe list` table to terminal."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("SDK")
    table.add_column("Mode")
    table.add_column("Status", justify="right")
    table.add_column("Tested")
    table.add_column("Note")

    for snap in snapshots:
        ep = snap.endpoint
        ok = sum(1 for r in snap.results if r.status == "available")
        fail = sum(1 for r in snap.results if r.status == "failed")
        if ep.list_error:
            status = "[red]list-error[/red]"
        elif not snap.results:
            status = "[yellow]not probed[/yellow]"
        else:
            status = f"[green]{ok}[/green]/[red]{fail}[/red]"
        latest = max((r.last_tested_at for r in snap.results if r.last_tested_at), default=None)
        table.add_row(
            ep.id,
            ep.name,
            ep.sdk,
            ep.mode,
            status,
            relative_time(latest),
            (ep.note[:40] + "…") if len(ep.note) > 40 else ep.note,
        )

    (console or Console()).print(table)


def render_show(snap: EndpointSnapshot, console: Console | None = None) -> None:
    """Render `probe show <name>` detail view."""
    c = console or Console()
    ep = snap.endpoint
    c.print(f"\n[bold cyan]{ep.name}[/bold cyan] ([dim]{ep.id}[/dim])")
    c.print(f"  SDK     : {ep.sdk}")
    c.print(f"  URL     : {ep.base_url}")
    c.print(f"  API key : {mask_api_key(ep.api_key)}")
    c.print(f"  Mode    : {ep.mode}")
    if ep.note:
        c.print(f"  Note    : {ep.note}")
    if ep.list_error:
        c.print(f"  [red]List error[/red]: {ep.list_error}")
    c.print()

    if not snap.results:
        c.print("[yellow]No probe results yet. Run `probe retest`.[/yellow]")
        return

    ok = [r for r in snap.results if r.status == "available"]
    fail = [r for r in snap.results if r.status == "failed"]

    if ok:
        t = Table(title=f"Available ({len(ok)})", title_style="bold green")
        t.add_column("Model")
        t.add_column("Latency", justify="right")
        t.add_column("Preview")
        for r in ok:
            t.add_row(
                r.model_id,
                f"{r.latency_ms} ms" if r.latency_ms else "-",
                (r.response_preview or "")[:60],
            )
        c.print(t)

    if fail:
        t = Table(title=f"Failed ({len(fail)})", title_style="bold red")
        t.add_column("Model")
        t.add_column("Error")
        t.add_column("Message")
        for r in fail:
            t.add_row(
                r.model_id,
                r.error_type or "-",
                (r.error_message or "")[:80],
            )
        c.print(t)


def render_markdown(snapshots: Iterable[EndpointSnapshot]) -> str:
    snapshots = list(snapshots)
    lines = [
        "# LLM Model Probe Report",
        "",
        f"_Generated: {datetime.now().isoformat(timespec='seconds')}_",
        "",
        "## Summary",
        "",
        "| Endpoint | SDK | Mode | Available | Failed | Tested |",
        "|---|---|---|---:|---:|---|",
    ]
    for snap in snapshots:
        ep = snap.endpoint
        ok = sum(1 for r in snap.results if r.status == "available")
        fail = sum(1 for r in snap.results if r.status == "failed")
        latest = max((r.last_tested_at for r in snap.results if r.last_tested_at), default=None)
        lines.append(
            f"| {ep.name} | {ep.sdk} | {ep.mode} | {ok} | {fail} | {relative_time(latest)} |"
        )
    lines.append("")

    for snap in snapshots:
        ep = snap.endpoint
        lines.append(f"## {ep.name} (`{ep.sdk}`)")
        lines.append("")
        lines.append(f"- Base URL: `{ep.base_url}`")
        lines.append(f"- Mode: `{ep.mode}`")
        if ep.note:
            lines.append(f"- Note: {ep.note}")
        if ep.list_error:
            lines.append(f"- **List error**: `{ep.list_error}`")
        lines.append("")
        ok = [r for r in snap.results if r.status == "available"]
        fail = [r for r in snap.results if r.status == "failed"]
        if ok:
            lines.append(f"### Available ({len(ok)})")
            lines.append("")
            lines.append("| Model | Latency | Preview |")
            lines.append("|---|---:|---|")
            for r in ok:
                preview = (r.response_preview or "").replace("|", "\\|").replace("\n", " ")
                lines.append(f"| `{r.model_id}` | {r.latency_ms} ms | {preview} |")
            lines.append("")
        if fail:
            lines.append(f"### Failed ({len(fail)})")
            lines.append("")
            lines.append("| Model | Error | Message |")
            lines.append("|---|---|---|")
            for r in fail:
                msg = (r.error_message or "").replace("|", "\\|").replace("\n", " ")
                lines.append(f"| `{r.model_id}` | {r.error_type or '-'} | {msg[:140]} |")
            lines.append("")
    return "\n".join(lines)


def render_json(snapshots: Iterable[EndpointSnapshot]) -> str:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "endpoints": [],
    }
    for snap in snapshots:
        ep = snap.endpoint
        payload["endpoints"].append({
            "id": ep.id,
            "name": ep.name,
            "sdk": ep.sdk,
            "base_url": ep.base_url,
            "mode": ep.mode,
            "note": ep.note,
            "list_error": ep.list_error,
            "results": [
                {
                    "model": r.model_id,
                    "source": r.source,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "error_type": r.error_type,
                    "error_message": r.error_message,
                    "response_preview": r.response_preview,
                    "last_tested_at": (
                        r.last_tested_at.isoformat(timespec="seconds")
                        if r.last_tested_at else None
                    ),
                }
                for r in snap.results
            ],
        })
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/test_report.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/report.py tests/test_report.py
git commit -m "feat(report): 终端表格 + markdown + json 输出"
```

---

## Task 7: cli.py — add / list / show commands

**Files:**
- Create: `src/llm_model_probe/cli.py`
- Modify: `src/llm_model_probe/__init__.py`

- [ ] **Step 1: Write `__init__.py` entry**

Replace contents of `src/llm_model_probe/__init__.py`:

```python
"""LLM model availability probe."""
from __future__ import annotations


def main() -> None:
    from .cli import app
    app()
```

- [ ] **Step 2: Implement cli.py with add/list/show**

Create `src/llm_model_probe/cli.py`:

```python
"""Typer-based CLI."""
from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console

from .models import Endpoint, new_endpoint_id
from .probe import ProbeRunner
from .report import EndpointSnapshot, render_list_table, render_show
from .settings import load_settings
from .store import EndpointStore

app = typer.Typer(
    add_completion=False,
    help="Manage and probe OpenAI/Anthropic API endpoints.",
    no_args_is_help=True,
)
console = Console()


def _store() -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _resolve(store: EndpointStore, name_or_id: str) -> Endpoint:
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise typer.BadParameter(f"endpoint '{name_or_id}' not found")
    return ep


def _snapshot(store: EndpointStore, ep: Endpoint) -> EndpointSnapshot:
    return EndpointSnapshot(endpoint=ep, results=store.list_model_results(ep.id))


@app.command()
def add(
    name: str = typer.Option(..., "--name", "-n", help="Alias for this endpoint"),
    sdk: str = typer.Option(..., "--sdk", help="openai | anthropic"),
    base_url: str = typer.Option(..., "--base-url", help="API base URL"),
    api_key: str = typer.Option(..., "--api-key", help="API key"),
    models: Optional[str] = typer.Option(
        None, "--models",
        help="Comma-separated model IDs to probe; if omitted, auto-discover",
    ),
    note: str = typer.Option("", "--note", help="Free-form note"),
    no_probe: bool = typer.Option(
        False, "--no-probe", help="Skip immediate probing"
    ),
) -> None:
    """Register a new endpoint and probe it immediately."""
    if sdk not in ("openai", "anthropic"):
        raise typer.BadParameter(f"sdk must be 'openai' or 'anthropic', got '{sdk}'")
    model_list = [m.strip() for m in (models or "").split(",") if m.strip()]
    mode = "specified" if model_list else "discover"
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk=sdk,  # type: ignore[arg-type]
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        mode=mode,  # type: ignore[arg-type]
        models=model_list,
        note=note,
    )
    store = _store()
    try:
        store.insert_endpoint(ep)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    console.print(
        f"[green]✓[/green] added [bold]{ep.name}[/bold] ({ep.id}) — mode=[bold]{ep.mode}[/bold]"
    )

    if no_probe:
        console.print("[dim]--no-probe set, skipping probe[/dim]")
        return

    settings = load_settings()
    runner = ProbeRunner(settings, console)
    outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=False))
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
        if outcome.new_results is not None:
            store.replace_model_results(ep.id, outcome.new_results)


@app.command(name="list")
def list_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of table"),
) -> None:
    """List all endpoints with current status."""
    store = _store()
    snaps = [_snapshot(store, ep) for ep in store.list_endpoints()]
    if not snaps:
        console.print("[dim]No endpoints registered. Use `probe add ...`.[/dim]")
        return
    if as_json:
        from .report import render_json
        console.print_json(render_json(snaps))
        return
    render_list_table(snaps, console)


@app.command()
def show(
    name_or_id: str = typer.Argument(..., metavar="NAME_OR_ID"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show detailed probe results for one endpoint."""
    store = _store()
    ep = _resolve(store, name_or_id)
    snap = _snapshot(store, ep)
    if as_json:
        from .report import render_json
        console.print_json(render_json([snap]))
        return
    render_show(snap, console)
```

- [ ] **Step 3: Update pyproject entry point**

Open `pyproject.toml`. The existing entry is:

```toml
[project.scripts]
llm-model-probe = "llm_model_probe:main"
```

Add a shorter alias right below it:

```toml
[project.scripts]
llm-model-probe = "llm_model_probe:main"
probe = "llm_model_probe:main"
```

Then re-sync: `uv sync`

- [ ] **Step 4: Smoke test**

Run: `uv run probe --help`
Expected: usage banner showing `add`, `list`, `show` commands.

Run: `uv run probe list`
Expected: `No endpoints registered.` (and a fresh `~/.llm-model-probe/` was created).

- [ ] **Step 5: Commit**

```bash
git add src/llm_model_probe/cli.py src/llm_model_probe/__init__.py pyproject.toml uv.lock
git commit -m "feat(cli): add/list/show 命令 + probe 入口"
```

---

## Task 8: cli.py — retest / rm / export

**Files:**
- Modify: `src/llm_model_probe/cli.py`

- [ ] **Step 1: Append retest, rm, export commands**

Add to bottom of `src/llm_model_probe/cli.py`:

```python
@app.command()
def retest(
    name_or_id: Optional[str] = typer.Argument(
        None, metavar="NAME_OR_ID",
        help="Endpoint to retest; omit and use --all for all endpoints",
    ),
    all_: bool = typer.Option(False, "--all", help="Retest all endpoints"),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Bypass cooldown (retest endpoints tested <24h ago)",
    ),
) -> None:
    """Re-run probing for one or all endpoints."""
    if not name_or_id and not all_:
        raise typer.BadParameter("provide an endpoint name/id or use --all")
    if name_or_id and all_:
        raise typer.BadParameter("--all conflicts with a specific endpoint")

    store = _store()
    settings = load_settings()
    runner = ProbeRunner(settings, console)

    if all_:
        targets = store.list_endpoints()
    else:
        assert name_or_id is not None
        targets = [_resolve(store, name_or_id)]

    if not targets:
        console.print("[dim]No endpoints to retest.[/dim]")
        return

    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(hours=settings.retest_cooldown_hours)
    skipped: list[str] = []
    todo: list[Endpoint] = []
    for ep in targets:
        last = store.last_tested_at(ep.id)
        if all_ and not force and last and last >= cutoff:
            skipped.append(ep.name)
        else:
            todo.append(ep)

    for ep in skipped:
        console.print(f"[dim]skip {ep} (within cooldown, use --force to override)[/dim]")

    async def run_all() -> None:
        for ep in todo:
            outcome = await runner.probe_endpoint(ep, allow_partial=True)
            if outcome.list_error:
                store.set_list_error(ep.id, outcome.list_error)
            else:
                store.set_list_error(ep.id, None)
            if outcome.new_results is not None:
                store.replace_model_results(ep.id, outcome.new_results)

    asyncio.run(run_all())
    console.print(
        f"[green]✓[/green] retested {len(todo)} endpoint(s)"
        f"{f', skipped {len(skipped)}' if skipped else ''}"
    )


@app.command()
def rm(
    name_or_id: str = typer.Argument(..., metavar="NAME_OR_ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove an endpoint (and its probe results)."""
    store = _store()
    ep = _resolve(store, name_or_id)
    if not yes:
        confirm = typer.confirm(f"Delete '{ep.name}' ({ep.id})?")
        if not confirm:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(0)
    store.delete_endpoint(ep.id)
    console.print(f"[green]✓[/green] removed {ep.name}")


@app.command()
def export(
    name_or_id: Optional[str] = typer.Argument(
        None, metavar="NAME_OR_ID",
        help="Specific endpoint; omit for all",
    ),
    fmt: str = typer.Option("md", "--format", "-f", help="md | json"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file; default stdout",
    ),
) -> None:
    """Export probe report as Markdown or JSON."""
    if fmt not in ("md", "json"):
        raise typer.BadParameter("format must be 'md' or 'json'")
    store = _store()
    if name_or_id:
        snaps = [_snapshot(store, _resolve(store, name_or_id))]
    else:
        snaps = [_snapshot(store, ep) for ep in store.list_endpoints()]

    from .report import render_json, render_markdown
    text = render_markdown(snaps) if fmt == "md" else render_json(snaps)

    if output:
        from pathlib import Path
        Path(output).write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/green] wrote {output}")
    else:
        print(text)
```

- [ ] **Step 2: Smoke test the new commands**

Run: `uv run probe --help`
Expected: now shows `retest`, `rm`, `export` too.

Run: `uv run probe retest --all`
Expected: `No endpoints to retest.`

Run: `uv run probe export --format json`
Expected: JSON with empty `endpoints` array.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/llm_model_probe/cli.py
git commit -m "feat(cli): retest/rm/export 命令"
```

---

## Task 9: README + final smoke

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` (already exists; verify)

- [ ] **Step 1: Verify .gitignore covers reports/ and any local config**

Read current `.gitignore`. If it doesn't include the following, append them:

```
# llm-model-probe local outputs
reports/
*.local.toml
```

- [ ] **Step 2: Replace README.md**

Overwrite `README.md`:

```markdown
# llm-model-probe

CLI tool to register OpenAI/Anthropic API endpoints into a local SQLite registry
and probe per-model availability on demand.

Built for the workflow: someone hands over a `(base_url, api_key)`, you want
to know which models actually work — now and again next week.

## Install

```bash
git clone <this repo>
cd llm-model-probe
uv sync
uv run probe --help
```

For a global install:

```bash
uv tool install --from . llm-model-probe
probe --help
```

## Quick Start

```bash
# 1. Add an endpoint, auto-discover models, probe immediately
probe add --name bob-glm --sdk openai \
  --base-url https://glm.example.com/v1 \
  --api-key "$GLM_KEY" \
  --note "from Bob 2026-05-01"

# 2. Add an endpoint with specified models (skip discovery)
probe add --name partner-claude --sdk anthropic \
  --base-url https://api.anthropic.com \
  --api-key "$CLAUDE_KEY" \
  --models claude-3-5-sonnet-latest,claude-3-haiku-20240307

# 3. See registry overview
probe list

# 4. Detailed view (model-level status)
probe show bob-glm

# 5. Re-probe one endpoint, or all (24h cooldown unless --force)
probe retest bob-glm
probe retest --all

# 6. Export a report
probe export --format md -o report.md
probe export --format json | jq .

# 7. Remove an endpoint
probe rm bob-glm
```

## Configuration

First run creates `~/.llm-model-probe/config.toml`. Edit it to tune probe
behavior:

```toml
[probe]
concurrency = 5            # parallel probes per endpoint
timeout_seconds = 30
max_tokens = 8             # ask for a tiny completion only
prompt = "Hi"
retest_cooldown_hours = 24 # skip --all retest within this window

[filters]
exclude = [                # discover-mode skip list (fnmatch, case-insensitive)
    "*embedding*", "*whisper*", "*tts*", "*image*",
    "*moderation*", "*rerank*",
]
```

Override the data directory via `LLM_MODEL_PROBE_HOME=/some/path`.

## Storage

| Path | Purpose |
|---|---|
| `~/.llm-model-probe/probes.db` | SQLite registry (perms 0600) |
| `~/.llm-model-probe/config.toml` | Global probe + filter settings |

API keys are stored as plaintext in SQLite. The directory is `0700` and
the DB file is `0600`. Don't sync this directory to anything you don't trust.
The CLI masks keys in display (`sk-1...wxyz`).

## Discover vs Specified

- **Discover mode** (default): on `add`, calls `models.list()` and probes
  every returned model against the global filter. Best when the provider's
  `/v1/models` is honest.
- **Specified mode**: pass `--models a,b,c`. The list endpoint isn't called;
  filter is bypassed; only those models are probed. Use this for proxies that
  return fake models or hide them.

You can switch modes by `rm`-ing and `add`-ing again.

## Probe Semantics

- OpenAI: `chat.completions.create(model=…, messages=[{"role":"user","content":prompt}], max_tokens=8)`. On reasoning-model `max_completion_tokens` errors, retries with that param instead.
- Anthropic: `messages.create(model=…, max_tokens=8, messages=[…])`.
- Captures: success bool, latency, error class + message, first ~80 chars of response.
- `models.list()` failure on retest keeps the prior snapshot so you don't lose data when a key briefly fails.

## Project Layout

```
src/llm_model_probe/
  paths.py     # ~/.llm-model-probe resolution
  settings.py  # config.toml loader
  models.py    # Endpoint, ModelResult dataclasses
  store.py     # SQLite layer
  providers.py # async OpenAI/Anthropic SDK wrappers
  probe.py     # ProbeRunner: list/filter/probe orchestration
  report.py    # rich tables + markdown + json
  cli.py       # typer commands
docs/
  specs/       # design docs
  plans/       # implementation plans
tests/         # pytest suite
```

## Testing

```bash
uv run pytest -q
```

## Out of Scope

Web UI, time-series history, scheduled probing, encrypted-at-rest keys.
See `docs/specs/2026-05-01-design.md` for the full design rationale.
```

- [ ] **Step 3: Final smoke test sequence**

Run sequence in shell:

```bash
cd ~/Code/Tools/llm-model-probe

# Use a tmp home so we don't pollute real ~/.llm-model-probe during smoke
export LLM_MODEL_PROBE_HOME="$(mktemp -d)/probe-home"
trap 'rm -rf "$LLM_MODEL_PROBE_HOME"' EXIT

uv run probe --help
uv run probe list                    # empty registry message
uv run probe add --name fake --sdk openai \
    --base-url https://invalid.example.com/v1 \
    --api-key sk-fake \
    --models a,b \
    --note "smoke" \
    --no-probe
uv run probe list                    # shows 'fake' as 'not probed'
uv run probe show fake               # shows specified models, no results
uv run probe rm fake -y
uv run probe list                    # empty again
unset LLM_MODEL_PROBE_HOME
```

Expected: all commands exit 0 and show sensible output.

- [ ] **Step 4: Run full test suite one more time**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: README 使用说明 + 收尾"
```

---

## Self-Review (post-write)

Spec coverage check (against `docs/specs/2026-05-01-design.md`):

- ✅ Goal & Non-Goals: README + tasks reflect them.
- ✅ Architecture: tasks build CLI → handlers → Store + ProbeRunner → Reporter.
- ✅ Data model: Task 4 schema matches spec exactly.
- ✅ CLI commands `add / list / show / retest / rm / export`: Tasks 7–8.
- ✅ Probe semantics (filter, list_error retention, max_completion_tokens retry): Tasks 5 + reused providers.py.
- ✅ Storage layout (`~/.llm-model-probe`, perms): Tasks 2 + 4.
- ✅ Configuration (`config.toml` defaults): Task 3.
- ✅ File layout: matches spec.
- ✅ Error handling table: covered by `add` conflict, `_resolve`, list_error path, sqlite OperationalError surfaces from default sqlite3.
- ✅ Testing: Task 1 sets up pytest; tasks 2–6 each have TDD tests.
- ✅ Documentation (README): Task 9.

Type/name consistency:
- `EndpointSnapshot.results` (list[ModelResult]), `ModelResult.model_id` (not `model.id`), `Endpoint.id` — used consistently across store/probe/report/cli.
- `ProbeOutcome.new_results: list[ModelResult] | None` — consumers handle the None branch in `add` (passes allow_partial=False so it's empty list, not None) and `retest` (passes allow_partial=True).

No placeholders; every code step has full code. Ready for execution.
