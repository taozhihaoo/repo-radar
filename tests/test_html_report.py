"""Tests for the self-contained HTML report."""

import json
import re

import pytest

from src.html_report import DATA_PLACEHOLDER, render_html, write_html
from src.models import RepoReport, RepoRequest


def make_reports() -> list[RepoReport]:
    ok = RepoReport.success(
        RepoRequest("psf", "requests"),
        {
            "html_url": "https://github.com/psf/requests",
            "description": "A simple, yet elegant, HTTP library.",
            "language": "Python",
            "stargazers_count": 54000,
            "forks_count": 11000,
            "open_issues_count": 240,
            "license": {"spdx_id": "Apache-2.0"},
            "pushed_at": "2026-09-28T16:55:48Z",
        },
    )
    missing = RepoReport.failure(
        RepoRequest("nope", "missing"), "not_found", "repository not found (HTTP 404)"
    )
    return [ok, missing]


def embedded_payload(html: str) -> dict:
    """Pull the JSON payload back out of the generated document."""
    match = re.search(r"const DATA = (\{.*?\});\n", html, re.DOTALL)
    assert match, "the report data was not embedded"
    return json.loads(match.group(1))


def test_placeholder_is_replaced():
    html = render_html(make_reports())
    assert DATA_PLACEHOLDER not in html
    assert "const DATA = {" in html


def test_payload_round_trips():
    payload = embedded_payload(render_html(make_reports()))
    assert payload["total"] == 2
    assert [row["status"] for row in payload["repositories"]] == ["ok", "not_found"]
    assert payload["repositories"][0]["stars"] == 54000


def test_language_is_embedded_and_defaults_to_english():
    assert embedded_payload(render_html(make_reports()))["lang"] == "en"
    assert embedded_payload(render_html(make_reports(), lang="zh"))["lang"] == "zh"


def test_unsupported_language_rejected():
    with pytest.raises(ValueError, match="unsupported language"):
        render_html(make_reports(), lang="fr")


def test_script_tag_injection_in_description_is_neutralised():
    payload = {
        "description": 'evil </script><script>alert("x")</script>',
        "language": "Python",
    }
    report = RepoReport.success(RepoRequest("a", "b"), payload)
    html = render_html([report])

    # The only closing script tag may be the template's own one.
    assert html.count("</script>") == 1
    # ... and the payload must still parse, with the text intact.
    assert "</script>" in embedded_payload(html)["repositories"][0]["description"]


def test_html_is_self_contained():
    html = render_html(make_reports())
    assert "http://" not in html.split("<body>")[0]
    assert "cdn" not in html.lower()
    assert "<style>" in html and "<script>" in html


def test_write_html_creates_parent_directories(tmp_path):
    path = write_html(make_reports(), tmp_path / "nested" / "report.html", lang="zh")

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert embedded_payload(text)["lang"] == "zh"


def test_write_html_leaves_no_temporary_files(tmp_path):
    write_html(make_reports(), tmp_path / "report.html")
    assert [p.name for p in tmp_path.iterdir()] == ["report.html"]
