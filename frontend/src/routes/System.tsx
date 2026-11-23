import { useMemo } from "react";
import { useHealth, useServiceIndex, useMarkets } from "@/lib/query/hooks";
import { isExchangeMode } from "@/lib/exchangeMode";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { formatCurrency } from "@/lib/utils/format";

export default function System() {
  const exchangeMode = isExchangeMode();
  const health = useHealth();
  const index = useServiceIndex();
  const allMarkets = useMarkets();

  const statusCounts = allMarkets.data?.markets.reduce(
    (acc, m) => {
      acc[m.status] = (acc[m.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  ) ?? {};

  const platformStats = useMemo(() => {
    const markets = allMarkets.data?.markets ?? [];
    return {
      totalVolume: markets.reduce((s, m) => s + (m.volume ?? 0), 0),
      totalLiquidity: markets.reduce((s, m) => s + (m.liquidity ?? 0), 0),
    };
  }, [allMarkets.data]);

  const isUp = health.data?.status === "ok";
  const exchangeInfo = health.data?.exchange;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)", minWidth: 0 }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>System Status</h1>

      {/* Health beacon */}
      <div style={cardStyle}>
        {health.error && health.data && <ReconnectingHint />}
        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)" }}>
          <div style={{
            width: 12,
            height: 12,
            borderRadius: "50%",
            background: health.isLoading ? "var(--color-warning, orange)" : isUp ? "var(--color-success)" : "var(--color-danger)",
            boxShadow: isUp ? "0 0 8px var(--color-success)" : undefined,
          }} />
          <span style={{ fontWeight: 600 }}>
            {health.isLoading ? "Checking..." : isUp ? "API Online" : "API Unreachable"}
          </span>
          {health.data && (
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginLeft: "auto" }}>
              {health.data.service} @ {new Date(health.data.timestamp).toLocaleTimeString()}
            </span>
          )}
        </div>
        {exchangeMode && exchangeInfo?.net && (
          <div style={{ marginTop: "var(--space-xs)", fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
            Exchange API · {exchangeInfo.net.markets.toLocaleString("en-US")} net markets ·{" "}
            {exchangeInfo.net.orders.toLocaleString("en-US")} orders
            {typeof exchangeInfo.users === "number" ? ` · ${exchangeInfo.users.toLocaleString("en-US")} traders` : ""}
          </div>
        )}
        {health.isError && !health.data && (
          <div style={{ marginTop: "var(--space-sm)", fontSize: "0.8rem", color: "var(--color-danger)" }}>
            {health.error instanceof Error ? health.error.message : "Connection failed"}
          </div>
        )}
      </div>

      {/* Platform aggregate stats (no duplicate Active/Resolved cards) */}
      {!allMarkets.isLoading && allMarkets.data && (
        <div style={cardStyle}>
          <h2 style={sectionTitle}>Platform Stats</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "var(--space-sm)" }}>
            <CountCard
              label="Total Volume"
              value={exchangeMode ? `${formatCurrency(platformStats.totalVolume)} credits` : formatCurrency(platformStats.totalVolume)}
              raw
            />
            <CountCard
              label="Total Liquidity"
              value={exchangeMode ? `${formatCurrency(platformStats.totalLiquidity)} credits` : formatCurrency(platformStats.totalLiquidity)}
              raw
            />
            {exchangeMode && exchangeInfo?.net && (
              <CountCard label="Net Orders" value={exchangeInfo.net.orders.toLocaleString("en-US")} raw />
            )}
            {exchangeMode && typeof exchangeInfo?.users === "number" && (
              <CountCard label="Traders" value={exchangeInfo.users.toLocaleString("en-US")} raw />
            )}
          </div>
        </div>
      )}

      {/* Market counts by status */}
      <div style={cardStyle}>
        <h2 style={sectionTitle}>Markets</h2>
        {allMarkets.error && allMarkets.data && <ReconnectingHint />}
        {allMarkets.error && !allMarkets.data ? (
          <ErrorMessage message="Could not load market statistics." />
        ) : allMarkets.isLoading ? (
          <LoadingPage />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: "var(--space-sm)" }}>
            <CountCard label="Total" value={allMarkets.data?.markets.length ?? 0} />
            <CountCard label="Active" value={statusCounts["active"] ?? 0} color="var(--color-success)" />
            <CountCard label="Resolved" value={statusCounts["resolved"] ?? 0} color="var(--color-primary)" />
            <CountCard label="Closed" value={statusCounts["closed"] ?? 0} />
            <CountCard label="Draft" value={statusCounts["draft"] ?? 0} />
          </div>
        )}
      </div>

      {/* API info */}
      {index.error && !index.data && <ErrorMessage message="Could not load the API surface." />}
      {index.data && (
        <div style={cardStyle}>
          {index.error && <ReconnectingHint />}
          <h2 style={sectionTitle}>API Surface</h2>
          <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-sm)" }}>
            Version: {index.data.meta.apiVersion}
          </div>
          <div style={{ display: "grid", gap: "var(--space-sm)" }}>
            {Object.entries(index.data.routes).map(([group, routes]) => (
              <div key={group}>
                <div style={{ fontSize: "0.8rem", fontWeight: 600, textTransform: "capitalize", marginBottom: 2 }}>
                  {group}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {routes.map((r) => (
                    <span key={r} style={routeTagStyle}>{r}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CountCard({ label, value, color, raw }: { label: string; value: number | string; color?: string; raw?: boolean }) {
  return (
    <div style={{
      padding: "var(--space-sm)",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--color-border)",
      background: "var(--color-bg)",
      textAlign: "center",
    }}>
      <div style={{ fontSize: raw ? "1.1rem" : "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)", color: color ?? "var(--color-text)" }}>
        {value}
      </div>
      <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>{label}</div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  minWidth: 0,
};

const sectionTitle: React.CSSProperties = {
  fontSize: "1rem",
  fontWeight: 600,
  marginBottom: "var(--space-sm)",
};

const routeTagStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: 4,
  background: "var(--color-bg)",
  border: "1px solid var(--color-border)",
  fontSize: "0.7rem",
  fontFamily: "var(--font-mono)",
};
