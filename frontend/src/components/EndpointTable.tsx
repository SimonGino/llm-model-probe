import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointSummary } from "@/lib/types";
import { relative } from "@/lib/format";
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
}: {
  endpoints: EndpointSummary[];
  onSelect: (idOrName: string) => void;
}) {
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const retest = useMutation({
    mutationFn: (id: string) => api.retestEndpoint(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => {
      setBusyId(null);
      qc.invalidateQueries({ queryKey: ["endpoints"] });
    },
  });

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
          <TableHead>Note</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {endpoints.map((ep) => (
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
              ) : ep.available + ep.failed === 0 ? (
                <span className="text-muted-foreground">not probed</span>
              ) : (
                <span>
                  <span className="text-green-600">{ep.available}</span>
                  /<span className="text-destructive">{ep.failed}</span>
                </span>
              )}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {relative(ep.last_tested_at)}
            </TableCell>
            <TableCell className="text-muted-foreground max-w-[200px] truncate">
              {ep.note}
            </TableCell>
            <TableCell
              className="text-right space-x-1"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                size="sm"
                variant="outline"
                disabled={busyId === ep.id || retest.isPending}
                onClick={() => retest.mutate(ep.id)}
              >
                {busyId === ep.id ? "…" : "↻"}
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
        ))}
      </TableBody>
    </Table>
  );
}
