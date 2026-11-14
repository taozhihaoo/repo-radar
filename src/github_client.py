"""GitHub REST API client with timeouts, retries, and explicit error types.

Two deliberate design choices:

- **Per-thread HTTP sessions.** ``requests.Session`` is not documented as
  thread-safe, and the processor runs requests from a thread pool. When no
  session is injected, each thread gets its own session (created lazily and
  closed by :meth:`GitHubClient.close`). An injected session is used as-is,
  which keeps tests and callers in control.
- **Bounded retries.** Retryable responses are retried with exponential
  backoff, but no single sleep may exceed ``max_retry_delay``. A server that
  asks for a longer wait is treated as a rate limit instead of stalling the
  whole run.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from . import __version__

logger = logging.getLogger(__name__)

# Status codes worth another attempt: transient server errors and the
# secondary rate-limit response. Primary rate limiting (HTTP 403 with
# X-RateLimit-Remaining: 0) is raised immediately -- waiting up to an
# hour inside one call is never the right move.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

DEFAULT_BASE_URL = "https://api.github.com"


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
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff: float = 1.0,
        max_retry_delay: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(max_retries, 1)
        self._backoff = backoff
        self._max_retry_delay = max(max_retry_delay, 0.0)
        self._token = token
        self._injected_session = session
        self._thread_local = threading.local()
        self._owned_sessions: list[requests.Session] = []
        self._owned_lock = threading.Lock()
        if session is not None:
            self._apply_headers(session)

    # -- session handling ---------------------------------------------------

    def _apply_headers(self, session: requests.Session) -> None:
        session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"repo-radar/{__version__}",
            }
        )
        if self._token:
            session.headers["Authorization"] = f"Bearer {self._token}"

    @property
    def _session(self) -> requests.Session:
        """The injected session, or a lazily created per-thread session."""
        if self._injected_session is not None:
            return self._injected_session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._apply_headers(session)
            self._thread_local.session = session
            with self._owned_lock:
                self._owned_sessions.append(session)
        return session

    def close(self) -> None:
        """Close sessions this client created (an injected session is left open)."""
        with self._owned_lock:
            owned, self._owned_sessions = self._owned_sessions, []
        for session in owned:
            try:
                session.close()
            except Exception:  # pragma: no cover - defensive, close() must not raise
                logger.debug("failed to close an HTTP session", exc_info=True)

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- API ----------------------------------------------------------------

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
            payload = response.json()
        except ValueError as exc:
            raise GitHubAPIError(f"invalid JSON in response for {path}") from exc
        if not isinstance(payload, dict):
            raise GitHubAPIError(
                f"unexpected JSON payload type for {path}: {type(payload).__name__}"
            )
        return payload

    def _get_with_retries(self, path: str) -> requests.Response:
        """GET ``{base_url}{path}`` with retry/backoff; returns the 200 response."""
        url = f"{self._base_url}{path}"
        last_error: GitHubAPIError | None = None

        for attempt in range(1, self._max_retries + 1):
            response: requests.Response | None = None
            try:
                response = self._session.get(url, timeout=self._timeout)
            except requests.RequestException as exc:
                last_error = self._network_error(path, exc)
                logger.warning(
                    "network error on %s (attempt %d/%d): %s",
                    path,
                    attempt,
                    self._max_retries,
                    exc,
                )
            else:
                if response.status_code == 200:
                    return response
                error = self._error_for(response)
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    _close_quietly(response)
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
                try:
                    self._sleep_before_retry(response, attempt, path)
                finally:
                    _close_quietly(response)

        # Unreachable in practice (max_retries >= 1), but never rely on assert:
        # assertions vanish under ``python -O``.
        raise last_error or GitHubAPIError(f"no response for {path}")

    @staticmethod
    def _network_error(path: str, exc: requests.RequestException) -> GitHubAPIError:
        """Map a transport-level failure to a descriptive API error."""
        if isinstance(exc, requests.Timeout):
            return GitHubAPIError(f"timed out calling {path}: {exc}")
        return GitHubAPIError(f"network error calling {path}: {exc}")

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

    def _sleep_before_retry(
        self,
        response: requests.Response | None,
        attempt: int,
        path: str = "",
    ) -> None:
        """Exponential backoff, honoring a server-provided Retry-After.

        The delay is capped at ``max_retry_delay``. If the server asks for a
        longer wait than the cap, the remaining retries would be pointless, so
        the run is told to stop instead of blocking: a
        :class:`RateLimitError` is raised.
        """
        delay = min(self._backoff * (2 ** (attempt - 1)), self._max_retry_delay)
        if response is not None:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                if retry_after > self._max_retry_delay:
                    raise RateLimitError(
                        f"GitHub asked to retry after {retry_after:g}s, above the "
                        f"{self._max_retry_delay:g}s cap; giving up on {path or 'the request'}"
                    )
                delay = max(delay, retry_after)
        logger.info("retrying in %.1f s (attempt %d/%d)", delay, attempt + 1, self._max_retries)
        time.sleep(delay)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (seconds form); ``None`` when unusable."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        logger.debug("ignoring non-numeric Retry-After header: %r", value)
        return None
    return seconds if seconds >= 0 else None


def _close_quietly(response: requests.Response | None) -> None:
    """Release a connection without letting cleanup mask the real error."""
    if response is None:
        return
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # pragma: no cover - defensive
            logger.debug("failed to close a response", exc_info=True)
