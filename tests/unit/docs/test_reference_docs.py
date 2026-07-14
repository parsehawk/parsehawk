from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from parsehawk.cli.main import (
    CLI_COMMAND_EXAMPLES,
    CLI_CONFIG_DESCRIPTIONS,
    CONFIG_ENV_OVERRIDES,
    DEFAULT_CLI_CONFIG,
    build_parser,
)
from parsehawk.config import Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _iter_command_parsers(
    parser: argparse.ArgumentParser,
) -> list[argparse.ArgumentParser]:
    parsers = [parser]
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        children = dict.fromkeys(action.choices.values())
        for child in children:
            parsers.extend(_iter_command_parsers(child))
    return parsers


def test_every_cli_command_and_argument_has_help() -> None:
    command_parsers = _iter_command_parsers(build_parser())

    assert command_parsers
    assert CLI_COMMAND_EXAMPLES.keys() == {parser.prog for parser in command_parsers}
    for parser in command_parsers:
        assert parser.description
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                continue
            assert action.help not in {None, argparse.SUPPRESS}, (
                f"Missing help for {parser.prog} {action.dest}"
            )


def test_configuration_metadata_covers_every_public_setting() -> None:
    assert CLI_CONFIG_DESCRIPTIONS.keys() == DEFAULT_CLI_CONFIG.keys()
    assert CONFIG_ENV_OVERRIDES.keys() == DEFAULT_CLI_CONFIG.keys()
    assert all(field.description for field in Settings.model_fields.values())


def test_generated_reference_pages_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_reference_docs.py", "--check"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
