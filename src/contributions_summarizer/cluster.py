from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Callable

from contributions_summarizer.models import ContributionCluster, PullRequest


STOP_WORDS = {
    "a",
    "add",
    "an",
    "and",
    "are",
    "as",
    "bugfix",
    "develop",
    "fix",
    "for",
    "from",
    "hotfix",
    "in",
    "into",
    "kl",
    "main",
    "of",
    "on",
    "or",
    "release",
    "scrum",
    "the",
    "to",
    "update",
    "with",
}


def cluster_pull_requests(
    pull_requests: list[PullRequest],
    similarity_threshold: float = 0.45,
) -> list[ContributionCluster]:
    clusters: list[list[PullRequest]] = []
    ignored_path_tokens = common_tokens(pull_requests, path_tokens)
    ignored_text_tokens = common_tokens(pull_requests, text_tokens)
    # Greedy clustering keeps the behavior deterministic and easy to inspect:
    # walk PRs chronologically, then attach each PR to the closest existing
    # cluster when the cluster as a whole is similar enough.
    for pr in sorted(pull_requests, key=lambda item: item.sort_date):
        best_index = None
        best_score = 0.0
        for index, existing in enumerate(clusters):
            # Average the strongest few matches instead of taking only the max.
            # This prevents one bridge PR from pulling unrelated work into a
            # broad "everything touched the app" cluster.
            score = cluster_similarity(
                pr,
                existing,
                ignored_text_tokens=ignored_text_tokens,
                ignored_path_tokens=ignored_path_tokens,
            )
            if score > best_score:
                best_index = index
                best_score = score
        if best_index is not None and best_score >= similarity_threshold:
            clusters[best_index].append(pr)
        else:
            clusters.append([pr])

    return [
        ContributionCluster(
            id=f"cluster-{index + 1}",
            title=cluster_title(prs),
            prs=tuple(prs),
            signals=cluster_signals(prs),
        )
        for index, prs in enumerate(sorted(clusters, key=lambda group: group[0].sort_date))
    ]


def cluster_similarity(
    pr: PullRequest,
    cluster: list[PullRequest],
    ignored_text_tokens: set[str] | None = None,
    ignored_path_tokens: set[str] | None = None,
) -> float:
    scores = [
        pr_similarity(
            pr,
            candidate,
            ignored_text_tokens=ignored_text_tokens,
            ignored_path_tokens=ignored_path_tokens,
        )
        for candidate in cluster
    ]
    strongest = sorted(scores, reverse=True)[: min(3, len(scores))]
    return sum(strongest) / len(strongest)


def pr_similarity(
    left: PullRequest,
    right: PullRequest,
    ignored_text_tokens: set[str] | None = None,
    ignored_path_tokens: set[str] | None = None,
) -> float:
    left_text_tokens = text_tokens(left) - (ignored_text_tokens or set())
    right_text_tokens = text_tokens(right) - (ignored_text_tokens or set())
    left_path_tokens = path_tokens(left) - (ignored_path_tokens or set())
    right_path_tokens = path_tokens(right) - (ignored_path_tokens or set())
    text_score = jaccard(left_text_tokens, right_text_tokens)
    path_score = jaccard(left_path_tokens, right_path_tokens)
    label_score = jaccard(set(left.labels), set(right.labels))
    date_score = recency_score(left.sort_date, right.sort_date)
    # Text and paths carry most of the signal. Labels are useful when teams keep
    # them consistent. Recency is intentionally weak so older follow-up work can
    # still join the right cluster when the content matches.
    return (
        (text_score * 0.40)
        + (path_score * 0.35)
        + (label_score * 0.20)
        + (date_score * 0.05)
    )


def text_tokens(pr: PullRequest) -> set[str]:
    raw = f"{pr.title} {pr.body[:500]} {' '.join(pr.labels)}"
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", raw.lower())
    return {word for word in words if word not in STOP_WORDS}


def path_tokens(pr: PullRequest) -> set[str]:
    tokens: set[str] = set()
    for file in pr.files:
        parts = re.split(r"[/_.-]+", file.filename.lower())
        tokens.update(part for part in parts if len(part) > 2 and part not in STOP_WORDS)
        area = file.top_level_area()
        if area:
            # Top-level directories are strong repository-area signals, so keep
            # them distinct from ordinary filename words.
            tokens.add(f"area:{area.lower()}")
    return tokens


def common_tokens(
    pull_requests: list[PullRequest],
    extractor: Callable[[PullRequest], set[str]],
    min_prs: int = 8,
    frequency_threshold: float = 0.55,
) -> set[str]:
    if len(pull_requests) < min_prs:
        return set()
    counts: Counter[str] = Counter()
    for pr in pull_requests:
        counts.update(extractor(pr))
    return {
        token
        for token, count in counts.items()
        if count / len(pull_requests) >= frequency_threshold
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def recency_score(left: datetime, right: datetime) -> float:
    days = abs((left - right).days)
    if days <= 14:
        return 1.0
    if days <= 45:
        return 0.5
    if days <= 90:
        return 0.25
    return 0.0


def cluster_title(pull_requests: list[PullRequest]) -> str:
    # Prefer human-curated labels for names, then changed areas, then common
    # words from titles and descriptions.
    label_counts: Counter[str] = Counter(
        label for pr in pull_requests for label in pr.labels if label
    )
    if label_counts:
        return titleize(label_counts.most_common(1)[0][0])

    area_counts: Counter[str] = Counter(
        area for pr in pull_requests for area in pr.changed_areas() if area
    )
    if area_counts:
        return f"{titleize(area_counts.most_common(1)[0][0])} Work"

    token_counts: Counter[str] = Counter(
        token for pr in pull_requests for token in text_tokens(pr)
    )
    if token_counts:
        return titleize(" ".join(token for token, _ in token_counts.most_common(3)))

    return "General Contributions"


def cluster_signals(pull_requests: list[PullRequest]) -> tuple[str, ...]:
    areas = Counter(area for pr in pull_requests for area in pr.changed_areas())
    labels = Counter(label for pr in pull_requests for label in pr.labels)
    signals: list[str] = []
    signals.extend(f"area:{area}" for area, _ in areas.most_common(5))
    signals.extend(f"label:{label}" for label, _ in labels.most_common(5))
    return tuple(signals)


def group_by_primary_area(pull_requests: list[PullRequest]) -> dict[str, list[PullRequest]]:
    grouped: dict[str, list[PullRequest]] = defaultdict(list)
    for pr in pull_requests:
        areas = pr.changed_areas()
        grouped[areas[0] if areas else "general"].append(pr)
    return dict(grouped)


def titleize(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()
