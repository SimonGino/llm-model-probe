# Model Grouping by Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth `sortMode` (`provider-group`) to `EndpointDetailPane` that nests each status section (Available / Failed / Untested) by provider, with collapsible per-provider sub-groups and per-sub-group TriCheckbox bulk-select.

**Architecture:** All changes live in one file (`frontend/src/components/EndpointDetailPane.tsx`). A new pure helper `groupByProvider()` buckets rows via the existing `detectProvider()`. A new `ProviderSubGroup` component mirrors the existing `ModelGroup` visual language one level deeper. `ModelGroup` gets an optional `subGroups` prop and delegates to `ProviderSubGroup` when set. Collapse state is a session-scoped `Set<string>` keyed `"${section}:${providerKey}"`, cleared on endpoint switch and on leaving `provider-group` mode.

**Tech Stack:** React 18, TypeScript, Vite, existing `@lobehub/icons` (already imported via `provider.tsx`).

**Spec:** `docs/specs/2026-05-13-model-grouping-design.md`

---

## File Structure

**Modify (single file):**
- `frontend/src/components/EndpointDetailPane.tsx` — add `ProviderGroup` type, `groupByProvider()` helper, `ProviderSubGroup` component, `collapsed` state + two `useEffect` cleanups, extend `SortMode` and `SortControls`, extend `ModelGroup` with `subGroups` branch, wire grouping at the 3 status section call sites.

**No new files. No backend changes. No tests** (frontend has no test runner; verification is `npm run build` + `npm run lint` + manual browser check).

---

## Pre-Flight

Before starting Task 1, confirm baseline build is green:

```bash
cd frontend
npm install        # if node_modules missing
npm run build
npm run lint
```

Expected: both commands exit 0. If lint reports pre-existing warnings, capture the count — final verification compares against this baseline (no new warnings introduced).

---

### Task 1: Add `ProviderGroup` type and `groupByProvider` helper

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Update the `ProviderKey` import**

Find line 16:

```typescript
import { ProviderIcon, detectProvider } from "@/lib/provider";
```

Replace with:

```typescript
import { ProviderIcon, detectProvider, type ProviderKey } from "@/lib/provider";
```

- [ ] **Step 2: Add the `ProviderGroup` type and helper near the other helpers**

Insert just above `function latencyTone(` (around line 849, after `ModelStatus` ends and before `latencyTone`):

```typescript
type ProviderGroup = {
  key: ProviderKey | "other";
  rows: string[];
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
      return a.key.localeCompare(b.key);
    });
}
```

- [ ] **Step 3: Verify build + lint**

Run from the project root:

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0. The helper is currently unused, which is fine — `tsc` allows unused top-level functions, and lint is configured for the project as-is. If lint complains about an unused `groupByProvider`, ignore for now (Task 6 wires it in).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): add groupByProvider helper for model sub-grouping"
```

---

### Task 2: Extend `SortMode` to include `"provider-group"` and update `SortControls`

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Extend the `SortMode` type**

Find line 18:

```typescript
type SortMode = "default" | "provider" | "name";
```

Replace with:

```typescript
type SortMode = "default" | "provider" | "provider-group" | "name";
```

- [ ] **Step 2: Rewrite `SortControls` for the 4-state cycle**

Replace the entire `SortControls` function (currently lines 855-904) with:

```typescript
function SortControls({
  mode,
  setMode,
}: {
  mode: SortMode;
  setMode: (m: SortMode) => void;
}) {
  function onProviderClick() {
    if (mode === "provider") setMode("provider-group");
    else if (mode === "provider-group") setMode("default");
    else setMode("provider");
  }

  const buttons: Array<{
    key: string;
    label: string;
    onClick: () => void;
    isActive: boolean;
  }> = [
    {
      key: "default",
      label: "latency",
      onClick: () => setMode("default"),
      isActive: mode === "default",
    },
    {
      key: "provider",
      label: mode === "provider-group" ? "provider ▾" : "provider",
      onClick: onProviderClick,
      isActive: mode === "provider" || mode === "provider-group",
    },
    {
      key: "name",
      label: "name",
      onClick: () => setMode("name"),
      isActive: mode === "name",
    },
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
      {buttons.map((b, i) => (
        <button
          key={b.key}
          type="button"
          aria-pressed={b.isActive}
          onClick={b.onClick}
          style={{
            padding: "0 9px",
            border: "none",
            borderRight:
              i === buttons.length - 1 ? "none" : "1px solid var(--border)",
            background: b.isActive ? "var(--bg-hover)" : "var(--bg-elev)",
            color: b.isActive ? "var(--text)" : "var(--text-muted)",
            fontSize: 11,
            fontWeight: b.isActive ? 600 : 500,
            cursor: "pointer",
            height: "100%",
          }}
        >
          {b.label}
        </button>
      ))}
    </div>
  );
}
```

Note: at this point, `sortMode === "provider-group"` is reachable through the UI but `applySort` doesn't branch on it and falls through to the `default` arm at the end of the function. That branch sorts by name, which is harmless as a temporary state — Task 6 will short-circuit `applySort` when grouping is active.

- [ ] **Step 3: Verify build + lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0.

- [ ] **Step 4: Sanity-check the cycle in the browser (optional but recommended)**

```bash
cd .. && uv run probe ui --no-browser
```

Open `http://localhost:8765`, pick an endpoint with models. Click the sort `provider` button:

- 1st click: `provider` button highlights, label is `provider`
- 2nd click: label becomes `provider ▾` (still highlighted)
- 3rd click: `default` becomes highlighted

Then `Ctrl-C` to stop the server.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): add provider-group sort mode + cycle"
```

---

### Task 3: Add `collapsed` state and lifecycle cleanups

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Add the `collapsed` state hook**

Find line 35 (the `sortMode` declaration):

```typescript
  const [sortMode, setSortMode] = useState<SortMode>("default");
```

Insert immediately below it:

```typescript
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
```

- [ ] **Step 2: Reset `collapsed` on endpoint switch**

Find the existing `useEffect` at lines 38-43:

```typescript
  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
    setModelSearch("");
  }, [detail.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps
```

Add a `setCollapsed` line so it becomes:

```typescript
  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
    setModelSearch("");
    setCollapsed(new Set());
  }, [detail.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 3: Clear `collapsed` when leaving `provider-group` mode**

Add a new `useEffect` immediately after the existing one (around line 44):

```typescript
  useEffect(() => {
    if (sortMode !== "provider-group") setCollapsed(new Set());
  }, [sortMode]);
```

- [ ] **Step 4: Add the `toggleCollapsed` callback**

Find `toggleAll` (lines 76-85). Immediately after `toggleAll` ends and before the `if (detail.isLoading ...)` guard (around line 86), insert:

```typescript
  function toggleCollapsed(parentKey: string, providerKey: string) {
    const k = `${parentKey}:${providerKey}`;
    setCollapsed((prev) => {
      const n = new Set(prev);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  }
```

- [ ] **Step 5: Verify build + lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0. `collapsed` and `toggleCollapsed` are unused so far — that's OK, they're wired in Task 5/6.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): collapsed state + lifecycle resets for provider sub-groups"
```

---

### Task 4: Add the `ProviderSubGroup` component

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Add the `ProviderSubGroup` component**

Insert immediately after the `ModelGroup` function (after the closing `}` around line 693, before the `function ModelRow(` declaration):

```typescript
function ProviderSubGroup({
  providerKey,
  rows,
  collapsed,
  onToggleCollapsed,
  checked,
  toggle,
  toggleAll,
  resultByModel,
  orch,
  ep,
  stale,
}: {
  providerKey: ProviderKey | "other";
  rows: string[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  checked: Set<string>;
  toggle: (m: string) => void;
  toggleAll: (rows: string[]) => void;
  resultByModel: Map<string, ModelResultPublic>;
  orch: ReturnType<typeof useProbeOrchestrator>;
  ep: EndpointDetail;
  stale: boolean;
}) {
  const iconModel = rows[0] ?? "";
  return (
    <div
      style={{
        marginBottom: 8,
        paddingLeft: 8,
        borderLeft: "1px solid var(--border)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 5,
        }}
      >
        <TriCheckbox
          state={triState(rows, checked)}
          onClick={() => toggleAll(rows)}
          title={`全选/全不选 ${providerKey}`}
        />
        <button
          type="button"
          onClick={onToggleCollapsed}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            flex: 1,
            background: "transparent",
            border: "none",
            padding: 0,
            cursor: "pointer",
            color: "var(--text)",
            textAlign: "left",
          }}
          aria-expanded={!collapsed}
        >
          <ProviderIcon modelId={iconModel} size={12} />
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: 0.3,
            }}
          >
            {providerKey}
          </span>
          <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
            {rows.length}
          </span>
          <Icon
            name={collapsed ? "chevron-right" : "chevron-down"}
            size={11}
          />
        </button>
      </div>
      {!collapsed && (
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
                stale={stale}
                pulse={false}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
```

Note: `void parentKey` silences the unused-prop lint while keeping the prop in the signature for future use (e.g., DOM hooks, analytics).

- [ ] **Step 2: Verify build + lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0. The component is defined but unused — that's allowed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): ProviderSubGroup component (not wired yet)"
```

---

### Task 5: Extend `ModelGroup` to delegate to `ProviderSubGroup` when `subGroups` is set

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Extend the `ModelGroup` props and body**

Replace the entire `ModelGroup` function (currently lines 598-693) with:

```typescript
function ModelGroup({
  title,
  tone,
  rows,
  subGroups,
  parentKey,
  collapsed,
  toggleCollapsed,
  isSearching,
  checked,
  toggle,
  toggleAll,
  resultByModel,
  orch,
  ep,
  stale,
  pulse,
}: {
  title: string;
  tone: "ok" | "bad" | "info" | "muted";
  rows: string[];
  subGroups?: ProviderGroup[];
  parentKey?: string;
  collapsed?: Set<string>;
  toggleCollapsed?: (parentKey: string, providerKey: string) => void;
  isSearching?: boolean;
  checked: Set<string>;
  toggle: (m: string) => void;
  toggleAll: (rows: string[]) => void;
  resultByModel: Map<string, ModelResultPublic>;
  orch: ReturnType<typeof useProbeOrchestrator>;
  ep: EndpointDetail;
  stale: boolean;
  pulse?: boolean;
}) {
  const color = {
    ok: "var(--ok)",
    bad: "var(--bad)",
    info: "var(--info)",
    muted: "var(--text-muted)",
  }[tone];
  const allRows = subGroups ? subGroups.flatMap((g) => g.rows) : rows;
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 5,
          paddingLeft: 2,
        }}
      >
        <TriCheckbox
          state={triState(allRows, checked)}
          onClick={() => toggleAll(allRows)}
          title={`全选/全不选 ${title}`}
        />
        <span className="dot" style={{ background: color }} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color,
            textTransform: "uppercase",
            letterSpacing: 0.7,
          }}
        >
          {title}
        </span>
        <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
          {allRows.length}
        </span>
      </div>
      {subGroups && parentKey ? (
        subGroups.map((g) => {
          const k = `${parentKey}:${g.key}`;
          const isCollapsed = isSearching
            ? false
            : (collapsed?.has(k) ?? false);
          return (
            <ProviderSubGroup
              key={g.key}
              providerKey={g.key}
              rows={g.rows}
              collapsed={isCollapsed}
              onToggleCollapsed={() =>
                toggleCollapsed?.(parentKey, g.key)
              }
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={ep}
              stale={stale}
            />
          );
        })
      ) : (
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
                stale={stale}
                pulse={!!pulse}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
```

Key changes from the old version:

1. New optional props: `subGroups`, `parentKey`, `collapsed`, `toggleCollapsed`, `isSearching`.
2. `allRows` is `subGroups.flatMap((g) => g.rows)` when grouping, else `rows`. The status-level TriCheckbox and count both use `allRows`.
3. When `subGroups && parentKey` is truthy, render `ProviderSubGroup` children instead of the flat grid. Otherwise, the existing flat grid is unchanged.

- [ ] **Step 2: Verify build + lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0. All current `ModelGroup` call sites still work because the new props are optional.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): ModelGroup supports nested ProviderSubGroup children"
```

---

### Task 6: Wire grouping into the three status section call sites

**Files:**
- Modify: `frontend/src/components/EndpointDetailPane.tsx`

- [ ] **Step 1: Compute grouping flags in render**

Find the section just before `const checkedVisible = ...` (around line 156-158):

```typescript
  const availableSorted = applySort(available, "available");
  const failedSorted = applySort(failed, "failed");
  const untestedSorted = applySort(untested, "untested");

  const checkedVisible = visible.filter((m) => checked.has(m));
```

Replace with:

```typescript
  const isGrouping = sortMode === "provider-group";
  const isSearching = q !== "";

  const availableSorted = isGrouping ? [] : applySort(available, "available");
  const failedSorted = isGrouping ? [] : applySort(failed, "failed");
  const untestedSorted = isGrouping ? [] : applySort(untested, "untested");

  const availableGroups = isGrouping ? groupByProvider(available) : undefined;
  const failedGroups = isGrouping ? groupByProvider(failed) : undefined;
  const untestedGroups = isGrouping ? groupByProvider(untested) : undefined;

  const checkedVisible = visible.filter((m) => checked.has(m));
```

(Note: `applySort` is skipped under grouping because `groupByProvider` does its own per-bucket sort. `q` is already defined at line 102.)

- [ ] **Step 2: Update the rendering condition for each status section**

The current rendering blocks (lines 449-490) look like:

```typescript
          {availableSorted.length > 0 && (
            <ModelGroup
              title="Available"
              tone="ok"
              rows={availableSorted}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
          {failedSorted.length > 0 && (
            <ModelGroup
              title="Failed"
              ...same props...
            />
          )}
          {untestedSorted.length > 0 && (
            <ModelGroup
              title="Untested"
              tone="muted"
              ...same props...
            />
          )}
```

Replace those three blocks with:

```typescript
          {(availableSorted.length > 0 ||
            (availableGroups && availableGroups.length > 0)) && (
            <ModelGroup
              title="Available"
              tone="ok"
              rows={availableSorted}
              subGroups={availableGroups}
              parentKey="available"
              collapsed={collapsed}
              toggleCollapsed={toggleCollapsed}
              isSearching={isSearching}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
          {(failedSorted.length > 0 ||
            (failedGroups && failedGroups.length > 0)) && (
            <ModelGroup
              title="Failed"
              tone="bad"
              rows={failedSorted}
              subGroups={failedGroups}
              parentKey="failed"
              collapsed={collapsed}
              toggleCollapsed={toggleCollapsed}
              isSearching={isSearching}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
          {(untestedSorted.length > 0 ||
            (untestedGroups && untestedGroups.length > 0)) && (
            <ModelGroup
              title="Untested"
              tone="muted"
              rows={untestedSorted}
              subGroups={untestedGroups}
              parentKey="untested"
              collapsed={collapsed}
              toggleCollapsed={toggleCollapsed}
              isSearching={isSearching}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
```

Note: the `Testing` section (lines 434-448) is **not** modified — it stays flat per the spec ("不做 Testing 段的分组").

- [ ] **Step 3: Verify build + lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both exit 0, no new warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EndpointDetailPane.tsx
git commit -m "feat(ui): wire provider grouping into status sections"
```

---

### Task 7: Manual browser verification

**Files:** none modified

This is the verification gate. Frontend has no automated UI tests, so all four spec scenarios must be hit by hand.

- [ ] **Step 1: Build the frontend and start the UI**

```bash
cd frontend && npm run build && cd ..
uv run probe ui --no-browser
```

In a different terminal (or browser), open `http://localhost:8765` and pick an endpoint that has at least 20 models spread across 2+ providers. If you only have small endpoints, use the test endpoint with 239 qwen+kimi+deepseek+glm+MiniMax models shown in the screenshot triggering this work.

- [ ] **Step 2: Scenario 1 — provider grouping appears, ordering correct**

1. Click sort button `[provider]` → still flat, sorted by provider key (existing behavior)
2. Click `[provider]` again → button label becomes `provider ▾`, model list switches to nested sub-groups
3. Verify in `Untested` section: largest provider sub-group appears first, smallest last, and `other` (if present) is at the bottom
4. Verify within each sub-group: model names sorted alphabetically (e.g. `qwen-1.8b-chat`, `qwen-14b-chat`, `qwen-72b-chat`, ...)

Pass criteria: all 4 above hold.

- [ ] **Step 3: Scenario 2 — collapse behaves correctly across mode switches**

1. In `provider-group` mode, click a sub-group header (the area with provider icon + name + caret) → the sub-group's row grid disappears, caret rotates to `▸`
2. Click again → expands back, caret rotates to `▾`
3. Click sort button `[name]` → all collapse state should be gone (sub-groups disappear; switch to flat view)
4. Click sort button `[provider]` twice to return to `provider-group` mode → all sub-groups default to expanded

Pass criteria: all 4 above hold.

- [ ] **Step 4: Scenario 3 — search auto-expands without losing manual state**

1. In `provider-group` mode, collapse the `qwen` sub-group manually
2. Type `qwen-coder` into the filter box → `qwen` sub-group auto-expands and shows matching rows, other sub-groups disappear (no matches)
3. Clear the filter box → manual state restored: `qwen` sub-group is collapsed again, all other sub-groups visible

Pass criteria: all 3 above hold.

- [ ] **Step 5: Scenario 4 — bulk-select via sub-group TriCheckbox**

1. In `provider-group` mode, start with everything checked (default)
2. Click a sub-group's TriCheckbox → all rows in that sub-group uncheck, status-section TriCheckbox shows indeterminate (partial), top-toolbar "X selected" counter decreases by exactly the sub-group's size
3. Click that sub-group's TriCheckbox again → all rows re-check, status-section TriCheckbox shows full check
4. Click "Test selected" → only the currently selected rows are probed (verify by watching pulse dots)

Pass criteria: all 4 above hold.

- [ ] **Step 6: Switch endpoint and verify collapse state resets**

1. In endpoint A: switch to `provider-group` mode, collapse 2-3 sub-groups manually
2. Click endpoint B in the left list
3. Click back to endpoint A
4. Verify: if `EndpointDetailPane` is still in `provider-group` mode (the `sortMode` local state may persist or reset depending on React reconciliation — either is acceptable), the previously-collapsed sub-groups must all be **expanded** now, because the `useEffect` on `[detail.data?.id]` cleared the `collapsed` set.

Pass criteria: no stale collapse state leaks between endpoints.

- [ ] **Step 7: Kill the server**

```bash
# back in the terminal running `probe ui`
Ctrl-C
```

- [ ] **Step 8: Commit (changelog entry only if you want to log the verification)**

No code change here. If you want a marker commit:

```bash
git commit --allow-empty -m "chore: verify provider grouping flow manually"
```

Otherwise skip.

---

## Final Self-Review Checklist

After Task 7 passes, run one more sweep before considering this done:

- [ ] All 6 modify-commits exist in `git log` (Tasks 1-6)
- [ ] `cd frontend && npm run build && npm run lint` exit 0
- [ ] `uv run pytest -q` still green (regression check on backend — should be untouched but verify zero impact)
- [ ] Existing `provider` sort mode (without `▾`) still works flat
- [ ] Switching to a fresh endpoint immediately shows correct content (no flicker, no stale collapse)
