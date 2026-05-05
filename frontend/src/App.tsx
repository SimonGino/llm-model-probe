import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { useTheme, type Theme } from "@/lib/theme";
import EndpointTable, { type LayoutMode } from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";
import LoginScreen from "@/components/LoginScreen";
import {
  BrandMark,
  Icon,
  Segmented,
  endpointHealth,
} from "@/components/atoms";

export default function App() {
  // Bind theme so the dataset attribute applies even on the login screen,
  // which never mounts ThemeToggle.
  useTheme();
  const [bumpAuth, setBumpAuth] = useState(0);
  const authState = useQuery({
    queryKey: ["auth-check", bumpAuth],
    queryFn: api.authCheck,
    retry: false,
  });

  if (authState.isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          color: "var(--text-muted)",
        }}
      >
        校验登录…
      </div>
    );
  }
  if (authState.error instanceof UnauthorizedError) {
    return <LoginScreen onSuccess={() => setBumpAuth((n) => n + 1)} />;
  }
  if (authState.error) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          color: "var(--bad)",
        }}
      >
        服务异常: {String(authState.error)}
      </div>
    );
  }
  return (
    <MainApp
      onLogout={() => {
        auth.clear();
        setBumpAuth((n) => n + 1);
      }}
    />
  );
}

function MainApp({ onLogout }: { onLogout: () => void }) {
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const orch = useProbeOrchestrator();
  const totalPending = orch.totalPending();

  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [autoTest, setAutoTest] = useState(false);
  const [search, setSearch] = useState("");
  const [sdkFilter, setSdkFilter] = useState<"all" | "openai" | "anthropic">(
    "all",
  );
  const [healthFilter, setHealthFilter] = useState<"all" | "healthy" | "issues">(
    "all",
  );
  const [layout, setLayout] = useState<LayoutMode>("table");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (showAdd) setShowAdd(false);
      else if (selected) {
        setSelected(null);
        setAutoTest(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAdd, selected]);

  async function retestEverything() {
    if (!list.data) return;
    await Promise.all(
      list.data
        .filter((ep) => ep.total_models > 0)
        .map(async (ep) => {
          const detail = await api.getEndpoint(ep.id);
          void orch.run(ep.id, detail.models);
        }),
    );
  }

  const endpoints = list.data ?? [];

  const filtered = useMemo(() => {
    return endpoints.filter((ep) => {
      if (search) {
        const q = search.toLowerCase();
        const hay = [ep.name, ep.note, ep.base_url, ...ep.tags]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (sdkFilter !== "all" && ep.sdk !== sdkFilter) return false;
      if (healthFilter !== "all") {
        const tone = endpointHealth(ep).tone;
        if (healthFilter === "healthy" && tone !== "ok") return false;
        if (healthFilter === "issues" && tone !== "warn" && tone !== "bad")
          return false;
      }
      return true;
    });
  }, [endpoints, search, sdkFilter, healthFilter]);

  const totals = useMemo(
    () =>
      endpoints.reduce(
        (acc, ep) => {
          acc.endpoints++;
          acc.models += ep.total_models;
          acc.available += ep.available;
          acc.failed += ep.failed;
          if (ep.list_error) acc.errored++;
          return acc;
        },
        { endpoints: 0, models: 0, available: 0, failed: 0, errored: 0 },
      ),
    [endpoints],
  );

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <TopBar
        onAdd={() => setShowAdd(true)}
        onRetestAll={retestEverything}
        onLogout={onLogout}
        retesting={totalPending > 0}
        retestPending={totalPending}
      />

      <main
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "28px 28px 80px",
        }}
      >
        {list.isLoading && (
          <div style={{ color: "var(--text-muted)", padding: "12px 0" }}>
            Loading…
          </div>
        )}
        {list.error && (
          <div style={{ color: "var(--bad)", padding: "12px 0" }}>
            Error: {String(list.error)}
          </div>
        )}
        {list.data && (
          <>
            <PageHeader totals={totals} />
            <FilterBar
              search={search}
              setSearch={setSearch}
              sdkFilter={sdkFilter}
              setSdkFilter={setSdkFilter}
              healthFilter={healthFilter}
              setHealthFilter={setHealthFilter}
              layout={layout}
              setLayout={setLayout}
              shown={filtered.length}
              total={endpoints.length}
            />
            <EndpointTable
              endpoints={filtered}
              layout={layout}
              onSelect={(id) => {
                setSelected(id);
                setAutoTest(false);
              }}
              onRetest={(id) => {
                setSelected(id);
                setAutoTest(true);
              }}
            />
          </>
        )}
      </main>

      <AddEndpointDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(id) => setSelected(id)}
      />
      <EndpointDetailDrawer
        idOrName={selected}
        autoTest={autoTest}
        onAutoTestConsumed={() => setAutoTest(false)}
        onClose={() => {
          setSelected(null);
          setAutoTest(false);
        }}
      />
    </div>
  );
}

function TopBar({
  onAdd,
  onRetestAll,
  onLogout,
  retesting,
  retestPending,
}: {
  onAdd: () => void;
  onRetestAll: () => void;
  onLogout: () => void;
  retesting: boolean;
  retestPending: number;
}) {
  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 30,
        background: "color-mix(in oklab, var(--bg) 92%, transparent)",
        backdropFilter: "saturate(1.4) blur(8px)",
        WebkitBackdropFilter: "saturate(1.4) blur(8px)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "10px 28px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <BrandMark />
        <div style={{ fontWeight: 600, letterSpacing: -0.2, fontSize: 14 }}>
          llm-model-probe
        </div>
        <span className="badge" style={{ marginLeft: 4 }}>
          v0.4
        </span>

        <div style={{ flex: 1 }} />

        <ThemeToggle />

        <button
          className="btn"
          onClick={onRetestAll}
          disabled={retesting}
          title="Retest all endpoints"
        >
          <Icon name="refresh" size={13} />
          {retesting ? `Retesting (${retestPending})…` : "Retest all"}
        </button>
        <button className="btn btn-primary" onClick={onAdd}>
          <Icon name="plus" size={13} /> Add endpoint
        </button>
        <button
          className="btn btn-ghost btn-icon"
          onClick={onLogout}
          title="Logout"
        >
          <Icon name="logout" size={13} />
        </button>
      </div>
    </header>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next: Record<Theme, Theme> = {
    light: "dim",
    dim: "dark",
    dark: "light",
  };
  const icon = theme === "light" ? "sun" : theme === "dim" ? "circle-half" : "moon";
  const label = theme === "light" ? "Light" : theme === "dim" ? "Dim" : "Dark";
  return (
    <button
      className="btn btn-ghost btn-icon"
      title={`Theme: ${label} (click to cycle)`}
      onClick={() => setTheme(next[theme])}
    >
      <Icon name={icon} size={14} />
    </button>
  );
}

function PageHeader({
  totals,
}: {
  totals: {
    endpoints: number;
    models: number;
    available: number;
    failed: number;
    errored: number;
  };
}) {
  return (
    <div style={{ marginBottom: 22 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 4,
        }}
      >
        <h1
          style={{
            fontSize: 24,
            fontWeight: 600,
            margin: 0,
            letterSpacing: -0.4,
          }}
        >
          Endpoints
        </h1>
        <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
          {totals.endpoints} endpoints · {totals.models} models tracked
        </span>
      </div>

      <div
        style={{
          display: "flex",
          gap: 28,
          marginTop: 14,
          flexWrap: "wrap",
        }}
      >
        <Stat
          label="Available"
          value={totals.available}
          tone="ok"
          sub={`${pct(totals.available, totals.models)}% of probed`}
        />
        <Stat
          label="Failed"
          value={totals.failed}
          tone="bad"
          sub={totals.failed === 0 ? "no current failures" : "needs attention"}
        />
        <Stat
          label="List errors"
          value={totals.errored}
          tone={totals.errored > 0 ? "warn" : "muted"}
          sub="endpoints unreachable"
        />
        <Stat
          label="Tracked models"
          value={totals.models}
          tone="muted"
          sub="across all endpoints"
        />
      </div>
    </div>
  );
}

function pct(a: number, b: number): number {
  return b === 0 ? 0 : Math.round((a / b) * 100);
}

function Stat({
  label,
  value,
  tone = "muted",
  sub,
}: {
  label: string;
  value: number;
  tone?: "ok" | "bad" | "warn" | "muted";
  sub: string;
}) {
  const color = {
    ok: "var(--ok)",
    bad: "var(--bad)",
    warn: "var(--warn)",
    muted: "var(--text)",
  }[tone];
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: 0.4,
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 600,
          color,
          lineHeight: 1.1,
          fontFamily: "Inter",
          letterSpacing: -0.5,
          marginTop: 2,
        }}
      >
        {value.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 1 }}>
        {sub}
      </div>
    </div>
  );
}

function FilterBar({
  search,
  setSearch,
  sdkFilter,
  setSdkFilter,
  healthFilter,
  setHealthFilter,
  layout,
  setLayout,
  shown,
  total,
}: {
  search: string;
  setSearch: (s: string) => void;
  sdkFilter: "all" | "openai" | "anthropic";
  setSdkFilter: (v: "all" | "openai" | "anthropic") => void;
  healthFilter: "all" | "healthy" | "issues";
  setHealthFilter: (v: "all" | "healthy" | "issues") => void;
  layout: LayoutMode;
  setLayout: (v: LayoutMode) => void;
  shown: number;
  total: number;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        marginBottom: 14,
        flexWrap: "wrap",
      }}
    >
      <div style={{ position: "relative", minWidth: 240 }}>
        <Icon
          name="search"
          size={13}
          style={{
            position: "absolute",
            left: 10,
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--text-faint)",
          }}
        />
        <input
          className="input"
          placeholder="搜索名称 / 备注 / 标签 / URL…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ paddingLeft: 30 }}
        />
      </div>

      <Segmented
        options={[
          { value: "all", label: "All" },
          { value: "openai", label: "OpenAI" },
          { value: "anthropic", label: "Anthropic" },
        ]}
        value={sdkFilter}
        onChange={setSdkFilter}
      />

      <Segmented
        options={[
          { value: "all", label: "Any" },
          { value: "healthy", label: "Healthy" },
          { value: "issues", label: "Issues" },
        ]}
        value={healthFilter}
        onChange={setHealthFilter}
      />

      <div style={{ flex: 1 }} />

      <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
        {shown}/{total}
      </span>

      <Segmented
        options={[
          { value: "table", label: "Table" },
          { value: "cards", label: "Cards" },
        ]}
        value={layout}
        onChange={setLayout}
        compact
      />
    </div>
  );
}

