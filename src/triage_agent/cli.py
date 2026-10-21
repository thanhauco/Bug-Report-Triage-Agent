"""Command-line entry point: ``triage-agent``."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from .config import ConfigError, Settings
from .graph import build_graph, pending_review, resume, thread_config
from .llm import make_chat_model
from .models import Issue, ReviewAction, ReviewDecision
from .nodes import Dependencies
from .tools import (
    ConsolePoster,
    FilesystemCodeSearcher,
    GitHubClient,
    GitHubPoster,
    LexicalDuplicateFinder,
    NullCodeSearcher,
    NullDuplicateFinder,
    load_issues,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triage-agent",
        description="Triage a bug report: classify it, draft a reply or fix plan, "
        "and ask for approval before posting.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue", type=int, metavar="N", help="GitHub issue number to triage")
    source.add_argument("--title", help="title of a report that is not on GitHub")
    parser.add_argument(
        "--body-file", type=Path, metavar="PATH", help="report body for --title ('-' for stdin)"
    )
    parser.add_argument(
        "--repo", metavar="OWNER/NAME", help="GitHub repository (default: $GITHUB_REPOSITORY)"
    )
    parser.add_argument(
        "--code-root", type=Path, metavar="DIR", help="source tree to search for relevant code"
    )
    parser.add_argument(
        "--known-issues",
        type=Path,
        metavar="PATH",
        help="JSON file of past issues for duplicate detection "
        "(default: recent issues from --repo, if set)",
    )
    parser.add_argument(
        "--post", action="store_true", help="post the approved comment to GitHub (default: print)"
    )
    parser.add_argument("--yes", action="store_true", help="approve the draft without prompting")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.body_file is not None and args.title is None:
        parser.error("--body-file can only be used with --title")
    try:
        settings = Settings.from_env()
        return _run(args, settings)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, settings: Settings) -> int:
    repo = args.repo or settings.github_repo
    if args.issue is not None and not repo:
        raise ConfigError("--issue needs --repo or GITHUB_REPOSITORY")
    if args.post and (args.issue is None or not settings.github_token):
        raise ConfigError("--post needs --issue and GITHUB_TOKEN")

    with ExitStack() as stack:
        github = None
        if repo:
            github = stack.enter_context(GitHubClient(repo, settings.github_token))

        issue = github.get_issue(args.issue) if args.issue is not None else _local_issue(args)

        if args.known_issues:
            duplicate_finder = LexicalDuplicateFinder(load_issues(args.known_issues))
        elif github is not None:
            duplicate_finder = LexicalDuplicateFinder(github.list_issues())
        else:
            duplicate_finder = NullDuplicateFinder()

        deps = Dependencies(
            model=make_chat_model(settings),
            fast_model=make_chat_model(settings, settings.fast_model),
            duplicate_finder=duplicate_finder,
            code_searcher=(
                FilesystemCodeSearcher(args.code_root) if args.code_root else NullCodeSearcher()
            ),
            poster=GitHubPoster(github) if args.post and github else ConsolePoster(),
            max_revisions=settings.max_revisions,
        )
        graph = build_graph(deps)
        config = thread_config(f"issue-{issue.number or uuid.uuid4().hex[:8]}")

        graph.invoke({"issue": issue}, config)
        payload = pending_review(graph, config)
        if payload is None:
            print("error: run finished without reaching human review", file=sys.stderr)
            return 1

        decision = ReviewDecision(action=ReviewAction.APPROVE) if args.yes else _ask(payload)
        result = resume(graph, config, decision)

    if decision.action is ReviewAction.REJECT:
        print("Rejected; nothing was posted.")
    elif result.get("posted_url"):
        print(f"Posted: {result['posted_url']}")
    return 0


def _local_issue(args: argparse.Namespace) -> Issue:
    body = ""
    if args.body_file is not None:
        body = (
            sys.stdin.read()
            if str(args.body_file) == "-"
            else args.body_file.read_text(encoding="utf-8")
        )
    return Issue(title=args.title, body=body)


def _ask(payload: dict[str, Any]) -> ReviewDecision:
    print(f"\nCategory: {payload['category']}\n")
    print(payload["draft_comment"])
    while True:
        choice = input("\n[a]pprove, [e]dit, [r]eject? ").strip().lower()[:1]
        if choice == "a":
            return ReviewDecision(action=ReviewAction.APPROVE)
        if choice == "r":
            return ReviewDecision(action=ReviewAction.REJECT)
        if choice == "e":
            edited = _edit(payload["draft_comment"]).strip()
            if edited:
                return ReviewDecision(action=ReviewAction.EDIT, comment=edited)
            print("Edited comment is empty; try again.")


def _edit(text: str) -> str:
    """Edit ``text`` in $VISUAL/$EDITOR, or read a replacement from stdin if neither is set."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        print("Enter the replacement comment; finish with a line containing only '.':")
        lines = []
        for line in sys.stdin:
            if line.rstrip("\n") == ".":
                break
            lines.append(line)
        return "".join(lines)

    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = Path(fh.name)
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
        return path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
