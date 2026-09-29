"""Tests for the processor: concurrency, ordering, and error isolation.

All clients are fakes; timing uses generous sleeps so assertions stay
deterministic without touching the network.
"""

import threading
import time

from src.github_client import GitHubAPIError, RateLimitError, RepositoryNotFoundError
from src.models import RepoRequest
from src.processor import fetch_reports, fetch_reports_concurrent

PAYLOAD = {"stargazers_count": 100}


class FakeClient:
    """Per-repo behaviour dict; sleeps *before* acting to widen race windows.

    ``delays`` maps full_name -> seconds slept before the call resolves.
    Records every call in execution order.
    """

    def __init__(self, behaviour: dict, delays: dict[str, float] | None = None) -> None:
        self._behaviour = behaviour
        self._delays = delays or {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def get_repository(self, owner: str, repository: str) -> dict:
        full_name = f"{owner}/{repository}"
        with self._lock:
            self.calls.append(full_name)
        time.sleep(self._delays.get(full_name, 0.0))
        result = self._behaviour[full_name]
        if isinstance(result, Exception):
            raise result
        return result


class BarrierClient:
    """The first *barrier_items* calls must all be in flight simultaneously.

    If the pool does not actually run ``parties`` requests concurrently,
    the barrier times out and raises, turning those rows into errors --
    which fails the tests that assert every row is ok.
    """

    def __init__(self, parties: int, barrier_items: int) -> None:
        self._barrier = threading.Barrier(parties)
        self._barrier_items = barrier_items
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def get_repository(self, owner: str, repository: str) -> dict:
        full_name = f"{owner}/{repository}"
        with self._lock:
            index = len(self.calls)
            self.calls.append(full_name)
        if index < self._barrier_items:
            self._barrier.wait(timeout=5)
        return PAYLOAD


def make_requests(*full_names: str) -> list[RepoRequest]:
    return [RepoRequest(*name.split("/")) for name in full_names]


def names(reports):
    """RepoReport keeps owner/repository fields; full_name only exists in to_dict()."""
    return [f"{r.owner}/{r.repository}" for r in reports]


# --- sequential mode -----------------------------------------------------------

def test_sequential_records_every_outcome_in_input_order():
    client = FakeClient(
        {
            "a/one": PAYLOAD,
            "b/two": RepositoryNotFoundError("not found"),
            "c/three": GitHubAPIError("boom"),
        }
    )

    reports = fetch_reports(make_requests("a/one", "b/two", "c/three"), client)

    assert [(r.owner, r.status) for r in reports] == [
        ("a", "ok"),
        ("b", "not_found"),
        ("c", "error"),
    ]


def test_sequential_rate_limit_stops_the_run():
    client = FakeClient(
        {
            "a/one": RateLimitError("rate limit"),
            "b/two": PAYLOAD,
        }
    )

    reports = fetch_reports(make_requests("a/one", "b/two"), client)

    assert client.calls == ["a/one"]
    assert [r.status for r in reports] == ["rate_limited"]


# --- concurrent mode -------------------------------------------------------------

def test_concurrent_results_keep_input_order_despite_completion_order():
    # Later items finish first; the report must still follow input order.
    client = FakeClient(
        {name: PAYLOAD for name in ("a/one", "b/two", "c/three", "d/four")},
        delays={"a/one": 0.4, "b/two": 0.3, "c/three": 0.2, "d/four": 0.1},
    )

    reports = fetch_reports_concurrent(
        make_requests("a/one", "b/two", "c/three", "d/four"), client, workers=4
    )

    assert names(reports) == ["a/one", "b/two", "c/three", "d/four"]
    assert all(r.status == "ok" for r in reports)


def test_concurrent_error_isolation_one_failure_never_affects_others():
    client = FakeClient(
        {
            "a/one": PAYLOAD,
            "b/two": RepositoryNotFoundError("not found"),
            "c/three": GitHubAPIError("boom"),
            "d/four": PAYLOAD,
        }
    )

    reports = fetch_reports_concurrent(
        make_requests("a/one", "b/two", "c/three", "d/four"), client, workers=3
    )

    assert [(n, r.status) for n, r in zip(names(reports), reports, strict=True)] == [
        ("a/one", "ok"),
        ("b/two", "not_found"),
        ("c/three", "error"),
        ("d/four", "ok"),
    ]
    assert set(client.calls) == {"a/one", "b/two", "c/three", "d/four"}


def test_concurrent_rate_limit_stops_new_requests():
    # a/one sleeps before raising so b/two is already in flight; once the
    # rate limit fires, no further request may start.
    client = FakeClient(
        {
            "a/one": RateLimitError("rate limit"),
            "b/two": PAYLOAD,
            "c/three": PAYLOAD,
            "d/four": PAYLOAD,
        },
        delays={"a/one": 0.2, "b/two": 0.6},  # b/two outlives the rate-limit event
    )

    reports = fetch_reports_concurrent(
        make_requests("a/one", "b/two", "c/three", "d/four"), client, workers=2
    )

    assert client.calls == ["a/one", "b/two"]  # items 3-4 were never requested
    assert [(n, r.status) for n, r in zip(names(reports), reports, strict=True)] == [
        ("a/one", "rate_limited"),
        ("b/two", "ok"),
    ]


def test_concurrent_pool_actually_runs_workers_in_parallel():
    client = BarrierClient(parties=3, barrier_items=3)

    reports = fetch_reports_concurrent(
        make_requests("a/one", "b/two", "c/three", "d/four", "e/five", "f/six"),
        client,
        workers=3,
    )

    assert len(reports) == 6
    assert all(r.status == "ok" for r in reports)


def test_sequential_and_concurrent_agree_on_results():
    behaviour = {
        "a/one": PAYLOAD,
        "b/two": RepositoryNotFoundError("not found"),
        "c/three": PAYLOAD,
    }
    requests_list = make_requests("a/one", "b/two", "c/three")

    sequential = fetch_reports(requests_list, FakeClient(behaviour))
    concurrent = fetch_reports_concurrent(requests_list, FakeClient(behaviour), workers=3)

    assert names(sequential) == names(concurrent)
    assert [(r.status, r.stars) for r in sequential] == [
        (r.status, r.stars) for r in concurrent
    ]


def test_concurrent_worker_count_is_capped_by_item_count():
    client = BarrierClient(parties=1, barrier_items=1)

    reports = fetch_reports_concurrent(make_requests("a/one"), client, workers=16)

    assert [r.status for r in reports] == ["ok"]
