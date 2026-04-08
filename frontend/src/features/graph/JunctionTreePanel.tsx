import { useEngineStats } from "@/lib/query/hooks";
import type { EngineStatsResponse, CliqueSummary } from "@/lib/api/types";

interface JunctionTreePanelProps {
  marketId: string;
}

function CliqueCard({ clique, maxStates }: { clique: CliqueSummary; maxStates: number }) {
  const barPct = maxStates > 0 ? (clique.states / maxStates) * 100 : 0;

  return (
    <div style={cliqueCardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 600, fontFamily: "var(--font-mono)" }}>
          {clique.id}
        </span>
        <span style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
          {clique.size} vars · {clique.states.toLocaleString()} states
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
        {clique.nodes.map((n) => (
          <span key={n} style={varTagStyle}>{n}</span>
        ))}
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--color-border)", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${barPct}%`,
            borderRadius: 3,
            background: barPct > 80 ? "var(--color-danger)" : barPct > 50 ? "var(--color-warning, orange)" : "var(--color-success)",
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}

function InferenceDiagnostics({ stats }: { stats: EngineStatsResponse }) {
  const d = stats.diagnostics;
  const inf = d.inference;
  const cache = d.cache;
  const hasLatency = (inf.sample_count ?? inf.count ?? 0) > 0;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "var(--space-sm)" }}>
      <MetricBox label="Requests" value={d.request_count.toLocaleString()} />
      <MetricBox label="Errors" value={d.error_count.toLocaleString()} warn={d.error_count > 0} />
      <MetricBox
        label="Cache Hit Rate"
        value={cache.hits + cache.misses > 0 ? `${(cache.hit_rate * 100).toFixed(1)}%` : "—"}
        sub={`${cache.hits} / ${cache.hits + cache.misses}`}
      />
      {hasLatency && (
        <>
          <MetricBox label="p50 Latency" value={`${inf.p50_ms.toFixed(1)}ms`} />
          <MetricBox label="p95 Latency" value={`${inf.p95_ms.toFixed(1)}ms`} />
          <MetricBox label="p99 Latency" value={`${inf.p99_ms.toFixed(1)}ms`} />
        </>
      )}
      {d.compile_time_ms != null && (
        <MetricBox label="Compile Time" value={`${d.compile_time_ms.toFixed(0)}ms`} />
      )}
      {d.memory_bytes != null && (
        <MetricBox label="Memory" value={formatBytes(d.memory_bytes)} />
      )}
    </div>
  );
}

function MetricBox({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div style={metricBoxStyle}>
      <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: "1.1rem", fontWeight: 700, fontFamily: "var(--font-mono)", color: warn ? "var(--color-danger)" : "var(--color-text)" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: "0.65rem", color: "var(--color-text-muted)" }}>{sub}</div>}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function JunctionTreePanel({ marketId }: JunctionTreePanelProps) {
  const { data, isLoading } = useEngineStats(marketId);

  if (isLoading) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center" }}>Loading engine stats...</div>
      </div>
    );
  }

  if (!data) return null;

  const { engine, cliques, diagnostics } = data;
  const maxStates = Math.max(1, ...cliques.cliques.map((c) => c.states));
  const hasCliques = cliques.cliques.length > 0;

  return (
    <div style={panelStyle}>
      <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>
        Junction Tree & Inference
      </h3>

      {/* Engine info banner */}
      <div style={engineBannerStyle}>
        <span><strong>Engine:</strong> {engine.mode} / {engine.backend} v{engine.version}</span>
        <span><strong>Precision:</strong> {engine.precision}</span>
        {engine.compile_id && <span><strong>Compiled:</strong> {engine.compile_id.slice(0, 12)}</span>}
        {engine.source_state_hash && <span><strong>State:</strong> {engine.source_state_hash.slice(0, 12)}</span>}
      </div>

      {/* Junction tree summary */}
      <div style={{ marginTop: "var(--space-md)" }}>
        <div style={{ display: "flex", gap: "var(--space-lg)", marginBottom: "var(--space-sm)" }}>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>Cliques</span>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
              {cliques.num_cliques}
            </div>
          </div>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>Max Clique Size</span>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
              {cliques.max_clique_size}
            </div>
          </div>
          <div>
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>Tree Width</span>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
              {cliques.junction_tree_width}
            </div>
          </div>
        </div>

        {hasCliques ? (
          <div style={{ display: "grid", gap: "var(--space-sm)" }}>
            {cliques.cliques.map((c) => (
              <CliqueCard key={c.id} clique={c} maxStates={maxStates} />
            ))}
          </div>
        ) : (
          <div style={emptyCliqueStyle}>
            No cliques yet — market has independent variables or hasn't been compiled.
            Submit conditional edits to create dependencies between variables.
          </div>
        )}
      </div>

      {/* Inference diagnostics */}
      <div style={{ marginTop: "var(--space-md)" }}>
        <h4 style={{ fontSize: "0.9rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>
          Inference Diagnostics
        </h4>
        <InferenceDiagnostics stats={data} />
        {diagnostics.last_updated && (
          <div style={{ fontSize: "0.65rem", color: "var(--color-text-muted)", marginTop: "var(--space-xs)" }}>
            Last updated: {new Date(diagnostics.last_updated).toLocaleString()}
          </div>
        )}
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

const engineBannerStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--space-md)",
  padding: "var(--space-sm) var(--space-md)",
  background: "var(--color-bg)",
  borderRadius: "var(--radius-sm)",
  fontSize: "0.8rem",
  fontFamily: "var(--font-mono)",
};

const cliqueCardStyle: React.CSSProperties = {
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
};

const varTagStyle: React.CSSProperties = {
  padding: "1px 6px",
  borderRadius: 4,
  background: "var(--color-primary)",
  color: "#fff",
  fontSize: "0.7rem",
  fontFamily: "var(--font-mono)",
  opacity: 0.8,
};

const metricBoxStyle: React.CSSProperties = {
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  textAlign: "center",
};

const emptyCliqueStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-bg)",
  color: "var(--color-text-muted)",
  fontSize: "0.8rem",
  textAlign: "center",
};
