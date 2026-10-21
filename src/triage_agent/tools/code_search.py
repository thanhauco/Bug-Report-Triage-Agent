"""Locating source files that mention identifiers from a bug report."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol

from ..models import CodeHit

DEFAULT_EXTENSIONS = frozenset(
    {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb",
        ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".swift", ".scala",
    }
)  # fmt: skip
IGNORED_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
        "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    }
)  # fmt: skip

PATH_MATCH_BONUS = 2.0
MAX_SNIPPET_CHARS = 200


class CodeSearcher(Protocol):
    def search(self, terms: Sequence[str]) -> list[CodeHit]: ...


class NullCodeSearcher:
    """Used when no source tree is available."""

    def search(self, terms: Sequence[str]) -> list[CodeHit]:
        return []


class FilesystemCodeSearcher:
    """Scores files under ``root`` by how often, and how many of, the search terms appear.

    Each hit points at the first line mentioning the highest-priority matching term,
    where priority is the order of ``terms``.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        extensions: frozenset[str] = DEFAULT_EXTENSIONS,
        max_file_bytes: int = 512_000,
        limit: int = 8,
    ):
        self._root = Path(root).resolve()
        if not self._root.is_dir():
            raise NotADirectoryError(f"code root {self._root} is not a directory")
        self._extensions = extensions
        self._max_file_bytes = max_file_bytes
        self._limit = limit

    def search(self, terms: Sequence[str]) -> list[CodeHit]:
        needles = [term for term in dict.fromkeys(terms) if term]
        if not needles:
            return []

        hits = []
        for path in self._iter_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            relative = path.relative_to(self._root).as_posix()
            hit = _score_file(relative, text, needles)
            if hit is not None:
                hits.append(hit)

        hits.sort(key=lambda h: (-h.score, h.path))
        return hits[: self._limit]

    def _iter_files(self) -> Iterator[Path]:
        for directory, subdirs, files in os.walk(self._root):
            subdirs[:] = sorted(d for d in subdirs if d not in IGNORED_DIRS)
            for name in sorted(files):
                path = Path(directory, name)
                if path.suffix not in self._extensions:
                    continue
                try:
                    if path.stat().st_size > self._max_file_bytes:
                        continue
                except OSError:
                    continue
                yield path


def _score_file(relative_path: str, text: str, needles: Sequence[str]) -> CodeHit | None:
    score = 0.0
    anchor: str | None = None
    for term in needles:
        occurrences = text.count(term)
        if occurrences:
            score += 1 + math.log(occurrences)
            anchor = anchor or term
        if term in relative_path:
            score += PATH_MATCH_BONUS
    if score == 0:
        return None

    # Files that only match by path point at their first line with no snippet.
    line_number, snippet = 1, ""
    if anchor is not None:
        for number, line in enumerate(text.splitlines(), 1):
            if anchor in line:
                line_number, snippet = number, line.strip()[:MAX_SNIPPET_CHARS]
                break
    return CodeHit(path=relative_path, line=line_number, snippet=snippet, score=round(score, 3))
