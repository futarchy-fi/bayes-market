import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { JunctionTreePanel } from "@/features/graph/JunctionTreePanel";
import type { EngineStatsResponse } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/lib/query/hooks", () => ({
  useNetwork: vi.fn(() => ({ data: undefined })),
  useEngineStats: vi.fn(),
}));

import { useEngineStats } from "@/lib/query/hooks";

const mockUseEngineStats = vi.mocked(useEngineStats);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const fullDiagnosticsData: EngineStatsResponse = {
  marketId: "mkt-1",
  engine: {
    mode: "exact",
    backend: "junction-tree",
    version: "2.1",
    precision: "float64",
    compile_id: "abc123def456",
    compile_type: "full",
    source_state_hash: "hash789abcdef",
  },
  cliques: {
    num_cliques: 3,
    max_clique_size: 4,
    junction_tree_width: 5,
    cliques: [
      { id: "c1", nodes: ["A", "B", "C"], size: 3, states: 8 },
      { id: "c2", nodes: ["B", "D"], size: 2, states: 4 },
      { id: "c3", nodes: ["D", "E", "F", "G"], size: 4, states: 16 },
    ],
  },
  diagnostics: {
    request_count: 42,
    error_count: 0,
    inference: { p50_ms: 1.2, p95_ms: 3.5, p99_ms: 7.8, mean_ms: 1.8, sample_count: 42 },
    cache: { hits: 30, misses: 12, hit_rate: 0.714 },
    compile_time_ms: 150,
    memory_bytes: 2048,
    last_updated: "2026-04-10T12:00:00Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-10T12:00:00Z" },
};

const minimalDiagnosticsData: EngineStatsResponse = {
  marketId: "mkt-1",
  engine: {
    mode: "approximate",
    backend: "loopy-bp",
    version: "1.0",
    precision: "float32",
    compile_id: null,
    compile_type: null,
    source_state_hash: null,
  },
  cliques: {
    num_cliques: 2,
    max_clique_size: 3,
    junction_tree_width: 4,
    cliques: [
      { id: "c1", nodes: ["X", "Y"], size: 2, states: 4 },
    ],
  },
  diagnostics: {
    request_count: 10,
    error_count: 0,
    inference: { p50_ms: 0.5, p95_ms: 1.0, p99_ms: 2.0, mean_ms: 0.7, sample_count: 10 },
    cache: { hits: 5, misses: 5, hit_rate: 0.5 },
    // compile_time_ms, memory_bytes, last_updated all omitted
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-10T12:00:00Z" },
};

const errorCountData: EngineStatsResponse = {
  ...minimalDiagnosticsData,
  diagnostics: {
    ...minimalDiagnosticsData.diagnostics,
    error_count: 5,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockLoading() {
  mockUseEngineStats.mockReturnValue({
    data: undefined,
    isLoading: true,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useEngineStats>);
}

function mockData(stats: EngineStatsResponse) {
  mockUseEngineStats.mockReturnValue({
    data: stats,
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useEngineStats>);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("JunctionTreePanel", () => {
  // Step 4: loading state
  it("shows loading indicator while data is loading", () => {
    mockLoading();
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText("Loading engine stats...")).toBeInTheDocument();
  });

  // Step 5: clique tree stats
  it("renders clique tree stats when data is loaded", () => {
    mockData(fullDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);

    // num_cliques = 3
    expect(screen.getByText("3")).toBeInTheDocument();
    // max_clique_size = 4
    expect(screen.getByText("4")).toBeInTheDocument();
    // junction_tree_width = 5
    expect(screen.getByText("5")).toBeInTheDocument();

    // Labels
    expect(screen.getByText("Cliques")).toBeInTheDocument();
    expect(screen.getByText("Max Clique Size")).toBeInTheDocument();
    expect(screen.getByText("Tree Width")).toBeInTheDocument();
  });

  // Step 6: inference diagnostics
  it("renders inference diagnostics when data is loaded", () => {
    mockData(fullDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);

    // request_count = 42
    expect(screen.getByText("42")).toBeInTheDocument();
    // error_count = 0
    expect(screen.getByText("0")).toBeInTheDocument();

    // Labels
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
    expect(screen.getByText("Cache Hit Rate")).toBeInTheDocument();
    expect(screen.getByText("71.4%")).toBeInTheDocument();

    // Latency percentiles (sample_count > 0)
    expect(screen.getByText("p50 Latency")).toBeInTheDocument();
    expect(screen.getByText("1.2ms")).toBeInTheDocument();
    expect(screen.getByText("p95 Latency")).toBeInTheDocument();
    expect(screen.getByText("3.5ms")).toBeInTheDocument();
    expect(screen.getByText("p99 Latency")).toBeInTheDocument();
    expect(screen.getByText("7.8ms")).toBeInTheDocument();
  });

  // Step 7: optional compile_time_ms
  it("renders Compile Time when compile_time_ms is present", () => {
    mockData(fullDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText("Compile Time")).toBeInTheDocument();
    expect(screen.getByText("150ms")).toBeInTheDocument();
  });

  it("does not render Compile Time when compile_time_ms is absent", () => {
    mockData(minimalDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.queryByText("Compile Time")).not.toBeInTheDocument();
  });

  // Step 8: optional memory_bytes with formatBytes
  it("renders Memory with formatted bytes when memory_bytes is present (KB)", () => {
    mockData(fullDiagnosticsData); // memory_bytes = 2048
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText("Memory")).toBeInTheDocument();
    expect(screen.getByText("2.0KB")).toBeInTheDocument();
  });

  it("formats memory_bytes as plain bytes when < 1024", () => {
    mockData({
      ...fullDiagnosticsData,
      diagnostics: { ...fullDiagnosticsData.diagnostics, memory_bytes: 512 },
    });
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText("512B")).toBeInTheDocument();
  });

  it("formats memory_bytes as MB when >= 1048576", () => {
    mockData({
      ...fullDiagnosticsData,
      diagnostics: { ...fullDiagnosticsData.diagnostics, memory_bytes: 1048576 },
    });
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText("1.0MB")).toBeInTheDocument();
  });

  it("does not render Memory when memory_bytes is absent", () => {
    mockData(minimalDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.queryByText("Memory")).not.toBeInTheDocument();
  });

  // Step 9: optional last_updated
  it("renders last updated timestamp when last_updated is present", () => {
    mockData(fullDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
  });

  it("does not render last updated when last_updated is absent", () => {
    mockData(minimalDiagnosticsData);
    renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);
    expect(screen.queryByText(/Last updated:/)).not.toBeInTheDocument();
  });

  // Step 10: error_count > 0 warning color
  it("applies danger color to error count when error_count > 0", () => {
    mockData(errorCountData);
    const { container } = renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);

    // The error count value "5" should be rendered with danger color
    // Find the MetricBox with "Errors" label and check its value has danger color
    const allMetricValues = container.querySelectorAll("div");
    let foundDangerError = false;
    for (const div of allMetricValues) {
      if (div.style.color === "var(--color-danger)" && div.textContent === "5") {
        foundDangerError = true;
        break;
      }
    }
    expect(foundDangerError).toBe(true);
  });

  it("does not apply danger color to error count when error_count is 0", () => {
    mockData(fullDiagnosticsData);
    const { container } = renderWithProviders(<JunctionTreePanel marketId="mkt-1" />);

    // error_count = 0, so the "0" value under Errors should use normal text color
    const allMetricValues = container.querySelectorAll("div");
    let foundDangerZero = false;
    for (const div of allMetricValues) {
      if (div.style.color === "var(--color-danger)" && div.textContent === "0") {
        foundDangerZero = true;
        break;
      }
    }
    expect(foundDangerZero).toBe(false);
  });
});
