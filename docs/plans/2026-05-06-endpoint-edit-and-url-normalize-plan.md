# Endpoint 编辑 + base_url 软规范化 — 实施计划

> **给 agent 用**：用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 一个任务一个任务地执行。每步用 `- [ ]` 复选框跟踪。

**目标**：实现 `docs/specs/2026-05-06-endpoint-edit-and-url-normalize-design.md` —— 让用户能编辑已存在的 endpoint（name/sdk/base_url/api_key/note），并在创建/编辑时自动剥掉常见的"完整接口 URL 尾巴"（如 `/chat/completions`、`/messages`），同时修复 `_parse_curl` 对非 `/v1` URL 的同源 bug。

**架构**：后端加一列 `stale_since` + 一个新 `PATCH` 路由 + 一个共享的 `normalize_base_url()` 纯函数（被 POST/PATCH/_parse_curl 三处复用）。前端抽出一个 `<BaseUrlInput>` 组件做实时 URL 提示，复用 `AddEndpointDialog` 加 `mode: "add" | "edit"` 分支，drawer 加 stale banner + 灰徽章 + 编辑入口。

**技术栈**：FastAPI / Pydantic / sqlite3（后端），React + TypeScript + shadcn/ui + @tanstack/react-query（前端）。

---

## 文件结构

```
src/llm_model_probe/
├── models.py             # 修改: Endpoint 加 stale_since 字段
├── store.py              # 修改: schema migration + update_endpoint() 方法
└── api.py                # 修改: normalize_base_url + PATCH 路由 + create flow + _apply_outcome + _parse_curl

tests/
├── test_url_normalize.py     # 新建: normalize_base_url 单元测试
├── test_store.py             # 修改: stale_since 持久化 + update_endpoint
├── test_api_endpoints.py     # 修改: PATCH scenarios + retest 清 stale + POST 规范化
└── test_api_parse.py         # 修改: 智谱 curl 回归测试

frontend/src/
├── lib/
│   ├── types.ts                       # 修改: EndpointSummary 加 stale_since; 新增 EndpointUpdate
│   └── api.ts                         # 修改: patchEndpoint
├── components/
│   ├── BaseUrlInput.tsx               # 新建: input + live hint + 采用按钮
│   ├── AddEndpointDialog.tsx          # 修改: 参数化为 mode: "add" | "edit"
│   ├── EndpointDetailDrawer.tsx       # 修改: 编辑入口 + stale banner + 灰徽章
│   └── EndpointTable.tsx              # 修改: 名字列加 stale 小灰点
```

---

## Task 1: `normalize_base_url()` 纯函数 + 单测

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 新建: `tests/test_url_normalize.py`

- [ ] **步骤 1：写测试**

新建 `tests/test_url_normalize.py`：

```python
"""Unit tests for normalize_base_url."""
from __future__ import annotations

import pytest

from llm_model_probe.api import normalize_base_url


@pytest.mark.parametrize(
    "input_url,expected",
    [
        # Standard OpenAI - longest suffix wins
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1",
        ),
        # ZhipuAI (non-/v1) - the bug we are fixing
        (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "https://open.bigmodel.cn/api/paas/v4",
        ),
        # Anthropic
        (
            "https://api.anthropic.com/v1/messages",
            "https://api.anthropic.com",
        ),
        ("https://proxy.example/messages", "https://proxy.example"),
        # Legacy /completions
        (
            "https://api.openai.com/v1/completions",
            "https://api.openai.com/v1",
        ),
        # No suffix — base URL pass-through, only trailing / trimmed
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        # Case-insensitive matching, original case preserved on the kept prefix
        (
            "https://api.openai.com/V1/Chat/Completions",
            "https://api.openai.com/V1",
        ),
        # Trailing slash + suffix combo
        (
            "https://api.openai.com/v1/chat/completions/",
            "https://api.openai.com/v1",
        ),
    ],
)
def test_normalize_base_url(input_url: str, expected: str) -> None:
    assert normalize_base_url(input_url) == expected
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_url_normalize.py -v
```

预期：`ImportError: cannot import name 'normalize_base_url' from 'llm_model_probe.api'`

- [ ] **步骤 3：写实现**

在 `src/llm_model_probe/api.py` 顶部（紧跟其它 `import` 之后、`DEV_MODE = ...` 之前）插入：

```python
_STRIP_SUFFIXES = (
    "/v1/chat/completions",
    "/chat/completions",
    "/v1/messages",
    "/messages",
    "/v1/completions",
    "/completions",
)


def normalize_base_url(url: str) -> str:
    """Strip well-known completion-endpoint suffixes from a base URL.

    Iterates _STRIP_SUFFIXES which is ordered so that any '/vN/X' variant is
    listed before plain '/X' — first match wins, longest suffix lands first.
    """
    s = url.rstrip("/")
    lowered = s.lower()
    for suffix in _STRIP_SUFFIXES:
        if lowered.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.rstrip("/")
```

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_url_normalize.py -v
```

预期：9 cases all PASS。

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_url_normalize.py
git commit -m "feat(api): normalize_base_url helper for stripping completion suffixes"
```

---

## Task 2: `stale_since` 列迁移 + dataclass 字段

**文件**：
- 修改: `src/llm_model_probe/models.py`
- 修改: `src/llm_model_probe/store.py`
- 修改: `tests/test_store.py`

- [ ] **步骤 1：写测试**

在 `tests/test_store.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_store.py::test_stale_since_roundtrip -v
```

预期：`AttributeError: 'Endpoint' object has no attribute 'stale_since'`（或 `TypeError` on dataclass init）。

- [ ] **步骤 3：改 dataclass**

`src/llm_model_probe/models.py` 的 `Endpoint` dataclass：

```python
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
    tags: list[str] = field(default_factory=list)
    stale_since: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **步骤 4：改 schema + migration + insert + row mapping**

`src/llm_model_probe/store.py`：

(a) `SCHEMA` 常量里 `endpoints` 表新增 `stale_since` 列：

```python
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
    tags_json   TEXT NOT NULL DEFAULT '[]',
    stale_since TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
... (model_results 表不变)
"""
```

(b) 加新的迁移方法（紧跟 `_migrate_tags`）：

```python
@staticmethod
def _migrate_stale_since(c: sqlite3.Connection) -> None:
    """Old DB without stale_since column - idempotently add it."""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
    if "stale_since" not in cols:
        c.execute(
            "ALTER TABLE endpoints ADD COLUMN stale_since TEXT"
        )
```

(c) `init_schema()` 里调用，紧跟 `_migrate_tags(c)`：

```python
def init_schema(self) -> None:
    with self._conn() as c:
        c.executescript(SCHEMA)
        self._migrate_tags(c)
        self._migrate_stale_since(c)
        self._backfill_models_from_results(c)
    try:
        self._path.chmod(0o600)
    except FileNotFoundError:
        pass
```

(d) `insert_endpoint` 的 SQL 加列：

```python
def insert_endpoint(self, ep: Endpoint) -> None:
    now = datetime.now()
    ep.created_at = ep.created_at or now
    ep.updated_at = now
    try:
        with self._conn() as c:
            c.execute(
                """INSERT INTO endpoints
                   (id, name, sdk, base_url, api_key, mode, models_json,
                    note, list_error, tags_json, stale_since,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ep.id, ep.name, ep.sdk, ep.base_url, ep.api_key,
                    ep.mode, json.dumps(ep.models), ep.note,
                    ep.list_error, json.dumps(ep.tags),
                    _iso(ep.stale_since),
                    _iso(ep.created_at), _iso(ep.updated_at),
                ),
            )
    except sqlite3.IntegrityError as e:
        raise ValueError(f"endpoint name '{ep.name}' already exists") from e
```

(e) `_row_to_endpoint`：

```python
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
        tags=json.loads(row["tags_json"]),
        stale_since=_from_iso(row["stale_since"]),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
    )
```

- [ ] **步骤 5：跑测试**

```
uv run pytest tests/test_store.py -v
```

预期：新 3 个测试 + 所有原有 store 测试 PASS。

- [ ] **步骤 6：commit**

```bash
git add src/llm_model_probe/models.py src/llm_model_probe/store.py tests/test_store.py
git commit -m "feat(store): add stale_since column + dataclass field"
```

---

## Task 3: `EndpointStore.update_endpoint()` 部分更新

**文件**：
- 修改: `src/llm_model_probe/store.py`
- 修改: `tests/test_store.py`

- [ ] **步骤 1：写测试**

在 `tests/test_store.py` 末尾追加：

```python
def test_update_endpoint_partial(store: EndpointStore) -> None:
    ep = _ep("editme")
    store.insert_endpoint(ep)
    store.update_endpoint(ep.id, name="renamed", note="new note")
    got = store.get_endpoint(ep.id)
    assert got is not None
    assert got.name == "renamed"
    assert got.note == "new note"
    assert got.base_url == "https://api.example.com/v1"  # untouched


def test_update_endpoint_no_fields_is_noop(store: EndpointStore) -> None:
    ep = _ep("noop")
    store.insert_endpoint(ep)
    before = store.get_endpoint(ep.id)
    store.update_endpoint(ep.id)  # no kwargs
    after = store.get_endpoint(ep.id)
    assert before == after  # updated_at didn't bump


def test_update_endpoint_set_stale_since(store: EndpointStore) -> None:
    ep = _ep("stalebump")
    store.insert_endpoint(ep)
    when = datetime(2026, 5, 6, 10, 0, 0)
    store.update_endpoint(ep.id, stale_since=when)
    got = store.get_endpoint(ep.id)
    assert got is not None
    assert got.stale_since == when


def test_update_endpoint_clear_stale_since(store: EndpointStore) -> None:
    ep = _ep("staleclear")
    ep.stale_since = datetime(2026, 5, 6, 10, 0, 0)
    store.insert_endpoint(ep)
    store.update_endpoint(ep.id, stale_since=None)
    got = store.get_endpoint(ep.id)
    assert got is not None
    assert got.stale_since is None


def test_update_endpoint_name_conflict(store: EndpointStore) -> None:
    a = _ep("alpha"); b = _ep("beta")
    store.insert_endpoint(a)
    store.insert_endpoint(b)
    with pytest.raises(ValueError, match="already in use|already exists"):
        store.update_endpoint(b.id, name="alpha")
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_store.py::test_update_endpoint_partial -v
```

预期：`AttributeError: 'EndpointStore' object has no attribute 'update_endpoint'`。

- [ ] **步骤 3：写实现**

在 `src/llm_model_probe/store.py` 文件顶部（其它 `import` 后面）加哨兵：

```python
_UNSET: object = object()
```

在 `EndpointStore` 类内（紧跟 `set_tags` 之后）加方法：

```python
def update_endpoint(
    self,
    ep_id: str,
    *,
    name: str | None = None,
    sdk: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    note: str | None = None,
    stale_since: object = _UNSET,
) -> None:
    """Partial update.

    For str fields, None means "leave unchanged".
    For stale_since, the default sentinel means "leave unchanged"; pass
    a datetime to set, or None to explicitly clear.
    """
    sets: list[str] = []
    params: list = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if sdk is not None:
        sets.append("sdk = ?")
        params.append(sdk)
    if base_url is not None:
        sets.append("base_url = ?")
        params.append(base_url)
    if api_key is not None:
        sets.append("api_key = ?")
        params.append(api_key)
    if note is not None:
        sets.append("note = ?")
        params.append(note)
    if stale_since is not _UNSET:
        sets.append("stale_since = ?")
        params.append(_iso(stale_since) if stale_since is not None else None)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_iso(datetime.now()))
    params.append(ep_id)
    sql = f"UPDATE endpoints SET {', '.join(sets)} WHERE id = ?"
    try:
        with self._conn() as c:
            c.execute(sql, params)
    except sqlite3.IntegrityError as e:
        raise ValueError(
            f"endpoint name conflict (likely '{name}' already in use)"
        ) from e
```

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_store.py -v
```

预期：所有 store 测试 PASS。

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/store.py tests/test_store.py
git commit -m "feat(store): update_endpoint partial-update with stale_since sentinel"
```

---

## Task 4: POST `/api/endpoints` 调用 `normalize_base_url`

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 修改: `tests/test_api_endpoints.py`

- [ ] **步骤 1：写测试**

在 `tests/test_api_endpoints.py` 末尾追加：

```python
def test_create_endpoint_normalizes_base_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/endpoints strips known completion-endpoint suffixes."""
    # Stub list_models so create doesn't hit the network
    async def _stub_list_models(self):  # type: ignore[no-untyped-def]
        return ["gpt-4"]
    from llm_model_probe.providers import OpenAIProvider
    monkeypatch.setattr(OpenAIProvider, "list_models", _stub_list_models)

    r = client.post(
        "/api/endpoints",
        json={
            "name": "zhipu",
            "sdk": "openai",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "api_key": "k",
            "no_probe": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_api_endpoints.py::test_create_endpoint_normalizes_base_url -v
```

预期：assertion fail，`base_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"`（保留了原值，因为还没接上规范化）。

- [ ] **步骤 3：在 `create_endpoint` 里调 `normalize_base_url`**

`src/llm_model_probe/api.py` 中 `create_endpoint`：

```python
@app.post(
    "/api/endpoints",
    response_model=EndpointDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_endpoint(payload: EndpointCreate) -> EndpointDetail:
    store = _store()
    mode = "specified" if payload.models else "discover"
    base_url = normalize_base_url(str(payload.base_url).rstrip("/"))
    ep = Endpoint(
        id=new_endpoint_id(),
        name=payload.name,
        sdk=payload.sdk,
        base_url=base_url,
        api_key=payload.api_key,
        mode=mode,  # type: ignore[arg-type]
        models=list(payload.models),
        note=payload.note,
        tags=_normalize_tags(payload.tags),
    )
    # ... rest unchanged ...
```

（替换原本那行 `base_url=str(payload.base_url).rstrip("/")` 为先经 `normalize_base_url`。）

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_api_endpoints.py -v
```

预期：所有 endpoints 测试 PASS。

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): apply normalize_base_url on POST /api/endpoints"
```

---

## Task 5: response schemas 加 `stale_since`

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 修改: `tests/test_api_endpoints.py`

- [ ] **步骤 1：写测试**

在 `tests/test_api_endpoints.py` 末尾追加：

```python
def test_endpoint_summary_includes_stale_since(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """A freshly seeded endpoint has stale_since=None and the API surfaces it."""
    _seed_endpoint(seed_store, "alpha")
    r = client.get("/api/endpoints")
    assert r.status_code == 200
    item = r.json()[0]
    assert "stale_since" in item
    assert item["stale_since"] is None


def test_endpoint_detail_includes_stale_since(
    client: TestClient, seed_store: EndpointStore
) -> None:
    _seed_endpoint(seed_store, "beta")
    r = client.get("/api/endpoints/beta")
    assert r.status_code == 200
    body = r.json()
    assert "stale_since" in body
    assert body["stale_since"] is None
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_api_endpoints.py::test_endpoint_summary_includes_stale_since -v
```

预期：KeyError on "stale_since"（schema 还没字段，序列化时就丢了）。

- [ ] **步骤 3：改 schema + helper**

`src/llm_model_probe/api.py` 中 `EndpointSummary`：

```python
class EndpointSummary(BaseModel):
    id: str
    name: str
    sdk: SdkType
    base_url: str
    mode: Mode
    note: str
    list_error: str | None
    available: int
    failed: int
    total_models: int
    tags: list[str]
    last_tested_at: datetime | None
    stale_since: datetime | None
    created_at: datetime
    updated_at: datetime
```

`_summary` helper：

```python
def _summary(store: EndpointStore, ep: Endpoint) -> EndpointSummary:
    ok, fail = store.summary(ep.id)
    return EndpointSummary(
        id=ep.id,
        name=ep.name,
        sdk=ep.sdk,
        base_url=ep.base_url,
        mode=ep.mode,
        note=ep.note,
        list_error=ep.list_error,
        available=ok,
        failed=fail,
        total_models=len(ep.models),
        tags=ep.tags,
        last_tested_at=store.last_tested_at(ep.id),
        stale_since=ep.stale_since,
        created_at=ep.created_at or datetime.now(),
        updated_at=ep.updated_at or datetime.now(),
    )
```

`EndpointDetail` 继承 `EndpointSummary`，自动得到字段，无需改。

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_api_endpoints.py -v
```

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): expose stale_since on EndpointSummary/Detail"
```

---

## Task 6: PATCH `/api/endpoints/{id}` 路由

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 修改: `tests/test_api_endpoints.py`

这个 task 比较大，但所有改动是新增一个 schema、一个路由处理函数 + 一组测试。中间不会让代码处于半成品状态，所以单 commit。

- [ ] **步骤 1：写测试**

在 `tests/test_api_endpoints.py` 末尾追加：

```python
def test_patch_endpoint_updates_note(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "ep1")
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"note": "updated"},
    )
    assert r.status_code == 200
    assert r.json()["note"] == "updated"
    assert r.json()["stale_since"] is None  # note 改不算 core


def test_patch_endpoint_base_url_triggers_stale(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "ep2")
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"base_url": "https://api.other.com/v1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://api.other.com/v1"
    assert body["stale_since"] is not None


def test_patch_endpoint_sdk_triggers_stale(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "ep3")
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"sdk": "anthropic"},
    )
    assert r.status_code == 200
    assert r.json()["sdk"] == "anthropic"
    assert r.json()["stale_since"] is not None


def test_patch_endpoint_api_key_triggers_stale(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "ep4")
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"api_key": "sk-newvalue"},
    )
    assert r.status_code == 200
    assert r.json()["stale_since"] is not None
    # detail still masks; verify via raw store
    fresh = seed_store.get_endpoint(ep.id)
    assert fresh is not None
    assert fresh.api_key == "sk-newvalue"


def test_patch_endpoint_normalizes_base_url(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "ep5")
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions"},
    )
    assert r.status_code == 200
    assert r.json()["base_url"] == "https://open.bigmodel.cn/api/paas/v4"


def test_patch_endpoint_base_url_normalized_equals_existing_no_stale(
    client: TestClient, seed_store: EndpointStore
) -> None:
    """If user submits a "completions URL" that normalizes back to the
    current base_url, no stale flag should fire."""
    ep = _seed_endpoint(seed_store, "ep6")
    # ep.base_url = "https://api.example.com/v1"
    r = client.patch(
        f"/api/endpoints/{ep.id}",
        json={"base_url": "https://api.example.com/v1/chat/completions"},
    )
    assert r.status_code == 200
    assert r.json()["base_url"] == "https://api.example.com/v1"
    assert r.json()["stale_since"] is None


def test_patch_endpoint_rename_to_existing_409(
    client: TestClient, seed_store: EndpointStore
) -> None:
    _seed_endpoint(seed_store, "alpha")
    e2 = _seed_endpoint(seed_store, "bravo")
    r = client.patch(f"/api/endpoints/{e2.id}", json={"name": "alpha"})
    assert r.status_code == 409


def test_patch_endpoint_rename_to_self_ok(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "samename")
    r = client.patch(
        f"/api/endpoints/{ep.id}", json={"name": "samename"}
    )
    assert r.status_code == 200


def test_patch_endpoint_empty_body_noop(
    client: TestClient, seed_store: EndpointStore
) -> None:
    ep = _seed_endpoint(seed_store, "noop")
    r = client.patch(f"/api/endpoints/{ep.id}", json={})
    assert r.status_code == 200


def test_patch_endpoint_404(client: TestClient) -> None:
    r = client.patch("/api/endpoints/nope", json={"note": "x"})
    assert r.status_code == 404
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_api_endpoints.py::test_patch_endpoint_updates_note -v
```

预期：`405 Method Not Allowed`（路由还不存在）。

- [ ] **步骤 3：加 Pydantic schema + 路由处理函数**

`src/llm_model_probe/api.py` 中（紧跟 `class EndpointCreate` 后）加：

```python
class EndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    sdk: SdkType | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    note: str | None = None
```

紧跟 `delete_endpoint` 路由后（约 `api.py:325` 处）加：

```python
@app.patch(
    "/api/endpoints/{name_or_id}",
    response_model=EndpointDetail,
)
def update_endpoint_route(
    name_or_id: str, payload: EndpointUpdate
) -> EndpointDetail:
    store = _store()
    existing = store.get_endpoint(name_or_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="endpoint not found")

    new_name = payload.name
    new_sdk = payload.sdk
    new_base_url = (
        normalize_base_url(str(payload.base_url))
        if payload.base_url is not None
        else None
    )
    new_api_key = payload.api_key
    new_note = payload.note

    # Name uniqueness — same name as self is fine
    if new_name is not None and new_name != existing.name:
        other = store.get_endpoint(new_name)
        if other is not None and other.id != existing.id:
            raise HTTPException(
                status_code=409,
                detail=f"name '{new_name}' already in use",
            )

    update_kwargs: dict = {}
    core_changed = False
    if new_name is not None and new_name != existing.name:
        update_kwargs["name"] = new_name
    if new_sdk is not None and new_sdk != existing.sdk:
        update_kwargs["sdk"] = new_sdk
        core_changed = True
    if new_base_url is not None and new_base_url != existing.base_url:
        update_kwargs["base_url"] = new_base_url
        core_changed = True
    if new_api_key is not None and new_api_key != existing.api_key:
        update_kwargs["api_key"] = new_api_key
        core_changed = True
    if new_note is not None and new_note != existing.note:
        update_kwargs["note"] = new_note
    if core_changed:
        update_kwargs["stale_since"] = datetime.now()

    if update_kwargs:
        try:
            store.update_endpoint(existing.id, **update_kwargs)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    fresh = store.get_endpoint(existing.id)
    assert fresh is not None
    return _detail(store, fresh)
```

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_api_endpoints.py -v
```

预期：所有 PATCH 测试 + 既有测试 PASS。

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): PATCH /api/endpoints/{id} for editing core fields"
```

---

## Task 7: `_apply_outcome` 重测后清 `stale_since`

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 修改: `tests/test_api_endpoints.py`

- [ ] **步骤 1：写测试**

在 `tests/test_api_endpoints.py` 末尾追加：

```python
def test_retest_clears_stale_since(
    client: TestClient,
    seed_store: EndpointStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After PATCH bumps stale_since, retest should clear it."""
    ep = _seed_endpoint(seed_store, "stale-retest")

    # Bump stale via PATCH
    r = client.patch(
        f"/api/endpoints/{ep.id}", json={"base_url": "https://other.com/v1"}
    )
    assert r.status_code == 200
    assert r.json()["stale_since"] is not None

    # Stub probe so retest doesn't hit network. ProbeOutcome's signature is
    # (list_error, new_results, skipped) — see src/llm_model_probe/probe.py:41.
    from llm_model_probe.probe import ProbeRunner, ProbeOutcome
    async def _stub_probe(self, ep, *, allow_partial=False):  # type: ignore[no-untyped-def]
        return ProbeOutcome(list_error=None, new_results=[], skipped=[])
    monkeypatch.setattr(ProbeRunner, "probe_endpoint", _stub_probe)

    r2 = client.post(f"/api/endpoints/{ep.id}/retest")
    assert r2.status_code == 200
    assert r2.json()["stale_since"] is None
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_api_endpoints.py::test_retest_clears_stale_since -v
```

预期：`assert r2.json()["stale_since"] is None` 失败，仍为 PATCH 时设的时间戳。

- [ ] **步骤 3：在 `_apply_outcome` 末尾加清 stale**

`src/llm_model_probe/api.py`：

```python
def _apply_outcome(store: EndpointStore, ep: Endpoint, outcome) -> None:
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
    if outcome.new_results is not None:
        store.replace_model_results(ep.id, outcome.new_results)
    store.update_endpoint(ep.id, stale_since=None)
```

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_api_endpoints.py -v
```

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_endpoints.py
git commit -m "feat(api): clear stale_since after retest completes"
```

---

## Task 8: 修 `_parse_curl` 用 `normalize_base_url`

**文件**：
- 修改: `src/llm_model_probe/api.py`
- 修改: `tests/test_api_parse.py`

- [ ] **步骤 1：写回归测试**

在 `tests/test_api_parse.py` 末尾追加：

```python
def test_parse_curl_zhipu_v4(isolated_home: Path) -> None:
    """Regression: non-/v1 URL must not be sliced down to host-only.

    Was a bug in _parse_curl's old `if "/v1" in url ... else: host-only` branch.
    """
    blob = (
        "curl https://open.bigmodel.cn/api/paas/v4/chat/completions "
        "-H 'Authorization: Bearer 943b...REjJ' "
        "-H 'Content-Type: application/json'"
    )
    r = _client(isolated_home).post(
        "/api/parse-paste", json={"blob": blob}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parser"] == "curl"
    assert (
        body["suggested"]["base_url"]
        == "https://open.bigmodel.cn/api/paas/v4"
    )
    assert body["suggested"]["api_key"] == "943b...REjJ"
```

- [ ] **步骤 2：跑测试确认 fail**

```
uv run pytest tests/test_api_parse.py::test_parse_curl_zhipu_v4 -v
```

预期：assertion fail，`base_url == "https://open.bigmodel.cn"`（被旧代码砍到了 host）。

- [ ] **步骤 3：替换 `_parse_curl` 里的 URL 处理分支**

`src/llm_model_probe/api.py` 中 `_parse_curl`，把这段：

```python
url_match = _URL.search(blob)
if url_match:
    url = url_match.group(0).rstrip(",;")
    if "/v1" in url:
        url = url.split("/v1", 1)[0] + "/v1"
    else:
        from urllib.parse import urlsplit
        sp = urlsplit(url)
        url = f"{sp.scheme}://{sp.netloc}"
    out["base_url"] = url
    out["sdk"] = _guess_sdk(url)
```

改成：

```python
url_match = _URL.search(blob)
if url_match:
    url = url_match.group(0).rstrip(",;")
    url = normalize_base_url(url)
    out["base_url"] = url
    out["sdk"] = _guess_sdk(url)
```

把那个 `from urllib.parse import urlsplit` 顶部 import 也可以一并清理（如果没别处用了）—— 跑 pytest 之前 `grep urlsplit src/llm_model_probe/api.py` 确认。

- [ ] **步骤 4：跑测试确认 pass**

```
uv run pytest tests/test_api_parse.py -v
```

预期：4 个原有测试 + 新回归测试都 PASS。注意 `test_parse_curl`（Anthropic）应当依然过：`https://api.anthropic.com/v1/messages` → `normalize_base_url` 剥成 `https://api.anthropic.com`，仍然包含 "anthropic.com"。

- [ ] **步骤 5：commit**

```bash
git add src/llm_model_probe/api.py tests/test_api_parse.py
git commit -m "fix(api): _parse_curl uses normalize_base_url (handles non-/v1 URLs)"
```

---

## Task 9: 前端 types + API client `patchEndpoint`

**文件**：
- 修改: `frontend/src/lib/types.ts`
- 修改: `frontend/src/lib/api.ts`

- [ ] **步骤 1：types 里加 `stale_since` + `EndpointUpdate`**

`frontend/src/lib/types.ts`：

```typescript
export interface EndpointSummary {
  id: string;
  name: string;
  sdk: Sdk;
  base_url: string;
  mode: Mode;
  note: string;
  list_error: string | null;
  available: number;
  failed: number;
  total_models: number;
  tags: string[];
  last_tested_at: string | null;
  stale_since: string | null;
  created_at: string;
  updated_at: string;
}

// EndpointDetail extends Summary, gets the new field automatically.

export interface EndpointUpdate {
  name?: string;
  sdk?: Sdk;
  base_url?: string;
  api_key?: string;
  note?: string;
}
```

- [ ] **步骤 2：API client 加 `patchEndpoint`**

`frontend/src/lib/api.ts` 的 `api` object 里加（位置：`setTags` 附近）：

```typescript
patchEndpoint: (idOrName: string, body: EndpointUpdate) =>
    req<EndpointDetail>(
        "PATCH",
        `/api/endpoints/${encodeURIComponent(idOrName)}`,
        body,
    ),
```

也在 import 行加 `EndpointUpdate`：

```typescript
import type {
  EndpointSummary,
  EndpointDetail,
  EndpointCreate,
  EndpointUpdate,
  PasteSuggestion,
  ModelResultPublic,
} from "./types";
```

- [ ] **步骤 3：编译检查**

```
cd frontend && npx tsc --noEmit
```

预期：无 TS 错误（新字段 `stale_since` 出现在已有用法里都能 compile pass，因为 `string | null` 不会被强制读取）。

- [ ] **步骤 4：commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): types + api.patchEndpoint for editing endpoints"
```

---

## Task 10: `<BaseUrlInput>` 组件 + 实时提示

**文件**：
- 新建: `frontend/src/components/BaseUrlInput.tsx`

- [ ] **步骤 1：写组件**

新建 `frontend/src/components/BaseUrlInput.tsx`：

```tsx
import { Input } from "@/components/ui/input";

const STRIP_SUFFIXES = [
  "/v1/chat/completions",
  "/chat/completions",
  "/v1/messages",
  "/messages",
  "/v1/completions",
  "/completions",
];

export function normalizeBaseUrl(url: string): string {
  let s = url.replace(/\/+$/, "");
  const lower = s.toLowerCase();
  for (const suffix of STRIP_SUFFIXES) {
    if (lower.endsWith(suffix)) {
      s = s.slice(0, -suffix.length);
      break;
    }
  }
  return s.replace(/\/+$/, "");
}

export default function BaseUrlInput({
  value,
  onChange,
  placeholder = "https://api.example.com/v1",
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  id?: string;
}) {
  const trimmed = value.trim();
  const suggestion = trimmed ? normalizeBaseUrl(trimmed) : "";
  const canSuggest = trimmed.length > 0 && suggestion !== trimmed;

  return (
    <div className="space-y-1">
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {canSuggest && (
        <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
          <span>
            检测到完整接口 URL，建议改成{" "}
            <code className="bg-muted px-1 rounded">{suggestion}</code>
          </span>
          <button
            type="button"
            onClick={() => onChange(suggestion)}
            className="text-primary hover:underline"
          >
            采用
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **步骤 2：编译检查**

```
cd frontend && npx tsc --noEmit
```

预期：无 TS 错误。

- [ ] **步骤 3：commit**

```bash
git add frontend/src/components/BaseUrlInput.tsx
git commit -m "feat(frontend): BaseUrlInput component with live suffix-strip hint"
```

---

## Task 11: 重构 `AddEndpointDialog` 支持 add/edit 模式

**文件**：
- 修改: `frontend/src/components/AddEndpointDialog.tsx`

这个 task 改动较大但内聚。一次性完成。

- [ ] **步骤 1：用新结构整体替换 `AddEndpointDialog.tsx`**

`frontend/src/components/AddEndpointDialog.tsx`：

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  EndpointCreate,
  EndpointDetail,
  EndpointUpdate,
} from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import SmartPasteArea from "./SmartPasteArea";
import BaseUrlInput from "./BaseUrlInput";

type FormState = {
  name: string;
  sdk: "openai" | "anthropic";
  base_url: string;
  api_key: string;
  note: string;
};

const emptyForm: FormState = {
  name: "",
  sdk: "openai",
  base_url: "",
  api_key: "",
  note: "",
};

type Props =
  | {
      mode: "add";
      open: boolean;
      onClose: () => void;
      onSuccess: (data: EndpointDetail) => void;
    }
  | {
      mode: "edit";
      open: boolean;
      onClose: () => void;
      onSuccess: (data: EndpointDetail) => void;
      initial: EndpointDetail;
    };

export default function AddEndpointDialog(props: Props) {
  const { mode, open, onClose, onSuccess } = props;
  const initial = mode === "edit" ? props.initial : null;
  const qc = useQueryClient();

  const [form, setForm] = useState<FormState>(() =>
    initial
      ? {
          name: initial.name,
          sdk: initial.sdk,
          base_url: initial.base_url,
          api_key: "",
          note: initial.note ?? "",
        }
      : emptyForm,
  );
  const [modelsText, setModelsText] = useState("");

  // Reset form when the dialog reopens for a different endpoint
  useEffect(() => {
    if (!open) return;
    if (initial) {
      setForm({
        name: initial.name,
        sdk: initial.sdk,
        base_url: initial.base_url,
        api_key: "",
        note: initial.note ?? "",
      });
    } else {
      setForm(emptyForm);
      setModelsText("");
    }
  }, [open, initial?.id]);

  const create = useMutation({
    mutationFn: (payload: EndpointCreate) =>
      api.createEndpoint({ ...payload, no_probe: true }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      setForm(emptyForm);
      setModelsText("");
      onClose();
      onSuccess(data);
    },
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: EndpointUpdate }) =>
      api.patchEndpoint(id, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      qc.invalidateQueries({ queryKey: ["endpoint", data.id] });
      qc.invalidateQueries({ queryKey: ["endpoint", data.name] });
      onClose();
      onSuccess(data);
    },
  });

  function submit() {
    if (mode === "add") {
      const models = modelsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      create.mutate({ ...form, models });
    } else {
      const body: EndpointUpdate = {};
      if (form.name !== initial!.name) body.name = form.name;
      if (form.sdk !== initial!.sdk) body.sdk = form.sdk;
      if (form.base_url !== initial!.base_url) body.base_url = form.base_url;
      if (form.api_key.trim()) body.api_key = form.api_key;
      if (form.note !== (initial!.note ?? "")) body.note = form.note;
      patch.mutate({ id: initial!.id, body });
    }
  }

  const pending = create.isPending || patch.isPending;
  const error = create.error || patch.error;
  const submittable =
    !pending &&
    form.name.trim().length > 0 &&
    form.base_url.trim().length > 0 &&
    (mode === "edit" || form.api_key.trim().length > 0);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === "add" ? "Add endpoint" : "Edit endpoint"}
          </DialogTitle>
        </DialogHeader>

        {mode === "add" && (
          <SmartPasteArea
            onApply={(s) => {
              setForm((f) => ({
                ...f,
                name: s.name ?? f.name,
                sdk: s.sdk ?? f.sdk,
                base_url: s.base_url ?? f.base_url,
                api_key: s.api_key ?? f.api_key,
                note: s.note ?? f.note,
              }));
              if (s.models && s.models.length)
                setModelsText(s.models.join(", "));
            }}
          />
        )}

        <div className="space-y-3 py-2">
          <Field label="Name">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="SDK">
            <select
              className="w-full border rounded-md px-2 h-9 bg-background"
              value={form.sdk}
              onChange={(e) =>
                setForm({
                  ...form,
                  sdk: e.target.value as "openai" | "anthropic",
                })
              }
            >
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
            </select>
          </Field>
          <Field label="Base URL">
            <BaseUrlInput
              value={form.base_url}
              onChange={(v) => setForm({ ...form, base_url: v })}
            />
          </Field>
          <Field
            label={
              mode === "edit"
                ? "API key (留空保持不变)"
                : "API key"
            }
          >
            <Input
              type="password"
              value={form.api_key}
              placeholder={mode === "edit" ? "••••••••" : ""}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
          </Field>
          {mode === "add" && (
            <Field label="Models (comma-separated, leave empty for auto-discover)">
              <Input
                value={modelsText}
                placeholder="gpt-4, gpt-3.5-turbo"
                onChange={(e) => setModelsText(e.target.value)}
              />
            </Field>
          )}
          <Field label="Note">
            <Input
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
            />
          </Field>

          {error && (
            <div className="text-sm text-destructive">{String(error)}</div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!submittable}>
            {pending
              ? mode === "add"
                ? "Adding…"
                : "Saving…"
              : mode === "add"
              ? "Add"
              : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  );
}
```

- [ ] **步骤 2：修复调用方（App.tsx）使用新 prop 形状**

`AddEndpointDialog` 原本是 `onCreated: (id: string) => void`，新签名是 `onSuccess: (data: EndpointDetail) => void`。在 App.tsx 里搜 `AddEndpointDialog` 的使用处：

```tsx
<AddEndpointDialog
  mode="add"
  open={addOpen}
  onClose={() => setAddOpen(false)}
  onSuccess={(d) => setSelected(d.id)}
/>
```

把现有 `onCreated={(id) => ...}` 替换成 `onSuccess={(d) => ...(d.id)}`，并加 `mode="add"`。

- [ ] **步骤 3：编译 + 启动 dev 验证**

```
cd frontend && npx tsc --noEmit
cd frontend && npm run dev
```

启动后端 dev：

```
LLM_MODEL_PROBE_DEV=1 uv run probe ui --dev --no-browser
```

打开 `http://localhost:5173`，手动 add 一个 endpoint，确认：
- SmartPaste 还能用 ✓
- Base URL 输入框下面输入 `.../v4/chat/completions` 时显示提示 ✓
- 点"采用"按钮后输入框被替换 ✓
- 创建成功 ✓

- [ ] **步骤 4：commit**

```bash
git add frontend/src/components/AddEndpointDialog.tsx frontend/src/App.tsx
git commit -m "feat(frontend): AddEndpointDialog supports edit mode"
```

---

## Task 12: drawer 加编辑入口（铅笔图标）

**文件**：
- 修改: `frontend/src/components/EndpointDetailDrawer.tsx`

- [ ] **步骤 1：drawer 顶部加铅笔按钮 + 内嵌 dialog**

`frontend/src/components/EndpointDetailDrawer.tsx`：

(a) 顶部加 imports：

```tsx
import { Pencil } from "lucide-react";
import AddEndpointDialog from "./AddEndpointDialog";
```

(b) 组件函数体内加状态：

```tsx
const [editOpen, setEditOpen] = useState(false);
```

(c) 修改 `<SheetTitle>` 那一行，让标题旁边带个铅笔按钮：

```tsx
<SheetHeader>
  <SheetTitle className="flex items-center gap-2">
    <span>{d?.name ?? "…"}</span>
    {d && (
      <button
        type="button"
        title="Edit endpoint"
        onClick={() => setEditOpen(true)}
        className="text-muted-foreground hover:text-foreground p-1 rounded"
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
    )}
  </SheetTitle>
</SheetHeader>
```

(d) 在 `<SheetContent>` 关闭标签前（紧挨着）加 dialog：

```tsx
{d && (
  <AddEndpointDialog
    mode="edit"
    open={editOpen}
    onClose={() => setEditOpen(false)}
    initial={d}
    onSuccess={() => {
      // detail.refetch handled by query invalidation in dialog
    }}
  />
)}
```

- [ ] **步骤 2：手动验证 UI**

```
cd frontend && npm run dev
```

- 打开任意 endpoint 的 drawer
- 点标题旁边的铅笔图标
- dialog 打开，字段预填好（除 api_key 留空）
- 改 base_url、保存
- drawer 内字段更新 ✓

- [ ] **步骤 3：commit**

```bash
git add frontend/src/components/EndpointDetailDrawer.tsx
git commit -m "feat(frontend): pencil edit entry on detail drawer"
```

---

## Task 13: drawer stale banner + 灰徽章

**文件**：
- 修改: `frontend/src/components/EndpointDetailDrawer.tsx`

- [ ] **步骤 1：banner**

`EndpointDetailDrawer.tsx` 中，紧跟 `<SheetHeader>` 闭合后、`{detail.isLoading && ...}` 之前插入：

```tsx
{d?.stale_since && (
  <div className="mt-2 mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
    端点配置已修改（{relative(d.stale_since)}），数据可能过期。建议点击 Retest 重新探测。
  </div>
)}
```

- [ ] **步骤 2：灰徽章**

把 `<ModelStatus>` 组件改成接收 `stale: boolean`，外层 wrap 一层 opacity：

(a) `<ModelRow>` 接受新 prop：

```tsx
function ModelRow({
  model,
  result,
  pending,
  transientError,
  filterSkip,
  checked,
  onToggle,
  stale,
}: {
  model: string;
  result: ModelResultPublic | null;
  pending: boolean;
  transientError: string | null;
  filterSkip: boolean;
  checked: boolean;
  onToggle: () => void;
  stale: boolean;
}) {
  return (
    <label className="flex items-center gap-2 px-3 py-2 hover:bg-muted/30 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-4 w-4 flex-shrink-0"
      />
      <div className="flex items-center gap-1 flex-1 min-w-0">
        <span className="font-mono text-xs truncate">{model}</span>
        <CopyButton text={model} />
      </div>
      {filterSkip && !result && !pending && !transientError && (
        <Badge variant="secondary" className="text-xs flex-shrink-0">
          filter-skip
        </Badge>
      )}
      <span className={stale ? "opacity-50" : undefined}>
        <ModelStatus
          result={result}
          pending={pending}
          transientError={transientError}
        />
      </span>
    </label>
  );
}
```

(b) 调用处（`renderRow`）传 `stale={!!d.stale_since}`：

```tsx
const renderRow = (m: string) => (
  <ModelRow
    key={m}
    model={m}
    result={resultByModel.get(m) ?? null}
    pending={orch.isPending(d.id, m)}
    transientError={orch.errorFor(d.id, m)}
    filterSkip={d.excluded_by_filter.includes(m)}
    checked={checked.has(m)}
    onToggle={() => toggle(m)}
    stale={!!d.stale_since}
  />
);
```

- [ ] **步骤 3：手动验证 UI**

```
cd frontend && npm run dev
```

- PATCH 一个 endpoint 的 base_url（通过 UI 编辑或直接 curl 后端）
- drawer 顶部出现 amber banner
- 模型行的状态徽章变灰（透明度）
- 点 Retest 后 banner 消失，徽章恢复

- [ ] **步骤 4：commit**

```bash
git add frontend/src/components/EndpointDetailDrawer.tsx
git commit -m "feat(frontend): stale banner + dimmed status badges in drawer"
```

---

## Task 14: 主表格名字列加 stale 小灰点

**文件**：
- 修改: `frontend/src/components/EndpointTable.tsx`

- [ ] **步骤 1：在名字 cell 里加点**

`EndpointTable.tsx` 中找到 `<TableCell className="font-medium">{ep.name}</TableCell>`，替换为：

```tsx
<TableCell className="font-medium">
  <div className="flex items-center gap-1.5">
    {ep.stale_since && (
      <span
        title="配置已修改，数据可能过期"
        className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500"
      />
    )}
    <span>{ep.name}</span>
  </div>
</TableCell>
```

- [ ] **步骤 2：手动验证**

```
cd frontend && npm run dev
```

- PATCH 一个 endpoint 触发 stale
- 主表格里该行 name 列前面出现一个琥珀色小点
- hover 时显示提示文案
- Retest 之后小点消失

- [ ] **步骤 3：commit**

```bash
git add frontend/src/components/EndpointTable.tsx
git commit -m "feat(frontend): stale indicator dot on endpoint table"
```

---

## 完工后整体验证

跑全部测试 + 全栈手动测一遍：

```bash
uv run pytest -q
cd frontend && npx tsc --noEmit && npm run build && cd ..
```

E2E 验收 checklist（手动 UI 跑一遍）：

- [ ] 新建 endpoint 时输入完整 completions URL，输入框下方有提示，"采用"能替换
- [ ] 不点"采用"直接提交，后端也会规范化
- [ ] 编辑入口（drawer 标题旁铅笔）打开 dialog，字段预填正确
- [ ] api_key 留空保存 → 数据库里 api_key 不变
- [ ] 改 base_url 保存 → drawer 出现 amber banner，徽章变灰，主表格名字前出现小灰点
- [ ] 点 Retest → banner 消失，徽章恢复，主表格小点消失
- [ ] 改名为已存在的 endpoint 名 → dialog 显示 409 错误
- [ ] SmartPaste 智谱 curl → base_url 自动剥成 `.../paas/v4`
