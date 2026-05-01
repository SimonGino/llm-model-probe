import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { parseLocally } from "@/lib/parsePaste";
import type { EndpointCreate } from "@/lib/types";

export default function SmartPasteArea({
  onApply,
}: {
  onApply: (suggestion: Partial<EndpointCreate>) => void;
}) {
  const [text, setText] = useState("");
  const [parser, setParser] = useState<string>("");
  const [confidence, setConfidence] = useState<number>(0);
  const [suggested, setSuggested] = useState<Partial<EndpointCreate>>({});
  const [busy, setBusy] = useState(false);

  async function reparse(value: string) {
    if (!value.trim()) {
      setParser("");
      setConfidence(0);
      setSuggested({});
      return;
    }
    const local = parseLocally(value);
    if (local.confidence >= 0.5) {
      const { confidence: c, parser: p, ...rest } = local;
      setParser(p);
      setConfidence(c);
      setSuggested(rest);
      return;
    }
    setBusy(true);
    try {
      const remote = await api.parsePaste(value);
      setParser(remote.parser);
      setConfidence(remote.confidence);
      setSuggested(remote.suggested);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border rounded-md p-3 bg-muted/30">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Smart paste</span>
        {parser && (
          <Badge variant={confidence >= 0.9 ? "default" : "secondary"}>
            {parser}
            {busy && "…"}
          </Badge>
        )}
      </div>
      <Textarea
        rows={5}
        placeholder={
          'Paste a JSON like {"base_url":"...","api_key":"..."}\n' +
          "or dotenv: OPENAI_BASE_URL=...\nOPENAI_API_KEY=...\n" +
          "or a curl command with Authorization: Bearer ..."
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => reparse(text)}
      />
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={!parser || parser === "none"}
          onClick={() => onApply(suggested)}
        >
          Apply to form
        </Button>
      </div>
    </div>
  );
}
