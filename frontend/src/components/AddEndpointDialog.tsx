import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EndpointCreate } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import SmartPasteArea from "./SmartPasteArea";

const empty: EndpointCreate = {
  name: "",
  sdk: "openai",
  base_url: "",
  api_key: "",
  models: [],
  note: "",
};

export default function AddEndpointDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<EndpointCreate>(empty);
  const [modelsText, setModelsText] = useState("");

  const create = useMutation({
    mutationFn: (payload: EndpointCreate) =>
      api.createEndpoint({ ...payload, no_probe: true }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      setForm(empty);
      setModelsText("");
      onClose();
      onCreated(data.id);
    },
  });

  function submit() {
    const models = modelsText
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    create.mutate({ ...form, models });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add endpoint</DialogTitle>
        </DialogHeader>

        <SmartPasteArea
          onApply={(s) => {
            setForm((f) => ({
              ...f,
              name: s.name ?? f.name,
              sdk: s.sdk ?? f.sdk,
              base_url: s.base_url ?? f.base_url,
              api_key: s.api_key ?? f.api_key,
              note: s.note ?? f.note,
            }));
            if (s.models && s.models.length) setModelsText(s.models.join(", "));
          }}
        />

        <div className="space-y-3 py-2">
          <Field label="Name">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="SDK">
            <select
              className="w-full border rounded-md px-2 h-9 bg-background"
              value={form.sdk}
              onChange={(e) =>
                setForm({
                  ...form,
                  sdk: e.target.value as "openai" | "anthropic",
                })
              }
            >
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
            </select>
          </Field>
          <Field label="Base URL">
            <Input
              placeholder="https://api.example.com/v1"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            />
          </Field>
          <Field label="API key">
            <Input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
          </Field>
          <Field label="Models (comma-separated, leave empty for auto-discover)">
            <Input
              value={modelsText}
              placeholder="gpt-4, gpt-3.5-turbo"
              onChange={(e) => setModelsText(e.target.value)}
            />
          </Field>
          <Field label="Note">
            <Input
              value={form.note ?? ""}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
            />
          </Field>

          {create.error && (
            <div className="text-sm text-destructive">
              {String(create.error)}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={
              create.isPending ||
              !form.name ||
              !form.base_url ||
              !form.api_key
            }
          >
            {create.isPending ? "Adding…" : "Add"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  );
}
