import { useParams } from "react-router-dom";
import { useMarket, useMarketEvents, useEngineStats } from "@/lib/query/hooks";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ProbabilityBar } from "@/components/ui/ProbabilityBar";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { formatCurrency, timeUntil, truncateHash, formatRelativeTime } from "@/lib/utils/format";
import { TradingPanel } from "@/features/trading/TradingPanel";
import { useState } from "react";

export default function MarketDetail() {
  const { marketId } = useParams<{ marketId: string }>();
  const { data, isLoading, error } = useMarket(marketId!);
  const events = useMarketEvents(marketId!);
  const engine = useEngineStats(marketId!);
  const [showEngine, setShowEngine] = useState(false);

  if (isLoading) return <LoadingPage />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Market not found"} />;
  if (!data) return null;

  const m = data.market;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <div>
        <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "center", marginBottom: "var(--space-sm)" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>{m.title}</h1>
          <StatusBadge status={m.status} />
        </div>
        <p style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>{m.description}</p>
        <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
          <span>Volume: {formatCurrency(m.volume)}</span>
          <span>Liquidity: {formatCurrency(m.liquidity)}</span>
          <span>Expires: {timeUntil(m.expires_at)}</span>
        </div>
      </div>

      <ProbabilityBar outcomes={m.outcomes} marginals={m.marginals} />

      {m.status === "active" && <TradingPanel market={m} />}

      {/* Event Journal */}
      <div>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Event Journal</h2>
        {events.isLoading && <LoadingPage />}
        {events.data && events.data.events.length === 0 && (
          <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>No events yet.</span>
        )}
        {events.data && events.data.events.length > 0 && (
          <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ background: "var(--color-bg-hover)" }}>
                  <th style={thStyle}>Seq</th>
                  <th style={thStyle}>Type</th>
                  <th style={thStyle}>Hash</th>
                  <th style={thStyle}>Time</th>
                </tr>
              </thead>
              <tbody>
                {events.data.events.map((e) => (
                  <tr key={e.eventId} style={{ borderTop: "1px solid var(--color-border)" }}>
                    <td style={tdStyle}>{e.seq}</td>
                    <td style={tdStyle}>{e.type}</td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                      {truncateHash(e.eventHash)}
                    </td>
                    <td style={tdStyle}>{formatRelativeTime(e.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Engine Stats */}
      <div>
        <button
          onClick={() => setShowEngine(!showEngine)}
          style={{
            background: "none",
            border: "none",
            color: "var(--color-primary)",
            cursor: "pointer",
            fontSize: "0.9rem",
            padding: 0,
          }}
        >
          {showEngine ? "▾" : "▸"} Engine Stats
        </button>
        {showEngine && engine.data && (
          <div style={{
            marginTop: "var(--space-sm)",
            padding: "var(--space-md)",
            background: "var(--color-bg-surface)",
            borderRadius: "var(--radius-md)",
            fontSize: "0.8rem",
            fontFamily: "var(--font-mono)",
          }}>
            <div>Mode: {engine.data.engine.mode} | Backend: {engine.data.engine.backend} | v{engine.data.engine.version}</div>
            <div>Junction tree width: {engine.data.cliques.junction_tree_width} (max clique size - 1)</div>
            <div>Requests: {engine.data.diagnostics.request_count} | Errors: {engine.data.diagnostics.error_count}</div>
            <div>Cache: {engine.data.diagnostics.cache.hits} hits / {engine.data.diagnostics.cache.misses} misses ({(engine.data.diagnostics.cache.hit_rate * 100).toFixed(1)}%)</div>
            {engine.data.diagnostics.inference.sample_count > 0 && (
              <div>Latency: p50={engine.data.diagnostics.inference.p50_ms.toFixed(1)}ms p95={engine.data.diagnostics.inference.p95_ms.toFixed(1)}ms p99={engine.data.diagnostics.inference.p99_ms.toFixed(1)}ms</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "6px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "6px 12px" };
