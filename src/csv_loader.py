"""Load and validate the input CSV of GitHub owner/repository pairs."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .models import RepoRequest, ValidationError

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("owner", "repository")


class CSVFormatError(Exception):
    """The input CSV is structurally invalid (missing, unreadable, wrong columns)."""


def load_repositories(path: str | Path) -> list[RepoRequest]:
    """Read owner/repository pairs from *path*.

    A structurally broken file raises :class:`CSVFormatError`. Individual
    invalid rows are logged and skipped, so one bad row never aborts the
    whole run; duplicates are removed.

    The file is read as ``utf-8-sig`` so CSVs exported from Excel (with a
    BOM) are handled transparently.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise CSVFormatError(f"input CSV not found: {file_path}")

    repositories: list[RepoRequest] = []
    seen: set[str] = set()
    skipped = 0

    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CSVFormatError(f"input CSV is empty: {file_path}")
        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise CSVFormatError(
                f"input CSV is missing required column(s): {', '.join(missing)}"
            )

        for line_no, row in enumerate(reader, start=2):  # line 1 is the header
            owner = (row.get("owner") or "").strip()
            repository = (row.get("repository") or "").strip()
            if not owner and not repository:
                continue  # tolerate blank lines
            try:
                request = RepoRequest(owner=owner, repository=repository)
            except ValidationError as exc:
                skipped += 1
                logger.warning("skipping line %d: %s", line_no, exc)
                continue
            if request.full_name in seen:
                skipped += 1
                logger.warning("skipping line %d: duplicate %s", line_no, request.full_name)
                continue
            seen.add(request.full_name)
            repositories.append(request)

    logger.info(
        "loaded %d valid repositories (%d skipped) from %s",
        len(repositories),
        skipped,
        file_path,
    )
    return repositories
