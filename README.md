# Repo Radar

A small Python CLI that fetches GitHub repository metadata for a CSV list of
`owner/repository` pairs and writes CSV and JSON reports.

Repo Radar is an **independently developed portfolio project** built on the
public GitHub REST API. It is designed as a clean, extensible, tested
automation tool — not as a production service, and it makes no
enterprise-grade claims.

## Features

- **CSV input with validation** — required columns, GitHub naming rules,
  whitespace trimming, blank-line tolerance, duplicate removal, and
  Excel-BOM handling; one invalid row never aborts the run.
- **GitHub REST integration** — `GET /repos/{owner}/{repo}` via
  `requests`, with per-request timeouts, retries with exponential backoff,
  server `Retry-After` support, and typed exceptions
  (`RepositoryNotFoundError`, `RateLimitError`, `GitHubServerError`).
- **Controlled concurrency** — `--workers` bounded thread pool (default 4,
  hard cap 32, no unbounded task creation). Results are re-assembled in
  input order regardless of completion order.
- **Rate-limit awareness** — a primary rate limit (HTTP 403 with
  `X-RateLimit-Remaining: 0`) stops the run instead of hammering the API;
  HTTP 429 / 5xx are retried with backoff.
- **Per-item error isolation** — a 404 or network failure becomes a report
  row with a status, never a crashed run.
- **Two report formats** — CSV and/or JSON (`--output-format
  csv|json|both`) with a stable column order.
- **Layered settings** — CLI flag > environment variable > `.env` file >
  built-in default, documented and tested.
- **Packaging** — installable with `pip install -e .`, exposing a
  `repo-radar` console command; `python -m src.main` still works.
- **94 offline unit tests** — all HTTP mocked, deterministic, no network
  access, plus ruff static checks and a GitHub Actions CI workflow.

## Architecture

```
Input CSV            sample_repos.csv
   ↓
Validation           src/csv_loader.py     CSV parsing, naming rules, dedup
   ↓
Fetching             src/processor.py      sequential or bounded thread pool
   ↓                                       (per-item error isolation, stop
   ↓                                        on primary rate limit)
HTTP / rate control  src/github_client.py  timeouts, retry + backoff,
   ↓                                       Retry-After, typed errors
   ↓
Normalization        src/models.py         RepoRequest / RepoReport,
   ↓                                       stable REPORT_COLUMNS
   ↓
Report generation    src/report_writer.py  CSV + JSON writers
   ↓
CLI                  src/main.py           argparse, settings precedence,
                                           logging, exit codes
```

Supporting modules:

- `src/config.py` — all tunable defaults, env/.env resolution, hard
  worker cap.
- `src/pagination.py` — generic, tested pagination helper (a `Page`
  dataclass, a `paginate()` iterator, and GitHub `Link`-header parsing)
  kept ready for future list endpoints; the current single-object
  endpoint does not paginate, so the main flow does not use it.

Dependency rule: only `github_client.py` imports `requests`. The processor
depends on the client's interface (method + typed exceptions), which is
injected by the CLI layer — tests substitute fake clients, so the whole
suite runs offline.

## Requirements

- Python 3.11+
- pip

## Installation

```bash
git clone https://github.com/<your-account>/repo-radar.git
cd repo-radar

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"            # runtime + pytest + ruff
```

Not published to PyPI; install from a clone.

## Quick Start

```bash
repo-radar sample_repos.csv
# or, equivalently:
python -m src.main sample_repos.csv
```

Reports are written to `output/repository_report.csv` and
`output/repository_report.json`.

## CLI Options

| Option | Default | Description |
| --- | --- | --- |
| `input` (positional) | — | Path to the input CSV |
| `--input` | — | Same as the positional argument |
| `--output-dir` | `output` | Directory for the generated reports |
| `--output-format` | `both` | `csv`, `json`, or `both` |
| `--token` | `$GITHUB_TOKEN` | GitHub token (prefer the env var) |
| `--timeout` | `10.0` | Per-request timeout in seconds |
| `--max-retries` | `3` | Retry attempts per request |
| `--workers` | `4` | Concurrent requests, 1–32 |
| `-v, --verbose` | off | Enable debug logging |

### Settings precedence

Numeric settings and the token resolve as:

```
CLI flag  >  environment variable  >  .env file  >  built-in default
```

Supported environment variables (see `.env.example`):

| Variable | Used for |
| --- | --- |
| `GITHUB_TOKEN` | GitHub authentication |
| `REPO_RADAR_TIMEOUT` | per-request timeout (seconds) |
| `REPO_RADAR_MAX_RETRIES` | retry attempts per request |
| `REPO_RADAR_WORKERS` | concurrent requests |

A local `.env` file (gitignored; copy `.env.example`) is loaded first, and
real environment variables override it. Invalid values — a non-numeric
timeout, `--workers 0` or `--workers 99` — are rejected with exit code 2.

## Input Format

A CSV with two columns, `owner` and `repository` (extra columns are
ignored, whitespace is trimmed, blank lines are skipped, duplicates are
removed):

```csv
owner,repository
psf,requests
pallets,flask
pytest-dev,pytest
encode,httpx
fastapi,fastapi
python,cpython
django,django
pandas-dev,pandas
this-owner-does-not-exist-xyz987,not-a-real-repo
```

The last row points to a repository that does not exist on purpose, to
demonstrate error isolation. Names are validated against GitHub's naming
rules; rows that fail validation are logged with their line number and
skipped.

## Output Format

Both files are written to the output directory with a stable column order
(18 columns: identity, status, metadata, timestamps, `error_message`).

`output/repository_report.csv` (excerpt):

```csv
owner,repository,full_name,status,url,description,language,stars,forks,open_issues,archived,default_branch,license
psf,requests,psf/requests,ok,https://github.com/psf/requests,"A simple, yet elegant, HTTP library.",Python,54361,11433,241,False,main,Apache-2.0
pallets,flask,pallets/flask,ok,https://github.com/pallets/flask,The Python micro framework for building web applications.,Python,74805,17010,4,False,main,BSD-3-Clause
this-owner-does-not-exist-xyz987,not-a-real-repo,...,not_found,...,...,...,0,0,0,False,,,
```

`output/repository_report.json` (excerpt):

```json
{
  "generated_at": "2026-09-29T11:32:50Z",
  "total": 9,
  "repositories": [
    {
      "owner": "psf",
      "repository": "requests",
      "full_name": "psf/requests",
      "status": "ok",
      "url": "https://github.com/psf/requests",
      "description": "A simple, yet elegant, HTTP library.",
      "language": "Python",
      "stars": 54361,
      "forks": 11433,
      "open_issues": 241,
      "archived": false,
      "default_branch": "main",
      "license": "Apache-2.0",
      "created_at": "2011-02-13T18:38:17Z",
      "updated_at": "2026-09-29T09:49:45Z",
      "pushed_at": "2026-09-28T16:55:48Z",
      "fetched_at": "2026-09-29T11:32:50Z",
      "error_message": ""
    }
  ]
}
```

## Error Handling

Every input row produces exactly one report row with a `status`:

| Status | Meaning |
| --- | --- |
| `ok` | metadata fetched successfully |
| `not_found` | HTTP 404 — repository does not exist |
| `rate_limited` | GitHub rate limit hit; the run stopped early |
| `error` | any other API/network failure after retries |

Exit codes (for cron/CI integration):

| Code | Meaning |
| --- | --- |
| `0` | run completed (at least one repository fetched) |
| `1` | run completed but nothing could be fetched |
| `2` | invalid input or configuration |

Concurrency behavior is explicit: a primary rate limit stops the run — no
new request is started, requests already in flight may finish, and items
never started are dropped from the report. A failed or skipped repository
never affects the others, and the report preserves the input order.

## Authentication

GitHub's API is rate limited per IP:

| Mode | Rate limit |
| --- | --- |
| Unauthenticated | 60 requests/hour |
| With a personal access token | 5,000 requests/hour |

Set a token via the environment (never commit one):

```bash
export GITHUB_TOKEN=ghp_your_token_here      # Windows: set GITHUB_TOKEN=...
repo-radar sample_repos.csv
```

The token is read from `GITHUB_TOKEN` (or passed with `--token`) and is
never logged — only its presence is reported. `.env` is gitignored.

## Testing

```bash
pytest -v          # 94 tests, fully offline and deterministic
ruff check .       # static checks (pycodestyle, pyflakes, isort, bugbear)
```

The suite covers input validation, retry/backoff behavior, error mapping
(404 / 403 / 429 / 5xx / timeouts / invalid JSON), pagination (termination
conditions, page caps, non-advancing pages), concurrency (input-order
stability, worker-pool parallelism, error isolation, rate-limit stops),
settings precedence, `.env` loading, and the CLI surface including the
packaged entry point. All HTTP is mocked; nothing touches the network.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:
Python 3.11 and 3.13, dependency installation, `ruff check`, the offline
pytest suite, and CLI smoke checks (`python -m src.main --help`,
`repo-radar --help`).

## Project Structure

```
.
├── sample_repos.csv          # example input (8 valid repos + 1 intentional 404)
├── requirements.txt
├── pyproject.toml            # packaging, console script, pytest + ruff config
├── .env.example              # placeholder environment template
├── .github/workflows/ci.yml  # CI: ruff + pytest + CLI smoke checks
├── src/
│   ├── config.py             # defaults, env/.env resolution, worker cap
│   ├── models.py             # RepoRequest / RepoReport dataclasses
│   ├── csv_loader.py         # input parsing + validation
│   ├── github_client.py      # REST client: timeout, retry, typed errors
│   ├── processor.py          # business layer: sequential + concurrent runs
│   ├── pagination.py         # generic pagination helper (for future endpoints)
│   ├── report_writer.py      # CSV + JSON output
│   └── main.py               # CLI entry point and run orchestration
├── tests/                    # 94 offline pytest tests
└── output/                   # generated reports (gitignored)
```

## Limitations

Stated plainly, this tool currently does **not**:

- fetch anything beyond single-repository metadata (`GET /repos/{owner}/{repo}`);
  list/search endpoints are not implemented yet — `src/pagination.py` is a
  tested building block for adding them;
- persist anything (no database, no incremental/delta runs);
- offer async I/O or non-GitHub providers (threads only, one client);
- resume or queue around a primary rate limit — it stops the run and
  reports; waiting up to an hour inside one invocation is intentional
  non-behavior;
- ship to PyPI or provide signed releases.

With the unauthenticated 60-requests/hour budget, input lists beyond ~60
repositories will stop early unless a token is set.

## Example Output

Real run (`repo-radar sample_repos.csv --workers 3`, unauthenticated):

```
2026-09-29 19:32:28 INFO  src.main: GitHub token: not set (unauthenticated: 60 requests/hour)
2026-09-29 19:32:28 INFO  src.main: settings: workers=3 timeout=10.0s max_retries=3 output_format=both
2026-09-29 19:32:28 INFO  src.csv_loader: loaded 9 valid repositories (0 skipped) from sample_repos.csv
2026-09-29 19:32:28 INFO  src.processor: fetching 9 repositories with 3 worker(s)
2026-09-29 19:32:29 INFO  src.processor: [1/9] fetched psf/requests (stars=54361)
2026-09-29 19:32:29 INFO  src.processor: [3/9] fetched pytest-dev/pytest (stars=14548)
2026-09-29 19:32:29 INFO  src.processor: [2/9] fetched pallets/flask (stars=74805)
2026-09-29 19:32:30 WARNING src.processor: [9/9] this-owner-does-not-exist-xyz987/not-a-real-repo: repository not found (HTTP 404)
2026-09-29 19:32:30 INFO  src.processor: [7/9] fetched django/django (stars=91228)
2026-09-29 19:32:30 INFO  src.report_writer: CSV report written to output\repository_report.csv (9 rows)
2026-09-29 19:32:30 INFO  src.report_writer: JSON report written to output\repository_report.json (9 records)
2026-09-29 19:32:30 INFO  src.main: done: 8/9 fetched; reports: output\repository_report.csv, output\repository_report.json
```

Note the interleaved completion order (`[3/9]` before `[2/9]`) from the
worker pool, while the report files keep the input order, and the single
404 is recorded without stopping the run.
