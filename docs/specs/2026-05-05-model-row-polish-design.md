# 模型行视觉密度优化 — 提供商图标 + 双列 + 色阶 + Hover 复制 + 聚类排序

**日期**: 2026-05-05
**状态**: 已口头确认
**基于**: 现有 `frontend/src/components/EndpointDetailPane.tsx` 的 `Section` + `ModelRow` 结构

## 目标

把当前模型列表（每行一行、横向信息密度低、提供商靠前缀脑内识别）改造成扫起来快、信息密度合理的样子。

具体痛点：
- 一行只放一个模型，239 个模型滚不到底
- 模型名 `qwen3-coder-flash` 占行宽 1/4，右边大段空白浪费
- 全靠 `qwen-` `deepseek-` `gpt-` 等前缀脑内匹配提供商，识别成本累

## 不做的事

- 卡片式（带阴影、大间距）模型展示 —— 还是 list 风格，但更紧凑
- 拖拽排序 / 自定义列
- 模型详情子抽屉（点行展开）—— `result.error_message` 已经在 `title` tooltip 里
- 提供商列表全量覆盖 —— 用 lobehub 库内置的，识别不出来的 fallback `<Cpu>`

## 改动总览（5 项叠加）

### 1. Provider 图标 (`@lobehub/icons`)

新依赖：

```bash
cd frontend
npm install @lobehub/icons
```

新文件 `frontend/src/lib/provider.ts` —— 模型 ID → provider key 映射 + 图标导出：

```ts
import {
  Qwen, DeepSeek, OpenAI, Claude, Gemini, Mistral, Meta,
  Yi, Moonshot, Zhipu, Cohere, Doubao, Hunyuan, Spark, Baichuan,
} from "@lobehub/icons";

export type ProviderKey =
  | "qwen" | "deepseek" | "openai" | "claude" | "gemini"
  | "mistral" | "llama" | "yi" | "moonshot" | "zhipu"
  | "cohere" | "doubao" | "hunyuan" | "spark" | "baichuan"
  | "unknown";

interface Rule {
  key: ProviderKey;
  match: RegExp;
}

// 顺序敏感: 更具体的 pattern 在前. 第一个命中即返回.
const RULES: Rule[] = [
  { key: "qwen",     match: /^(qwen|qwq|qvq|tongyi)/i },
  { key: "deepseek", match: /^deepseek/i },
  { key: "claude",   match: /^claude/i },
  { key: "gemini",   match: /^gemini/i },
  { key: "openai",   match: /^(gpt|o[1-9](-|$)|text-|davinci|chatgpt)/i },
  { key: "mistral",  match: /^(mistral|mixtral|codestral|ministral)/i },
  { key: "llama",    match: /^(llama|meta-llama)/i },
  { key: "yi",       match: /^yi-/i },
  { key: "moonshot", match: /^(moonshot|kimi)/i },
  { key: "zhipu",    match: /^(glm|chatglm)/i },
  { key: "cohere",   match: /^(command|cohere)/i },
  { key: "doubao",   match: /^doubao/i },
  { key: "hunyuan",  match: /^hunyuan/i },
  { key: "spark",    match: /^spark/i },
  { key: "baichuan", match: /^baichuan/i },
];

export function detectProvider(modelId: string): ProviderKey {
  for (const r of RULES) {
    if (r.match.test(modelId)) return r.key;
  }
  return "unknown";
}

const ICON_MAP: Record<Exclude<ProviderKey, "unknown">, React.ComponentType<{ size?: number }>> = {
  qwen: Qwen, deepseek: DeepSeek, openai: OpenAI, claude: Claude,
  gemini: Gemini, mistral: Mistral, llama: Meta, yi: Yi,
  moonshot: Moonshot, zhipu: Zhipu, cohere: Cohere, doubao: Doubao,
  hunyuan: Hunyuan, spark: Spark, baichuan: Baichuan,
};

export function ProviderIcon({
  modelId, size = 14,
}: { modelId: string; size?: number }) {
  const key = detectProvider(modelId);
  if (key === "unknown") {
    // 通用 fallback: 用 atoms 里的 Icon 一个 Cpu 形状
    return <Icon name="cpu" size={size} style={{ color: "var(--text-faint)" }} />;
  }
  const Comp = ICON_MAP[key];
  return <Comp size={size} />;
}
```

`atoms.tsx` 里的 `Icon` 如果**还没有 `cpu`** 这个名字，加一个（一个 `<rect>` + `<line>` 简单画也行）。

集成到 `ModelRow`：在 checkbox 和 model 名之间插入：

```tsx
<ProviderIcon modelId={model} size={14} />
```

### 2. 双列响应式网格

`Section` 组件里渲染 ModelRow 的 `<div>` 改成响应式网格：

```tsx
<div
  style={{
    display: "grid",
    // 默认 2 列, 容器宽 < 480px 单列. 用 minmax 实现.
    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
    gap: 0,
    border: "1px solid var(--border)",
    borderRadius: 7,
    overflow: "hidden",
    background: "var(--bg-elev)",
  }}
>
  {rows.map((m) => <ModelRow ... />)}
</div>
```

`ModelRow` 不需要再传 `last`（边框靠 grid 单元格内部 border 实现）。每个 row 改成：

```tsx
<label
  style={{
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 10px",
    cursor: "pointer",
    borderRight: "1px solid var(--border)",
    borderBottom: "1px solid var(--border)",
    minWidth: 0,
    /* :nth-child 控制最右列去掉 right border / 最末行去掉 bottom border —
       grid 自动布局复杂, 改用伪类不靠谱. 简化做法: 都画 border, 容器
       overflow:hidden 把外侧边框吃掉. */
  }}
>
  ...
</label>
```

> **细节**：避免双列的 right/bottom border 不对齐问题，可以改成"行间用 outline 而不是 border"，或者直接 `gap: 1px` + `background: var(--border)` 让网格隔阂用背景透出。

### 3. Latency 色阶

把 `ModelStatus` 里 `result.status === "available"` 的渲染从纯绿色改成按延迟分档：

```tsx
function latencyTone(ms: number): { color: string; label: string } {
  if (ms < 500)  return { color: "var(--ok)",   label: `${ms}ms` };
  if (ms < 2000) return { color: "var(--text-muted)", label: `${ms}ms` };
  return         { color: "var(--warn)", label: `${ms}ms` };
}
```

应用：

```tsx
const { color, label } = latencyTone(result.latency_ms);
return (
  <span className="mono" style={{ fontSize: 11, color, ... }}>
    <Icon name="check" size={10} />
    {label}
  </span>
);
```

> 注意：不分档"很慢"和"超时"，统一进 `> 2000` 的 warn。失败的（`status === "failed"`）继续 `var(--bad)`，不动。

### 4. Hover-only 复制按钮

`CopyBtn` 默认透明 / 灰，行 hover 时浮出。当前 `ModelRow` 已经在 `onMouseEnter` 改 background，把 CSS class 化更省事：

a) `index.css` 加：

```css
.model-row { }
.model-row .row-copy {
  opacity: 0;
  transition: opacity .12s;
}
.model-row:hover .row-copy {
  opacity: 1;
}
```

b) `ModelRow` 的 `<label>` 加 `className="model-row"`，`CopyBtn` 包一层 `<span className="row-copy">`：

```tsx
<span className="row-copy">
  <CopyBtn text={model} title="Copy model id" />
</span>
```

复制后的 ✓ 反馈不该被 hover 隐藏（`copied` state 时强制 visible）：

```tsx
<span
  className="row-copy"
  style={copied ? { opacity: 1 } : undefined}
>
```

需要 `CopyBtn` 把 `copied` 透传出来 —— 或者更简单：移除 `row-copy` opacity 0 在 `copied` 期间。改 `CopyBtn` 让它接受 `forceVisible` prop。

### 5. 段内"按 provider 聚类"排序选项

当前段内排序：
- Available: `latency_ms` 升序
- Failed: `error_type` 字母序
- Untested: 字母序

加一个段级别开关：**按 provider 分组**（同 provider 模型挨在一起）。UI 实现：

a) Models 标题栏右边加一个排序切换：

```
Models 239   [filter...]                    Sort: [latency ▾] [Test all]
                                                    └─ latency
                                                    └─ provider
                                                    └─ name
```

实现成简单的 `<details>`/dropdown 或者直接 segmented buttons。

b) 排序 state 升级到 `EndpointDetailPane` 顶层（影响所有 3 个段）：

```tsx
type SortMode = "default" | "provider" | "name";
const [sortMode, setSortMode] = useState<SortMode>("default");
```

c) 排序逻辑：

```ts
function sortRows(rows: string[], section: "available" | "failed" | "untested"): string[] {
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
  // default: 各段用各自的排序
  if (section === "available") {
    return [...rows].sort(...latencyAscThenName);
  }
  if (section === "failed") {
    return [...rows].sort(...errorTypeThenName);
  }
  return [...rows].sort((a, b) => a.localeCompare(b));
}
```

`default` 是当前行为，保留；`provider` 把同家挨一起；`name` 简单字母序。

## 文件结构

```
frontend/
├── package.json                        # 加 @lobehub/icons
├── src/
│   ├── lib/
│   │   └── provider.ts                 # 新建: detectProvider + ProviderIcon
│   ├── components/
│   │   └── EndpointDetailPane.tsx      # 修改: ModelRow 加图标 + 双列网格 + 排序切换
│   ├── components/atoms.tsx            # 可能修改: 加 cpu icon (如果还没有)
│   └── index.css                       # 修改: model-row hover 复制按钮规则
```

## 后端 / 测试

**零改动**。纯前端 polish。

后端测试不动；前端没自动化测试，靠手动 smoke：

1. 进 drawer，模型行最左有 provider 图标（qwen 紫色、deepseek 蓝、openai 黑等）
2. 没识别的（比如 `Pro/Qwen2-72B-Instruct` 这种被代理改了名的）显示 cpu fallback
3. 容器够宽时双列；窄了单列；resize 浏览器观察过渡
4. Available 段延迟 < 500 绿、500–2000 灰、> 2000 黄
5. 行 hover 复制按钮浮出；点击后 ✓ 反馈强制可见 1.2s
6. Sort 切到 `provider` → 同家模型挨一起；切回 `latency` → 默认行为；`name` → 全字母序

## 兼容性 / 风险

- `@lobehub/icons` 包大小：截至撰写时 ~50KB gzip（主要是 SVG 路径），可接受。如果担心可以按需 import（已经写成 named import）。
- 双列网格在容器宽度尴尬时（460-560px）可能切换抖动。`auto-fill` + `minmax(260px, 1fr)` 的取值可能要试；如果体验不好回退到 1 列。
- Hover-only 复制按钮在触屏设备（你不主要用，但 docker 部署后可能他人手机访问）会让复制不可发现。**接受**：触屏少数场景，长按行还能选模型名复制。
- Latency 色阶阈值（500 / 2000）写死。后续如果觉得不准，挪到 `config.toml`。先固定。

## 工作量

- provider.ts + ProviderIcon + 测试映射 ~1h
- 双列网格 + ModelRow border 调整 ~30min
- Latency 色阶 + ModelStatus 调整 ~15min
- Hover-only 复制按钮（CSS + 强制 visible 联动）~30min
- 排序切换 dropdown + 状态提升 ~30min
- 安装包 + smoke ~15min

总计 ~3 小时纯前端。
