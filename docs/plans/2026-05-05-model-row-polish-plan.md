# 模型行视觉密度优化 — 实施计划

> **给 agent 用**：用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 一个任务一个任务地执行。每步用 `- [ ]` 复选框跟踪。

**目标**：实现 `docs/specs/2026-05-05-model-row-polish-design.md` 里的 5 项叠加 polish — provider 图标 + 双列网格 + latency 色阶 + hover-only 复制按钮 + 段内 provider 聚类排序。

**架构**：纯前端改动，零后端。新增一个 `lib/provider.tsx` 文件承载 provider detection + icon。`EndpointDetailPane.tsx` 内做 5 处叠加修改，每个任务一个原子提交。CSS 在 `index.css` 加几条 `.model-row` 规则。`atoms.tsx` 加一个 `cpu` icon + 给 `CopyBtn` 加 `data-copied` 属性。

**技术栈**：React 19 + TypeScript + Vite + Tailwind（已用）+ `@lobehub/icons`（新增）。无前端测试框架，靠 build / lint / 手动 smoke 验证。

---

## 文件结构

```
frontend/
├── package.json                            # 修改: 加 @lobehub/icons 依赖
├── package-lock.json                       # 自动重新生成
├── src/
│   ├── lib/
│   │   └── provider.tsx                    # 新建: detectProvider + ProviderIcon
│   ├── components/
│   │   ├── atoms.tsx                       # 修改: 加 "cpu" icon + CopyBtn 加 data-copied
│   │   └── EndpointDetailPane.tsx          # 修改: ModelRow 加图标 + 双列网格 + latency 色阶
│   │                                       #       + hover 复制 + 段内排序切换
│   └── index.css                           # 修改: .model-row 系列规则
```

---

## 任务 1：Provider 图标基础设施 — 装包 + provider.tsx + cpu icon

**文件**：
- 修改：`frontend/package.json`
- 修改：`frontend/src/components/atoms.tsx`
- 新建：`frontend/src/lib/provider.tsx`

- [ ] **步骤 1：在 frontend 目录下安装 @lobehub/icons**

```bash
cd frontend && npm install @lobehub/icons
```

预期：`package.json` 的 dependencies 多了一条 `"@lobehub/icons": "..."`，`package-lock.json` 同步更新。

- [ ] **步骤 2：在 atoms.tsx 的 IconName 联合类型加上 "cpu"，并实现该 case**

打开 `frontend/src/components/atoms.tsx`，把 `IconName` 类型从：

```ts
type IconName =
  | "plus"
  | "x"
  | "refresh"
  | "search"
  | "trash"
  | "copy"
  | "check"
  | "eye"
  | "eye-off"
  | "logout"
  | "settings"
  | "filter"
  | "chevron-down"
  | "chevron-right"
  | "play"
  | "globe"
  | "lock"
  | "key"
  | "bolt"
  | "clock"
  | "tag"
  | "sun"
  | "moon"
  | "circle-half";
```

改为（末尾追加 `"cpu"`）：

```ts
type IconName =
  | "plus"
  | "x"
  | "refresh"
  | "search"
  | "trash"
  | "copy"
  | "check"
  | "eye"
  | "eye-off"
  | "logout"
  | "settings"
  | "filter"
  | "chevron-down"
  | "chevron-right"
  | "play"
  | "globe"
  | "lock"
  | "key"
  | "bolt"
  | "clock"
  | "tag"
  | "sun"
  | "moon"
  | "circle-half"
  | "cpu";
```

并在 `switch (name)` 的最后一个 `case "circle-half":` 之后、`default:` 之前插入：

```tsx
    case "cpu":
      return (
        <svg {...common}>
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <rect x="9" y="9" width="6" height="6" />
          <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
        </svg>
      );
```

- [ ] **步骤 3：跑 tsc 确认 atoms 改动编译通过**

```bash
cd frontend && npm run build
```

预期：构建成功，dist/ 目录生成。如果失败，检查 IconName 类型联合是否完整、case 是否在 default 之前。

- [ ] **步骤 4：新建 `frontend/src/lib/provider.tsx`**

注意文件扩展名是 `.tsx`（spec 写的 `.ts` 有误，因为 ProviderIcon 含 JSX），完整内容：

```tsx
import {
  Qwen,
  DeepSeek,
  OpenAI,
  Claude,
  Gemini,
  Mistral,
  Meta,
  Yi,
  Moonshot,
  Zhipu,
  Cohere,
  Doubao,
  Hunyuan,
  Spark,
  Baichuan,
} from "@lobehub/icons";
import { Icon } from "@/components/atoms";

export type ProviderKey =
  | "qwen"
  | "deepseek"
  | "openai"
  | "claude"
  | "gemini"
  | "mistral"
  | "llama"
  | "yi"
  | "moonshot"
  | "zhipu"
  | "cohere"
  | "doubao"
  | "hunyuan"
  | "spark"
  | "baichuan"
  | "unknown";

interface Rule {
  key: ProviderKey;
  match: RegExp;
}

// 顺序敏感: 更具体的 pattern 在前. 第一个命中即返回.
const RULES: Rule[] = [
  { key: "qwen", match: /^(qwen|qwq|qvq|tongyi)/i },
  { key: "deepseek", match: /^deepseek/i },
  { key: "claude", match: /^claude/i },
  { key: "gemini", match: /^gemini/i },
  { key: "openai", match: /^(gpt|o[1-9](-|$)|text-|davinci|chatgpt)/i },
  { key: "mistral", match: /^(mistral|mixtral|codestral|ministral)/i },
  { key: "llama", match: /^(llama|meta-llama)/i },
  { key: "yi", match: /^yi-/i },
  { key: "moonshot", match: /^(moonshot|kimi)/i },
  { key: "zhipu", match: /^(glm|chatglm)/i },
  { key: "cohere", match: /^(command|cohere)/i },
  { key: "doubao", match: /^doubao/i },
  { key: "hunyuan", match: /^hunyuan/i },
  { key: "spark", match: /^spark/i },
  { key: "baichuan", match: /^baichuan/i },
];

export function detectProvider(modelId: string): ProviderKey {
  for (const r of RULES) {
    if (r.match.test(modelId)) return r.key;
  }
  return "unknown";
}

const ICON_MAP: Record<
  Exclude<ProviderKey, "unknown">,
  React.ComponentType<{ size?: number }>
> = {
  qwen: Qwen,
  deepseek: DeepSeek,
  openai: OpenAI,
  claude: Claude,
  gemini: Gemini,
  mistral: Mistral,
  llama: Meta,
  yi: Yi,
  moonshot: Moonshot,
  zhipu: Zhipu,
  cohere: Cohere,
  doubao: Doubao,
  hunyuan: Hunyuan,
  spark: Spark,
  baichuan: Baichuan,
};

export function ProviderIcon({
  modelId,
  size = 14,
}: {
  modelId: string;
  size?: number;
}) {
  const key = detectProvider(modelId);
  if (key === "unknown") {
    return (
      <Icon name="cpu" size={size} style={{ color: "var(--text-faint)" }} />
    );
  }
  const Comp = ICON_MAP[key];
  return <Comp size={size} />;
}
```

> 提示：`@lobehub/icons` 的具体导出名按官方包为准；如果某个 named import 失败，去 `node_modules/@lobehub/icons/package.json` 看真实 main / exports，再调整 import 路径或名字。常见情况是要 `from "@lobehub/icons"` 直接 named import，少数情况是分子包。**遇到 import 报错时不要拆分 spec，先在 atoms 暂用 cpu fallback 跑通，再回来修。**

- [ ] **步骤 5：跑 build + lint 确认通过**

```bash
cd frontend && npm run build && npm run lint
```

预期：build 成功，lint 0 error。即使 ProviderIcon 暂时没人用，也不应报"未使用导出"——TS 默认不警告未使用的 export。

- [ ] **步骤 6：提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/provider.tsx frontend/src/components/atoms.tsx
git commit -m "feat(frontend): add @lobehub/icons + provider detection helper

- New lib/provider.tsx with detectProvider() + ProviderIcon component
- Add 'cpu' icon to atoms.tsx as fallback for unknown providers"
```

---

## 任务 2：把 ProviderIcon 接进 ModelRow

**文件**：
- 修改：`frontend/src/components/EndpointDetailPane.tsx`

- [ ] **步骤 1：在 EndpointDetailPane.tsx 顶部加 ProviderIcon 的 import**

打开 `frontend/src/components/EndpointDetailPane.tsx`，在现有 import 区域（第 1-14 行）末尾加：

```ts
import { ProviderIcon } from "@/lib/provider";
```

- [ ] **步骤 2：在 ModelRow 的 checkbox 和 model 名之间插入 ProviderIcon**

定位到 `ModelRow` 函数（第 564 行附近）的 JSX。当前结构是：

```tsx
<label ...>
  <input type="checkbox" ... />
  <span className="mono" style={{ fontSize: 12, flex: 1, ... }}>
    {model}
  </span>
  <CopyBtn text={model} title="Copy model id" />
  <ModelStatus ... />
</label>
```

在 `<input type="checkbox" ... />` 之后、`<span className="mono"...>` 之前插入：

```tsx
      <ProviderIcon modelId={model} size={14} />
```

整段变成：

```tsx
<label
  style={{
    display: "flex",
    alignItems: "center",
    gap: 9,
    padding: "7px 12px",
    borderBottom: last ? "none" : "1px solid var(--border)",
    cursor: "pointer",
    transition: "background .1s",
  }}
  onMouseEnter={(e) =>
    (e.currentTarget.style.background = "var(--bg-hover)")
  }
  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
>
  <input
    type="checkbox"
    checked={checked}
    onChange={toggle}
    style={{ accentColor: "var(--text)" }}
  />
  <ProviderIcon modelId={model} size={14} />
  <span
    className="mono"
    style={{
      fontSize: 12,
      flex: 1,
      minWidth: 0,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
    }}
  >
    {model}
  </span>
  <CopyBtn text={model} title="Copy model id" />
  <ModelStatus
    result={result}
    transientError={transientError}
    filterSkip={filterSkip}
    pulse={pulse}
  />
</label>
```

- [ ] **步骤 3：build + lint**

```bash
cd frontend && npm run build && npm run lint
```

预期：通过。

- [ ] **步骤 4：手动 smoke**

```bash
cd frontend && npm run dev
```

打开浏览器（vite 默认 http://localhost:5173），打开任意 endpoint 详情，确认：
- 模型行最左 checkbox 之后多了一个 14px 的图标
- `qwen-*` 行显示 Qwen 紫色图标
- `deepseek-*` 行显示 DeepSeek 蓝色图标
- `gpt-*` 行显示 OpenAI 黑/白图标
- 不识别的（如 `Pro/Qwen2-72B-Instruct`、`Doubao-1.5-pro`）显示 cpu 矩形 fallback

如果颜色不对，是 lobehub 默认行为；不强求改。

- [ ] **步骤 5：提交**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(frontend): show provider icon in each ModelRow"
```

---

## 任务 3：Latency 色阶（< 500 绿 / 500–2000 灰 / > 2000 黄）

**文件**：
- 修改：`frontend/src/components/EndpointDetailPane.tsx`

- [ ] **步骤 1：在 EndpointDetailPane.tsx 文件底部（在最后一个 `}` 之后，也就是 `function ModelStatus` 之后）加 `latencyTone` 辅助函数**

定位到文件末尾的 `function ModelStatus(...)` 闭合大括号 `}` 之后（第 712 行 `}` 之后），追加：

```ts
function latencyTone(ms: number): { color: string; label: string } {
  if (ms < 500) return { color: "var(--ok)", label: `${ms}ms` };
  if (ms < 2000) return { color: "var(--text-muted)", label: `${ms}ms` };
  return { color: "var(--warn)", label: `${ms}ms` };
}
```

- [ ] **步骤 2：把 ModelStatus 中 available 分支的渲染改成用 latencyTone**

定位到 `ModelStatus` 里 `if (result.status === "available")` 这一段（第 656-672 行附近）。当前：

```tsx
if (result.status === "available") {
  return (
    <span
      className="mono"
      style={{
        fontSize: 11,
        color: "var(--ok)",
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      <Icon name="check" size={10} />
      {result.latency_ms}ms
    </span>
  );
}
```

改为：

```tsx
if (result.status === "available") {
  const { color, label } = latencyTone(result.latency_ms ?? 0);
  return (
    <span
      className="mono"
      style={{
        fontSize: 11,
        color,
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      <Icon name="check" size={10} />
      {label}
    </span>
  );
}
```

> 注意：`result.latency_ms` 在 `ModelResultPublic` 上是 `number | null`，所以用 `?? 0` 兜底；available 分支理论上 latency 必有值，0 只是给 TS 看。

- [ ] **步骤 3：build + lint**

```bash
cd frontend && npm run build && npm run lint
```

预期：通过。

- [ ] **步骤 4：手动 smoke**

dev server 还在跑的话热更新即可，否则重启。打开 endpoint 详情看 Available 段：
- 延迟 `< 500ms` 的行 → 绿色 ✓ + 时长
- `500-2000ms` 的行 → 灰色 ✓ + 时长（`var(--text-muted)`）
- `> 2000ms` 的行 → 黄色 ✓ + 时长（`var(--warn)`）
- Failed 段保持红色 ✗（不动）
- Untested 段保持灰色（不动）

- [ ] **步骤 5：提交**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(frontend): tier latency color in ModelStatus by ms threshold

< 500 ok / 500-2000 muted / > 2000 warn"
```

---

## 任务 4：双列响应式网格 + `model-row` class

**文件**：
- 修改：`frontend/src/components/EndpointDetailPane.tsx`
- 修改：`frontend/src/index.css`

- [ ] **步骤 1：在 index.css 末尾追加 `.model-row` 基础样式**

打开 `frontend/src/index.css`，在文件末尾（`@keyframes popIn` 之后）追加：

```css
.model-row {
  background: var(--bg-elev);
  transition: background 0.1s;
}
.model-row:hover {
  background: var(--bg-hover);
}
```

- [ ] **步骤 2：把 ModelGroup 内包裹 ModelRow 的容器改成 grid（用 gap 透出 border）**

定位到 `ModelGroup` 函数里渲染 rows 的 `<div>`（第 533-540 行附近）：

```tsx
<div
  style={{
    border: "1px solid var(--border)",
    borderRadius: 7,
    overflow: "hidden",
    background: "var(--bg-elev)",
  }}
>
  {rows.map((m, i) => {
    ...
    return (
      <ModelRow
        ...
        last={i === rows.length - 1}
        ...
      />
    );
  })}
</div>
```

改为（用 `gap: 1` + `background: var(--border)` 让间隙透出分隔线，去掉 `last` 计算）：

```tsx
<div
  style={{
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
    gap: 1,
    border: "1px solid var(--border)",
    borderRadius: 7,
    overflow: "hidden",
    background: "var(--border)",
  }}
>
  {rows.map((m) => {
    const r = resultByModel.get(m);
    const te = orch.errorFor(ep.id, m);
    const filterSkip = ep.excluded_by_filter.includes(m);
    return (
      <ModelRow
        key={m}
        model={m}
        result={r ?? null}
        transientError={te}
        filterSkip={filterSkip}
        checked={checked.has(m)}
        toggle={() => toggle(m)}
        pulse={!!pulse}
      />
    );
  })}
</div>
```

> 关键改动：
> - `display: "grid"` + `gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))"` —— 容器宽 ≥ 520 时双列，更窄时单列
> - `gap: 1` + 容器 `background: "var(--border)"` —— 用网格间隙的 1px 背景透出分隔线，每个 row 自己 bg-elev 盖住其余
> - 去掉 `last={i === rows.length - 1}` —— 最后一行不再需要特殊处理
> - 整段 `rows.map((m, i)` 的 `i` 没用了，改成 `rows.map((m) =>`

- [ ] **步骤 3：把 ModelRow 改成用 `.model-row` class，去掉 `last` prop 和 inline hover handlers**

定位到 `ModelRow` 函数签名（第 564-582 行）：

```tsx
function ModelRow({
  model,
  result,
  transientError,
  filterSkip,
  checked,
  toggle,
  last,
  pulse,
}: {
  model: string;
  result: ModelResultPublic | null;
  transientError: string | null;
  filterSkip: boolean;
  checked: boolean;
  toggle: () => void;
  last: boolean;
  pulse: boolean;
}) {
```

改为（去掉 `last`）：

```tsx
function ModelRow({
  model,
  result,
  transientError,
  filterSkip,
  checked,
  toggle,
  pulse,
}: {
  model: string;
  result: ModelResultPublic | null;
  transientError: string | null;
  filterSkip: boolean;
  checked: boolean;
  toggle: () => void;
  pulse: boolean;
}) {
```

然后 ModelRow 的 `<label>` 元素（第 583-598 行附近）：

```tsx
<label
  style={{
    display: "flex",
    alignItems: "center",
    gap: 9,
    padding: "7px 12px",
    borderBottom: last ? "none" : "1px solid var(--border)",
    cursor: "pointer",
    transition: "background .1s",
  }}
  onMouseEnter={(e) =>
    (e.currentTarget.style.background = "var(--bg-hover)")
  }
  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
>
```

改为（用 className，去掉 inline hover、去掉 borderBottom、padding 略缩）：

```tsx
<label
  className="model-row"
  style={{
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 10px",
    cursor: "pointer",
    minWidth: 0,
  }}
>
```

> `minWidth: 0` 关键——确保 grid cell 内的 model 名 ellipsis 生效，否则 cell 会被长名撑开破坏双列。

- [ ] **步骤 4：build + lint**

```bash
cd frontend && npm run build && npm run lint
```

预期：通过。如果 lint 报 `last` 未使用的旧引用，搜索 `last` 在 EndpointDetailPane 里所有出现，确保 ModelGroup → ModelRow 调用处也已删除 `last={...}`。

- [ ] **步骤 5：手动 smoke**

dev 浏览器观察：
- 容器 ≥ 520px 时双列；窄到单列时无视觉破损
- 列与列、行与行之间是 1px 细线（不是双线、不是错位）
- 每个 row hover 仍然背景变深（`var(--bg-hover)`）
- 长模型名（如 `Pro/Qwen2-72B-Instruct-GPTQ-Int4`）单元格内 ellipsis，不撑开格子
- 拖动浏览器宽度，列数从 1→2→3 平滑过渡（如果 drawer 够宽，3 列也合理）

如果某种宽度下出现"双线"（列 / 行间隙超过 1px），把 `gap: 1` 改成 `gap: "1px"` 显式字符串。

- [ ] **步骤 6：提交**

```bash
git add frontend/src/components/EndpointDetailPane.tsx frontend/src/index.css
git commit -m "feat(frontend): 2-column responsive grid for model rows

- ModelGroup container: grid auto-fill minmax(260px, 1fr) with 1px gap trick
- ModelRow: model-row class for hover bg, drop last prop"
```

---

## 任务 5：Hover-only 复制按钮（CSS + CopyBtn data-copied）

**文件**：
- 修改：`frontend/src/components/atoms.tsx`
- 修改：`frontend/src/components/EndpointDetailPane.tsx`
- 修改：`frontend/src/index.css`

- [ ] **步骤 1：在 atoms.tsx 的 CopyBtn 内部 button 上加 `data-copied`**

定位到 `CopyBtn` 组件（atoms.tsx 第 245-266 行）。当前：

```tsx
export function CopyBtn({ text, title = "复制" }: { text: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-ghost btn-icon btn-sm"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(text).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1100);
      }}
      title={title}
    >
      <Icon
        name={copied ? "check" : "copy"}
        size={12}
        style={{ color: copied ? "var(--ok)" : "var(--text-muted)" }}
      />
    </button>
  );
}
```

改成（在 `<button>` 上加 `data-copied={copied || undefined}`）：

```tsx
export function CopyBtn({ text, title = "复制" }: { text: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-ghost btn-icon btn-sm"
      data-copied={copied || undefined}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(text).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1100);
      }}
      title={title}
    >
      <Icon
        name={copied ? "check" : "copy"}
        size={12}
        style={{ color: copied ? "var(--ok)" : "var(--text-muted)" }}
      />
    </button>
  );
}
```

> `copied || undefined` 保证当 copied=false 时 React 不渲染 `data-copied="false"` 属性（避免 CSS `:has([data-copied])` 把它当 truthy）。

- [ ] **步骤 2：在 index.css 已有的 `.model-row` 块下追加 `.row-copy` 规则**

打开 `frontend/src/index.css`，找到任务 4 里加的 `.model-row` 段落，扩成：

```css
.model-row {
  background: var(--bg-elev);
  transition: background 0.1s;
}
.model-row:hover {
  background: var(--bg-hover);
}
.model-row .row-copy {
  opacity: 0;
  transition: opacity 0.12s;
}
.model-row:hover .row-copy {
  opacity: 1;
}
.model-row .row-copy:has([data-copied]) {
  opacity: 1;
}
```

> `:has()` 在 Chrome 105+ / Safari 15.4+ / Firefox 121+ 支持，2026 年的目标用户群可接受。这条规则保证点击复制后 ✓ 反馈不会因为鼠标移走立即消失。

- [ ] **步骤 3：在 EndpointDetailPane.tsx 的 ModelRow 把 CopyBtn 包一层 `<span className="row-copy">`**

定位到 ModelRow 内的 `<CopyBtn text={model} title="Copy model id" />`（任务 2 之后大约第 604 行附近）：

```tsx
<CopyBtn text={model} title="Copy model id" />
```

改为：

```tsx
<span className="row-copy">
  <CopyBtn text={model} title="Copy model id" />
</span>
```

- [ ] **步骤 4：build + lint**

```bash
cd frontend && npm run build && npm run lint
```

预期：通过。

- [ ] **步骤 5：手动 smoke**

dev 浏览器：
- 默认状态：模型行的复制按钮不可见（opacity 0）
- 鼠标移到任意 row 上 → 复制按钮淡入显示（120ms）
- 点击复制按钮 → ✓ 绿色反馈持续 1.1s
- ✓ 反馈期间把鼠标移开 row → ✓ 仍然可见（不会因 hover 失去而消失）
- 1.1s 后复制按钮自动隐藏，row 也未在 hover 内

如果点击后立刻消失，确认 atoms.tsx 的 `data-copied` 真的写在了内层 `<button>` 上（不是 `<Icon>` 上），并且 CSS `:has([data-copied])` 选择器没拼错。

- [ ] **步骤 6：提交**

```bash
git add frontend/src/components/atoms.tsx frontend/src/components/EndpointDetailPane.tsx frontend/src/index.css
git commit -m "feat(frontend): hover-only copy button on model rows

- CopyBtn exposes data-copied attribute when active
- .row-copy fades in on row hover; stays visible during copied feedback via :has()"
```

---

## 任务 6：段内排序切换（latency / provider / name）

**文件**：
- 修改：`frontend/src/components/EndpointDetailPane.tsx`

- [ ] **步骤 1：把 detectProvider 的 import 加进 EndpointDetailPane.tsx**

打开 `frontend/src/components/EndpointDetailPane.tsx`，把任务 2 里加的：

```ts
import { ProviderIcon } from "@/lib/provider";
```

改为：

```ts
import { ProviderIcon, detectProvider } from "@/lib/provider";
```

- [ ] **步骤 2：在 EndpointDetailPane 组件顶部加 SortMode 类型 + state**

定位到 `EndpointDetailPane` 函数体内已有 state 区域（第 29-30 行附近）：

```tsx
const [checked, setChecked] = useState<Set<string>>(new Set());
const [modelSearch, setModelSearch] = useState("");
```

之后追加：

```tsx
const [sortMode, setSortMode] = useState<SortMode>("default");
```

并在文件顶部（在 imports 之后、第一个 export 之前）加 SortMode 类型定义：

```ts
type SortMode = "default" | "provider" | "name";
```

- [ ] **步骤 3：替换现有的 available / failed / untested 分别 `.sort(...)` 为统一的 `applySort` 函数**

定位到第 97-109 行的三个 inline sort：

```tsx
available.sort((a, b) => {
  const la = resultByModel.get(a)?.latency_ms ?? Number.MAX_SAFE_INTEGER;
  const lb = resultByModel.get(b)?.latency_ms ?? Number.MAX_SAFE_INTEGER;
  if (la !== lb) return la - lb;
  return a.localeCompare(b);
});
failed.sort((a, b) => {
  const ea = resultByModel.get(a)?.error_type ?? orch.errorFor(d.id, a) ?? "";
  const eb = resultByModel.get(b)?.error_type ?? orch.errorFor(d.id, b) ?? "";
  if (ea !== eb) return ea.localeCompare(eb);
  return a.localeCompare(b);
});
untested.sort((a, b) => a.localeCompare(b));
```

整段替换为：

```tsx
function applySort(rows: string[], section: "available" | "failed" | "untested"): string[] {
  if (sortMode === "provider") {
    return [...rows].sort((a, b) => {
      const pa = detectProvider(a);
      const pb = detectProvider(b);
      if (pa !== pb) return pa.localeCompare(pb);
      return a.localeCompare(b);
    });
  }
  if (sortMode === "name") {
    return [...rows].sort((a, b) => a.localeCompare(b));
  }
  // default 模式：每段保持原有排序
  if (section === "available") {
    return [...rows].sort((a, b) => {
      const la = resultByModel.get(a)?.latency_ms ?? Number.MAX_SAFE_INTEGER;
      const lb = resultByModel.get(b)?.latency_ms ?? Number.MAX_SAFE_INTEGER;
      if (la !== lb) return la - lb;
      return a.localeCompare(b);
    });
  }
  if (section === "failed") {
    return [...rows].sort((a, b) => {
      const ea = resultByModel.get(a)?.error_type ?? orch.errorFor(d.id, a) ?? "";
      const eb = resultByModel.get(b)?.error_type ?? orch.errorFor(d.id, b) ?? "";
      if (ea !== eb) return ea.localeCompare(eb);
      return a.localeCompare(b);
    });
  }
  return [...rows].sort((a, b) => a.localeCompare(b));
}

const availableSorted = applySort(available, "available");
const failedSorted = applySort(failed, "failed");
const untestedSorted = applySort(untested, "untested");
```

> 注意：原来的 `available`、`failed`、`untested` 是 `let` 数组，被 in-place `.sort` 修改了。改成 `applySort` 返回新数组，原变量保留为 push 阶段的中间产物。下面渲染处要用新名字。

- [ ] **步骤 4：把 ModelGroup 渲染处用上新排序变量**

定位到第 333-381 行的 4 个 `<ModelGroup ... rows={...} ...>`：

```tsx
{testing.length > 0 && (
  <ModelGroup
    title="Testing"
    ...
    rows={testing}
    ...
  />
)}
{available.length > 0 && (
  <ModelGroup
    title="Available"
    ...
    rows={available}
    ...
  />
)}
{failed.length > 0 && (
  <ModelGroup
    title="Failed"
    ...
    rows={failed}
    ...
  />
)}
{untested.length > 0 && (
  <ModelGroup
    title="Untested"
    ...
    rows={untested}
    ...
  />
)}
```

把 `rows={available}` `rows={failed}` `rows={untested}` 分别改成 `rows={availableSorted}` `rows={failedSorted}` `rows={untestedSorted}`。`rows={testing}` 不动（testing 段不参与排序，按到达顺序）。

> 三个 `xxx.length > 0` 条件用 `xxxSorted.length` 也可以——长度相同。改不改都行；这里建议改成 `availableSorted` 等，避免读者疑惑。下面给完整片段：

```tsx
{testing.length > 0 && (
  <ModelGroup
    title="Testing"
    tone="info"
    rows={testing}
    checked={checked}
    toggle={toggle}
    resultByModel={resultByModel}
    orch={orch}
    ep={d}
    pulse
  />
)}
{availableSorted.length > 0 && (
  <ModelGroup
    title="Available"
    tone="ok"
    rows={availableSorted}
    checked={checked}
    toggle={toggle}
    resultByModel={resultByModel}
    orch={orch}
    ep={d}
  />
)}
{failedSorted.length > 0 && (
  <ModelGroup
    title="Failed"
    tone="bad"
    rows={failedSorted}
    checked={checked}
    toggle={toggle}
    resultByModel={resultByModel}
    orch={orch}
    ep={d}
  />
)}
{untestedSorted.length > 0 && (
  <ModelGroup
    title="Untested"
    tone="muted"
    rows={untestedSorted}
    checked={checked}
    toggle={toggle}
    resultByModel={resultByModel}
    orch={orch}
    ep={d}
  />
)}
```

- [ ] **步骤 5：在文件底部加 SortControls 组件**

定位到任务 3 加的 `latencyTone` 之后，文件最末尾追加：

```tsx
function SortControls({
  mode,
  setMode,
}: {
  mode: SortMode;
  setMode: (m: SortMode) => void;
}) {
  const opts: Array<[SortMode, string]> = [
    ["default", "latency"],
    ["provider", "provider"],
    ["name", "name"],
  ];
  return (
    <div
      style={{
        display: "flex",
        border: "1px solid var(--border)",
        borderRadius: 6,
        overflow: "hidden",
        height: 26,
      }}
      role="group"
      aria-label="Sort models"
    >
      {opts.map(([k, label], i) => (
        <button
          key={k}
          type="button"
          onClick={() => setMode(k)}
          style={{
            padding: "0 9px",
            border: "none",
            borderRight:
              i === opts.length - 1 ? "none" : "1px solid var(--border)",
            background:
              mode === k ? "var(--bg-hover)" : "var(--bg-elev)",
            color: mode === k ? "var(--text)" : "var(--text-muted)",
            fontSize: 11,
            fontWeight: mode === k ? 600 : 500,
            cursor: "pointer",
            height: "100%",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **步骤 6：在 Models 标题栏插入 SortControls**

定位到 Models header 区域（第 272-331 行），找到现有的 filter input 之后、`<div style={{ flex: 1 }} />` 之前。插入 `<SortControls ... />`：

当前结构：

```tsx
<div ...filter input wrapper>
  ...
</div>
<div style={{ flex: 1 }} />
<span>...selected count...</span>
```

改成：

```tsx
<div ...filter input wrapper>
  ...
</div>
<SortControls mode={sortMode} setMode={setSortMode} />
<div style={{ flex: 1 }} />
<span>...selected count...</span>
```

完整片段（替换第 285-312 行附近）：

```tsx
<div
  style={{
    position: "relative",
    marginLeft: 8,
    flex: 1,
    maxWidth: 200,
  }}
>
  <Icon
    name="search"
    size={11}
    style={{
      position: "absolute",
      left: 9,
      top: "50%",
      transform: "translateY(-50%)",
      color: "var(--text-faint)",
    }}
  />
  <input
    className="input"
    placeholder="filter…"
    value={modelSearch}
    onChange={(e) => setModelSearch(e.target.value)}
    style={{ paddingLeft: 27, height: 26, fontSize: 11 }}
  />
</div>
<SortControls mode={sortMode} setMode={setSortMode} />
<div style={{ flex: 1 }} />
```

- [ ] **步骤 7：build + lint**

```bash
cd frontend && npm run build && npm run lint
```

预期：通过。

如果 TS 报 `available is never used`（因为我们改成了 `availableSorted`），把 `const available: string[] = [];` 等三个变量留着不动——它们仍然被 push 用作中间结果。如果 lint 仍然不爽，把循环里的 push 直接 push 到 `availableSorted`/`failedSorted`/`untestedSorted` 也行，但那要 `let` 数组并放在 applySort 调用之后赋值，反而更绕。**保留中间变量名 `available` `failed` `untested`，再用 `applySort` 产出 sorted 版本——这是当前方案。**

- [ ] **步骤 8：手动 smoke**

dev 浏览器：
1. 默认（latency 高亮）：Available 段按延迟升序，Failed 段按 error_type 字母序，Untested 字母序——和改动前一致
2. 点 `provider` → 三个段的模型都按 provider key 字母序聚类（claude / deepseek / gemini / openai / qwen / unknown 等），同 provider 内字母序
3. 点 `name` → 三个段都纯字母序（A→Z），打破 provider 聚集和延迟排序
4. 切回 `latency` → 恢复默认行为
5. Testing 段不受 sortMode 影响，按到达顺序

- [ ] **步骤 9：提交**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(frontend): segmented sort control for model rows

- SortMode: default (per-section) | provider | name
- SortControls component in Models header
- applySort() unifies all three sections"
```

---

## 验证总览（所有任务完成后）

按 spec 的 smoke 清单逐条过：

1. ✅ Drawer 打开后，模型行最左有 provider 图标（qwen 紫、deepseek 蓝、openai 黑等）
2. ✅ 不识别的模型显示 cpu 矩形 fallback
3. ✅ 容器宽 → 双列；窄 → 单列；浏览器 resize 时切换平滑
4. ✅ Available 段：< 500 绿、500–2000 灰、> 2000 黄
5. ✅ 行 hover → 复制按钮淡入；点击 → ✓ 强制可见 1.1s
6. ✅ Sort 切到 `provider` → 同家挨一起；切回 `latency` → 默认；`name` → 全字母

最后跑一次 build 确认产物 OK：

```bash
cd frontend && npm run build
```

预期：`dist/` 生成，无 error / warning（chunk-size warning 可以忽略）。

---

## 工作量参考

| 任务 | 预计 | 主要工作 |
|------|------|----------|
| 1 | 45 min | npm install + provider.tsx + cpu icon + lobehub import 调试 |
| 2 | 10 min | 一行 JSX 插入 |
| 3 | 15 min | latencyTone 函数 + ModelStatus 改造 |
| 4 | 30 min | grid + gap trick + 移除 last prop + 调试列宽 |
| 5 | 25 min | data-copied + CSS :has + wrap span |
| 6 | 50 min | SortMode 状态 + applySort + SortControls + 标题栏接入 |

**合计**：约 3 小时纯前端，跟 spec 估算吻合。
