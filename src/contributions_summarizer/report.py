from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from contributions_summarizer.models import (
    ClusterSummary,
    ContributionCluster,
    to_jsonable,
)


@dataclass(frozen=True)
class ReportContext:
    repo: str
    user: str
    since: date | None = None
    until: date | None = None


def render_markdown(
    context: ReportContext,
    clusters: list[ContributionCluster],
    summaries: list[ClusterSummary],
) -> str:
    summary_by_cluster = {summary.cluster_id: summary for summary in summaries}
    lines = [
        f"# Contribution Summary for `{context.user}`",
        "",
        f"Repository: `{context.repo}`",
        f"Date range: {format_date_range(context)}",
        f"Pull requests: {sum(len(cluster.prs) for cluster in clusters)}",
        "",
    ]

    for cluster in clusters:
        summary = summary_by_cluster.get(cluster.id)
        headline = summary.headline if summary else cluster.title
        lines.extend(
            [
                f"## {headline}",
                "",
                f"PRs: {len(cluster.prs)} | Additions: {cluster.additions} | Deletions: {cluster.deletions}",
                f"Areas: {', '.join(cluster.changed_areas()) or 'n/a'}",
                "",
            ]
        )
        if summary:
            lines.extend(
                [
                    summary.summary.strip(),
                    "",
                    f"Impact: {summary.impact.strip()}",
                    "",
                ]
            )
        else:
            lines.extend([fallback_summary(cluster), ""])

        lines.append("Representative PRs:")
        for pr in cluster.prs:
            merged = pr.merged_at.date().isoformat() if pr.merged_at else "not merged"
            lines.append(f"- #{pr.number} [{pr.title}]({pr.url}) ({merged})")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_json(
    context: ReportContext,
    clusters: list[ContributionCluster],
    summaries: list[ClusterSummary],
) -> str:
    payload = {
        "repo": context.repo,
        "user": context.user,
        "since": context.since.isoformat() if context.since else None,
        "until": context.until.isoformat() if context.until else None,
        "clusters": to_jsonable(clusters),
        "summaries": to_jsonable(summaries),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def format_date_range(context: ReportContext) -> str:
    since = context.since.isoformat() if context.since else "beginning"
    until = context.until.isoformat() if context.until else "now"
    return f"{since} to {until}"


def fallback_summary(cluster: ContributionCluster) -> str:
    areas = ", ".join(cluster.changed_areas()) or "the repository"
    return f"Worked on {areas} across {len(cluster.prs)} pull request(s)."
