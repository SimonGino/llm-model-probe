import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export default function TagEditor({
  endpointId,
  tags,
}: {
  endpointId: string;
  tags: string[];
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");

  const setTags = useMutation({
    mutationFn: (next: string[]) => api.setTags(endpointId, next),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["endpoint", endpointId] });
      qc.invalidateQueries({ queryKey: ["endpoints"] });
    },
  });

  function addTag() {
    const t = draft.trim();
    if (!t) return;
    if (tags.includes(t)) {
      setDraft("");
      return;
    }
    setTags.mutate([...tags, t]);
    setDraft("");
  }

  function removeTag(t: string) {
    setTags.mutate(tags.filter((x) => x !== t));
  }

  return (
    <div className="flex flex-wrap gap-1 items-center">
      {tags.map((t) => (
        <Badge key={t} variant="secondary" className="text-xs gap-1 pr-1">
          <span>{t}</span>
          <button
            type="button"
            onClick={() => removeTag(t)}
            className="text-muted-foreground hover:text-destructive ml-1"
            aria-label={`Remove tag ${t}`}
          >
            ✕
          </button>
        </Badge>
      ))}
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            addTag();
          }
        }}
        placeholder="+ tag"
        className="h-6 text-xs w-24 inline-block"
        disabled={setTags.isPending}
      />
    </div>
  );
}
