"""Command-line entry point.

Reads a CSV of owner/repository pairs, fetches each repository from the
GitHub API (sequentially or with a bounded worker pool), and writes CSV,
JSON and/or HTML reports. Per-repository failures are recorded in the
report instead of aborting the run.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config
from .console import LOG_FORMAT, build_formatter, supports_color
from .csv_loader import CSVFormatError, load_repositories
from .github_client import GitHubClient
from .html_report import write_html
from .models import STATUS_OK, RepoReport
from .processor import fetch_reports, fetch_reports_concurrent
from .report_writer import write_csv, write_json

__all__ = [
    "fetch_reports",
    "fetch_reports_concurrent",
    "main",
    "parse_args",
    "setup_logging",
    "write_reports",
]

logger = logging.getLogger(__name__)

# ``both`` keeps its historical meaning (CSV + JSON) so existing invocations
# behave exactly as before; ``all`` adds the HTML dashboard.
OUTPUT_FORMATS = ("csv", "json", "html", "both", "all")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo-radar",
        description=(
            "Fetch GitHub repository metadata for a CSV list of owner/repository "
            "pairs and write CSV, JSON and/or HTML reports."
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
        choices=OUTPUT_FORMATS,
        default="both",
        help=(
            "which reports to write: csv, json, html, both (csv+json) or "
            "all (csv+json+html) (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--lang",
        choices=config.SUPPORTED_LANGUAGES,
        default=config.DEFAULT_LANGUAGE,
        help="initial language of the HTML report interface (default: %(default)s)",
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
            f"number of concurrent requests, 1-{config.MAX_WORKERS} "
            f"(default: {config.DEFAULT_WORKERS}, or ${config.WORKERS_ENV_VAR})"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colours in the log output (also honoured: NO_COLOR)",
    )

    args = parser.parse_args(argv)
    if args.input_option and args.input_positional:
        parser.error("give the input CSV either positionally or via --input, not both")
    if not args.input_option and not args.input_positional:
        parser.error("an input CSV is required (positional argument or --input)")
    return args


def setup_logging(verbose: bool = False, *, color: bool | None = None) -> None:
    """Configure root logging once; colour is auto-detected unless forced."""
    use_color = supports_color() if color is None else color
    handler = logging.StreamHandler()
    handler.setFormatter(build_formatter(LOG_FORMAT, color=use_color))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=[handler],
    )


def selected_formats(output_format: str) -> tuple[str, ...]:
    """Expand the ``--output-format`` choice into concrete writer names."""
    if output_format == "all":
        return ("csv", "json", "html")
    if output_format == "both":
        return ("csv", "json")
    return (output_format,)


def write_reports(
    reports: list[RepoReport],
    output_dir: Path,
    output_format: str,
    *,
    lang: str = config.DEFAULT_LANGUAGE,
) -> list[Path]:
    """Write every requested report; returns the paths that were written."""
    writers = {
        "csv": lambda path: write_csv(reports, path),
        "json": lambda path: write_json(reports, path),
        "html": lambda path: write_html(reports, path, lang=lang),
    }
    names = {
        "csv": config.OUTPUT_CSV_NAME,
        "json": config.OUTPUT_JSON_NAME,
        "html": config.OUTPUT_HTML_NAME,
    }
    return [writers[fmt](output_dir / names[fmt]) for fmt in selected_formats(output_format)]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, color=False if args.no_color else None)

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
        max_retry_delay=config.MAX_RETRY_DELAY_SECONDS,
    )
    try:
        if settings.workers > 1:
            reports = fetch_reports_concurrent(requests_list, client, settings.workers)
        else:
            reports = fetch_reports(requests_list, client)
    finally:
        client.close()

    output_dir = Path(args.output_dir)
    try:
        written = write_reports(reports, output_dir, args.output_format, lang=args.lang)
    except OSError as exc:
        logger.error("could not write the report(s) into %s: %s", output_dir, exc)
        return 2

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
