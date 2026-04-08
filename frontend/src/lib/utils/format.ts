export function formatProbability(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}

export function formatCurrency(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}

export function truncateHash(hash: string, len = 8): string {
  if (hash.startsWith("sha256:")) return `sha256:${hash.slice(7, 7 + len)}…`;
  return hash.length > len ? `${hash.slice(0, len)}…` : hash;
}

export function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function timeUntil(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "expired";
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  return `${hours}h ${mins}m`;
}

const STATUS_COLORS: Record<string, string> = {
  active: "var(--color-active)",
  resolved: "var(--color-resolved)",
  closed: "var(--color-closed)",
  draft: "var(--color-draft)",
};

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "var(--color-text-muted)";
}
