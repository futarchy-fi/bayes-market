import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface VolumeChartProps {
  totalVolume: number;
  tradeCount: number;
}

export function VolumeChart({ totalVolume, tradeCount }: VolumeChartProps) {
  const data = [
    { name: "Volume", value: totalVolume },
    { name: "Trades", value: tradeCount },
  ];

  return (
    <div>
      <div style={metricsStyle}>
        <div style={metricStyle}>
          <div style={metricLabelStyle}>Total Volume</div>
          <div style={metricValueStyle}>{totalVolume.toLocaleString()}</div>
        </div>
        <div style={metricStyle}>
          <div style={metricLabelStyle}>Trade Count</div>
          <div style={metricValueStyle}>{tradeCount.toLocaleString()}</div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="name"
            tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
            stroke="var(--color-border)"
          />
          <YAxis
            tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
            stroke="var(--color-border)"
            width={50}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-bg-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.75rem",
            }}
          />
          <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const metricsStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "var(--space-md)",
  marginBottom: "var(--space-sm)",
};

const metricStyle: React.CSSProperties = {
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-bg-hover)",
};

const metricLabelStyle: React.CSSProperties = {
  fontSize: "0.7rem",
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-xs)",
};

const metricValueStyle: React.CSSProperties = {
  fontSize: "1.1rem",
  fontWeight: 600,
  fontFamily: "var(--font-mono)",
};
