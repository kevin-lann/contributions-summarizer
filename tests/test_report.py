from datetime import date

from contributions_summarizer.models import ClusterSummary, ContributionCluster
from contributions_summarizer.report import ReportContext, render_json, render_markdown
from tests.test_cluster import make_pr


def test_render_markdown_includes_summary_and_prs() -> None:
    cluster = ContributionCluster(
        id="cluster-1",
        title="Auth",
        prs=(make_pr(1, "Add login callback", "auth/oauth.py", ("auth",)),),
    )
    summary = ClusterSummary(
        cluster_id="cluster-1",
        headline="Auth improvements",
        summary="Improved login.",
        impact="Reduced sign-in failures.",
    )

    markdown = render_markdown(
        ReportContext("acme/app", "octocat", date(2024, 1, 1), None),
        [cluster],
        [summary],
    )

    assert "# Contribution Summary for `octocat`" in markdown
    assert "## Auth improvements" in markdown
    assert "#1 [Add login callback]" in markdown


def test_render_json_includes_clusters() -> None:
    cluster = ContributionCluster(
        id="cluster-1",
        title="Auth",
        prs=(make_pr(1, "Add login callback", "auth/oauth.py", ("auth",)),),
    )

    payload = render_json(ReportContext("acme/app", "octocat"), [cluster], [])

    assert '"repo": "acme/app"' in payload
    assert '"id": "cluster-1"' in payload
