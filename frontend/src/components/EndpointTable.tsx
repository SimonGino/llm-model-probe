import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { relative } from "@/lib/format";
import { useProbeOrchestrator } from "@/lib/orchestrator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function EndpointTable({
  endpoints,
  onSelect,
  onRetest,
}: {
  endpoints: EndpointSummary[];
  onSelect: (idOrName: string) => void;
  onRetest: (idOrName: string) => void;
}) {
  const qc = useQueryClient();
  const orch = useProbeOrchestrator();

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteEndpoint(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });

  if (endpoints.length === 0) {
    return (
      <div className="text-muted-foreground p-8 text-center border rounded-md">
        No endpoints yet. Click <strong>+ Add endpoint</strong>.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-28">ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>SDK</TableHead>
          <TableHead>Mode</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Tested</TableHead>
          <TableHead>Tags</TableHead>
          <TableHead>Note</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {endpoints.map((ep) => {
          const pendingForRow = orch.pendingForEndpoint(ep.id);
          const untested = ep.total_models - ep.available - ep.failed;
          return (
            <TableRow
              key={ep.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => onSelect(ep.id)}
            >
              <TableCell className="font-mono text-xs text-muted-foreground">
                {ep.id}
              </TableCell>
              <TableCell className="font-medium">{ep.name}</TableCell>
              <TableCell>{ep.sdk}</TableCell>
              <TableCell>{ep.mode}</TableCell>
              <TableCell>
                {ep.list_error ? (
                  <Badge variant="destructive">list-error</Badge>
                ) : ep.total_models === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <span className="text-xs">
                    <span className="text-green-600">{ep.available}</span>
                    {" / "}
                    <span className="text-destructive">{ep.failed}</span>
                    {untested > 0 && (
                      <>
                        {" / "}
                        <span className="text-muted-foreground">
                          {untested} untested
                        </span>
                      </>
                    )}
                    {pendingForRow > 0 && (
                      <span className="text-blue-600 ml-1">
                        ({pendingForRow} testing)
                      </span>
                    )}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {relative(ep.last_tested_at)}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {ep.tags.slice(0, 3).map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">
                      {t}
                    </Badge>
                  ))}
                  {ep.tags.length > 3 && (
                    <Badge variant="outline" className="text-xs">
                      +{ep.tags.length - 3}
                    </Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-muted-foreground max-w-[160px] truncate">
                {ep.note}
              </TableCell>
              <TableCell
                className="text-right space-x-1"
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ep.total_models === 0 || pendingForRow > 0}
                  title="Open + test all models"
                  onClick={() => onRetest(ep.id)}
                >
                  ↻
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (confirm(`Delete '${ep.name}'?`)) remove.mutate(ep.id);
                  }}
                >
                  ✕
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
