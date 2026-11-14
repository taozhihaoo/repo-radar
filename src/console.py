"""Terminal presentation helpers for the CLI.

Colour is a nice-to-have, never a requirement: it is only enabled when the
log stream is a real terminal, the ``NO_COLOR`` convention is not set and the
terminal is not dumb. Redirected output, CI logs and piped runs therefore stay
plain text, which keeps log assertions and log shippers simple.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import IO

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

LEVEL_COLORS = {
    "DEBUG": DIM,
    "INFO": "\x1b[36m",  # cyan
    "WARNING": "\x1b[33m",  # yellow
    "ERROR": "\x1b[31m",  # red
    "CRITICAL": "\x1b[1;31m",  # bold red
}

# Level names are padded by the formatter itself so ANSI escape codes do not
# count towards the column width and the log stays aligned.
LEVEL_WIDTH = 8

TRUTHY = {"1", "true", "yes", "on"}


def _windows_enable_vt() -> bool:
    """Best-effort enable of ANSI processing on legacy Windows consoles."""
    if os.name != "nt":  # pragma: no cover - non-Windows
        return True
    try:  # pragma: no cover - Windows only
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-12)  # STDERR
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_virtual_terminal = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal))
    except Exception:  # pragma: no cover - defensive
        return False


def supports_color(stream: IO[str] | None = None) -> bool:
    """Whether ANSI colour should be written to *stream* (default: stderr)."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR", "").strip().lower() in TRUTHY:
        return True
    if os.environ.get("TERM", "").lower() in {"dumb", "unknown"}:
        return False
    target = stream if stream is not None else sys.stderr
    if not hasattr(target, "isatty") or not target.isatty():
        return False
    return _windows_enable_vt()


class ColorFormatter(logging.Formatter):
    """Formatter that colours and pads the level name, leaving the rest alone.

    The record is mutated only for the duration of the call, so other
    handlers (a file handler, a test capture handler) still see the plain
    level name.
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        color = LEVEL_COLORS.get(original)
        if color is None:
            return super().format(record)
        record.levelname = f"{color}{original:<{LEVEL_WIDTH}}{RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def build_formatter(fmt: str, *, color: bool) -> logging.Formatter:
    """Return a colouring or plain formatter for *fmt*.

    Colour mode pads the level name itself, so callers must not add a width
    specifier to ``%(levelname)s``.
    """
    return ColorFormatter(fmt) if color else logging.Formatter(fmt)


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
