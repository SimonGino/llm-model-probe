import { relative } from "@/lib/format";
import { endpointHealth, type HealthTone } from "@/components/atoms";
import type { EndpointSummary } from "@/lib/types";

export type SortKey = "status" | "name" | "tested";

const STATUS_ORDER: Record<HealthTone, number> = {
  bad: 0,
  warn: 1,
  muted: 2,
  ok: 3,
};

function dotColor(tone: HealthTone): string {
  return {
    ok: "var(--ok)",
    warn: "var(--warn)",
    bad: "var(--bad)",
    muted: "var(--text-faint)",
  }[tone];
}

export default function EndpointSidebar({
  endpoints,
  selectedId,
  onSelect,
  sortBy,
  setSortBy,
}: {
  endpoints: EndpointSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  sortBy: SortKey;
  setSortBy: (v: SortKey) => void;
}) {
  const sorted = sortEndpoints(endpoints, sortBy);
  return (
    <aside
      style={{
        borderRight: "1px solid var(--border)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg-elev)",
        minWidth: 0,
      }}
    >
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-sunk)",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: 0.6,
            fontWeight: 600,
          }}
        >
          Endpoints
        </span>
        <span style={{ fontSize: 11, color: "var(--text-faint)" }}>
          {sorted.length}
        </span>
        <div style={{ flex: 1 }} />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          style={{
            background: "transparent",
            border: "none",
            fontSize: 11,
            color: "var(--text-muted)",
            outline: "none",
            cursor: "pointer",
          }}
        >
          <option value="status">sort: status</option>
          <option value="name">sort: name</option>
          <option value="tested">sort: tested</option>
        </select>
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>
        {sorted.length === 0 ? (
          <div
            style={{
              padding: 32,
              textAlign: "center",
              color: "var(--text-faint)",
              fontSize: 12,
            }}
          >
            没有匹配的端点
          </div>
        ) : (
          sorted.map((ep) => (
            <ListRow
              key={ep.id}
              ep={ep}
              active={ep.id === selectedId}
              onClick={() => onSelect(ep.id)}
            />
          ))
        )}
      </div>
    </aside>
  );
}

function sortEndpoints(
  endpoints: EndpointSummary[],
  sortBy: SortKey,
): EndpointSummary[] {
  const arr = [...endpoints];
  if (sortBy === "status") {
    arr.sort(
      (a, b) =>
        STATUS_ORDER[endpointHealth(a).tone] -
          STATUS_ORDER[endpointHealth(b).tone] || a.name.localeCompare(b.name),
    );
  } else if (sortBy === "name") {
    arr.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    arr.sort((a, b) => {
      const ta = a.last_tested_at ? new Date(a.last_tested_at).getTime() : 0;
      const tb = b.last_tested_at ? new Date(b.last_tested_at).getTime() : 0;
      return tb - ta;
    });
  }
  return arr;
}

function ListRow({
  ep,
  active,
  onClick,
}: {
  ep: EndpointSummary;
  active: boolean;
  onClick: () => void;
}) {
  const tone = endpointHealth(ep).tone;
  return (
    <div
      onClick={onClick}
      style={{
        padding: "11px 16px",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        background: active ? "var(--bg-hover)" : "transparent",
        borderLeft: active
          ? "2px solid var(--accent)"
          : "2px solid transparent",
        transition: "background .1s",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "var(--bg-sunk)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "transparent";
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          marginBottom: 3,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: dotColor(tone),
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontWeight: active ? 600 : 500,
            fontSize: 13,
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {ep.name}
        </span>
        <span
          style={{
            fontSize: 10,
            color: "var(--text-faint)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {relative(ep.last_tested_at)}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 11,
          color: "var(--text-faint)",
          gap: 8,
        }}
      >
        <span
          className="mono"
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
            minWidth: 0,
          }}
        >
          {ep.base_url.replace(/^https?:\/\//, "")}
        </span>
        <span style={{ fontVariantNumeric: "tabular-nums", flexShrink: 0 }}>
          {ep.list_error ? (
            <span style={{ color: "var(--bad)" }}>err</span>
          ) : ep.total_models === 0 ? (
            <span>—</span>
          ) : (
            <>
              <span style={{ color: "var(--ok)" }}>{ep.available}</span>
              <span>/{ep.total_models}</span>
            </>
          )}
        </span>
      </div>
      {ep.tags.length > 0 && (
        <div style={{ display: "flex", gap: 3, marginTop: 5 }}>
          {ep.tags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="badge"
              style={{ fontSize: 9, height: 15 }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
