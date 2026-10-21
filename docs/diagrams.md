# Diagrams

All diagrams are Mermaid and render on GitHub.

## 1. Workflow graph

```mermaid
flowchart TD
    S([START]) --> C[classify]
    C -->|needs_info| A[ask_reporter]
    C -->|duplicate| D[link_duplicate]
    C -->|real_bug| L[locate_code]
    L --> P[draft_plan]
    P --> K[critic]
    K -->|problems and revisions < 3| P
    K -->|APPROVED or revisions >= 3| H
    A --> H{{human_approval<br/>interrupt_before}}
    D --> H
    H --> X[post_comment]
    X --> E([END])
```

## 2. Sequence: real-bug path with human gate

```mermaid
sequenceDiagram
    actor Dev as Human reviewer
    participant App as LangGraph app
    participant CP as Checkpointer
    participant LLM as OpenRouter LLM
    participant GH as GitHub

    App->>LLM: classify(issue)
    LLM-->>App: real_bug
    App->>LLM: locate_code(issue)
    loop up to 3 revisions
        App->>LLM: draft_plan(issue, context, critique)
        App->>LLM: critic(plan)
        LLM-->>App: APPROVED / problems
    end
    App->>CP: save state, pause before human_approval
    Dev->>CP: get_state / update_state (optional edit)
    Dev->>App: invoke(None, thread_id)
    App->>GH: post_comment(comment)
```

## 3. State machine of the critic loop

```mermaid
stateDiagram-v2
    [*] --> Drafting
    Drafting --> Reviewing: plan written, revisions += 1
    Reviewing --> Drafting: critique has problems and revisions < 3
    Reviewing --> AwaitingHuman: APPROVED or revisions >= 3
    AwaitingHuman --> Posted: resume
    Posted --> [*]
```

## 4. Components

```mermaid
flowchart LR
    subgraph Agent[triage.py]
        G[StateGraph]
        N[Node functions]
        R[Routers]
    end
    G --> N
    G --> R
    N -->|ChatOpenAI| OR[(OpenRouter API)]
    G -->|MemorySaver| CP[(Checkpoint store)]
    N -.->|extension point| T1[Repo search]
    N -.->|extension point| T2[Issue vector store]
    N -.->|extension point| T3[GitHub API]
```

## 5. State schema

```mermaid
classDiagram
    class State {
        str issue
        str category
        str code_context
        str plan
        str critique
        int revisions
        str comment
    }
```
