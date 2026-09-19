---
name: npx-install-fails-on-windows-eperm
description: npx -y bantamkit-mcp fails on the user's Windows box with EPERM errno
  -4048 and they switched to the PyPI install instead, what the tarball probe ruled
  out, and why the npx defect still matters
type: project
created: '2026-09-05'
last_recalled: '2026-09-15'
links:
- feedback-must-run-on-windows-not-just-macos
- public-install-is-pure-node-by-ruling
- npm-publish-0-26-0-blocked-on-login
- project-windows-ci-measured-failures
---

STATUS 2026-09-05: the user is UNBLOCKED — they installed from PyPI on Windows and it worked. The npx defect itself is UNDIAGNOSED and still open. The probe was never run, so no `bk-eperm-probe.txt` exists and the EPERM stack frame was never captured.

SYMPTOM: `npx -y bantamkit-mcp` on Windows fails with `EPERM: operation not permitted, errno: -4048` (-4048 = ERROR_ACCESS_DENIED). The user's own reading was "เหมือนจะมีปัญหาที่ node" — a hunch about their Node/npm install, not a measurement. Never repeat it as a finding.

RULED OUT BY MEASUREMENT, against the PUBLISHED artifact and not the working tree — `npm pack bantamkit-mcp@latest` (dist-tags latest = 0.29.1, 150 files), then inspected the tgz:
- zero symlink/hardlink entries (the classic Windows EPERM cause)
- longest packed path 66 chars, `package/assets/evals/devteam/repo/issues/142-settlement-timeout.md` — nowhere near MAX_PATH 260
- no Windows-illegal chars in any name, no case-insensitive collisions
- published package.json has NO preinstall/postinstall/install script; only `prepack` and `pretest`, neither of which runs on install

No bantamkit code executes during that install at all, so the fault is in npm's own extract/rename into `%LocalAppData%\npm-cache\_npx\<hash>`, not in the payload. Rerun the probe rather than trusting this paragraph.

TWO REMAINING BRANCHES, never discriminated: (A) a torn `_npx/<hash>` from a previous run with node.exe still holding a handle — Windows refuses to rename over a file another process has open, the SAME mechanism already written up in `runtime-ts/scripts/sync-assets.mjs:85` where an atomic-rename sync-assets measured EPERM and was removed; (B) Defender realtime holding handles on freshly-extracted files. Node version is a third, untested candidate given `engines: node >=20`.

WHY THIS STILL MATTERS DESPITE THE WORKAROUND: the shipped `--install claude` writes an UNPINNED `npx -y bantamkit-mcp` into the host config, so every teammate installing that way on Windows meets the same wall. And the PyPI escape hatch CONTRADICTS the standing ruling in [[public-install-is-pure-node-by-ruling]] — "npx runs NODE, no Python at runtime" — whose whole point was a teammate with no clone and no venv. On Windows that promise is currently unmet: the only install路 that demonstrably works needs Python. The ruling is not overturned by this; the gap is a defect against it.

PROBE SCRIPT: `win-eperm-probe.ps1`, written to a session scratchpad that is likely gone — regenerate it. It captures node/npm versions, LongPathsEnabled, cache and `_npx` paths, a per-hash file count under `_npx\<hash>\node_modules\bantamkit-mcp` (compare against 150 — fewer means torn extract, branch A), processes holding handles, cache writability, Defender realtime + exclusions, a `npx -y --loglevel silly bantamkit-mcp --help` repro, and the tail of the newest npm debug log. `--help` is safe as the repro verb: `dist/cli.js` parses `-h`/`--help` and exits rather than starting the stdio server and hanging.

UNRUN DISCRIMINATING TEST: `npm i -g bantamkit-mcp@0.29.1` then `bantamkit-mcp --help`. Passing means the fault is specific to the `_npx` cache and the host config can point at the global shim; failing the same way means machine-level permissions/AV.
