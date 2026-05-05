export function relative(when: string | null): string {
  if (!when) return "never";
  const seconds = Math.floor((Date.now() - new Date(when).getTime()) / 1000);
  if (seconds < 30) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export type FreshnessTone = "fresh" | "ok" | "old" | "stale";

export function freshnessTone(when: string | null): FreshnessTone {
  if (!when) return "stale";
  const ms = Date.now() - new Date(when).getTime();
  const h = ms / 3_600_000;
  if (h < 1) return "fresh";
  if (h < 24) return "ok";
  if (h < 168) return "old";
  return "stale";
}
