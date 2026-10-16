import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
const { TouchLog, TOUCH_LOG_CAP_BYTES } = await import(process.argv[2] + '/runtime-ts/dist/touch/index.js');
const d = fs.mkdtempSync(path.join(os.tmpdir(), 'stuck-')); const log = new TouchLog(d, '0123456789abcdef'); fs.mkdirSync(path.dirname(log.path), { recursive: true });
const n = Number(process.argv[3]);
let body = '';
for (let i = 0; i < n; i++) body += JSON.stringify({ ts: '2026-10-01T00:00:00Z', session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 }) + '\n';
let i = 0;
while (Buffer.byteLength(body) <= TOUCH_LOG_CAP_BYTES) { body += JSON.stringify({ ts: `2026-10-02T00:00:${String(i % 60).padStart(2, '0')}Z`, session: '6f1c2d3e-aaaa-bbbb-cccc-0123456789ab', seq: i + 1, op: 'read', path: `src/x${i}.py` }) + '\n'; i++; }
fs.writeFileSync(log.path, body);
console.log('start size', fs.statSync(log.path).size, 'folded rows', n, 'live', i);
for (let k = 0; k < 10; k++) { const a = performance.now(); log.appendTouch('s', 100000 + k, 'read', `new${k}.py`, null, null, '2026-10-03T00:00:00Z'); console.log(`append ${k}: size ${fs.statSync(log.path).size} ms ${(performance.now() - a).toFixed(1)}`); }
