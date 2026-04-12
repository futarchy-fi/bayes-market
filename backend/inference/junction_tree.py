"""Bounded-treewidth junction tree inference module for the Bayes engine seam."""

from __future__ import annotations

import hashlib
import itertools
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

    def compile_result(
        self,
        *,
        market_snapshot: Mapping[str, Any],
        conditional_marginals: Mapping[str, Mapping[str, float]] | None = None,
        compile_time_ms: float = 0.0,
        last_updated: str,
    ) -> CompileResult:
        """Compile a market snapshot via junction tree with market-level source hashing."""
        market_id = str(market_snapshot["id"])
        variable_id = str(market_snapshot["variableId"])
        outcomes = [str(o["id"]) for o in market_snapshot["outcomes"]]

        graph: BayesianNetworkGraph = {
            "variables": [{"id": variable_id, "outcomes": outcomes}],
            "edges": [],
            "cpts": {},
        }

        network_result = self.compile_network(
            graph=graph,
            market_id=market_id,
            elimination_ordering=(variable_id,),
            last_updated=last_updated,
        )

        # Recompute source_state_hash from full market state to match server cache lookup
        source_state_inputs = {
            "market": dict(market_snapshot),
            "conditionalMarginals": dict(conditional_marginals or {}),
        }
        source_state_hash = _canonical_json_hash(source_state_inputs)
        compile_id = _compile_id_from_hash(source_state_hash)

        assert isinstance(network_result.artifact, JunctionTreeCompileArtifact)
        old_artifact = network_result.artifact
        artifact = JunctionTreeCompileArtifact(
            market_id=old_artifact.market_id,
            variable_ids=old_artifact.variable_ids,
            cliques=old_artifact.cliques,
            separator_sets=old_artifact.separator_sets,
            elimination_ordering=old_artifact.elimination_ordering,
            message_schedule=old_artifact.message_schedule,
            potential_tables=old_artifact.potential_tables,
            junction_tree_width=old_artifact.junction_tree_width,
            exact_eligible=old_artifact.exact_eligible,
            eligibility_reason=old_artifact.eligibility_reason,
            source_state_hash=source_state_hash,
            compile_id=compile_id,
            compile_type=old_artifact.compile_type,
            memory_bytes=old_artifact.memory_bytes,
        )

        return artifact.to_compile_result(
            compile_time_ms=network_result.compile_time_ms,
            last_updated=last_updated,
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

        # Initialize potentials from CPTs if provided
        potential_tables: dict[str, Factor] | None = None
        if graph.get("cpts"):
            potential_tables = _initialize_potentials(graph, cliques_tuple)

        compile_time_ms = round((time.perf_counter() - started_at) * 1000.0, 3)

        artifact = JunctionTreeCompileArtifact(
            market_id=market_id,
            variable_ids=variable_ids,
            cliques=cliques_tuple,
            separator_sets=separator_sets,
            elimination_ordering=elimination_ordering,
            message_schedule=message_schedule,
            potential_tables=potential_tables,
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
# Factor operations
# ---------------------------------------------------------------------------

# A factor is a pair: (vars_tuple, table) where vars_tuple is a sorted tuple
# of variable ids, and table is dict[tuple[str,...], float] mapping joint
# outcome assignments (in the same order as vars_tuple) to probabilities.

Factor = tuple[tuple[str, ...], dict[tuple[str, ...], float]]


def _factor_multiply(f1: Factor, f2: Factor) -> Factor:
    """Multiply two factors over their shared variables."""
    vars1, tab1 = f1
    vars2, tab2 = f2
    result_vars = tuple(sorted(set(vars1) | set(vars2)))
    idx1 = tuple(result_vars.index(v) for v in vars1)
    idx2 = tuple(result_vars.index(v) for v in vars2)

    # Index f2 by the shared variable positions for fast lookup
    result: dict[tuple[str, ...], float] = {}
    tab2_index: dict[tuple[str, ...], list[tuple[tuple[str, ...], float]]] = {}
    shared_positions_in_vars2 = [i for i, v in enumerate(vars2) if v in set(vars1)]
    for assignment2, val2 in tab2.items():
        key = tuple(assignment2[p] for p in shared_positions_in_vars2)
        tab2_index.setdefault(key, []).append((assignment2, val2))

    for assignment1, val1 in tab1.items():
        shared_key = tuple(assignment1[vars1.index(vars2[p])] for p in shared_positions_in_vars2)
        for assignment2, val2 in tab2_index.get(shared_key, []):
            res_assignment = [""] * len(result_vars)
            for i, pos in enumerate(idx1):
                res_assignment[pos] = assignment1[i]
            for i, pos in enumerate(idx2):
                res_assignment[pos] = assignment2[i]
            result[tuple(res_assignment)] = val1 * val2

    return result_vars, result


def _factor_marginalize(f: Factor, eliminate: frozenset[str]) -> Factor:
    """Sum out a set of variables from a factor."""
    vars_f, tab = f
    keep_indices = [i for i, v in enumerate(vars_f) if v not in eliminate]
    result_vars = tuple(vars_f[i] for i in keep_indices)
    if not result_vars:
        return result_vars, {(): sum(tab.values())}
    result: dict[tuple[str, ...], float] = {}
    for assignment, val in tab.items():
        key = tuple(assignment[i] for i in keep_indices)
        result[key] = result.get(key, 0.0) + val
    return result_vars, result


def _factor_normalize(f: Factor) -> Factor:
    """Normalize a factor so its values sum to 1."""
    vars_f, tab = f
    total = sum(tab.values())
    if total == 0.0:
        return vars_f, dict(tab)
    return vars_f, {k: v / total for k, v in tab.items()}


# ---------------------------------------------------------------------------
# Potential initialization
# ---------------------------------------------------------------------------


def _initialize_potentials(
    graph: BayesianNetworkGraph,
    cliques: tuple[CliqueSummary, ...],
) -> dict[str, Factor]:
    """Create initial clique potential tables from the CPTs in the graph.

    Each CPT factor is assigned to the smallest clique that contains its
    family (child + parents). Unassigned cliques get a uniform potential.
    """
    variables = {v["id"]: v for v in graph["variables"]}
    cpts = graph["cpts"]

    # Build per-child parent list from edges
    parents_of: dict[str, list[str]] = {v["id"]: [] for v in graph["variables"]}
    for edge in graph["edges"]:
        parents_of[edge["child"]].append(edge["parent"])

    # Convert each CPT to a Factor and assign to the smallest containing clique
    clique_factors: dict[str, list[Factor]] = {c.id: [] for c in cliques}

    for var_id, cpt_table in cpts.items():
        family = frozenset([var_id] + parents_of.get(var_id, []))
        factor_vars = tuple(sorted(family))
        factor_tab: dict[tuple[str, ...], float] = {}

        for parent_key, dist in cpt_table.items():
            # Parse parent assignment from pipe-separated key
            parent_assignment: dict[str, str] = {}
            if parent_key:
                for part in parent_key.split("|"):
                    pvar, pval = part.split("=")
                    parent_assignment[pvar] = pval

            for outcome, prob in dist.items():
                assignment: dict[str, str] = dict(parent_assignment)
                assignment[var_id] = outcome
                key = tuple(assignment[v] for v in factor_vars)
                factor_tab[key] = prob

        factor: Factor = (factor_vars, factor_tab)

        # Assign to smallest containing clique
        best_clique: CliqueSummary | None = None
        for c in cliques:
            if family <= frozenset(c.nodes):
                if best_clique is None or c.size < best_clique.size:
                    best_clique = c
        if best_clique is not None:
            clique_factors[best_clique.id].append(factor)

    # Build clique potentials by multiplying assigned factors
    potentials: dict[str, Factor] = {}
    for c in cliques:
        factors = clique_factors[c.id]
        if not factors:
            # Uniform potential
            factor_vars = tuple(sorted(c.nodes))
            outcomes_list = [variables[v]["outcomes"] for v in factor_vars]
            tab = {combo: 1.0 for combo in itertools.product(*outcomes_list)}
            potentials[c.id] = (factor_vars, tab)
        else:
            pot = factors[0]
            for f in factors[1:]:
                pot = _factor_multiply(pot, f)
            potentials[c.id] = pot

    return potentials


# ---------------------------------------------------------------------------
# Shafer-Shenoy belief propagation
# ---------------------------------------------------------------------------


def _run_belief_propagation(
    cliques: tuple[CliqueSummary, ...],
    separator_sets: tuple[frozenset[str], ...],
    message_schedule: tuple[tuple[str, str], ...],
    potential_tables: dict[str, Factor],
) -> dict[str, Factor]:
    """Run Shafer-Shenoy message passing and return updated clique potentials."""
    # Build adjacency: which cliques are neighbours and what is their separator
    adjacency: dict[str, list[str]] = {c.id: [] for c in cliques}
    separator_for: dict[tuple[str, str], frozenset[str]] = {}
    clique_node_sets = {c.id: frozenset(c.nodes) for c in cliques}

    for i, ci in enumerate(cliques):
        for j in range(i + 1, len(cliques)):
            cj = cliques[j]
            sep = clique_node_sets[ci.id] & clique_node_sets[cj.id]
            if sep:
                adjacency[ci.id].append(cj.id)
                adjacency[cj.id].append(ci.id)
                separator_for[(ci.id, cj.id)] = sep
                separator_for[(cj.id, ci.id)] = sep

    # Use first clique as root; build collection order via BFS
    root = cliques[0].id
    visited_order: list[str] = []
    parent_of: dict[str, str | None] = {root: None}
    queue = [root]
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        visited_order.append(node)
        for nb in adjacency[node]:
            if nb not in parent_of:
                parent_of[nb] = node
                queue.append(nb)

    # Messages: (src, dst) -> Factor
    messages: dict[tuple[str, str], Factor] = {}

    # Working copies of potentials
    updated = {cid: (vars_t, dict(tab)) for cid, (vars_t, tab) in potential_tables.items()}

    # Collect phase: leaves to root (reverse BFS order)
    for node in reversed(visited_order):
        par = parent_of[node]
        if par is None:
            continue
        sep = separator_for[(node, par)]
        # Message = product of node's potential with all incoming messages except to par,
        # marginalized down to the separator
        product = updated[node]
        for nb in adjacency[node]:
            if nb != par and (nb, node) in messages:
                product = _factor_multiply(product, messages[(nb, node)])
        eliminate = frozenset(clique_node_sets[node]) - sep
        msg = _factor_marginalize(product, eliminate)
        messages[(node, par)] = msg

    # Distribute phase: root to leaves (BFS order)
    for node in visited_order:
        par = parent_of[node]
        if par is None:
            continue
        sep = separator_for[(par, node)]
        product = updated[par]
        for nb in adjacency[par]:
            if nb != node and (nb, par) in messages:
                product = _factor_multiply(product, messages[(nb, par)])
        eliminate = frozenset(clique_node_sets[par]) - sep
        msg = _factor_marginalize(product, eliminate)
        messages[(par, node)] = msg

    # Update clique beliefs: potential * all incoming messages
    beliefs: dict[str, Factor] = {}
    for c in cliques:
        belief = updated[c.id]
        for nb in adjacency[c.id]:
            if (nb, c.id) in messages:
                belief = _factor_multiply(belief, messages[(nb, c.id)])
        beliefs[c.id] = belief

    return beliefs


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


def _get_beliefs(artifact: JunctionTreeCompileArtifact) -> dict[str, Factor]:
    """Run belief propagation on the artifact's potential tables."""
    if artifact.potential_tables is None:
        raise InferenceQueryError(
            "Artifact has no potential tables — compile with CPTs first",
            details={"compileId": artifact.compile_id},
        )
    return _run_belief_propagation(
        artifact.cliques,
        artifact.separator_sets,
        artifact.message_schedule,
        artifact.potential_tables,  # type: ignore[arg-type]
    )


def _extract_variable_marginal(
    beliefs: dict[str, Factor],
    cliques: tuple[CliqueSummary, ...],
    variable_id: str,
) -> dict[str, float]:
    """Find a clique containing the variable and marginalize to get its marginal."""
    for c in cliques:
        if variable_id in c.nodes:
            belief = beliefs[c.id]
            eliminate = frozenset(c.nodes) - {variable_id}
            marginal = _factor_marginalize(belief, eliminate)
            marginal = _factor_normalize(marginal)
            _, tab = marginal
            return {k[0]: v for k, v in tab.items()}
    raise InferenceQueryError(
        f"Variable '{variable_id}' not found in any clique",
        details={"variableId": variable_id},
    )


@dataclass(frozen=True)
class JunctionTreeQueryBackend(InferenceQueryBackend):
    """Execute queries against junction-tree compiled artifacts via Shafer-Shenoy."""

    def query_marginals(
        self,
        compile_result: CompileResult,
        *,
        context: Mapping[str, str] | None = None,
    ) -> MarginalQueryResult:
        """Compute marginal probabilities for all variables via belief propagation."""
        started_at = time.perf_counter()
        artifact = _require_junction_tree_artifact(compile_result)
        beliefs = _get_beliefs(artifact)

        all_marginals: dict[str, float] = {}
        for var_id in artifact.variable_ids:
            marginal = _extract_variable_marginal(beliefs, artifact.cliques, var_id)
            all_marginals.update(marginal)

        runtime_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
        return MarginalQueryResult(
            marginals=all_marginals,
            runtime_ms=runtime_ms,
            compile_id=artifact.compile_id,
        )

    def query_atomic_event(
        self,
        compile_result: CompileResult,
        *,
        variable_id: str,
        outcome_id: str,
        negated: bool = False,
    ) -> AtomicEventQueryResult:
        """Return the probability of a single variable-outcome pair."""
        started_at = time.perf_counter()
        artifact = _require_junction_tree_artifact(compile_result)
        beliefs = _get_beliefs(artifact)

        marginal = _extract_variable_marginal(beliefs, artifact.cliques, variable_id)
        p = marginal.get(outcome_id, 0.0)
        if negated:
            p = 1.0 - p

        runtime_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
        return AtomicEventQueryResult(
            variable_id=variable_id,
            outcome_id=outcome_id,
            probability=p,
            runtime_ms=runtime_ms,
            compile_id=artifact.compile_id,
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
