// Prints the reference (Python) answers of storage-retention, to check they are not vacuous.
import { spawnSync } from 'node:child_process';
import { mkdtempSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const repo = process.argv[2];
process.env.BANTAMKIT_RETENTION = 'off';
let captured = null;
const runPython = (script, payload, env = {}) => {
  const r = spawnSync(join(repo, '.venv/bin/python'), [script], { input: JSON.stringify(payload), env: { ...process.env, PYTHONPATH: join(repo, 'runtime-py/src'), ...env }, maxBuffer: 1 << 28 });
  captured = JSON.parse(r.stdout.toString());
  return captured;
};
const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'peek-')));
const suite = await import(pathToFileURL(join(repo, 'tools/conformance/suites/storage-retention.mjs')).href);
const res = await suite.run({ runtimeTs: join(repo, 'runtime-ts'), scratch, runPython, repoRoot: repo, options: {} });
const b = captured.beds;
const show = (x) => JSON.stringify(x).replaceAll(scratch, '<S>').slice(0, 1500);
console.log('run#1 report', show(b[0][2]));
console.log('run#2 report', show(b[0][19]));
console.log('run#3 (ghost) report', show(b[0][21]));
console.log('searches', show(b[0].slice(11, 17)));
console.log('child', show(b[1][2]), '\nchild again', show(b[1][8]), '\nchild day 9', show(b[1][10]));
console.log('due', show([b[1][1], b[1][4], b[1][5], b[1][6], b[1][7]]));
console.log('opt-out', show(b[2][2]), show(b[2][3]));
console.log('reducer', show(b[3][1]), show(b[3][2]));
console.log('usage aaaa', Buffer.from(b[0][5], 'base64').toString());
console.log('cases', res.cases.length);
