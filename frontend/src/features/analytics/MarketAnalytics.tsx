import { useState } from "react";
import { useMarketAnalytics } from "@/lib/query/hooks";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { PriceHistoryChart } from "./PriceHistoryChart";
import { VolumeChart } from "./VolumeChart";

interface MarketAnalyticsProps {
  marketId: string;
}

export function MarketAnalytics({ marketId }: MarketAnalyticsProps) {
  const [expanded, setExpanded] = useState(false);
  const [interval, setInterval] = useState("1h");
  const { data, isLoading, error } = useMarketAnalytics(marketId, { interval });

  return (
    <section style={sectionStyle}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={toggleStyle}
      >
        <span style={{ fontSize: "0.65rem", marginRight: 6 }}>
          {expanded ? "\u25BC" : "\u25B6"}
        </span>
        Market Analytics
      </button>

      {expanded && (
        <div style={{ marginTop: "var(--space-sm)" }}>
          {isLoading && <LoadingPage />}
          {error && (
            <ErrorMessage
              message={error instanceof Error ? error.message : "Failed to load analytics"}
            />
          )}
          {data && (
            <div style={{ display: "grid", gap: "var(--space-md)" }}>
              <div>
                <h3 style={subheadingStyle}>Price History</h3>
                <PriceHistoryChart
                  priceHistory={data.price_history}
                  outcomes={Object.keys(
                    data.price_history[0]?.marginals ?? {},
                  )}
                  interval={interval}
                  onIntervalChange={setInterval}
                />
              </div>
              <div>
                <h3 style={subheadingStyle}>Volume</h3>
                <VolumeChart
                  totalVolume={data.total_volume}
                  tradeCount={data.trade_count}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const sectionStyle: React.CSSProperties = {
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const toggleStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--color-text)",
  cursor: "pointer",
  fontSize: "1.1rem",
  fontWeight: 600,
  padding: 0,
  textAlign: "left",
  width: "100%",
};

const subheadingStyle: React.CSSProperties = {
  fontSize: "0.85rem",
  fontWeight: 600,
  marginBottom: "var(--space-xs)",
};
