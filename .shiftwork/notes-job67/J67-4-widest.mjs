// J67-4 (#189): widest --statusline line on both runtimes, the issue's column method
// (code point > 0x1F000 or U+26AA counts 2). Usage: node .shiftwork/notes-job67/J67-4-widest.mjs
// Runs every bed on a throwaway HOME under $TMPDIR; prints one row per bed and the max.
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..');
const NODE_CLI = path.join(ROOT, 'runtime-ts/dist/cli.js'), PY = path.join(ROOT, '.venv/bin/python');
const cols = (s) => [...s].reduce((a, ch) => a + (ch.codePointAt(0) > 0x1f000 || ch === '⚪' ? 2 : 1), 0);
const W = fs.mkdtempSync(path.join(os.tmpdir(), 'j674-')), H = path.join(W, 'home'); fs.mkdirSync(H);
const rec = (tool, outcome) => JSON.stringify({ v: 1, ts: '2026-10-13T00:00:00.000Z', tool, outcome, detail: {} });
const T64 = 'a'.repeat(64);
const beds = {
  'issue: 50x memory_recall empty-unreadable-layer': Array(50).fill(rec('memory_recall', 'empty-unreadable-layer')),
  'real: 3 events, 1 problem memory_recall': [rec('memory_save', 'saved'), rec('memory_save', 'saved'), rec('memory_recall', 'empty-unreadable-layer')],
  'longest: 50x 64-char tool empty-unreadable-layer': Array(50).fill(rec(T64, 'empty-unreadable-layer')),
  'longest active: 50x 64-char tool empty-nothing-saved': Array(50).fill(rec(T64, 'empty-nothing-saved')),
  'real active: shiftwork_clock_out refused-validation': Array(50).fill(rec('shiftwork_clock_out', 'refused-validation')),
  'fits: 2 events memory_save saved': [rec('memory_save', 'saved'), rec('memory_save', 'saved')],
};
let max = 0;
for (const [name, lines] of Object.entries(beds)) {
  const log = path.join(W, name.replace(/[^a-z0-9]+/gi, '_') + '.jsonl'); fs.writeFileSync(log, lines.join('\n') + '\n', 'utf8');
  const env = { ...process.env, HOME: H, USERPROFILE: H, BANTAMKIT_EVENT_LOG: log };
  const n = spawnSync(process.execPath, [NODE_CLI, '--statusline'], { cwd: H, env, encoding: 'utf8' }).stdout;
  const p = spawnSync(PY, ['-m', 'bantamkit.mcpserver', '--statusline'], { cwd: H, env, encoding: 'utf8' }).stdout;
  const line = n.replace(/\n$/, ''); max = Math.max(max, cols(line), cols(p.replace(/\n$/, '')));
  console.log(`${n === p ? 'same' : 'DIFF'} ${String(cols(line)).padStart(3)} ${name}: ${JSON.stringify(line)}`);
}
console.log(`widest ${max} columns; HOME=${H}`);
fs.rmSync(W, { recursive: true, force: true });
