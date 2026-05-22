from datetime import datetime, timezone

from contributions_summarizer.cluster import cluster_pull_requests
from contributions_summarizer.models import PullRequest, PullRequestFile


def test_cluster_pull_requests_groups_related_work() -> None:
    auth_one = make_pr(
        1,
        "Add login callback",
        "auth/oauth.py",
        labels=("auth",),
    )
    auth_two = make_pr(
        2,
        "Fix oauth token refresh",
        "auth/tokens.py",
        labels=("auth",),
    )
    billing = make_pr(
        3,
        "Add invoice csv export",
        "billing/export.py",
        labels=("billing",),
    )

    clusters = cluster_pull_requests([auth_one, billing, auth_two])

    assert len(clusters) == 2
    assert [pr.number for pr in clusters[0].prs] == [1, 2]
    assert [pr.number for pr in clusters[1].prs] == [3]


def make_pr(
    number: int,
    title: str,
    filename: str,
    labels: tuple[str, ...],
) -> PullRequest:
    timestamp = datetime(2024, 1, number, tzinfo=timezone.utc)
    return PullRequest(
        number=number,
        title=title,
        url=f"https://github.com/acme/app/pull/{number}",
        author="octocat",
        state="closed",
        created_at=timestamp,
        updated_at=timestamp,
        merged_at=timestamp,
        body="",
        labels=labels,
        files=(
            PullRequestFile(
                filename=filename,
                status="modified",
                additions=5,
                deletions=1,
                changes=6,
            ),
        ),
        additions=5,
        deletions=1,
        changed_files=1,
    )
