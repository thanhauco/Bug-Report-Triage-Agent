import pytest
from langgraph.graph import END

from triage_agent import (
    Dependencies,
    ReviewAction,
    ReviewDecision,
    build_graph,
    pending_review,
    resume,
    thread_config,
)
from triage_agent.models import (
    Category,
    Classification,
    CodeHit,
    Critique,
    DuplicateCandidate,
    FixPlan,
)
from triage_agent.routing import (
    DRAFT_PLAN,
    LOCATE_CODE,
    MARK_DUPLICATE,
    POST_COMMENT,
    REQUEST_INFO,
    WRITE_PLAN_COMMENT,
    make_review_router,
    route_after_classify,
    route_after_human,
)

CANDIDATE = DuplicateCandidate(number=117, title="KeyError in load_config", score=0.7)
HIT = CodeHit(path="app/config/loader.py", line=2, snippet="def load_config(raw):", score=3.0)
PLAN = FixPlan(
    summary="Default the network section.",
    suspected_cause="load_config assumes raw['network'] exists.",
    steps=["Use raw.get('network', {})"],
    files=["app/config/loader.py"],
    tests=["Load a config without a network section"],
)
APPROVED = Critique(approved=True)
REJECTED = Critique(approved=False, problems=["Missing regression test"])


class StubDuplicateFinder:
    def __init__(self, candidates):
        self.candidates = candidates

    def find(self, issue):
        return list(self.candidates)


class StubCodeSearcher:
    def __init__(self):
        self.terms = None

    def search(self, terms):
        self.terms = list(terms)
        return [HIT]


def classification(category, **kwargs):
    return Classification(category=category, rationale="because", **kwargs)


class TestRouting:
    @pytest.mark.parametrize(
        ("result", "candidates", "expected"),
        [
            (classification(Category.NEEDS_INFO), [], REQUEST_INFO),
            (classification(Category.REAL_BUG), [], LOCATE_CODE),
            (classification(Category.DUPLICATE, duplicate_of=117), [CANDIDATE], MARK_DUPLICATE),
            # A duplicate number that was never retrieved is treated as a hallucination.
            (classification(Category.DUPLICATE, duplicate_of=999), [CANDIDATE], LOCATE_CODE),
            (classification(Category.DUPLICATE), [CANDIDATE], LOCATE_CODE),
        ],
    )
    def test_after_classify(self, result, candidates, expected):
        state = {"classification": result, "duplicate_candidates": candidates}
        assert route_after_classify(state) == expected

    def test_after_review(self):
        route = make_review_router(max_revisions=2)
        assert route({"critique": APPROVED, "revisions": 1}) == WRITE_PLAN_COMMENT
        assert route({"critique": REJECTED, "revisions": 1}) == DRAFT_PLAN
        assert route({"critique": REJECTED, "revisions": 2}) == WRITE_PLAN_COMMENT

    def test_after_human(self):
        assert route_after_human({"decision": ReviewDecision(action="reject")}) == END
        assert route_after_human({"decision": ReviewDecision(action="approve")}) == POST_COMMENT


@pytest.fixture
def run(fake_model, poster):
    """Run a fresh graph until the human-review interrupt and return (graph, config, payload)."""

    def _run(issue, *, candidates=(), searcher=None, max_revisions=3):
        deps = Dependencies(
            model=fake_model,
            duplicate_finder=StubDuplicateFinder(candidates),
            code_searcher=searcher or StubCodeSearcher(),
            poster=poster,
            max_revisions=max_revisions,
        )
        graph = build_graph(deps)
        config = thread_config("test")
        graph.invoke({"issue": issue}, config)
        return graph, config, pending_review(graph, config)

    return _run


def test_needs_info_path(run, fake_model, poster, crash_issue):
    fake_model.queue(
        classification(Category.NEEDS_INFO, missing_info=["App version"]),
        "Thanks! Could you share:\n- [ ] App version",
    )
    graph, config, payload = run(crash_issue)

    assert payload["category"] == "needs_info"
    assert payload["draft_comment"].startswith("Thanks!")
    assert "App version" in fake_model.calls_for(None)[0][1].content
    assert poster.posted == []

    result = resume(graph, config, ReviewDecision(action=ReviewAction.APPROVE))
    assert poster.posted == [(crash_issue, payload["draft_comment"])]
    assert result["posted_url"].startswith("https://example.test/")


def test_duplicate_path(run, fake_model, poster, crash_issue):
    fake_model.queue(classification(Category.DUPLICATE, duplicate_of=117))
    graph, config, payload = run(crash_issue, candidates=[CANDIDATE])

    assert "#117" in payload["draft_comment"]
    assert "#117: KeyError in load_config" in fake_model.calls_for(Classification)[0][1].content

    resume(graph, config, ReviewDecision(action=ReviewAction.APPROVE))
    assert len(poster.posted) == 1


def test_real_bug_path_revises_until_approved(run, fake_model, poster, crash_issue):
    searcher = StubCodeSearcher()
    fake_model.queue(classification(Category.REAL_BUG), PLAN, REJECTED, PLAN, APPROVED)
    graph, config, payload = run(crash_issue, searcher=searcher)

    assert "load_config" in searcher.terms
    plan_calls = fake_model.calls_for(FixPlan)
    assert len(plan_calls) == 2
    assert "Missing regression test" not in plan_calls[0][1].content
    assert "Missing regression test" in plan_calls[1][1].content

    state = graph.get_state(config).values
    assert state["revisions"] == 2
    assert "triaged as a bug" in payload["draft_comment"]
    assert "Note" not in payload["draft_comment"]


def test_real_bug_path_stops_at_max_revisions(run, fake_model, crash_issue):
    fake_model.queue(classification(Category.REAL_BUG), PLAN, REJECTED, PLAN, REJECTED)
    graph, config, payload = run(crash_issue, max_revisions=2)

    assert graph.get_state(config).values["revisions"] == 2
    assert "did not pass automated review after 2" in payload["draft_comment"]


def test_edit_posts_reviewer_text(run, fake_model, poster, crash_issue):
    fake_model.queue(classification(Category.REAL_BUG), PLAN, APPROVED)
    graph, config, _ = run(crash_issue)

    result = resume(graph, config, ReviewDecision(action=ReviewAction.EDIT, comment="Edited."))
    assert poster.posted == [(crash_issue, "Edited.")]
    assert result["final_comment"] == "Edited."


def test_reject_posts_nothing(run, fake_model, poster, crash_issue):
    fake_model.queue(classification(Category.REAL_BUG), PLAN, APPROVED)
    graph, config, _ = run(crash_issue)

    result = resume(graph, config, ReviewDecision(action=ReviewAction.REJECT))
    assert poster.posted == []
    assert "final_comment" not in result
    assert pending_review(graph, config) is None


def test_fast_model_handles_classification_and_review(fake_model, poster, crash_issue):
    from conftest import FakeChatModel

    fast = FakeChatModel().queue(classification(Category.REAL_BUG), APPROVED)
    fake_model.queue(PLAN)
    deps = Dependencies(model=fake_model, fast_model=fast, poster=poster)
    graph = build_graph(deps)
    config = thread_config("fast")
    graph.invoke({"issue": crash_issue}, config)

    assert [key for key, _ in fast.calls] == [Classification, Critique]
    assert [key for key, _ in fake_model.calls] == [FixPlan]
    assert pending_review(graph, config) is not None


def test_dependencies_validate_max_revisions(fake_model):
    with pytest.raises(ValueError):
        Dependencies(model=fake_model, max_revisions=0)


def test_checkpoint_restores_models_without_warnings(run, fake_model, crash_issue, caplog):
    fake_model.queue(classification(Category.REAL_BUG), PLAN, APPROVED)
    graph, config, _ = run(crash_issue)

    state = graph.get_state(config).values
    assert isinstance(state["plan"], FixPlan)
    assert state["classification"].category is Category.REAL_BUG
    assert "unregistered type" not in caplog.text
