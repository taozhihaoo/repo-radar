"""Tests for the GitHub API client (HTTP fully mocked, no network)."""

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
    response.json.return_value = (
        {"full_name": "psf/requests"} if payload is None else payload
    )
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
    session.get.assert_called_once_with(
        "https://api.github.com/repos/psf/requests", timeout=5
    )


def test_token_sets_authorization_header():
    session = requests.Session()
    GitHubClient(session=session, token="secret-token")
    assert session.headers["Authorization"] == "Bearer secret-token"
    assert session.headers["Accept"].startswith("application/vnd.github")


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
