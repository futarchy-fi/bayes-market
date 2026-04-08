import { useState } from "react";
import { Link } from "react-router-dom";
import { useMarkets } from "@/lib/query/hooks";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { formatCurrency, timeUntil } from "@/lib/utils/format";

const STATUSES = ["", "active", "resolved", "closed", "draft"] as const;

export default function MarketList() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading, error } = useMarkets(statusFilter || undefined);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-lg)" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Markets</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            padding: "6px 12px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--color-border)",
            background: "var(--color-bg-surface)",
            color: "var(--color-text)",
            fontSize: "0.875rem",
          }}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s || "All statuses"}</option>
          ))}
        </select>
      </div>

      {isLoading && <LoadingPage />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load markets"} />}

      {data && (
        <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>
          {data.markets.map((m) => (
            <Link
              key={m.id}
              to={`/markets/${m.id}`}
              style={{
                display: "block",
                padding: "var(--space-md)",
                borderRadius: "var(--radius-md)",
                background: "var(--color-bg-surface)",
                border: "1px solid var(--color-border)",
                textDecoration: "none",
                color: "inherit",
                transition: "border-color 0.15s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--color-primary)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--color-border)")}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "var(--space-sm)" }}>
                <span style={{ fontWeight: 500, fontSize: "0.95rem" }}>{m.title}</span>
                <StatusBadge status={m.status} />
              </div>
              <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-sm)" }}>
                <span>Vol {formatCurrency(m.volume)}</span>
                <span>Liq {formatCurrency(m.liquidity)}</span>
                <span>{timeUntil(m.expires_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {data && data.markets.length === 0 && (
        <div style={{ textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" }}>
          No markets found.
        </div>
      )}
    </div>
  );
}
