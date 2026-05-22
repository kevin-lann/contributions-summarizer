import os

from contributions_summarizer.cli import load_env_file


def test_load_env_file_sets_missing_environment_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                'GITHUB_TOKEN="from-file"',
                "GOOGLE_CLOUD_PROJECT=project-from-file",
                "export GOOGLE_CLOUD_LOCATION=us-central1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    load_env_file(env_file)

    assert os.environ["GITHUB_TOKEN"] == "from-file"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "project-from-file"
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "us-central1"


def test_load_env_file_does_not_override_existing_environment(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=from-file", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "from-shell")

    load_env_file(env_file)

    assert os.environ["GITHUB_TOKEN"] == "from-shell"
