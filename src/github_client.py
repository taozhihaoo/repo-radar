"""GitHub REST API client with timeouts, retries, and explicit error types."""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Status codes worth another attempt: transient server errors and the
# secondary rate-limit response. Primary rate limiting (HTTP 403 with
# X-RateLimit-Remaining: 0) is raised immediately -- waiting up to an
# hour inside one call is never the right move.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class GitHubAPIError(Exception):
    """Base class for all GitHub API failures."""


class RepositoryNotFoundError(GitHubAPIError):
    """The requested repository does not exist (HTTP 404)."""


class RateLimitError(GitHubAPIError):
    """The GitHub API rate limit was hit (HTTP 403/429)."""


class GitHubServerError(GitHubAPIError):
    """GitHub answered with a server error (5xx) and retries were exhausted."""


class GitHubClient:
    """Small requests-based client for the read-only endpoints we need."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        base_url: str = "https://api.github.com",
        token: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        self._session = session or requests.Session()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(max_retries, 1)
        self._backoff = backoff
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "github-repo-automation-reporting/1.0",
            }
        )
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def get_repository(self, owner: str, repository: str) -> dict:
        """Fetch one repository's metadata.

        Returns the decoded JSON payload.

        Raises:
            RepositoryNotFoundError: the repository does not exist (404).
            RateLimitError: the API rate limit was hit.
            GitHubAPIError: any other network or API failure.
        """
        path = f"/repos/{owner}/{repository}"
        response = self._get_with_retries(path)
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubAPIError(f"invalid JSON in response for {path}") from exc

    def _get_with_retries(self, path: str) -> requests.Response:
        """GET ``{base_url}{path}`` with retry/backoff; returns the 200 response."""
        url = f"{self._base_url}{path}"
        last_error: GitHubAPIError | None = None

        for attempt in range(1, self._max_retries + 1):
            response: requests.Response | None = None
            try:
                response = self._session.get(url, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = GitHubAPIError(f"network error calling {path}: {exc}")
                logger.warning(
                    "network error on %s (attempt %d/%d): %s", path, attempt, self._max_retries, exc
                )
            except requests.RequestException as exc:
                last_error = GitHubAPIError(f"request failed calling {path}: {exc}")
                logger.warning(
                    "request error on %s (attempt %d/%d): %s", path, attempt, self._max_retries, exc
                )
            else:
                if response.status_code == 200:
                    return response
                error = self._error_for(response)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise error
                last_error = error
                logger.warning(
                    "HTTP %d on %s (attempt %d/%d)",
                    response.status_code,
                    path,
                    attempt,
                    self._max_retries,
                )

            if attempt < self._max_retries:
                self._sleep_before_retry(response, attempt)

        assert last_error is not None  # every completed loop iteration sets it
        raise last_error

    @staticmethod
    def _error_for(response: requests.Response) -> GitHubAPIError:
        """Map a non-200 response to the most specific error type."""
        status = response.status_code
        if status == 404:
            return RepositoryNotFoundError("repository not found (HTTP 404)")
        if status == 429 or (
            status == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
        ):
            return RateLimitError(f"GitHub API rate limit exceeded (HTTP {status})")
        if status == 403:
            return GitHubAPIError("access forbidden (HTTP 403); check token scope")
        if 500 <= status <= 599:
            return GitHubServerError(f"GitHub server error (HTTP {status})")
        return GitHubAPIError(f"unexpected HTTP {status} from the GitHub API")

    def _sleep_before_retry(self, response: requests.Response | None, attempt: int) -> None:
        """Exponential backoff, honoring a server-provided Retry-After."""
        delay = self._backoff * (2 ** (attempt - 1))
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    logger.debug("ignoring non-numeric Retry-After header: %r", retry_after)
        logger.info("retrying in %.1f s (attempt %d/%d)", delay, attempt + 1, self._max_retries)
        time.sleep(delay)
