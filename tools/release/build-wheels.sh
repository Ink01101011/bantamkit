#!/usr/bin/env bash
#
# tools/release/build-wheels.sh -- the compiled platform wheels of one release (#316 G4, J90-P8).
#
# WHAT IT BUILDS. From ONE sdist (the one publish.sh uploads), a mypyc-compiled wheel per
# CPython 3.11-3.14 for each of:
#
#   macos   macosx_11_0_arm64, on this Mac, with python-build-standalone interpreters from uv
#   linux   x86_64 and aarch64, in cibuildwheel's manylinux_2_28 images under local Docker
#           (aarch64 runs natively on Apple silicon, x86_64 under emulation). auditwheel tags them
#           manylinux2014 / manylinux_2_17 / manylinux_2_28 (see LINUX_TAGS).
#
# Everything else -- Windows (#336), musllinux, macOS x86_64, other interpreters -- installs the
# pure `py3-none-any` wheel publish.sh builds beside these: pip prefers the most specific tag
# that matches (PEP 425), so no import-time switch is needed.
#
# WHY NOT CIBUILDWHEEL ON MACOS TOO. Run outside CI, cibuildwheel refuses to install the
# python.org framework builds it needs (`sudo installer -pkg`) and stops with "cibuildwheel will
# not perform system-wide installs when running outside of CI" (cibuildwheel 4.3.5,
# platforms/macos.py). python-build-standalone is built for macOS 11.0 on arm64, which is the tag
# python.org's own arm64 builds carry, so the wheel is the same tag a CI build would produce.
#
# WHAT EACH WHEEL IS. `BANTAMKIT_MYPYC=1` turns on the compile in runtime-py/hatch_build.py, in an
# isolated build that installs mypy==2.4.1 (the compiler J90-P7 measured). Built FROM THE SDIST,
# never from the checkout, so the sdist is proven to build a platform wheel and no `.so` ever
# lands in the source tree. cibuildwheel then imports each Linux wheel in a fresh venv inside the
# image and refuses one whose generated modules are not compiled; publish.sh's phase 3 installs
# and drives every wheel again (tools/release/smoke-wheel.sh).
#
# USAGE
#   tools/release/build-wheels.sh --sdist FILE --out DIR [--only macos|linux]
#   tools/release/build-wheels.sh --list VERSION [--only macos|linux]   # the exact file names
#
# Needs: uv (or UV=/path/to/uv), Docker (for linux), network (isolated builds fetch hatchling and
# mypy from PyPI). Interpreters and the cibuildwheel venv are cached under
# ${BANTAMKIT_WHEEL_CACHE:-<repo>/.release/cache}, never in the user's own uv store.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"

PYTHONS="3.11 3.12 3.13 3.14"
CIBUILDWHEEL_REQUIREMENT="cibuildwheel==4.3.5"
MACOS_TAG="macosx_11_0_arm64"
# What auditwheel names these wheels, MEASURED on the J90-P8 build (cibuildwheel 4.3.5, image
# manylinux_2_28 2026.10.26-1), not predicted: the extensions need nothing past glibc 2.17, so
# auditwheel adds the manylinux2014 / manylinux_2_17 aliases. (The first guess here,
# `manylinux_2_27...`, was refused by the check at the end of this script, as it should be.) A
# cibuildwheel or image that changes the name makes that check refuse, never upload unnamed.
LINUX_TAGS="manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64 manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64"

SDIST=""
OUT=""
ONLY=""
LIST_VERSION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sdist) [ $# -ge 2 ] || { echo "build-wheels.sh: --sdist needs a file" >&2; exit 2; }; shift; SDIST="$1" ;;
    --out) [ $# -ge 2 ] || { echo "build-wheels.sh: --out needs a directory" >&2; exit 2; }; shift; OUT="$1" ;;
    --only) [ $# -ge 2 ] || { echo "build-wheels.sh: --only needs macos or linux" >&2; exit 2; }; shift; ONLY="$1" ;;
    --list) [ $# -ge 2 ] || { echo "build-wheels.sh: --list needs a version" >&2; exit 2; }; shift; LIST_VERSION="$1" ;;
    --help|-h) awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "build-wheels.sh: unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
case "$ONLY" in
  ''|macos|linux) ;;
  *) echo "build-wheels.sh: --only takes macos or linux, got '$ONLY'" >&2; exit 2 ;;
esac

# The matrix, as exact file names: one per (interpreter, platform). publish.sh names every
# artifact it uploads in full, so this is where the platform wheels' names come from.
list_wheels() { # version
  local v cp tag
  for v in $PYTHONS; do
    cp="cp${v/./}"
    if [ "$ONLY" != "linux" ]; then
      printf 'bantamkit-%s-%s-%s-%s.whl\n' "$1" "$cp" "$cp" "$MACOS_TAG"
    fi
    if [ "$ONLY" != "macos" ]; then
      for tag in $LINUX_TAGS; do
        printf 'bantamkit-%s-%s-%s-%s.whl\n' "$1" "$cp" "$cp" "$tag"
      done
    fi
  done
}

if [ -n "$LIST_VERSION" ]; then
  list_wheels "$LIST_VERSION"
  exit 0
fi

[ -n "$SDIST" ] && [ -f "$SDIST" ] || { echo "build-wheels.sh: --sdist FILE is required and must exist" >&2; exit 2; }
[ -n "$OUT" ] || { echo "build-wheels.sh: --out DIR is required" >&2; exit 2; }
mkdir -p "$OUT"
SDIST="$(cd "$(dirname "$SDIST")" && pwd)/$(basename "$SDIST")"
OUT="$(cd "$OUT" && pwd)"
NAME="$(basename "$SDIST" .tar.gz)"            # bantamkit-<version>
VERSION="${NAME#bantamkit-}"
CACHE="${BANTAMKIT_WHEEL_CACHE:-$REPO/.release/cache}"
mkdir -p "$CACHE"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/bk-wheels-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

build_macos() {
  local uv="${UV:-uv}" v py venv src cp wheel start
  if ! "$uv" --version >/dev/null 2>&1; then
    echo "REFUSED: uv is not runnable as '$uv'; set UV=/path/to/uv (it provides the interpreters)." >&2
    return 1
  fi
  if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
    echo "REFUSED: the macOS wheels are built on an arm64 Mac; this is $(uname -s)-$(uname -m)." >&2
    return 1
  fi
  export UV_PYTHON_INSTALL_DIR="$CACHE/pythons"
  for v in $PYTHONS; do
    start=$SECONDS
    cp="cp${v/./}"
    # --no-bin: never link a `python3.X` into ~/.local/bin; the interpreter stays in the cache.
    "$uv" python install --no-config --no-bin --managed-python "$v" >/dev/null
    py="$("$uv" python find --no-config --managed-python "$v")"
    venv="$WORK/mac-$cp"
    "$py" -m venv "$venv"
    "$venv/bin/python" -m pip install --quiet --disable-pip-version-check build
    src="$WORK/mac-$cp-src"
    mkdir -p "$src"
    tar -xzf "$SDIST" -C "$src"
    env BANTAMKIT_MYPYC=1 MACOSX_DEPLOYMENT_TARGET=11.0 \
      "$venv/bin/python" -m build --wheel --outdir "$OUT" "$src/$NAME" >"$WORK/mac-$cp.log" 2>&1 || {
        tail -40 "$WORK/mac-$cp.log" >&2
        echo "REFUSED: the $cp macOS wheel did not build (log above)." >&2
        return 1
      }
    wheel="$OUT/$NAME-$cp-$cp-$MACOS_TAG.whl"
    if [ ! -f "$wheel" ]; then
      tail -5 "$WORK/mac-$cp.log" >&2
      echo "REFUSED: the $cp build did not produce $(basename "$wheel")." >&2
      return 1
    fi
    echo "  built $(basename "$wheel")  ($(wc -c <"$wheel" | tr -d ' ') bytes, $((SECONDS - start)) s, $("$py" -c 'import sys; print(sys.version.split()[0])'))"
  done
}

build_linux() {
  local docker start
  docker="$(command -v docker || true)"
  if [ -z "$docker" ] && [ -x /usr/local/bin/docker ]; then
    export PATH="/usr/local/bin:$PATH"; docker=/usr/local/bin/docker
  fi
  if [ -z "$docker" ] || ! "$docker" info >/dev/null 2>&1; then
    echo "REFUSED: Docker is not running (or not on PATH); the Linux wheels are built in its manylinux images." >&2
    return 1
  fi
  if [ ! -x "$CACHE/cibw/bin/cibuildwheel" ] || ! "$CACHE/cibw/bin/python" -m pip show cibuildwheel 2>/dev/null | grep -qx "Version: ${CIBUILDWHEEL_REQUIREMENT#*==}"; then
    rm -rf "$CACHE/cibw"
    "$REPO/.venv/bin/python" -m venv "$CACHE/cibw"
    "$CACHE/cibw/bin/python" -m pip install --quiet --disable-pip-version-check "$CIBUILDWHEEL_REQUIREMENT"
  fi
  start=$SECONDS
  # The test runs inside the image, in a fresh venv holding only the built wheel: it is the
  # cheapest place to refuse a wheel that built but would run the pure modules.
  env \
    CIBW_BUILD="cp311-* cp312-* cp313-* cp314-*" \
    CIBW_SKIP="*-musllinux_*" \
    CIBW_ARCHS_LINUX="aarch64 x86_64" \
    CIBW_ENVIRONMENT="BANTAMKIT_MYPYC=1" \
    CIBW_TEST_EXTRAS="mcp" \
    CIBW_TEST_COMMAND="python -c \"import bantamkit.mcpserver as m; c = m._compiled_build(); print(c); assert c.startswith('mypyc (') and c.endswith(' compiled, 1 interpreted)'), c\"" \
    "$CACHE/cibw/bin/cibuildwheel" --platform linux --output-dir "$OUT" "$SDIST" || {
      echo "REFUSED: cibuildwheel failed (its output is above)." >&2
      return 1
    }
  echo "  cibuildwheel built the Linux set in $((SECONDS - start)) s"
}

FAILED=0
if [ "$ONLY" != "linux" ]; then build_macos || FAILED=1; fi
if [ "$ONLY" != "macos" ]; then build_linux || FAILED=1; fi
[ "$FAILED" -eq 0 ] || exit 1

# Every name the matrix promises is there. (Extra files are publish.sh's to refuse: it owns OUT.)
MISSING=0
while IFS= read -r name; do
  if [ ! -f "$OUT/$name" ]; then
    echo "REFUSED: the matrix names $name and the build did not produce it." >&2
    MISSING=1
  fi
done < <(list_wheels "$VERSION")
exit "$MISSING"
