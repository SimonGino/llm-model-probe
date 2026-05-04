# Tier 1 - 标签 + 搜索 + 模型排序

**日期**: 2026-05-04
**状态**: 已口头确认
**基于**: `docs/specs/2026-05-01-design.md`、`2026-05-01-ui-design.md`、`2026-05-02-probe-redesign-design.md`

## 目标

让这工具能舒服地管理 10+ 个 endpoint，补齐三个会最先暴露出来的痛点：

1. **标签 (tags)** —— endpoint 上挂多个自由文本标签，按"来源 / 用途"分类（如 `供应商A`、`trial`、`team-foo`）
2. **endpoint 搜索** —— 表格上方的过滤框，按 name / note / tag 任意子串匹配
3. **drawer 内模型搜索 + 段内排序** —— 200 个模型里搜 `gpt-4` 直接定位；Available 段按延迟从快到慢，Failed 段按错误类型聚类，Untested 段字母序

这是从"个人 demo"跨到"30+ endpoint 也不会乱"的最小集合。历史、加密、认证、定时探活等都**不在这次范围**，留给后续 Tier 2/3。

## 不做的事

- CLI 编辑标签（只支持 `probe add --tag`，后续编辑走 UI）
- 标签自动补全（输入框 + 表格的多选下拉一起够用了）
- 标签颜色 / 图标
- 模型探活历史（Tier 2）
- 跨 endpoint 模型矩阵（Tier 2）
- 加密、认证、定时探活、能力探查（Tier 3）

## 数据模型

只加一列。`endpoints` 表加 `tags_json`：

```sql
ALTER TABLE endpoints
    ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
```

SQLite 没有 `IF NOT EXISTS` 加列语法，所以 `EndpointStore.init_schema` 里跑一段幂等迁移：

```python
def _migrate_tags(self, c: sqlite3.Connection) -> None:
    cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
    if "tags_json" not in cols:
        c.execute(
            "ALTER TABLE endpoints "
            "ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
        )
```

在 `executescript(SCHEMA)` 之后、原有的 models 回填之前调用一次。已有数据自动得到 `[]`。

`Endpoint` dataclass 加 `tags: list[str] = field(default_factory=list)`，存取方式跟 `models` 完全一样（JSON 序列化）。

## API 改动

### `EndpointCreate`（请求体）

```python
class EndpointCreate(BaseModel):
    # ... 已有字段不变 ...
    tags: list[str] = []
```

允许空数组。`create_endpoint` 路由把 tags 写入新列。

### `EndpointSummary` 和 `EndpointDetail`（响应体）

```python
class EndpointSummary(BaseModel):
    # ... 已有字段不变 ...
    tags: list[str]
```

list 接口和 detail 接口都返回 tags，前端表格不用额外请求 detail。

### 新增：`PUT /api/endpoints/{name_or_id}/tags`

```python
class TagsUpdate(BaseModel):
    tags: list[str]

@app.put("/api/endpoints/{name_or_id}/tags",
         response_model=EndpointSummary)
def set_tags(name_or_id: str, body: TagsUpdate) -> EndpointSummary:
    ...
```

整体替换标签列表。每个元素 trim 空格、丢掉空字符串、保留首次出现顺序去重。返回更新后的 `EndpointSummary`，方便前端刷新缓存。

endpoint 找不到 → 404。

## CLI 改动

只在 `probe add` 加一个选项：

```python
tags: Optional[str] = typer.Option(
    None, "--tag",
    help="逗号分隔的标签，如 'bob,trial'",
),
```

跟 `--models` 一样的解析方式：按逗号切、trim、丢空。CLI 不做编辑功能。

## 前端改动

### `EndpointTable` —— 搜索 + 标签筛选 + 标签列

表格上方加一行（新）：

```
┌──────────────────────────────────────────────────┐
│ [搜 name/note/tag...]  [标签 ▾]                  │
└──────────────────────────────────────────────────┘
ID  Name  SDK  Mode  Status  Tested  Tags  Note  Actions
```

- **搜索框**（自由文本）：大小写不敏感，匹配 `name` / `note` / 任意 tag 的子串
- **标签下拉**（多选）：列出所有 endpoint 当前用到的 tag，AND 组合搜索框。用 shadcn `<DropdownMenu>` + checkbox。空选 = 不过滤
- **Tags 列**：每个 tag 一个小 badge（`<Badge variant="secondary">`）。超过 3 个 → 显示前 3 个 + `+N`

Note 列变窄给 Tags 让位（`max-w-[160px]`，原来 200）。

state：搜索字符串 + 选中 tag 集合放在 `App.tsx`（提到上层免得重新查询时丢失），通过 props 传下来。

### `EndpointDetailDrawer` —— 标签编辑器

详情卡片区加一行：

```
Tags    [trial ✕] [bob ✕]   [+ 添加 tag 输入框 ↵]
```

- 每个 tag：`<Badge>` + 小 ✕ 按钮
- 输入框：小型 text field，回车追加到 tag 列表 → PUT 到服务器
- 点 ✕ 移除 → PUT

state：`useMutation` 包 `api.setTags(idOrName, tags)`。成功后 invalidate `["endpoint", id]` 和 `["endpoints"]`，表格自动反映变化。

### `EndpointDetailDrawer` —— 模型搜索 + 段内排序

三个段上方加一个搜索框：

```
Models (239)               [搜模型...]
                                                  [Test selected (12)] [Test all]

AVAILABLE (3) ...
FAILED (12) ...
UNTESTED (224) ...
```

前端按 `model_id` 子串过滤三个段（大小写不敏感）。空 = 全部显示。

**段内排序**：

| 段 | 排序键 |
|---|---|
| Available | `latency_ms` 升序（最快在前），null 在最后 |
| Failed | `error_type` 升序，再按 `model_id` 升序（同类错误聚在一起） |
| Untested | `model_id` 升序（字母序） |

**搜索激活时**，"Test selected" / "Test all" 按钮作用于**过滤后**的视图（这样可以"测试所有 gpt-* 模型"）。按钮 label 加提示：`Test all (filtered: 5)`。

### 前端 `api.ts`

加：

```ts
setTags: (idOrName: string, tags: string[]) =>
  req<EndpointSummary>("PUT",
    `/api/endpoints/${encodeURIComponent(idOrName)}/tags`,
    { tags }),
```

### 前端 `types.ts`

`EndpointSummary` 和 `EndpointDetail` 都加 `tags: string[]`。`EndpointCreate` 加 `tags?: string[]`。

## 后端测试

`tests/test_api_endpoints.py` 加：

- `test_create_with_tags_persists` —— POST 带 `tags: ["a","b"]`，GET 返回相同
- `test_create_default_tags_empty` —— POST 不带 tags → `tags == []`
- `test_set_tags_replaces` —— PUT 整体替换；去重；trim
- `test_set_tags_unknown_endpoint_404`
- `test_summary_includes_tags` —— list 接口也返回 tags

`tests/test_store.py` 加：

- `test_init_schema_adds_tags_column_idempotently` —— 手动构造一个没有 `tags_json` 列的旧表，调用 `init_schema`，确认新列存在 + 旧行得到 `[]`

## 前端测试

按现有惯例，v1 不写单元测试。手动 smoke 清单：

1. CLI `probe add --tag x,y` 加 endpoint → 表格 tag chip 显示
2. drawer 加一个 tag → 表格立即反映（不用刷新）
3. drawer 删一个 tag → 表格立即反映
4. 搜索框输入 → 表格实时过滤
5. 标签下拉选一个 → 表格在搜索基础上再缩
6. drawer 搜 `gpt` → 三段同时过滤，计数更新
7. Available 段确实是最快的在最前
8. drawer 搜索激活时 "Test all" 显示 `(filtered: N)`

## 兼容性

- 老 DB 自动得到 `tags_json` 列，默认 `'[]'`，**不丢数据**
- 老的 API 调用方不发 `tags` 字段 → 默认 `[]`
- CLI `--tag` 是可选的，不传完全不影响
- 新的 `PUT /tags` 接口纯增量

## 明确不做

- 标签规范化（小写化 / slug）。标签**区分大小写**，原样存储
- 跨 endpoint 标签重命名 / 合并（Tier 2）
- 搜索状态保存到 URL hash（如有需要 Tier 2）
- 批量打标签（一次给 N 个 endpoint 加同一个 tag）
- 表头点击排序（独立功能）
