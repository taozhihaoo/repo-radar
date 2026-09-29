"""Tests for the CSV/JSON report writers."""

import csv
import json

from src.models import RepoReport, RepoRequest
from src.report_writer import write_csv, write_json


def sample_report() -> RepoReport:
    payload = {
        "html_url": "https://github.com/psf/requests",
        "description": "A simple, yet elegant, HTTP library.",
        "language": "Python",
        "stargazers_count": 50000,
        "forks_count": 9000,
        "open_issues_count": 100,
        "archived": False,
        "default_branch": "main",
        "license": {"spdx_id": "Apache-2.0"},
        "created_at": "2011-01-01T00:00:00Z",
    }
    return RepoReport.success(RepoRequest("psf", "requests"), payload)


def test_write_csv_creates_parent_directories(tmp_path):
    path = write_csv([sample_report()], tmp_path / "nested" / "report.csv")

    assert path.exists()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["owner"] == "psf"
    assert rows[0]["stars"] == "50000"
    assert rows[0]["status"] == "ok"


def test_write_csv_empty_report_still_has_header(tmp_path):
    path = write_csv([], tmp_path / "empty.csv")

    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("owner,repository,full_name,status")


def test_write_json_envelope(tmp_path):
    path = write_json([sample_report()], tmp_path / "report.json")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total"] == 1
    assert data["repositories"][0]["full_name"] == "psf/requests"
    assert data["repositories"][0]["stars"] == 50000
    assert "generated_at" in data
