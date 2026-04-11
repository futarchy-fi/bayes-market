import { useRef, useState, useEffect, useCallback } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ForceNode extends SimulationNodeDatum {
  id: string;
  title: string;
  status: string;
  /** Pinned position (set by drag) */
  fx?: number | null;
  fy?: number | null;
}

export interface ForceLink extends SimulationLinkDatum<ForceNode> {
  source: string | ForceNode;
  target: string | ForceNode;
}

export interface ForceGraphPositions {
  nodes: Array<{ id: string; x: number; y: number }>;
}

export interface UseForceGraphOptions {
  width: number;
  height: number;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useForceGraph(
  inputNodes: Array<{ id: string; title: string; status: string }>,
  inputLinks: Array<{ source: string; target: string }>,
  options: UseForceGraphOptions = { width: 600, height: 400 },
) {
  const simRef = useRef<Simulation<ForceNode, ForceLink> | null>(null);
  const nodesRef = useRef<ForceNode[]>([]);
  const linksRef = useRef<ForceLink[]>([]);
  const [positions, setPositions] = useState<ForceGraphPositions>({ nodes: [] });

  // Stable snapshot updater
  const flushPositions = useCallback(() => {
    setPositions({
      nodes: nodesRef.current.map((n) => ({
        id: n.id,
        x: n.x ?? 0,
        y: n.y ?? 0,
      })),
    });
  }, []);

  // Diff and reconcile nodes/links when inputs change
  useEffect(() => {
    const { width, height } = options;

    // --- Diff nodes ---
    const prevById = new Map(nodesRef.current.map((n) => [n.id, n]));
    const nextNodes: ForceNode[] = inputNodes.map((inp) => {
      const existing = prevById.get(inp.id);
      if (existing) {
        // Preserve position, update data
        existing.title = inp.title;
        existing.status = inp.status;
        return existing;
      }
      // New node: place near center with jitter
      return {
        id: inp.id,
        title: inp.title,
        status: inp.status,
        x: width / 2 + (Math.random() - 0.5) * 60,
        y: height / 2 + (Math.random() - 0.5) * 60,
      };
    });

    nodesRef.current = nextNodes;

    // --- Diff links ---
    const nextLinks: ForceLink[] = inputLinks.map((l) => ({
      source: l.source,
      target: l.target,
    }));
    linksRef.current = nextLinks;

    // --- Create or update simulation ---
    if (!simRef.current) {
      const sim = forceSimulation<ForceNode>(nextNodes)
        .force(
          "link",
          forceLink<ForceNode, ForceLink>(nextLinks)
            .id((d) => d.id)
            .distance(120),
        )
        .force("charge", forceManyBody().strength(-300))
        .force("center", forceCenter(width / 2, height / 2))
        .force("collide", forceCollide(50))
        .on("tick", flushPositions);

      simRef.current = sim;
    } else {
      const sim = simRef.current;
      sim.nodes(nextNodes);

      const linkForce = sim.force("link") as ReturnType<typeof forceLink<ForceNode, ForceLink>> | undefined;
      if (linkForce) {
        linkForce.links(nextLinks);
      }

      // Gentle restart to avoid resetting all positions
      sim.alpha(0.1).restart();
    }

    // Initial flush
    flushPositions();
  }, [inputNodes, inputLinks, options.width, options.height, flushPositions]);

  // Cleanup
  useEffect(() => {
    return () => {
      simRef.current?.stop();
    };
  }, []);

  // Expose simulation ref for drag/zoom integration
  const getSimulation = useCallback(() => simRef.current, []);
  const getNodes = useCallback(() => nodesRef.current, []);

  return {
    positions,
    getSimulation,
    getNodes,
    flushPositions,
  };
}
