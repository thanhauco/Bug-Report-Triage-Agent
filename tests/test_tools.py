import io
import json

import httpx
import pytest

from triage_agent.models import Issue
from triage_agent.tools import (
    ConsolePoster,
    FilesystemCodeSearcher,
    GitHubClient,
    GitHubPoster,
    LexicalDuplicateFinder,
    load_issues,
)

KNOWN = [
    Issue(number=101, title="Dark mode toggle does not persist", body="Theme resets on reload."),
    Issue(
        number=117,
        title="KeyError network in load_config after upgrade",
        body="ConfigLoader fails when settings.yaml has no network section.",
    ),
    Issue(number=123, title="CSV export drops the last row", body="Odd row counts lose a line."),
]


class TestLexicalDuplicateFinder:
    def test_ranks_the_matching_issue_first(self, crash_issue):
        candidates = LexicalDuplicateFinder(KNOWN).find(crash_issue)
        assert [c.number for c in candidates] == [117]
        assert 0 < candidates[0].score <= 1

    def test_unrelated_report_has_no_candidates(self):
        report = Issue(title="Login button misaligned on mobile", body="Overlaps the logo.")
        assert LexicalDuplicateFinder(KNOWN).find(report) == []

    def test_skips_the_issue_itself(self):
        assert LexicalDuplicateFinder(KNOWN).find(KNOWN[1]) == []

    def test_ignores_corpus_entries_without_number(self, crash_issue):
        finder = LexicalDuplicateFinder([Issue(title=crash_issue.title, body=crash_issue.body)])
        assert finder.find(crash_issue) == []

    def test_load_issues(self, tmp_path):
        path = tmp_path / "issues.json"
        path.write_text(json.dumps([{"number": 1, "title": "a"}]))
        assert load_issues(path) == [Issue(number=1, title="a")]

        path.write_text(json.dumps({"number": 1}))
        with pytest.raises(ValueError, match="JSON array"):
            load_issues(path)


class TestFilesystemCodeSearcher:
    @pytest.fixture
    def repo(self, tmp_path):
        (tmp_path / "app" / "config").mkdir(parents=True)
        (tmp_path / "app" / "config" / "loader.py").write_text(
            "class ConfigLoader:\n    def load_config(self, raw):\n"
            "        return raw['network']['timeout']\n"
        )
        (tmp_path / "app" / "export.py").write_text("def export_csv(rows):\n    return rows\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "vendored.js").write_text("ConfigLoader")
        (tmp_path / "README.md").write_text("ConfigLoader docs")
        return tmp_path

    def test_finds_relevant_file_with_line(self, repo):
        hits = FilesystemCodeSearcher(repo).search(["load_config", "ConfigLoader"])
        assert [h.path for h in hits] == ["app/config/loader.py"]
        assert hits[0].line == 2
        assert hits[0].snippet == "def load_config(self, raw):"

    def test_path_only_match(self, repo):
        hits = FilesystemCodeSearcher(repo).search(["export"])
        assert hits[0].path == "app/export.py"

    def test_no_terms_or_no_matches(self, repo):
        searcher = FilesystemCodeSearcher(repo)
        assert searcher.search([]) == []
        assert searcher.search(["DoesNotExist"]) == []

    def test_rejects_missing_root(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            FilesystemCodeSearcher(tmp_path / "missing")


class TestGitHub:
    @staticmethod
    def client(handler) -> GitHubClient:
        return GitHubClient("octo/app", "token", transport=httpx.MockTransport(handler))

    def test_get_issue(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/repos/octo/app/issues/5"
            assert request.headers["Authorization"] == "Bearer token"
            return httpx.Response(
                200, json={"number": 5, "title": "Bug", "body": None, "html_url": "u"}
            )

        assert self.client(handler).get_issue(5) == Issue(number=5, title="Bug", url="u")

    def test_list_issues_skips_pull_requests_and_paginates(self):
        pages = {
            "1": [{"number": 1, "title": "a"}, {"number": 2, "title": "pr", "pull_request": {}}],
            "2": [{"number": 3, "title": "b"}],
            "3": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=pages[request.url.params["page"]])

        assert [i.number for i in self.client(handler).list_issues()] == [1, 3]

    def test_poster_publishes_comment(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert json.loads(request.content) == {"body": "hello"}
            return httpx.Response(201, json={"html_url": "https://github.com/c/1"})

        poster = GitHubPoster(self.client(handler))
        assert poster.post(Issue(number=9, title="t"), "hello") == "https://github.com/c/1"
        with pytest.raises(ValueError, match="no number"):
            poster.post(Issue(title="t"), "hello")

    def test_errors_are_raised(self):
        client = self.client(lambda request: httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            client.get_issue(1)

    def test_rejects_bad_repo(self):
        with pytest.raises(ValueError, match="owner/name"):
            GitHubClient("not-a-repo")


def test_console_poster_prints():
    stream = io.StringIO()
    assert ConsolePoster(stream).post(Issue(number=3, title="t"), "body") is None
    assert "comment for #3" in stream.getvalue()
    assert "body" in stream.getvalue()
