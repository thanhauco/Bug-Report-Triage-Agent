"""Node names and the conditional-edge routers that choose between them."""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END

from .models import Category, ReviewAction
from .state import TriageState

FIND_DUPLICATES = "find_duplicates"
CLASSIFY = "classify"
REQUEST_INFO = "request_info"
MARK_DUPLICATE = "mark_duplicate"
LOCATE_CODE = "locate_code"
DRAFT_PLAN = "draft_plan"
REVIEW_PLAN = "review_plan"
WRITE_PLAN_COMMENT = "write_plan_comment"
HUMAN_REVIEW = "human_review"
POST_COMMENT = "post_comment"


def route_after_classify(state: TriageState) -> str:
    classification = state["classification"]
    if classification.category is Category.NEEDS_INFO:
        return REQUEST_INFO
    if classification.category is Category.DUPLICATE:
        # Trust a duplicate verdict only if it names one of the retrieved candidates;
        # otherwise the model invented a number, so investigate the report as a bug.
        known = {c.number for c in state.get("duplicate_candidates", [])}
        if classification.duplicate_of in known:
            return MARK_DUPLICATE
    return LOCATE_CODE


def make_review_router(max_revisions: int) -> Callable[[TriageState], str]:
    def route_after_review(state: TriageState) -> str:
        if state["critique"].approved or state["revisions"] >= max_revisions:
            return WRITE_PLAN_COMMENT
        return DRAFT_PLAN

    return route_after_review


def route_after_human(state: TriageState) -> str:
    return END if state["decision"].action is ReviewAction.REJECT else POST_COMMENT
