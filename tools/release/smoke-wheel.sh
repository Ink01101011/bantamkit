#!/usr/bin/env bash
#
# tools/release/smoke-wheel.sh -- install ONE built wheel into a clean venv and run it (#316 G4).
#
# publish.sh's phase 3 calls this once per wheel it is about to upload. Each wheel is installed,
# with the [mcp] extra, into a fresh venv on the interpreter and platform its tag names, and then:
#
#   1. imported in isolated mode (`python -I`, from an empty directory, so neither PYTHONPATH nor
#      a checkout can supply the code) and asked `build_identity`'s `compiled` field: a platform
#      wheel must answer `mypyc (N compiled, 1 interpreted)` with every compiled module's file
#      inside that venv, and the pure wheel `none (0 compiled, N interpreted)`;
#   2. driven over real stdio by roster-probe.mjs, which must see the roster MCP_TOOLS declares.
#
# WHERE EACH WHEEL RUNS
#   py3-none-any          the repo venv's interpreter, on this machine
#   macosx_11_0_arm64     the uv-managed CPython build-wheels.sh built it with (same cache)
#   manylinux_*_<arch>    the manylinux_2_28 image cibuildwheel built it in (its pinned digest),
#                         under local Docker
#                         (`--platform linux/amd64` for x86_64), server and all
#
# USAGE   tools/release/smoke-wheel.sh WHEEL
# Exit 0 when both checks hold; 1 otherwise, with the reason on stderr.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
CACHE="${BANTAMKIT_WHEEL_CACHE:-$REPO/.release/cache}"
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: smoke-wheel.sh WHEEL (an existing .whl)" >&2; exit 2; }
WHEEL="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
NAME="$(basename "$WHEEL")"

# bantamkit-<version>-<python>-<abi>-<platform>.whl
IFS=- read -r _dist _version PYTAG _abi PLATFORM <<<"${NAME%.whl}"
case "$PLATFORM" in
  any) WHERE=host; EXPECT=none ;;
  macosx_*_arm64) WHERE=host; EXPECT=mypyc ;;
  manylinux*_x86_64) WHERE=docker; EXPECT=mypyc; ARCH=x86_64; DPLAT=linux/amd64 ;;
  manylinux*_aarch64) WHERE=docker; EXPECT=mypyc; ARCH=aarch64; DPLAT=linux/arm64 ;;
  *) echo "smoke-wheel.sh: no rule for platform '$PLATFORM' in $NAME" >&2; exit 2 ;;
esac

WORK="$(mktemp -d "${TMPDIR:-/tmp}/bk-smoke-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
cp "$WHEEL" "$WORK/$NAME"
mkdir -p "$WORK/empty"

# Run inside the venv from an empty directory. Prints the field and where the code came from,
# and refuses a build that is not the one the tag promises.
cat >"$WORK/check.py" <<'PY'
import importlib, pathlib, sys, sysconfig
from importlib.machinery import EXTENSION_SUFFIXES

expect = sys.argv[1]
import bantamkit
import bantamkit.mcpserver as server

site = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
platsite = pathlib.Path(sysconfig.get_paths()["platlib"]).resolve()
root = pathlib.Path(bantamkit.__file__).resolve()
assert root.is_relative_to(site) or root.is_relative_to(platsite), f"bantamkit imported from {root}, not the venv"
compiled = server.build_identity()["compiled"]
gen = root.parent / "_generated"
stems = sorted(p.stem for p in gen.glob("*.py") if p.stem != "__init__")
files = {s: importlib.import_module(f"bantamkit._generated.{s}").__file__ for s in stems}
ext = sorted(s for s, f in files.items() if f.endswith(tuple(EXTENSION_SUFFIXES)))
print(f"compiled field : {compiled}")
print(f"bantamkit      : {root}")
print(f"store module   : {files['store']}")
if expect == "mypyc":
    assert compiled == f"mypyc ({len(stems) - 1} compiled, 1 interpreted)", compiled
    assert ext == sorted(s for s in stems if s != "_ts2py_adapters"), ext
    assert all(pathlib.Path(files[s]).resolve().is_relative_to(platsite) for s in ext)
else:
    assert compiled == f"none (0 compiled, {len(stems)} interpreted)", compiled
    assert not ext, ext
print(f"ok: {expect}")
PY

ENVS=(BANTAMKIT_RETENTION=off BANTAMKIT_SKILL_AUDIT=off BANTAMKIT_SKILL_AUTO=off)

if [ "$WHERE" = host ]; then
  if [ "$PLATFORM" = any ]; then
    PY="$REPO/.venv/bin/python"
  else
    v="${PYTAG#cp}"; v="${v:0:1}.${v:1}"
    PY="$(env UV_PYTHON_INSTALL_DIR="$CACHE/pythons" "${UV:-uv}" python find --no-config --managed-python "$v")"
  fi
  "$PY" -m venv "$WORK/venv"
  "$WORK/venv/bin/python" -m pip install --quiet --disable-pip-version-check "$WORK/$NAME[mcp]"
  (cd "$WORK/empty" && env "${ENVS[@]}" "$WORK/venv/bin/python" -I "$WORK/check.py" "$EXPECT")
  env "${ENVS[@]}" node "$SCRIPT_DIR/roster-probe.mjs" --label "$NAME" -- "$WORK/venv/bin/bantamkit-mcp"
else
  DOCKER="$(command -v docker || echo /usr/local/bin/docker)"
  # The exact image cibuildwheel built the wheel in: its pinned digest, read from the cibuildwheel
  # build-wheels.sh installed, so this is never a second, newer pull of a moving tag.
  CFG="$(find "$CACHE/cibw/lib" -name pinned_docker_images.cfg 2>/dev/null | head -1)"
  IMAGE="$(awk -v a="[$ARCH]" '$0==a{on=1;next} /^\[/{on=0} on && $1=="manylinux_2_28"{print $3}' "${CFG:-/dev/null}")"
  [ -n "$IMAGE" ] || { echo "smoke-wheel.sh: no pinned manylinux_2_28 $ARCH image under $CACHE/cibw (run build-wheels.sh first)" >&2; exit 1; }
  PYBIN="/opt/python/$PYTAG-$PYTAG/bin/python"
  DENV=()
  for e in "${ENVS[@]}"; do DENV+=(-e "$e"); done
  "$DOCKER" run --rm --platform "$DPLAT" -v "$WORK:/w" "${DENV[@]}" "$IMAGE" sh -ec "
    $PYBIN -m venv /w/venv
    /w/venv/bin/python -m pip install --quiet --disable-pip-version-check '/w/$NAME[mcp]'
    cd /w/empty && /w/venv/bin/python -I /w/check.py $EXPECT"
  node "$SCRIPT_DIR/roster-probe.mjs" --label "$NAME (in $IMAGE)" --timeout-ms 300000 -- \
    "$DOCKER" run -i --rm --platform "$DPLAT" -v "$WORK:/w" "${DENV[@]}" -w /w/empty "$IMAGE" /w/venv/bin/bantamkit-mcp
fi
