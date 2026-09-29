"""Tests for the CLI surface: argument parsing, end-to-end runs with a fake
client, output-format handling, and the packaged console entry point."""

import csv
import importlib.metadata
import json
import logging

import pytest

import src.main as main_module
from src.main import main, parse_args


def write_input_csv(tmp_path, content="owner,repository\npsf,requests\npallets,flask\n"):
    path = tmp_path / "repos.csv"
    path.write_text(content, encoding="utf-8")
    return path


class FakeClient:
    """Stand-in for GitHubClient: canned payloads, thread-safe call log."""

    def __init__(self, behaviour: dict, **kwargs) -> None:
        assert "base_url" in kwargs and "timeout" in kwargs  # receives run settings
        self._behaviour = behaviour
        self.kwargs = kwargs
        self.calls: list[str] = []

    def get_repository(self, owner: str, repository: str) -> dict:
        full_name = f"{owner}/{repository}"
        self.calls.append(full_name)
        result = self._behaviour[full_name]
        if isinstance(result, Exception):
            raise result
        return result


def install_fake_client(monkeypatch, behaviour):
    """Route main()'s GitHubClient construction to a fake (no network)."""
    monkeypatch.setattr(
        main_module, "GitHubClient", lambda **kwargs: FakeClient(behaviour, **kwargs)
    )


# --- parse_args -------------------------------------------------------------------

def test_positional_input_and_defaults():
    args = parse_args(["repos.csv"])
    assert args.input_positional == "repos.csv"
    assert args.input_option is None
    assert args.output_format == "both"
    assert args.output_dir == "output"
    assert args.timeout is None
    assert args.max_retries is None
    assert args.workers is None
    assert args.verbose is False


def test_input_flag_is_accepted_alone():
    assert parse_args(["--input", "repos.csv"]).input_option == "repos.csv"


def test_positional_and_input_flag_conflict():
    with pytest.raises(SystemExit, match="2"):
        parse_args(["repos.csv", "--input", "other.csv"])


def test_missing_input_is_an_error():
    with pytest.raises(SystemExit, match="2"):
        parse_args([])


def test_output_format_rejects_unknown_values():
    with pytest.raises(SystemExit, match="2"):
        parse_args(["repos.csv", "--output-format", "xml"])


def test_numeric_options_are_parsed():
    args = parse_args(
        ["repos.csv", "--workers", "8", "--timeout", "2.5", "--max-retries", "5"]
    )
    assert (args.workers, args.timeout, args.max_retries) == (8, 2.5, 5)


def test_verbose_flag():
    assert parse_args(["repos.csv", "-v"]).verbose is True


def test_help_mentions_repo_radar_and_workers(capsys):
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["--help"])
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "repo-radar" in output
    assert "--workers" in output
    assert "--output-format" in output


# --- end-to-end main() with a fake client -------------------------------------------

def test_main_happy_path_writes_both_reports(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path)
    install_fake_client(
        monkeypatch,
        {
            "psf/requests": {"stargazers_count": 1},
            "pallets/flask": {"stargazers_count": 2},
        },
    )
    output_dir = tmp_path / "reports"

    exit_code = main([str(input_csv), "--output-dir", str(output_dir), "--workers", "2"])

    assert exit_code == 0
    rows = list(csv.DictReader((output_dir / "repository_report.csv").open(encoding="utf-8")))
    assert [row["full_name"] for row in rows] == ["psf/requests", "pallets/flask"]
    data = json.loads((output_dir / "repository_report.json").read_text(encoding="utf-8"))
    assert data["total"] == 2


def test_main_output_format_csv_writes_only_csv(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path)
    install_fake_client(monkeypatch, {"psf/requests": {"stargazers_count": 1}})
    output_dir = tmp_path / "reports"

    exit_code = main(
        [str(input_csv), "--output-dir", str(output_dir), "--output-format", "csv"]
    )

    assert exit_code == 0
    assert (output_dir / "repository_report.csv").exists()
    assert not (output_dir / "repository_report.json").exists()


def test_main_output_format_json_writes_only_json(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path)
    install_fake_client(monkeypatch, {"psf/requests": {"stargazers_count": 1}})
    output_dir = tmp_path / "reports"

    exit_code = main(
        [str(input_csv), "--output-dir", str(output_dir), "--output-format", "json"]
    )

    assert exit_code == 0
    assert not (output_dir / "repository_report.csv").exists()
    assert (output_dir / "repository_report.json").exists()


def test_main_concurrent_default_workers_keep_order(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path)
    install_fake_client(
        monkeypatch,
        {
            "psf/requests": {"stargazers_count": 1},
            "pallets/flask": {"stargazers_count": 2},
        },
    )
    output_dir = tmp_path / "reports"

    exit_code = main([str(input_csv), "--output-dir", str(output_dir)])  # default workers=4

    assert exit_code == 0
    rows = list(csv.DictReader((output_dir / "repository_report.csv").open(encoding="utf-8")))
    assert [row["full_name"] for row in rows] == ["psf/requests", "pallets/flask"]


def test_main_all_failures_exit_code_1(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path, "owner,repository\nnope,missing\n")
    install_fake_client(monkeypatch, {"nope/missing": Exception("repository not found (HTTP 404)")})

    exit_code = main(
        [str(input_csv), "--output-dir", str(tmp_path / "out"), "--workers", "1"]
    )

    assert exit_code == 1


def test_main_invalid_input_exit_code_2(tmp_path, monkeypatch):
    exit_code = main([str(tmp_path / "missing.csv")])
    assert exit_code == 2


def test_main_config_error_exit_code_2(tmp_path, monkeypatch):
    input_csv = write_input_csv(tmp_path)
    install_fake_client(monkeypatch, {"psf/requests": {"stargazers_count": 1}})

    exit_code = main([str(input_csv), "--workers", "999"])

    assert exit_code == 2


def test_main_never_logs_the_token(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    input_csv = write_input_csv(tmp_path)
    install_fake_client(monkeypatch, {"psf/requests": {"stargazers_count": 1}})
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret-token-value")

    main([str(input_csv), "--output-dir", str(tmp_path / "out"), "--workers", "1"])

    assert "super-secret-token-value" not in caplog.text
    assert "GitHub token: provided" in caplog.text


def test_main_reports_settings_and_summary(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    input_csv = write_input_csv(tmp_path, "owner,repository\npsf,requests\n")
    install_fake_client(monkeypatch, {"psf/requests": {"stargazers_count": 1}})

    main(
        [
            str(input_csv),
            "--output-dir",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--timeout",
            "3",
            "--max-retries",
            "2",
        ]
    )

    assert "settings: workers=1 timeout=3.0s max_retries=2" in caplog.text
    assert "done: 1/1 fetched" in caplog.text


# --- packaging ----------------------------------------------------------------------

def test_console_entry_point_is_declared():
    match = next(
        (e for e in importlib.metadata.entry_points(group="console_scripts")
         if e.name == "repo-radar"),
        None,
    )
    if match is None:
        pytest.skip("repo-radar is not installed in this environment (pip install -e .)")
    assert match.value == "src.main:main"
