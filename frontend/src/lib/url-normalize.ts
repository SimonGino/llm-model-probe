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
