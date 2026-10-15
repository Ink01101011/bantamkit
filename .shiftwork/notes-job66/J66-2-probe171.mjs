// J66-2 probe for #171, adapted from the issue's repro to this checkout's runtime-ts/dist.
// Run from the repo root: node .shiftwork/notes-job66/J66-2-probe171.mjs
// HOME is a fresh mkdtemp under $TMPDIR, never the operator's.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const CLI = path.resolve('runtime-ts/dist/cli.js');
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'bk-j66-2-'));
const H = path.join(W, 'home');
const P = path.join(W, 'proj');
fs.mkdirSync(path.join(P, '.bantamkit', 'memory', 'facts'), { recursive: true });
fs.writeFileSync(path.join(P, '.bantamkit', 'memory', 'index.md'), '');
const kept = path.join(H, '.bantamkit/mcp/node_modules/bantamkit-mcp');
fs.mkdirSync(path.join(kept, 'dist'), { recursive: true });
fs.writeFileSync(path.join(kept, 'package.json'), JSON.stringify({ name: 'bantamkit-mcp', version: '0.35.7' }));
// The kept cli.js is a stub that reports its argv, so running the printed command updates nothing.
fs.writeFileSync(path.join(kept, 'dist', 'cli.js'), 'console.log(JSON.stringify(process.argv.slice(2)));\n');
fs.writeFileSync(
  path.join(H, '.bantamkit/update-check.json'),
  JSON.stringify({ checked_at: new Date().toISOString(), npm: { package: 'bantamkit-mcp', latest: '9.9.9' } }),
);
const r = spawnSync(process.execPath, [CLI, '--hook'], {
  cwd: P,
  input: JSON.stringify({ session_id: 's', cwd: P, hook_event_name: 'SessionStart', source: 'startup' }),
  encoding: 'utf8',
  env: { ...process.env, HOME: H, USERPROFILE: H },
});
if (!fs.existsSync(path.join(H, '.bantamkit', 'hooks', 'hook-log.jsonl'))) throw new Error('HOME redirect did not take');
const ctx = JSON.parse(r.stdout).hookSpecificOutput.additionalContext;
const cmd = ctx.match(/run `([^`]+)`, then reconnect/)?.[1];
console.log('printed command:', cmd);
const sh = spawnSync('/bin/sh', ['-c', cmd], { encoding: 'utf8', env: { HOME: H, PATH: '/usr/bin:/bin' } });
console.log('run via /bin/sh with PATH=/usr/bin:/bin -> exit', sh.status, JSON.stringify(sh.stdout.trim()), sh.stderr.trim().slice(0, 80));
fs.rmSync(W, { recursive: true, force: true });
