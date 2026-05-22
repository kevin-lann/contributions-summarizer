from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai

from contributions_summarizer.models import ClusterSummary, ContributionCluster, PullRequest


logger = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    pass


class TextGenerator(Protocol):
    def generate(self, prompt: str, response_schema: dict | None = None) -> str:
        pass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


GEMINI_PRICING: dict[str, ModelPricing] = {
    "gemini-2.5-flash": ModelPricing(input_per_million=0.30, output_per_million=2.50),
    "gemini-2.5-flash-lite": ModelPricing(
        input_per_million=0.10,
        output_per_million=0.40,
    ),
    "gemini-2.5-pro": ModelPricing(input_per_million=1.25, output_per_million=10.00),
}


GROUPING_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "groups": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "pr_numbers": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "signals": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["title", "pr_numbers", "signals"],
            },
        }
    },
    "required": ["groups"],
}


SUMMARY_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "impact": {"type": "STRING"},
        "resume_bullets": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "summary", "impact", "resume_bullets"],
}


@dataclass(frozen=True)
class GeminiConfig:
    project: str
    location: str = "us-central1"
    model: str = "gemini-2.5-flash"

    @classmethod
    def from_env(cls, model: str = "gemini-2.5-flash") -> "GeminiConfig":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise GeminiError("GOOGLE_CLOUD_PROJECT is required for Vertex AI.")
        return cls(
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=model,
        )


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    candidate_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    thought_tokens: int | None = None

    @classmethod
    def from_response(cls, response: Any) -> "TokenUsage | None":
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return None

        usage = cls(
            prompt_tokens=metadata_value(metadata, "prompt_token_count"),
            candidate_tokens=metadata_value(metadata, "candidates_token_count"),
            total_tokens=metadata_value(metadata, "total_token_count"),
            cached_tokens=metadata_value(metadata, "cached_content_token_count"),
            thought_tokens=metadata_value(metadata, "thoughts_token_count"),
        )
        if all(value is None for value in usage.__dict__.values()):
            return None
        return usage

    def log(self, model: str) -> None:
        logger.info(
            "Gemini token usage: model=%s prompt=%s candidate=%s total=%s cached=%s thought=%s",
            model,
            format_token_count(self.prompt_tokens),
            format_token_count(self.candidate_tokens),
            format_token_count(self.total_tokens),
            format_token_count(self.cached_tokens),
            format_token_count(self.thought_tokens),
        )


@dataclass
class TokenUsageTotals:
    calls: int = 0
    prompt_tokens: int = 0
    candidate_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    thought_tokens: int = 0
    missing_usage_calls: int = 0

    def add(self, usage: TokenUsage | None) -> None:
        self.calls += 1
        if usage is None:
            self.missing_usage_calls += 1
            return
        self.prompt_tokens += usage.prompt_tokens or 0
        self.candidate_tokens += usage.candidate_tokens or 0
        self.total_tokens += usage.total_tokens or 0
        self.cached_tokens += usage.cached_tokens or 0
        self.thought_tokens += usage.thought_tokens or 0

    @property
    def billable_output_tokens(self) -> int:
        return self.candidate_tokens + self.thought_tokens

    def estimated_cost(self, model: str) -> float | None:
        pricing = pricing_for_model(model)
        if pricing is None:
            return None
        input_cost = (self.prompt_tokens / 1_000_000) * pricing.input_per_million
        output_cost = (
            self.billable_output_tokens / 1_000_000
        ) * pricing.output_per_million
        return input_cost + output_cost


class GeminiTextGenerator:
    def __init__(self, config: GeminiConfig) -> None:
        self.config = config
        self.token_totals = TokenUsageTotals()
        self.client = genai.Client(
            vertexai=True,
            project=config.project,
            location=config.location,
        )

    def generate(self, prompt: str, response_schema: dict | None = None) -> str:
        response = self.client.models.generate_content(
            model=self.config.model,
            contents=prompt,
            config=build_generation_config(response_schema),
        )
        usage = TokenUsage.from_response(response)
        self.token_totals.add(usage)
        if usage:
            usage.log(self.config.model)
        else:
            logger.info("Gemini token usage: model=%s unavailable", self.config.model)
        text = getattr(response, "text", None)
        if not text:
            raise GeminiError("Gemini returned an empty response.")
        return text

    def log_token_totals(self) -> None:
        estimated_cost = self.token_totals.estimated_cost(self.config.model)
        cost_text = (
            f"${estimated_cost:.6f}" if estimated_cost is not None else "unavailable"
        )
        logger.info(
            "Gemini token totals: model=%s calls=%s prompt=%s candidate=%s thought=%s total=%s cached=%s missing_usage_calls=%s estimated_cost=%s",
            self.config.model,
            self.token_totals.calls,
            self.token_totals.prompt_tokens,
            self.token_totals.candidate_tokens,
            self.token_totals.thought_tokens,
            self.token_totals.total_tokens,
            self.token_totals.cached_tokens,
            self.token_totals.missing_usage_calls,
            cost_text,
        )


class ContributionSummarizer:
    def __init__(self, generator: TextGenerator) -> None:
        self.generator = generator

    def group_pull_requests(
        self,
        pull_requests: list[PullRequest],
    ) -> list[ContributionCluster]:
        if not pull_requests:
            return []

        prompt = build_grouping_prompt(pull_requests)
        raw = self.generator.generate(prompt, response_schema=GROUPING_RESPONSE_SCHEMA)
        payload = parse_json_response(raw)
        return clusters_from_grouping_payload(payload, pull_requests)

    def summarize_cluster(self, cluster: ContributionCluster) -> ClusterSummary:
        prompt = build_cluster_prompt(cluster)
        raw = self.generator.generate(prompt, response_schema=SUMMARY_RESPONSE_SCHEMA)
        payload = parse_json_response(raw)
        return ClusterSummary(
            cluster_id=cluster.id,
            headline=str(payload.get("headline") or cluster.title),
            summary=str(payload.get("summary") or ""),
            impact=str(payload.get("impact") or ""),
            resume_bullets=tuple(
                str(bullet)
                for bullet in payload.get("resume_bullets", [])
                if str(bullet).strip()
            ),
        )

    def summarize(self, clusters: list[ContributionCluster]) -> list[ClusterSummary]:
        return [self.summarize_cluster(cluster) for cluster in clusters]


def build_grouping_prompt(pull_requests: list[PullRequest]) -> str:
    prs = [compact_pr_fact(pr) for pr in pull_requests]
    return (
        "You group a developer's GitHub pull requests into contribution themes.\n"
        "Create narrow groups that represent coherent features, projects, or isolated improvements.\n"
        "Do not group unrelated PRs only because they share a repository root directory, release timing, or generic words.\n"
        "Prefer groups of multiple PRs when there is a real theme. Use one-PR groups for isolated fixes, docs, releases, or unclear work.\n"
        "Good group examples: Authentication and session handling, AI chatbot and RAG assistant, Timetable generation, Documentation updates.\n"
        "Return data matching the configured JSON schema.\n"
        "Every PR number must appear exactly once across all groups.\n\n"
        f"Pull requests JSON:\n{json.dumps(prs, indent=2)}"
    )


def compact_pr_fact(pr: PullRequest) -> dict:
    return {
        "number": pr.number,
        "title": pr.title,
        "body": pr.body[:300],
        "labels": list(pr.labels),
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
        "changed_areas": list(pr.changed_areas()),
        "top_files": [file.filename for file in pr.files[:8]],
        "additions": pr.additions,
        "deletions": pr.deletions,
    }


def clusters_from_grouping_payload(
    payload: dict,
    pull_requests: list[PullRequest],
) -> list[ContributionCluster]:
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise GeminiError("Gemini grouping response must contain a groups list.")

    prs_by_number = {pr.number: pr for pr in pull_requests}
    assigned: set[int] = set()
    clusters: list[ContributionCluster] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_prs: list[PullRequest] = []
        for raw_number in group.get("pr_numbers", []):
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                continue
            if number in assigned or number not in prs_by_number:
                continue
            assigned.add(number)
            group_prs.append(prs_by_number[number])
        if not group_prs:
            continue
        clusters.append(
            ContributionCluster(
                id=f"cluster-{len(clusters) + 1}",
                title=str(group.get("title") or "Contribution Theme"),
                prs=tuple(sorted(group_prs, key=lambda pr: pr.sort_date)),
                signals=tuple(str(signal) for signal in group.get("signals", []) if signal),
            )
        )

    for pr in pull_requests:
        if pr.number not in assigned:
            clusters.append(
                ContributionCluster(
                    id=f"cluster-{len(clusters) + 1}",
                    title=pr.title,
                    prs=(pr,),
                    signals=("unassigned-by-ai",),
                )
            )

    return clusters


def build_cluster_prompt(cluster: ContributionCluster) -> str:
    prs = [
        {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body[:1200],
            "labels": list(pr.labels),
            "url": pr.url,
            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
            "changed_areas": list(pr.changed_areas()),
            "files": [file.filename for file in pr.files[:25]],
            "additions": pr.additions,
            "deletions": pr.deletions,
        }
        for pr in cluster.prs
    ]
    return (
        "You summarize a developer's GitHub pull request contributions.\n"
        "Write factual, concise prose based only on the provided PR data.\n"
        "Return data matching the configured JSON schema.\n"
        "The summary should explain what was built or changed. The impact should explain why it mattered.\n\n"
        "Also write 2-3 resume-ready bullets for this cluster.\n"
        "Each bullet should start with a strong action verb, mention concrete technologies or product areas when present, and emphasize shipped impact.\n"
        "Do not invent metrics, scale, users, revenue, or performance numbers that are not present in the PR data.\n\n"
        f"Cluster title: {cluster.title}\n"
        f"Cluster signals: {', '.join(cluster.signals)}\n"
        f"Pull requests JSON:\n{json.dumps(prs, indent=2)}"
    )


def parse_json_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = strip_fenced_json(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini did not return valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GeminiError("Gemini response must be a JSON object.")
    return payload


def strip_fenced_json(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def build_generation_config(response_schema: dict | None) -> dict | None:
    if response_schema is None:
        return None
    return {
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }


def pricing_for_model(model: str) -> ModelPricing | None:
    normalized = model.lower()
    if normalized in GEMINI_PRICING:
        return GEMINI_PRICING[normalized]
    for model_prefix, pricing in GEMINI_PRICING.items():
        if normalized.startswith(model_prefix):
            return pricing
    return None


def metadata_value(metadata: Any, key: str) -> int | None:
    if isinstance(metadata, dict):
        value = metadata.get(key)
    else:
        value = getattr(metadata, key, None)
    return int(value) if value is not None else None


def format_token_count(value: int | None) -> str:
    return str(value) if value is not None else "n/a"
