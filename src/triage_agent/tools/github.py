"""GitHub REST access and the comment posters used by the final node."""

from __future__ import annotations

import sys
from typing import Protocol, TextIO

import httpx

from ..models import Issue

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"


class CommentPoster(Protocol):
    def post(self, issue: Issue, body: str) -> str | None:
        """Publish ``body`` on ``issue`` and return the comment URL, if there is one."""
        ...


class ConsolePoster:
    """Prints the comment instead of publishing it. The default, so dry runs are safe."""

    def __init__(self, stream: TextIO | None = None):
        self._stream = stream

    def post(self, issue: Issue, body: str) -> str | None:
        stream = self._stream or sys.stdout
        print(f"--- comment for {issue.label} ---\n{body}\n--- end ---", file=stream)
        return None


class GitHubClient:
    """Minimal client for the issue endpoints this project needs."""

    def __init__(
        self,
        repo: str,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        owner, _, name = repo.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError(f"repository must look like 'owner/name', got {repo!r}")
        self.repo = repo

        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=f"{API_URL}/repos/{repo}",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_issue(self, number: int) -> Issue:
        response = self._http.get(f"/issues/{number}")
        response.raise_for_status()
        return _to_issue(response.json())

    def list_issues(self, *, state: str = "all", limit: int = 200) -> list[Issue]:
        """Most recently updated issues, excluding pull requests."""
        issues: list[Issue] = []
        page = 1
        while len(issues) < limit:
            response = self._http.get(
                "/issues",
                params={"state": state, "per_page": 100, "page": page, "sort": "updated"},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            issues.extend(_to_issue(item) for item in batch if "pull_request" not in item)
            page += 1
        return issues[:limit]

    def post_comment(self, number: int, body: str) -> str:
        response = self._http.post(f"/issues/{number}/comments", json={"body": body})
        response.raise_for_status()
        return response.json()["html_url"]


class GitHubPoster:
    """Publishes the approved comment on the GitHub issue."""

    def __init__(self, client: GitHubClient):
        self._client = client

    def post(self, issue: Issue, body: str) -> str | None:
        if issue.number is None:
            raise ValueError("cannot post to GitHub: the issue has no number")
        return self._client.post_comment(issue.number, body)


def _to_issue(item: dict) -> Issue:
    return Issue(
        number=item["number"],
        title=item["title"],
        body=item.get("body") or "",
        url=item.get("html_url"),
    )
