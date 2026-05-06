import { Input } from "@/components/ui/input";

// Keep in sync with _STRIP_SUFFIXES in src/llm_model_probe/api.py
const STRIP_SUFFIXES = [
  "/v1/messages",
  "/chat/completions",
  "/messages",
  "/completions",
];

export function normalizeBaseUrl(url: string): string {
  let s = url.replace(/\/+$/, "");
  const lower = s.toLowerCase();
  for (const suffix of STRIP_SUFFIXES) {
    if (lower.endsWith(suffix)) {
      s = s.slice(0, -suffix.length);
      break;
    }
  }
  return s.replace(/\/+$/, "");
}

export default function BaseUrlInput({
  value,
  onChange,
  placeholder = "https://api.example.com/v1",
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  id?: string;
}) {
  const trimmed = value.trim();
  const suggestion = trimmed ? normalizeBaseUrl(trimmed) : "";
  const canSuggest =
    trimmed.length > 0 && suggestion.length > 0 && suggestion !== trimmed;

  return (
    <div className="space-y-1">
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {canSuggest && (
        <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
          <span>
            检测到完整接口 URL，建议改成{" "}
            <code className="bg-muted px-1 rounded">{suggestion}</code>
          </span>
          <button
            type="button"
            title={`使用建议的 URL: ${suggestion}`}
            aria-label={`使用建议的 URL: ${suggestion}`}
            onClick={() => onChange(suggestion)}
            className="text-primary hover:underline"
          >
            采用
          </button>
        </div>
      )}
    </div>
  );
}
