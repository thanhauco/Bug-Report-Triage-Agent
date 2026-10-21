# Architecture

Bug-Report-Triage-Agent is a [LangGraph](https://langchain-ai.github.io/langgraph/) `StateGraph` that turns a raw bug report into a reviewed GitHub comment. It does three things:

- It retrieves context with deterministic tools: similar past issues and relevant source files.
- It uses LLMs, through [OpenRouter](https://openrouter.ai), for classification, writing and self-review.
- It always pauses for a human before anything leaves the process.

All diagrams use one colour key. The full set is in [docs/diagrams.md](docs/diagrams.md).

| **Colour** | **Meaning** |
|---|---|
| Royal blue `#4D7FEE` | LLM call |
| Teal `#69D0BF` | Deterministic processing and tools; the success path |
| Orange `#EC8131` | Decisions: routers and the human gate |
| Cream `#F3EFE6` | State, storage, inputs and terminals |
| Coral `#E94E5E` | External side effects, rejection and failure paths |

## Workflow

```mermaid
flowchart LR
    S([START]):::term --> FD[find_duplicates]:::tool --> C[classify]:::llm --> R1{route_after_classify}:::decision

    subgraph outcomes [Triage outcomes]
        direction TB
        RI[request_info]:::llm
        MD[mark_duplicate]:::tool
        subgraph loop [Fix-plan loop, max N revisions]
            direction LR
            LC[locate_code]:::tool --> DP[draft_plan]:::llm --> RP[review_plan]:::llm --> R2{route_after_review}:::decision
            R2 -- "problems, revisions below N" --> DP
        end
        R2 -- "approved or revisions = N" --> WC[write_plan_comment]:::tool
    end

    R1 -- needs_info --> RI
    R1 -- "duplicate of a retrieved candidate" --> MD
    R1 -- "real_bug, or unverified duplicate" --> LC

    RI --> HR
    MD --> HR
    WC --> HR
    HR{{"human_review<br/>interrupt()"}}:::decision --> R3{route_after_human}:::decision
    R3 -- "approve / edit" --> PC[post_comment]:::external --> E([END]):::term
    R3 -- reject --> E2([END]):::reject

    classDef llm fill:#4D7FEE,stroke:#2F5BC4,color:#0B1530,stroke-width:1.5px
    classDef tool fill:#69D0BF,stroke:#3A9E8D,color:#0B2A25,stroke-width:1.5px
    classDef decision fill:#EC8131,stroke:#B85E1C,color:#2A1405,stroke-width:1.5px
    classDef term fill:#F3EFE6,stroke:#9C9585,color:#2B2B2B,stroke-width:1.5px
    classDef external fill:#E94E5E,stroke:#B3303E,color:#2A0508,stroke-width:1.5px
    classDef reject fill:#F3EFE6,stroke:#E94E5E,color:#B3303E,stroke-width:2px,stroke-dasharray:4 3
    style outcomes fill:#FBFAF6,stroke:#9C9585
    style loop fill:#EEF3FD,stroke:#4D7FEE
```

## Components

```mermaid
flowchart LR
    subgraph inputs [Entry points]
        direction TB
        CLI[["triage-agent CLI<br/>cli.py"]]:::term
        API[["Python API<br/>build_graph()"]]:::term
    end

    subgraph core [Orchestration: triage_agent]
        direction TB
        G[Compiled StateGraph<br/>graph.py + routing.py]:::decision
        N[TriageNodes<br/>nodes.py]:::tool
        P[Prompts and comment templates<br/>prompts.py, comments.py]:::llm
        CP[(Checkpointer<br/>InMemorySaver)]:::store
        G -- "runs" --> N
        N --> P
        G <-- "state per thread_id" --> CP
    end

    subgraph tools [Tools, injected via Dependencies]
        direction TB
        DF[LexicalDuplicateFinder]:::tool
        CS[FilesystemCodeSearcher]:::tool
        PO[ConsolePoster / GitHubPoster]:::tool
        GHC[GitHubClient]:::tool
    end

    subgraph external [External systems and data]
        direction TB
        OR[(OpenRouter API<br/>main + fast model)]:::external
        GH[(GitHub REST API)]:::external
        SRC[(Local source tree)]:::store
        KI[(known_issues.json)]:::store
    end

    CLI -- "invoke / resume" --> G
    API -- "invoke / resume" --> G
    N -- "ChatOpenAI" --> OR
    N --> DF
    N --> CS
    N --> PO
    CS -. "--code-root" .-> SRC
    CLI -. "--known-issues" .-> KI
    CLI -. "--issue N, --repo" .-> GHC
    PO -. "--post" .-> GHC
    GHC --> GH

    classDef llm fill:#4D7FEE,stroke:#2F5BC4,color:#0B1530
    classDef tool fill:#69D0BF,stroke:#3A9E8D,color:#0B2A25
    classDef decision fill:#EC8131,stroke:#B85E1C,color:#2A1405
    classDef term fill:#F3EFE6,stroke:#9C9585,color:#2B2B2B
    classDef store fill:#F3EFE6,stroke:#4D7FEE,color:#2B2B2B,stroke-width:2px
    classDef external fill:#E94E5E,stroke:#B3303E,color:#2A0508
    style inputs fill:#FBFAF6,stroke:#9C9585
    style core fill:#FEF5EE,stroke:#EC8131
    style tools fill:#F2FBF9,stroke:#3A9E8D
    style external fill:#FDF1F2,stroke:#E94E5E
```

| **Module** | **Responsibility** |
|---|---|
| `config.py` | `Settings.from_env()`: reads and validates environment variables |
| `llm.py` | Builds `ChatOpenAI` clients pointed at OpenRouter; `structured()` binds a Pydantic output schema |
| `models.py` | Domain models (`Issue`, `CodeHit`, ...) and LLM output schemas (`Classification`, `FixPlan`, `Critique`) |
| `state.py` | `TriageState`, the graph's shared state |
| `text.py` | Tokenisation and identifier extraction for the retrieval tools |
| `prompts.py` | System prompts and message builders, one per LLM call |
| `comments.py` | Fixed comment templates for outcomes that need no LLM wording |
| `tools/` | `LexicalDuplicateFinder`, `FilesystemCodeSearcher`, `GitHubClient`, comment posters |
| `nodes.py` | `Dependencies` (injected services) and `TriageNodes` (one method per node) |
| `routing.py` | Node names and the three conditional-edge routers |
| `graph.py` | `build_graph()`, plus `pending_review()` / `resume()` for the interrupt |
| `cli.py` | `triage-agent` command: wires real services into `Dependencies` and prompts the reviewer |

## Nodes

| **Node** | **Kind** | **Reads** | **Writes** |
|---|---|---|---|
| `find_duplicates` | Tool | `issue` | `duplicate_candidates` |
| `classify` | LLM, fast model | `issue`, `duplicate_candidates` | `classification` |
| `request_info` | LLM, main model | `issue`, `classification.missing_info` | `draft_comment` |
| `mark_duplicate` | Template | `classification.duplicate_of`, `duplicate_candidates` | `draft_comment` |
| `locate_code` | Tool | `issue` | `code_hits`, `revisions = 0` |
| `draft_plan` | LLM, main model | `issue`, `code_hits`, previous `plan` and `critique` | `plan`, `revisions + 1` |
| `review_plan` | LLM, fast model | `issue`, `code_hits`, `plan` | `critique` |
| `write_plan_comment` | Template | `plan`, `critique`, `revisions` | `draft_comment` |
| `human_review` | Interrupt | `issue`, `classification`, `draft_comment` | `decision` |
| `post_comment` | Side effect | `decision`, `draft_comment` | `final_comment`, `posted_url` |

## Routing rules

| **Router** | **Condition** | **Next node** |
|---|---|---|
| `route_after_classify` | `needs_info` | `request_info` |
| | `duplicate` **and** `duplicate_of` is one of the retrieved candidates | `mark_duplicate` |
| | `real_bug`, or a duplicate number that was not retrieved | `locate_code` |
| `route_after_review` | `critique.approved` **or** `revisions >= max_revisions` | `write_plan_comment` |
| | otherwise | `draft_plan` |
| `route_after_human` | `reject` | `END` |
| | `approve` or `edit` | `post_comment` |

## Design decisions

### Structured outputs everywhere a decision is made
`classify`, `draft_plan` and `review_plan` return Pydantic models through `with_structured_output(..., method="function_calling")`. Routing then reads typed fields like `critique.approved` instead of searching free text for "APPROVED". Tool calling is used rather than JSON-schema response formats because more of the models available on OpenRouter support it.

### Retrieval proposes, the LLM decides, the router verifies
Duplicate detection is split into three steps:
1. A cheap TF-IDF retriever shortlists candidates.
2. The LLM decides whether any of them is a real match.
3. The router accepts the verdict only if the number came from the shortlist.

A made-up issue number therefore can't close a report. The report is investigated as a bug instead.

### Bounded self-review
The draft/review loop is capped by `max_revisions` (default 3), so cost and latency stay bounded. If the cap is reached without approval, the plan is still sent for human review. Its comment says so explicitly and lists the critic's open problems.

### Human approval is structural
`human_review` calls LangGraph's `interrupt()`, and every branch passes through it. Nothing can be posted without a `ReviewDecision`. An `edit` decision must include replacement text, which the model validator enforces.

### Two model tiers
Classification and review are short, schema-constrained calls, so they go to `TRIAGE_FAST_MODEL`. Writing fix plans and replies goes to `TRIAGE_MODEL`. Either can be any OpenRouter model slug.

### Dependency injection
External services (models, retrievers, poster) are passed in through `Dependencies`. Tests run the real graph end to end with a scripted fake model and stub tools, without network access.

## Persistence

`build_graph()` compiles with `InMemorySaver` by default, which keeps paused runs only for the life of the process. That is enough for the CLI, which pauses and resumes in one process. A service that resumes later should pass a durable checkpointer, such as LangGraph's SQLite or Postgres savers, and a stable `thread_id` per issue.

## Limitations

| **Area** | **Current behaviour** | **Possible improvement** |
|---|---|---|
| Duplicate retrieval | Lexical TF-IDF over titles and bodies | Embedding search |
| Code search | Literal identifier matching over files | Symbol index, or embeddings over chunks |
| Persistence | In-memory checkpoints | SQLite or Postgres checkpointer |
| Triggering | Manual CLI run | GitHub webhook or Action on `issues.opened` |
