"""Finding previously reported issues that look like the one being triaged."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from ..models import DuplicateCandidate, Issue
from ..text import tokenize

# Titles are short and usually name the symptom, so they count more than the body.
TITLE_WEIGHT = 2


class DuplicateFinder(Protocol):
    def find(self, issue: Issue) -> list[DuplicateCandidate]: ...


class NullDuplicateFinder:
    """Used when no corpus of known issues is available."""

    def find(self, issue: Issue) -> list[DuplicateCandidate]:
        return []


class LexicalDuplicateFinder:
    """Ranks known issues by TF-IDF cosine similarity to the new report.

    Cheap and dependency-free; good enough to put a shortlist in front of the
    classifier, which makes the final duplicate call.
    """

    def __init__(self, corpus: Iterable[Issue], *, threshold: float = 0.25, limit: int = 5):
        self._issues = [issue for issue in corpus if issue.number is not None]
        self._threshold = threshold
        self._limit = limit

        term_counts = [_term_counts(issue) for issue in self._issues]
        document_frequency: Counter[str] = Counter()
        for counts in term_counts:
            document_frequency.update(counts.keys())
        total = len(self._issues)
        self._idf = {
            term: math.log((1 + total) / (1 + df)) + 1 for term, df in document_frequency.items()
        }
        self._default_idf = math.log(1 + total) + 1
        self._vectors = [self._weigh(counts) for counts in term_counts]

    def find(self, issue: Issue) -> list[DuplicateCandidate]:
        query = self._weigh(_term_counts(issue))
        candidates = []
        for known, vector in zip(self._issues, self._vectors, strict=True):
            if issue.number is not None and known.number == issue.number:
                continue
            score = _cosine(query, vector)
            if score >= self._threshold:
                candidates.append(
                    DuplicateCandidate(
                        number=known.number, title=known.title, url=known.url, score=round(score, 3)
                    )
                )
        candidates.sort(key=lambda c: (-c.score, c.number))
        return candidates[: self._limit]

    def _weigh(self, counts: Counter[str]) -> dict[str, float]:
        return {term: tf * self._idf.get(term, self._default_idf) for term, tf in counts.items()}


def load_issues(path: str | Path) -> list[Issue]:
    """Load known issues from a JSON array of objects with number, title and optional body/url."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of issues")
    return [Issue.model_validate(item) for item in data]


def _term_counts(issue: Issue) -> Counter[str]:
    counts = Counter(tokenize(issue.body))
    for term in tokenize(issue.title):
        counts[term] += TITLE_WEIGHT
    return counts


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(weight * b.get(term, 0.0) for term, weight in a.items())
    norm = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
    return dot / norm if norm else 0.0
