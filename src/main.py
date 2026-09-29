"""Command-line entry point.

Reads a CSV of owner/repository pairs, fetches each repository from the
GitHub API (sequentially or with a bounded worker pool), and writes CSV
and/or JSON reports. Per-repository failures are recorded in the report
instead of aborting the run.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config
from .csv_loader import CSVFormatError, load_repositories
from .github_client import GitHubClient
from .models import STATUS_OK
from .processor import fetch_reports, fetch_reports_concurrent
from .report_writer import write_csv, write_json

__all__ = ["fetch_reports", "main", "parse_args", "setup_logging"]

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo-radar",
        description=(
            "Fetch GitHub repository metadata for a CSV list of owner/repository "
            "pairs and write CSV and/or JSON reports."
        ),
    )
    parser.add_argument(
        "input_positional",
        nargs="?",
        metavar="input",
        help="input CSV with 'owner' and 'repository' columns",
    )
    parser.add_argument(
        "--input",
        dest="input_option",
        help="path to the input CSV (same as the positional argument)",
    )
    parser.add_argument(
        "--output-dir",
        default=config.OUTPUT_DIR,
        help="directory for the generated reports (default: %(default)s)",
    )
    parser.add_argument(
        "--output-format",
        choices=("csv", "json", "both"),
        default="both",
        help="which reports to write (default: %(default)s)",
    )
    parser.add_argument(
        "--token",
        help="GitHub token; prefer the GITHUB_TOKEN environment variable instead",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "per-request timeout in seconds "
            f"(default: {config.REQUEST_TIMEOUT_SECONDS:g}, or ${config.TIMEOUT_ENV_VAR})"
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help=(
            "retry attempts per request "
            f"(default: {config.MAX_RETRIES}, or ${config.MAX_RETRIES_ENV_VAR})"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "number of concurrent requests, 1-%d "
            f"(default: {config.DEFAULT_WORKERS}, or ${config.WORKERS_ENV_VAR})"
            % config.MAX_WORKERS
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")

    args = parser.parse_args(argv)
    if args.input_option and args.input_positional:
        parser.error("give the input CSV either positionally or via --input, not both")
    if not args.input_option and not args.input_positional:
        parser.error("an input CSV is required (positional argument or --input)")
    return args


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    config.load_dotenv()
    try:
        settings = config.resolve_settings(
            timeout=args.timeout,
            max_retries=args.max_retries,
            workers=args.workers,
        )
    except config.ConfigError as exc:
        logger.error("configuration error: %s", exc)
        return 2

    token = args.token or config.get_github_token()
    logger.info(
        "GitHub token: %s",
        "provided" if token else "not set (unauthenticated: 60 requests/hour)",
    )
    logger.info(
        "settings: workers=%d timeout=%.1fs max_retries=%d output_format=%s",
        settings.workers,
        settings.timeout,
        settings.max_retries,
        args.output_format,
    )

    input_csv = args.input_option or args.input_positional
    try:
        requests_list = load_repositories(input_csv)
    except CSVFormatError as exc:
        logger.error("input error: %s", exc)
        return 2
    if not requests_list:
        logger.error("no valid repositories found in %s", input_csv)
        return 2

    client = GitHubClient(
        base_url=config.API_BASE_URL,
        token=token,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
        backoff=config.RETRY_BACKOFF_SECONDS,
    )
    if settings.workers > 1:
        reports = fetch_reports_concurrent(requests_list, client, settings.workers)
    else:
        reports = fetch_reports(requests_list, client)

    output_dir = Path(args.output_dir)
    written: list[Path] = []
    if args.output_format in ("csv", "both"):
        written.append(write_csv(reports, output_dir / config.OUTPUT_CSV_NAME))
    if args.output_format in ("json", "both"):
        written.append(write_json(reports, output_dir / config.OUTPUT_JSON_NAME))

    succeeded = sum(1 for report in reports if report.status == STATUS_OK)
    logger.info(
        "done: %d/%d fetched; reports: %s",
        succeeded,
        len(reports),
        ", ".join(str(path) for path in written),
    )
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
