"""Bounded-treewidth junction tree inference module for the Bayes engine seam."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TypedDict

from .contracts import (
    AtomicEventQueryResult,
    CliqueSummary,
    CompileResult,
    InferenceQueryBackend,
    MarginalQueryResult,
)
from .errors import (
    InferenceQueryError,
    InferenceUnsupportedQueryError,
)


# ---------------------------------------------------------------------------
# Graph input TypedDicts
# ---------------------------------------------------------------------------


class VariableNode(TypedDict):
    """A variable (node) in a Bayesian network."""

    id: str
    outcomes: list[str]


class DirectedEdge(TypedDict):
    """A directed edge from parent to child in a Bayesian network."""

    parent: str
    child: str


class BayesianNetworkGraph(TypedDict):
    """JSON-serializable description of a Bayesian network structure."""

    variables: list[VariableNode]
    edges: list[DirectedEdge]
    cpts: dict[str, Any]


# ---------------------------------------------------------------------------
# Compile artifact
# ---------------------------------------------------------------------------

JUNCTION_TREE_EXACT_ELIGIBILITY_REASON = "bounded_treewidth_junction_tree"
_COMPILE_TYPE = "junction_tree"


def _canonical_json_hash(data: object) -> str:
    """Return a stable SHA-256 digest for JSON-serializable data."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _compile_id_from_hash(source_state_hash: str) -> str:
    digest = source_state_hash.split(":", 1)[-1]
    return f"comp-{digest[:12]}"


def _estimate_memory_bytes(cliques: tuple[CliqueSummary, ...]) -> int:
    total = 0
    for clique in cliques:
        total += int(clique.states) * 32 + int(clique.size) * 64
    return total


@dataclass(frozen=True)
class JunctionTreeCompileArtifact:
    """Immutable compile artifact for a junction-tree network compilation."""

    market_id: str
    variable_ids: tuple[str, ...]
    cliques: tuple[CliqueSummary, ...]
    separator_sets: tuple[frozenset[str], ...]
    elimination_ordering: tuple[str, ...]
    message_schedule: tuple[tuple[str, str], ...]
    potential_tables: Mapping[str, Any] | None
    junction_tree_width: int
    exact_eligible: bool
    eligibility_reason: str
    source_state_hash: str
    compile_id: str
    compile_type: str
    memory_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "variable_ids", tuple(self.variable_ids))
        object.__setattr__(self, "cliques", tuple(self.cliques))
        object.__setattr__(self, "separator_sets", tuple(self.separator_sets))
        object.__setattr__(self, "elimination_ordering", tuple(self.elimination_ordering))
        object.__setattr__(self, "message_schedule", tuple(self.message_schedule))

        if not self.market_id:
            raise ValueError("Compile artifact must include market_id")
        if not self.source_state_hash:
            raise ValueError("Compile artifact must include source_state_hash")
        if not self.compile_id:
            raise ValueError("Compile artifact must include compile_id")
        if not self.compile_type:
            raise ValueError("Compile artifact must include compile_type")
        if self.junction_tree_width < 0:
            raise ValueError("Compile artifact junction_tree_width must be non-negative")
        if self.memory_bytes < 0:
            raise ValueError("Compile artifact memory_bytes must be non-negative")
        if not self.eligibility_reason:
            raise ValueError("Compile artifact must include eligibility_reason")

    def to_compile_result(self, *, compile_time_ms: float = 0.0, last_updated: str) -> CompileResult:
        """Convert the artifact into the shared compile-result contract."""
        return CompileResult(
            compile_id=self.compile_id,
            compile_type=self.compile_type,
            source_state_hash=self.source_state_hash,
            cliques=self.cliques,
            compile_time_ms=compile_time_ms,
            memory_bytes=self.memory_bytes,
            last_updated=last_updated,
            artifact=self,
        )


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def _build_adjacency(variables: Sequence[VariableNode], edges: Sequence[DirectedEdge]) -> dict[str, set[str]]:
    """Build an undirected adjacency map (moral graph) from the Bayesian network."""
    var_ids = {v["id"] for v in variables}
    adj: dict[str, set[str]] = {vid: set() for vid in var_ids}

    # Group parents per child for moralisation
    children_parents: dict[str, list[str]] = {vid: [] for vid in var_ids}
    for edge in edges:
        parent, child = edge["parent"], edge["child"]
        adj[parent].add(child)
        adj[child].add(parent)
        children_parents[child].append(parent)

    # Moralise: connect co-parents
    for parents in children_parents.values():
        for i in range(len(parents)):
            for j in range(i + 1, len(parents)):
                adj[parents[i]].add(parents[j])
                adj[parents[j]].add(parents[i])

    return adj


def _eliminate_and_build_cliques(
    adj: dict[str, set[str]],
    elimination_ordering: tuple[str, ...],
    outcome_counts: dict[str, int],
) -> tuple[list[CliqueSummary], list[frozenset[str]], int]:
    """Run variable elimination to produce cliques, separators, and treewidth."""
    adj = {v: set(neighbors) for v, neighbors in adj.items()}  # deep copy

    cliques: list[CliqueSummary] = []
    seen_clique_sets: list[frozenset[str]] = []
    max_width = 0

    for var in elimination_ordering:
        neighbors = adj.get(var, set())
        clique_nodes = frozenset({var} | neighbors)

        # Check if this clique is a subset of an existing one
        is_subset = any(clique_nodes <= existing for existing in seen_clique_sets)
        if not is_subset:
            sorted_nodes = tuple(sorted(clique_nodes))
            states = 1
            for n in sorted_nodes:
                states *= outcome_counts.get(n, 2)
            cliques.append(
                CliqueSummary(
                    id=f"jt-c{len(cliques)}",
                    nodes=sorted_nodes,
                    size=len(sorted_nodes),
                    states=states,
                )
            )
            seen_clique_sets.append(clique_nodes)

        width = len(clique_nodes) - 1
        if width > max_width:
            max_width = width

        # Fill: connect all neighbors of the eliminated variable
        for n1 in neighbors:
            for n2 in neighbors:
                if n1 != n2:
                    adj[n1].add(n2)

        # Remove eliminated variable
        for n in neighbors:
            adj[n].discard(var)
        del adj[var]

    return cliques, seen_clique_sets, max_width


def _build_separator_sets(clique_node_sets: list[frozenset[str]]) -> tuple[frozenset[str], ...]:
    """Compute separator sets between adjacent cliques in the junction tree."""
    separators: list[frozenset[str]] = []
    for i in range(len(clique_node_sets)):
        for j in range(i + 1, len(clique_node_sets)):
            intersection = clique_node_sets[i] & clique_node_sets[j]
            if intersection:
                separators.append(intersection)
    return tuple(separators)


def _build_message_schedule(cliques: list[CliqueSummary], clique_node_sets: list[frozenset[str]]) -> tuple[tuple[str, str], ...]:
    """Build a message-passing schedule as directed edges between clique ids."""
    schedule: list[tuple[str, str]] = []
    for i in range(len(clique_node_sets)):
        for j in range(i + 1, len(clique_node_sets)):
            if clique_node_sets[i] & clique_node_sets[j]:
                # Bidirectional messages
                schedule.append((cliques[i].id, cliques[j].id))
                schedule.append((cliques[j].id, cliques[i].id))
    return tuple(schedule)


@dataclass(frozen=True)
class JunctionTreeCompiler:
    """Compile a Bayesian network graph into a junction tree artifact."""

    max_treewidth: int = 15
    compile_type: str = _COMPILE_TYPE
    eligibility_reason: str = JUNCTION_TREE_EXACT_ELIGIBILITY_REASON

    def compile_market(self, *, market_id: str, source_state_hash: str) -> CompileResult:
        """Protocol-required method — junction tree compilation requires compile_network."""
        raise InferenceUnsupportedQueryError(
            "junction tree compilation requires compile_network, not compile_market",
            details={"market_id": market_id},
        )

    def compile_network(
        self,
        *,
        graph: BayesianNetworkGraph,
        market_id: str = "network",
        elimination_ordering: tuple[str, ...] | None = None,
        last_updated: str = "",
    ) -> CompileResult:
        """Compile a Bayesian network graph into a junction tree artifact."""
        started_at = time.perf_counter()

        variables = graph["variables"]
        edges = graph["edges"]
        variable_ids = tuple(v["id"] for v in variables)
        outcome_counts = {v["id"]: len(v["outcomes"]) for v in variables}

        if elimination_ordering is None:
            elimination_ordering = self._triangulate(variables, edges)

        # Build moral graph and run elimination
        adj = _build_adjacency(variables, edges)
        cliques, clique_node_sets, treewidth = _eliminate_and_build_cliques(
            adj, elimination_ordering, outcome_counts,
        )

        separator_sets = _build_separator_sets(clique_node_sets)
        message_schedule = _build_message_schedule(cliques, clique_node_sets)
        exact_eligible = self._check_treewidth(treewidth)

        # Build source state hash from the graph structure
        source_hash_input = {
            "variables": [{"id": v["id"], "outcomes": v["outcomes"]} for v in variables],
            "edges": [{"parent": e["parent"], "child": e["child"]} for e in edges],
        }
        source_state_hash = _canonical_json_hash(source_hash_input)
        compile_id = _compile_id_from_hash(source_state_hash)

        cliques_tuple = tuple(cliques)
        memory_bytes = _estimate_memory_bytes(cliques_tuple)
        compile_time_ms = round((time.perf_counter() - started_at) * 1000.0, 3)

        artifact = JunctionTreeCompileArtifact(
            market_id=market_id,
            variable_ids=variable_ids,
            cliques=cliques_tuple,
            separator_sets=separator_sets,
            elimination_ordering=elimination_ordering,
            message_schedule=message_schedule,
            potential_tables=None,
            junction_tree_width=treewidth,
            exact_eligible=exact_eligible,
            eligibility_reason=self.eligibility_reason if exact_eligible else f"treewidth_{treewidth}_exceeds_bound_{self.max_treewidth}",
            source_state_hash=source_state_hash,
            compile_id=compile_id,
            compile_type=self.compile_type,
            memory_bytes=memory_bytes,
        )

        return artifact.to_compile_result(
            compile_time_ms=compile_time_ms,
            last_updated=last_updated or "1970-01-01T00:00:00Z",
        )

    def _triangulate(
        self,
        variables: Sequence[VariableNode],
        edges: Sequence[DirectedEdge],
    ) -> tuple[str, ...]:
        """Placeholder triangulation — raises until a real heuristic is implemented."""
        raise InferenceUnsupportedQueryError(
            "automatic triangulation not yet implemented; provide an explicit elimination_ordering",
            details={"variable_count": len(variables), "edge_count": len(edges)},
        )

    def _check_treewidth(self, treewidth: int) -> bool:
        """Return True if treewidth is within the configured bound."""
        return treewidth <= self.max_treewidth


# ---------------------------------------------------------------------------
# Query backend
# ---------------------------------------------------------------------------


def _require_junction_tree_artifact(compile_result: CompileResult) -> JunctionTreeCompileArtifact:
    """Validate and extract a JunctionTreeCompileArtifact from a CompileResult."""
    artifact = compile_result.artifact
    if artifact is None:
        raise InferenceQueryError(
            "Compile result does not include a queryable artifact",
            details={"compileId": compile_result.compile_id},
        )
    if not isinstance(artifact, JunctionTreeCompileArtifact):
        raise InferenceQueryError(
            "Compile result artifact is not a junction-tree artifact",
            details={
                "compileId": compile_result.compile_id,
                "artifactType": type(artifact).__name__,
            },
        )
    if compile_result.compile_id != artifact.compile_id:
        raise InferenceQueryError(
            "Compile result metadata does not match artifact compile_id",
            details={
                "compileId": compile_result.compile_id,
                "artifactCompileId": artifact.compile_id,
            },
        )
    if compile_result.source_state_hash != artifact.source_state_hash:
        raise InferenceQueryError(
            "Compile result metadata does not match artifact source_state_hash",
            details={
                "compileId": compile_result.compile_id,
                "sourceStateHash": compile_result.source_state_hash,
                "artifactSourceStateHash": artifact.source_state_hash,
            },
        )
    if compile_result.compile_type != artifact.compile_type:
        raise InferenceQueryError(
            "Compile result metadata does not match artifact compile_type",
            details={
                "compileId": compile_result.compile_id,
                "compileType": compile_result.compile_type,
                "artifactCompileType": artifact.compile_type,
            },
        )
    if not artifact.exact_eligible:
        raise InferenceUnsupportedQueryError(
            "Compiled artifact is not eligible for exact query execution",
            details={
                "compileId": compile_result.compile_id,
                "eligibilityReason": artifact.eligibility_reason,
            },
        )
    return artifact


@dataclass(frozen=True)
class JunctionTreeQueryBackend(InferenceQueryBackend):
    """Execute queries against junction-tree compiled artifacts (placeholder)."""

    def query_marginals(
        self,
        compile_result: CompileResult,
        *,
        context: Mapping[str, str] | None = None,
    ) -> MarginalQueryResult:
        """Validate the artifact and raise — message passing not yet implemented."""
        _require_junction_tree_artifact(compile_result)
        raise InferenceUnsupportedQueryError(
            "junction tree message passing not yet implemented",
            details={"compileId": compile_result.compile_id},
        )

    def query_atomic_event(
        self,
        compile_result: CompileResult,
        *,
        variable_id: str,
        outcome_id: str,
        negated: bool = False,
    ) -> AtomicEventQueryResult:
        """Validate the artifact and raise — message passing not yet implemented."""
        _require_junction_tree_artifact(compile_result)
        raise InferenceUnsupportedQueryError(
            "junction tree message passing not yet implemented",
            details={
                "compileId": compile_result.compile_id,
                "variableId": variable_id,
                "outcomeId": outcome_id,
            },
        )


# ---------------------------------------------------------------------------
# Module-level singletons and exports
# ---------------------------------------------------------------------------

JUNCTION_TREE_COMPILER = JunctionTreeCompiler()
JUNCTION_TREE_QUERY_BACKEND = JunctionTreeQueryBackend()

__all__ = [
    "BayesianNetworkGraph",
    "DirectedEdge",
    "JUNCTION_TREE_COMPILER",
    "JUNCTION_TREE_EXACT_ELIGIBILITY_REASON",
    "JUNCTION_TREE_QUERY_BACKEND",
    "JunctionTreeCompileArtifact",
    "JunctionTreeCompiler",
    "JunctionTreeQueryBackend",
    "VariableNode",
]
