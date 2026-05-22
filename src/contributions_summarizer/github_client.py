from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

import requests

from contributions_summarizer.models import PullRequest


DEFAULT_GITHUB_API_URL = "https://api.github.com"


class GitHubClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    api_url: str = DEFAULT_GITHUB_API_URL

    @classmethod
    def from_env(cls) -> "GitHubConfig":
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise GitHubClientError("GITHUB_TOKEN is required.")
        return cls(
            token=token,
            api_url=os.environ.get("GITHUB_API_URL", DEFAULT_GITHUB_API_URL).rstrip("/"),
        )


class GitHubClient:
    def __init__(
        self,
        config: GitHubConfig,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {config.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def list_contribution_prs(
        self,
        repo: str,
        user: str,
        since: date | None = None,
        until: date | None = None,
        include_open: bool = False,
        max_prs: int | None = None,
    ) -> list[PullRequest]:
        self._validate_repo(repo)
        issues = self._search_pr_issues(
            repo=repo,
            user=user,
            since=since,
            until=until,
            include_open=include_open,
            max_prs=max_prs,
        )
        pull_requests: list[PullRequest] = []
        for issue in issues:
            number = int(issue["number"])
            pull_payload = self._get_json(f"/repos/{repo}/pulls/{number}")
            file_payloads = self._get_paginated(f"/repos/{repo}/pulls/{number}/files")
            pull_requests.append(PullRequest.from_github(pull_payload, file_payloads))
        return sorted(pull_requests, key=lambda pr: pr.sort_date)

    def _search_pr_issues(
        self,
        repo: str,
        user: str,
        since: date | None,
        until: date | None,
        include_open: bool,
        max_prs: int | None,
    ) -> list[dict]:
        query_parts = [f"repo:{repo}", "type:pr", f"author:{user}"]
        if not include_open:
            query_parts.append("is:merged")
        if since and until:
            query_parts.append(f"created:{since.isoformat()}..{until.isoformat()}")
        elif since:
            query_parts.append(f"created:>={since.isoformat()}")
        elif until:
            query_parts.append(f"created:<={until.isoformat()}")

        query = "+".join(quote(part, safe=":>=.") for part in query_parts)
        items: list[dict] = []
        page = 1
        while True:
            per_page = min(100, max_prs - len(items)) if max_prs else 100
            payload = self._get_json(
                f"/search/issues?q={query}&sort=created&order=asc&per_page={per_page}&page={page}"
            )
            batch = payload.get("items", [])
            items.extend(batch)
            if max_prs and len(items) >= max_prs:
                return items[:max_prs]
            if len(batch) < per_page:
                return items
            page += 1

    def _get_paginated(self, path: str) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            batch = self._get_json(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise GitHubClientError(f"Expected a list response from {path}.")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def _get_json(self, path: str) -> dict | list:
        url = f"{self.config.api_url}{path}"
        response = self.session.get(url, timeout=30)
        if response.status_code >= 400:
            message = self._error_message(response)
            raise GitHubClientError(f"GitHub API request failed: {message}")
        return response.json()

    @staticmethod
    def _validate_repo(repo: str) -> None:
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise GitHubClientError("Repository must use the owner/repo format.")

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"{response.status_code} {response.text}"
        message = payload.get("message", response.text)
        return f"{response.status_code} {message}"
