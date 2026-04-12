import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { PriceHistoryEntry } from "@/lib/api/types";

const OUTCOME_COLORS = [
  "#6366f1",
  "#22c55e",
  "#eab308",
  "#ef4444",
  "#06b6d4",
  "#f97316",
  "#a855f7",
  "#ec4899",
];

const INTERVALS = ["1h", "6h", "1d", "7d"] as const;

interface PriceHistoryChartProps {
  priceHistory: PriceHistoryEntry[];
  outcomes: string[];
  interval?: string;
  onIntervalChange?: (interval: string) => void;
}

export function PriceHistoryChart({
  priceHistory,
  outcomes,
  interval = "1h",
  onIntervalChange,
}: PriceHistoryChartProps) {
  const [selectedInterval, setSelectedInterval] = useState(interval);

  const handleIntervalChange = (iv: string) => {
    setSelectedInterval(iv);
    onIntervalChange?.(iv);
  };

  const chartData = useMemo(
    () =>
      priceHistory.map((entry) => ({
        time: new Date(entry.timestamp).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
        ...entry.marginals,
      })),
    [priceHistory],
  );

  if (priceHistory.length === 0) {
    return (
      <div style={emptyStyle}>No price history available.</div>
    );
  }

  return (
    <div>
      <div style={intervalBarStyle}>
        {INTERVALS.map((iv) => (
          <button
            key={iv}
            onClick={() => handleIntervalChange(iv)}
            style={{
              ...intervalBtnStyle,
              background: selectedInterval === iv ? "var(--color-primary)" : "transparent",
              color: selectedInterval === iv ? "#fff" : "var(--color-text-muted)",
            }}
          >
            {iv}
          </button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="time"
            tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
            stroke="var(--color-border)"
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
            stroke="var(--color-border)"
            width={40}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-bg-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)",
              fontSize: "0.75rem",
            }}
            formatter={(value) => `${(Number(value) * 100).toFixed(1)}%`}
          />
          <Legend
            wrapperStyle={{ fontSize: "0.75rem" }}
          />
          {outcomes.map((outcomeId, i) => (
            <Line
              key={outcomeId}
              type="monotone"
              dataKey={outcomeId}
              stroke={OUTCOME_COLORS[i % OUTCOME_COLORS.length]}
              strokeWidth={2}
              dot={false}
              name={outcomeId}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

const intervalBarStyle: React.CSSProperties = {
  display: "flex",
  gap: "var(--space-xs)",
  marginBottom: "var(--space-sm)",
};

const intervalBtnStyle: React.CSSProperties = {
  padding: "2px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  cursor: "pointer",
  fontSize: "0.75rem",
  fontFamily: "var(--font-mono)",
};

const emptyStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.85rem",
  padding: "var(--space-md)",
  textAlign: "center",
};
