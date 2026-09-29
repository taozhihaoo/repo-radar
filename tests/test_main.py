"""Tests for the run orchestration in main.py (fake client, no network)."""

from src.github_client import RateLimitError, RepositoryNotFoundError
from src.main import fetch_reports
from src.models import RepoRequest


class FakeClient:
    """Returns canned payloads / raises canned errors; records every call."""

    def __init__(self, behaviour: dict) -> None:
        self._behaviour = behaviour
        self.calls: list[str] = []

    def get_repository(self, owner: str, repository: str) -> dict:
        full_name = f"{owner}/{repository}"
        self.calls.append(full_name)
        result = self._behaviour[full_name]
        if isinstance(result, Exception):
            raise result
        return result


def make_requests(*full_names: str) -> list[RepoRequest]:
    return [RepoRequest(*name.split("/")) for name in full_names]


def test_failures_are_recorded_not_raised():
    client = FakeClient(
        {
            "psf/requests": {"stargazers_count": 50000},
            "nope/missing": RepositoryNotFoundError("repository not found (HTTP 404)"),
        }
    )

    reports = fetch_reports(
        make_requests("psf/requests", "nope/missing"), client  # type: ignore[arg-type]
    )

    assert [r.status for r in reports] == ["ok", "not_found"]
    assert reports[0].stars == 50000
    assert "404" in reports[1].error_message


def test_rate_limit_stops_the_run():
    client = FakeClient(
        {
            "a/one": RateLimitError("GitHub API rate limit exceeded"),
            "b/two": {"stargazers_count": 1},
        }
    )

    reports = fetch_reports(make_requests("a/one", "b/two"), client)  # type: ignore[arg-type]

    assert client.calls == ["a/one"]  # b/two is never requested
    assert reports[0].status == "rate_limited"
    assert len(reports) == 1
