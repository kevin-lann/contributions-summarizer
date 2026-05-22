from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from contributions_summarizer.cluster import cluster_pull_requests
from contributions_summarizer.gemini import (
    ContributionSummarizer,
    GeminiConfig,
    GeminiTextGenerator,
)
from contributions_summarizer.github_client import GitHubClient, GitHubConfig
from contributions_summarizer.models import ClusterSummary, ContributionCluster
from contributions_summarizer.report import ReportContext, render_json, render_markdown


def main(argv: list[str] | None = None) -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging()

    try:
        since = parse_date(args.since, "--since")
        until = parse_date(args.until, "--until")
        client = GitHubClient(GitHubConfig.from_env())
        pull_requests = client.list_contribution_prs(
            repo=args.repo,
            user=args.user,
            since=since,
            until=until,
            include_open=args.include_open,
            max_prs=args.max_prs,
        )
        clusters = cluster_pull_requests(
            pull_requests,
            similarity_threshold=args.similarity_threshold,
        )
        summaries = summarize(clusters, no_ai=args.no_ai, model=args.model)
        context = ReportContext(repo=args.repo, user=args.user, since=since, until=until)
        markdown = render_markdown(context, clusters, summaries)
        write_output(args.out, markdown)
        if args.json_out:
            write_output(args.json_out, render_json(context, clusters, summaries))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contrib-summary",
        description="Summarize a GitHub user's pull request contributions to a repository.",
    )
    parser.add_argument("repo", help="Repository in owner/repo format.")
    parser.add_argument("--user", required=True, help="GitHub username to summarize.")
    parser.add_argument("--since", help="Only include PRs created on or after YYYY-MM-DD.")
    parser.add_argument("--until", help="Only include PRs created on or before YYYY-MM-DD.")
    parser.add_argument("--out", default="-", help="Markdown output path, or '-' for stdout.")
    parser.add_argument("--json-out", help="Optional JSON output path.")
    parser.add_argument(
        "--include-open",
        action="store_true",
        help="Include open and unmerged PRs. By default only merged PRs are included.",
    )
    parser.add_argument("--max-prs", type=int, help="Maximum PRs to fetch.")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.32,
        help="Similarity threshold for deterministic clustering.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Vertex AI Gemini model to use for summaries.",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip Gemini calls and render deterministic fallback summaries.",
    )
    return parser


def summarize(
    clusters: list[ContributionCluster],
    no_ai: bool,
    model: str,
) -> list[ClusterSummary]:
    if no_ai:
        return []
    generator = GeminiTextGenerator(GeminiConfig.from_env(model=model))
    return ContributionSummarizer(generator).summarize(clusters)


def parse_date(value: str | None, flag: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{flag} must use YYYY-MM-DD.") from exc


def write_output(path: str, content: str) -> None:
    if path == "-":
        print(content, end="")
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def load_environment() -> None:
    for env_path in env_file_candidates():
        if env_path.exists():
            load_env_file(env_path)


def env_file_candidates() -> tuple[Path, ...]:
    package_dir = Path(__file__).resolve().parent
    return (
        Path.cwd() / ".env",
        package_dir / ".env",
    )


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


if __name__ == "__main__":
    raise SystemExit(main())
