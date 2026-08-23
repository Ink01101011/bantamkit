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
license   MIT
engines   node >= 18        measured on 18.20.8, not assumed
bin       bantamkit-mcp -> dist/cli.js
files     dist, assets
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
- [ ] **A `LICENSE` file exists.** `package.json` declares MIT; as of this writing the file
      does not exist, so npm would show a licence with no text in the tarball.
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

Then verify from a clean directory, not from the checkout:

```bash
cd "$(mktemp -d)"
npx -y bantamkit-mcp@<version> --help
```

## Version float: an open policy question

`0.25.0` is currently pinned to match `runtime_py.__version__`, because `build_identity`
reports that string and a drift would make the instrument lie.

The consequence is that **every Python release forces an npm release**, including ones that
change no TypeScript. The alternative is independent versioning, which costs the identity of
that single number. This has not been decided.

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
