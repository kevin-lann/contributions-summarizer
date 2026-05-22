from contributions_summarizer.models import PullRequest


def test_pull_request_from_github_payload() -> None:
    pr = PullRequest.from_github(
        {
            "number": 12,
            "title": "Add billing export",
            "html_url": "https://github.com/acme/app/pull/12",
            "user": {"login": "octocat"},
            "state": "closed",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "merged_at": "2024-01-02T01:00:00Z",
            "body": "Adds CSV export support.",
            "labels": [{"name": "billing"}],
            "additions": 10,
            "deletions": 2,
            "changed_files": 1,
        },
        [
            {
                "filename": "billing/export.py",
                "status": "added",
                "additions": 10,
                "deletions": 2,
                "changes": 12,
            }
        ],
    )

    assert pr.number == 12
    assert pr.author == "octocat"
    assert pr.labels == ("billing",)
    assert pr.changed_areas() == ("billing",)
