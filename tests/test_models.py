import pytest
from pydantic import ValidationError

from triage_agent.comments import duplicate_comment, plan_comment
from triage_agent.models import (
    Critique,
    DuplicateCandidate,
    FixPlan,
    Issue,
    ReviewAction,
    ReviewDecision,
)

PLAN = FixPlan(
    summary="Default the missing network section.",
    suspected_cause="load_config indexes raw['network'] unconditionally.",
    steps=["Use raw.get('network', {})", "Fall back to the default timeout"],
    files=["app/config/loader.py"],
    tests=["Load a v2.2 config without a network section"],
)


def test_issue_label_and_text():
    assert Issue(number=7, title="t").label == "#7"
    assert Issue(title="Broken").label == "'Broken'"
    assert Issue(title="Title", body="Body").text == "Title\n\nBody"


def test_fix_plan_requires_steps():
    with pytest.raises(ValidationError):
        FixPlan(summary="s", suspected_cause="c", steps=[])


def test_fix_plan_markdown_skips_empty_sections():
    markdown = PLAN.to_markdown()
    assert "1. Use raw.get('network', {})" in markdown
    assert "**Files:**\n- app/config/loader.py" in markdown
    assert "**Risks:**" not in markdown


def test_edit_decision_requires_comment():
    with pytest.raises(ValidationError):
        ReviewDecision(action=ReviewAction.EDIT, comment="  ")
    assert ReviewDecision(action="edit", comment="new text").comment == "new text"


def test_duplicate_comment_links_original():
    original = DuplicateCandidate(number=117, title="KeyError in load_config", score=0.8)
    assert "#117" in duplicate_comment(original)


def test_plan_comment_flags_unapproved_plan():
    rejected = Critique(approved=False, problems=["No regression test"])
    assert "did not pass automated review after 3" in plan_comment(PLAN, rejected, 3)
    assert "> - No regression test" in plan_comment(PLAN, rejected, 3)
    assert "Note" not in plan_comment(PLAN, Critique(approved=True), 1)
