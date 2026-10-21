"""Shared graph state. Each node returns a partial update that LangGraph merges in."""

from typing import TypedDict

from .models import (
    Classification,
    CodeHit,
    Critique,
    DuplicateCandidate,
    FixPlan,
    Issue,
    ReviewDecision,
)


class TriageState(TypedDict, total=False):
    # Input
    issue: Issue

    # Retrieval
    duplicate_candidates: list[DuplicateCandidate]
    code_hits: list[CodeHit]

    # LLM decisions
    classification: Classification
    plan: FixPlan
    critique: Critique
    revisions: int

    # Output
    draft_comment: str
    decision: ReviewDecision
    final_comment: str
    posted_url: str | None
