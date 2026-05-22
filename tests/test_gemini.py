from contributions_summarizer.gemini import (
    ContributionSummarizer,
    GeminiConfig,
    TokenUsage,
    parse_json_response,
)
from contributions_summarizer.models import ContributionCluster
from tests.test_cluster import make_pr


class FakeGenerator:
    def generate(self, prompt: str) -> str:
        assert "Pull requests JSON" in prompt
        return '{"headline":"Auth improvements","summary":"Improved login.","impact":"Reduced sign-in failures."}'


def test_parse_json_response_strips_fences() -> None:
    payload = parse_json_response(
        '```json\n{"headline":"A","summary":"B","impact":"C"}\n```'
    )

    assert payload["headline"] == "A"


def test_contribution_summarizer_returns_cluster_summary() -> None:
    cluster = ContributionCluster(
        id="cluster-1",
        title="Auth",
        prs=(make_pr(1, "Add login callback", "auth/oauth.py", ("auth",)),),
    )

    summary = ContributionSummarizer(FakeGenerator()).summarize_cluster(cluster)

    assert summary.cluster_id == "cluster-1"
    assert summary.headline == "Auth improvements"
    assert summary.impact == "Reduced sign-in failures."


def test_gemini_config_reads_vertex_ai_environment(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-prod")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east4")

    config = GeminiConfig.from_env(model="gemini-2.5-pro")

    assert config.project == "acme-prod"
    assert config.location == "us-east4"
    assert config.model == "gemini-2.5-pro"


def test_token_usage_reads_vertex_response_metadata() -> None:
    class Response:
        usage_metadata = {
            "prompt_token_count": 100,
            "candidates_token_count": 40,
            "total_token_count": 140,
            "cached_content_token_count": 10,
            "thoughts_token_count": 5,
        }

    usage = TokenUsage.from_response(Response())

    assert usage is not None
    assert usage.prompt_tokens == 100
    assert usage.candidate_tokens == 40
    assert usage.total_tokens == 140
    assert usage.cached_tokens == 10
    assert usage.thought_tokens == 5
