#!/usr/bin/env python3
"""Gate packaged dependency licenses against the project's Apache-2.0 policy.

One policy, many sources (issue #92). The unified default is `osv-scanner`, which
reads both uv.lock and pnpm-lock.yaml in one pass and resolves licenses via
deps.dev (neither lockfile embeds license data, so this enrichment is what makes a
single tool possible). pip-licenses (Python) and `pnpm licenses list` (Node) are
kept as offline alternates that read locally-installed metadata. Every source is
reduced to a package -> license-string mapping and classified identically here.

Usage:
    # unified (both ecosystems, no install needed). osv exits non-zero when it
    # finds anything outside its allowlist, so tolerate that and classify here:
    osv-scanner scan source --format json \
        --licenses="MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC" \
        --lockfile uv.lock --lockfile pnpm-lock.yaml > osv.json || true
    python3 scripts/check_dep_licenses.py --source osv < osv.json

    # offline alternates
    pip-licenses --format=json | python3 scripts/check_dep_licenses.py --source pip
    pnpm --dir apps/web licenses list --json | python3 scripts/check_dep_licenses.py --source pnpm

The osv allowlist only controls which packages osv *surfaces* (permissive ones are
omitted); the real block/flag/allow decision is made by classify() below, so a
narrow allowlist is safe — anything dangerous still surfaces and gets classified.

Policy:
    block  strong-copyleft (GPL/AGPL), source-available (Elastic/BUSL/SSPL),
           non-commercial (CC-*-NC)             -> exit 1
    flag   LGPL and UNKNOWN                      -> reported, does not block
    allow  permissive, MPL-2.0, and anything on the exception allowlist

`--report-only` never exits non-zero (used for the first rollout PR to surface
the baseline before the gate goes blocking). Package-specific exceptions live in
scripts/dep_license_exceptions.txt (one `name` or `name==reason` per line).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXCEPTIONS_FILE = Path(__file__).with_name("dep_license_exceptions.txt")

# Ordered most-specific-first: AGPL/LGPL must be tested before GPL, since both
# strings contain "GPL". Each entry: (verdict, human label, regex over the
# uppercased license string).
BLOCK, FLAG, ALLOW = "BLOCK", "FLAG", "ALLOW"
RULES: list[tuple[str, str, re.Pattern[str]]] = [
    # --- source-available (block): not OSI/Apache-compatible when shipped ---
    (BLOCK, "source-available", re.compile(r"ELASTIC|\bELV2\b")),
    (BLOCK, "source-available", re.compile(r"BUSL|BUSINESS SOURCE")),
    (BLOCK, "source-available", re.compile(r"\bSSPL\b|SERVER SIDE PUBLIC")),
    (BLOCK, "source-available", re.compile(r"COMMONS CLAUSE")),
    # --- non-commercial Creative Commons (block) ---
    (BLOCK, "non-commercial", re.compile(r"\bNC\b|NONCOMMERCIAL|NON-COMMERCIAL")),
    # --- weak copyleft (flag, not block): LGPL before GPL ---
    (FLAG, "weak-copyleft", re.compile(r"\bA?LGPL|LESSER GENERAL PUBLIC")),
    # --- strong copyleft (block): AGPL before GPL ---
    (BLOCK, "strong-copyleft", re.compile(r"\bAGPL|AFFERO")),
    (BLOCK, "strong-copyleft", re.compile(r"\bGPL|GENERAL PUBLIC")),
    # --- permissive / notice / weak-file-copyleft treated as allowed ---
    (
        ALLOW,
        "permissive",
        re.compile(
            r"\bMIT\b|\bBSD\b|APACHE|\bISC\b|PYTHON SOFTWARE|\bPSF\b|MPL|MOZILLA|"
            r"\bZLIB\b|UNLICENSE|\b0BSD\b|\bWTFPL\b|BOOST|\bBSL-1\b|\bCC0\b|"
            r"OFL|OPEN FONT|\bEPL\b|ECLIPSE PUBLIC|\bMIT-0\b|POSTGRESQL"
        ),
    ),
]


def load_exceptions() -> set[str]:
    if not EXCEPTIONS_FILE.exists():
        return set()
    out: set[str] = set()
    for line in EXCEPTIONS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line.split("==", 1)[0].strip().lower())
    return out


def classify(license_str: str) -> tuple[str, str]:
    """Return (verdict, label) for a raw license string."""
    text = (license_str or "").upper()
    if not text or text in {"UNKNOWN", "NONE", "UNLICENSED"}:
        return FLAG, "unknown"
    for verdict, label, pat in RULES:
        if pat.search(text):
            return verdict, label
    return FLAG, "unrecognized"


def parse_pip(raw: str) -> list[tuple[str, str]]:
    return [(e.get("Name", "?"), e.get("License", "")) for e in json.loads(raw)]


def parse_pnpm(raw: str) -> list[tuple[str, str]]:
    """pnpm licenses list --json -> {licenseString: [{name, versions, ...}]}."""
    data = json.loads(raw)
    if isinstance(data, dict) and set(data) == {"error"}:
        raise SystemExit(f"pnpm error: {data['error']}")
    pkgs: list[tuple[str, str]] = []
    for license_str, entries in (data or {}).items():
        for entry in entries:
            pkgs.append((entry.get("name", "?"), license_str))
    return pkgs


def parse_osv(raw: str) -> list[tuple[str, str]]:
    """osv-scanner --format json -> results[].packages[] with a `licenses` list.

    Only packages outside osv's allowlist are present; each carries the SPDX id(s)
    deps.dev resolved (or "UNKNOWN"). Multiple ids are joined so classify() sees
    the whole expression (e.g. "Apache-2.0 OR MIT").
    """
    data = json.loads(raw)
    pkgs: list[tuple[str, str]] = []
    for result in data.get("results", []):
        for pkg in result.get("packages", []):
            name = pkg.get("package", {}).get("name", "?")
            licenses = pkg.get("licenses", []) or []
            pkgs.append((name, " ".join(licenses)))
    return pkgs


PARSERS = {"pip": parse_pip, "pnpm": parse_pnpm, "osv": parse_osv}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=tuple(PARSERS), required=True)
    ap.add_argument(
        "--report-only", action="store_true", help="print findings but always exit 0 (rollout mode)"
    )
    args = ap.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        print(f"error: no input on stdin for --source {args.source}", file=sys.stderr)
        return 2
    packages = PARSERS[args.source](raw)

    exceptions = load_exceptions()
    blocked: list[tuple[str, str, str]] = []
    flagged: list[tuple[str, str, str]] = []
    for name, license_str in sorted(set(packages)):
        if name.lower() in exceptions:
            continue
        verdict, label = classify(license_str)
        if verdict == BLOCK:
            blocked.append((name, license_str, label))
        elif verdict == FLAG:
            flagged.append((name, license_str, label))

    if flagged:
        print(f"⚠ {len(flagged)} package(s) to review ({args.source}):")
        for name, lic, label in flagged:
            print(f"    {label:16} {name} — {lic!r}")
    if blocked:
        print(f"✖ {len(blocked)} DISALLOWED license(s) ({args.source}):")
        for name, lic, label in blocked:
            print(f"    {label:16} {name} — {lic!r}")
    else:
        print(f"✓ no disallowed dependency licenses ({args.source}).")

    if blocked and not args.report_only:
        print(
            "\nBlock a package only after review: add it to "
            f"{EXCEPTIONS_FILE.name} with a reason, or remove the dependency."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
