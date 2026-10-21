from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from triage_agent.models import Issue


class FakeChatModel:
    """Scripted stand-in for a chat model.

    Queue responses with ``queue``: pydantic objects are returned from
    ``with_structured_output(<their type>)``, strings from plain ``invoke``.
    """

    def __init__(self) -> None:
        self._responses: dict[type | None, deque[Any]] = defaultdict(deque)
        self.calls: list[tuple[type | None, list[BaseMessage]]] = []

    def queue(self, *responses: BaseModel | str) -> FakeChatModel:
        for response in responses:
            key = None if isinstance(response, str) else type(response)
            self._responses[key].append(response)
        return self

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        return AIMessage(content=self._next(None, messages))

    def with_structured_output(self, schema: type, **_: Any) -> _Structured:
        return _Structured(self, schema)

    def calls_for(self, schema: type | None) -> list[list[BaseMessage]]:
        return [messages for key, messages in self.calls if key is schema]

    def _next(self, key: type | None, messages: list[BaseMessage]) -> Any:
        self.calls.append((key, messages))
        queue = self._responses[key]
        assert queue, f"no scripted response left for {key.__name__ if key else 'text'}"
        return queue.popleft()


class _Structured:
    def __init__(self, model: FakeChatModel, schema: type) -> None:
        self._model = model
        self._schema = schema

    def invoke(self, messages: list[BaseMessage]) -> Any:
        return self._model._next(self._schema, messages)


class RecordingPoster:
    def __init__(self) -> None:
        self.posted: list[tuple[Issue, str]] = []

    def post(self, issue: Issue, body: str) -> str:
        self.posted.append((issue, body))
        return f"https://example.test/issues/{issue.number}#comment-{len(self.posted)}"


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def poster() -> RecordingPoster:
    return RecordingPoster()


@pytest.fixture
def crash_issue() -> Issue:
    return Issue(
        number=150,
        title="Crash on startup after upgrading to v2.3",
        body="KeyError: 'network' raised from load_config in app/config/loader.py. "
        "ConfigLoader assumes a network section.",
    )
