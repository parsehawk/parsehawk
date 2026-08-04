from pathlib import Path

import yaml

from parsehawk.config import DEFAULT_PARSING_MAX_TOKENS

COMPOSE_PATH = Path(__file__).parents[2] / "docker" / "docker-compose.yml"


def test_compose_passes_parsing_token_budget_to_api_and_worker() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    expected = f"${{PARSEHAWK_PARSING_MAX_TOKENS:-{DEFAULT_PARSING_MAX_TOKENS}}}"

    for service_name in ("api", "worker"):
        environment = compose["services"][service_name]["environment"]
        assert environment["PARSEHAWK_PARSING_MAX_TOKENS"] == expected
