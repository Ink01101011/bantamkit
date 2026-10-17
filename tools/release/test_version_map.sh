#!/usr/bin/env bash
#
# tools/release/test_version_map.sh -- the prerelease version mapping in publish.sh (job68, #199).
#
# A beta has two spellings: PEP 440 on PyPI (`0.37.0b1`, what __init__.py declares) and semver
# on npm (`0.37.0-beta.1`, what package.json declares). publish.sh maps the first to the second
# before comparing them, and publishes a prerelease to npm under `--tag beta` so `@latest` --
# which every user's MCP config runs -- does not move to it. A stable version maps to itself
# and gets no dist-tag, so a stable release behaves exactly as before.
#
# The functions are read OUT OF publish.sh, not copied here, so this tests the bytes that run.
#
#   bash tools/release/test_version_map.sh     # exit 0 and "PASS n" when every case holds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLISH="${PUBLISH_SH:-$SCRIPT_DIR/publish.sh}"

for fn in map_pep440_to_semver npm_dist_tag; do
  body="$(awk -v fn="$fn" '$0 ~ "^"fn"\\(\\)" {on=1} on {print} on && /^}/ {exit}' "$PUBLISH")"
  if [ -z "$body" ]; then
    printf 'FAIL  %s() is not defined in %s\n' "$fn" "$PUBLISH" >&2
    exit 1
  fi
  eval "$body"
done

PASS=0
FAIL=0
expect() { # label, expected, actual
  if [ "$2" = "$3" ]; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL  %s: expected %s, got %s\n' "$1" "'$2'" "'$3'" >&2
  fi
}

# PEP 440 -> semver
expect "map 0.37.0b1"   "0.37.0-beta.1"  "$(map_pep440_to_semver 0.37.0b1)"
expect "map 0.37.0b12"  "0.37.0-beta.12" "$(map_pep440_to_semver 0.37.0b12)"
expect "map 0.37.0rc2"  "0.37.0-rc.2"    "$(map_pep440_to_semver 0.37.0rc2)"
expect "map 0.37.0a3"   "0.37.0-alpha.3" "$(map_pep440_to_semver 0.37.0a3)"
expect "map 10.20.30b4" "10.20.30-beta.4" "$(map_pep440_to_semver 10.20.30b4)"
# stable passes through unchanged
expect "map 0.36.0"     "0.36.0"         "$(map_pep440_to_semver 0.36.0)"
expect "map 0.35.9"     "0.35.9"         "$(map_pep440_to_semver 0.35.9)"
# anything the mapping does not recognise is left alone, so the version-site check refuses it
# instead of a guess going through
expect "map 0.37.0.dev1 (untouched)" "0.37.0.dev1" "$(map_pep440_to_semver 0.37.0.dev1)"
expect "map 0.37.0b (untouched)"     "0.37.0b"     "$(map_pep440_to_semver 0.37.0b)"

# npm dist-tag: a prerelease never goes to @latest; a stable release gets no --tag at all
expect "tag 0.37.0-beta.1"  "beta" "$(npm_dist_tag 0.37.0-beta.1)"
expect "tag 0.37.0-rc.2"    "beta" "$(npm_dist_tag 0.37.0-rc.2)"
expect "tag 0.37.0-alpha.3" "beta" "$(npm_dist_tag 0.37.0-alpha.3)"
expect "tag 0.36.0"         ""     "$(npm_dist_tag 0.36.0)"

# The runtime-py/README.md wheelhouse pin: publish.sh's own README_PINS line, run against a
# fixture README. A PyPI pin keeps the PEP 440 spelling, and a semver spelling there reads as
# its bare X.Y.Z, which then disagrees with __version__ and is refused. The stable case is the
# one that guards "a stable release behaves exactly as before": J68-9's first cut lost a space
# in this line and read NO pin at all on 0.35.9, which only the before/after dry-run diff saw.
pins_line="$(grep -E '^README_PINS=' "$PUBLISH" | head -1)"
if [ -z "$pins_line" ]; then
  printf 'FAIL  no README_PINS= line in %s\n' "$PUBLISH" >&2
  exit 1
fi
FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/bk-version-map-XXXXXX")"
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/runtime-py"
readme_pins() { # README body -> what publish.sh reads as the pin(s)
  printf '%s\n' "$1" > "$FIXTURE/runtime-py/README.md"
  REPO="$FIXTURE"
  eval "$pins_line"
  printf '%s\n' "$README_PINS"
}
expect "pin stable"           "0.35.9"   "$(readme_pins 'pip download "bantamkit[mcp]==0.35.9" -d wheelhouse')"
expect "pin PEP 440 beta"     "0.37.0b1" "$(readme_pins 'pip download "bantamkit[mcp]==0.37.0b1" -d wheelhouse')"
expect "pin PEP 440 rc"       "0.37.0rc2" "$(readme_pins 'pip download "bantamkit[mcp]==0.37.0rc2" -d wheelhouse')"
expect "pin semver (refused)" "0.37.0"   "$(readme_pins 'pip download "bantamkit[mcp]==0.37.0-beta.1" -d wheelhouse')"

if [ "$FAIL" -gt 0 ]; then
  printf 'FAIL %d of %d\n' "$FAIL" "$((PASS + FAIL))" >&2
  exit 1
fi
printf 'PASS %d\n' "$PASS"
