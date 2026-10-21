import pytest

from triage_agent.config import DEFAULT_MAX_REVISIONS, DEFAULT_MODEL, ConfigError, Settings


def test_requires_api_key():
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        Settings.from_env({})


def test_blank_api_key_is_rejected():
    with pytest.raises(ConfigError):
        Settings.from_env({"OPENROUTER_API_KEY": "   "})


def test_defaults():
    settings = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test"})
    assert settings.model == DEFAULT_MODEL
    assert settings.max_revisions == DEFAULT_MAX_REVISIONS
    assert settings.github_token is None
    assert settings.github_repo is None


def test_overrides():
    settings = Settings.from_env(
        {
            "OPENROUTER_API_KEY": "sk-or-test",
            "TRIAGE_MODEL": "openai/gpt-4o",
            "TRIAGE_FAST_MODEL": "openai/gpt-4o-mini",
            "TRIAGE_MAX_REVISIONS": "5",
            "TRIAGE_TEMPERATURE": "0.2",
            "GITHUB_REPOSITORY": "octo/app",
        }
    )
    assert settings.model == "openai/gpt-4o"
    assert settings.fast_model == "openai/gpt-4o-mini"
    assert settings.max_revisions == 5
    assert settings.temperature == 0.2
    assert settings.github_repo == "octo/app"


@pytest.mark.parametrize("value", ["zero", "1.5"])
def test_malformed_number(value):
    with pytest.raises(ConfigError, match="TRIAGE_MAX_REVISIONS"):
        Settings.from_env({"OPENROUTER_API_KEY": "k", "TRIAGE_MAX_REVISIONS": value})


def test_max_revisions_must_be_positive():
    with pytest.raises(ConfigError, match="at least 1"):
        Settings.from_env({"OPENROUTER_API_KEY": "k", "TRIAGE_MAX_REVISIONS": "0"})
