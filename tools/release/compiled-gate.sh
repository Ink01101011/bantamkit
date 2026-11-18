#!/usr/bin/env bash
#
# tools/release/compiled-gate.sh -- pytest and `--all` against the mypyc build, and proof that
# the compiled code is what ran (#316 G4, J90-RF2).
#
# WHY ONE COMMAND. CLAUDE.md requires a change that reaches `_generated/` to keep pytest and
# `node tools/conformance/run.mjs --all` green with the mypyc extensions beside the `.py` files.
# J90-PF and J90-PF2 reported that green from `PYTHONPATH=<compiled tree> node run.mjs --all`,
# and those runs were PURE: every reference script does `sys.path.insert(0, <checkout>/
# runtime-py/src)` first, which wins over PYTHONPATH, so the references loaded the checkout's
# `.py` files (J90-RR). This script cannot do that, and fails if it did:
#
#   1. a scratch worktree of REV (default HEAD; uncommitted changes are NOT in it), with its own
#      venv (`pip install -e "runtime-py[dev,mcp]"`) and its own Node build;
#   2. the compiled wheel: built from that worktree with BANTAMKIT_MYPYC=1 (runtime-py/
#      hatch_build.py, an isolated build with mypy 2.4.1), or the one --wheel names;
#   3. its extension modules unpacked into the WORKTREE's runtime-py/src at the paths the wheel
#      gives them: one per compiled module beside its `.py`, and mypyc's group library
#      `<hash>__mypyc.<suffix>` beside `bantamkit/`. The checkout under test IS the compiled tree,
#      so every `sys.path.insert` in a reference points at extensions;
#   4. before anything runs, a probe from an empty directory: `bantamkit` comes from the
#      worktree, every module of the compile set imports from an extension file, and
#      `build_identity` answers `mypyc (N compiled, 1 interpreted)`;
#   5. pytest (`runtime-py/tests`) and `--all`, in the worktree, with a load logger (a `.pth` file) in
#      the worktree venv that appends, at the exit of EVERY Python process on that interpreter, where
#      each loaded `bantamkit._generated` module came from;
#   6. after both: any compile-set module loaded from a `.py` under the worktree's runtime-py/src
#      fails the gate, and so does a run in which no process loaded a compiled module at all.
#      Modules loaded from elsewhere (a test's deliberate pure copy in a temp dir) are counted
#      and printed, not failed.
#
# HOME and USERPROFILE are a directory under the work dir for every step: no suite, test or
# build here reads or writes the operator's ~/.bantamkit, ~/.claude or caches. pip and npm caches
# default to the work dir too (set PIP_CACHE_DIR / npm_config_cache to reuse one). Rust: cargo is
# found through CARGO_HOME (default: the real ~/.cargo, read before HOME is switched), and
# RUSTUP_HOME likewise. The worktree is removed at the end unless --keep.
#
# USAGE
#   tools/release/compiled-gate.sh --python PY [--wheel WHL] [--rev REV] [--work DIR] [--keep]
#                                  [--only pytest|all]
#
#   --python   the interpreter to build and run on (a base interpreter or a venv's; 3.11-3.14)
#   --wheel    a compiled wheel for that interpreter, built earlier from the same REV
#   --only     run only pytest or only --all (the probe and the load check still run)
#
# Exit 0 only when the probe, pytest, --all and the load check all hold; 1 otherwise, with the
# reason. Docs: docs/porting.md, *The generated Python compiled with mypyc*, "The compiled gate".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHECK="$SCRIPT_DIR/compiled_gate.py"

PY="" WHEEL="" REV="HEAD" WORK="" KEEP=0 ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PY="$2"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --rev) REV="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    *) echo "compiled-gate.sh: unknown argument '$1' (see the header for usage)" >&2; exit 2 ;;
  esac
done
[ -n "$PY" ] || { echo "compiled-gate.sh: --python PY is required" >&2; exit 2; }
[ -x "$PY" ] || { echo "compiled-gate.sh: --python $PY is not an executable" >&2; exit 2; }
case "$ONLY" in ""|pytest|all) ;; *) echo "compiled-gate.sh: --only takes pytest or all" >&2; exit 2 ;; esac
if [ -n "$WHEEL" ]; then
  [ -f "$WHEEL" ] || { echo "compiled-gate.sh: --wheel $WHEEL does not exist" >&2; exit 2; }
  WHEEL="$(cd "$(dirname "$WHEEL")" && pwd)/$(basename "$WHEEL")"
fi

SHA="$(git -C "$REPO" rev-parse --verify "$REV^{commit}")"
if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
  echo "compiled-gate.sh: note: the checkout has uncommitted changes; the gate runs $SHA without them" >&2
fi

# Rust and caches are located BEFORE HOME moves.
export CARGO_HOME="${CARGO_HOME:-$HOME/.cargo}" RUSTUP_HOME="${RUSTUP_HOME:-$HOME/.rustup}"
export PATH="$CARGO_HOME/bin:$PATH"
[ -n "${TS2PY_CARGO:-}" ] || { [ -x "$CARGO_HOME/bin/cargo" ] && export TS2PY_CARGO="$CARGO_HOME/bin/cargo"; } || true

if [ -z "$WORK" ]; then WORK="$(mktemp -d "${TMPDIR:-/tmp}/bk-compiled-gate-XXXXXX")"; fi
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd -P)"
WT="$WORK/wt"
LOGS="$WORK/logs"
mkdir -p "$LOGS" "$WORK/home" "$WORK/empty"
export HOME="$WORK/home" USERPROFILE="$WORK/home"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$WORK/cache/pip}" npm_config_cache="${npm_config_cache:-$WORK/cache/npm}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
unset PYTHONPATH

cleanup() {
  if [ "$KEEP" = 0 ] && [ -d "$WT" ]; then
    git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

step() { echo "== $(date +%H:%M:%S) $*"; }
fail() { echo "compiled-gate.sh: FAIL: $*" >&2; exit 1; }

step "worktree $SHA at $WT"
[ ! -e "$WT" ] || fail "$WT already exists (pass a fresh --work)"
git -C "$REPO" worktree add --detach "$WT" "$SHA" >"$LOGS/worktree.log" 2>&1 || fail "git worktree add (see $LOGS/worktree.log)"

step "venv on $("$PY" -c 'import sys; print(sys.version.split()[0])') and the editable install"
"$PY" -m venv "$WT/.venv"
VPY="$WT/.venv/bin/python"
"$VPY" -m pip install -q -e "$WT/runtime-py[dev,mcp]" >"$LOGS/venv.log" 2>&1 || fail "pip install -e (see $LOGS/venv.log)"

if [ -z "$WHEEL" ]; then
  step "building the compiled wheel (BANTAMKIT_MYPYC=1)"
  BANTAMKIT_MYPYC=1 "$VPY" -m pip wheel -q --no-deps -w "$WORK/dist" "$WT/runtime-py" >"$LOGS/wheel.log" 2>&1 \
    || fail "the compiled wheel did not build (see $LOGS/wheel.log)"
  WHEEL="$(find "$WORK/dist" -name 'bantamkit-*.whl' | head -1)"
  [ -n "$WHEEL" ] || fail "no wheel in $WORK/dist"
fi
echo "   wheel: $WHEEL"

step "unpacking its extensions into the worktree"
"$VPY" "$CHECK" unpack "$WHEEL" "$WT/runtime-py/src" || fail "the wheel is not a compiled build of $SHA for this interpreter"

step "Node build"
(cd "$WT/runtime-ts" && npm ci --no-audit --no-fund >"$LOGS/npm-ci.log" 2>&1 && npm run build >"$LOGS/npm-build.log" 2>&1) \
  || fail "the Node build failed (see $LOGS/npm-*.log)"

step "probe: the modules under test load from extension files"
(cd "$WORK/empty" && env BANTAMKIT_RETENTION=off BANTAMKIT_SKILL_AUDIT=off BANTAMKIT_SKILL_AUTO=off \
  "$VPY" "$CHECK" probe "$WT/runtime-py/src") || fail "the probe found modules under test that are not extensions"

# The load log: every Python process on the worktree venv's interpreter records, at exit, where
# its `bantamkit._generated` modules came from. Written into the venv, so no environment variable
# is needed and a suite that scrubs its children's environment is still recorded.
LOADLOG="$WORK/loads.jsonl"
: >"$LOADLOG"
"$VPY" "$CHECK" logger "$LOADLOG" || fail "could not install the load logger"

STATUS=0
if [ "$ONLY" != all ]; then
  step "pytest runtime-py/tests (log: $LOGS/pytest.log)"
  if (cd "$WT" && "$VPY" -m pytest runtime-py/tests -q -p no:cacheprovider >"$LOGS/pytest.log" 2>&1); then :; else STATUS=1; fi
  echo "   $(tail -n 1 "$LOGS/pytest.log")"
fi
if [ "$ONLY" != pytest ]; then
  step "node tools/conformance/run.mjs --all (log: $LOGS/all.log)"
  if (cd "$WT" && node tools/conformance/run.mjs --all --python "$VPY" >"$LOGS/all.log" 2>&1); then :; else STATUS=1; fi
  echo "   $(grep -E '^(PASS|FAIL):' "$LOGS/all.log" | tail -n 1 || echo 'no PASS/FAIL line')"
fi

step "load check over $(wc -l <"$LOADLOG" | tr -d ' ') recorded processes"
"$VPY" "$CHECK" loads "$LOADLOG" "$WT/runtime-py/src" || STATUS=1

if [ "$STATUS" = 0 ]; then
  echo "compiled-gate.sh: PASS ($SHA, $("$VPY" -c 'import sys; print(sys.version.split()[0])'), logs in $LOGS)"
else
  echo "compiled-gate.sh: FAIL ($SHA; logs in $LOGS)" >&2
fi
exit "$STATUS"
