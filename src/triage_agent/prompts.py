"""Prompt templates. Each builder returns the message list for one LLM call."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .models import CodeHit, Critique, DuplicateCandidate, FixPlan, Issue

CLASSIFY_SYSTEM = """\
You triage incoming bug reports for a software project. Pick exactly one category:

- needs_info: a maintainer could not start investigating without more detail \
(version, environment, steps to reproduce, expected vs actual behaviour, logs). \
List exactly what is missing in missing_info.
- duplicate: the report describes the same underlying problem as one of the candidate \
issues provided. Only choose this when a candidate clearly matches, and set duplicate_of \
to that candidate's number. Never use a number that is not in the candidate list.
- real_bug: the report is specific enough to begin investigating.

When unsure between needs_info and real_bug, choose needs_info."""

REQUEST_INFO_SYSTEM = """\
You write GitHub comments on behalf of project maintainers. Thank the reporter in one short \
sentence, then ask for the missing details as a Markdown checklist. Be friendly and concise. \
Output only the comment body, with no preamble."""

PLAN_SYSTEM = """\
You are a senior engineer writing a fix plan for a confirmed bug. Ground the plan in the code \
context provided: only list files that appear there, and if none look relevant, leave files \
empty and say so in suspected_cause. Steps must be concrete and ordered. Always include at \
least one regression test."""

REVIEW_SYSTEM = """\
You are a strict code reviewer checking a fix plan before it is shared. Approve only if all \
of these hold:
1. The plan addresses the symptom described in the report.
2. The steps are concrete and in a sensible order.
3. It includes at least one regression test.
4. Every file it lists appears in the code context.
Otherwise set approved to false and list each problem as a specific, actionable sentence."""


def format_candidates(candidates: Sequence[DuplicateCandidate]) -> str:
    if not candidates:
        return "(no similar issues found)"
    return "\n".join(f"#{c.number}: {c.title} (similarity {c.score:.2f})" for c in candidates)


def format_code_hits(hits: Sequence[CodeHit]) -> str:
    if not hits:
        return "(no code context available)"
    return "\n".join(f"{h.path}:{h.line}: {h.snippet}" for h in hits)


def _issue_block(issue: Issue) -> str:
    return f"<issue>\nTitle: {issue.title}\n\n{issue.body or '(no description)'}\n</issue>"


def classify_messages(issue: Issue, candidates: Sequence[DuplicateCandidate]) -> list[BaseMessage]:
    return [
        SystemMessage(CLASSIFY_SYSTEM),
        HumanMessage(
            f"{_issue_block(issue)}\n\n"
            f"<candidate_duplicates>\n{format_candidates(candidates)}\n</candidate_duplicates>"
        ),
    ]


def request_info_messages(issue: Issue, missing: Sequence[str]) -> list[BaseMessage]:
    wanted = "\n".join(f"- {item}" for item in missing) or "- steps to reproduce"
    return [
        SystemMessage(REQUEST_INFO_SYSTEM),
        HumanMessage(f"{_issue_block(issue)}\n\n<missing>\n{wanted}\n</missing>"),
    ]


def plan_messages(
    issue: Issue,
    hits: Sequence[CodeHit],
    previous: FixPlan | None = None,
    critique: Critique | None = None,
) -> list[BaseMessage]:
    content = f"{_issue_block(issue)}\n\n<code_context>\n{format_code_hits(hits)}\n</code_context>"
    if previous is not None and critique is not None and not critique.approved:
        problems = "\n".join(f"- {p}" for p in critique.problems)
        content += (
            f"\n\n<previous_plan>\n{previous.to_markdown()}\n</previous_plan>"
            f"\n\n<review_problems>\n{problems}\n</review_problems>"
            "\n\nRevise the plan so that every review problem is resolved."
        )
    return [SystemMessage(PLAN_SYSTEM), HumanMessage(content)]


def review_messages(issue: Issue, hits: Sequence[CodeHit], plan: FixPlan) -> list[BaseMessage]:
    return [
        SystemMessage(REVIEW_SYSTEM),
        HumanMessage(
            f"{_issue_block(issue)}\n\n"
            f"<code_context>\n{format_code_hits(hits)}\n</code_context>\n\n"
            f"<plan>\n{plan.to_markdown()}\n</plan>"
        ),
    ]
