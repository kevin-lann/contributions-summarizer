from contributions_summarizer.gemini import (
    ContributionSummarizer,
    GEMINI_PRICING,
    GeminiError,
    GeminiConfig,
    GROUPING_RESPONSE_SCHEMA,
    SUMMARY_RESPONSE_SCHEMA,
    TokenUsage,
    TokenUsageTotals,
    build_generation_config,
    build_grouping_prompt,
    clusters_from_grouping_payload,
    parse_json_response,
    pricing_for_model,
)
from contributions_summarizer.models import ContributionCluster
from tests.test_cluster import make_pr


class FakeGenerator:
    def generate(self, prompt: str, response_schema: dict | None = None) -> str:
        assert "Pull requests JSON" in prompt
        assert "resume-ready bullets" in prompt
        assert response_schema == SUMMARY_RESPONSE_SCHEMA
        return (
            '{"headline":"Auth improvements",'
            '"summary":"Improved login.",'
            '"impact":"Reduced sign-in failures.",'
            '"resume_bullets":["Built login callback support.","Improved auth reliability."]}'
        )


class FakeGroupingGenerator:
    def generate(self, prompt: str, response_schema: dict | None = None) -> str:
        assert "contribution themes" in prompt
        assert "Every PR number must appear exactly once" in prompt
        assert response_schema == GROUPING_RESPONSE_SCHEMA
        return (
            '{"groups":['
            '{"title":"Authentication","pr_numbers":[1,2],"signals":["login flow"]},'
            '{"title":"Billing export","pr_numbers":[3],"signals":["csv export"]}'
            "]}"
        )


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
    assert summary.resume_bullets == (
        "Built login callback support.",
        "Improved auth reliability.",
    )


def test_contribution_summarizer_groups_pull_requests_with_ai() -> None:
    prs = [
        make_pr(1, "Add login callback", "auth/oauth.py", ("auth",)),
        make_pr(2, "Fix redirect login", "auth/routes.py", ("auth",)),
        make_pr(3, "Add invoice csv export", "billing/export.py", ("billing",)),
    ]

    clusters = ContributionSummarizer(FakeGroupingGenerator()).group_pull_requests(prs)

    assert [cluster.title for cluster in clusters] == ["Authentication", "Billing export"]
    assert [pr.number for pr in clusters[0].prs] == [1, 2]
    assert clusters[0].signals == ("login flow",)


def test_grouping_payload_adds_unassigned_prs_as_isolated_clusters() -> None:
    prs = [
        make_pr(1, "Add login callback", "auth/oauth.py", ("auth",)),
        make_pr(2, "Fix redirect login", "auth/routes.py", ("auth",)),
    ]

    clusters = clusters_from_grouping_payload(
        {"groups": [{"title": "Authentication", "pr_numbers": [1], "signals": []}]},
        prs,
    )

    assert [cluster.title for cluster in clusters] == [
        "Authentication",
        "Fix redirect login",
    ]
    assert [cluster.prs[0].number for cluster in clusters] == [1, 2]


def test_build_grouping_prompt_uses_compact_pr_facts() -> None:
    prompt = build_grouping_prompt(
        [make_pr(1, "Add login callback", "auth/oauth.py", ("auth",))]
    )

    assert "top_files" in prompt
    assert "configured JSON schema" in prompt
    assert "Pull requests JSON" in prompt


def test_build_generation_config_requests_structured_json() -> None:
    config = build_generation_config(SUMMARY_RESPONSE_SCHEMA)

    assert config == {
        "response_mime_type": "application/json",
        "response_schema": SUMMARY_RESPONSE_SCHEMA,
    }


def test_gemini_config_reads_vertex_ai_environment(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-prod")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east4")

    config = GeminiConfig.from_env(model="gemini-2.5-pro", provider="vertex-ai")

    assert config.provider == "vertex-ai"
    assert config.project == "acme-prod"
    assert config.location == "us-east4"
    assert config.model == "gemini-2.5-pro"


def test_gemini_config_reads_google_ai_environment(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "api-key")

    config = GeminiConfig.from_env(model="gemini-2.5-flash", provider="google-ai")

    assert config.provider == "google-ai"
    assert config.api_key == "api-key"
    assert config.project is None
    assert config.model == "gemini-2.5-flash"


def test_gemini_config_requires_provider_credentials(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    try:
        GeminiConfig.from_env(provider="google-ai")
    except GeminiError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected missing GEMINI_API_KEY to fail.")


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


def test_token_usage_totals_estimates_cost() -> None:
    totals = TokenUsageTotals()
    totals.add(
        TokenUsage(
            prompt_tokens=1_000_000,
            candidate_tokens=100_000,
            total_tokens=1_100_000,
            thought_tokens=50_000,
        )
    )

    assert totals.calls == 1
    assert totals.billable_output_tokens == 150_000
    assert totals.estimated_cost("gemini-2.5-flash") == 0.675


def test_pricing_for_model_handles_versioned_suffixes() -> None:
    assert pricing_for_model("gemini-2.5-flash-001") == GEMINI_PRICING[
        "gemini-2.5-flash"
    ]
    assert pricing_for_model("unknown-model") is None
