#!/usr/bin/env node
// The checkout's entry to the detached Retention child (#204, job69 J69-6):
//
//   node tools/storage/retention-child.mjs <cwd> <home>
//
// One pass, at most once per 24 h (`<home>/.bantamkit/retention.json`), over `<home>` and the
// `.shiftwork/` directly under `<cwd>`. It runs `runtime-ts/dist/storage/retention-child.js`,
// the file the SessionStart hook and the MCP server spawn, so a checkout and an npm install
// run the same code; it prints nothing and exits 0. `BANTAMKIT_RETENTION=off` makes it a
// no-op. BOTH ARGUMENTS ARE REQUIRED: the child never guesses a home (J69-6's incident).
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
await import(pathToFileURL(join(here, '..', '..', 'runtime-ts', 'dist', 'storage', 'retention-child.js')).href);
