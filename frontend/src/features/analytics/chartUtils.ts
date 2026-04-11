import type { AnalyticsInterval } from "@/lib/api/types";
import { formatCurrency } from "@/lib/utils/format";

const OUTCOME_COLORS = [
  "#818cf8",
  "#22c55e",
  "#f59e0b",
  "#38bdf8",
  "#f97316",
  "#f472b6",
];

export function getOutcomeColor(index: number): string {
  return OUTCOME_COLORS[index % OUTCOME_COLORS.length] ?? "#818cf8";
}

export function scaleNumber(
  value: number,
  domainMin: number,
  domainMax: number,
  rangeMin: number,
  rangeMax: number,
): number {
  if (domainMax === domainMin) {
    return (rangeMin + rangeMax) / 2;
  }

  const ratio = (value - domainMin) / (domainMax - domainMin);
  return rangeMin + (rangeMax - rangeMin) * ratio;
}

export function buildLinePath(points: Array<{ x: number; y: number }>): string {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
}

export function formatTimestampLabel(iso: string, interval: AnalyticsInterval): string {
  const date = new Date(iso);
  if (interval === "hour") {
    return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} ${date.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    })}`;
  }

  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function formatBucketRangeLabel(
  bucketStart: string,
  bucketEnd: string,
  interval: AnalyticsInterval,
): string {
  if (interval === "day") {
    return formatTimestampLabel(bucketStart, interval);
  }

  const start = new Date(bucketStart);
  const end = new Date(bucketEnd);
  return `${start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} - ${end.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

export function formatSignedCurrency(value: number): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatCurrency(value)}`;
}
