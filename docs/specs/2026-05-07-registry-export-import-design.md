# 跨机器导出 / 导入注册表（dump / load）

**日期**: 2026-05-07
**状态**: 已口头确认
**基于**: `docs/specs/2026-05-01-design.md`、`2026-05-06-endpoint-edit-and-url-normalize-design.md`

## 背景

工具的注册表（endpoints 表 + api keys）目前只能就地用：用户在 A 机器上把一堆 `(base_url, api_key)` 录进来、跑 discover、确认能用，回到 B 机器还得从头再录一遍。已有的 `probe export` 命令产出的是**人类阅读的报告**（md / json），不是可重新载入的数据快照——格式不同、不带 keys、字段也不齐。

主要场景：用户在测试机和正式机分别维护同一份配置，想要"在 A 上导出 → scp 拷过去 → 在 B 上导入"这种最朴素的工作流。

## 目标

1. **dump**：把 endpoints 表序列化成单个 JSON 文件，可选包含 / 不包含 api keys。
2. **load**：从 JSON 文件读回 endpoints，处理与本地的 name 冲突。
3. **CLI 双向支持**（`probe dump` / `probe load`），**Web UI 只支持 dump**（导出按钮，不开导入入口避免公网 UI 上误触发覆盖）。
4. 文件格式带 envelope（`kind` + `version`），为后续 schema 演进留口。

## 不做的事

- **不导出 `model_results` 表**：probe 结果本来就有时效性，新机器到位后用户自己 retest 一次即可。如果将来确实需要带历史，做 v2 schema 加 `results` 字段，不会破坏 v1 文件兼容。
- **不导出 `app_settings`**：那里存的是机器本地状态（如 LLM 解析 token），跨机器迁移会污染目标机配置。
- **不做选择性导出**（按 tag / name 过滤）：用户需要时可以 `probe dump | jq '.endpoints |= map(select(...))' > subset.json`，导入路径不变。
- **不在 UI 暴露 import**：load 是高破坏性操作（特别是 `--on-conflict=replace`），UI 暴露在公网时只多一道攻击面，价值有限。
- **不在文件层做加密**：默认不带 keys 已经覆盖"安全分享"场景；要加密自己 `gpg -c` 一道即可，文件格式里不需要管。
- **不做 round-trip 之外的合并 / 比对工具**：`--on-conflict` 三档够用。

## 文件格式

JSON 单文件，UTF-8。建议扩展名 `.json`，文件名约定 `llm-model-probe-registry-YYYY-MM-DD.json`（UI 下载时用此名；CLI 不强制）。

```json
{
  "kind": "llm-model-probe-registry",
  "version": 1,
  "exported_at": "2026-05-07T12:34:56",
  "endpoints": [
    {
      "id": "ep_8a3f12",
      "name": "bob-glm",
      "sdk": "openai",
      "base_url": "https://glm.example.com/v1",
      "api_key": null,
      "mode": "discover",
      "models": ["gpt-4o", "gpt-4o-mini"],
      "tags": ["bob", "trial"],
      "note": "from Bob 2026-05-01",
      "created_at": "2026-05-01T10:00:00",
      "updated_at": "2026-05-06T14:22:11"
    }
  ]
}
```

字段说明：

| 字段 | 来源 | 备注 |
|---|---|---|
| `kind` | 常量 | 必为 `"llm-model-probe-registry"`，否则 load 拒绝 |
| `version` | 常量 | 当前 `1`；load 遇到 `> 1` 报"文件来自更新版本" |
| `exported_at` | `datetime.now()` ISO8601 | 仅供人类参考，load 不读 |
| `endpoints[].id` | DB 列 | 写出文件；load 到空库时复用，遇冲突时被本地 id 覆盖（见"冲突 / 匹配语义"） |
| `endpoints[].name` | DB 列 | UNIQUE，import 用它做匹配键 |
| `endpoints[].sdk` | DB 列 | `"openai"` / `"anthropic"` |
| `endpoints[].base_url` | DB 列 | 已规范化（`add` / `edit` 入库前都跑过 `normalize_base_url`） |
| `endpoints[].api_key` | DB 列 / null | 默认 `null`；`--include-keys` 时为字符串 |
| `endpoints[].mode` | DB 列 | `"discover"` / `"specified"` |
| `endpoints[].models` | DB 列 | 字符串数组 |
| `endpoints[].tags` | DB 列 | 字符串数组 |
| `endpoints[].note` | DB 列 | 字符串，可空 |
| `endpoints[].created_at` / `updated_at` | DB 列 | ISO8601 |

不导出的字段：`list_error`、`stale_since`（运行时状态）、`model_results` 整张表、`app_settings`。

## 模块切分

新增一个文件 `src/llm_model_probe/registry_io.py`，纯函数 + dataclass，没有 IO 副作用以外的逻辑：

```python
def dump_endpoints(
    endpoints: list[Endpoint],
    *,
    include_keys: bool,
    now: datetime | None = None,
) -> dict:
    """Build the JSON-serializable envelope."""

@dataclass
class LoadReport:
    imported: list[str]            # names successfully imported
    skipped: list[str]              # names skipped due to conflict
    replaced: list[str]             # names replaced (on-conflict=replace)
    missing_keys: list[str]         # names whose api_key is empty after import

class LoadConflict(Exception): ...
class LoadFormatError(Exception): ...

def load_endpoints(
    payload: dict,
    store: EndpointStore,
    *,
    on_conflict: Literal["skip", "replace", "error"],
) -> LoadReport:
    """Validate envelope, then apply to the store inside a single transaction."""
```

CLI 和 API 都调这两个函数；JSON 序列化（`json.dumps` / `json.loads`）和文件 IO 留给调用方，方便测试纯逻辑。

## CLI

`src/llm_model_probe/cli.py` 加两个命令。命名选 `dump` / `load` 而不是 `export` / `import`，避免和现有 `probe export`（产出报告）撞名，也避开 `import` 这个 Python 关键字带来的语义混淆。

### `probe dump`

```bash
probe dump                              # JSON 写 stdout，无 keys
probe dump --output registry.json       # 写文件
probe dump --include-keys -o reg.json   # 带明文 keys
```

```python
@app.command()
def dump(
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    include_keys: bool = typer.Option(
        False, "--include-keys",
        help="Include api_key in the output. WARNING: keys are written in plaintext.",
    ),
) -> None:
    store = _store()
    payload = dump_endpoints(
        store.list_endpoints(),
        include_keys=include_keys,
    )
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        try:
            Path(output).chmod(0o600)
        except OSError:
            pass  # best effort
        console.print(f"[green]✓[/green] wrote {output} ({len(payload['endpoints'])} endpoints)")
        if include_keys:
            console.print("[yellow]![/yellow] file contains plaintext API keys; chmod 0600 applied")
    else:
        print(text)
```

### `probe load`

```bash
probe load registry.json                       # default --on-conflict=skip
probe load registry.json --on-conflict=replace
probe load registry.json --on-conflict=error
```

```python
@app.command()
def load(
    path: str = typer.Argument(..., metavar="FILE"),
    on_conflict: str = typer.Option(
        "skip", "--on-conflict",
        help="Strategy when an endpoint name already exists: skip | replace | error",
    ),
) -> None:
    if on_conflict not in ("skip", "replace", "error"):
        raise typer.BadParameter("--on-conflict must be skip | replace | error")
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"not valid JSON: {e}")
    store = _store()
    try:
        report = load_endpoints(payload, store, on_conflict=on_conflict)
    except LoadFormatError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except LoadConflict as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(2)
    _print_load_report(report, console)
```

`_print_load_report` 输出形如：

```
✓ imported 7 endpoints
  · skipped 2 conflicts: bob-glm, alice-claude (use --on-conflict=replace to override)
  · 5 endpoints have no api_key — use `probe edit <name> --api-key ...` (UI: 编辑 dialog)
```

注意：当前 CLI 没有 `probe edit` 命令（见 endpoint-edit spec 的 Out of scope）。文案上指向 UI，避免误导用户去找不存在的命令；如果将来 CLI 加 edit，文案再同步。

## API（仅 dump）

`src/llm_model_probe/api.py` 加一个端点：

```python
@app.get("/api/registry/dump")
def dump_registry(include_keys: bool = False) -> JSONResponse:
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

走和其他 `/api/*` 端点一样的 token 中间件，不额外特判。

不加 import 端点（Q4 决定）。

## 前端

新增组件 `frontend/src/components/ExportRegistryButton.tsx`：

- 一个带下拉的按钮，标签 `Export registry`
- 点击展开两个选项 / 一个 dialog：
  - 复选框 `Include API keys`（默认 unchecked）
  - 勾选时旁边一行红色小字提示："Plaintext keys will be written to the file."
  - 主按钮 `Download`
- 点 Download → `fetch('/api/registry/dump?include_keys=0|1', { headers: auth.header() })` → 把 response 转成 Blob → 触发浏览器下载，文件名沿用 `Content-Disposition` 给的（`llm-model-probe-registry-YYYY-MM-DD.json`）

放在哪里：主列表页右上角工具区，靠近 "Add endpoint" 按钮的位置；样式参考 shadcn `<Button variant="outline">`。

`frontend/src/lib/api.ts` 加一个 helper：

```typescript
downloadRegistry: async (includeKeys: boolean): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(
        `${BASE}/api/registry/dump?include_keys=${includeKeys ? 1 : 0}`,
        { headers: auth.header() },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const m = cd.match(/filename="([^"]+)"/);
    const filename = m?.[1] ?? `registry-${new Date().toISOString().slice(0, 10)}.json`;
    return { blob, filename };
}
```

## 冲突 / 匹配语义（精确版）

匹配键：**name**（DB UNIQUE 列）。文件里的 `id` 不参与匹配。

对每个 file 里的 endpoint：

1. `existing = store.get_endpoint_by_name(file_ep.name)`
2. `existing is None` → 直接 `insert`，使用文件里的 `id`（保留 round-trip 稳定）
   - 例外：如果文件里的 `id` 在本地 DB 里被**别的 name 占用**，insert 会因主键冲突失败。这种情况按"corrupted-ish dump"处理：当作 format error 报错，提示用户先 `probe rm` 那个冲突的 endpoint 或手改文件 id。
3. `existing` 存在：
   - `on_conflict == "skip"`：跳过，加入 `skipped`
   - `on_conflict == "replace"`：保留 `existing.id`（model_results 的 FK 指着它）；其他字段全部按文件覆盖；`tags` 也覆盖；`stale_since` 不动（用户进 UI 自己决定要不要重测）；加入 `replaced`
   - `on_conflict == "error"`：抛 `LoadConflict`，事务回滚，整批啥也没改

`api_key` 处理：

- 文件里 `api_key == null`：endpoint 写入时 `api_key = ""`，加入 `missing_keys` 报告
- 文件里 `api_key` 是字符串：原样写入

`base_url` 处理：load 时再过一次 `normalize_base_url`，防御文件被手动编辑或来自旧版本（彼时还没规范化）。

事务：整个 load 过程包在一个 SQLite 事务里。三种策略下任何 DB 错误都触发回滚。`error` 策略遇冲突主动回滚。

## Edge cases

- **空文件**（`endpoints: []`）：load 成功，imported = 0，无错误
- **同一文件里 name 重复出现**：format error，提示"duplicate name 'bob-glm' in file"
- **同一文件里 id 重复出现**：format error
- **文件里 sdk / mode 不在枚举范围**：format error，提示"endpoint 'foo' has invalid sdk='xx'"
- **`models` 不是数组 / `tags` 不是数组**：format error
- **`include_keys=true` dump 的文件被人 `--include-keys=false` 重新 dump**：keys 丢失，这是用户自己的选择（合理行为，不防御）
- **load 一个 v1 文件到将来的 v2 程序**：v2 应当向后兼容 v1；spec 要求未来加字段都用 `Optional` + 默认值
- **load 一个 v2 文件到当前 v1 程序**：报错"file version 2 not supported, please upgrade"
- **dump 一个空注册表**：正常输出 `endpoints: []`，UI / CLI 都不报错
- **load 同一个文件两次（默认 skip）**：第二次全部 skipped，幂等
- **api_key 含特殊字符**（含 `"` / 换行）：JSON 标准转义，无特殊处理
- **大文件**（>10 MB）：当前规模下不太可能（每条 endpoint 也就 1-2 KB），不专门优化；加载走 `json.loads` 一次性反序列化即可

## 测试

新增测试文件：

### `tests/test_registry_io.py`（纯函数）

- `dump_endpoints` 不带 keys → 所有 `api_key` 字段为 `None`
- `dump_endpoints` 带 keys → 所有 `api_key` 为原值
- envelope 含 `kind` / `version` / `exported_at`
- `load_endpoints` 接受 v1 文件，写入 store
- 文件 `kind` 错 → `LoadFormatError`
- 文件 `version=2` → `LoadFormatError`，错误信息含"upgrade"
- 文件 `endpoints` 缺字段（如缺 `sdk`）→ `LoadFormatError`，错误指出哪条 / 哪个字段
- `endpoints` 数组里 name 重复 → `LoadFormatError`
- conflict=skip：name 已存在 → 加入 skipped，imported 不含
- conflict=replace：name 已存在 → 原 id 保留，其他字段被覆盖
- conflict=error：name 已存在 → 抛 `LoadConflict`，store 状态完全没变（事务回滚）
- 文件 `api_key=null` → DB 里 `api_key=""`，name 出现在 `missing_keys`

### `tests/test_cli_dump_load.py`

- `probe dump --output FILE` → 文件存在 + JSON 合法 + 非空
- `probe dump --output FILE` 文件权限 0600
- `probe dump`（无 --output） → 打到 stdout
- `probe dump --include-keys` → 文件里有 keys
- `probe load FILE` happy path
- `probe load FILE --on-conflict=replace`
- `probe load FILE --on-conflict=error` 撞冲突 → exit code 2
- `probe load nonexistent.json` → 友好报错（非 traceback）
- `probe load /tmp/garbage.txt`（非 JSON）→ 友好报错

### `tests/test_api_registry_dump.py`

- `GET /api/registry/dump` 200，body 是合法 envelope，所有 `api_key` 为 null
- `GET /api/registry/dump?include_keys=1` 200，含 keys
- `Content-Disposition` header 带文件名
- token 模式下未带 token → 401（走中间件，无需特判）

## 实现顺序建议

1. `registry_io.py` + `tests/test_registry_io.py`（纯函数先稳）
2. `cli.py` 的 `dump` / `load` + `tests/test_cli_dump_load.py`
3. `api.py` 的 `/api/registry/dump` + `tests/test_api_registry_dump.py`
4. 前端 `ExportRegistryButton.tsx` + `api.ts` helper + 接到主页面
5. README 加一节简短文档

## Out of scope（未来工作）

- UI import（看是否真有诉求，再叠 file upload + 二次确认 dialog）
- 文件加密（如果跨外人传输的需求出现）
- 选择性 dump（`--tag` / `--name` 过滤）
- 把 `model_results` / `app_settings` 也搬过去
- v2 schema 演进（加 `results` / `settings` 节）
- CLI `probe edit` 命令（已在 endpoint-edit spec 列为 OOS，本 spec 的 missing_keys 文案已经把 CLI 用户引到 UI 编辑）
