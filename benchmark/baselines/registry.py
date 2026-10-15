from __future__ import annotations

from causegraph.graph.repository import GraphRepository
from causegraph.rca import CauseGraphMethod, GraphOnlyBaseline

from benchmark.baselines.base import RcaMethod
from benchmark.baselines.graph_llm import GraphLlmBaseline
from benchmark.baselines.llm_only import LlmOnlyBaseline
from benchmark.baselines.random_baseline import RandomBaseline
from benchmark.baselines.rules_baseline import RulesBaseline

# B0-B4 plus CauseGraph (CG) itself (spec section 9.1). Ablations (spec
# section 9.2) are just CauseGraphMethod with a smaller `enabled_terms` set
# or an `intervention_scorer` -- construct one directly rather than adding
# a new registry entry per ablation.
_FACTORIES = {
    "random": lambda graph: RandomBaseline(graph),
    "rules": lambda graph: RulesBaseline(graph),
    "graph_only": lambda graph: GraphOnlyBaseline(graph),
    "llm_only": lambda graph: LlmOnlyBaseline(),
    "graph_llm": lambda graph: GraphLlmBaseline(graph),
    "causegraph": lambda graph: CauseGraphMethod(graph),
}


def get_method(method_name: str, graph: GraphRepository) -> RcaMethod:
    factory = _FACTORIES.get(method_name)
    if factory is None:
        raise ValueError(f"unknown RCA method '{method_name}'")
    return factory(graph)


def list_methods() -> list[str]:
    return sorted(_FACTORIES.keys())
