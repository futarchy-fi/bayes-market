import type { AnalyticsInterval, MarketAnalyticsSeries } from "@/lib/api/types";
import { formatProbability } from "@/lib/utils/format";
import {
  buildLinePath,
  formatTimestampLabel,
  getOutcomeColor,
  scaleNumber,
} from "./chartUtils";

interface PriceChartProps {
  series: MarketAnalyticsSeries[];
  interval: AnalyticsInterval;
}

const WIDTH = 760;
const HEIGHT = 320;
const MARGIN = { top: 24, right: 24, bottom: 48, left: 52 };

export function PriceChart({ series, interval }: PriceChartProps) {
  const timestamps = series
    .flatMap((outcome) => outcome.points.map((point) => Date.parse(point.emittedAt)))
    .filter((value) => Number.isFinite(value));
  const domainStart = timestamps.length > 0 ? Math.min(...timestamps) : Date.now();
  const domainEnd = timestamps.length > 1 ? Math.max(...timestamps) : domainStart + 1;
  const chartLeft = MARGIN.left;
  const chartRight = WIDTH - MARGIN.right;
  const chartTop = MARGIN.top;
  const chartBottom = HEIGHT - MARGIN.bottom;
  const xTickCount = timestamps.length > 1 ? Math.min(4, timestamps.length) : 1;
  const xTicks = Array.from({ length: xTickCount }, (_, index) => {
    if (xTickCount === 1) {
      return domainStart;
    }

    return domainStart + ((domainEnd - domainStart) * index) / (xTickCount - 1);
  });

  return (
    <section style={cardStyle}>
      <div style={headerStyle}>
        <div>
          <h2 style={titleStyle}>Probability History</h2>
          <p style={subtitleStyle}>
            Accepted unconditional prices only. Event trades and contextual edits
            stay out of the line series.
          </p>
        </div>
        <div style={legendStyle}>
          {series.map((outcome, index) => (
            <span key={outcome.outcomeId} style={legendItemStyle}>
              <span
                style={{
                  ...legendDotStyle,
                  background: getOutcomeColor(index),
                }}
              />
              {outcome.outcomeName}
            </span>
          ))}
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <svg
          data-testid="price-chart"
          role="img"
          aria-label="Probability history chart"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: "auto", minWidth: 460 }}
        >
          {[1, 0.75, 0.5, 0.25, 0].map((value) => {
            const y = scaleNumber(value, 0, 1, chartBottom, chartTop);
            return (
              <g key={value}>
                <line
                  x1={chartLeft}
                  y1={y}
                  x2={chartRight}
                  y2={y}
                  stroke="rgba(139, 143, 163, 0.28)"
                  strokeDasharray="4 4"
                />
                <text
                  x={chartLeft - 10}
                  y={y + 4}
                  fill="var(--color-text-muted)"
                  fontSize="11"
                  textAnchor="end"
                >
                  {formatProbability(value)}
                </text>
              </g>
            );
          })}

          {xTicks.map((tick) => {
            const x = scaleNumber(tick, domainStart, domainEnd, chartLeft, chartRight);
            return (
              <g key={tick}>
                <line
                  x1={x}
                  y1={chartTop}
                  x2={x}
                  y2={chartBottom}
                  stroke="rgba(139, 143, 163, 0.16)"
                />
                <text
                  x={x}
                  y={HEIGHT - 14}
                  fill="var(--color-text-muted)"
                  fontSize="11"
                  textAnchor="middle"
                >
                  {formatTimestampLabel(new Date(tick).toISOString(), interval)}
                </text>
              </g>
            );
          })}

          <line
            x1={chartLeft}
            y1={chartBottom}
            x2={chartRight}
            y2={chartBottom}
            stroke="var(--color-border)"
          />
          <line
            x1={chartLeft}
            y1={chartTop}
            x2={chartLeft}
            y2={chartBottom}
            stroke="var(--color-border)"
          />

          {series.map((outcome, outcomeIndex) => {
            const points = outcome.points.map((point) => ({
              x: scaleNumber(
                Date.parse(point.emittedAt),
                domainStart,
                domainEnd,
                chartLeft,
                chartRight,
              ),
              y: scaleNumber(point.probability, 0, 1, chartBottom, chartTop),
            }));
            const color = getOutcomeColor(outcomeIndex);

            return (
              <g key={outcome.outcomeId}>
                {points.length > 1 && (
                  <path
                    d={buildLinePath(points)}
                    fill="none"
                    stroke={color}
                    strokeWidth="3"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                )}
                {points.map((point, pointIndex) => (
                  <circle
                    key={`${outcome.outcomeId}-${pointIndex}`}
                    cx={point.x}
                    cy={point.y}
                    r="4"
                    fill={color}
                    stroke="var(--color-bg-surface)"
                    strokeWidth="2"
                  />
                ))}
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

const cardStyle: React.CSSProperties = {
  padding: "var(--space-lg)",
  borderRadius: "var(--radius-lg)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "var(--space-md)",
  flexWrap: "wrap",
  marginBottom: "var(--space-md)",
};

const titleStyle: React.CSSProperties = {
  fontSize: "1.05rem",
  fontWeight: 600,
};

const subtitleStyle: React.CSSProperties = {
  marginTop: "var(--space-xs)",
  fontSize: "0.8rem",
  color: "var(--color-text-muted)",
  maxWidth: 560,
};

const legendStyle: React.CSSProperties = {
  display: "flex",
  gap: "var(--space-sm)",
  alignItems: "center",
  flexWrap: "wrap",
};

const legendItemStyle: React.CSSProperties = {
  display: "inline-flex",
  gap: "6px",
  alignItems: "center",
  fontSize: "0.8rem",
  color: "var(--color-text-muted)",
};

const legendDotStyle: React.CSSProperties = {
  width: 10,
  height: 10,
  borderRadius: "50%",
};
