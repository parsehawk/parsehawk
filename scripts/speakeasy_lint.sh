#!/usr/bin/env bash
set -euo pipefail

readonly SPEAKEASY_VERSION="v1.790.1"
readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CACHE_DIR="${REPOSITORY_ROOT}/.cache/tools/speakeasy/${SPEAKEASY_VERSION}"
readonly BINARY="${CACHE_DIR}/speakeasy"

platform="$(uname -s | tr '[:upper:]' '[:lower:]')"
architecture="$(uname -m)"
case "${architecture}" in
  x86_64) architecture="amd64" ;;
  arm64 | aarch64) architecture="arm64" ;;
  *)
    echo "Unsupported architecture for Speakeasy: ${architecture}" >&2
    exit 1
    ;;
esac

case "${platform}" in
  darwin | linux) ;;
  *)
    echo "Unsupported platform for Speakeasy: ${platform}" >&2
    exit 1
    ;;
esac

if [[ ! -x "${BINARY}" ]]; then
  asset="speakeasy_${platform}_${architecture}.zip"
  release_url="https://github.com/speakeasy-api/speakeasy/releases/download/${SPEAKEASY_VERSION}"
  work_dir="$(mktemp -d)"
  trap 'rm -rf "${work_dir}"' EXIT

  echo "Downloading Speakeasy ${SPEAKEASY_VERSION} for ${platform}/${architecture}..."
  curl --fail --location --silent --show-error "${release_url}/${asset}" -o "${work_dir}/${asset}"
  curl --fail --location --silent --show-error \
    "${release_url}/checksums.txt" -o "${work_dir}/checksums.txt"

  expected_checksum="$(awk -v asset="${asset}" '$2 == asset {print $1}' "${work_dir}/checksums.txt")"
  if [[ -z "${expected_checksum}" ]]; then
    echo "Published checksum not found for ${asset}." >&2
    exit 1
  fi

  if command -v shasum >/dev/null 2>&1; then
    actual_checksum="$(shasum -a 256 "${work_dir}/${asset}" | awk '{print $1}')"
  else
    actual_checksum="$(sha256sum "${work_dir}/${asset}" | awk '{print $1}')"
  fi
  if [[ "${actual_checksum}" != "${expected_checksum}" ]]; then
    echo "Speakeasy checksum verification failed." >&2
    exit 1
  fi

  mkdir -p "${CACHE_DIR}"
  unzip -q "${work_dir}/${asset}" -d "${CACHE_DIR}"
  chmod +x "${BINARY}"
fi

cd "${REPOSITORY_ROOT}"
NO_COLOR=1 TERM=dumb "${BINARY}" lint openapi \
  --schema openapi/openapi.yaml \
  --ruleset parsehawk \
  --non-interactive \
  --max-validation-errors 0 \
  --max-validation-warnings 0
