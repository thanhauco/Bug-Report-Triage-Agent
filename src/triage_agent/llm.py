"""Chat model construction for OpenRouter's OpenAI-compatible API."""

from __future__ import annotations

from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .config import Settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
APP_URL = "https://github.com/thanhauco/Bug-Report-Triage-Agent"
APP_TITLE = "Bug Report Triage Agent"

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def make_chat_model(settings: Settings, model: str | None = None) -> ChatOpenAI:
    """Return a chat model that talks to OpenRouter; ``model`` overrides ``settings.model``."""
    return ChatOpenAI(
        model=model or settings.model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
        temperature=settings.temperature,
        timeout=settings.request_timeout,
        max_retries=2,
        # Optional attribution headers used by OpenRouter's app rankings.
        default_headers={"HTTP-Referer": APP_URL, "X-Title": APP_TITLE},
    )


def structured(model: BaseChatModel, schema: type[SchemaT]) -> Runnable:
    """Bind ``schema`` as the model's output format.

    Tool calling is used rather than JSON-schema response formats because it is
    supported by far more of the models OpenRouter routes to.
    """
    return model.with_structured_output(schema, method="function_calling")
