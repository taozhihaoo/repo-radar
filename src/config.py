"""Central configuration.

Every tunable default lives here. Numeric settings are resolved with the
precedence: CLI argument > environment variable (including a local .env
file) > built-in default. Secrets (the GitHub token) come from the
environment only and are never logged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# --- GitHub API ----------------------------------------------------------
API_BASE_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS: float = 10.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 1.0  # base delay, doubles with each attempt

# --- Concurrency -----------------------------------------------------------
# 4 is deliberately conservative: unauthenticated GitHub access allows only
# 60 requests/hour, so the rate limit -- not the thread pool -- is the real
# bottleneck. MAX_WORKERS is a hard cap; unbounded concurrency is not allowed.
DEFAULT_WORKERS = 4
MAX_WORKERS = 32

# --- Output ---------------------------------------------------------------
OUTPUT_DIR = "output"
OUTPUT_CSV_NAME = "repository_report.csv"
OUTPUT_JSON_NAME = "repository_report.json"

# --- Environment ------------------------------------------------------------
TOKEN_ENV_VAR = "GITHUB_TOKEN"
TIMEOUT_ENV_VAR = "REPO_RADAR_TIMEOUT"
MAX_RETRIES_ENV_VAR = "REPO_RADAR_MAX_RETRIES"
WORKERS_ENV_VAR = "REPO_RADAR_WORKERS"
DOTENV_PATH = ".env"


class ConfigError(Exception):
    """Raised when a setting from the environment or CLI is invalid."""


@dataclass(frozen=True)
class Settings:
    """Fully resolved run settings (after CLI > env > default precedence)."""

    timeout: float
    max_retries: int
    workers: int


def get_github_token() -> str | None:
    """Return the optional GitHub token from the environment.

    A token raises the API rate limit from 60 to 5,000 requests/hour.
    If the variable is unset (or blank), the API is used unauthenticated.
    Nothing is ever hardcoded or logged.
    """
    return (os.getenv(TOKEN_ENV_VAR) or "").strip() or None


def load_dotenv(path: str | Path = DOTENV_PATH) -> None:
    """Merge ``KEY=VALUE`` pairs from a .env file into the environment.

    Real environment variables always win: existing keys are never
    overwritten. Comments (``#``), blank lines and lines without ``=``
    are ignored; surrounding quotes are stripped from values. A missing
    file is silently skipped.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return
    for line_no, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            logger.warning("ignoring malformed line %d in %s", line_no, file_path)
            continue
        os.environ.setdefault(key, value)


def _env_float(env_var: str) -> float | None:
    raw = os.getenv(env_var)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{env_var} must be a number, got {raw!r}") from None


def _env_int(env_var: str) -> int | None:
    raw = os.getenv(env_var)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{env_var} must be a number, got {raw!r}") from None
    if value != int(value):
        raise ConfigError(f"{env_var} must be a whole number, got {raw!r}")
    return int(value)


def resolve_settings(
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    workers: int | None = None,
) -> Settings:
    """Resolve run settings with CLI > environment > default precedence.

    ``None`` arguments mean "not given on the CLI", so the corresponding
    environment variable (if set) applies; otherwise the default from this
    module is used. Invalid values raise :class:`ConfigError` regardless of
    where they came from.
    """
    resolved_timeout = timeout if timeout is not None else _env_float(TIMEOUT_ENV_VAR)
    if resolved_timeout is None:
        resolved_timeout = REQUEST_TIMEOUT_SECONDS
    if resolved_timeout <= 0:
        raise ConfigError(
            f"timeout must be positive (got {resolved_timeout}; check --timeout "
            f"and {TIMEOUT_ENV_VAR})"
        )

    resolved_retries = max_retries if max_retries is not None else _env_int(MAX_RETRIES_ENV_VAR)
    if resolved_retries is None:
        resolved_retries = MAX_RETRIES
    if resolved_retries < 1:
        raise ConfigError(
            f"max retries must be >= 1 (got {resolved_retries}; check --max-retries "
            f"and {MAX_RETRIES_ENV_VAR})"
        )

    resolved_workers = workers if workers is not None else _env_int(WORKERS_ENV_VAR)
    if resolved_workers is None:
        resolved_workers = DEFAULT_WORKERS
    if resolved_workers < 1:
        raise ConfigError(
            f"workers must be >= 1 (got {resolved_workers}; check --workers "
            f"and {WORKERS_ENV_VAR})"
        )
    if resolved_workers > MAX_WORKERS:
        raise ConfigError(
            f"workers must be <= {MAX_WORKERS} (got {resolved_workers}; check --workers "
            f"and {WORKERS_ENV_VAR})"
        )

    return Settings(
        timeout=resolved_timeout, max_retries=resolved_retries, workers=resolved_workers
    )
