import { useState } from "react";
import { Link } from "react-router-dom";
import { useMarkets } from "@/lib/query/hooks";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { formatCurrency, timeUntil } from "@/lib/utils/format";
import type { MarketSortField } from "@/lib/api/types";

const STATUSES = ["", "active", "resolved", "closed", "draft"] as const;
type StatusFilter = (typeof STATUSES)[number];

const SORT_OPTIONS: Array<{ value: MarketSortField | ""; label: string }> = [
  { value: "", label: "Default order" },
  { value: "volume", label: "Volume (high to low)" },
  { value: "liquidity", label: "Liquidity (high to low)" },
  { value: "created", label: "Newest first" },
];

export default function MarketList() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [sortField, setSortField] = useState<MarketSortField | "">("");
  const [searchQuery, setSearchQuery] = useState("");

  const marketFilters = {
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(sortField ? { sort: sortField } : {}),
    ...(searchQuery.trim() ? { q: searchQuery.trim() } : {}),
  };
  const hasFilters = Object.keys(marketFilters).length > 0;
  const { data, isLoading, error } = useMarkets(hasFilters ? marketFilters : undefined);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-lg)" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Markets</h1>
        <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center" }}>
          <input
            type="text"
            placeholder="Search markets..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              background: "var(--color-bg-surface)",
              color: "var(--color-text)",
              fontSize: "0.875rem",
              width: "180px",
            }}
          />
          <select
            aria-label="Sort by"
            value={sortField}
            onChange={(e) => setSortField(e.target.value as MarketSortField | "")}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              background: "var(--color-bg-surface)",
              color: "var(--color-text)",
              fontSize: "0.875rem",
            }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
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
          <Link
            to="/markets/new"
            style={{
              padding: "6px 14px",
              borderRadius: "var(--radius-sm)",
              background: "var(--color-primary)",
              color: "#fff",
              fontSize: "0.875rem",
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            + New Market
          </Link>
        </div>
      </div>

      {isLoading && <LoadingPage />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load markets"} />}

      {data && data.markets.length > 0 && (
        <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>
          <span>{data.markets.length} market{data.markets.length !== 1 ? "s" : ""}</span>
          <span>Total Volume: {formatCurrency(data.markets.reduce((s, m) => s + m.volume, 0))}</span>
          <span>Total Liquidity: {formatCurrency(data.markets.reduce((s, m) => s + m.liquidity, 0))}</span>
        </div>
      )}

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
