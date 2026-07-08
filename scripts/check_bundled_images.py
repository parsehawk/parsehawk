#!/usr/bin/env python3
"""Enforce the reviewed manifest of bundled/referenced container images.

Dependency scanners only see packaged deps, so a source-available image pulled in
via a Dockerfile `FROM` or a Compose `image:` (e.g. Arize Phoenix, ELv2) is
invisible to them. This guard closes that gap: it extracts every image any
Dockerfile or Compose file in the repo references and checks it against
licenses/bundled-images.toml, which records each image's license and how it
ships. It fails when:

  1. novelty      — a referenced image has no manifest entry (forces a human to
                    classify a newly-added image before merge);
  2. ship-mode    — a manifest image whose license is disallowed (strong-copyleft
                    / source-available / non-commercial) is marked `redistributed`
                    (the same license is fine as `runtime-pull` / `build-only`);
  3. stale        — a manifest entry no image references any more (warn only).

With --scan-images it additionally pulls the small images and uses trivy to detect
the license actually inside them, failing on drift from the manifest (catches a
vendor relicensing an existing image, e.g. Apache -> BUSL). Each image is scanned
at the tag actually referenced, so the scan tests the artifact in use. vLLM is
skipped (multi-GB). Requires trivy + a working container runtime.

Known limitation: a Compose service that both `build:`s locally and names its
output with `image:` will surface as novel (line-based parsing cannot pair the
two keys). No such service exists today; if one appears, list its first-party
image in the manifest or teach this parser about the pairing.

The license policy is imported from check_dep_licenses so images and dependencies
share one source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_dep_licenses import BLOCK, classify  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "licenses" / "bundled-images.toml"
# Vendored/generated trees that cannot reference images we ship. Hidden dirs
# (.git, .venv, ...) are pruned by the leading-dot check in image_files().
SKIP_DIRS = {"node_modules", "__pycache__", "dist", "build"}
ALLOWED_SHIPS = {"redistributed", "runtime-pull", "build-only"}
# Images too large to pull for a content scan; the manifest is authoritative.
SCAN_SKIP = {"vllm/vllm-openai"}

FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", re.IGNORECASE)
ARG_RE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)", re.IGNORECASE)
VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
COMPOSE_FILE_RE = re.compile(r"(docker-)?compose[^/]*\.ya?ml")
IMAGE_KEY_RE = re.compile(r"^\s*image:\s*[\"']?([^\"'\s#]+)")
# Compose interpolation with a default: ${VAR:-default} / ${VAR-default}.
COMPOSE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def bare_name(image_ref: str) -> str:
    """Strip tag and digest, keep repository (incl. any registry/namespace)."""
    ref = image_ref.split("@", 1)[0]
    # A ':' is a tag only if it's after the last '/': registries can carry a port.
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon > slash:
        ref = ref[:colon]
    return ref


def image_files() -> tuple[list[Path], list[Path]]:
    """All Dockerfiles and Compose files in the repo, hidden/vendored dirs pruned."""
    dockerfiles: list[Path] = []
    composes: list[Path] = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for f in files:
            low = f.lower()
            if low.startswith("dockerfile"):
                dockerfiles.append(Path(root) / f)
            elif COMPOSE_FILE_RE.fullmatch(low):
                composes.append(Path(root) / f)
    return sorted(dockerfiles), sorted(composes)


def referenced_images() -> dict[str, list[tuple[str, str]]]:
    """Map bare image name -> list of (full ref as written, 'path:line').

    Dockerfiles: resolves ARG-default FROMs, skips build-stage aliases
    (FROM <stage>). Compose files: reads `image:` keys, resolving
    ${VAR:-default} interpolation. References that still contain an
    unresolvable variable are skipped in both.
    """
    refs: dict[str, list[tuple[str, str]]] = {}

    def add(image: str, path: Path, n: int) -> None:
        refs.setdefault(bare_name(image), []).append((image, f"{path.relative_to(REPO)}:{n}"))

    dockerfiles, composes = image_files()
    for path in dockerfiles:
        args: dict[str, str] = {}
        stages: set[str] = set()
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if m := ARG_RE.match(line):
                args[m.group(1)] = m.group(2)
            if m := FROM_RE.match(line):
                image = m.group(1)
                # Resolve ${VAR} against ARG defaults seen so far.
                image = VAR_RE.sub(lambda mm: args.get(mm.group(1), mm.group(0)), image)
                # Track `AS <stage>` and skip references to prior stages.
                after = line[m.end() :].strip().split()
                if len(after) >= 2 and after[0].lower() == "as":
                    stages.add(after[1].lower())
                if image.lower() in stages or "$" in image:
                    continue
                add(image, path, n)
    for path in composes:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if m := IMAGE_KEY_RE.match(line):
                image = COMPOSE_VAR_RE.sub(
                    lambda mm: mm.group(0) if mm.group(2) is None else mm.group(2),
                    m.group(1),
                )
                if "$" in image:
                    continue
                add(image, path, n)
    return refs


def trivy_image_license(ref: str) -> set[str]:
    """Return the set of disallowed license names trivy finds inside an image.

    `ref` is the reference as written (tag/digest included), so the scan tests
    the artifact actually in use; untagged refs default to :latest.
    """
    target = ref if ref != bare_name(ref) else f"{ref}:latest"
    cmd = [
        "trivy",
        "image",
        "--config",
        str(REPO / ".trivyaml"),
        "--scanners",
        "license",
        "--severity",
        "CRITICAL",
        "--format",
        "json",
        "--quiet",
        target,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"    (image scan skipped for {target}: {e})")
        return set()
    if out.returncode not in (0, 1) or not out.stdout.strip():
        print(f"    (image scan inconclusive for {target})")
        return set()
    data = json.loads(out.stdout)
    names = set()
    for r in data.get("Results") or []:
        for lic in r.get("Licenses") or []:
            names.add(lic.get("Name", ""))
    return {n for n in names if n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--scan-images",
        action="store_true",
        help="also pull small images and check for license drift (needs trivy)",
    )
    args = ap.parse_args()

    manifest = tomllib.loads(MANIFEST.read_text())
    entries = {e["name"]: e for e in manifest.get("image", [])}
    for name, e in entries.items():
        if e.get("ships") not in ALLOWED_SHIPS:
            print(
                f"✖ manifest entry {name!r} has invalid ships={e.get('ships')!r} "
                f"(expected one of {sorted(ALLOWED_SHIPS)})"
            )
            return 2

    refs = referenced_images()
    failures: list[str] = []

    # 1. novelty + 2. ship-mode
    for name, uses in sorted(refs.items()):
        where = ", ".join(loc for _, loc in uses)
        entry = entries.get(name)
        if entry is None:
            failures.append(
                f"unlisted image {name!r} referenced at {where} — "
                f"add it to {MANIFEST.relative_to(REPO)} with license + ships"
            )
            continue
        verdict, label = classify(entry["license"])
        if verdict == BLOCK and entry["ships"] == "redistributed":
            failures.append(
                f"{name!r} is {entry['license']} ({label}) but marked "
                f"ships=redistributed at {where} — disallowed when shipped"
            )

    # 3. stale entries (warn only)
    for name in sorted(entries.keys() - refs.keys()):
        print(
            f"⚠ manifest entry {name!r} is no longer referenced by any Dockerfile or Compose file"
        )

    # optional drift scan, at each tag actually referenced
    if args.scan_images:
        for name, entry in sorted(entries.items()):
            if name not in refs or name in SCAN_SKIP:
                continue
            declared = entry["license"]
            for ref in sorted({r for r, _ in refs[name]}):
                print(f"→ scanning {ref} for license drift…")
                found = trivy_image_license(ref)
                # Only source-available / non-commercial licenses signal a
                # relicense: strong-copyleft (GPL/LGPL) shows up as normal base-OS
                # system packages (mere aggregation), so flagging it here would be
                # all false positives.
                drift = {
                    n
                    for n in found
                    if n.upper() != declared.upper()
                    and classify(n)[1] in ("source-available", "non-commercial")
                }
                if drift:
                    failures.append(
                        f"{ref!r} manifest says {declared} but image contains "
                        f"restricted license(s) {sorted(drift)} — relicense drift"
                    )

    if failures:
        print(f"\n✖ {len(failures)} bundled-image violation(s):")
        for f in failures:
            print(f"    {f}")
        return 1
    print(f"✓ all {len(refs)} referenced image(s) are reviewed and compatible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
