# Releasing `bantamkit-mcp` to npm

Publishing is **outward-facing and irreversible in practice** — npm unpublish is restricted
after 72 hours, and a name, once taken, is taken. Nothing in this document should be run
without an explicit decision to publish.

For the PyPI/tag side of a release see [install.md](install.md#releasing-maintainers). For
what the package *is*, see [`runtime-ts/README.md`](../runtime-ts/README.md).

## What ships

```
name      bantamkit-mcp
version   0.25.0
type      module            (ESM)
license   MIT               LICENSE vendored from the repository root at prepack
engines   node >= 18        measured on 18.20.8, not assumed
bin       bantamkit-mcp     -> dist/cli.js        the MCP server, what a host launches
          bantamkit-memory  -> dist/memory/cli.js the memory lifecycle CLI
files     dist, assets      plus README.md, LICENSE and package.json, which npm packs
                            unconditionally
deps      @modelcontextprotocol/sdk  pinned exactly 1.30.0
```

One runtime dependency, pinned exactly. `devDependencies` do not ship.

`files` is an allow-list: `src/`, `test/`, `tsconfig.json` and everything under `tools/` stay
out of the tarball. That is what makes "no Python at runtime" true — the conformance harness
shells out to CPython, and it is not in the package.

## The asset pack has to be vendored first

The pack lives at the **repository** root, one level above the package root, and no packaging
system can reach outside its own package directory. npm is stricter than hatchling here:
there is no `force-include`, so `assets/` must physically exist under `runtime-ts/` before
the tarball is built.

`scripts/sync-assets.mjs` does this and is wired to `prepack`, so `npm pack` and
`npm publish` both trigger it. It is the Node counterpart of `runtime-py/hatch_build.py` and
carries the same two rules:

1. **Locate, don't hardcode.** Prefer `../assets` (the checkout) over a populated local
   `assets/` (the already-vendored layout), so a stale vendored copy can never win.
2. **Neither found, or found empty → throw.** A build that cannot include the pack must
   fail, not succeed short. That rule exists because of a Python build that returned 0 and
   shipped an artifact without its data.

The copy is byte-for-byte and stale files are deleted first, because `build_identity` hashes
every byte of the tree — an extra file moves `assets_digest` exactly as surely as a missing
one.

The **`LICENSE` has the same problem and the same fix**, in the same script and by the same
two rules. It is easy to assume otherwise, because npm really does pack `LICENSE`
unconditionally — but only from the *package* root, and this repository's licence is one
level above it. Both vendored copies are gitignored: a tracked second copy is a copy that
drifts.

## One command: `tools/release/publish.sh`

The checklist below is the hand-run form, and it is still what the script does — but doing it
by hand is how job56 happened. **`tools/release/publish.sh` is the whole release in one
command**: test → build → prepublish → npm → PyPI, refusing before it ships and skipping what
is already published.

```bash
tools/release/publish.sh --dry-run    # phases 0-3; nothing leaves the machine
tools/release/publish.sh              # the real thing, from a terminal
```

Eight phases, in this order, because the order is a safety property — everything that can be
checked before the first upload is checked before the first upload:

| phase | what it does |
|---|---|
| 0 preflight | version sites agree, tree clean, toolchain present, PyPI credential present, **and both registries asked what they already carry** |
| 1 test | the four gates. 0 failures is the bar |
| 2 build | both artifacts, into a **clean directory named for the version** |
| 3 prepublish | `npx-cold-start.mjs`, `twine check`, and the asset pack inside each artifact **hashed** against `assets/` |
| 4 npm | `npm publish --access public`, output streamed live |
| 5 verify npm | `registry.npmjs.org` directly, then the **published** tarball driven over stdio |
| 6 PyPI | `twine upload`, **by exact filename** |
| 7 verify PyPI | the per-version endpoint, sha256 against the local build, then an install with the `[mcp]` extra driven over stdio |
| 8 summary | what shipped, and what is still yours to do (tag, GitHub release) |

Four properties are worth knowing before you trust it:

- **It is resumable.** A version already on a registry is skipped, never republished — npm
  forbids republishing a version anyway, so skipping is the only correct behaviour and not a
  convenience. This repository has a half-done release in its history: npm carries `0.26.0`
  and PyPI's version list starts at `0.27.0`. Rerunning the script is how that gets finished.
- **It refuses rather than proceeds.** Every refusal above happens while nothing has left the
  machine. The refusals are named one by one, all of them in a single run.
- **There is no secret in it.** npm publishes with no `--otp`: it answers with a callback URL
  you authenticate in a browser, which is why the script streams npm's output straight through
  and never captures it. twine reads its token from `~/.pypirc`, whose *existence* preflight
  checks and whose contents it never reads — a missing credential is a refusal in phase 0, not
  a prompt in phase 6 after npm has already published.
- **`--dry-run` is a real rehearsal.** It runs phases 0–3 — including a real `npm pack`, a real
  `python -m build` and the cold-start gate — and stops before the first publish.

Two checks in phase 3 exist because nothing else in the repository performs them. The asset
pack is compared **byte for byte** (`tools/release/check-asset-pack.py`): both packaging gates
compare asset *names*, and job56 measured a pack with the right names and the wrong bytes going
through a green build, a green packaging gate and an installed server that advertised a
description and an input schema no commit carries — silently. And both published artifacts are
**driven over real stdio** (`tools/release/roster-probe.mjs`) and compared against `MCP_TOOLS`,
because every local gate rebuilds before it looks, and the artifact that reaches a user is the
one nothing was asking.

## Before you publish

Everything here is verification, and none of it contacts the registry.

```bash
cd runtime-ts
npm test                                    # includes the packaging gate
node ../tools/conformance/run.mjs --all     # both runtimes, all seven suites
npm pack --dry-run                          # what the tarball would contain
```

Then check, in order:

- [ ] **CI is green on all cells** — `gh run list --branch <branch>`. Read the log, not the
      colour: each cell must print a non-zero test count. A step that never ran prints no
      summary at all, and that is what to look for.
- [ ] **The PR is merged**, so the published version corresponds to a commit on `main`.
- [ ] **`LICENSE` is in the tarball.** `package.json` declares MIT and the text now exists,
      at the **repository** root. npm's documented rule that `LICENSE` is always packed
      regardless of `files` is about the *package* root and does not reach it — measured:
      with the file at the repo root and no vendoring step the listing was 129 files and
      carried no LICENSE. `scripts/sync-assets.mjs` vendors it at `prepack`, which takes the
      listing to 130, and `test/packaging.test.mjs` asserts it byte-for-byte.
- [ ] **`version` is the one you mean.** See the version-float question below.
- [ ] **`npm whoami`** is the account you intend to publish from.
- [ ] **The name resolves as expected.** `npm view bantamkit-mcp version` — an `E404` means
      the name is still free.

## Publishing

Requires an explicit decision. Not part of any automated flow.

```bash
cd runtime-ts
npm publish --access public
```

### `npm publish` refuses if the install gate is red

`prepublishOnly` runs `runtime-ts/scripts/gate-before-publish.mjs`, which runs
`tools/conformance/npx-cold-start.mjs` — a real `npm pack`, installed through `npx` into a
cache that has never seen it and driven over stdio — and **exits non-zero if it fails, which
stops the publish before npm packs anything or contacts the registry**. Measured with npm
11.6.2 on a worktree whose `dist/` predated a tool: `npm publish --dry-run` stopped at the
hook, printing `FAIL: npx cold start, 2 failed checks` naming the missing tools, with no
`prepack`, no tarball listing and no `Publishing to …` line after it. The `--offline` arm is
not used; it costs minutes, and a release step nobody will wait for is one somebody will
bypass.

`npm publish --dry-run` is a faithful rehearsal of that refusal: the hook does the same work
and returns the same exit code. Two consequences worth knowing before you type it — it
**compiles `runtime-ts/dist/`** and installs a real tarball into a temp `npx` cache (it still
publishes nothing), and on an already-published version it ends at npm's own
`You cannot publish over the previously published versions`, which is npm refusing, not the
gate.

**What the hook does not cover**, each measured rather than assumed:

- `npm publish --ignore-scripts` skips it silently.
- `npm publish <tarball.tgz>` skips it — npm runs no lifecycle script out of a pre-built
  tarball. Publishing a tarball someone else packed is publishing something nothing checked.
- The PyPI half: `twine upload` has no hook of any kind. (The Python wheel has no compiled
  artifact that can go stale — see the job56 row in [porting.md](porting.md).)
- It gates the **working tree you are standing in**, not the commit or the tag. The merged-PR
  checkbox above is what ties the two together.

Then verify from a clean directory, not from the checkout:

```bash
cd "$(mktemp -d)"
npx -y bantamkit-mcp@<version> --help
```

## Version agreement

This was an open question and it is now decided. Read this before you bump anything.

**`runtime-py/src/bantamkit/__init__.py`'s `__version__` is authoritative.
`runtime-ts/package.json`'s `version` follows it.** They are one number with two
declarations, never two numbers that happen to match.

*(The paragraph replaced here named the Python declaration `runtime_py.__version__`. There
is no such symbol and there never was — the module is `bantamkit`, the file is
`runtime-py/src/bantamkit/__init__.py`. That is the calibre of check prose gets, and the
reason the rest of this section is a gate rather than a paragraph.)*

**Why one number.** `build_identity` reports a version alongside a digest of the code
answering, and the whole instrument is worth nothing if that version does not describe that
code. It has already lied once here: `RB-P45`, an editable `v0.25.0` checkout advertising
`0.3.0`, because the string was read from the last *install* instead of the checkout. Two
runtimes sharing one memory store and reporting two different versions is the same defect in
the other runtime's clothes — a client cannot tell which half it is talking to, and the field
that was supposed to disambiguate is the one that differs.

**Why Python is the authoritative half.** It is the declaration `pyproject.toml` names as
its `dynamic` version source, so it is already the single source for the wheel's metadata and
for what the running MCP server advertises. `package.json`'s copy is a second statement of
it, and the second statement is the one that follows.

**What it costs.** Every Python release forces an npm release, including ones that change no
TypeScript. That is the price of the identity, and it is now paid deliberately. Independent
versioning was the alternative; it was rejected because it buys a few skipped publishes at
the cost of the one number that says which build you are running.

**When they disagree.** The suite goes red before anything is published — no judgement call,
no "which one did we mean". Bring `package.json` to `__version__`, not the reverse.

**Who notices.** Two nodes, one in each suite, because whoever bumps `package.json` runs
`npm test` and whoever bumps `__version__` runs pytest — a gate living only in the other
side's suite is a gate the person making the mistake never runs:

| runs under | node |
|---|---|
| `pytest runtime-py/tests` | `runtime-py/tests/test_version_agreement.py::test_the_two_version_declarations_agree` |
| `npm test --prefix runtime-ts` | `runtime-ts/test/packaging.test.mjs` → `the two version declarations agree` |

A third node, `test_the_ruling_is_still_written_down`, reads **this section** and fails if it
stops naming both declarations and the nodes above — so the ruling cannot rot into a comment
nobody re-derives while the gate it explains stays behind.

## Things that are not release steps

- **`git tag`.** Tagging is the Python-side release ritual documented in
  [install.md](install.md#releasing-maintainers) and is a separate decision from npm.
- **`npm login` is not authorization.** Being logged in only means an accidental
  `npm publish` would now succeed.
- **Publishing to fix a mistake.** Bump the version and publish again; do not unpublish.

## Consuming without the registry

If publishing is not wanted, the package still works — the team just loses "no install at
all":

```bash
npm pack                                       # -> bantamkit-mcp-0.25.0.tgz
npx -y --package=./bantamkit-mcp-0.25.0.tgz bantamkit-mcp
```

Note the form. **`npx ./some.tgz` does not work** — npx execs the bare path and the shell
answers `Permission denied`. The `--package=` form is the one that runs.

Or skip npm entirely and point the client at `node /abs/path/to/dist/cli.js`.
