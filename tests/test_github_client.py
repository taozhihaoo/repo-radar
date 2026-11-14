"""Tests for the GitHub API client (HTTP fully mocked, no network)."""

import threading
from unittest import mock

import pytest
import requests

from src.github_client import (
    GitHubAPIError,
    GitHubClient,
    GitHubServerError,
    RateLimitError,
    RepositoryNotFoundError,
)


def fake_response(status_code=200, payload=None, headers=None):
    response = mock.Mock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = {"full_name": "psf/requests"} if payload is None else payload
    return response


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Record sleep calls instead of actually sleeping during retries."""
    sleeps: list[float] = []
    monkeypatch.setattr("src.github_client.time.sleep", sleeps.append)
    return sleeps


def make_client(session, **kwargs):
    kwargs.setdefault("timeout", 5)
    kwargs.setdefault("backoff", 0.0)
    return GitHubClient(session=session, **kwargs)


def test_success_returns_payload_and_uses_expected_url():
    session = mock.Mock()
    session.get.return_value = fake_response(
        200, {"full_name": "psf/requests", "stargazers_count": 1}
    )
    client = make_client(session, max_retries=1)

    payload = client.get_repository("psf", "requests")

    assert payload["stargazers_count"] == 1
    session.get.assert_called_once_with("https://api.github.com/repos/psf/requests", timeout=5)


def test_token_sets_authorization_header():
    session = requests.Session()
    GitHubClient(session=session, token="secret-token")
    assert session.headers["Authorization"] == "Bearer secret-token"
    assert session.headers["Accept"].startswith("application/vnd.github")
    assert session.headers["User-Agent"].startswith("repo-radar/")


def test_version_is_reported_consistently():
    import src

    session = requests.Session()
    GitHubClient(session=session)
    assert session.headers["User-Agent"] == f"repo-radar/{src.__version__}"


def test_404_is_not_retried():
    session = mock.Mock()
    session.get.return_value = fake_response(404)
    client = make_client(session, max_retries=3)

    with pytest.raises(RepositoryNotFoundError):
        client.get_repository("nope", "missing")
    assert session.get.call_count == 1


def test_primary_rate_limit_is_raised_immediately():
    session = mock.Mock()
    session.get.return_value = fake_response(403, headers={"X-RateLimit-Remaining": "0"})
    client = make_client(session, max_retries=3)

    with pytest.raises(RateLimitError):
        client.get_repository("psf", "requests")
    assert session.get.call_count == 1


def test_500_is_retried_until_success(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = [fake_response(503), fake_response(503), fake_response(200)]
    client = make_client(session, max_retries=3)

    assert client.get_repository("psf", "requests")["full_name"] == "psf/requests"
    assert session.get.call_count == 3
    assert len(no_real_sleep) == 2  # slept between attempts, not after the last


def test_retries_exhausted_raises_server_error(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = [fake_response(500) for _ in range(3)]
    client = make_client(session, max_retries=3)

    with pytest.raises(GitHubServerError):
        client.get_repository("psf", "requests")
    assert session.get.call_count == 3


def test_timeout_is_retried_then_raised(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = requests.Timeout("timed out")
    client = make_client(session, max_retries=2)

    with pytest.raises(GitHubAPIError):
        client.get_repository("psf", "requests")
    assert session.get.call_count == 2


def test_retry_after_header_is_honored(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = [
        fake_response(429, headers={"Retry-After": "7"}),
        fake_response(200),
    ]
    client = make_client(session, max_retries=3)

    assert client.get_repository("psf", "requests")["full_name"] == "psf/requests"
    assert no_real_sleep == [7.0]  # waited the server-requested interval


def test_invalid_json_raises_api_error():
    session = mock.Mock()
    response = fake_response(200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response
    client = make_client(session, max_retries=1)

    with pytest.raises(GitHubAPIError):
        client.get_repository("psf", "requests")


def test_non_object_payload_raises_api_error():
    session = mock.Mock()
    session.get.return_value = fake_response(200, ["not", "a", "dict"])
    client = make_client(session, max_retries=1)

    with pytest.raises(GitHubAPIError, match="unexpected JSON payload type"):
        client.get_repository("psf", "requests")


def test_excessive_retry_after_is_reported_instead_of_waited(no_real_sleep):
    # Two hours of waiting is never the intent of one CLI invocation.
    session = mock.Mock()
    session.get.return_value = fake_response(429, headers={"Retry-After": "7200"})
    client = make_client(session, max_retries=3, max_retry_delay=30)

    with pytest.raises(RateLimitError, match="cap"):
        client.get_repository("psf", "requests")
    assert session.get.call_count == 1
    assert no_real_sleep == []


def test_backoff_is_capped(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = [fake_response(503) for _ in range(4)]
    client = make_client(session, max_retries=4, backoff=10, max_retry_delay=12)

    with pytest.raises(GitHubServerError):
        client.get_repository("psf", "requests")
    assert no_real_sleep == [10.0, 12.0, 12.0]


def test_non_numeric_retry_after_is_ignored(no_real_sleep):
    session = mock.Mock()
    session.get.side_effect = [
        fake_response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        fake_response(200),
    ]
    client = make_client(session, max_retries=2, backoff=0.5)

    assert client.get_repository("psf", "requests")["full_name"] == "psf/requests"
    assert no_real_sleep == [0.5]


def test_error_responses_are_closed():
    session = mock.Mock()
    response = fake_response(404)
    session.get.return_value = response
    client = make_client(session, max_retries=1)

    with pytest.raises(RepositoryNotFoundError):
        client.get_repository("nope", "missing")
    response.close.assert_called_once()


def test_successful_response_is_not_closed():
    session = mock.Mock()
    response = fake_response(200)
    session.get.return_value = response
    client = make_client(session, max_retries=1)

    client.get_repository("psf", "requests")
    response.close.assert_not_called()


# --- sessions ---------------------------------------------------------------------


class RecordingSession(requests.Session):
    """Session that remembers whether it was closed."""

    instances: list = []

    def __init__(self) -> None:
        super().__init__()
        self.was_closed = False
        RecordingSession.instances.append(self)

    def close(self) -> None:
        self.was_closed = True
        super().close()


def test_client_creates_one_session_per_thread_and_closes_them(monkeypatch):
    RecordingSession.instances = []
    monkeypatch.setattr(requests, "Session", RecordingSession)

    client = GitHubClient(max_retries=1)
    sessions: dict[int, object] = {}

    def grab(index: int) -> None:
        sessions[index] = client._session  # noqa: SLF001 - deliberate white-box check

    threads = [threading.Thread(target=grab, args=(index,)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(session) for session in sessions.values()}) == 3  # never shared
    client.close()
    assert all(session.was_closed for session in RecordingSession.instances)


def test_injected_session_is_used_for_every_thread_and_left_open():
    session = mock.Mock()
    session.get.return_value = fake_response(200)
    client = make_client(session, max_retries=1)

    threads = [
        threading.Thread(target=client.get_repository, args=("psf", "requests")) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert session.get.call_count == 2
    client.close()
    session.close.assert_not_called()  # the caller owns an injected session


def test_context_manager_closes_the_client(monkeypatch):
    RecordingSession.instances = []
    monkeypatch.setattr(requests, "Session", RecordingSession)

    with GitHubClient(max_retries=1) as client:
        assert client._session is not None  # noqa: SLF001 - forces lazy creation
    assert len(RecordingSession.instances) == 1
    assert all(session.was_closed for session in RecordingSession.instances)
