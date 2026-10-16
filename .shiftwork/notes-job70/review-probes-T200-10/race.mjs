import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import { spawn } from 'node:child_process';
const repo = process.argv[2]; const F = Number(process.argv[3]); const N = Number(process.argv[4]); const K = Number(process.argv[5]);
const d = fs.mkdtempSync(path.join(os.tmpdir(), 'race-')); const p = path.join(d, '.bantamkit', 'touch', '0123456789abcdef.jsonl'); fs.mkdirSync(path.dirname(p), { recursive: true });
let body = ''; for (let i = 0; i < F; i++) body += JSON.stringify({ ts: '2026-10-01T00:00:00Z', session: '', seq: 0, op: 'folded', path: `src/module_${String(i).padStart(6, '0')}/component_file.py`, n: 1 }) + '\n';
let i = 0; while (F >= 0 && Buffer.byteLength(body) <= 1_000_000) { body += JSON.stringify({ ts: '2026-10-02T00:00:00Z', session: 'x', seq: i + 1, op: 'read', path: `src/x${i}.py` }) + '\n'; i++; }
fs.writeFileSync(p, body);
const child = `const { TouchLog } = await import(${JSON.stringify(repo + '/runtime-ts/dist/touch/index.js')}); const l = new TouchLog(process.argv[1], '0123456789abcdef'); const j = Number(process.argv[2]); for (let k = 0; k < Number(process.argv[3]); k++) l.appendTouch('race', j * 1000 + k, 'read', 'r' + j + '_' + k + '.py', null, null, '2026-10-03T00:00:00Z');`;
await Promise.all(Array.from({ length: N }, (_, j) => new Promise((res) => spawn(process.execPath, ['--input-type=module', '-e', child, d, String(j), String(K)], { stdio: 'inherit' }).on('exit', res))));
const got = fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.session === 'race');
console.log('expected', N * K, 'race lines present', got.length, 'size', fs.statSync(p).size);
