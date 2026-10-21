"""Deterministic comment bodies for outcomes that do not need an LLM to phrase them."""

from __future__ import annotations

from .models import Critique, DuplicateCandidate, FixPlan


def duplicate_comment(original: DuplicateCandidate) -> str:
    return (
        f"Thanks for the report! This looks like a duplicate of #{original.number} "
        f"({original.title}). Please follow that issue and add any extra details there."
    )


def plan_comment(plan: FixPlan, critique: Critique | None, revisions: int) -> str:
    body = f"Thanks for the report. This has been triaged as a bug.\n\n{plan.to_markdown()}"
    if critique is not None and not critique.approved:
        open_problems = "\n".join(f"- {p}" for p in critique.problems)
        body += (
            f"\n\n> **Note:** this plan did not pass automated review after {revisions} "
            f"revision(s). Open points:\n>\n"
            + "\n".join(f"> {line}" for line in open_problems.splitlines())
        )
    return body
