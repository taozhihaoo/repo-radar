"""Offline end-to-end smoke run used by CI.

Runs the real CLI pipeline (argument parsing -> CSV loading -> processing ->
all three report writers) with the HTTP client replaced by a stub, so the
check needs no network and no token, yet exercises the installed entry point
the same way a user would.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import src.main as main_module

STUB_PAYLOADS = {
    "psf/requests": {
        "html_url": "https://github.com/psf/requests",
        "description": "A simple, yet elegant, HTTP library.",
        "language": "Python",
        "stargazers_count": 54321,
        "forks_count": 11000,
        "open_issues_count": 240,
        "license": {"spdx_id": "Apache-2.0"},
        "pushed_at": "2026-09-28T16:55:48Z",
    },
    "pallets/flask": {
        "html_url": "https://github.com/pallets/flask",
        "description": "The Python micro framework for building web applications.",
        "language": "Python",
        "stargazers_count": 74805,
        "forks_count": 17010,
        "open_issues_count": 4,
        "license": {"spdx_id": "BSD-3-Clause"},
        "pushed_at": "2026-09-20T10:00:00Z",
    },
}


class StubClient:
    """Minimal stand-in for GitHubClient (no sockets involved)."""

    def __init__(self, **_kwargs: object) -> None:
        self.calls: list[str] = []

    def get_repository(self, owner: str, repository: str) -> dict:
        self.calls.append(f"{owner}/{repository}")
        return STUB_PAYLOADS[self.calls[-1]]

    def close(self) -> None:
        return None


def main() -> int:
    main_module.GitHubClient = StubClient  # type: ignore[assignment]

    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        input_csv = root / "repos.csv"
        input_csv.write_text("owner,repository\npsf,requests\npallets,flask\n", encoding="utf-8")
        output_dir = root / "out"

        exit_code = main_module.main(
            [
                str(input_csv),
                "--output-dir",
                str(output_dir),
                "--output-format",
                "all",
                "--workers",
                "2",
            ]
        )
        if exit_code != 0:
            print(f"FAILED: exit code {exit_code}", file=sys.stderr)
            return 1

        expected = ("repository_report.csv", "repository_report.json", "repository_report.html")
        missing = [name for name in expected if not (output_dir / name).is_file()]
        if missing:
            print(f"FAILED: missing reports {missing}", file=sys.stderr)
            return 1

        html = (output_dir / "repository_report.html").read_text(encoding="utf-8")
        for needle in ("psf/requests", "pallets/flask", "Repo Radar"):
            if needle not in html:
                print(f"FAILED: {needle!r} missing from the HTML report", file=sys.stderr)
                return 1

    print("ok: end-to-end run produced CSV, JSON and HTML reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
