import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { AnalyticsInterval, MarketSummary } from "@/lib/api/types";
import { formatCurrency, timeUntil } from "@/lib/utils/format";

const INTERVAL_OPTIONS: AnalyticsInterval[] = ["day", "hour"];

interface AnalyticsFiltersProps {
  markets: MarketSummary[];
  selectedMarketId: string;
  interval: AnalyticsInterval;
  selectedMarket?: MarketSummary;
  onMarketChange: (marketId: string) => void;
  onIntervalChange: (interval: AnalyticsInterval) => void;
}

export function AnalyticsFilters({
  markets,
  selectedMarketId,
  interval,
  selectedMarket,
  onMarketChange,
  onIntervalChange,
}: AnalyticsFiltersProps) {
  return (
    <section style={cardStyle}>
      <div style={{ display: "grid", gap: "var(--space-md)" }}>
        <div style={headerRowStyle}>
          <div style={{ display: "grid", gap: "var(--space-xs)" }}>
            <div style={eyebrowStyle}>Selected Market</div>
            <div
              style={{
                display: "flex",
                gap: "var(--space-sm)",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <h2 style={{ fontSize: "1.2rem", fontWeight: 600 }}>
                {selectedMarket?.title ?? "Choose a market"}
              </h2>
              {selectedMarket && <StatusBadge status={selectedMarket.status} />}
            </div>
            {selectedMarket && (
              <div style={metaRowStyle}>
                <span>Liquidity {formatCurrency(selectedMarket.liquidity)}</span>
                <span>Volume {formatCurrency(selectedMarket.volume)}</span>
                <span>Expires {timeUntil(selectedMarket.expires_at)}</span>
              </div>
            )}
          </div>
          {selectedMarket && (
            <Link to={`/markets/${selectedMarket.id}`} style={actionLinkStyle}>
              Open Market
            </Link>
          )}
        </div>

        <div
          style={{
            display: "flex",
            gap: "var(--space-md)",
            alignItems: "end",
            flexWrap: "wrap",
          }}
        >
          <label style={fieldStyle}>
            <span style={labelStyle}>Market</span>
            <select
              aria-label="Market"
              data-testid="market-select"
              value={selectedMarketId}
              onChange={(event) => onMarketChange(event.target.value)}
              style={selectStyle}
            >
              {markets.map((market) => (
                <option key={market.id} value={market.id}>
                  {market.title}
                </option>
              ))}
            </select>
          </label>

          <div style={fieldStyle}>
            <span style={labelStyle}>Interval</span>
            <div style={{ display: "flex", gap: "var(--space-sm)", flexWrap: "wrap" }}>
              {INTERVAL_OPTIONS.map((option) => {
                const active = option === interval;
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => onIntervalChange(option)}
                    style={{
                      ...intervalButtonStyle,
                      borderColor: active ? "var(--color-primary)" : "var(--color-border)",
                      background: active ? "rgba(99, 102, 241, 0.18)" : "var(--color-bg)",
                      color: active ? "var(--color-text)" : "var(--color-text-muted)",
                    }}
                  >
                    {option === "day" ? "Day" : "Hour"}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

const cardStyle: React.CSSProperties = {
  padding: "var(--space-lg)",
  borderRadius: "var(--radius-lg)",
  border: "1px solid var(--color-border)",
  background:
    "linear-gradient(180deg, rgba(99, 102, 241, 0.08), rgba(15, 17, 23, 0.9))",
};

const headerRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "start",
  gap: "var(--space-md)",
  flexWrap: "wrap",
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-muted)",
};

const metaRowStyle: React.CSSProperties = {
  display: "flex",
  gap: "var(--space-md)",
  flexWrap: "wrap",
  fontSize: "0.82rem",
  color: "var(--color-text-muted)",
};

const actionLinkStyle: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "rgba(15, 17, 23, 0.75)",
  color: "var(--color-text)",
  fontSize: "0.85rem",
  fontWeight: 600,
};

const fieldStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-xs)",
  minWidth: 220,
};

const labelStyle: React.CSSProperties = {
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-muted)",
};

const selectStyle: React.CSSProperties = {
  padding: "10px 12px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "rgba(15, 17, 23, 0.92)",
  color: "var(--color-text)",
  fontSize: "0.9rem",
};

const intervalButtonStyle: React.CSSProperties = {
  padding: "10px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text-muted)",
  fontSize: "0.84rem",
  fontWeight: 600,
  cursor: "pointer",
};
