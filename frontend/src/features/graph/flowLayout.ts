/**
 * Layered DAG layout (Sugiyama-style) for the belief-flow graph.
 *
 * Columns are causal depth (longest path from a root), so the network reads
 * left-to-right as cause -> effect. Within-column order is settled by a few
 * barycenter sweeps to keep edges short and crossings low. Pure functions,
 * deterministic for a given input.
 */

export interface FlowEdge {
  source: string;
  target: string;
}

export interface PositionedNode {
  id: string;
  layer: number;
  row: number;
  x: number;
  y: number;
}

export interface FlowLayoutOptions {
  nodeWidth: number;
  nodeHeight: number;
  columnGap: number;
  rowGap: number;
  padding: number;
  /** "horizontal": layers are columns (cause -> effect reads left to right).
   *  "vertical": layers are rows (cause -> effect reads top to bottom). */
  orientation: "horizontal" | "vertical";
}

export interface FlowLayout {
  nodes: PositionedNode[];
  width: number;
  height: number;
  layerCount: number;
}

export const DEFAULT_FLOW_OPTIONS: FlowLayoutOptions = {
  nodeWidth: 192,
  nodeHeight: 62,
  columnGap: 56,
  rowGap: 26,
  padding: 12,
  orientation: "vertical",
};

/**
 * Longest-path layering: roots sit at layer 0, every node one layer past its
 * deepest parent. Nodes trapped in a cycle (shouldn't happen for market DAGs,
 * but never crash a render) are appended after the last resolvable layer.
 */
export function layerByLongestPath(
  nodeIds: string[],
  edges: FlowEdge[],
): Map<string, number> {
  const ids = new Set(nodeIds);
  const parents = new Map<string, string[]>();
  const children = new Map<string, string[]>();
  for (const id of nodeIds) {
    parents.set(id, []);
    children.set(id, []);
  }
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue;
    parents.get(e.target)!.push(e.source);
    children.get(e.source)!.push(e.target);
  }

  const layer = new Map<string, number>();
  const remainingParents = new Map<string, number>();
  for (const id of nodeIds) remainingParents.set(id, parents.get(id)!.length);

  let frontier = nodeIds.filter((id) => remainingParents.get(id) === 0).sort();
  for (const id of frontier) layer.set(id, 0);

  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const child of children.get(id)!) {
        const proposed = layer.get(id)! + 1;
        if ((layer.get(child) ?? -1) < proposed) layer.set(child, proposed);
        const left = remainingParents.get(child)! - 1;
        remainingParents.set(child, left);
        if (left === 0) next.push(child);
      }
    }
    frontier = next.sort();
  }

  // Cycle fallback: anything unlayered goes one past the deepest layer.
  const deepest = Math.max(0, ...layer.values());
  for (const id of nodeIds) {
    if (!layer.has(id)) layer.set(id, deepest + 1);
  }
  return layer;
}

function sortLayerByBarycenter(
  layerIds: string[],
  neighborRows: Map<string, number[]>,
): string[] {
  const current = new Map(layerIds.map((id, i) => [id, i]));
  return [...layerIds].sort((a, b) => {
    const rowsA = neighborRows.get(a) ?? [];
    const rowsB = neighborRows.get(b) ?? [];
    const keyA = rowsA.length ? rowsA.reduce((s, r) => s + r, 0) / rowsA.length : current.get(a)!;
    const keyB = rowsB.length ? rowsB.reduce((s, r) => s + r, 0) / rowsB.length : current.get(b)!;
    if (keyA !== keyB) return keyA - keyB;
    return current.get(a)! - current.get(b)!;
  });
}

/**
 * Compute the full layout: layer assignment, barycenter ordering (two
 * down-sweeps and one up-sweep), and pixel positions. Rows within a shorter
 * column are centered against the tallest column.
 */
export function computeFlowLayout(
  nodeIds: string[],
  edges: FlowEdge[],
  options: Partial<FlowLayoutOptions> = {},
): FlowLayout {
  const opts = { ...DEFAULT_FLOW_OPTIONS, ...options };
  if (nodeIds.length === 0) {
    return { nodes: [], width: 0, height: 0, layerCount: 0 };
  }

  const layerOf = layerByLongestPath(nodeIds, edges);
  const layerCount = Math.max(...layerOf.values()) + 1;
  const layers: string[][] = Array.from({ length: layerCount }, () => []);
  for (const id of [...nodeIds].sort()) layers[layerOf.get(id)!]!.push(id);

  const ids = new Set(nodeIds);
  const cleanEdges = edges.filter(
    (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
  );

  const rowOf = new Map<string, number>();
  const commitRows = () => {
    for (const layerIds of layers) {
      layerIds.forEach((id, row) => rowOf.set(id, row));
    }
  };
  commitRows();

  for (let sweep = 0; sweep < 3; sweep++) {
    const goingDown = sweep % 2 === 0;
    const order = goingDown
      ? [...layers.keys()].slice(1)
      : [...layers.keys()].slice(0, -1).reverse();
    for (const k of order) {
      const neighborRows = new Map<string, number[]>();
      for (const e of cleanEdges) {
        const [anchor, moving] = goingDown ? [e.source, e.target] : [e.target, e.source];
        if (layerOf.get(moving) !== k) continue;
        const anchorRow = rowOf.get(anchor);
        if (anchorRow === undefined) continue;
        if (!neighborRows.has(moving)) neighborRows.set(moving, []);
        neighborRows.get(moving)!.push(anchorRow);
      }
      layers[k] = sortLayerByBarycenter(layers[k]!, neighborRows);
      commitRows();
    }
  }

  const maxRows = Math.max(...layers.map((l) => l.length));
  const vertical = opts.orientation === "vertical";

  // Along the flow axis, layers advance by node extent + columnGap; across
  // it, siblings advance by node extent + rowGap.
  const alongExtent = vertical ? opts.nodeHeight : opts.nodeWidth;
  const acrossExtent = vertical ? opts.nodeWidth : opts.nodeHeight;
  const alongPitch = alongExtent + opts.columnGap;
  const acrossPitch = acrossExtent + opts.rowGap;
  const alongSize = opts.padding * 2 + layerCount * alongExtent + (layerCount - 1) * opts.columnGap;
  const acrossSize = opts.padding * 2 + maxRows * acrossExtent + (maxRows - 1) * opts.rowGap;
  const width = vertical ? acrossSize : alongSize;
  const height = vertical ? alongSize : acrossSize;

  const nodes: PositionedNode[] = [];
  layers.forEach((layerIds, k) => {
    const offset = ((maxRows - layerIds.length) * acrossPitch) / 2;
    layerIds.forEach((id, row) => {
      const along = opts.padding + k * alongPitch;
      const across = opts.padding + offset + row * acrossPitch;
      nodes.push({
        id,
        layer: k,
        row,
        x: vertical ? across : along,
        y: vertical ? along : across,
      });
    });
  });

  return { nodes, width, height, layerCount };
}

/** Word-wrap a title into at most two lines; ellipsize only past that. */
export function wrapTitle(title: string, maxCharsPerLine: number): string[] {
  const words = title.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  let overflow = false;

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxCharsPerLine || !current) {
      current = candidate;
      continue;
    }
    if (lines.length + 1 >= 2) {
      overflow = true;
      break;
    }
    lines.push(current);
    current = word;
  }
  if (current) lines.push(current);
  if (overflow && lines.length > 0) {
    const last = lines[lines.length - 1]!;
    lines[lines.length - 1] = `${last.slice(0, Math.max(1, maxCharsPerLine - 1))}…`;
  }
  return lines.slice(0, 2);
}
