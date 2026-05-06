import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  CopyBtn,
  HealthBadge,
  Icon,
  endpointHealth,
} from "@/components/atoms";
import TagEditor from "./TagEditor";
import ApiKeyReveal from "./ApiKeyReveal";
import AddEndpointDialog from "./AddEndpointDialog";
import { relative } from "@/lib/format";
import type { EndpointDetail, ModelResultPublic } from "@/lib/types";
import { ProviderIcon, detectProvider } from "@/lib/provider";

type SortMode = "default" | "provider" | "name";

export default function EndpointDetailPane({
  idOrName,
  onDeleted,
}: {
  idOrName: string;
  onDeleted: (id: string) => void;
}) {
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName),
  });
  const orch = useProbeOrchestrator();
  const qc = useQueryClient();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [modelSearch, setModelSearch] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("default");
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
    setModelSearch("");
  }, [detail.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const resultByModel = useMemo(() => {
    const m = new Map<string, ModelResultPublic>();
    if (detail.data) for (const r of detail.data.results) m.set(r.model_id, r);
    return m;
  }, [detail.data]);

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteEndpoint(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      onDeleted(id);
    },
  });

  const rediscover = useMutation({
    mutationFn: (id: string) => api.rediscoverEndpoint(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["endpoint", id] });
      qc.invalidateQueries({ queryKey: ["endpoints"] });
    },
  });

  function toggle(model: string) {
    setChecked((prev) => {
      const n = new Set(prev);
      if (n.has(model)) n.delete(model);
      else n.add(model);
      return n;
    });
  }

  function toggleAll(rows: string[]) {
    if (rows.length === 0) return;
    setChecked((prev) => {
      const allChecked = rows.every((m) => prev.has(m));
      const n = new Set(prev);
      if (allChecked) for (const m of rows) n.delete(m);
      else for (const m of rows) n.add(m);
      return n;
    });
  }

  if (detail.isLoading || !detail.data) {
    return (
      <div style={{ padding: 32, color: "var(--text-muted)" }}>Loading…</div>
    );
  }
  const d = detail.data;
  const health = endpointHealth(d);
  const pending = orch.pendingForEndpoint(d.id);
  const lats = d.results
    .filter((r) => r.status === "available" && r.latency_ms != null)
    .map((r) => r.latency_ms as number);
  const avgLat = lats.length
    ? Math.round(lats.reduce((s, n) => s + n, 0) / lats.length)
    : null;

  const q = modelSearch.trim().toLowerCase();
  const visible = q
    ? d.models.filter((m) => m.toLowerCase().includes(q))
    : d.models;

  const testing: string[] = [];
  const available: string[] = [];
  const failed: string[] = [];
  const untested: string[] = [];
  for (const m of visible) {
    if (orch.isPending(d.id, m)) {
      testing.push(m);
      continue;
    }
    const r = resultByModel.get(m);
    const te = orch.errorFor(d.id, m);
    if (r?.status === "available") available.push(m);
    else if (r || te) failed.push(m);
    else untested.push(m);
  }
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
    // default: 各段保持原有排序
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

  const checkedVisible = visible.filter((m) => checked.has(m));

  function confirmDelete() {
    if (
      window.confirm(`确认删除端点 ${d.name}？此操作不可撤销，会删除所有模型记录。`)
    ) {
      remove.mutate(d.id);
    }
  }

  return (
    <div
      key={d.id}
      style={{ padding: "22px 32px 32px", width: "100%" }}
      className="anim-fade-in"
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 5,
          flexWrap: "wrap",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: -0.3,
          }}
        >
          {d.name}
        </h2>
        <span
          className="mono"
          style={{ fontSize: 11, color: "var(--text-faint)" }}
        >
          {d.id}
        </span>
        <HealthBadge health={health} />
        <div style={{ flex: 1 }} />
        <button
          className="btn btn-sm"
          onClick={() => {
            if (d.mode === "discover") rediscover.mutate(d.id);
            else orch.run(d.id, d.models);
          }}
          disabled={
            rediscover.isPending ||
            pending > 0 ||
            (d.mode === "specified" && d.models.length === 0)
          }
          title={
            d.mode === "discover"
              ? "Re-fetch model list from /v1/models (use Test all to probe)"
              : "Retest all specified models"
          }
        >
          <Icon name="refresh" size={11} />
          {rediscover.isPending
            ? "Refreshing…"
            : pending > 0
              ? `Testing… (${pending})`
              : "Retest"}
        </button>
        <button
          className="btn btn-sm btn-ghost btn-icon"
          title="Edit endpoint"
          aria-label="Edit endpoint"
          onClick={() => setEditOpen(true)}
        >
          <Icon name="edit" size={11} />
        </button>
        <button
          className="btn btn-sm btn-ghost btn-icon"
          title="Delete endpoint"
          onClick={confirmDelete}
          disabled={remove.isPending}
        >
          <Icon name="trash" size={11} />
        </button>
      </div>
      <div
        className="mono"
        style={{
          fontSize: 12,
          color: "var(--text-muted)",
          marginBottom: 18,
          display: "flex",
          alignItems: "center",
          gap: 5,
          wordBreak: "break-all",
        }}
      >
        {d.base_url}
        <CopyBtn text={d.base_url} />
      </div>

      {d.stale_since && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "9px 12px",
            marginBottom: 14,
            background: "var(--bg-elev)",
            border: "1px solid var(--warn)",
            borderRadius: 7,
            fontSize: 12,
            color: "var(--text)",
          }}
        >
          <span
            className="dot"
            style={{ background: "var(--warn)", flexShrink: 0 }}
          />
          <span style={{ flex: 1 }}>
            端点配置已修改（{relative(d.stale_since)}），数据可能过期。建议重测。
          </span>
        </div>
      )}

      {/* stat strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 1,
          background: "var(--border)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          overflow: "hidden",
          marginBottom: 22,
        }}
      >
        <StatCell
          label="available"
          value={d.list_error ? "—" : `${d.available}/${d.total_models}`}
          color={d.list_error ? "var(--bad)" : "var(--ok)"}
        />
        <StatCell
          label="failed"
          value={d.list_error ? "—" : d.failed}
          color={d.failed > 0 ? "var(--bad)" : "var(--text)"}
        />
        <StatCell
          label="avg latency"
          value={avgLat != null ? `${avgLat}ms` : "—"}
          color="var(--text)"
        />
        <StatCell
          label="last test"
          value={relative(d.last_tested_at)}
          color="var(--text)"
        />
      </div>

      {d.list_error && (
        <div
          className="badge badge-bad"
          style={{
            display: "flex",
            height: "auto",
            padding: "8px 11px",
            marginBottom: 18,
            fontSize: 11,
          }}
        >
          <Icon name="x" size={11} />
          {d.list_error}
        </div>
      )}

      {/* meta grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "100px 1fr",
          gap: "7px 16px",
          marginBottom: 22,
          fontSize: 12,
        }}
      >
        <Meta label="SDK">
          <span className="badge">{d.sdk}</span>
        </Meta>
        <Meta label="Mode">
          <span className="badge">{d.mode}</span>
        </Meta>
        <Meta label="API key">
          <ApiKeyReveal endpointId={d.id} masked={d.api_key_masked} />
        </Meta>
        <Meta label="Tags">
          <TagEditor endpointId={d.id} tags={d.tags} />
        </Meta>
        {d.note && (
          <Meta label="Note">
            <span style={{ color: "var(--text-muted)" }}>{d.note}</span>
          </Meta>
        )}
      </div>

      {/* models */}
      {d.models.length > 0 && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
              flexWrap: "wrap",
            }}
          >
            <TriCheckbox
              state={triState(visible, checked)}
              onClick={() => toggleAll(visible)}
              title="全选/全不选当前可见模型"
            />
            <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Models</h3>
            <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
              {d.models.length}
            </span>
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
            <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
              {checkedVisible.length} selected
            </span>
            <button
              className="btn btn-sm"
              onClick={() => orch.run(d.id, checkedVisible)}
              disabled={checkedVisible.length === 0 || pending > 0}
            >
              <Icon name="play" size={10} />
              Test selected
            </button>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => orch.run(d.id, visible)}
              disabled={visible.length === 0 || pending > 0}
            >
              {pending > 0 ? `Testing… (${pending})` : "Test all"}
            </button>
          </div>

          {testing.length > 0 && (
            <ModelGroup
              title="Testing"
              tone="info"
              rows={testing}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
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
              tone="bad"
              rows={failedSorted}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
          {untestedSorted.length > 0 && (
            <ModelGroup
              title="Untested"
              tone="muted"
              rows={untestedSorted}
              checked={checked}
              toggle={toggle}
              toggleAll={toggleAll}
              resultByModel={resultByModel}
              orch={orch}
              ep={d}
              stale={!!d.stale_since}
            />
          )}
          {visible.length === 0 && (
            <div
              style={{
                padding: 24,
                textAlign: "center",
                color: "var(--text-faint)",
                fontSize: 12,
              }}
            >
              没有匹配 “{modelSearch}” 的模型
            </div>
          )}
        </>
      )}

      {d.models.length === 0 && (
        <div
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--text-muted)",
            border: "1px dashed var(--border)",
            borderRadius: 8,
          }}
        >
          {d.list_error
            ? "未发现任何模型 — 请检查 base URL 与 API key。"
            : "No models. Specified mode with empty list."}
        </div>
      )}

      <AddEndpointDialog
        mode="edit"
        open={editOpen}
        onClose={() => setEditOpen(false)}
        initial={d}
        onSuccess={() => {
          // Query invalidation is handled inside the dialog's patch.onSuccess.
        }}
      />
    </div>
  );
}

function StatCell({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div style={{ background: "var(--bg-elev)", padding: "11px 14px" }}>
      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: 0.5,
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          color,
          marginTop: 2,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Meta({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <div
        style={{
          color: "var(--text-faint)",
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          paddingTop: 3,
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div style={{ minWidth: 0 }}>{children}</div>
    </>
  );
}

function ModelGroup({
  title,
  tone,
  rows,
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
          state={triState(rows, checked)}
          onClick={() => toggleAll(rows)}
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
          {rows.length}
        </span>
      </div>
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
    </div>
  );
}

function ModelRow({
  model,
  result,
  transientError,
  filterSkip,
  checked,
  toggle,
  stale,
  pulse,
}: {
  model: string;
  result: ModelResultPublic | null;
  transientError: string | null;
  filterSkip: boolean;
  checked: boolean;
  toggle: () => void;
  stale: boolean;
  pulse: boolean;
}) {
  return (
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
      <span className="row-copy">
        <CopyBtn text={model} title="Copy model id" />
      </span>
      <span style={{ opacity: stale && !pulse ? 0.5 : 1 }}>
        <ModelStatus
          result={result}
          transientError={transientError}
          filterSkip={filterSkip}
          pulse={pulse}
        />
      </span>
    </label>
  );
}

function ModelStatus({
  result,
  transientError,
  filterSkip,
  pulse,
}: {
  result: ModelResultPublic | null;
  transientError: string | null;
  filterSkip: boolean;
  pulse: boolean;
}) {
  if (pulse) {
    return (
      <span
        style={{
          fontSize: 11,
          color: "var(--info)",
          display: "flex",
          alignItems: "center",
          gap: 5,
        }}
      >
        <span className="dot dot-pulse" /> testing
      </span>
    );
  }
  if (result) {
    if (result.status === "available") {
      const ms = result.latency_ms;
      const { color } = latencyTone(ms ?? Number.MAX_SAFE_INTEGER);
      const label = ms == null ? "—" : `${ms}ms`;
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
    return (
      <span
        title={result.error_message ?? undefined}
        className="mono"
        style={{
          fontSize: 11,
          color: "var(--bad)",
          maxWidth: 200,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        ✗ {result.error_type}
      </span>
    );
  }
  if (transientError) {
    return (
      <span
        title={transientError}
        className="mono"
        style={{
          fontSize: 11,
          color: "var(--bad)",
          maxWidth: 200,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        ✗ request
      </span>
    );
  }
  if (filterSkip) return <span className="badge">filter-skip</span>;
  return (
    <span style={{ fontSize: 11, color: "var(--text-faint)" }}>untested</span>
  );
}

function latencyTone(ms: number): { color: string; label: string } {
  if (ms < 500) return { color: "var(--ok)", label: `${ms}ms` };
  if (ms < 2000) return { color: "var(--text-muted)", label: `${ms}ms` };
  return { color: "var(--warn)", label: `${ms}ms` };
}

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
          aria-pressed={mode === k}
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

type TriState = "all" | "partial" | "none";

function triState(rows: string[], checked: Set<string>): TriState {
  if (rows.length === 0) return "none";
  let hit = 0;
  for (const m of rows) if (checked.has(m)) hit++;
  if (hit === 0) return "none";
  if (hit === rows.length) return "all";
  return "partial";
}

function TriCheckbox({
  state,
  onClick,
  title,
}: {
  state: TriState;
  onClick: () => void;
  title?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "partial";
  }, [state]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={state === "all"}
      onChange={onClick}
      title={title}
      style={{ accentColor: "var(--text)", cursor: "pointer" }}
    />
  );
}
