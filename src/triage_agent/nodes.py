"""Graph node implementations.

Every node takes the current ``TriageState`` and returns a partial update. External
services are injected through ``Dependencies`` so the graph can run against fakes in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langgraph.types import interrupt

from . import comments, prompts
from .llm import structured
from .models import Classification, Critique, FixPlan, ReviewAction, ReviewDecision
from .state import TriageState
from .text import extract_identifiers
from .tools import (
    CodeSearcher,
    CommentPoster,
    ConsolePoster,
    DuplicateFinder,
    NullCodeSearcher,
    NullDuplicateFinder,
)


@dataclass(frozen=True)
class Dependencies:
    model: BaseChatModel
    """Model used for writing: info requests and fix plans."""

    fast_model: BaseChatModel | None = None
    """Cheaper model for classification and plan review. Falls back to ``model``."""

    duplicate_finder: DuplicateFinder = field(default_factory=NullDuplicateFinder)
    code_searcher: CodeSearcher = field(default_factory=NullCodeSearcher)
    poster: CommentPoster = field(default_factory=ConsolePoster)
    max_revisions: int = 3

    def __post_init__(self) -> None:
        if self.max_revisions < 1:
            raise ValueError("max_revisions must be at least 1")


class TriageNodes:
    def __init__(self, deps: Dependencies):
        self._deps = deps
        self._fast_model = deps.fast_model or deps.model

    def find_duplicates(self, state: TriageState) -> TriageState:
        return {"duplicate_candidates": self._deps.duplicate_finder.find(state["issue"])}

    def classify(self, state: TriageState) -> TriageState:
        messages = prompts.classify_messages(state["issue"], state.get("duplicate_candidates", []))
        classification = structured(self._fast_model, Classification).invoke(messages)
        return {"classification": classification}

    def request_info(self, state: TriageState) -> TriageState:
        missing = state["classification"].missing_info
        reply = self._deps.model.invoke(prompts.request_info_messages(state["issue"], missing))
        return {"draft_comment": reply.text.strip()}

    def mark_duplicate(self, state: TriageState) -> TriageState:
        number = state["classification"].duplicate_of
        original = next(c for c in state["duplicate_candidates"] if c.number == number)
        return {"draft_comment": comments.duplicate_comment(original)}

    def locate_code(self, state: TriageState) -> TriageState:
        terms = extract_identifiers(state["issue"].text)
        return {"code_hits": self._deps.code_searcher.search(terms), "revisions": 0}

    def draft_plan(self, state: TriageState) -> TriageState:
        messages = prompts.plan_messages(
            state["issue"],
            state.get("code_hits", []),
            previous=state.get("plan"),
            critique=state.get("critique"),
        )
        plan = structured(self._deps.model, FixPlan).invoke(messages)
        return {"plan": plan, "revisions": state.get("revisions", 0) + 1}

    def review_plan(self, state: TriageState) -> TriageState:
        messages = prompts.review_messages(
            state["issue"], state.get("code_hits", []), state["plan"]
        )
        return {"critique": structured(self._fast_model, Critique).invoke(messages)}

    def write_plan_comment(self, state: TriageState) -> TriageState:
        body = comments.plan_comment(state["plan"], state.get("critique"), state["revisions"])
        return {"draft_comment": body}

    def human_review(self, state: TriageState) -> TriageState:
        # Pauses the run. The value passed to Command(resume=...) is returned here.
        answer = interrupt(
            {
                "issue": state["issue"].model_dump(mode="json"),
                "category": state["classification"].category.value,
                "draft_comment": state["draft_comment"],
            }
        )
        return {"decision": ReviewDecision.model_validate(answer)}

    def post_comment(self, state: TriageState) -> TriageState:
        decision = state["decision"]
        body = decision.comment if decision.action is ReviewAction.EDIT else state["draft_comment"]
        url = self._deps.poster.post(state["issue"], body)
        return {"final_comment": body, "posted_url": url}
