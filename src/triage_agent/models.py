"""Domain models and the structured outputs requested from the LLM."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Issue(BaseModel):
    title: str
    body: str = ""
    number: int | None = None
    url: str | None = None

    @property
    def label(self) -> str:
        return f"#{self.number}" if self.number is not None else repr(self.title)

    @property
    def text(self) -> str:
        return f"{self.title}\n\n{self.body}".strip()


class DuplicateCandidate(BaseModel):
    number: int
    title: str
    score: float
    url: str | None = None


class CodeHit(BaseModel):
    path: str
    line: int
    snippet: str
    score: float


class Category(str, Enum):
    NEEDS_INFO = "needs_info"
    DUPLICATE = "duplicate"
    REAL_BUG = "real_bug"


class Classification(BaseModel):
    """Triage decision for a single bug report."""

    category: Category
    rationale: str = Field(description="One or two sentences explaining the decision.")
    duplicate_of: int | None = Field(
        default=None,
        description="Number of the original issue. Only set when category is 'duplicate'.",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Specific details the reporter must provide. Only set for 'needs_info'.",
    )


class FixPlan(BaseModel):
    """A concrete plan for fixing a confirmed bug."""

    summary: str = Field(description="One sentence describing the fix.")
    suspected_cause: str = Field(description="Most likely root cause, with the evidence for it.")
    steps: list[str] = Field(min_length=1, description="Ordered implementation steps.")
    files: list[str] = Field(
        default_factory=list, description="Files to change, taken from the code context."
    )
    tests: list[str] = Field(default_factory=list, description="Regression tests to add.")
    risks: list[str] = Field(default_factory=list, description="Side effects to watch for.")

    def to_markdown(self) -> str:
        parts = [
            f"**Summary:** {self.summary}",
            f"**Suspected cause:** {self.suspected_cause}",
            "**Steps:**\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(self.steps, 1)),
        ]
        for heading, items in (("Files", self.files), ("Tests", self.tests), ("Risks", self.risks)):
            if items:
                parts.append(f"**{heading}:**\n" + "\n".join(f"- {item}" for item in items))
        return "\n\n".join(parts)


class Critique(BaseModel):
    """Review verdict on a fix plan."""

    approved: bool = Field(description="True only if the plan needs no further changes.")
    problems: list[str] = Field(
        default_factory=list, description="Concrete problems to fix. Empty when approved."
    )


class ReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class ReviewDecision(BaseModel):
    """A human reviewer's answer to the approval interrupt."""

    action: ReviewAction
    comment: str | None = None

    @model_validator(mode="after")
    def _edit_needs_comment(self) -> ReviewDecision:
        if self.action is ReviewAction.EDIT and not (self.comment and self.comment.strip()):
            raise ValueError("an 'edit' decision must include the replacement comment")
        return self


# Types stored in TriageState, which the checkpointer must be allowed to restore.
CHECKPOINT_TYPES: tuple[type, ...] = (
    Issue,
    DuplicateCandidate,
    CodeHit,
    Category,
    Classification,
    FixPlan,
    Critique,
    ReviewAction,
    ReviewDecision,
)
