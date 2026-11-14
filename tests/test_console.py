"""Tests for terminal colour handling (colour never breaks non-TTY output)."""

import logging

from src.console import LOG_FORMAT, ColorFormatter, build_formatter, supports_color


class FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def clean_env(monkeypatch):
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(name, raising=False)


def test_no_color_env_disables_colour(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    assert supports_color(FakeStream(tty=True)) is False


def test_force_color_env_enables_colour_even_without_tty(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert supports_color(FakeStream(tty=False)) is True


def test_pipe_is_not_coloured(monkeypatch):
    clean_env(monkeypatch)
    assert supports_color(FakeStream(tty=False)) is False


def test_dumb_terminal_is_not_coloured(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    assert supports_color(FakeStream(tty=True)) is False


def make_record(level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("src.demo", level, __file__, 10, "hello %s", ("world",), None)


def test_colour_formatter_colours_and_pads_the_level_name():
    text = ColorFormatter(LOG_FORMAT).format(make_record())

    assert "\x1b[36mINFO    \x1b[0m" in text  # colour + padding to 8 columns
    assert text.endswith("src.demo: hello world")


def test_colour_formatter_restores_the_record():
    record = make_record(logging.ERROR)
    ColorFormatter(LOG_FORMAT).format(record)
    assert record.levelname == "ERROR"


def test_plain_formatter_emits_no_escape_codes():
    text = build_formatter(LOG_FORMAT, color=False).format(make_record())
    assert "\x1b[" not in text
    assert "INFO src.demo: hello world" in text


def test_unknown_level_is_left_untouched():
    text = ColorFormatter(LOG_FORMAT).format(make_record(level=25))
    assert "\x1b[" not in text
