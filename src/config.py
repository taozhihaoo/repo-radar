"""Central configuration.

Every tunable default lives here -- the business logic receives its
settings from the caller (main.py) instead of hardcoding values.
Secrets (the GitHub token) come from the environment only.
"""

from __future__ import annotations

import os

# --- GitHub API ----------------------------------------------------------
API_BASE_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS: float = 10.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 1.0  # base delay, doubles with each attempt

# --- Output ---------------------------------------------------------------
OUTPUT_DIR = "output"
OUTPUT_CSV_NAME = "repository_report.csv"
OUTPUT_JSON_NAME = "repository_report.json"

# --- Secrets ---------------------------------------------------------------
TOKEN_ENV_VAR = "GITHUB_TOKEN"


def get_github_token() -> str | None:
    """Return the optional GitHub token from the environment.

    A token raises the API rate limit from 60 to 5,000 requests/hour.
    If the variable is unset, the API is used unauthenticated. Nothing
    is ever hardcoded.
    """
    return os.getenv(TOKEN_ENV_VAR) or None
