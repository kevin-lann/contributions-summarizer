from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PullRequestFile:
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str | None = None

    @classmethod
    def from_github(cls, payload: dict[str, Any]) -> "PullRequestFile":
        return cls(
            filename=str(payload.get("filename", "")),
            status=str(payload.get("status", "")),
            additions=int(payload.get("additions", 0)),
            deletions=int(payload.get("deletions", 0)),
            changes=int(payload.get("changes", 0)),
            patch=payload.get("patch"),
        )

    def top_level_area(self) -> str:
        return self.filename.split("/", 1)[0] if "/" in self.filename else self.filename


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    url: str
    author: str
    state: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    body: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    files: tuple[PullRequestFile, ...] = field(default_factory=tuple)
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0

    @classmethod
    def from_github(
        cls,
        pull_payload: dict[str, Any],
        file_payloads: list[dict[str, Any]],
    ) -> "PullRequest":
        user = pull_payload.get("user") or {}
        return cls(
            number=int(pull_payload["number"]),
            title=str(pull_payload.get("title", "")),
            url=str(pull_payload.get("html_url", "")),
            author=str(user.get("login", "")),
            state=str(pull_payload.get("state", "")),
            created_at=parse_github_datetime(str(pull_payload["created_at"])),
            updated_at=parse_github_datetime(str(pull_payload["updated_at"])),
            merged_at=parse_optional_github_datetime(pull_payload.get("merged_at")),
            body=str(pull_payload.get("body") or ""),
            labels=tuple(
                str(label.get("name", ""))
                for label in pull_payload.get("labels", [])
                if label.get("name")
            ),
            files=tuple(PullRequestFile.from_github(file) for file in file_payloads),
            additions=int(pull_payload.get("additions", 0)),
            deletions=int(pull_payload.get("deletions", 0)),
            changed_files=int(pull_payload.get("changed_files", len(file_payloads))),
        )

    @property
    def sort_date(self) -> datetime:
        return self.merged_at or self.updated_at or self.created_at

    def changed_areas(self) -> tuple[str, ...]:
        return tuple(sorted({file.top_level_area() for file in self.files if file.filename}))


@dataclass(frozen=True)
class ContributionCluster:
    id: str
    title: str
    prs: tuple[PullRequest, ...]
    signals: tuple[str, ...] = field(default_factory=tuple)

    @property
    def additions(self) -> int:
        return sum(pr.additions for pr in self.prs)

    @property
    def deletions(self) -> int:
        return sum(pr.deletions for pr in self.prs)

    def changed_areas(self) -> tuple[str, ...]:
        return tuple(sorted({area for pr in self.prs for area in pr.changed_areas()}))


@dataclass(frozen=True)
class ClusterSummary:
    cluster_id: str
    headline: str
    summary: str
    impact: str
    resume_bullets: tuple[str, ...] = field(default_factory=tuple)


def parse_github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_optional_github_datetime(value: str | None) -> datetime | None:
    return parse_github_datetime(value) if value else None


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value
