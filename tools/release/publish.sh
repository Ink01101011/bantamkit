#!/usr/bin/env bash
#
# bantamkit release pipeline: test -> build -> prepublish -> npm -> PyPI, in one command.
#
# WHY THIS FILE EXISTS. Every release here has been a sequence of hand-typed commands read
# out of two documents, and job56 is what that costs. (served-tools: dated — the counts in
# this sentence are what the two PUBLISHED 0.35.0 artifacts answered on 2026-09-19, not what
# this checkout serves.) `bantamkit-mcp@0.35.0` went to npm advertising 12 tools where its own
# source declares 14, while `bantamkit==0.35.0` on PyPI served all 14 — one number, two
# registries, two different answers, and nothing in the procedure compared them. That was not
# a bug in either runtime. It was a procedure with no gate on it.
#
# The other way a hand-run release goes wrong is that it stops halfway, and this repository
# has done that too: npm carries 0.26.0 (published 2026-09-05) and PyPI has never carried it
# at all — its history starts at 0.27.0. One registry moved and the other did not, and the
# only record of it is the gap in the version list. Hence the resume rule below.
#
# WHAT IT REFUSES TO DO. It never publishes anything it has not first built, gated and driven
# over real stdio, and every check that CAN run before the first upload DOES, because a
# publish cannot be undone. npm forbids republishing a version outright; PyPI does the same.
# So the ordering of the phases below is a safety property, not a style.
#
# RESUMABLE. Before anything is built, both registries are asked what they already carry. A
# version already published is SKIPPED, never republished — npm forbids republishing a version
# anyway, so skipping is the only correct behaviour and not a convenience. That is what lets a
# half-done release (0.26.0's shape: npm landed, PyPI did not) be finished by rerunning this
# script with no arguments and no flags to remember.
#
# AUTHENTICATION, AND WHY THERE IS NO SECRET IN THIS FILE.
#   npm   plain `npm publish --access public`, with NO --otp. npm answers with a callback URL
#         that you open in a browser and authenticate there. That flow reads no stdin, so it
#         does not need a TTY -- but it DOES need to reach your eyes, which is why npm's
#         output is streamed straight to this script's stdout and stderr: never captured,
#         never piped, never wrapped. (USER'S RULING, 2026-09-19.)
#   PyPI  `twine upload` reads its token from ~/.pypirc or from TWINE_PASSWORD. Preflight
#         REFUSES when neither is present, rather than letting twine reach an interactive
#         prompt from a context that may not be able to answer one.
# No token, no OTP and no placeholder that could be mistaken for either appears anywhere in
# this file, deliberately.
#
# USAGE
#   tools/release/publish.sh [--dry-run] [--yes] [--out-dir DIR] [--help]
#
#   --dry-run   run phases 0-3 (preflight, test, build, prepublish) and STOP before the first
#               publish. Nothing leaves the machine. Exit 0 means: this tree is publishable.
#   --yes       skip the interactive confirmation before the first publish. Without it and
#               without a TTY, the script refuses rather than publishing unattended.
#   --out-dir   where the artifacts are built (default `<repo>/.release/<version>`). The
#               directory is named for the version and emptied first, because
#               `python -m build` does not clean its output directory and `twine check`
#               reports PASSED on a stale wheel sitting beside a current one -- measured in
#               job56, with three sibling `runtime-py/dist*/` directories holding six
#               artifacts, not one of them the version being released. Nothing here ever
#               globs; every artifact is named in full.
#
# WHAT IT DOES NOT DO: it does not tag, it does not create a GitHub release, and it does not
# write release notes. Those are decisions, and the summary at the end says so.

set -euo pipefail

# --------------------------------------------------------------------------------- setup

# npm exports npm_config_dry_run=true into anything it spawns under --dry-run, and npm reads
# its own configuration back out of npm_config_*. Inherited, it silently turns a child
# `npm pack` into a dry run that exits 0, prints a tarball name and writes NO FILE -- measured
# in job56 (J56-3), where it produced a TypeError instead of a verdict on a healthy tree.
# Nothing in this pipeline should ever become a dry run by inheritance: --dry-run here means
# "stop before publishing", which is a decision this script makes and not a flag it passes on.
unset npm_config_dry_run || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"

DRY_RUN=0
ASSUME_YES=0
OUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    # `--out-dir` with nothing after it used to die SILENTLY: the `shift` in this case arm
    # consumed the flag, the loop's own `shift` then ran with $# = 0, returned 1, and `set -e`
    # exited the script with no output at all — exit 1 and not one word about why. Measured
    # 2026-09-19 (J56-6): `publish.sh --out-dir` printed nothing. Same class as the five
    # `[ cond ] && action` lines J56-7 found; this is the sixth.
    --out-dir)
      if [ $# -lt 2 ]; then
        printf 'publish.sh: --out-dir needs a directory after it (try --help)\n' >&2
        exit 2
      fi
      shift; OUT_DIR="$1"
      ;;
    # The header IS the help text, printed from line 2 up to the first line that is not a
    # comment — a line range would need re-counting every time a paragraph gains a clause.
    --help|-h) awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf 'publish.sh: unknown argument: %s (try --help)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

say()   { printf '%s\n' "$*"; }
phase() { printf '\n======== %s ========\n' "$*"; }
ok()    { printf '  ok      %s\n' "$*"; }
note()  { printf '  note    %s\n' "$*"; }
bad()   { printf '  FAILED  %s\n' "$*" >&2; }
die()   { printf '\nREFUSED: %s\n' "$*" >&2; exit 1; }

PROBLEM_COUNT=0
problem() { PROBLEM_COUNT=$((PROBLEM_COUNT + 1)); bad "$1"; }

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/bk-release-XXXXXX")"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

VENV_PY="$REPO/.venv/bin/python"
RUFF="$REPO/.venv/bin/ruff"

say "bantamkit release pipeline"
say "  repo     : $REPO"
say "  commit   : $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '(not a git checkout)')"
say "  branch   : $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
if [ "$DRY_RUN" -eq 1 ]; then
  say "  mode     : --dry-run (phases 0-3; nothing is published)"
else
  say "  mode     : LIVE (a successful run publishes to npm and PyPI)"
fi

# ============================================================== phase 0: preflight
#
# Everything that can be known before anything is built. It all runs; the refusal at the end
# names every problem at once, because finding out about the second one on the next run is how
# a release takes an afternoon.

phase "phase 0/8  preflight -- refuse rather than proceed"

# `.git` is a DIRECTORY in an ordinary clone and a FILE in a git worktree. Testing for the
# directory therefore answers "not a checkout" inside every worktree — and it did, measured on
# this script's own rig, where it ALSO silently skipped the uncommitted-changes check that was
# guarded by it. Ask git what it thinks instead of guessing from the filesystem.
IS_GIT=0
if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IS_GIT=1
else
  problem "$REPO is not a git checkout, so nothing here can say which commit is being released."
fi

# --- the version, from the one declaration that is authoritative --------------------------
# runtime-py/src/bantamkit/__init__.py is THE version site: pyproject.toml is
# dynamic = ["version"] and names that file as its source, so the string there is the wheel's
# metadata AND what the running server advertises. Every other declaration follows it.
VERSION="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$REPO/runtime-py/src/bantamkit/__init__.py" | head -1 || true)"
if [ -z "$VERSION" ]; then
  die "cannot read __version__ from runtime-py/src/bantamkit/__init__.py."
fi
say "  version  : $VERSION  (from runtime-py/src/bantamkit/__init__.py)"

PKG_VERSION="$(node -p "require('$REPO/runtime-ts/package.json').version" 2>/dev/null || true)"
LOCK_VERSION="$(node -p "require('$REPO/runtime-ts/package-lock.json').version" 2>/dev/null || true)"
LOCK_ROOT_VERSION="$(node -p "require('$REPO/runtime-ts/package-lock.json').packages[''].version" 2>/dev/null || true)"

check_site() { # label, value
  if [ "${2:-}" != "$VERSION" ]; then
    problem "version site disagrees: $1 says '${2:-(unreadable)}', __init__.py says '$VERSION'."
  else
    ok "$1 = $VERSION"
  fi
}
check_site "runtime-ts/package.json" "$PKG_VERSION"
check_site "runtime-ts/package-lock.json .version" "$LOCK_VERSION"
check_site "runtime-ts/package-lock.json .packages[''].version" "$LOCK_ROOT_VERSION"

# The offline-wheelhouse block in runtime-py/README.md is an INSTRUCTION -- copy this, get a
# working install -- so it is a version site too, and it has been moved at every release since
# 0.34.3. A pin there that is not this version is a site left behind. (A version literal that
# REPORTS what some artifact did on a date is a historical record, not a site, and is
# deliberately not checked here.)
README_PINS="$(grep -oE 'bantamkit\[mcp\]==[0-9]+\.[0-9]+\.[0-9]+' "$REPO/runtime-py/README.md" | sed 's/.*==//' | sort -u | tr '\n' ' ' | sed 's/ *$//' || true)"
if [ -z "$README_PINS" ]; then
  note "runtime-py/README.md carries no wheelhouse pin to check."
elif [ "$README_PINS" != "$VERSION" ]; then
  problem "runtime-py/README.md wheelhouse pin(s) '$README_PINS' != $VERSION."
else
  ok "runtime-py/README.md wheelhouse pin = $VERSION"
fi

# --- the tree ------------------------------------------------------------------------------
# Tracked modifications refuse; untracked files only warn. A release is built from what is
# committed, and an untracked scratch directory is in neither artifact -- refusing on it would
# teach people to pass a --force nobody should have.
if [ "$IS_GIT" -eq 1 ]; then
  DIRTY="$(git -C "$REPO" status --porcelain --untracked-files=no || true)"
  if [ -n "$DIRTY" ]; then
    problem "the working tree has uncommitted changes to tracked files:"
    printf '%s\n' "$DIRTY" | sed 's/^/            /' >&2
    # PHASE 1 DIRTIES THIS FILE ITSELF. The shiftwork suites APPEND to the tracked log
    # `tools/shiftwork/example-codefix-checkpoint.json.log.jsonl`, so a completed run leaves
    # the tree dirty and the NEXT run — the resume, the whole point of this script — refuses
    # on a file the script's own gates wrote. It is still a refusal, because a cleanliness
    # check with a quiet exception is a check nobody can trust. What it gets instead is the
    # remedy, named, so the rerun is one command away. (The file is in neither artifact:
    # npm packs `dist` and `assets`, the wheel packs `src/bantamkit` and its asset pack.)
    ONLY_GATE_LOG="$(printf '%s\n' "$DIRTY" | grep -vE '^ ?M tools/shiftwork/[^ ]*\.log\.jsonl$' || true)"
    if [ -z "$ONLY_GATE_LOG" ]; then
      printf '            ^ that is the append-only log phase 1 writes, and nothing else.\n' >&2
      printf '              It ships in neither artifact. Commit it, or reset it and rerun:\n' >&2
      printf '                git -C %s checkout -- tools/shiftwork/\n' "$REPO" >&2
    fi
  else
    ok "working tree clean (tracked files)"
  fi
  UNTRACKED="$(git -C "$REPO" ls-files --others --exclude-standard | head -5 || true)"
  if [ -n "$UNTRACKED" ]; then
    note "untracked files present (shipped by nothing, not a refusal): $(printf '%s' "$UNTRACKED" | tr '\n' ' ')"
  fi
fi

# --- the toolchain ---------------------------------------------------------------------------
need_cmd() { # label, command
  if command -v "$2" >/dev/null 2>&1; then
    ok "$1: $(command -v "$2")"
  else
    problem "$1 not found: $2"
  fi
}
need_cmd "node" node
need_cmd "npm" npm
need_cmd "git" git
need_cmd "curl" curl

if [ -x "$VENV_PY" ]; then
  ok "repo venv python: $VENV_PY"
else
  problem "the repo venv python is missing: $VENV_PY (runtime-py has no venv of its own)."
fi
if [ -x "$RUFF" ]; then
  ok "ruff: $RUFF"
else
  problem "ruff is missing: $RUFF"
fi
if [ -x "$VENV_PY" ] && ! "$VENV_PY" -c 'import build' >/dev/null 2>&1; then
  problem "the repo venv cannot 'import build'; the Python artifact cannot be built."
fi

TWINE=""
for candidate in "$REPO/.venv/bin/twine" "$HOME/.local/bin/twine"; do
  if [ -z "$TWINE" ] && [ -x "$candidate" ]; then TWINE="$candidate"; fi
done
if [ -z "$TWINE" ] && command -v twine >/dev/null 2>&1; then TWINE="$(command -v twine)"; fi
if [ -n "$TWINE" ]; then
  ok "twine: $TWINE"
else
  problem "twine not found (looked in .venv/bin, ~/.local/bin, PATH)."
fi

# --- the PyPI credential, checked for EXISTENCE and never read or printed ---------------------
# twine with no credential falls through to an interactive prompt. A prompt reached from a
# context that cannot answer one is a release that hangs AFTER npm has already published,
# which is the worst half-state available. So this is a refusal, in preflight, before anything
# is built.
#
# `TWINE_API_KEY` IS NOT A TWINE VARIABLE, and this check used to accept it as proof of a
# credential. MEASURED 2026-09-19 (J56-6) against the twine in this repo's venv (7.0.0): the
# only environment variables it reads are TWINE_USERNAME, TWINE_PASSWORD, TWINE_REPOSITORY,
# TWINE_REPOSITORY_URL, TWINE_CERT and TWINE_NON_INTERACTIVE. So an operator who exported
# TWINE_API_KEY and had no ~/.pypirc got `ok` here and a PROMPT in phase 6 — after npm had
# already published, which is precisely the half-state this block exists to prevent. A
# false green in a preflight is worse than no preflight.
if [ -n "${TWINE_PASSWORD:-}" ]; then
  ok "PyPI credential: TWINE_PASSWORD is set in the environment"
elif [ -f "$HOME/.pypirc" ] && grep -q '^\[pypi\]' "$HOME/.pypirc" && grep -qE '^[[:space:]]*password[[:space:]]*=' "$HOME/.pypirc"; then
  ok "PyPI credential: ~/.pypirc carries a [pypi] password (existence only; not read, not printed)"
else
  problem "no PyPI credential: ~/.pypirc has no [pypi] password and TWINE_PASSWORD is unset -- twine would reach a prompt."
  if [ -n "${TWINE_API_KEY:-}" ]; then
    printf '            ^ TWINE_API_KEY is set, and twine does not read it. Export the token as\n' >&2
    printf '              TWINE_PASSWORD (with TWINE_USERNAME=__token__), or put it in ~/.pypirc.\n' >&2
  fi
fi

# --- npm auth ----------------------------------------------------------------------------------
NPM_USER="$(npm whoami 2>/dev/null || true)"
if [ -n "$NPM_USER" ]; then
  ok "npm account: $NPM_USER"
else
  problem "npm whoami failed -- run 'npm login' first; a publish from here would be rejected."
fi

# --- what the registries already carry: this is what makes the script resumable -----------------
REGISTRY_ANSWER=""
registry_state() { # url, label -> sets REGISTRY_ANSWER to yes|no, or refuses outright
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$1" 2>/dev/null || true)"
  case "$code" in
    200) REGISTRY_ANSWER="yes" ;;
    404) REGISTRY_ANSWER="no" ;;
    *)
      die "$2 answered HTTP '${code:-000}' for $1.
         An unreadable registry is not the same as an unpublished version, and guessing which
         it is would either skip a publish that never happened or repeat one that did."
      ;;
  esac
}

# registry.npmjs.org is asked DIRECTLY rather than through `npm view`, which answers out of a
# metadata cache that lags a publish by minutes.
registry_state "https://registry.npmjs.org/bantamkit-mcp/$VERSION" "npm"
NPM_ALREADY="$REGISTRY_ANSWER"
# The PER-VERSION PyPI endpoint. The plain /pypi/<name>/json "latest" view and the simple index
# are both CDN-cached and lag; this one answers 404 until the version exists.
registry_state "https://pypi.org/pypi/bantamkit/$VERSION/json" "PyPI"
PYPI_ALREADY="$REGISTRY_ANSWER"

if [ "$NPM_ALREADY" = "yes" ]; then
  note "npm ALREADY carries bantamkit-mcp@$VERSION -- it will be verified, never republished."
else
  ok "npm does not yet carry bantamkit-mcp@$VERSION"
fi
if [ "$PYPI_ALREADY" = "yes" ]; then
  note "PyPI ALREADY carries bantamkit==$VERSION -- it will be verified, never re-uploaded."
else
  ok "PyPI does not yet carry bantamkit==$VERSION"
fi

if [ "$PROBLEM_COUNT" -gt 0 ]; then
  die "preflight found $PROBLEM_COUNT problem(s), each named above.
         Nothing has been built and nothing has been published. Fix them and rerun."
fi
ok "preflight clean"

# ============================================================== phase 1: test
#
# The four gates this repository runs, all of them, every time. ZERO FAILURES is the bar -- a
# pass count is a function of repo content and is never an expectation. All four run even after
# one fails, so a single run tells you everything that is wrong.

phase "phase 1/8  test -- the four gates (0 failures is the bar)"

GATE_FAILED=0
GATE_FAILED_NAMES=""
gate() { # label, then the command
  local label="$1"; shift
  say "  --- $label"
  if "$@"; then
    ok "$label"
  else
    GATE_FAILED=$((GATE_FAILED + 1))
    GATE_FAILED_NAMES="$GATE_FAILED_NAMES
           - $label"
    bad "$label"
  fi
}
gate "pytest runtime-py/tests" "$VENV_PY" -m pytest "$REPO/runtime-py/tests" -q
gate "ruff check runtime-py tools" "$RUFF" check "$REPO/runtime-py" "$REPO/tools"
gate "npm test (runtime-ts)" bash -c "cd '$REPO/runtime-ts' && npm test"
gate "conformance --all" node "$REPO/tools/conformance/run.mjs" --all

if [ "$GATE_FAILED" -gt 0 ]; then
  die "$GATE_FAILED gate(s) failed:$GATE_FAILED_NAMES
         Nothing has been built and nothing has been published."
fi

# ============================================================== phase 2: build
#
# Into a CLEAN directory named for the version. Never a reused one, never a glob.
# `python -m build` does not clean its output directory, `twine check` reports PASSED on a
# stale wheel, and this checkout carries three sibling runtime-py/dist*/ directories whose six
# artifacts are all older releases. A pipeline that globbed any of that would upload the wrong
# version under a green check.

phase "phase 2/8  build -- both artifacts, into a clean directory named for $VERSION"

if [ -z "$OUT_DIR" ]; then OUT_DIR="$REPO/.release/$VERSION"; fi
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/npm" "$OUT_DIR/pypi"
say "  output   : $OUT_DIR"

say "  --- npm pack (its prepack runs build-for-pack.mjs, then sync-assets)"
( cd "$REPO/runtime-ts" && npm pack --pack-destination "$OUT_DIR/npm" ) || die "npm pack failed."

say "  --- python -m build (wheel + sdist)"
"$VENV_PY" -m build --no-isolation --outdir "$OUT_DIR/pypi" "$REPO/runtime-py" || die "python -m build failed."

TGZ="$OUT_DIR/npm/bantamkit-mcp-$VERSION.tgz"
WHEEL="$OUT_DIR/pypi/bantamkit-$VERSION-py3-none-any.whl"
SDIST="$OUT_DIR/pypi/bantamkit-$VERSION.tar.gz"

for artifact in "$TGZ" "$WHEEL" "$SDIST"; do
  if [ ! -f "$artifact" ]; then
    die "the build did not produce $artifact.
         Every upload below names its file in full, so a missing one is a stop, not a glob."
  fi
  ok "built $(basename "$artifact")  ($(wc -c < "$artifact" | tr -d ' ') bytes)"
done

# A directory holding anything BUT those three files is a directory that accumulated, and
# accumulation is the defect. Refuse rather than pick.
EXTRAS="$(find "$OUT_DIR" -type f ! -path "$TGZ" ! -path "$WHEEL" ! -path "$SDIST" | head -20 || true)"
if [ -n "$EXTRAS" ]; then
  die "unexpected files in $OUT_DIR:
$(printf '%s' "$EXTRAS" | sed 's/^/           /')"
fi

# ============================================================== phase 3: prepublish
#
# The checks that ask the BUILT ARTIFACT what it contains and what it answers. No local test
# can do this: every local path reads the checkout, and the checkout always agrees with itself.

phase "phase 3/8  prepublish -- what the artifacts actually contain and serve"

say "  --- npx cold start (a real npm pack, installed through npx, driven over stdio)"
node "$REPO/tools/conformance/npx-cold-start.mjs" || die "the npx cold-start gate failed. Nothing has been published."
ok "npx cold start: 0 failed checks"

# The asset pack, BY BYTES. Both packaging gates compare asset NAMES, and job56 measured a pack
# with the right names and the wrong bytes going all the way through a green build, a green
# packaging gate and an installed server that advertised a description and an input schema no
# commit carries -- silently. Names are not enough.
say "  --- asset pack inside each artifact, byte for byte against $REPO/assets"
"$VENV_PY" "$SCRIPT_DIR/check-asset-pack.py" "$TGZ" "package/assets" "$REPO/assets" \
  --also "package/LICENSE=LICENSE" || die "the npm tarball's asset pack disagrees with the checkout."
"$VENV_PY" "$SCRIPT_DIR/check-asset-pack.py" "$WHEEL" "bantamkit/assets" "$REPO/assets" \
  || die "the wheel's asset pack disagrees with the checkout."
"$VENV_PY" "$SCRIPT_DIR/check-asset-pack.py" "$SDIST" "bantamkit-$VERSION/_assets" "$REPO/assets" \
  || die "the sdist's asset pack disagrees with the checkout."

say "  --- twine check, by exact filename"
"$TWINE" check "$WHEEL" "$SDIST" || die "twine check failed."
note "twine check validates METADATA, not currency: it reports PASSED on a stale wheel. The"
note "byte-for-byte check above is what makes currency a measured property here."

if [ "$DRY_RUN" -eq 1 ]; then
  phase "--dry-run: stopping before the first publish"
  say "  This tree is publishable: built, gated and checked, and nothing left the machine."
  say "  artifacts     : $OUT_DIR"
  if [ "$NPM_ALREADY" = "yes" ]; then
    say "  would do  npm : SKIP, the registry already carries bantamkit-mcp@$VERSION"
  else
    say "  would do  npm : publish bantamkit-mcp@$VERSION"
  fi
  if [ "$PYPI_ALREADY" = "yes" ]; then
    say "  would do PyPI : SKIP, PyPI already carries bantamkit==$VERSION"
  else
    say "  would do PyPI : upload bantamkit==$VERSION"
  fi
  say "  rerun without --dry-run to publish."
  exit 0
fi

# ============================================================== phase 4: publish npm
#
# THE CONFIRMATION. Everything above this line is reversible. Nothing below it is.

if [ "$NPM_ALREADY" = "no" ] || [ "$PYPI_ALREADY" = "no" ]; then
  if [ "$ASSUME_YES" -eq 1 ]; then
    note "--yes given; publishing without asking."
  elif [ -t 0 ]; then
    printf '\nAbout to publish bantamkit %s. This cannot be undone.\n' "$VERSION"
    if [ "$NPM_ALREADY" = "yes" ]; then
      printf '  npm  : skip (already published)\n'
    else
      printf '  npm  : publish bantamkit-mcp@%s as %s\n' "$VERSION" "$NPM_USER"
    fi
    if [ "$PYPI_ALREADY" = "yes" ]; then
      printf '  PyPI : skip (already published)\n'
    else
      printf '  PyPI : upload bantamkit==%s\n' "$VERSION"
    fi
    printf 'Type the version to confirm: '
    read -r CONFIRM
    if [ "$CONFIRM" != "$VERSION" ]; then
      die "confirmation did not match '$VERSION'. Nothing has been published."
    fi
  else
    die "stdin is not a terminal and --yes was not given, so the confirmation cannot be
         answered. Rerun from a terminal, or pass --yes if you mean it."
  fi
fi

phase "phase 4/8  publish npm"

if [ "$NPM_ALREADY" = "yes" ]; then
  note "SKIPPED: the registry already carries bantamkit-mcp@$VERSION."
  note "npm forbids republishing a version, so skipping is the only correct behaviour here --"
  note "not a convenience, and it is what lets a half-done release be finished by rerunning."
else
  say '  npm publish --access public, with NO --otp.'
  say '  npm answers with a CALLBACK URL to open in a browser. Its output is streamed'
  say '  straight through below: nothing here captures, buffers or wraps it.'
  say ''
  # No pipe, no capture, no wrapper: stdout and stderr are this script's own, unbuffered by
  # anything we control, so the callback URL reaches the person running this.
  if ( cd "$REPO/runtime-ts" && npm publish --access public ); then
    ok "npm publish returned 0"
  else
    # A NON-ZERO npm publish IS NOT PROOF THAT NOTHING WAS PUBLISHED (0.35.6, 2026-09-26).
    # The registry stamped bantamkit-mcp@0.35.6 at 13:20:32Z with this run's own tarball, and
    # npm then printed "You cannot publish over the previously published versions: 0.35.6"
    # and exited 1 -- its own second PUT, after the browser authentication, colliding with
    # its first. This script stopped there and PyPI was not uploaded, so the release sat
    # half-done until a rerun. So the registry decides, not npm's exit code: when it carries
    # this version AND its dist.shasum is the sha1 of the tarball built above, the publish
    # happened and this run carries on to phase 5, which verifies it by running it. A version
    # the registry carries with ANY other shasum is someone else's artifact and a stop.
    # `npm pack` is deterministic for the same tree -- measured: the 0.35.6 phase-2 tarball
    # and the registry's copy are both sha1 5d376813f2c8fadba24bd3312b7d365c08f67865.
    say ''
    note "npm publish exited non-zero. Asking the registry whether it published anyway."
    LOCAL_SHA1="$(node -e 'process.stdout.write(require("crypto").createHash("sha1").update(require("fs").readFileSync(process.argv[1])).digest("hex"))' "$TGZ")"
    REMOTE_SHA1=""
    attempt=0
    while [ "$attempt" -lt 6 ]; do
      REMOTE_SHA1="$(curl -sS --max-time 30 "https://registry.npmjs.org/bantamkit-mcp/$VERSION" 2>/dev/null \
        | node -e 'let t="";process.stdin.on("data",d=>t+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(t).dist.shasum||""))}catch{}})' \
        || true)"
      [ -n "$REMOTE_SHA1" ] && break
      attempt=$((attempt + 1))
      say "      the registry does not carry it (attempt $attempt); waiting 5 s"
      sleep 5
    done
    if [ -z "$REMOTE_SHA1" ]; then
      die "npm publish failed (its output is above), and registry.npmjs.org does not carry
         bantamkit-mcp@$VERSION after 30 s. Nothing was uploaded to PyPI."
    elif [ "$REMOTE_SHA1" != "$LOCAL_SHA1" ]; then
      die "npm publish failed, and registry.npmjs.org carries bantamkit-mcp@$VERSION with shasum
         $REMOTE_SHA1 -- not $LOCAL_SHA1, the tarball this run built. That is a different
         artifact under this version. Nothing was uploaded to PyPI."
    fi
    ok "npm publish exited non-zero, but the registry carries THIS tarball (sha1 $LOCAL_SHA1) -- continuing"
  fi
fi

# ============================================================== phase 5: verify npm landed

phase "phase 5/8  verify npm -- decided by the registry, then by running the artifact"

say "  --- asking registry.npmjs.org directly"
NPM_LANDED="no"
attempt=0
while [ "$attempt" -lt 30 ]; do
  registry_state "https://registry.npmjs.org/bantamkit-mcp/$VERSION" "npm"
  if [ "$REGISTRY_ANSWER" = "yes" ]; then NPM_LANDED="yes"; break; fi
  attempt=$((attempt + 1))
  say "      not visible yet (attempt $attempt); waiting 5 s"
  sleep 5
done
if [ "$NPM_LANDED" != "yes" ]; then
  die "bantamkit-mcp@$VERSION is still not on registry.npmjs.org. PyPI was NOT uploaded."
fi
ok "registry.npmjs.org carries bantamkit-mcp@$VERSION"

say "  --- installing the PUBLISHED tarball and driving it over stdio"
# npm's own metadata cache can answer ETARGET for minutes after a successful publish.
# --prefer-online is the fix, and an ETARGET here is NEVER evidence that the publish did not
# happen: the registry answer above already decided that question.
NPM_PROBE="$SCRATCH/npm-probe"
mkdir -p "$NPM_PROBE"
attempt=0
INSTALLED="no"
while [ "$attempt" -lt 10 ]; do
  if npm install --prefix "$NPM_PROBE" --prefer-online --no-audit --no-fund \
       "bantamkit-mcp@$VERSION" >/dev/null 2>"$SCRATCH/npm-install.err"; then
    INSTALLED="yes"; break
  fi
  attempt=$((attempt + 1))
  say "      npm has not resolved it yet (attempt $attempt). The registry says it is there, so"
  say "      this is npm's metadata cache, not a failed publish. Waiting 10 s."
  sleep 10
done
if [ "$INSTALLED" != "yes" ]; then
  cat "$SCRATCH/npm-install.err" >&2 || true
  die "could not install bantamkit-mcp@$VERSION even with --prefer-online.
         The registry answered 200 for it, so it IS published; this is an install problem and
         not a publish problem. PyPI was NOT uploaded."
fi
node "$SCRIPT_DIR/roster-probe.mjs" --label "npm bantamkit-mcp@$VERSION" \
  -- node "$NPM_PROBE/node_modules/bantamkit-mcp/dist/cli.js" \
  || die "the PUBLISHED npm artifact does not advertise what MCP_TOOLS declares. PyPI was NOT uploaded."

# ============================================================== phase 6: publish PyPI

phase "phase 6/8  publish PyPI"

if [ "$PYPI_ALREADY" = "yes" ]; then
  note "SKIPPED: PyPI already carries bantamkit==$VERSION."
else
  say "  twine upload, BY EXACT FILENAME -- never a glob:"
  say "    $WHEEL"
  say "    $SDIST"
  say ""
  # TWINE_NON_INTERACTIVE turns the one thing this script cannot survive -- a password prompt
  # reached AFTER npm has published, from a context that may have no one watching -- into an
  # immediate error with a message. Preflight already refuses when no credential exists; this
  # is the belt to that braces, for the cases preflight cannot see (a `password =` line with
  # nothing after it, a token revoked between phase 0 and phase 6). Measured: twine 7.0.0
  # reads it; older twine simply ignores an environment variable it does not know.
  TWINE_NON_INTERACTIVE=1 "$TWINE" upload "$WHEEL" "$SDIST" \
    || die "twine upload failed (its output is above). npm is published and PyPI is not.
         Rerunning this script skips npm and retries PyPI."
  ok "twine upload returned 0"
fi

# ============================================================== phase 7: verify PyPI landed

phase "phase 7/8  verify PyPI -- per-version endpoint, digests, then a real install"

say "  --- asking the PER-VERSION endpoint (the 'latest' view and the simple index both lag)"
PYPI_LANDED="no"
attempt=0
while [ "$attempt" -lt 30 ]; do
  registry_state "https://pypi.org/pypi/bantamkit/$VERSION/json" "PyPI"
  if [ "$REGISTRY_ANSWER" = "yes" ]; then PYPI_LANDED="yes"; break; fi
  attempt=$((attempt + 1))
  say "      not visible yet (attempt $attempt); waiting 5 s"
  sleep 5
done
if [ "$PYPI_LANDED" != "yes" ]; then
  die "bantamkit==$VERSION is still not on PyPI's per-version endpoint."
fi
ok "pypi.org carries bantamkit==$VERSION"

say "  --- sha256 of what PyPI serves vs what was built here"
curl -sS --max-time 60 "https://pypi.org/pypi/bantamkit/$VERSION/json" -o "$SCRATCH/pypi.json" \
  || die "could not read PyPI's per-version JSON."
"$VENV_PY" - "$SCRATCH/pypi.json" "$WHEEL" "$SDIST" <<'PY' || die "PyPI is serving different bytes from the ones built here."
import hashlib
import json
import sys
from pathlib import Path

meta = json.loads(Path(sys.argv[1]).read_text())
remote = {u["filename"]: u["digests"]["sha256"] for u in meta.get("urls", [])}
bad = False
for local in sys.argv[2:]:
    path = Path(local)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    served = remote.get(path.name)
    if served is None:
        print(f"    PyPI does not serve {path.name} for this version", file=sys.stderr)
        bad = True
    elif served != digest:
        print(f"    {path.name}: local {digest} != PyPI {served}", file=sys.stderr)
        bad = True
    else:
        print(f"    {path.name}: sha256 matches ({digest[:16]}...)")
sys.exit(1 if bad else 0)
PY
ok "PyPI serves exactly the bytes built in phase 2"

say "  --- installing bantamkit[mcp]==$VERSION into a throwaway venv and driving it over stdio"
# The [mcp] EXTRA is not optional for this check. Without it the entry point exits with
# `bantamkit-mcp needs the MCP extra`, and a probe against that measures nothing at all.
"$VENV_PY" -m venv "$SCRATCH/pyvenv" || die "could not create a throwaway venv."
"$SCRATCH/pyvenv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
# pip resolves through the SIMPLE INDEX, which is a different surface from the per-version
# endpoint the loop above waited on -- and by that loop's own comment, it lags. Waiting for
# one and then installing through the other loses the race on most releases: the digests
# match, then pip reports `from versions: ...` ending one release short. So poll the surface
# pip actually reads. --no-cache-dir keeps pip's own HTTP cache from re-serving the stale
# index page it fetched on the first attempt.
PYPI_INSTALLED="no"
attempt=0
while [ "$attempt" -lt 30 ]; do
  if "$SCRATCH/pyvenv/bin/pip" install --quiet --no-cache-dir "bantamkit[mcp]==$VERSION"; then
    PYPI_INSTALLED="yes"
    break
  fi
  attempt=$((attempt + 1))
  say "      the simple index has not caught up yet (attempt $attempt); waiting 5 s"
  sleep 5
done
if [ "$PYPI_INSTALLED" != "yes" ]; then
  die "could not install bantamkit[mcp]==$VERSION from PyPI."
fi
node "$SCRIPT_DIR/roster-probe.mjs" --label "PyPI bantamkit[mcp]==$VERSION" \
  -- "$SCRATCH/pyvenv/bin/bantamkit-mcp" \
  || die "the PUBLISHED PyPI artifact does not advertise what MCP_TOOLS declares."

# ============================================================== phase 8: summary

phase "phase 8/8  summary"

say "  bantamkit $VERSION is published and verified on BOTH registries."
say ""
say "  npm   https://www.npmjs.com/package/bantamkit-mcp/v/$VERSION"
say "        verified by installing the published tarball and listing its tools over stdio"
say "  PyPI  https://pypi.org/project/bantamkit/$VERSION/"
say "        verified by sha256 against the local build, then by installing the [mcp] extra"
say "        and listing its tools over stdio"
say ""
say "  artifacts kept at: $OUT_DIR"
say ""
say "  STILL YOURS TO DO, by hand and by decision:"
say "    - git tag -a v$VERSION -m \"bantamkit $VERSION\" && git push origin v$VERSION"
say "    - gh release create v$VERSION --notes-file <notes>   (notes cover TAG TO TAG)"
say "    - merge the release branch to main if it is not there already"
say ""
