// T200-11-fold.mjs <dist> -- ms of one append that folds the re-review's stuck log (6,000 folded rows, then live
// lines past the cap) and of the plain append after it (median of 9); T200-10-fold.mjs is the ordinary log.
import fs from 'node:fs'; import path from 'node:path'; import { pathToFileURL } from 'node:url';
const t = await import(pathToFileURL(path.join(process.argv[2], 'touch', 'index.js')).href);
const dir = fs.mkdtempSync(path.join(process.env.TMPDIR, 'fold11-'));
let body = '';
for (let i = 0; i < 6000; i++) body += JSON.stringify({ ts: `2026-09-${String(1 + ((i * 7919) % 28)).padStart(2, '0')}T00:00:00Z`, session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 }) + '\n';
for (let i = 0; Buffer.byteLength(body) <= t.TOUCH_LOG_CAP_BYTES; i++) body += JSON.stringify({ ts: `2026-10-02T00:00:${String(i % 60).padStart(2, '0')}Z`, session: 's', seq: i + 1, op: 'read', path: `src/x${i}.py` }) + '\n';
const med = (a) => a.sort((x, y) => x - y)[a.length >> 1];
const fold = [], plain = [];
for (let k = 0; k < 9; k++) {
  const log = new t.TouchLog(dir, `id${k}`); fs.mkdirSync(path.dirname(log.path), { recursive: true });
  fs.writeFileSync(log.path, body);
  let a = performance.now(); log.appendTouch('n', 1, 'read', 'x.py'); fold.push(performance.now() - a);
  a = performance.now(); log.appendTouch('n', 2, 'read', 'y.py'); plain.push(performance.now() - a);
}
console.log(JSON.stringify({ log_bytes: Buffer.byteLength(body), folding_append_ms: +med(fold).toFixed(2), plain_append_ms: +med(plain).toFixed(2), after_fold_bytes: fs.statSync(new t.TouchLog(dir, 'id0').path).size }));
fs.rmSync(dir, { recursive: true, force: true });
