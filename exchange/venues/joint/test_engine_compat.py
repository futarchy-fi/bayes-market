import json
from pathlib import Path

SEEDS = Path(__file__).resolve().parents[3] / "backend" / "seeds_takeoff.json"


def test_inference_imports_on_modern_python():
    from backend.inference.factored_market import FactoredMarket  # noqa: F401


def test_build_from_takeoff_seeds():
    from backend.inference.factored_market import FactoredMarket
    seeds = json.loads(SEEDS.read_text())
    # build nodes the same way bayes server does: markets list with cpt/priors
    from exchange.venues.joint.venue import nodes_from_seeds
    nodes = nodes_from_seeds(seeds)
    fm = FactoredMarket.from_nodes(nodes, liquidity=50.0, max_width=8)
    assert len(fm.variables()) > 900
    m = fm.marginal("ftm_agi_by_2040")
    assert m is not None and 0.0 < m["yes"] < 1.0
