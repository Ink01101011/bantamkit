# bantamkit-mcp

The bantamkit MCP server as a pure-Node package: `npx bantamkit-mcp`, no Python, no
`uv`, no `pipx`, no interpreter bootstrap.

**Status: not a server yet.** Job38 unit N1 ships the package skeleton and the asset
resolver. The stdio server and the seven tools land in later units, and the package is
not published. `bantamkit-mcp --assets-root` prints the asset pack this build resolved,
which is the packaged-arm resolution running inside a real install.

## The asset pack

The pack is language-agnostic data (tool manifests, schemas, skills, rubrics, contract
wording, eval fixtures) that lives at the **repository root**, one level above this
package, and is shared verbatim with `runtime-py`. npm cannot reach outside a package
directory, so `scripts/sync-assets.mjs` vendors it into `runtime-ts/assets/` on
`prepack`; that directory is generated and git-ignored.

`build_identity` hashes **every byte of the whole tree**, not just the 20 files the
tools read, so the pack ships whole — 83 files / 212,480 bytes — or `assets_digest` and
`build_id` change. `test/packaging.test.mjs` asserts that against what `npm pack` would
actually put in the tarball, never against the source tree.

## Resolving the pack at runtime

`assetsRoot()` mirrors `runtime-py/src/bantamkit/assets.py` arm for arm:

1. `$BANTAMKIT_ASSETS`, verbatim, with no existence check.
2. `<package>/assets/` — one level above `dist/`. **This is the arm `npx` uses.**
3. `<repo>/assets/` — two levels above `dist/`, for a dev checkout with nothing
   vendored.
4. Otherwise `AssetNotFound: no assets directory found; set BANTAMKIT_ASSETS`.

## Development

```sh
npm install
npm run build      # tsc -> dist/
npm test           # node --test; `npm test -- packaging` selects one file
npm pack --dry-run # vendors the pack via prepack, lists the tarball
```

Runtime dependencies: none yet. Dev dependencies do not ship.
