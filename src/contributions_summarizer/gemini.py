from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai

from contributions_summarizer.models import ClusterSummary, ContributionCluster


logger = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    pass


class TextGenerator(Protocol):
    def generate(self, prompt: str) -> str:
        pass


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


class GeminiTextGenerator:
    def __init__(self, config: GeminiConfig) -> None:
        self.config = config
        self.client = genai.Client(
            vertexai=True,
            project=config.project,
            location=config.location,
        )

    def generate(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.config.model,
            contents=prompt,
        )
        usage = TokenUsage.from_response(response)
        if usage:
            usage.log(self.config.model)
        else:
            logger.info("Gemini token usage: model=%s unavailable", self.config.model)
        text = getattr(response, "text", None)
        if not text:
            raise GeminiError("Gemini returned an empty response.")
        return text


class ContributionSummarizer:
    def __init__(self, generator: TextGenerator) -> None:
        self.generator = generator

    def summarize_cluster(self, cluster: ContributionCluster) -> ClusterSummary:
        prompt = build_cluster_prompt(cluster)
        raw = self.generator.generate(prompt)
        payload = parse_json_response(raw)
        return ClusterSummary(
            cluster_id=cluster.id,
            headline=str(payload.get("headline") or cluster.title),
            summary=str(payload.get("summary") or ""),
            impact=str(payload.get("impact") or ""),
        )

    def summarize(self, clusters: list[ContributionCluster]) -> list[ClusterSummary]:
        return [self.summarize_cluster(cluster) for cluster in clusters]


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
        "Return valid JSON with exactly these keys: headline, summary, impact.\n"
        "The summary should explain what was built or changed. The impact should explain why it mattered.\n\n"
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


def metadata_value(metadata: Any, key: str) -> int | None:
    if isinstance(metadata, dict):
        value = metadata.get(key)
    else:
        value = getattr(metadata, key, None)
    return int(value) if value is not None else None


def format_token_count(value: int | None) -> str:
    return str(value) if value is not None else "n/a"
