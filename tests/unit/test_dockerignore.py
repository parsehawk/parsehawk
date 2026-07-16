from pathlib import Path

import pytest

DOCKERIGNORE = Path(__file__).parents[2] / ".dockerignore"


def _patterns() -> set[str]:
    return {
        line.strip()
        for line in DOCKERIGNORE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


@pytest.mark.parametrize(
    "pattern",
    [
        "**/.venv",
        "**/.ruff_cache",
        "**/.pytest_cache",
        "**/.coverage",
        "**/.DS_Store",
        "**/__pycache__",
        "**/*.pyc",
        "**/node_modules",
        "**/dist",
        "**/coverage",
        "**/*.tsbuildinfo",
        "**/.cache",
        "**/playwright-report",
        "**/test-results",
        "**/.env",
        "**/.env.*",
        "**/*.env",
        "**/*.log",
    ],
)
def test_generated_and_sensitive_artifacts_are_ignored_recursively(pattern: str) -> None:
    assert pattern in _patterns()


@pytest.mark.parametrize("pattern", ["data", "examples", "example-applications"])
def test_local_runtime_and_example_data_are_ignored(pattern: str) -> None:
    assert pattern in _patterns()
