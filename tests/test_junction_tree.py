"""Tests for the bounded-treewidth junction tree inference module."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from backend.inference import (
    BayesianNetworkGraph,
    CliqueSummary,
    CompileResult,
    InferenceQueryError,
    InferenceUnsupportedQueryError,
    JUNCTION_TREE_COMPILER,
    JUNCTION_TREE_EXACT_ELIGIBILITY_REASON,
    JUNCTION_TREE_QUERY_BACKEND,
    JunctionTreeCompileArtifact,
    JunctionTreeCompiler,
    JunctionTreeQueryBackend,
    VariableNode,
    DirectedEdge,
)


def _three_node_chain_graph() -> BayesianNetworkGraph:
    """A -> B -> C chain graph for testing."""
    return {
        "variables": [
            {"id": "A", "outcomes": ["a0", "a1"]},
            {"id": "B", "outcomes": ["b0", "b1"]},
            {"id": "C", "outcomes": ["c0", "c1"]},
        ],
        "edges": [
            {"parent": "A", "child": "B"},
            {"parent": "B", "child": "C"},
        ],
        "cpts": {},
    }


def _diamond_graph() -> BayesianNetworkGraph:
    """A diamond: A -> B, A -> C, B -> D, C -> D."""
    return {
        "variables": [
            {"id": "A", "outcomes": ["a0", "a1"]},
            {"id": "B", "outcomes": ["b0", "b1"]},
            {"id": "C", "outcomes": ["c0", "c1"]},
            {"id": "D", "outcomes": ["d0", "d1"]},
        ],
        "edges": [
            {"parent": "A", "child": "B"},
            {"parent": "A", "child": "C"},
            {"parent": "B", "child": "D"},
            {"parent": "C", "child": "D"},
        ],
        "cpts": {},
    }


class TestJunctionTreeCompileArtifact(unittest.TestCase):
    """Test JunctionTreeCompileArtifact construction and to_compile_result."""

    def _make_artifact(self, **overrides) -> JunctionTreeCompileArtifact:
        defaults = {
            "market_id": "net1",
            "variable_ids": ("A", "B", "C"),
            "cliques": (
                CliqueSummary(id="jt-c0", nodes=("A", "B"), size=2, states=4),
                CliqueSummary(id="jt-c1", nodes=("B", "C"), size=2, states=4),
            ),
            "separator_sets": (frozenset({"B"}),),
            "elimination_ordering": ("A", "C", "B"),
            "message_schedule": (("jt-c0", "jt-c1"), ("jt-c1", "jt-c0")),
            "potential_tables": None,
            "junction_tree_width": 1,
            "exact_eligible": True,
            "eligibility_reason": JUNCTION_TREE_EXACT_ELIGIBILITY_REASON,
            "source_state_hash": "sha256:abc123",
            "compile_id": "comp-abc123",
            "compile_type": "junction_tree",
            "memory_bytes": 384,
        }
        defaults.update(overrides)
        return JunctionTreeCompileArtifact(**defaults)

    def test_construction_and_field_access(self):
        artifact = self._make_artifact()

        self.assertEqual(artifact.market_id, "net1")
        self.assertEqual(artifact.variable_ids, ("A", "B", "C"))
        self.assertEqual(len(artifact.cliques), 2)
        self.assertEqual(artifact.separator_sets, (frozenset({"B"}),))
        self.assertEqual(artifact.elimination_ordering, ("A", "C", "B"))
        self.assertEqual(artifact.message_schedule, (("jt-c0", "jt-c1"), ("jt-c1", "jt-c0")))
        self.assertIsNone(artifact.potential_tables)
        self.assertEqual(artifact.junction_tree_width, 1)
        self.assertTrue(artifact.exact_eligible)
        self.assertEqual(artifact.eligibility_reason, JUNCTION_TREE_EXACT_ELIGIBILITY_REASON)
        self.assertEqual(artifact.compile_type, "junction_tree")

    def test_immutability(self):
        artifact = self._make_artifact()

        with self.assertRaises(FrozenInstanceError):
            artifact.market_id = "net2"  # type: ignore[misc]

    def test_to_compile_result_round_trip(self):
        artifact = self._make_artifact()
        result = artifact.to_compile_result(
            compile_time_ms=1.5,
            last_updated="2026-04-11T00:00:00Z",
        )

        self.assertIsInstance(result, CompileResult)
        self.assertEqual(result.compile_id, artifact.compile_id)
        self.assertEqual(result.compile_type, artifact.compile_type)
        self.assertEqual(result.source_state_hash, artifact.source_state_hash)
        self.assertEqual(result.cliques, artifact.cliques)
        self.assertEqual(result.memory_bytes, artifact.memory_bytes)
        self.assertEqual(result.compile_time_ms, 1.5)
        self.assertEqual(result.last_updated, "2026-04-11T00:00:00Z")
        self.assertIs(result.artifact, artifact)

    def test_validation_rejects_empty_market_id(self):
        with self.assertRaises(ValueError):
            self._make_artifact(market_id="")

    def test_validation_rejects_negative_treewidth(self):
        with self.assertRaises(ValueError):
            self._make_artifact(junction_tree_width=-1)

    def test_validation_rejects_negative_memory_bytes(self):
        with self.assertRaises(ValueError):
            self._make_artifact(memory_bytes=-1)

    def test_validation_rejects_empty_eligibility_reason(self):
        with self.assertRaises(ValueError):
            self._make_artifact(eligibility_reason="")

    def test_tuples_are_normalized(self):
        """Lists passed for tuple fields are normalized to tuples."""
        artifact = self._make_artifact(
            variable_ids=["X", "Y"],
            elimination_ordering=["Y", "X"],
        )
        self.assertIsInstance(artifact.variable_ids, tuple)
        self.assertIsInstance(artifact.elimination_ordering, tuple)


class TestJunctionTreeCompiler(unittest.TestCase):
    """Test JunctionTreeCompiler compilation logic."""

    def test_compile_market_raises_unsupported(self):
        with self.assertRaises(InferenceUnsupportedQueryError) as ctx:
            JUNCTION_TREE_COMPILER.compile_market(
                market_id="m1",
                source_state_hash="sha256:abc",
            )
        self.assertIn("compile_network", str(ctx.exception))

    def test_compile_network_three_node_chain(self):
        graph = _three_node_chain_graph()
        result = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            market_id="chain3",
            elimination_ordering=("A", "C", "B"),
            last_updated="2026-04-11T00:00:00Z",
        )

        self.assertIsInstance(result, CompileResult)
        self.assertEqual(result.compile_type, "junction_tree")
        self.assertEqual(result.last_updated, "2026-04-11T00:00:00Z")

        artifact = result.artifact
        self.assertIsInstance(artifact, JunctionTreeCompileArtifact)
        self.assertEqual(artifact.market_id, "chain3")
        self.assertEqual(artifact.variable_ids, ("A", "B", "C"))
        self.assertEqual(artifact.elimination_ordering, ("A", "C", "B"))
        self.assertIsNone(artifact.potential_tables)
        self.assertTrue(artifact.exact_eligible)

        # A->B->C chain: eliminating A gives clique {A,B}, eliminating C gives {B,C}
        # treewidth should be 1
        self.assertEqual(artifact.junction_tree_width, 1)
        self.assertTrue(len(artifact.cliques) >= 2)

        # All variable_ids should appear in at least one clique
        all_clique_vars = set()
        for clique in artifact.cliques:
            all_clique_vars.update(clique.nodes)
        self.assertEqual(all_clique_vars, {"A", "B", "C"})

    def test_compile_network_diamond_graph(self):
        graph = _diamond_graph()
        # Eliminate A first, then D, then B, then C
        result = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            market_id="diamond",
            elimination_ordering=("A", "D", "B", "C"),
            last_updated="2026-04-11T00:00:00Z",
        )

        artifact = result.artifact
        self.assertIsInstance(artifact, JunctionTreeCompileArtifact)
        self.assertEqual(artifact.variable_ids, ("A", "B", "C", "D"))
        self.assertTrue(artifact.exact_eligible)

        # All variables should appear in cliques
        all_clique_vars = set()
        for clique in artifact.cliques:
            all_clique_vars.update(clique.nodes)
        self.assertEqual(all_clique_vars, {"A", "B", "C", "D"})

    def test_compile_network_deterministic_hash(self):
        graph = _three_node_chain_graph()
        result1 = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )
        result2 = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )
        self.assertEqual(result1.source_state_hash, result2.source_state_hash)
        self.assertEqual(result1.compile_id, result2.compile_id)

    def test_treewidth_bound_sets_exact_eligible_false(self):
        graph = _three_node_chain_graph()
        compiler = JunctionTreeCompiler(max_treewidth=0)
        result = compiler.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )

        artifact = result.artifact
        self.assertIsInstance(artifact, JunctionTreeCompileArtifact)
        self.assertFalse(artifact.exact_eligible)
        self.assertIn("exceeds_bound", artifact.eligibility_reason)

    def test_triangulate_placeholder_raises(self):
        graph = _three_node_chain_graph()
        with self.assertRaises(InferenceUnsupportedQueryError) as ctx:
            JUNCTION_TREE_COMPILER.compile_network(
                graph=graph,
                # no elimination_ordering provided
            )
        self.assertIn("triangulation", str(ctx.exception))

    def test_separator_sets_computed(self):
        graph = _three_node_chain_graph()
        result = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )
        artifact = result.artifact
        # Chain A-B-C with cliques {A,B} and {B,C}: separator is {B}
        self.assertTrue(len(artifact.separator_sets) > 0)
        has_b_separator = any(frozenset({"B"}) == s for s in artifact.separator_sets)
        self.assertTrue(has_b_separator)

    def test_message_schedule_computed(self):
        graph = _three_node_chain_graph()
        result = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )
        artifact = result.artifact
        # Should have bidirectional messages between adjacent cliques
        self.assertTrue(len(artifact.message_schedule) > 0)
        # Each entry is a tuple of two clique ids
        for src, dst in artifact.message_schedule:
            self.assertIsInstance(src, str)
            self.assertIsInstance(dst, str)

    def test_memory_bytes_positive(self):
        graph = _three_node_chain_graph()
        result = JUNCTION_TREE_COMPILER.compile_network(
            graph=graph,
            elimination_ordering=("A", "C", "B"),
        )
        self.assertGreater(result.memory_bytes, 0)


class TestJunctionTreeQueryBackend(unittest.TestCase):
    """Test JunctionTreeQueryBackend placeholder behavior."""

    def _compile_chain(self, *, max_treewidth: int = 15) -> CompileResult:
        compiler = JunctionTreeCompiler(max_treewidth=max_treewidth)
        return compiler.compile_network(
            graph=_three_node_chain_graph(),
            elimination_ordering=("A", "C", "B"),
            last_updated="2026-04-11T00:00:00Z",
        )

    def test_query_marginals_raises_unsupported(self):
        result = self._compile_chain()
        with self.assertRaises(InferenceUnsupportedQueryError) as ctx:
            JUNCTION_TREE_QUERY_BACKEND.query_marginals(result)
        self.assertIn("not yet implemented", str(ctx.exception))

    def test_query_atomic_event_raises_unsupported(self):
        result = self._compile_chain()
        with self.assertRaises(InferenceUnsupportedQueryError) as ctx:
            JUNCTION_TREE_QUERY_BACKEND.query_atomic_event(
                result,
                variable_id="A",
                outcome_id="a0",
            )
        self.assertIn("not yet implemented", str(ctx.exception))

    def test_query_marginals_validates_artifact_presence(self):
        result = replace(self._compile_chain(), artifact=None)
        with self.assertRaises(InferenceQueryError):
            JUNCTION_TREE_QUERY_BACKEND.query_marginals(result)

    def test_query_marginals_validates_artifact_type(self):
        result = replace(self._compile_chain(), artifact="not-an-artifact")
        with self.assertRaises(InferenceQueryError) as ctx:
            JUNCTION_TREE_QUERY_BACKEND.query_marginals(result)
        self.assertIn("not a junction-tree artifact", str(ctx.exception))

    def test_query_marginals_validates_compile_id_match(self):
        result = replace(self._compile_chain(), compile_id="comp-mismatch")
        with self.assertRaises(InferenceQueryError):
            JUNCTION_TREE_QUERY_BACKEND.query_marginals(result)

    def test_query_rejects_ineligible_artifact(self):
        result = self._compile_chain(max_treewidth=0)
        with self.assertRaises(InferenceUnsupportedQueryError) as ctx:
            JUNCTION_TREE_QUERY_BACKEND.query_marginals(result)
        self.assertIn("not eligible", str(ctx.exception))


class TestJunctionTreeImports(unittest.TestCase):
    """Test that all public names are importable from backend.inference."""

    def test_all_public_names_importable(self):
        from backend.inference import (
            BayesianNetworkGraph,
            DirectedEdge,
            JUNCTION_TREE_COMPILER,
            JUNCTION_TREE_EXACT_ELIGIBILITY_REASON,
            JUNCTION_TREE_QUERY_BACKEND,
            JunctionTreeCompileArtifact,
            JunctionTreeCompiler,
            JunctionTreeQueryBackend,
            VariableNode,
        )

        self.assertIsInstance(JUNCTION_TREE_COMPILER, JunctionTreeCompiler)
        self.assertIsInstance(JUNCTION_TREE_QUERY_BACKEND, JunctionTreeQueryBackend)
        self.assertIsInstance(JUNCTION_TREE_EXACT_ELIGIBILITY_REASON, str)
        self.assertTrue(JUNCTION_TREE_EXACT_ELIGIBILITY_REASON)

    def test_singleton_identity(self):
        self.assertIs(JUNCTION_TREE_COMPILER, JUNCTION_TREE_COMPILER)
        self.assertIs(JUNCTION_TREE_QUERY_BACKEND, JUNCTION_TREE_QUERY_BACKEND)


if __name__ == "__main__":
    unittest.main()
