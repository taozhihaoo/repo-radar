"""Business layer: turn repository requests into report rows via a client.

The processor depends only on the client's *interface* (``get_repository``
plus its typed exceptions) -- never on ``requests`` or HTTP details. The
client is injected by the caller, so tests substitute fake clients and the
suite stays offline and deterministic.

Two execution modes share one per-item handler:

- ``fetch_reports`` -- sequential (one request at a time), used for
  ``--workers 1``. On a rate limit the run stops; items after it are not
  fetched and do not appear in the report.
- ``fetch_reports_concurrent`` -- bounded thread pool. Results are
  re-assembled in input order regardless of completion order. On a rate
  limit no new request is started; requests already in flight may finish,
  and items never started are dropped from the report (the same visible
  semantics as the sequential run).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from .github_client import GitHubAPIError, RateLimitError, RepositoryNotFoundError
from .models import (
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_RATE_LIMITED,
    RepoReport,
    RepoRequest,
)

logger = logging.getLogger(__name__)


def _fetch_single(
    request: RepoRequest,
    client: object,
    stop_event: threading.Event,
    position: int,
    total: int,
) -> RepoReport | None:
    """Fetch one repository; return ``None`` when skipped after a rate limit.

    Every failure mode is caught here so one broken item can never take
    down the whole run.
    """
    if stop_event.is_set():
        logger.debug(
            "[%d/%d] skipped %s (stopping after rate limit)", position, total, request.full_name
        )
        return None
    logger.debug("[%d/%d] fetching %s", position, total, request.full_name)
    try:
        payload = client.get_repository(request.owner, request.repository)  # type: ignore[attr-defined]
    except RepositoryNotFoundError as exc:
        logger.warning("[%d/%d] %s: %s", position, total, request.full_name, exc)
        return RepoReport.failure(request, STATUS_NOT_FOUND, str(exc))
    except RateLimitError as exc:
        stop_event.set()
        logger.error(
            "[%d/%d] %s: %s -- stopping the run so the API is not hammered",
            position,
            total,
            request.full_name,
            exc,
        )
        return RepoReport.failure(request, STATUS_RATE_LIMITED, str(exc))
    except GitHubAPIError as exc:
        logger.error("[%d/%d] %s: %s", position, total, request.full_name, exc)
        return RepoReport.failure(request, STATUS_ERROR, str(exc))
    except Exception as exc:  # isolation guarantee: no unexpected error escapes
        logger.error("[%d/%d] %s: unexpected failure: %s", position, total, request.full_name, exc)
        return RepoReport.failure(request, STATUS_ERROR, f"unexpected failure: {exc}")
    else:
        logger.info(
            "[%d/%d] fetched %s (stars=%d)",
            position,
            total,
            request.full_name,
            int(payload.get("stargazers_count") or 0),
        )
        return RepoReport.success(request, payload)


def fetch_reports(requests_list: list[RepoRequest], client: object) -> list[RepoReport]:
    """Fetch every request sequentially; collect successes and failures."""
    stop_event = threading.Event()
    total = len(requests_list)
    reports: list[RepoReport] = []
    for position, request in enumerate(requests_list, start=1):
        row = _fetch_single(request, client, stop_event, position, total)
        if row is not None:
            reports.append(row)
        if stop_event.is_set():
            break
    return reports


def fetch_reports_concurrent(
    requests_list: list[RepoRequest],
    client: object,
    workers: int,
) -> list[RepoReport]:
    """Fetch with a bounded thread pool; results keep the input order.

    At most ``workers`` requests are in flight at any moment -- the pool
    size is capped by the number of items, and callers cap ``workers``
    themselves (see config.MAX_WORKERS), so threads are never unbounded.
    """
    stop_event = threading.Event()
    total = len(requests_list)
    max_workers = max(1, min(workers, total))
    logger.info("fetching %d repositories with %d worker(s)", total, max_workers)

    results: list[RepoReport | None] = [None] * total
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="repo-radar") as pool:
        futures = [
            (index, pool.submit(_fetch_single, request, client, stop_event, index + 1, total))
            for index, request in enumerate(requests_list)
        ]
        for index, future in futures:
            results[index] = future.result()
    return [row for row in results if row is not None]
