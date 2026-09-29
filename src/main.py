"""Command-line entry point.

Reads a CSV of owner/repository pairs, fetches each repository from the
GitHub API, and writes CSV + JSON reports. Per-repository failures are
recorded in the report instead of aborting the run.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config
from .csv_loader import CSVFormatError, load_repositories
from .github_client import GitHubAPIError, GitHubClient, RateLimitError, RepositoryNotFoundError
from .models import (
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    RepoReport,
    RepoRequest,
)
from .report_writer import write_csv, write_json

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="github-repo-reporting",
        description=(
            "Fetch GitHub repository metadata for a CSV list of owner/repository "
            "pairs and write CSV + JSON reports."
        ),
    )
    parser.add_argument("input", help="input CSV with 'owner' and 'repository' columns")
    parser.add_argument(
        "--output-dir",
        default=config.OUTPUT_DIR,
        help="directory for the generated reports (default: %(default)s)",
    )
    parser.add_argument(
        "--token",
        help="GitHub token; prefer the GITHUB_TOKEN environment variable instead",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=config.REQUEST_TIMEOUT_SECONDS,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=config.MAX_RETRIES,
        help="retry attempts per request (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args(argv)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def fetch_reports(requests_list: list[RepoRequest], client: GitHubClient) -> list[RepoReport]:
    """Fetch every request; collect successes and failures into report rows."""
    reports: list[RepoReport] = []
    for request in requests_list:
        try:
            payload = client.get_repository(request.owner, request.repository)
        except RepositoryNotFoundError as exc:
            logger.warning("%s: %s", request.full_name, exc)
            reports.append(RepoReport.failure(request, STATUS_NOT_FOUND, str(exc)))
        except RateLimitError as exc:
            logger.error(
                "%s: %s -- stopping the run so the API is not hammered", request.full_name, exc
            )
            reports.append(RepoReport.failure(request, STATUS_RATE_LIMITED, str(exc)))
            break
        except GitHubAPIError as exc:
            logger.error("%s: %s", request.full_name, exc)
            reports.append(RepoReport.failure(request, STATUS_ERROR, str(exc)))
        else:
            logger.info(
                "fetched %s (stars=%d)",
                request.full_name,
                int(payload.get("stargazers_count") or 0),
            )
            reports.append(RepoReport.success(request, payload))
    return reports


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    token = args.token or config.get_github_token()
    logger.info(
        "GitHub token: %s",
        "provided" if token else "not set (unauthenticated: 60 requests/hour)",
    )

    try:
        requests_list = load_repositories(args.input)
    except CSVFormatError as exc:
        logger.error("input error: %s", exc)
        return 2
    if not requests_list:
        logger.error("no valid repositories found in %s", args.input)
        return 2

    client = GitHubClient(
        base_url=config.API_BASE_URL,
        token=token,
        timeout=args.timeout,
        max_retries=args.max_retries,
        backoff=config.RETRY_BACKOFF_SECONDS,
    )
    reports = fetch_reports(requests_list, client)

    output_dir = Path(args.output_dir)
    csv_path = write_csv(reports, output_dir / config.OUTPUT_CSV_NAME)
    json_path = write_json(reports, output_dir / config.OUTPUT_JSON_NAME)

    succeeded = sum(1 for report in reports if report.status == STATUS_OK)
    logger.info("done: %d/%d fetched; reports: %s, %s", succeeded, len(reports), csv_path, json_path)
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
