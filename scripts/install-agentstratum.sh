#!/usr/bin/env bash
# Generated from brand/templates/install-cli.sh.in; run scripts/generate-brand.mjs.
# Install a pinned standalone CLI from the configured public OBS/CDN download root.
set -euo pipefail

fail() { printf 'ContextBase installer: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'USAGE'
Usage: bash install-agentstratum.sh --base-url <HTTPS download root> --version <version> [--bin-dir <directory>]

Environment alternatives: AGENTSTRATUM_DOWNLOAD_BASE_URL, AGENTSTRATUM_VERSION,
AGENTSTRATUM_BIN_DIR (default: ~/.local/bin).
The download root is separate from your API/MCP Endpoint. No service is started.
USAGE
}

base_url="${AGENTSTRATUM_DOWNLOAD_BASE_URL:-}"
version="${AGENTSTRATUM_VERSION:-}"
bin_dir="${AGENTSTRATUM_BIN_DIR:-${HOME}/.local/bin}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --base-url|--version|--bin-dir)
      [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$1 requires a value"
      case "$1" in
        --base-url) base_url="$2" ;;
        --version) version="$2" ;;
        --bin-dir) bin_dir="$2" ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

case "$base_url" in https://?*) ;; *) fail 'configure an HTTPS download root with --base-url' ;; esac
case "$base_url" in *'?'*|*'#'*|*'@'*|*[[:space:]]*) fail 'download root must not contain credentials, query, fragment or whitespace' ;; esac
base_url="${base_url%/}"
version="${version#v}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] || fail 'set an explicit release version with --version'
case "$(uname -s)" in Linux) os=linux ;; Darwin) os=darwin ;; *) fail 'supported CLI platforms: Linux and macOS' ;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) fail 'supported CLI architectures: amd64 and arm64' ;; esac
command -v curl >/dev/null 2>&1 || fail 'curl is required'
if command -v sha256sum >/dev/null 2>&1; then
  checksum() { sha256sum "$1"; }
elif command -v shasum >/dev/null 2>&1; then
  checksum() { shasum -a 256 "$1"; }
else
  fail 'sha256sum or shasum is required'
fi

work_dir=$(mktemp -d)
staged_binary=''
cleanup() {
  rm -rf -- "$work_dir"
  if [ -n "$staged_binary" ]; then rm -f -- "$staged_binary"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
asset_url="$base_url/agentstratum-cli/$version/$os-$arch"
download() {
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --silent --show-error --location \
    --connect-timeout 15 --max-time 300 --output "$2" "$1"
}
download "$asset_url/SHA256SUMS" "$work_dir/SHA256SUMS"
# Only accept the exact binary entry, not arbitrary paths from a downloaded checksum file.
expected=$(awk '$2 == "agentstratum" { print $1 }' "$work_dir/SHA256SUMS")
[[ "$expected" =~ ^[[:xdigit:]]{64}$ ]] || fail 'SHA256SUMS must contain exactly one valid agentstratum entry'
download "$asset_url/agentstratum" "$work_dir/agentstratum"
actual=$(checksum "$work_dir/agentstratum" | awk '{print $1}')
expected=$(printf '%s' "$expected" | tr 'A-F' 'a-f')
[ "$actual" = "$expected" ] || fail 'SHA-256 mismatch; existing CLI was not changed'

mkdir -p -- "$bin_dir"
[ ! -d "$bin_dir/agentstratum" ] || fail 'the destination is a directory'
# Stage on the destination filesystem so replacement is atomic, even across mount points.
staged_binary=$(mktemp "$bin_dir/.agentstratum.XXXXXX")
cp "$work_dir/agentstratum" "$staged_binary"
chmod 755 "$staged_binary"
mv -f -- "$staged_binary" "$bin_dir/agentstratum"
staged_binary=''
printf 'Installed ContextBase (agentstratum) %s to %s/agentstratum\n' "$version" "$bin_dir"
printf 'Add this directory to PATH, then configure your API Endpoint and credential using a Profile.\n'
