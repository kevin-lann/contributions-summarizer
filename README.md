# Contributions Summarizer

`contrib-summary` fetches pull requests authored by a GitHub user in a repository, clusters related work, and asks Gemini to generate concise contribution summaries.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

Set credentials in your shell:

```bash
export GITHUB_TOKEN="github_pat_or_app_token"
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
# Only needed when using --ai-provider google-ai
export GEMINI_API_KEY="gemini_api_key"
```

You can also put those values in a `.env` file at the repository root:

```bash
GITHUB_TOKEN="github_pat_or_app_token"
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
GOOGLE_CLOUD_LOCATION="us-central1"
# Only needed when using --ai-provider google-ai
GEMINI_API_KEY="gemini_api_key"
```

The CLI automatically loads `.env` from the directory where you run `contrib-summary`. It also supports `src/contributions_summarizer/.env` for local development, but the repository root is the preferred location.

For GitHub Enterprise Server, set:

```bash
export GITHUB_API_URL="https://github.example.com/api/v3"
```

## GitHub Token

The tool needs a GitHub token so it can read PR metadata and changed files without hitting low unauthenticated rate limits. Private repositories also require a token with access to the target repository.

Recommended option: create a fine-grained personal access token.

1. Go to GitHub Settings: `Settings` -> `Developer settings` -> `Personal access tokens` -> `Fine-grained tokens`.
2. Select `Generate new token`.
3. Set the resource owner to the user or organization that owns the repository.
4. Under `Repository access`, choose the specific repository you want to summarize.
5. Under `Repository permissions`, grant:
   - `Pull requests`: `Read-only`
   - `Contents`: `Read-only`
   - `Metadata`: automatically included by GitHub
6. Generate the token and set it as `GITHUB_TOKEN`.

Classic personal access tokens also work. For public repositories, `public_repo` is enough. For private repositories, use the `repo` scope.

Do not commit tokens. Keep them in your shell environment, password manager, or a local ignored `.env` file.

## Vertex AI Gemini

By default, summaries use Gemini through Google Vertex AI. The tool uses Application Default Credentials and the `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` environment variables.

One-time setup:

1. Install the Google Cloud CLI.
2. Authenticate locally:

```bash
gcloud auth application-default login
```

3. Set the active project:

```bash
gcloud config set project your-gcp-project-id
```

4. Enable the Vertex AI API:

```bash
gcloud services enable aiplatform.googleapis.com
```

5. Set the environment variables

```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
```

For non-local usage, use a service account with permission to call Vertex AI and set `GOOGLE_APPLICATION_CREDENTIALS` to the service account JSON path.

## Google AI Gemini

You can also use Gemini through the Google AI API with an API key:

```bash
export GEMINI_API_KEY="gemini_api_key"
contrib-summary owner/repo --user github-login --ai-provider google-ai
```

Provider selection is explicit:

- `--ai-provider vertex-ai`: default, uses Google Cloud Vertex AI with Application Default Credentials.
- `--ai-provider google-ai`: uses `GEMINI_API_KEY`.

The provider boundary is isolated behind the text generator interface, so additional providers such as OpenAI or Claude can be added later without changing the GitHub ingestion, grouping, or report rendering pipeline.

## Usage

```bash
contrib-summary owner/repo --user github-login --since 2024-01-01 --until 2024-12-31 --out summary.md
```

Useful options:

```bash
contrib-summary owner/repo --user github-login --json-out summary.json
contrib-summary owner/repo --user github-login --include-open
contrib-summary owner/repo --user github-login --max-prs 50
contrib-summary owner/repo --user github-login --ai-provider google-ai
contrib-summary owner/repo --user github-login --no-ai
```

Gemini token usage is logged to stderr for each AI grouping and summary call:

```text
Gemini token usage: model=gemini-2.5-flash prompt=1200 candidate=180 total=1380 cached=n/a thought=n/a
```

After all AI calls finish, aggregate token usage and estimated cost are logged:

```text
Gemini token totals: model=gemini-2.5-flash calls=8 prompt=24000 candidate=4200 thought=0 total=28200 cached=0 missing_usage_calls=0 estimated_cost=$0.017700
```

Cost estimates use standard Vertex AI Gemini text pricing for supported models:

- `gemini-2.5-flash`: $0.30 per 1M input tokens, $2.50 per 1M output tokens
- `gemini-2.5-flash-lite`: $0.10 per 1M input tokens, $0.40 per 1M output tokens
- `gemini-2.5-pro`: $1.25 per 1M input tokens, $10.00 per 1M output tokens for prompts up to 200K tokens

The estimate uses prompt tokens as input and candidate plus thought tokens as output. It does not model cached-token discounts, batch pricing, nonstandard enterprise pricing, taxes, or `gemini-2.5-pro` long-context pricing above 200K tokens.

When Markdown is written to stdout, token logs still go to stderr. Redirect report output with `--out` when you want a clean file.

## Private Repositories

Private repositories work when `GITHUB_TOKEN` can read the target repository.

Required access:

- Classic personal access token: `repo`
- Fine-grained personal access token: repository access with pull request read permission, and contents read permission for changed files
- GitHub App installation token: repository access with pull request read permission, and contents read permission for changed files

## Output

The Markdown report contains:

- Repository, author, and date range
- Contribution theme groups
- AI-generated summary per group
- Representative PRs with changed areas

JSON output is available for downstream tools.

## How Clustering Works

By default, the tool uses a two-pass AI grouping flow. First, Gemini receives compact PR facts and assigns every PR to a narrow contribution theme such as `Authentication and session handling`, `AI chatbot and RAG assistant`, `Timetable generation`, or `Documentation updates`. Then Gemini summarizes each final theme.

Gemini calls use structured JSON output with `response_mime_type="application/json"` and explicit response schemas. The grouping schema returns theme titles, PR numbers, and grouping signals. The summary schema returns a headline, summary, impact, and 2-3 resume-ready bullets.

The grouping instructions tell Gemini to avoid broad buckets based only on shared repository roots, release timing, or generic words. It prefers coherent features, projects, and isolated improvements, with one-PR groups for standalone fixes, docs, releases, or unclear work.

`--no-ai` switches to deterministic clustering. In that mode, the algorithm walks PRs in chronological order and compares each PR against existing clusters. A PR joins the cluster with the highest similarity score when that score is at least `--similarity-threshold`, which defaults to `0.45`. Otherwise, it starts a new cluster.

Similarity combines four signals:

- Text overlap from PR titles, body excerpts, and labels: 40%
- Changed path overlap from filenames and top-level directories: 35%
- Label overlap: 20%
- Date proximity: 5%

Text and path overlap use Jaccard similarity, which compares shared tokens against total unique tokens. Path tokens include filename pieces such as `auth`, `oauth`, and `tokens`, plus explicit area tokens like `area:src` or `area:billing` from top-level directories.

Date proximity is deliberately weak. PRs within 14 days get the full recency score, PRs within 45 days get a partial score, and PRs farther apart can still cluster when their text, paths, or labels match.

For repositories with many PRs, tokens that appear across most PRs are ignored during clustering. This prevents broad repository names, shared root directories, release words, and repeated branch prefixes from merging unrelated features into one large group.

Cluster assignment uses the strongest few PR matches inside a cluster, not a single best match. This makes clusters narrower because one bridge PR cannot pull unrelated work into an already broad group.

Cluster titles are chosen from the strongest available human-readable signal:

- Most common label
- Most common changed area
- Most common title/body tokens
- `General Contributions` as a fallback

## Tests

```bash
pytest
```
