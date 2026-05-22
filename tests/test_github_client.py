from contributions_summarizer.github_client import GitHubClient, GitHubConfig


class FakeResponse:
    def __init__(self, payload: dict | list, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict | list:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.urls: list[str] = []

    def get(self, url: str, timeout: int) -> FakeResponse:
        self.urls.append(url)
        if "/search/issues" in url:
            return FakeResponse(
                {
                    "items": [
                        {
                            "number": 7,
                        }
                    ]
                }
            )
        if "/pulls/7/files" in url:
            return FakeResponse(
                [
                    {
                        "filename": "src/app.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "changes": 4,
                    }
                ]
            )
        if "/pulls/7" in url:
            return FakeResponse(
                {
                    "number": 7,
                    "title": "Improve app",
                    "html_url": "https://github.com/acme/app/pull/7",
                    "user": {"login": "octocat"},
                    "state": "closed",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                    "merged_at": "2024-01-02T00:00:00Z",
                    "body": "",
                    "labels": [],
                    "additions": 3,
                    "deletions": 1,
                    "changed_files": 1,
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")


def test_list_contribution_prs_hydrates_files() -> None:
    session = FakeSession()
    client = GitHubClient(
        GitHubConfig(token="token", api_url="https://github.example.com/api/v3"),
        session=session,  # type: ignore[arg-type]
    )

    prs = client.list_contribution_prs("acme/app", "octocat")

    assert len(prs) == 1
    assert prs[0].number == 7
    assert prs[0].files[0].filename == "src/app.py"
    assert session.urls[0].startswith("https://github.example.com/api/v3/search/issues")
