"""Tests for the data models."""

import pytest

from src.models import REPORT_COLUMNS, RepoReport, RepoRequest, ValidationError


def test_full_name_property():
    assert RepoRequest("psf", "requests").full_name == "psf/requests"


@pytest.mark.parametrize(
    "owner",
    ["", "has space", "-leading", "trailing-", "x" * 40],
)
def test_invalid_owner_rejected(owner):
    with pytest.raises(ValidationError):
        RepoRequest(owner, "requests")


@pytest.mark.parametrize("repository", ["", "has space", "x" * 101])
def test_invalid_repository_rejected(repository):
    with pytest.raises(ValidationError):
        RepoRequest("psf", repository)


def test_success_maps_api_payload():
    payload = {
        "html_url": "https://github.com/psf/requests",
        "description": None,  # GitHub returns null for missing descriptions
        "language": "Python",
        "stargazers_count": 50000,
        "forks_count": 9000,
        "open_issues_count": 100,
        "archived": False,
        "default_branch": "main",
        "license": {"spdx_id": "Apache-2.0"},
        "created_at": "2011-01-01T00:00:00Z",
    }

    report = RepoReport.success(RepoRequest("psf", "requests"), payload)

    assert report.status == "ok"
    assert report.description == ""
    assert report.license == "Apache-2.0"
    assert report.stars == 50000
    assert report.to_dict()["full_name"] == "psf/requests"


def test_success_without_license():
    report = RepoReport.success(RepoRequest("psf", "requests"), {"license": None})
    assert report.license == ""


def test_failure_row_keeps_error_details():
    report = RepoReport.failure(
        RepoRequest("psf", "requests"), "not_found", "repository not found (HTTP 404)"
    )
    assert report.status == "not_found"
    assert report.error_message == "repository not found (HTTP 404)"
    assert report.stars == 0


def test_to_dict_matches_report_columns():
    report = RepoReport.failure(RepoRequest("a", "b"), "error", "boom")
    assert list(report.to_dict()) == list(REPORT_COLUMNS)
