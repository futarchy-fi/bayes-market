import { useState, useCallback, useRef } from "react";
import type { GraphEdge } from "./deriveEdges";

/** Per-hop stagger delay in ms */
const HOP_DELAY = 150;
/** Maximum total animation duration in ms */
const MAX_DURATION = 1500;

export interface AnimationState {
  /** Set of node IDs currently highlighted by the animation wave */
  animatingNodes: Set<string>;
  /** Set of edge keys ("source::target" sorted) currently animated */
  animatingEdges: Set<string>;
  /** The node ID that is the evidence source (glows differently) */
  evidenceNodeId: string | null;
}

function edgeKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`;
}

/**
 * BFS from a starting node along the given edges.
 * Returns an array of layers: layer 0 = [startId], layer 1 = its neighbors, etc.
 */
function bfsLayers(startId: string, edges: GraphEdge[]): string[][] {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push(e.target);
    adj.get(e.target)!.push(e.source);
  }

  const visited = new Set<string>([startId]);
  const layers: string[][] = [[startId]];
  let frontier = [startId];

  while (frontier.length > 0) {
    const next: string[] = [];
    for (const nodeId of frontier) {
      for (const neighbor of adj.get(nodeId) ?? []) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          next.push(neighbor);
        }
      }
    }
    if (next.length > 0) {
      layers.push(next);
      frontier = next;
    } else {
      break;
    }
  }

  return layers;
}

/**
 * Hook that manages evidence propagation animation state.
 * Performs BFS from an evidence node and staggers visual highlights per hop.
 */
export function useAnimationPropagation() {
  const [state, setState] = useState<AnimationState>({
    animatingNodes: new Set(),
    animatingEdges: new Set(),
    evidenceNodeId: null,
  });

  // Ref to store timeout IDs for cancellation
  const timersRef = useRef<number[]>([]);
  const activeRef = useRef(false);

  const cancelAnimation = useCallback(() => {
    activeRef.current = false;
    for (const t of timersRef.current) {
      window.clearTimeout(t);
    }
    timersRef.current = [];
    setState({
      animatingNodes: new Set(),
      animatingEdges: new Set(),
      evidenceNodeId: null,
    });
  }, []);

  const triggerAnimation = useCallback(
    (evidenceNodeId: string, allEdges: GraphEdge[]) => {
      // Cancel any in-progress animation
      cancelAnimation();
      activeRef.current = true;

      const layers = bfsLayers(evidenceNodeId, allEdges);
      const maxHops = layers.length;
      // Cap stagger so total doesn't exceed MAX_DURATION
      const stagger = Math.min(HOP_DELAY, Math.floor(MAX_DURATION / Math.max(maxHops, 1)));

      const timers: number[] = [];
      const allNodes = new Set<string>();
      const allEdgeKeys = new Set<string>();

      // Schedule each layer
      for (let hop = 0; hop < layers.length; hop++) {
        const delay = hop * stagger;
        const t = window.setTimeout(() => {
          if (!activeRef.current) return;

          // Add this layer's nodes
          for (const nodeId of layers[hop]!) {
            allNodes.add(nodeId);
          }

          // Add edges between this layer and previous layers
          if (hop > 0) {
            const prevNodes = new Set<string>();
            for (let p = 0; p < hop; p++) {
              for (const n of layers[p]!) prevNodes.add(n);
            }
            for (const nodeId of layers[hop]!) {
              for (const e of allEdges) {
                const src = e.source;
                const tgt = e.target;
                if (
                  (src === nodeId && prevNodes.has(tgt)) ||
                  (tgt === nodeId && prevNodes.has(src))
                ) {
                  allEdgeKeys.add(edgeKey(src, tgt));
                }
              }
            }
          }

          setState({
            animatingNodes: new Set(allNodes),
            animatingEdges: new Set(allEdgeKeys),
            evidenceNodeId,
          });
        }, delay);
        timers.push(t);
      }

      // Schedule cleanup after all layers + a hold duration
      const holdDuration = 600;
      const totalDuration = (layers.length - 1) * stagger + holdDuration;
      const cleanupTimer = window.setTimeout(() => {
        if (!activeRef.current) return;
        activeRef.current = false;
        setState({
          animatingNodes: new Set(),
          animatingEdges: new Set(),
          evidenceNodeId: null,
        });
      }, totalDuration);
      timers.push(cleanupTimer);

      timersRef.current = timers;
    },
    [cancelAnimation],
  );

  return {
    animatingNodes: state.animatingNodes,
    animatingEdges: state.animatingEdges,
    evidenceNodeId: state.evidenceNodeId,
    triggerAnimation,
    cancelAnimation,
  };
}
