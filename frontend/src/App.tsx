import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { auth, UnauthorizedError } from "@/lib/auth";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";
import LoginScreen from "@/components/LoginScreen";

export default function App() {
  const [bumpAuth, setBumpAuth] = useState(0);
  const authState = useQuery({
    queryKey: ["auth-check", bumpAuth],
    queryFn: api.authCheck,
    retry: false,
  });

  if (authState.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-muted-foreground">
        校验登录…
      </div>
    );
  }
  if (authState.error instanceof UnauthorizedError) {
    return <LoginScreen onSuccess={() => setBumpAuth((n) => n + 1)} />;
  }
  if (authState.error) {
    return (
      <div className="min-h-screen flex items-center justify-center text-destructive">
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
  const [tagFilter, setTagFilter] = useState<Set<string>>(new Set());

  async function retestEverything() {
    if (!list.data) return;
    for (const ep of list.data) {
      if (ep.total_models === 0) continue;
      const detail = await api.getEndpoint(ep.id);
      void orch.run(ep.id, detail.models);
    }
  }

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">llm-model-probe</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={totalPending > 0}
            onClick={retestEverything}
          >
            {totalPending > 0
              ? `Retesting (${totalPending} in flight)…`
              : "↻ Retest all"}
          </Button>
          <Button onClick={() => setShowAdd(true)}>+ Add endpoint</Button>
          <Button variant="ghost" onClick={onLogout} title="Logout">
            ↪
          </Button>
        </div>
      </div>

      {list.isLoading && (
        <div className="text-muted-foreground">Loading…</div>
      )}
      {list.error && (
        <div className="text-destructive">Error: {String(list.error)}</div>
      )}
      {list.data && (
        <EndpointTable
          endpoints={list.data}
          search={search}
          setSearch={setSearch}
          tagFilter={tagFilter}
          setTagFilter={setTagFilter}
          onSelect={(id) => {
            setSelected(id);
            setAutoTest(false);
          }}
          onRetest={(id) => {
            setSelected(id);
            setAutoTest(true);
          }}
        />
      )}

      <AddEndpointDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={(id) => setSelected(id)}
      />
      <EndpointDetailDrawer
        idOrName={selected}
        autoTest={autoTest}
        onAutoTestConsumed={() => setAutoTest(false)}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
