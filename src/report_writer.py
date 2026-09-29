"""Writers that turn report rows into CSV and JSON files."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import REPORT_COLUMNS, RepoReport

logger = logging.getLogger(__name__)


def write_csv(reports: list[RepoReport], path: str | Path) -> Path:
    """Write *reports* to *path* as CSV; parent directories are created."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORT_COLUMNS))
        writer.writeheader()
        writer.writerows(report.to_dict() for report in reports)
    logger.info("CSV report written to %s (%d rows)", file_path, len(reports))
    return file_path


def write_json(reports: list[RepoReport], path: str | Path) -> Path:
    """Write *reports* to *path* as a JSON document with a small envelope."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(reports),
        "repositories": [report.to_dict() for report in reports],
    }
    file_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("JSON report written to %s (%d records)", file_path, len(reports))
    return file_path
