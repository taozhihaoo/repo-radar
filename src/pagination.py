"""Generic pagination helper for list-style REST endpoints.

The current Repo Radar workflow only calls ``GET /repos/{owner}/{repo}``,
which returns a single object and never paginates -- so the main flow does
not use this module today. It exists as a small, fully tested building
block for future list endpoints (user repositories, releases, search
results, ...) so they can be added without redesigning paging.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

# GitHub advertises pagination through the Link header, e.g.
#   <https://api.github.com/repos/x/y/issues?page=2>; rel="next", <...?page=7>; rel="last"
_LINK_URL_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
_LINK_PAGE_RE = re.compile(r"[?&]page=(\d+)")


class PaginationError(Exception):
    """Pagination would not terminate (a page points backwards or to itself)."""


@dataclass(frozen=True)
class Page:
    """One fetched page: its items plus the number of the next page.

    ``next_page`` is ``None`` for the last page.
    """

    items: tuple[object, ...]
    next_page: int | None


def next_page_from_link_header(header: str | None) -> int | None:
    """Extract the next page number from a GitHub ``Link`` response header.

    Returns ``None`` when the header is missing or contains no ``rel="next"``
    entry, i.e. when the current page is the last one.
    """
    if not header:
        return None
    url_match = _LINK_URL_RE.search(header)
    if url_match is None:
        return None
    page_match = _LINK_PAGE_RE.search(url_match.group(1))
    if page_match is None:
        return None
    return int(page_match.group(1))


def paginate(
    fetch_page: Callable[[int], Page],
    *,
    start_page: int = 1,
    max_pages: int | None = None,
) -> Iterator[object]:
    """Yield every item from ``fetch_page(page)`` until the last page.

    - Stops when a page reports ``next_page is None`` (last page).
    - Caps the number of fetched pages when *max_pages* is given.
    - Yields items in page order and fetches each page exactly once, so no
      duplicates are introduced by the iteration itself.
    - Exceptions raised by ``fetch_page`` (network errors, rate limits, ...)
      propagate to the caller and end the iteration.

    Raises:
        PaginationError: if a page points to itself or backwards, which
            would loop forever.
    """
    page = start_page
    pages_fetched = 0
    while True:
        result = fetch_page(page)
        pages_fetched += 1
        yield from result.items
        if result.next_page is None:
            return
        if result.next_page <= page:
            raise PaginationError(f"page {page} points to page {result.next_page}; aborting loop")
        if max_pages is not None and pages_fetched >= max_pages:
            return
        page = result.next_page
