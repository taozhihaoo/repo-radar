"""Writers that turn report rows into CSV and JSON files.

Both writers are atomic: the file is written to a temporary sibling and then
moved into place with :func:`os.replace`. A crash, a Ctrl-C or a full disk
therefore leaves the previous report intact instead of a truncated one.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from .models import REPORT_COLUMNS, RepoReport

logger = logging.getLogger(__name__)


def write_csv(reports: list[RepoReport], path: str | Path) -> Path:
    """Write *reports* to *path* as CSV; parent directories are created."""
    file_path = Path(path)

    def render(handle: TextIO) -> None:
        writer = csv.DictWriter(handle, fieldnames=list(REPORT_COLUMNS))
        writer.writeheader()
        writer.writerows(report.to_dict() for report in reports)

    atomic_write(file_path, render)
    logger.info("CSV report written to %s (%d rows)", file_path, len(reports))
    return file_path


def write_json(reports: list[RepoReport], path: str | Path) -> Path:
    """Write *reports* to *path* as a JSON document with a small envelope."""
    file_path = Path(path)
    document = {
        "generated_at": _utc_now(),
        "total": len(reports),
        "repositories": [report.to_dict() for report in reports],
    }
    atomic_write(
        file_path,
        lambda handle: handle.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n"),
    )
    logger.info("JSON report written to %s (%d records)", file_path, len(reports))
    return file_path


def atomic_write(file_path: Path, render: Callable[[TextIO], None]) -> None:
    """Render into a temporary sibling file, then atomically replace the target."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", newline="", encoding="utf-8") as handle:
            render(handle)
        os.replace(temp_name, file_path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:  # pragma: no cover - best-effort cleanup
            logger.debug("could not remove temporary file %s", temp_name, exc_info=True)
        raise


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
