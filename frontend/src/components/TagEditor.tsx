import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Icon } from "@/components/atoms";

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
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 4,
        alignItems: "center",
      }}
    >
      {tags.map((t) => (
        <span
          key={t}
          className="badge"
          style={{ paddingRight: 4, gap: 4 }}
        >
          {t}
          <button
            type="button"
            onClick={() => removeTag(t)}
            disabled={setTags.isPending}
            aria-label={`Remove tag ${t}`}
            style={{
              border: "none",
              background: "transparent",
              color: "var(--text-faint)",
              padding: 0,
              cursor: "pointer",
              display: "inline-flex",
            }}
          >
            <Icon name="x" size={10} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            addTag();
          }
        }}
        placeholder="+ tag"
        disabled={setTags.isPending}
        className="input"
        style={{
          width: 76,
          height: 20,
          padding: "0 6px",
          fontSize: 11,
          borderRadius: 4,
        }}
      />
    </div>
  );
}
