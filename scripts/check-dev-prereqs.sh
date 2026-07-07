#!/usr/bin/env bash
set -euo pipefail

include_runtime=0

for arg in "$@"; do
  case "$arg" in
    --runtime)
      include_runtime=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

missing=0

check_required() {
  local command_name="$1"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required development tool: $command_name"
    missing=1
  fi
}

check_required git
check_required just
check_required uv
check_required node
check_required pnpm
check_required docker

if [ "$include_runtime" -eq 1 ]; then
  if command -v docker >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
    echo "Missing required runtime tool: docker compose"
    missing=1
  fi
fi

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Install the missing tool(s), then rerun the command."
  echo "Install guides:"
  echo "  just: https://just.systems/man/en/packages.html"
  echo "  uv: https://docs.astral.sh/uv/getting-started/installation/"
  echo "  Node.js: https://nodejs.org/en/download"
  echo "  pnpm: https://pnpm.io/installation"
  if [ "$include_runtime" -eq 1 ]; then
    echo "  Docker: https://docs.docker.com/get-started/get-docker/"
  fi
  exit 1
fi
