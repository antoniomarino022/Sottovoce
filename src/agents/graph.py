from functools import lru_cache
from typing import Any, NamedTuple, Optional

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.memory import get_checkpointer, get_thread_config
from src.agents.nodes import (
    defense_node,
    judge_node,
    prosecution_node,
    triage_node,
)
from src.agents.state import ConfessionState

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# Node names
TRIAGE = "triage"
JUDGE = "judge"
DEFENSE = "defense"
PROSECUTION = "prosecution"

# Purchasable powers
POWER_LAWYER = "ai_lawyer"
POWER_PROSECUTOR = "ai_prosecutor"

ConfessionId = int | str | None


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def route_after_triage(state: ConfessionState) -> str:
    """Go to the judge if the confession is approved, otherwise stop."""
    return JUDGE if state.get("mod_status") == "approved" else END


# --------------------------------------------------------------------------- #
# Workflows (uncompiled definitions)
# --------------------------------------------------------------------------- #
def _build_pipeline_workflow() -> StateGraph:
    """Main pipeline: START -> TRIAGE -> (JUDGE if approved) -> END."""
    graph = StateGraph(ConfessionState)
    graph.add_node(TRIAGE, triage_node)
    graph.add_node(JUDGE, judge_node)

    graph.add_edge(START, TRIAGE)
    graph.add_conditional_edges(TRIAGE, route_after_triage, {JUDGE: JUDGE, END: END})
    graph.add_edge(JUDGE, END)
    return graph


def _build_single_node_workflow(name: str, node: Any) -> StateGraph:
    """Standalone workflow with one node: START -> node -> END."""
    graph = StateGraph(ConfessionState)
    graph.add_node(name, node)
    graph.add_edge(START, name)
    graph.add_edge(name, END)
    return graph


workflow = _build_pipeline_workflow()
defense_workflow = _build_single_node_workflow(DEFENSE, defense_node)
prosecution_workflow = _build_single_node_workflow(PROSECUTION, prosecution_node)


# --------------------------------------------------------------------------- #
# Compiled graphs
# --------------------------------------------------------------------------- #
class _CompiledGraphs(NamedTuple):
    pipeline: CompiledStateGraph
    defense: CompiledStateGraph
    prosecution: CompiledStateGraph


@lru_cache(maxsize=1)
def _get_graphs() -> _CompiledGraphs:
    """Compile graphs once. Stateless one-shot personas omit checkpointer DB writes."""
    saver = get_checkpointer()
    return _CompiledGraphs(
        pipeline=workflow.compile(checkpointer=saver),
        defense=defense_workflow.compile(),
        prosecution=prosecution_workflow.compile(),
    )


def reset_compiled_graphs() -> None:
    """Drop cached graphs (call after close_checkpointer() or in tests)."""
    _get_graphs.cache_clear()


async def _run_graph(
    graph: CompiledStateGraph,
    state: ConfessionState,
    confession_id: ConfessionId,
) -> dict[str, Any]:
    """Invoke a graph using the thread config tied to the confession."""
    return await graph.ainvoke(state, config=get_thread_config(confession_id))


# --------------------------------------------------------------------------- #
# State builder
# --------------------------------------------------------------------------- #
def _build_initial_state(
    content: str,
    confession_id: ConfessionId,
    active_powers: Optional[list[str]] = None,
) -> ConfessionState:
    """Full initial state for a brand-new confession entering the pipeline."""
    return {
        "confession_id": confession_id,
        "content": content,
        "mod_status": "pending_ai",
        "severity": 0,
        "roast_allowed": True,
        "triage_reason": "",
        "ai_roast": None,
        "ai_defense": None,
        "ai_prosecution": None,
        "active_powers": active_powers or [],
        "guardrails_triggered": [],
        "messages": [HumanMessage(content=content)],
    }


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
async def run_confession_pipeline(
    content: str,
    confession_id: ConfessionId = None,
    active_powers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Triage the confession and, if approved, generate the judge's roast."""
    state = _build_initial_state(content, confession_id, active_powers)
    return await _run_graph(_get_graphs().pipeline, state, confession_id)


async def run_defense_agent(
    confession_id: ConfessionId = None,
    content: str = "",
    ai_roast: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke the defense attorney agent on demand (stateless, no checkpoint I/O)."""
    state: ConfessionState = {
        "confession_id": confession_id,
        "content": content,
        "ai_roast": ai_roast,
        "active_powers": [POWER_LAWYER],
    }
    return await _get_graphs().defense.ainvoke(state)


async def run_prosecution_agent(
    confession_id: ConfessionId = None,
    content: str = "",
    ai_roast: Optional[str] = None,
    ai_defense: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke the prosecutor agent on demand (stateless, no checkpoint I/O)."""
    state: ConfessionState = {
        "confession_id": confession_id,
        "content": content,
        "ai_roast": ai_roast,
        "ai_defense": ai_defense,
        "active_powers": [POWER_PROSECUTOR],
    }
    return await _get_graphs().prosecution.ainvoke(state)


__all__ = [
    "route_after_triage",
    "workflow",
    "defense_workflow",
    "prosecution_workflow",
    "reset_compiled_graphs",
    "run_confession_pipeline",
    "run_defense_agent",
    "run_prosecution_agent",
]