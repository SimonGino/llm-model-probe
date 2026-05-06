# Endpoint 编辑 + base_url 软规范化

**日期**: 2026-05-06
**状态**: 已口头确认
**基于**: `docs/specs/2026-05-01-design.md`、`2026-05-01-ui-design.md`、`2026-05-04-tier1-design.md`

## 背景

当前一旦 endpoint `add` 进来，五个用户填的字段（`name`、`sdk`、`base_url`、`api_key`、`note`）就**没有任何 UI 路径可以改**——只有 `/tags` 接口在 `2026-05-04-tier1` 那一轮加了。想纠正一个填错的 `base_url` 必须 `delete` 再 `add`，标签和探测历史也跟着丢。

第二个相关坑：很多非 OpenAI 标准的 provider，base URL 不以 `/v1` 结尾。例如智谱 `https://open.bigmodel.cn/api/paas/v4`。如果用户从厂商页面复制了完整的 chat completions URL（`.../paas/v4/chat/completions`），SDK 会在它后面再拼 `/models`，得到 `/v4/chat/completions/models` → 404。系统目前没有任何检测或提示，错误埋在第一次探活时才暴露。

`api.py:_parse_curl` 的 SmartPaste 路径里也有同样的根源 bug——它假设所有 base 都以 `/v1` 结尾，碰到非 `/v1` 的就把 URL 砍到只剩 host。

## 目标

1. **能编辑** `name` / `sdk` / `base_url` / `api_key` / `note` —— UI + 后端 API 都补上。`tags` 已经能改不再动。
2. **核心字段改了之后**（`base_url` / `sdk` / `api_key`），把 endpoint 标记为 stale，UI 上提示用户重测，但不自动清旧数据。
3. **base_url 软规范化** —— 表单里实时检测"完整接口 URL"模式（如尾巴是 `/chat/completions`、`/messages`），在输入框下显示一键采纳的建议；后端兜底剥尾。
4. 顺手修掉 `_parse_curl` 对非 `/v1` URL 的剪裁 bug（同源问题）。

## 不做的事

- CLI 端的 `probe edit` 命令（CLI 用户可以直接 SQL，或者删了重建——少数派场景，不优先）
- 编辑后自动触发重测（用户自己点 Retest，行为可预测）
- 改了 `sdk` 时强制清空 `models[]`（让用户走 stale 流程 + 手动重测，模型列表会被 discover 替换）
- "测试连接"按钮（先看真用了再说，YAGNI）
- 改 `name` 之后老链接重定向（前端 query key 用 `id`，name 改了不影响 URL）

## 数据模型

`endpoints` 表加一列：

```sql
ALTER TABLE endpoints
    ADD COLUMN stale_since TEXT NULL;
```

含义：核心字段（`base_url` / `sdk` / `api_key`）改动时写入 ISO8601 时间戳；retest 完成时清回 NULL。

`store.py::EndpointStore.init_schema` 里幂等迁移（参考 `_migrate_tags` 同款写法）：

```python
@staticmethod
def _migrate_stale_since(c: sqlite3.Connection) -> None:
    cols = {row["name"] for row in c.execute("PRAGMA table_info(endpoints)")}
    if "stale_since" not in cols:
        c.execute(
            "ALTER TABLE endpoints ADD COLUMN stale_since TEXT NULL"
        )
```

`Endpoint` dataclass 加 `stale_since: datetime | None = None`，`_row_to_endpoint` 里用 `_from_iso(row["stale_since"])` 还原。

## API 改动

### 新增 `PATCH /api/endpoints/{name_or_id}`

请求体（partial-update，所有字段可选）：

```python
class EndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    sdk: SdkType | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    note: str | None = None
```

行为：

1. 取出现有 endpoint。如果 `name` 改了且新 `name` 已被别的 endpoint 占用 → `409 Conflict`。
2. 对传进来的 `base_url` 跑一次 `normalize_base_url()`（见下节），得到剥尾后的字符串。
3. 比较新值 vs 旧值，如果 `base_url` / `sdk` / `api_key` 任一发生变化 → `stale_since = datetime.now()`。其他字段单独变不动 stale_since。
4. 写一条 SQL，只更新有传进来的列 + `updated_at` + 可能的 `stale_since`。
5. 返回更新后的 `EndpointDetail`（跟 GET 同 schema）。

返回 `200 OK`。响应体可以多一个 `normalized_base_url: bool` 标志告诉前端"我帮你剥了尾巴"，但前端基于 hint 已经先示意过，这字段更多是兜底信号；先不加，避免膨胀。

### 修改 `POST /api/endpoints`

`create_endpoint` 里在构造 `Endpoint` 之前对 `payload.base_url` 跑一次 `normalize_base_url()`。新建的 endpoint `stale_since` 默认 NULL（创建即视为干净）。

### 修改 `_apply_outcome`（retest 完成钩子）

在已有逻辑后面追加一句 `store.set_stale_since(ep.id, None)`。语义：retest 跑完了，不管成功失败，stale 都消除（用户已经知道当前状态了，不再"过期"）。

### `EndpointSummary` / `EndpointDetail` 加字段

```python
stale_since: datetime | None
```

前端用它判断要不要显示 banner / 灰徽章。

### URL 规范化函数

新文件不必，加在 `api.py` 里：

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

    Returns the URL with the longest matching suffix removed (longest-match
    so '/v1/chat/completions' wins over '/chat/completions') and trailing
    '/' trimmed.
    """
    s = url.rstrip("/")
    for suffix in _STRIP_SUFFIXES:  # 已按长→短排序
        if s.lower().endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.rstrip("/")
```

同一函数被 `POST /api/endpoints`、`PATCH /api/endpoints/{id}`、和下面的 `_parse_curl` 修复共用。

### 修复 `_parse_curl`

现状（`api.py:540-548`）：

```python
if "/v1" in url:
    url = url.split("/v1", 1)[0] + "/v1"
else:
    sp = urlsplit(url)
    url = f"{sp.scheme}://{sp.netloc}"   # 智谱被砍到只剩 host，bug
```

改成直接走 `normalize_base_url`，去掉那个 `else` 砍 host 分支：

```python
url = normalize_base_url(url)
```

副作用：标准的 OpenAI curl `https://api.openai.com/v1/chat/completions` 也会被剥成 `https://api.openai.com/v1`，结果一致。智谱的 `.../paas/v4/chat/completions` 现在能正确剥成 `.../paas/v4`，bug 修了。

## 前端改动

### 1. `<BaseUrlInput>` 新组件

`frontend/src/components/BaseUrlInput.tsx`，包一层标准 `<Input>`：

- props: `value`, `onChange`, `id` 等
- 内部维护 `suggestion: string | null` —— 用同一份 `_STRIP_SUFFIXES` 逻辑（前端 TS 复刻一份；列表短）实时检测尾巴
- 命中时在 input 下方显示一行小字：
  > `检测到完整接口 URL，建议改成 https://open.bigmodel.cn/api/paas/v4` [采用]
- "采用"按钮 → 调 `onChange(suggestion)` 把建议值塞进去 → 提示消失

`AddEndpointDialog` 和 `EditEndpointDialog`（下一节）的 base_url 输入位都换成 `<BaseUrlInput>`。

### 2. `EditEndpointDialog`

复用现有 `AddEndpointDialog.tsx` —— 改造它接受可选的 `mode: "add" | "edit"` + `initial?: EndpointDetail`：

- `mode === "add"`：行为不变（必填、提交 → POST、自动 discover）
- `mode === "edit"`：所有输入预填 `initial`；`api_key` 默认显示 mask，可点眼睛切换；提交 → PATCH；不触发 discover/probe

或者复制一份成 `EditEndpointDialog.tsx` 也行——共享一组 form field 子组件即可。倾向**参数化同一个 dialog**，因为字段几乎一样，重复成本不值得。

入口：`EndpointDetailDrawer` 标题旁边加一个铅笔按钮，点击 → 打开 dialog（mode=edit）。

### 3. Stale 视觉

`EndpointDetailDrawer`：

- 当 `endpoint.stale_since != null` —— drawer 顶部加一条 amber banner：
  > 端点配置已修改（{相对时间，如 "5 分钟前"}），数据可能过期。建议点击 Retest 重新探测。
- 模型列表里所有 status 徽章加 `opacity-50` —— 让人一眼看出"这是过期数据"。其他列（latency、error）保持原样可读，只是徽章变灰。

`EndpointTable`（主列表）：endpoint 名字旁边 stale 时加一个小灰点或 `(stale)` 标记，让人不进 drawer 也能察觉。

Retest 成功后接口返回新的 `EndpointDetail`（`stale_since` 已被后端置 NULL），前端 query 失效后 banner / 灰度自动消失。

### 4. API client

`frontend/src/lib/api.ts` 加：

```typescript
patchEndpoint: (idOrName: string, body: Partial<EndpointUpdate>) =>
    fetch(`${BASE}/api/endpoints/${idOrName}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...auth.header() },
        body: JSON.stringify(body),
    }).then(handle)
```

类型定义 `EndpointUpdate` 跟后端 schema 对齐。

## Edge cases

- **改 `name` 改成已存在的别名** → 后端 409，前端 dialog 显示错误，输入框红框。
- **改 `name` 改成自己当前名字** → 后端检测到 `existing.name == new_name` 跳过冲突检查（不算冲突）。
- **改了 `base_url` 但规范化之后跟旧值相等** → 不算 base_url 变化，不触发 stale。
- **传了 `base_url` 但值跟现有相同** → 不触发 stale。
- **同一次 PATCH 又改了 `note` 又改了 `base_url`** → 后者触发 stale，note 字段照样写入。
- **PATCH 提交了空 body** → 200，啥也不干，`updated_at` 也不刷新（避免无意义版本号跳动）。
- **改 `sdk` 后老 `models[]` 是 OpenAI 模型名** → stale banner + 灰徽章给信号，用户点 Retest，`probe_endpoint` 在 discover 模式下会重新调 `list_models()`，新结果替换旧 results；老的 `models[]` 列表是否同步替换取决于现有 `_apply_outcome` 行为（目前只 replace results；如果发现 list 没同步是 pre-existing 问题，单独 issue）。

## 测试

加在 `tests/test_api.py`：

- `normalize_base_url` 单元测试覆盖 6 个 suffix + 末尾 `/`
- PATCH 改单字段（每个字段一例）
- PATCH 改 `name` 撞已有 → 409
- PATCH 改 `name` 改成自己 → 200
- PATCH 改 `base_url` 触发 stale_since 被设
- PATCH 只改 `note` 不触发 stale
- PATCH 改 `base_url` 但规范化后等于旧值 → 不触发 stale
- POST `/api/endpoints` 时 base_url 自动剥尾
- retest 之后 stale_since 被清回 NULL
- `_parse_curl` 喂智谱 `.../paas/v4/chat/completions` curl → 剥成 `.../paas/v4`（回归测试）

前端可以加 vitest 单测 `<BaseUrlInput>`，但不是阻塞项；先后端 + 手动 UI 测过即可。

## Out of scope（未来工作）

- CLI 端 `probe edit` 命令
- "Test connection" 按钮（在保存前先打个 `/models` 探活）
- 编辑历史 / 审计日志
- `models[]` 列表在 retest 时也跟着 discover 同步刷新（pre-existing，本次不动）
