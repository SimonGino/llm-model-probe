import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { useTheme, type Theme } from "@/lib/theme";
import EndpointSidebar, {
  type SortKey,
} from "@/components/EndpointSidebar";
import EndpointDetailPane from "@/components/EndpointDetailPane";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import LoginScreen from "@/components/LoginScreen";
import { BrandMark, Icon } from "@/components/atoms";

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
    <SplitApp
      onLogout={() => {
        auth.clear();
        setBumpAuth((n) => n + 1);
      }}
    />
  );
}

function SplitApp({ onLogout }: { onLogout: () => void }) {
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const orch = useProbeOrchestrator();
  const totalPending = orch.totalPending();

  const [showAdd, setShowAdd] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("status");

  const endpoints = list.data ?? [];

  const filtered = useMemo(() => {
    if (!search.trim()) return endpoints;
    const q = search.toLowerCase();
    return endpoints.filter((ep) =>
      [ep.name, ep.note, ep.base_url, ...ep.tags]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [endpoints, search]);

  // Auto-select first endpoint when none selected (or current one disappears).
  useEffect(() => {
    if (endpoints.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !endpoints.some((ep) => ep.id === selectedId)) {
      setSelectedId(endpoints[0].id);
    }
  }, [endpoints, selectedId]);

  // ⌘K / Ctrl+K → focus topbar search; Esc → close add dialog.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.getElementById("topbar-search")?.focus();
        return;
      }
      if (e.key === "Escape" && showAdd) setShowAdd(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAdd]);

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

  function onDeleted(deletedId: string) {
    const idx = filtered.findIndex((ep) => ep.id === deletedId);
    const next =
      filtered[idx + 1]?.id ??
      filtered[idx - 1]?.id ??
      filtered.find((ep) => ep.id !== deletedId)?.id ??
      null;
    setSelectedId(next);
  }

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
      }}
    >
      <TopBar
        search={search}
        setSearch={setSearch}
        onAdd={() => setShowAdd(true)}
        onRetestAll={retestEverything}
        onLogout={onLogout}
        retesting={totalPending > 0}
        retestPending={totalPending}
      />

      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "360px 1fr",
          overflow: "hidden",
        }}
      >
        <EndpointSidebar
          endpoints={filtered}
          selectedId={selectedId}
          onSelect={setSelectedId}
          sortBy={sortBy}
          setSortBy={setSortBy}
        />

        <main style={{ overflow: "auto" }}>
          {list.isLoading ? (
            <div style={{ padding: 32, color: "var(--text-muted)" }}>
              Loading…
            </div>
          ) : list.error ? (
            <div style={{ padding: 32, color: "var(--bad)" }}>
              Error: {String(list.error)}
            </div>
          ) : selectedId ? (
            <EndpointDetailPane
              key={selectedId}
              idOrName={selectedId}
              onDeleted={onDeleted}
            />
          ) : (
            <EmptyDetail
              hasEndpoints={endpoints.length > 0}
              onAdd={() => setShowAdd(true)}
            />
          )}
        </main>
      </div>

      <AddEndpointDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(id) => setSelectedId(id)}
      />
    </div>
  );
}

function TopBar({
  search,
  setSearch,
  onAdd,
  onRetestAll,
  onLogout,
  retesting,
  retestPending,
}: {
  search: string;
  setSearch: (s: string) => void;
  onAdd: () => void;
  onRetestAll: () => void;
  onLogout: () => void;
  retesting: boolean;
  retestPending: number;
}) {
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        padding: "10px 18px",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <BrandMark size={22} />
      <span style={{ fontWeight: 600, fontSize: 13 }}>llm-model-probe</span>
      <span className="badge" style={{ marginLeft: 2 }}>
        v0.4
      </span>
      <div style={{ flex: 1 }} />
      <div style={{ position: "relative" }}>
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
          id="topbar-search"
          className="input"
          placeholder="搜索…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 240, paddingLeft: 28, paddingRight: 60 }}
        />
        <span
          style={{
            position: "absolute",
            right: 8,
            top: "50%",
            transform: "translateY(-50%)",
            display: "flex",
            gap: 2,
            pointerEvents: "none",
          }}
        >
          <span className="kbd">⌘</span>
          <span className="kbd">K</span>
        </span>
      </div>
      <ThemeToggle />
      <button
        className="btn"
        onClick={onRetestAll}
        disabled={retesting}
        title="Retest all endpoints"
      >
        <Icon name="refresh" size={12} />
        {retesting ? `Retesting (${retestPending})…` : "Retest all"}
      </button>
      <button className="btn btn-primary" onClick={onAdd}>
        <Icon name="plus" size={12} /> Add
      </button>
      <button
        className="btn btn-ghost btn-icon"
        onClick={onLogout}
        title="Logout"
      >
        <Icon name="logout" size={12} />
      </button>
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
  const icon =
    theme === "light" ? "sun" : theme === "dim" ? "circle-half" : "moon";
  const label =
    theme === "light" ? "Light" : theme === "dim" ? "Dim" : "Dark";
  return (
    <button
      className="btn btn-ghost btn-icon"
      title={`Theme: ${label} (click to cycle)`}
      onClick={() => setTheme(next[theme])}
    >
      <Icon name={icon} size={13} />
    </button>
  );
}

function EmptyDetail({
  hasEndpoints,
  onAdd,
}: {
  hasEndpoints: boolean;
  onAdd: () => void;
}) {
  if (hasEndpoints) {
    return (
      <div
        style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}
      >
        选择左侧端点查看详情
      </div>
    );
  }
  return (
    <div
      style={{
        height: "100%",
        display: "grid",
        placeItems: "center",
        padding: 32,
      }}
    >
      <div style={{ textAlign: "center", maxWidth: 360 }}>
        <h2
          style={{
            margin: 0,
            fontSize: 18,
            fontWeight: 600,
            letterSpacing: -0.3,
          }}
        >
          还没有端点
        </h2>
        <p
          style={{
            color: "var(--text-muted)",
            fontSize: 13,
            margin: "6px 0 18px",
          }}
        >
          注册一个 OpenAI / Anthropic 兼容端点，立即发现可用模型。
        </p>
        <button className="btn btn-primary" onClick={onAdd}>
          <Icon name="plus" size={13} /> Add endpoint
        </button>
      </div>
    </div>
  );
}
