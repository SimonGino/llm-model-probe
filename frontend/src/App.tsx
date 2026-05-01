import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import EndpointTable from "@/components/EndpointTable";
import AddEndpointDialog from "@/components/AddEndpointDialog";
import EndpointDetailDrawer from "@/components/EndpointDetailDrawer";

export default function App() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["endpoints"],
    queryFn: api.listEndpoints,
  });
  const retestAll = useMutation({
    mutationFn: api.retestAll,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">llm-model-probe</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={retestAll.isPending}
            onClick={() => retestAll.mutate()}
          >
            {retestAll.isPending ? "Retesting…" : "↻ Retest all"}
          </Button>
          <Button onClick={() => setShowAdd(true)}>+ Add endpoint</Button>
        </div>
      </div>

      {list.isLoading && (
        <div className="text-muted-foreground">Loading…</div>
      )}
      {list.error && (
        <div className="text-destructive">Error: {String(list.error)}</div>
      )}
      {list.data && (
        <EndpointTable endpoints={list.data} onSelect={setSelected} />
      )}

      <AddEndpointDialog open={showAdd} onClose={() => setShowAdd(false)} />
      <EndpointDetailDrawer
        idOrName={selected}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
