"""Self-contained HTML report: one file, no network, no build step.

The template in ``templates/dashboard.html`` carries the markup, styling and
the rendering script; this module only injects the report data as JSON and
writes the file atomically. Everything the browser needs is inlined, so the
report can be opened from a file share, attached to a ticket or archived
without a web server.

Security notes:
- the payload is embedded as JSON with ``</`` escaped, so a repository
  description containing ``</script>`` cannot break out of the script tag;
- every value is rendered through ``textContent``-style escaping in the
  template, so remote text cannot inject markup.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .config import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from .models import RepoReport
from .report_writer import atomic_write

logger = logging.getLogger(__name__)

TEMPLATE_PATH = "templates/dashboard.html"
DATA_PLACEHOLDER = "__REPORT_DATA__"


class TemplateError(RuntimeError):
    """The bundled HTML template could not be read."""


def render_html(reports: list[RepoReport], *, lang: str = DEFAULT_LANGUAGE) -> str:
    """Return the full HTML document for *reports* as a string."""
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language {lang!r}; expected one of {SUPPORTED_LANGUAGES}")

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(reports),
        "lang": lang,
        "repositories": [report.to_dict() for report in reports],
    }
    document = _load_template().replace(DATA_PLACEHOLDER, _embed_json(payload))
    return document


def write_html(
    reports: list[RepoReport], path: str | Path, *, lang: str = DEFAULT_LANGUAGE
) -> Path:
    """Write the HTML report to *path*; parent directories are created."""
    file_path = Path(path)
    html = render_html(reports, lang=lang)
    atomic_write(file_path, lambda handle: handle.write(html))
    logger.info("HTML report written to %s (%d rows, lang=%s)", file_path, len(reports), lang)
    return file_path


def _load_template() -> str:
    """Read the bundled template, from the installed package or the source tree."""
    try:
        return resources.files(__package__).joinpath(TEMPLATE_PATH).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, AttributeError) as exc:  # pragma: no cover
        raise TemplateError(f"bundled HTML template {TEMPLATE_PATH} is missing") from exc


def _embed_json(payload: dict) -> str:
    """Serialise *payload* for inline use inside a ``<script>`` element.

    ``</`` is rewritten to ``<\\/`` (still valid JSON, inert for the HTML
    parser) and the two Unicode line separators are escaped, so no repo name
    or description can terminate the script block early.
    """
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
