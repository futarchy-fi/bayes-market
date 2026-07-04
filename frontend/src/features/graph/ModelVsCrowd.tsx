import type { MarketSummary } from "@/lib/api/types";
import {
  topAnchorGaps,
  topFtmGaps,
  hasModelVsCrowdData,
  formatPct,
  formatGap,
  truncateTitle,
  type ModelVsCrowdRow,
} from "./modelVsCrowd";

// ---------------------------------------------------------------------------
// Compact, chrome-free comparison of the crowd's current price against two
// independent references: external forecasts (Metaculus/Manifold, tagged
// M/F) anchored to a market, and the futarchy team's own model-implied
// prior (ftmImplied, tagged FTM). Renders nothing when the market set
// carries neither field yet.
// ---------------------------------------------------------------------------

function ModelVsCrowdRowLine({ row }: { row: ModelVsCrowdRow }) {
  const gap = formatGap(row.gapPts);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        padding: "3px 0",
        borderTop: "1px solid var(--color-border)",
      }}
    >
      <span
        title={row.title}
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontSize: "0.72rem",
          color: "var(--color-text)",
        }}
      >
        {truncateTitle(row.title)}
      </span>
      <span
        style={{
          fontSize: "0.72rem",
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
          color: "var(--color-text)",
          minWidth: 40,
          textAlign: "right",
        }}
      >
        {formatPct(row.priceP)}
      </span>
      <span
        style={{
          fontSize: "0.68rem",
          color: "var(--color-text-muted)",
          fontVariantNumeric: "tabular-nums",
          minWidth: 56,
          textAlign: "right",
        }}
      >
        {row.referenceTag} {formatPct(row.referenceP)}
      </span>
      <span
        style={{
          fontSize: "0.72rem",
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
          minWidth: 40,
          textAlign: "right",
          color: row.gapPts >= 0 ? "var(--color-success)" : "var(--color-danger)",
        }}
      >
        {gap.symbol}
        {gap.magnitude}
      </span>
    </div>
  );
}

function ModelVsCrowdColumn({ heading, rows }: { heading: string; rows: ModelVsCrowdRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div style={{ flex: 1, minWidth: 220 }}>
      <div
        style={{
          fontSize: "0.68rem",
          color: "var(--color-text-muted)",
          marginBottom: 4,
          textTransform: "uppercase",
          letterSpacing: "0.03em",
        }}
      >
        {heading}
      </div>
      {rows.map((r) => (
        <ModelVsCrowdRowLine key={r.id} row={r} />
      ))}
    </div>
  );
}

export function ModelVsCrowd({ markets }: { markets: MarketSummary[] }) {
  if (!hasModelVsCrowdData(markets)) return null;

  const anchorRows = topAnchorGaps(markets);
  const ftmRows = topFtmGaps(markets);
  if (anchorRows.length === 0 && ftmRows.length === 0) return null;

  return (
    <div style={panelStyle}>
      <h3 style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Model vs. crowd</h3>
      <div style={{ display: "flex", gap: "var(--space-lg)", flexWrap: "wrap" }}>
        <ModelVsCrowdColumn heading="Biggest gaps vs. external forecasts" rows={anchorRows} />
        <ModelVsCrowdColumn heading="Biggest gaps vs. model prior" rows={ftmRows} />
      </div>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};
