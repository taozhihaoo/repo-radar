"""Data models for input requests and report rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

# GitHub owner (user/org) names: alphanumeric, single hyphens inside,
# 1-39 characters. Repository names additionally allow dots/underscores,
# up to 100 characters.
_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

# Fetch states used in the reports.
STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ERROR = "error"

# Stable column order shared by the CSV and JSON reports.
REPORT_COLUMNS: tuple[str, ...] = (
    "owner",
    "repository",
    "full_name",
    "status",
    "url",
    "description",
    "language",
    "stars",
    "forks",
    "open_issues",
    "archived",
    "default_branch",
    "license",
    "created_at",
    "updated_at",
    "pushed_at",
    "fetched_at",
    "error_message",
)


class ValidationError(ValueError):
    """Raised when an input value does not pass validation."""


@dataclass(frozen=True)
class RepoRequest:
    """One owner/repository pair to look up."""

    owner: str
    repository: str

    def __post_init__(self) -> None:
        if not _OWNER_PATTERN.match(self.owner):
            raise ValidationError(f"invalid GitHub owner name: {self.owner!r}")
        if not _REPOSITORY_PATTERN.match(self.repository):
            raise ValidationError(f"invalid GitHub repository name: {self.repository!r}")

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repository}"


@dataclass
class RepoReport:
    """Metadata for one repository, or the error that replaced it."""

    owner: str
    repository: str
    status: str
    error_message: str = ""
    url: str = ""
    description: str = ""
    language: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    archived: bool = False
    default_branch: str = ""
    license: str = ""
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    fetched_at: str = ""

    @classmethod
    def success(cls, request: RepoRequest, payload: dict) -> RepoReport:
        """Build a report row from a GitHub ``GET /repos/{owner}/{repo}`` payload."""
        license_info = payload.get("license") or {}
        return cls(
            owner=request.owner,
            repository=request.repository,
            status=STATUS_OK,
            url=payload.get("html_url", ""),
            description=payload.get("description") or "",
            language=payload.get("language") or "",
            stars=int(payload.get("stargazers_count") or 0),
            forks=int(payload.get("forks_count") or 0),
            open_issues=int(payload.get("open_issues_count") or 0),
            archived=bool(payload.get("archived")),
            default_branch=payload.get("default_branch") or "",
            license=license_info.get("spdx_id") or "",
            created_at=payload.get("created_at") or "",
            updated_at=payload.get("updated_at") or "",
            pushed_at=payload.get("pushed_at") or "",
            fetched_at=_utc_now(),
        )

    @classmethod
    def failure(cls, request: RepoRequest, status: str, message: str) -> RepoReport:
        """Build a report row for a repository that could not be fetched."""
        return cls(
            owner=request.owner,
            repository=request.repository,
            status=status,
            error_message=message,
            fetched_at=_utc_now(),
        )

    def to_dict(self) -> dict[str, object]:
        """Flatten to a dict following the shared REPORT_COLUMNS order."""
        return {
            "owner": self.owner,
            "repository": self.repository,
            "full_name": f"{self.owner}/{self.repository}",
            "status": self.status,
            "url": self.url,
            "description": self.description,
            "language": self.language,
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "archived": self.archived,
            "default_branch": self.default_branch,
            "license": self.license,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
            "fetched_at": self.fetched_at,
            "error_message": self.error_message,
        }


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
