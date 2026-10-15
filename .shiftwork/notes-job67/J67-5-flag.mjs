// From the repo root: node .shiftwork/notes-job67/J67-5-flag.mjs <label> runtime-ts/dist/cli.js <flag>: 25 cold runs of `node cli.js <flag>` on a throwaway HOME, p50/p95
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const [label, cliArg, flag] = process.argv.slice(2); const cli = path.resolve(cliArg); // runs spawn in the throwaway HOME
const H = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-flag-'));
const env = { ...process.env, HOME: H, USERPROFILE: H }; delete env.BANTAMKIT_MEMORY_DIR;
const ms = [];
for (let i = 0; i < 25; i++) { const t = performance.now(); const r = spawnSync(process.execPath, [cli, flag], { cwd: H, env, input: '' }); ms.push(performance.now() - t); if (r.status !== 0) { console.error(String(r.stderr)); process.exit(1); } }
ms.sort((a, b) => a - b);
console.log(`${label}\t${flag}\tp50 ${ms[12].toFixed(1)}\tp95 ${ms[23].toFixed(1)}\t(n=25)`);
