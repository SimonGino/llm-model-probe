import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  CopyBtn,
  HealthBadge,
  HealthRing,
  Icon,
  FreshnessPill,
  endpointHealth,
} from "@/components/atoms";
import TagEditor from "./TagEditor";
import ApiKeyReveal from "./ApiKeyReveal";
import type { EndpointDetail, ModelResultPublic } from "@/lib/types";

export default function EndpointDetailDrawer({
  idOrName,
  autoTest,
  onAutoTestConsumed,
  onClose,
}: {
  idOrName: string | null;
  autoTest: boolean;
  onAutoTestConsumed: () => void;
  onClose: () => void;
}) {
  const open = idOrName !== null;
  const detail = useQuery({
    queryKey: ["endpoint", idOrName],
    queryFn: () => api.getEndpoint(idOrName!),
    enabled: open,
  });
  const orch = useProbeOrchestrator();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [modelSearch, setModelSearch] = useState("");

  useEffect(() => {
    if (!detail.data) return;
    const excl = new Set(detail.data.excluded_by_filter);
    setChecked(new Set(detail.data.models.filter((m) => !excl.has(m))));
  }, [detail.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (autoTest && detail.data && detail.data.models.length > 0) {
      void orch.run(detail.data.id, detail.data.models);
      onAutoTestConsumed();
    }
  }, [autoTest, detail.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const resultByModel = useMemo(() => {
    const m = new Map<string, ModelResultPublic>();
    if (detail.data) for (const r of detail.data.results) m.set(r.model_id, r);
    return m;
  }, [detail.data]);

  function toggle(model: string) {
    setChecked((prev) => {
      const n = new Set(prev);
      if (n.has(model)) n.delete(model);
      else n.add(model);
      return n;
    });
  }

  if (!open) return null;
  const d = detail.data;

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 40,
          background: "rgba(10, 10, 9, 0.32)",
          backdropFilter: "blur(2px)",
          animation: "fadeIn .18s ease-out",
        }}
      />
      <aside
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          zIndex: 50,
          width: "min(680px, 100vw)",
          background: "var(--bg)",
          borderLeft: "1px solid var(--border)",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
          animation: "slideIn .24s cubic-bezier(.2,.8,.2,1)",
        }}
      >
        {detail.isLoading || !d ? (
          <div
            style={{
              padding: 32,
              color: "var(--text-muted)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>Loading…</span>
            <button
              className="btn btn-ghost btn-icon"
              onClick={onClose}
              title="Close"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        ) : (
          <DrawerBody
            d={d}
            checked={checked}
            toggle={toggle}
            modelSearch={modelSearch}
            setModelSearch={setModelSearch}
            resultByModel={resultByModel}
            orch={orch}
            onClose={onClose}
          />
        )}
      </aside>
    </>
  );
}

function DrawerBody({
  d,
  checked,
  toggle,
  modelSearch,
  setModelSearch,
  resultByModel,
  orch,
  onClose,
}: {
  d: EndpointDetail;
  checked: Set<string>;
  toggle: (m: string) => void;
  modelSearch: string;
  setModelSearch: (s: string) => void;
  resultByModel: Map<string, ModelResultPublic>;
  orch: ReturnType<typeof useProbeOrchestrator>;
  onClose: () => void;
}) {
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

  const checkedVisible = visible.filter((m) => checked.has(m));
  const pending = orch.pendingForEndpoint(d.id);

  return (
    <>
      {/* Header */}
      <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <HealthRing
            available={d.available}
            failed={d.failed}
            total={d.total_models}
            size={28}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2
                style={{
                  margin: 0,
                  fontSize: 17,
                  fontWeight: 600,
                  letterSpacing: -0.3,
                }}
              >
                {d.name}
              </h2>
              <HealthBadge health={endpointHealth(d)} />
            </div>
            <div
              className="mono"
              style={{
                color: "var(--text-faint)",
                fontSize: 11,
                marginTop: 2,
              }}
            >
              {d.id}
            </div>
          </div>
          <button
            className="btn btn-ghost btn-icon"
            onClick={onClose}
            title="Close (Esc)"
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        {/* Meta grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            gap: "8px 16px",
            marginTop: 14,
            fontSize: 12,
          }}
        >
          <MetaRow label="SDK">
            <span className="badge">{d.sdk}</span>
          </MetaRow>
          <MetaRow label="Mode">
            <span className="badge">{d.mode}</span>
          </MetaRow>
          <MetaRow label="Base URL">
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <code
                className="mono"
                style={{
                  background: "var(--bg-sunk)",
                  padding: "2px 6px",
                  borderRadius: 4,
                  fontSize: 11,
                  wordBreak: "break-all",
                }}
              >
                {d.base_url}
              </code>
              <CopyBtn text={d.base_url} />
            </span>
          </MetaRow>
          <MetaRow label="API Key">
            <ApiKeyReveal endpointId={d.id} masked={d.api_key_masked} />
          </MetaRow>
          <MetaRow label="Tags">
            <TagEditor endpointId={d.id} tags={d.tags} />
          </MetaRow>
          {d.note && (
            <MetaRow label="Note">
              <span style={{ color: "var(--text-muted)" }}>{d.note}</span>
            </MetaRow>
          )}
          <MetaRow label="Last test">
            <FreshnessPill iso={d.last_tested_at} />
          </MetaRow>
          {d.list_error && (
            <MetaRow label="List error">
              <span className="badge badge-bad">{d.list_error}</span>
            </MetaRow>
          )}
        </div>
      </div>

      {/* Action bar */}
      <div
        style={{
          padding: "10px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
          background: "var(--bg-sunk)",
        }}
      >
        <div style={{ position: "relative", flex: 1, minWidth: 180 }}>
          <Icon
            name="search"
            size={12}
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
            placeholder="搜索模型…"
            value={modelSearch}
            onChange={(e) => setModelSearch(e.target.value)}
            style={{ paddingLeft: 28, height: 28, fontSize: 12 }}
          />
        </div>
        <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
          {checkedVisible.length} selected · {visible.length} models
        </span>
        <button
          className="btn btn-sm"
          disabled={checkedVisible.length === 0 || pending > 0}
          onClick={() => orch.run(d.id, checkedVisible)}
        >
          <Icon name="play" size={11} /> Test selected
        </button>
        <button
          className="btn btn-primary btn-sm"
          disabled={visible.length === 0 || pending > 0}
          onClick={() => orch.run(d.id, visible)}
        >
          {pending > 0 ? `Testing… (${pending})` : "Test all"}
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 20px 24px" }}>
        {d.models.length === 0 ? (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              color: "var(--text-muted)",
            }}
          >
            {d.list_error
              ? "未发现任何模型 — 请检查 base URL 与 API key。"
              : "No models. Specified mode with empty list."}
          </div>
        ) : (
          <>
            {(
              [
                { title: "Testing", tone: "info", rows: testing, pulse: true },
                { title: "Available", tone: "ok", rows: available, pulse: false },
                { title: "Failed", tone: "bad", rows: failed, pulse: false },
                { title: "Untested", tone: "muted", rows: untested, pulse: false },
              ] as const
            ).map(
              (g) =>
                g.rows.length > 0 && (
                  <ModelGroup
                    key={g.title}
                    title={g.title}
                    tone={g.tone}
                    rows={g.rows}
                    checked={checked}
                    toggle={toggle}
                    resultByModel={resultByModel}
                    orch={orch}
                    ep={d}
                    pulse={g.pulse}
                  />
                ),
            )}
            {visible.length === 0 && (
              <div
                style={{
                  padding: 32,
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
      </div>
    </>
  );
}

function MetaRow({
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
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.4,
          paddingTop: 3,
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
  resultByModel,
  orch,
  ep,
  pulse,
}: {
  title: string;
  tone: "ok" | "bad" | "info" | "muted";
  rows: string[];
  checked: Set<string>;
  toggle: (m: string) => void;
  resultByModel: Map<string, ModelResultPublic>;
  orch: ReturnType<typeof useProbeOrchestrator>;
  ep: EndpointDetail;
  pulse?: boolean;
}) {
  const color = {
    ok: "var(--ok)",
    bad: "var(--bad)",
    info: "var(--info)",
    muted: "var(--text-muted)",
  }[tone];
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 6,
          paddingLeft: 2,
        }}
      >
        <span className="dot" style={{ background: color }} />
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color,
            textTransform: "uppercase",
            letterSpacing: 0.6,
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
          border: "1px solid var(--border)",
          borderRadius: 8,
          overflow: "hidden",
          background: "var(--bg-elev)",
        }}
      >
        {rows.map((m, i) => {
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
              last={i === rows.length - 1}
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
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "9px 12px",
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
      return (
        <span
          className="mono"
          style={{
            fontSize: 11,
            color: "var(--ok)",
            display: "flex",
            alignItems: "center",
            gap: 5,
          }}
        >
          <Icon name="check" size={11} /> {result.latency_ms}ms
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
          maxWidth: 220,
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
          maxWidth: 220,
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
