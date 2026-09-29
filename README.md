# Repo Radar 📡

**GitHub Repository Automation & Reporting** — a lightweight, production-style
Python CLI that reads a list of GitHub
`owner/repository` pairs from a CSV file, fetches live repository metadata
from the GitHub REST API, and writes structured **CSV + JSON** reports.

Built as a portfolio project to demonstrate clean, testable API automation:
robust HTTP handling (timeouts, exponential-backoff retries, rate-limit
awareness), strict input validation, structured logging, and a clear
separation between configuration and business logic.

```
CSV input ──► validate ──► GitHub REST API (timeout / retry / backoff) ──► CSV report
                                                                     └──► JSON report
```

## Features

- **CSV in → CSV + JSON out**, one row per repository: description, language,
  stars, forks, open issues, license, default branch, created/updated/pushed
  timestamps, and a per-row fetch `status`.
- **Resilient HTTP layer** — per-request timeouts, retries with exponential
  backoff, and `Retry-After` support for HTTP 429.
- **Explicit error handling** — typed exceptions (`RepositoryNotFoundError`,
  `RateLimitError`, `GitHubServerError`); one bad repository never aborts the
  run, it just becomes a `not_found` / `error` row in the report. Rate
  limiting gracefully stops the run instead of hammering the API.
- **Input validation** — owner/repository names are checked against GitHub's
  naming rules; invalid rows and duplicates are logged and skipped. BOM
  prefixed CSVs (Excel export) are handled transparently.
- **No hardcoded secrets** — an optional token is read from the
  `GITHUB_TOKEN` environment variable only (raises the rate limit from 60 to
  5,000 requests/hour).
- **Structured logging** with a run summary and meaningful exit codes
  (`0` success, `1` no repository fetched, `2` invalid input) for easy
  cron/CI integration.
- **Unit-tested with pytest** — the whole suite is mocked and never touches
  the network.

## Project structure

```
.
├── sample_repos.csv          # example input
├── requirements.txt
├── pyproject.toml            # pytest configuration
├── src/
│   ├── config.py             # all tunable defaults + token from env
│   ├── models.py             # RepoRequest / RepoReport dataclasses
│   ├── github_client.py      # REST client: timeout, retry, typed errors
│   ├── csv_loader.py         # input parsing + validation
│   ├── report_writer.py      # CSV + JSON output
│   └── main.py               # CLI entry point and run orchestration
├── tests/                    # 36 pytest unit tests (HTTP mocked)
└── output/                   # generated reports (gitignored)
```

## Requirements

- Python 3.11+
- pip

## Installation

```bash
git clone https://github.com/<your-account>/repo-radar.git
cd repo-radar

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

```bash
python -m src.main sample_repos.csv
```

Example run (last row of the sample CSV points to a repository that does
not exist on purpose, to demonstrate error isolation):

```
2026-09-29 13:26:30 INFO  __main__: GitHub token: not set (unauthenticated: 60 requests/hour)
2026-09-29 13:26:30 INFO  src.csv_loader: loaded 7 valid repositories (0 skipped) from sample_repos.csv
2026-09-29 13:26:31 INFO  __main__: fetched psf/requests (stars=54356)
2026-09-29 13:26:31 INFO  __main__: fetched pallets/flask (stars=74801)
2026-09-29 13:26:32 INFO  __main__: fetched pytest-dev/pytest (stars=14547)
2026-09-29 13:26:32 INFO  __main__: fetched encode/httpx (stars=15520)
2026-09-29 13:26:33 INFO  __main__: fetched fastapi/fastapi (stars=102708)
2026-09-29 13:26:33 INFO  __main__: fetched python/cpython (stars=77337)
2026-09-29 13:26:33 WARNING __main__: this-owner-does-not-exist-xyz987/not-a-real-repo: repository not found (HTTP 404)
2026-09-29 13:26:33 INFO  src.report_writer: CSV report written to output\repository_report.csv (7 rows)
2026-09-29 13:26:33 INFO  src.report_writer: JSON report written to output\repository_report.json (7 records)
2026-09-29 13:26:33 INFO  __main__: done: 6/7 fetched; reports: output\repository_report.csv, output\repository_report.json
```

### CLI options

| Option | Default | Description |
| --- | --- | --- |
| `input` (positional) | — | Path to the input CSV |
| `--output-dir` | `output` | Directory for the generated reports |
| `--token` | `$GITHUB_TOKEN` | GitHub token (prefer the env var) |
| `--timeout` | `10.0` | Per-request timeout in seconds |
| `--max-retries` | `3` | Retry attempts per request |
| `-v, --verbose` | off | Enable debug logging |

## Input format

A CSV with two columns, `owner` and `repository` (extra columns are ignored,
whitespace is trimmed, blank lines are skipped, duplicates are removed):

```csv
owner,repository
psf,requests
pallets,flask
pytest-dev,pytest
encode,httpx
fastapi,fastapi
python,cpython
this-owner-does-not-exist-xyz987,not-a-real-repo
```

Names are validated against GitHub's naming rules; rows that fail
validation are logged with their line number and skipped.

## Output

Both files are written to the output directory with a stable column order.

`output/repository_report.csv` (excerpt):

```csv
owner,repository,full_name,status,url,description,language,stars,forks,open_issues,archived,default_branch,license
psf,requests,psf/requests,ok,https://github.com/psf/requests,"A simple, yet elegant, HTTP library.",Python,54356,11389,241,False,main,Apache-2.0
pallets,flask,pallets/flask,ok,https://github.com/pallets/flask,The Python micro framework for building web applications.,Python,74801,17010,4,False,main,BSD-3-Clause
this-owner-does-not-exist-xyz987,not-a-real-repo,...,not_found,...,...,...,0,0,0,False,,,
```

`output/repository_report.json` (excerpt):

```json
{
  "generated_at": "2026-09-29T05:26:33Z",
  "total": 7,
  "repositories": [
    {
      "owner": "psf",
      "repository": "requests",
      "full_name": "psf/requests",
      "status": "ok",
      "url": "https://github.com/psf/requests",
      "description": "A simple, yet elegant, HTTP library.",
      "language": "Python",
      "stars": 54356,
      "forks": 11389,
      "open_issues": 241,
      "archived": false,
      "default_branch": "main",
      "license": "Apache-2.0",
      "created_at": "2011-02-13T18:38:17Z",
      "updated_at": "2026-09-28T20:19:51Z",
      "pushed_at": "2026-09-28T16:55:48Z",
      "fetched_at": "2026-09-29T05:26:31Z",
      "error_message": ""
    }
  ]
}
```

Every row carries a `status` (`ok`, `not_found`, `rate_limited`, `error`)
and an `error_message`; the `status` column tells you at a glance what
happened to each repository.

## Configuration & rate limits

Unauthenticated GitHub API access allows **60 requests/hour per IP**. Set a
token to raise this to **5,000 requests/hour** — never commit one:

```bash
export GITHUB_TOKEN=ghp_your_token_here      # Windows: set GITHUB_TOKEN=...
python -m src.main sample_repos.csv
```

All other defaults (base URL, timeout, retries, output paths) live in
`src/config.py` and can be overridden per run via CLI flags.

## Testing

```bash
pytest -v
```

36 unit tests cover input validation, retry/backoff behavior, error mapping
(404 / 403 / 429 / 5xx / timeouts / invalid JSON), report serialization, and
run orchestration. All HTTP interactions are mocked, so the suite is fast
and deterministic.
