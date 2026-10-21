import os
from typing import TypedDict, Literal
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

llm = ChatOpenAI(
    model=os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-5-5"),
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
    temperature=0,
    default_headers={
        "HTTP-Referer": "https://github.com/thanhauco/Bug-Report-Triage-Agent",
        "X-Title": "Bug Report Triage Agent",
    },
)


class State(TypedDict, total=False):
    issue: str
    category: Literal["needs_info", "duplicate", "real_bug"]
    code_context: str
    plan: str
    critique: str
    revisions: int
    comment: str


def classify(s: State):
    r = llm.invoke(
        "Classify this issue as exactly one of: needs_info, duplicate, real_bug.\n\n"
        + s["issue"]
    )
    cat = r.content.strip().lower()
    return {
        "category": cat if cat in ("needs_info", "duplicate", "real_bug") else "needs_info",
        "revisions": 0,
    }


def ask_reporter(s: State):
    r = llm.invoke("Write a polite comment asking for repro steps/logs:\n" + s["issue"])
    return {"comment": r.content}


def link_duplicate(s: State):
    # swap in a vector-search tool over past issues here
    return {"comment": "This looks like a duplicate of an existing issue; closing."}


def locate_code(s: State):
    # swap in repo grep / embedding search tool here
    r = llm.invoke("Guess which modules are likely involved and why:\n" + s["issue"])
    return {"code_context": r.content}


def draft_plan(s: State):
    prompt = f"Issue:\n{s['issue']}\n\nContext:\n{s['code_context']}\n"
    if s.get("critique"):
        prompt += f"\nRevise per this critique:\n{s['critique']}\n"
    r = llm.invoke(prompt + "\nWrite a concise fix plan.")
    return {"plan": r.content, "revisions": s.get("revisions", 0) + 1}


def critic(s: State):
    r = llm.invoke(
        "Review this fix plan. Reply 'APPROVED' or list concrete problems.\n" + s["plan"]
    )
    return {"critique": r.content}


def human_approval(s: State):
    # the graph is interrupted before this node; a human may edit state first
    return {"comment": s.get("comment") or s["plan"]}


def post_comment(s: State):
    print("POSTING:\n", s["comment"])  # call GitHub API here
    return {}


def route_category(s: State):
    return s["category"]


def route_critic(s: State):
    if "APPROVED" in s["critique"].upper() or s["revisions"] >= 3:
        return "human_approval"
    return "draft_plan"


def build_app():
    g = StateGraph(State)
    for name, fn in [
        ("classify", classify),
        ("ask_reporter", ask_reporter),
        ("link_duplicate", link_duplicate),
        ("locate_code", locate_code),
        ("draft_plan", draft_plan),
        ("critic", critic),
        ("human_approval", human_approval),
        ("post_comment", post_comment),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        route_category,
        {"needs_info": "ask_reporter", "duplicate": "link_duplicate", "real_bug": "locate_code"},
    )
    g.add_edge("locate_code", "draft_plan")
    g.add_edge("draft_plan", "critic")
    g.add_conditional_edges("critic", route_critic, ["draft_plan", "human_approval"])
    g.add_edge("ask_reporter", "human_approval")
    g.add_edge("link_duplicate", "human_approval")
    g.add_edge("human_approval", "post_comment")
    g.add_edge("post_comment", END)

    return g.compile(checkpointer=MemorySaver(), interrupt_before=["human_approval"])


app = build_app()

if __name__ == "__main__":
    cfg = {"configurable": {"thread_id": "issue-42"}}
    app.invoke({"issue": "App crashes on startup after upgrading to v2.3 (NPE in ConfigLoader)"}, cfg)
    # graph pauses before human_approval; inspect with app.get_state(cfg)
    # optionally edit: app.update_state(cfg, {"comment": "edited text"})
    app.invoke(None, cfg)  # resume -> posts the comment
