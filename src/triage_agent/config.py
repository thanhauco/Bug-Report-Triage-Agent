"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_FAST_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_MAX_REVISIONS = 3


class ConfigError(ValueError):
    """Raised when required settings are missing or malformed."""


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    model: str = DEFAULT_MODEL
    fast_model: str = DEFAULT_FAST_MODEL
    temperature: float = 0.0
    max_revisions: int = DEFAULT_MAX_REVISIONS
    request_timeout: float = 60.0
    github_token: str | None = None
    github_repo: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        api_key = env.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("OPENROUTER_API_KEY is not set")

        max_revisions = _parse(env, "TRIAGE_MAX_REVISIONS", int, DEFAULT_MAX_REVISIONS)
        if max_revisions < 1:
            raise ConfigError("TRIAGE_MAX_REVISIONS must be at least 1")

        return cls(
            openrouter_api_key=api_key,
            model=env.get("TRIAGE_MODEL") or DEFAULT_MODEL,
            fast_model=env.get("TRIAGE_FAST_MODEL") or DEFAULT_FAST_MODEL,
            temperature=_parse(env, "TRIAGE_TEMPERATURE", float, 0.0),
            max_revisions=max_revisions,
            request_timeout=_parse(env, "TRIAGE_REQUEST_TIMEOUT", float, 60.0),
            github_token=env.get("GITHUB_TOKEN") or None,
            github_repo=env.get("GITHUB_REPOSITORY") or None,
        )


def _parse(env: Mapping[str, str], name: str, kind: type, default):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return kind(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a valid {kind.__name__}, got {raw!r}") from exc
