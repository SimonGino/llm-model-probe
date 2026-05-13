# 模型列表按 Provider 分组

**日期**: 2026-05-13
**状态**: 已口头确认
**基于**: `docs/specs/2026-05-01-ui-design.md`、`2026-05-05-model-row-polish-design.md`

## 背景

单 endpoint 可能返回上百个模型（实际见到一例 239 个）。当前 `EndpointDetailPane` 把它们按 status 段（Testing / Available / Failed / Untested）切开，每段内部要么按 latency / provider / name 排序，要么走默认的状态相关排序——总之都是**扁平网格**。

在大量模型场景下扁平列表暴露两个痛点：

1. **批量决策成本高**：用户想"qwen-image-* 这一坨全跳过"或"只测 deepseek-* 这一组"，得手动一个一个勾选。
2. **视觉混杂**：同一段里 qwen / deepseek / kimi / MiniMax / glm 等多家模型交错出现，扫一眼找不到自己关心的 provider 在哪。

`detectProvider()` (`frontend/src/lib/provider.tsx`) 已经能把模型名映射到 provider key，且这个映射已被用于 row 的 provider 图标和现有的 "provider sort"。分组的原语其实早就在了，只是没拼起来。

## 目标

1. 让用户能在每个 status 段内部按 provider 把模型聚成可折叠子组，并对子组做批量选择。
2. 复用现有 `detectProvider()`，不引入新的分组规则源。
3. 与现有的 sort / search / 全选 TriCheckbox 交互一致，不打破任何现有行为。
4. 改动局部化在 `EndpointDetailPane.tsx`，后端 / API / store 零变化。

## 不做的事

- **不重写 status 分段**：保留 Testing / Available / Failed / Untested 四段。分组是在 status 段**内部**再切一层，不是替换 status 段。
- **不引入持久化**：折叠状态是 session-scoped、内存里的 Map，切 endpoint 或 reload 都重置。理由：现有 `checked` 选中状态也是这样处理的（`useEffect` 在 endpoint id 切换时重置），保持一致；持久化引入的复杂度（localStorage key 设计、跨标签页同步）对一次性的"全选 / 跳过这组"操作没收益。
- **不扩 RULES**：不在本次顺手扩 `provider.tsx` 里的 RULES 数组识别 MiniMax / kimi/ 前缀这类情况——所有 unknown 走"other"兜底子组。如果 RULES 漏识别成为问题，单独做一次。
- **不做 Testing 段的分组**：那段是动态进出的瞬时状态，分组没意义，保持扁平。
- **不对 sort 模式做正交化**：不引入"按 latency 排序 + 按 provider 分组"的组合。分组是 sort 模式的一种，互斥不正交。理由：现状下 sort 是单选 toggle，正交化要么给 sort 加多键、要么加独立 group 按钮——前者复杂、后者 UI 多一个常驻控件。当前只有"分组里也按 latency 排"这种诉求不强（用户已经选了"组内按名字字母序"）。
- **不做嵌套折叠的过渡动画**：手动展开收起即时切换，避免重排抖动。

## 用户交互

`SortControls` 三按钮 `[latency] [provider] [name]` 升级为四态：

| 状态 | 按钮显示 | 行为 |
|---|---|---|
| `default` | `[latency]` 选中 | 现状：Available 按 latency、Failed 按 error_type、Untested 按 name |
| `provider`（排序） | `[provider]` 选中、无 ▾ | 现状：扁平按 provider key 排序 |
| `provider-group`（分组） | `[provider ▾]` 选中 | 新增：在每个 status 段内按 provider 切子组 |
| `name` | `[name]` 选中 | 现状：扁平按名字字母序 |

切换逻辑（基于点 `provider` 按钮时的当前 mode）：

- 当前 mode 不在 `{provider, provider-group}` → 跳到 `provider`
- 当前 mode 为 `provider` → 跳到 `provider-group`
- 当前 mode 为 `provider-group` → 跳回 `default`（避开"循环到 sort 再点又跳回来"的颠簸）
- 点 `latency` / `name` → 直接走对应 mode，任何 provider 子态丢弃

按钮视觉：`provider-group` 态下按钮标签是 `provider ▾`，比 `provider` 多一个 caret 字符示意分组态。

## 数据流

```
visible (经过 modelSearch 过滤)
  ↓
按 status 分段: testing / available / failed / untested
  ↓
applySort(段, mode)            // 现有逻辑, 处理前 3 种 mode
  ↓
mode === "provider-group" ?
  ↓ 是
groupByProvider(段)             // 新增
  ↓
[{ key: "qwen", rows: [...] }, { key: "deepseek", rows: [...] }, ..., { key: "other", rows: [...] }]
  ↓
ModelGroup (status 段头) → ProviderSubGroup × N (provider 子组)
```

新函数：

```typescript
type ProviderGroup = {
  key: ProviderKey | "other";
  rows: string[];  // 已按 name 字母序
};

function groupByProvider(rows: string[]): ProviderGroup[] {
  const buckets = new Map<string, string[]>();
  for (const m of rows) {
    const k = detectProvider(m);
    const bucket = k === "unknown" ? "other" : k;
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket)!.push(m);
  }
  for (const arr of buckets.values()) arr.sort((a, b) => a.localeCompare(b));
  return [...buckets.entries()]
    .map(([key, rows]) => ({ key: key as ProviderKey | "other", rows }))
    .sort((a, b) => {
      if (a.key === "other") return 1;
      if (b.key === "other") return -1;
      if (a.rows.length !== b.rows.length) return b.rows.length - a.rows.length;
      return a.key.localeCompare(b.key);  // tie-break
    });
}
```

## 组件结构

新增 `ProviderSubGroup` 组件，复用 `ModelGroup` 的视觉语言但缩一级。`ModelGroup` 接收可选的 `subGroups`：传了就走嵌套渲染，没传则照旧（Testing 段保持扁平）。

```typescript
function ModelGroup({
  title, tone, rows, subGroups, ...passThrough
}: {
  ...
  subGroups?: ProviderGroup[];  // 新增, 优先级高于 rows
  ...
}) {
  // 头部 (TriCheckbox + dot + title + count) 不变, 全选作用于 rows (扁平) 或 subGroups.flatMap(g => g.rows)
  // 若 subGroups 传入: 渲染 N 个 ProviderSubGroup 而非扁平 grid
  // 若仅 rows 传入: 原扁平 grid
}

function ProviderSubGroup({
  parentKey,           // e.g. "untested" — 用于 collapsed map 的 key
  providerKey,         // e.g. "qwen" | "other"
  rows,
  checked, toggle, toggleAll,
  resultByModel, orch, ep, stale,
  collapsed, toggleCollapsed,
}: { ... }) {
  // 头部行布局 (左到右):
  //   <TriCheckbox onClick={全选/反选本组 row}>  — 独立点击区，不冒泡到折叠
  //   <button onClick={toggleCollapsed}>          — 这个 button 包住后续所有元素:
  //     <ProviderIcon modelId={rows[0]} />        — "other" 子组 ProviderIcon 自然 fallback 到 cpu icon
  //     <span>{providerKey}</span>
  //     <span>{rows.length}</span>
  //     <Icon name={collapsed ? "chevron-right" : "chevron-down"} />
  //   </button>
  // collapsed === false → 渲染同样的 grid (同 ModelGroup 现在用的 auto-fill 网格)
  // collapsed === true  → 只显示头部
}
```

视觉缩级方式：

- 子组头字体比 status 段头小一档（10px → 11px tone-muted）
- 子组本身有左侧 4px 的左边距 + 左边框（`border-left: 1px solid var(--border)`）形成视觉缩进
- caret 用现有 `<Icon name="chevron-right">`（collapsed）/ `<Icon name="chevron-down">`（expanded），两个 name 都在 `frontend/src/components/atoms.tsx` 已定义

## 折叠状态

```typescript
const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
// key 形如 "untested:qwen" / "available:deepseek" / "failed:other"
// 缺失即展开 (默认全展开)

function toggleCollapsed(parentKey: string, providerKey: string) {
  const k = `${parentKey}:${providerKey}`;
  setCollapsed(prev => {
    const n = new Set(prev);
    if (n.has(k)) n.delete(k); else n.add(k);
    return n;
  });
}
```

**生命周期**：

- 跟随 `checked` 的 `useEffect`，在 endpoint id 切换时清空：
  ```typescript
  useEffect(() => {
    if (!detail.data) return;
    // ... 现有 checked 重置逻辑 ...
    setCollapsed(new Set());
  }, [detail.data?.id]);
  ```
- `sortMode` 离开 `provider-group` 时也清空（避免回来时残留陈旧折叠态）：
  ```typescript
  useEffect(() => {
    if (sortMode !== "provider-group") setCollapsed(new Set());
  }, [sortMode]);
  ```

**搜索联动**：

```typescript
const isSearching = modelSearch.trim() !== "";
// 在渲染层 (ProviderSubGroup props) 计算:
const effectiveCollapsed = isSearching ? false : collapsed.has(k);
```

搜索激活时所有子组强制展开但不写 Set；清空搜索词后恢复用户手动折叠态。

## 边界与回归

- **空子组**：`groupByProvider` 不会产生空 bucket（只对实际出现的模型建 bucket），不需要特殊处理。但搜索过滤可能让某子组所有 row 都不匹配——这时是上游 `visible` 过滤掉了那些 row，根本不会进 `groupByProvider`。
- **filter-skip 模型**：`ep.excluded_by_filter` 在 `ModelRow` 内部读取，分组对这个状态透明，row 视觉表现不变。
- **单 provider 极端情况**：所有模型同一 provider（如全 qwen）→ 单个子组，看起来比扁平多一个标题行，可接受。
- **零 row 的 status 段**：`ModelGroup` 现在就有 `rows.length > 0` 的渲染门控，分组模式下基于 `subGroups.length > 0` 同理处理。
- **TriCheckbox 全选语义**：
  - status 段全选 → 选中该段所有 row（不论分组与否）
  - provider 子组全选 → 选中该子组的 row
  - 顶部 "Models" 全选 → 选中所有 visible row（不变）
- **"selected N" / "Test selected" 按钮**：基于 `checked` 集合，与分组无关，行为不变。
- **`exclude` 列表的 filter-skip 模型**：默认不在 `checked` 里（line 38-43 已经 `models.filter(m => !excl.has(m))`），分组不影响这层。
- **i18n**：`other` 显示为字面字符串 `other`，与 UI 现有英文 / 中文混用风格一致（status 段标题也是英文）。不引入 i18n 层。

## 测试

前端没有 test runner，验证靠：

- `cd frontend && npm run build` 编译 + 类型通过
- `cd frontend && npm run lint` 无错
- `uv run pytest -q` 后端测试保持绿（应当与前端改动完全无关，零变更）
- 手动浏览器验证 4 个场景：
  1. 切到 `provider ▾` → 各 status 段出现 provider 子组，"other" 在末尾，子组按 count 降序，组内按名字字母序
  2. 折叠某子组 → 子组 row 隐藏；展开 → 恢复；切到 `name` mode → 折叠态清空；切回 `provider ▾` → 默认全展开
  3. filter 框输入 "qwen-coder" → 所有命中子组自动展开；清空 → 恢复手动折叠态
  4. 子组 TriCheckbox 全选 → 该子组所有 row 选中 + 顶部 "X selected" 正确累加 + status 段 TriCheckbox 变 indeterminate

## 实现顺序建议

1. `groupByProvider` 纯函数（写在 `EndpointDetailPane.tsx` 文件内 helper 区）
2. `ProviderSubGroup` 子组件
3. `ModelGroup` 接收 `subGroups` 分支
4. `SortControls` 加 `provider-group` 态 + 按钮 caret 显示逻辑
5. `EndpointDetailPane` 顶层引入 `collapsed` state + 两个 `useEffect` 清空钩子
6. 把 `provider-group` 态串通到三个 status 段（available / failed / untested）的 `ModelGroup` 调用处

## Out of scope（未来工作）

- 跨 endpoint 持久化折叠偏好（localStorage）
- 子组级"测试本组"按钮（现在通过 TriCheckbox 全选 + 顶部 "Test selected" 两步实现）
- 把 RULES 扩展到识别 MiniMax / kimi/ 前缀（独立的 provider 识别质量改进）
- 多键 sort（在分组态下还能选组内按 latency 还是按名字）
- 折叠 / 展开过渡动画
