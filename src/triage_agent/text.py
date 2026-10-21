"""Text helpers shared by the retrieval tools."""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_IDENTIFIER_PATTERNS = (
    # `backticked` spans
    re.compile(r"`([^`\n]{2,80})`"),
    # file names such as config/loader.py
    re.compile(
        r"\b([\w./-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|kt|rb|php|cs|c|h|cpp|hpp|swift|scala))\b"
    ),
    # dotted paths such as app.config.load
    re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b"),
    # CamelCase names such as ConfigLoader
    re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b"),
    # snake_case names such as load_config
    re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b"),
)

STOPWORDS = frozenset(
    """
    a about after again also am an and any are as at be been before being but by can could did do
    does doing for from get got had has have how i if in into is it its just me my no not of on
    or our please should so some than that the their them then there these this those to too
    up use using very was we were what when where which while who why will with would you your
    bug issue problem
    """.split()  # noqa: SIM905
)


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens with camelCase and snake_case split apart and stopwords removed."""
    tokens: list[str] = []
    for word in _WORD_RE.findall(text):
        for chunk in word.split("_"):
            tokens.extend(part.lower() for part in _CAMEL_BOUNDARY_RE.split(chunk) if len(part) > 1)
    return [token for token in tokens if token not in STOPWORDS]


def extract_identifiers(text: str, limit: int = 12) -> list[str]:
    """Code-like identifiers mentioned in ``text``, most specific patterns first, deduplicated."""
    found: dict[str, None] = {}
    for pattern in _IDENTIFIER_PATTERNS:
        for match in pattern.findall(text):
            candidate = match.strip()
            if len(candidate) >= 4:
                found.setdefault(candidate, None)
    return list(found)[:limit]
