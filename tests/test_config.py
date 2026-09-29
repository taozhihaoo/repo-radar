"""Tests for configuration resolution: CLI > environment > default precedence."""

import pytest

from src import config

# --- get_github_token -------------------------------------------------------

def test_token_read_from_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    assert config.get_github_token() == "tok-123"


def test_token_absent_returns_none(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert config.get_github_token() is None


def test_empty_token_treated_as_absent(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    assert config.get_github_token() is None


# --- resolve_settings: precedence --------------------------------------------

def test_defaults_used_when_nothing_set(monkeypatch):
    monkeypatch.delenv(config.TIMEOUT_ENV_VAR, raising=False)
    monkeypatch.delenv(config.MAX_RETRIES_ENV_VAR, raising=False)
    monkeypatch.delenv(config.WORKERS_ENV_VAR, raising=False)

    settings = config.resolve_settings()

    assert settings == config.Settings(
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        max_retries=config.MAX_RETRIES,
        workers=config.DEFAULT_WORKERS,
    )


def test_cli_values_win_over_everything(monkeypatch):
    monkeypatch.setenv(config.TIMEOUT_ENV_VAR, "99")
    monkeypatch.setenv(config.MAX_RETRIES_ENV_VAR, "9")
    monkeypatch.setenv(config.WORKERS_ENV_VAR, "8")

    settings = config.resolve_settings(timeout=1.5, max_retries=2, workers=2)

    assert settings == config.Settings(timeout=1.5, max_retries=2, workers=2)


def test_environment_wins_over_default(monkeypatch):
    monkeypatch.setenv(config.TIMEOUT_ENV_VAR, "4.5")
    monkeypatch.setenv(config.MAX_RETRIES_ENV_VAR, "7")
    monkeypatch.setenv(config.WORKERS_ENV_VAR, "6")

    settings = config.resolve_settings()

    assert settings == config.Settings(timeout=4.5, max_retries=7, workers=6)


def test_blank_environment_values_are_ignored(monkeypatch):
    monkeypatch.setenv(config.TIMEOUT_ENV_VAR, "   ")
    assert config.resolve_settings().timeout == config.REQUEST_TIMEOUT_SECONDS


# --- resolve_settings: validation ---------------------------------------------

def test_non_positive_timeout_rejected_from_cli():
    with pytest.raises(config.ConfigError, match="timeout"):
        config.resolve_settings(timeout=0)


def test_non_numeric_timeout_env_rejected(monkeypatch):
    monkeypatch.setenv(config.TIMEOUT_ENV_VAR, "ten")
    with pytest.raises(config.ConfigError, match="REPO_RADAR_TIMEOUT"):
        config.resolve_settings()


def test_zero_max_retries_rejected(monkeypatch):
    monkeypatch.setenv(config.MAX_RETRIES_ENV_VAR, "0")
    with pytest.raises(config.ConfigError, match="REPO_RADAR_MAX_RETRIES"):
        config.resolve_settings()


def test_fractional_max_retries_env_rejected(monkeypatch):
    monkeypatch.setenv(config.MAX_RETRIES_ENV_VAR, "2.5")
    with pytest.raises(config.ConfigError, match="whole number"):
        config.resolve_settings()


def test_workers_below_one_rejected():
    with pytest.raises(config.ConfigError, match="workers"):
        config.resolve_settings(workers=0)


def test_workers_above_hard_cap_rejected():
    with pytest.raises(config.ConfigError, match=f"must be <= {config.MAX_WORKERS}"):
        config.resolve_settings(workers=config.MAX_WORKERS + 1)


def test_workers_env_above_hard_cap_rejected(monkeypatch):
    monkeypatch.setenv(config.WORKERS_ENV_VAR, str(config.MAX_WORKERS + 5))
    with pytest.raises(config.ConfigError, match="REPO_RADAR_WORKERS"):
        config.resolve_settings()


# --- load_dotenv ---------------------------------------------------------------

def test_load_dotenv_sets_missing_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "REPO_RADAR_TIMEOUT=3.5\nREPO_RADAR_WORKERS=2\n", encoding="utf-8"
    )

    config.load_dotenv()

    assert config.resolve_settings(workers=None).timeout == 3.5
    monkeypatch.delenv(config.TIMEOUT_ENV_VAR)
    monkeypatch.delenv(config.WORKERS_ENV_VAR)


def test_load_dotenv_never_overrides_real_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO_RADAR_TIMEOUT", "9")
    (tmp_path / ".env").write_text("REPO_RADAR_TIMEOUT=1\n", encoding="utf-8")

    config.load_dotenv()

    assert config.resolve_settings().timeout == 9


def test_load_dotenv_ignores_comments_blank_and_malformed_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPO_RADAR_MAX_RETRIES", raising=False)
    (tmp_path / ".env").write_text(
        "# comment\n\nNO_EQUALS_SIGN\nREPO_RADAR_MAX_RETRIES=5\n", encoding="utf-8"
    )

    config.load_dotenv()

    assert config.resolve_settings().max_retries == 5
    monkeypatch.delenv("REPO_RADAR_MAX_RETRIES")


def test_load_dotenv_strips_quotes_and_whitespace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPO_RADAR_WORKERS", raising=False)
    (tmp_path / ".env").write_text('  REPO_RADAR_WORKERS = "3"  \n', encoding="utf-8")

    config.load_dotenv()

    assert config.resolve_settings().workers == 3
    monkeypatch.delenv("REPO_RADAR_WORKERS")


def test_load_dotenv_missing_file_is_a_no_op(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    config.load_dotenv()  # must not raise
    assert not any(".env" in record.message for record in caplog.records)
