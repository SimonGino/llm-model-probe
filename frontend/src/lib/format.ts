export function relative(when: string | null): string {
  if (!when) return "never";
  const seconds = Math.floor((Date.now() - new Date(when).getTime()) / 1000);
  if (seconds < 30) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}
