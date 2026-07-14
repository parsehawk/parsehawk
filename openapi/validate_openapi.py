#!/usr/bin/env python3
"""Validate the committed ParseHawk OpenAPI document structurally."""

from __future__ import annotations

from pathlib import Path

import yaml
from openapi_spec_validator import validate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = REPOSITORY_ROOT / "openapi" / "openapi.yaml"


def main() -> int:
    document = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(document)
    print("OpenAPI document is structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
