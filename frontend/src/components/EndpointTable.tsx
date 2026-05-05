import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  FreshnessPill,
  HealthBadge,
  HealthRing,
  Icon,
  LatencyBars,
  endpointHealth,
} from "@/components/atoms";

export type LayoutMode = "table" | "cards";

interface CommonProps {
  endpoints: EndpointSummary[];
  layout: LayoutMode;
  onSelect: (idOrName: string) => void;
  onRetest: (idOrName: string) => void;
}

export default function EndpointTable({
  endpoints,
  layout,
  onSelect,
  onRetest,
}: CommonProps) {
  if (endpoints.length === 0) return <EmptyState />;
  if (layout === "cards") {
    return (
      <CardsView endpoints={endpoints} onSelect={onSelect} onRetest={onRetest} />
    );
  }
  return (
    <TableView endpoints={endpoints} onSelect={onSelect} onRetest={onRetest} />
  );
}

const COLS =
  "minmax(180px, 1.4fr) 80px 110px 120px 200px minmax(120px, 1fr) 110px 80px";

function TableView({
  endpoints,
  onSelect,
  onRetest,
}: Omit<CommonProps, "layout">) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        overflow: "hidden",
        background: "var(--bg-elev)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: COLS,
          padding: "10px 16px",
          gap: 12,
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-sunk)",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.4,
          color: "var(--text-muted)",
          fontWeight: 500,
        }}
      >
        <div>Endpoint</div>
        <div>SDK</div>
        <div>Health</div>
        <div>Models</div>
        <div>Latency</div>
        <div>Tags</div>
        <div>Tested</div>
        <div style={{ textAlign: "right" }}>Actions</div>
      </div>
      {endpoints.map((ep) => (
        <TableRow
          key={ep.id}
          ep={ep}
          onSelect={onSelect}
          onRetest={onRetest}
        />
      ))}
    </div>
  );
}

function TableRow({
  ep,
  onSelect,
  onRetest,
}: {
  ep: EndpointSummary;
  onSelect: (id: string) => void;
  onRetest: (id: string) => void;
}) {
  const orch = useProbeOrchestrator();
  const pending = orch.pendingForEndpoint(ep.id);
  const health = endpointHealth(ep);
  const latencies = useFetchedLatencies(ep);
  const avg = latencies.length
    ? Math.round(latencies.reduce((s, n) => s + n, 0) / latencies.length)
    : null;

  return (
    <div
      onClick={() => onSelect(ep.id)}
      style={{
        display: "grid",
        gridTemplateColumns: COLS,
        padding: "12px 16px",
        gap: 12,
        alignItems: "center",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        transition: "background .1s",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.background = "var(--bg-hover)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontWeight: 500, fontSize: 13 }}>{ep.name}</span>
          <span className="badge" style={{ fontSize: 10 }}>
            {ep.mode}
          </span>
        </div>
        <div
          className="mono"
          style={{
            color: "var(--text-faint)",
            fontSize: 11,
            marginTop: 2,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {ep.base_url}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{ep.sdk}</div>
      <div>
        <HealthBadge health={health} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <HealthRing
          available={ep.available}
          failed={ep.failed}
          total={ep.total_models}
          size={24}
        />
        <div style={{ fontSize: 12, lineHeight: 1.2 }}>
          {ep.list_error ? (
            <span style={{ color: "var(--bad)" }}>—</span>
          ) : ep.total_models === 0 ? (
            <span style={{ color: "var(--text-faint)" }}>—</span>
          ) : (
            <>
              <span style={{ color: "var(--ok)", fontWeight: 500 }}>
                {ep.available}
              </span>
              <span style={{ color: "var(--text-faint)" }}> / </span>
              <span style={{ color: "var(--text-muted)" }}>
                {ep.total_models}
              </span>
              {pending > 0 && (
                <span
                  className="mono"
                  style={{ color: "var(--info)", marginLeft: 6, fontSize: 11 }}
                >
                  ({pending} testing)
                </span>
              )}
            </>
          )}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <LatencyBars values={latencies.slice(0, 12)} width={84} height={18} />
        <span
          className="mono"
          style={{ fontSize: 11, color: "var(--text-muted)" }}
        >
          {avg !== null ? `${avg}ms` : "—"}
        </span>
      </div>
      <TagsList tags={ep.tags} max={3} />
      <div>
        <FreshnessPill iso={ep.last_tested_at} />
      </div>
      <div
        style={{
          textAlign: "right",
          display: "flex",
          gap: 2,
          justifyContent: "flex-end",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <RetestBtn ep={ep} pending={pending} onRetest={onRetest} />
        <DeleteBtn ep={ep} />
      </div>
    </div>
  );
}

function TagsList({ tags, max }: { tags: string[]; max: number }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, minWidth: 0 }}>
      {tags.slice(0, max).map((t) => (
        <span key={t} className="badge">
          {t}
        </span>
      ))}
      {tags.length > max && (
        <span className="badge">+{tags.length - max}</span>
      )}
    </div>
  );
}

function RetestBtn({
  ep,
  pending,
  onRetest,
}: {
  ep: EndpointSummary;
  pending: number;
  onRetest: (id: string) => void;
}) {
  return (
    <button
      className="btn btn-ghost btn-icon btn-sm"
      title="Retest"
      disabled={ep.total_models === 0 || pending > 0}
      onClick={() => onRetest(ep.id)}
    >
      <Icon name="refresh" size={12} />
    </button>
  );
}

function CardsView({
  endpoints,
  onSelect,
  onRetest,
}: Omit<CommonProps, "layout">) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
        gap: 14,
      }}
    >
      {endpoints.map((ep) => (
        <EndpointCard
          key={ep.id}
          ep={ep}
          onSelect={onSelect}
          onRetest={onRetest}
        />
      ))}
    </div>
  );
}

function EndpointCard({
  ep,
  onSelect,
  onRetest,
}: {
  ep: EndpointSummary;
  onSelect: (id: string) => void;
  onRetest: (id: string) => void;
}) {
  const orch = useProbeOrchestrator();
  const pending = orch.pendingForEndpoint(ep.id);
  const health = endpointHealth(ep);
  const latencies = useFetchedLatencies(ep);
  return (
    <div
      onClick={() => onSelect(ep.id)}
      style={{
        background: "var(--bg-elev)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: 16,
        cursor: "pointer",
        boxShadow: "var(--shadow-sm)",
        transition: "border-color .12s",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.borderColor = "var(--border-strong)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.borderColor = "var(--border)")
      }
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <HealthRing
          available={ep.available}
          failed={ep.failed}
          total={ep.total_models}
          size={32}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>{ep.name}</span>
          </div>
          <div
            className="mono"
            style={{
              color: "var(--text-faint)",
              fontSize: 11,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {ep.base_url}
          </div>
        </div>
        <HealthBadge health={health} />
      </div>

      <div
        style={{
          display: "flex",
          gap: 14,
          marginTop: 14,
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: 0.4,
            }}
          >
            Models
          </span>
          <span
            style={{ fontSize: 16, fontWeight: 600, letterSpacing: -0.3 }}
          >
            {ep.list_error ? (
              <span style={{ color: "var(--bad)" }}>err</span>
            ) : (
              <>
                <span style={{ color: "var(--ok)" }}>{ep.available}</span>
                <span
                  style={{ color: "var(--text-faint)", fontWeight: 400 }}
                >
                  /{ep.total_models}
                </span>
              </>
            )}
            {pending > 0 && (
              <span
                className="mono"
                style={{
                  color: "var(--info)",
                  marginLeft: 6,
                  fontSize: 11,
                  fontWeight: 500,
                }}
              >
                ({pending}…)
              </span>
            )}
          </span>
        </div>
        <div style={{ width: 1, height: 28, background: "var(--border)" }} />
        <div style={{ flex: 1 }}>
          <span
            style={{
              fontSize: 10,
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: 0.4,
            }}
          >
            Latency
          </span>
          <div style={{ marginTop: 2 }}>
            <LatencyBars values={latencies.slice(0, 16)} width={120} height={16} />
          </div>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 14,
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          <span className="badge">{ep.sdk}</span>
          <span className="badge">{ep.mode}</span>
          {ep.tags.slice(0, 2).map((t) => (
            <span key={t} className="badge">
              {t}
            </span>
          ))}
        </div>
        <div
          style={{ display: "flex", alignItems: "center", gap: 4 }}
          onClick={(e) => e.stopPropagation()}
        >
          <FreshnessPill iso={ep.last_tested_at} />
          <RetestBtn ep={ep} pending={pending} onRetest={onRetest} />
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        border: "1px dashed var(--border-strong)",
        borderRadius: 10,
        padding: "60px 24px",
        textAlign: "center",
        color: "var(--text-muted)",
      }}
    >
      <Icon name="globe" size={28} style={{ color: "var(--text-faint)" }} />
      <div style={{ marginTop: 12, fontWeight: 500 }}>没有匹配的端点</div>
      <div style={{ fontSize: 12, marginTop: 4 }}>
        调整筛选条件，或点击 “Add endpoint” 注册新服务。
      </div>
    </div>
  );
}

function DeleteBtn({ ep }: { ep: EndpointSummary }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteEndpoint(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });
  return (
    <button
      className="btn btn-ghost btn-icon btn-sm"
      title="Delete"
      disabled={remove.isPending}
      onClick={(e) => {
        e.stopPropagation();
        if (confirm(`Delete '${ep.name}'?`)) remove.mutate(ep.id);
      }}
    >
      <Icon name="trash" size={12} />
    </button>
  );
}

function useFetchedLatencies(ep: EndpointSummary): number[] {
  const enabled = !ep.list_error && ep.available > 0;
  const detail = useQuery({
    queryKey: ["endpoint", ep.id],
    queryFn: () => api.getEndpoint(ep.id),
    enabled,
    staleTime: 30_000,
  });
  if (!detail.data) return [];
  const out: number[] = [];
  for (const r of detail.data.results) {
    if (r.status === "available" && typeof r.latency_ms === "number") {
      out.push(r.latency_ms);
    }
  }
  return out;
}

