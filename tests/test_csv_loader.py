"""Tests for CSV loading and input validation."""

import pytest

from src.csv_loader import CSVFormatError, load_repositories


def write(tmp_path, content, name="repos.csv"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_valid_rows(tmp_path):
    path = write(tmp_path, "owner,repository\npsf,requests\npallets,flask\n")
    pairs = [(r.owner, r.repository) for r in load_repositories(path)]
    assert pairs == [("psf", "requests"), ("pallets", "flask")]


def test_strips_whitespace_and_skips_blank_lines(tmp_path):
    path = write(tmp_path, "owner,repository\n  psf , requests \n\npallets,flask\n")
    pairs = [(r.owner, r.repository) for r in load_repositories(path)]
    assert pairs == [("psf", "requests"), ("pallets", "flask")]


def test_skips_invalid_rows_but_keeps_valid_ones(tmp_path):
    path = write(tmp_path, "owner,repository\npsf,requests\nbad owner,x\npsf,\n")
    pairs = [(r.owner, r.repository) for r in load_repositories(path)]
    assert pairs == [("psf", "requests")]


def test_removes_duplicates(tmp_path):
    path = write(tmp_path, "owner,repository\npsf,requests\npsf,requests\n")
    assert len(load_repositories(path)) == 1


def test_tolerates_utf8_bom_from_excel(tmp_path):
    path = write(tmp_path, "\ufeffowner,repository\npsf,requests\n")
    assert len(load_repositories(path)) == 1


def test_missing_required_column_raises(tmp_path):
    path = write(tmp_path, "owner,name\npsf,requests\n")
    with pytest.raises(CSVFormatError):
        load_repositories(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(CSVFormatError):
        load_repositories(tmp_path / "missing.csv")


def test_empty_file_raises(tmp_path):
    path = write(tmp_path, "")
    with pytest.raises(CSVFormatError):
        load_repositories(path)


def test_header_only_file_is_valid_but_empty(tmp_path):
    path = write(tmp_path, "owner,repository\n")
    assert load_repositories(path) == []


def test_header_names_are_matched_case_insensitively(tmp_path):
    path = write(tmp_path, " Owner , REPOSITORY \npsf,requests\n")
    assert [(r.owner, r.repository) for r in load_repositories(path)] == [("psf", "requests")]


def test_extra_columns_are_ignored(tmp_path):
    path = write(tmp_path, "owner,repository,notes\npsf,requests,keep this\n")
    assert [(r.owner, r.repository) for r in load_repositories(path)] == [("psf", "requests")]


def test_non_utf8_file_raises_format_error(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("owner,repository\npsf,répo\n".encode("latin-1"))

    with pytest.raises(CSVFormatError, match="UTF-8"):
        load_repositories(path)


def test_dot_segments_are_rejected_as_invalid_rows(tmp_path):
    path = write(tmp_path, "owner,repository\npsf,..\npsf,.\npsf,requests\n")
    assert [(r.owner, r.repository) for r in load_repositories(path)] == [("psf", "requests")]
