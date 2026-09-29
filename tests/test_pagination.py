"""Tests for the generic pagination utility (pure logic, no HTTP)."""

import pytest

from src.pagination import Page, PaginationError, next_page_from_link_header, paginate


def page_source(pages: dict[int, tuple[tuple, int | None]]) -> tuple:
    """Build (fetch_page, call_log) from {page_number: (items, next_page)}."""
    calls: list[int] = []

    def fetch_page(number: int) -> Page:
        calls.append(number)
        items, next_page = pages[number]
        return Page(items=tuple(items), next_page=next_page)

    return fetch_page, calls


def test_yields_all_items_across_pages_in_order():
    fetch_page, calls = page_source(
        {1: (("a", "b"), 2), 2: (("c",), 3), 3: (("d", "e"), None)}
    )

    items = list(paginate(fetch_page))

    assert items == ["a", "b", "c", "d", "e"]
    assert calls == [1, 2, 3]  # each page fetched exactly once, no repeats


def test_single_page_terminates_immediately():
    fetch_page, calls = page_source({1: (("x",), None)})

    assert list(paginate(fetch_page)) == ["x"]
    assert calls == [1]


def test_empty_pages_terminate_cleanly():
    fetch_page, _ = page_source({1: ((), 2), 2: ((), None)})

    assert list(paginate(fetch_page)) == []


def test_max_pages_caps_number_of_fetches():
    fetch_page, calls = page_source(
        {1: (("a",), 2), 2: (("b",), 3), 3: (("c",), None)}
    )

    items = list(paginate(fetch_page, max_pages=2))

    assert items == ["a", "b"]
    assert calls == [1, 2]


def test_max_pages_one_fetches_only_first_page():
    fetch_page, calls = page_source({1: (("a",), 2), 2: (("b",), None)})

    assert list(paginate(fetch_page, max_pages=1)) == ["a"]
    assert calls == [1]


def test_start_page_is_honored():
    fetch_page, calls = page_source({4: (("d",), None)})

    assert list(paginate(fetch_page, start_page=4)) == ["d"]
    assert calls == [4]


def test_exception_from_fetch_page_propagates():
    def fetch_page(number: int) -> Page:
        raise PaginationError("simulated rate limit")  # any exception must surface

    with pytest.raises(PaginationError, match="rate limit"):
        list(paginate(fetch_page))


def test_self_referencing_page_raises_pagination_error():
    fetch_page, _ = page_source({1: (("a",), 1)})

    with pytest.raises(PaginationError, match="points to page"):
        list(paginate(fetch_page))


def test_backwards_page_raises_pagination_error():
    fetch_page, _ = page_source({2: (("b",), 1), 1: (("a",), 2)})

    with pytest.raises(PaginationError):
        list(paginate(fetch_page, start_page=2))


# --- next_page_from_link_header ------------------------------------------------

GITHUB_LINK_HEADER = (
    '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
    '<https://api.github.com/repositories/1/issues?page=7>; rel="last"'
)


def test_link_header_parses_next_page():
    assert next_page_from_link_header(GITHUB_LINK_HEADER) == 2


def test_link_header_without_next_returns_none():
    last_only = '<https://api.github.com/x?page=7>; rel="last"'
    assert next_page_from_link_header(last_only) is None


def test_missing_link_header_returns_none():
    assert next_page_from_link_header(None) is None
    assert next_page_from_link_header("") is None


def test_link_header_with_unparsable_url_returns_none():
    assert next_page_from_link_header('<https://api.github.com/x>; rel="next"') is None
