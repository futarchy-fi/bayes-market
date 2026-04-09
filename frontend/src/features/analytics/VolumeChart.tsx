import type {
  AnalyticsInterval,
  MarketAnalyticsVolumeBucket,
} from "@/lib/api/types";
import { formatCurrency } from "@/lib/utils/format";
import { formatBucketRangeLabel, scaleNumber } from "./chartUtils";

interface VolumeChartProps {
  buckets: MarketAnalyticsVolumeBucket[];
  interval: AnalyticsInterval;
}

const WIDTH = 760;
const HEIGHT = 280;
const MARGIN = { top: 24, right: 24, bottom: 54, left: 52 };

export function VolumeChart({ buckets, interval }: VolumeChartProps) {
  const values = buckets.map((bucket) => bucket.volume);
  const maxVolume = values.length > 0 ? Math.max(...values) : 1;
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const chartBottom = HEIGHT - MARGIN.bottom;
  const chartTop = MARGIN.top;
  const labelEvery = Math.max(1, Math.ceil(buckets.length / 5));
  const barWidth = Math.min(
    88,
    Math.max(30, innerWidth / Math.max(buckets.length * 1.4, 1)),
  );
  const midpoints = buckets.map((bucket) => {
    const start = Date.parse(bucket.bucketStart);
    const end = Date.parse(bucket.bucketEnd);
    return start + (end - start) / 2;
  });
  const domainStart = midpoints.length > 0 ? Math.min(...midpoints) : Date.now();
  const domainEnd = midpoints.length > 1 ? Math.max(...midpoints) : domainStart + 1;

  return (
    <section style={cardStyle}>
      <div style={headerStyle}>
        <div>
          <h2 style={titleStyle}>Activity Volume</h2>
          <p style={subtitleStyle}>
            Accepted trade and edit volume grouped into sparse UTC buckets.
          </p>
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <svg
          data-testid="volume-chart"
          role="img"
          aria-label="Activity volume chart"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: "auto", minWidth: 460 }}
        >
          {[0, 0.5, 1].map((ratio) => {
            const y = scaleNumber(ratio, 0, 1, chartBottom, chartTop);
            const value = maxVolume * ratio;
            return (
              <g key={ratio}>
                <line
                  x1={MARGIN.left}
                  y1={y}
                  x2={WIDTH - MARGIN.right}
                  y2={y}
                  stroke="rgba(139, 143, 163, 0.28)"
                  strokeDasharray="4 4"
                />
                <text
                  x={MARGIN.left - 10}
                  y={y + 4}
                  fill="var(--color-text-muted)"
                  fontSize="11"
                  textAnchor="end"
                >
                  {formatCurrency(value)}
                </text>
              </g>
            );
          })}

          <line
            x1={MARGIN.left}
            y1={chartBottom}
            x2={WIDTH - MARGIN.right}
            y2={chartBottom}
            stroke="var(--color-border)"
          />
          <line
            x1={MARGIN.left}
            y1={chartTop}
            x2={MARGIN.left}
            y2={chartBottom}
            stroke="var(--color-border)"
          />

          {buckets.map((bucket, index) => {
            const midpoint = midpoints[index] ?? domainStart;
            const xCenter =
              buckets.length === 1
                ? MARGIN.left + innerWidth / 2
                : scaleNumber(
                    midpoint,
                    domainStart,
                    domainEnd,
                    MARGIN.left + barWidth / 2,
                    WIDTH - MARGIN.right - barWidth / 2,
                  );
            const barHeight = scaleNumber(
              bucket.volume,
              0,
              maxVolume || 1,
              0,
              chartBottom - chartTop,
            );
            const x = xCenter - barWidth / 2;
            const y = chartBottom - barHeight;
            const showLabel = index % labelEvery === 0;

            return (
              <g key={`${bucket.bucketStart}-${bucket.bucketEnd}`}>
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={barHeight}
                  rx="8"
                  fill="rgba(99, 102, 241, 0.75)"
                />
                <text
                  x={xCenter}
                  y={y - 8}
                  fill="var(--color-text)"
                  fontSize="11"
                  textAnchor="middle"
                >
                  {bucket.tradeCount}
                </text>
                {showLabel && (
                  <text
                    x={xCenter}
                    y={HEIGHT - 20}
                    fill="var(--color-text-muted)"
                    fontSize="11"
                    textAnchor="middle"
                  >
                    {formatBucketRangeLabel(
                      bucket.bucketStart,
                      bucket.bucketEnd,
                      interval,
                    )}
                  </text>
                )}
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
  maxWidth: 480,
};
