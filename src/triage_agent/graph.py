"""Graph assembly and helpers for driving the human-review interrupt."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from .models import CHECKPOINT_TYPES, ReviewDecision
from .nodes import Dependencies, TriageNodes
from .routing import (
    CLASSIFY,
    DRAFT_PLAN,
    FIND_DUPLICATES,
    HUMAN_REVIEW,
    LOCATE_CODE,
    MARK_DUPLICATE,
    POST_COMMENT,
    REQUEST_INFO,
    REVIEW_PLAN,
    WRITE_PLAN_COMMENT,
    make_review_router,
    route_after_classify,
    route_after_human,
)
from .state import TriageState


def build_graph(
    deps: Dependencies, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Compile the triage workflow.

    A checkpointer is required because the run pauses for human review; an in-memory
    one is used unless another is supplied. A custom checkpointer's serializer must
    allow the types in ``models.CHECKPOINT_TYPES``.
    """
    nodes = TriageNodes(deps)
    graph = StateGraph(TriageState)

    graph.add_node(FIND_DUPLICATES, nodes.find_duplicates)
    graph.add_node(CLASSIFY, nodes.classify)
    graph.add_node(REQUEST_INFO, nodes.request_info)
    graph.add_node(MARK_DUPLICATE, nodes.mark_duplicate)
    graph.add_node(LOCATE_CODE, nodes.locate_code)
    graph.add_node(DRAFT_PLAN, nodes.draft_plan)
    graph.add_node(REVIEW_PLAN, nodes.review_plan)
    graph.add_node(WRITE_PLAN_COMMENT, nodes.write_plan_comment)
    graph.add_node(HUMAN_REVIEW, nodes.human_review)
    graph.add_node(POST_COMMENT, nodes.post_comment)

    graph.add_edge(START, FIND_DUPLICATES)
    graph.add_edge(FIND_DUPLICATES, CLASSIFY)
    graph.add_conditional_edges(
        CLASSIFY, route_after_classify, [REQUEST_INFO, MARK_DUPLICATE, LOCATE_CODE]
    )
    graph.add_edge(LOCATE_CODE, DRAFT_PLAN)
    graph.add_edge(DRAFT_PLAN, REVIEW_PLAN)
    graph.add_conditional_edges(
        REVIEW_PLAN, make_review_router(deps.max_revisions), [DRAFT_PLAN, WRITE_PLAN_COMMENT]
    )
    for outcome in (REQUEST_INFO, MARK_DUPLICATE, WRITE_PLAN_COMMENT):
        graph.add_edge(outcome, HUMAN_REVIEW)
    graph.add_conditional_edges(HUMAN_REVIEW, route_after_human, [POST_COMMENT, END])
    graph.add_edge(POST_COMMENT, END)

    return graph.compile(checkpointer=checkpointer or default_checkpointer())


def default_checkpointer() -> InMemorySaver:
    """In-memory checkpointer whose serializer is allowed to restore this package's models.

    Without the explicit allowlist LangGraph logs an "unregistered type" warning on every
    restore, and strict mode (``LANGGRAPH_STRICT_MSGPACK=true``) refuses to restore them.
    """
    allowed = [(t.__module__, t.__name__) for t in CHECKPOINT_TYPES]
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


def thread_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def pending_review(graph: CompiledStateGraph, config: RunnableConfig) -> dict[str, Any] | None:
    """The payload of the human-review interrupt, or None if the run is not waiting on one."""
    for task in graph.get_state(config).tasks:
        for pending in task.interrupts:
            return pending.value
    return None


def resume(
    graph: CompiledStateGraph, config: RunnableConfig, decision: ReviewDecision
) -> TriageState:
    """Answer the human-review interrupt and run the graph to completion."""
    return graph.invoke(Command(resume=decision.model_dump(mode="json")), config)
