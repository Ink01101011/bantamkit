import { spawnSync } from 'node:child_process';
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit';
const ff = await import(R + '/runtime-ts/dist/memory/factfile.js');
let seed = Number(process.argv[2] ?? 1); const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = (a) => a[Math.floor(rnd() * a.length)];
const words = ['a', 'b c', 'x', '1', 'true', '~', 'null', '2026-01-02', '-x', 'a:b', 'a#b', 'é', '', ' ', '  ', '\t', 'q\tr', "'", '"', '#c', ' #c', 'k: v', '- z'];
const hdr = ['|', '>', '|-', '|+', '>-', '>+', '|1', '|2', '|3', '>2', '|-1', '|2+', '| #c', '|  ', '|0', '|x'];
const ind = () => ' '.repeat(Math.floor(rnd() * 5));
function value() {
  const r = rnd();
  if (r < 0.55) { // block scalar
    let s = pick(hdr) + '\n'; const n = Math.floor(rnd() * 5);
    for (let k = 0; k < n; k++) s += rnd() < 0.2 ? ind() + '\n' : ind() + pick(words) + '\n';
    return s.replace(/\n$/, rnd() < 0.5 ? '' : '\n');
  }
  if (r < 0.85) { // flow sequence
    const n = Math.floor(rnd() * 4); const items = [];
    for (let k = 0; k < n; k++) items.push(rnd() < 0.2 ? `'${pick(words)}'` : rnd() < 0.1 ? `"${pick(words)}"` : pick(words));
    return '[' + pick(['', ' ']) + items.join(pick([',', ', ', ' ,', ' , '])) + pick(['', ',', ', ', ' ']) + ']' + pick(['', ' ', ' #c', '#c', ' x']);
  }
  return pick(['&', '*', '!', '%', '@', '`', '{', '}', ',', '?', '-', ':', '#', '']) + pick(words);
}
const fronts = [];
for (let k = 0; k < Number(process.argv[3] ?? 3000); k++) {
  const where = rnd();
  if (where < 0.7) fronts.push(`name: n\ndescription: ${value()}\ntype: project\n` + (rnd() < 0.3 ? '#tail\n' : ''));
  else fronts.push(`name: n\ndescription: d\nlinks:\n- ${value()}\n- y\ntype: project\n`);
}
const py = JSON.parse(spawnSync(R + '/.venv/bin/python', ['-I', 'probe_py.py'], { input: JSON.stringify(fronts), maxBuffer: 1e9 }).stdout);
const jn = (v) => v === null ? null : Array.isArray(v) ? v.map(jn) : typeof v === 'object' ? `<python ${v.pyType.replace('datetime.', '')} ${v.text}>` : v;
const c = { same: 0, misread: 0, nodeAnswersPyRefuses: 0, nodeRefuses: 0, both: 0 }; const bad = [];
fronts.forEach((f, i) => {
  let nd; try { const m = ff.parseFrontmatter(f); nd = { ok: Object.fromEntries(Object.entries(m).map(([k, v]) => [k, jn(v)])) }; } catch (e) { nd = { err: e.message }; }
  const p = py[i];
  if (p.ok !== undefined && nd.ok !== undefined) { if (JSON.stringify(p.ok) === JSON.stringify(nd.ok)) c.same++; else { c.misread++; bad.push(['MISREAD', f, p.ok, nd.ok]); } }
  else if (p.err && nd.err) c.both++; else if (p.err) { c.nodeAnswersPyRefuses++; bad.push(['NODE-ANSWERS', f, p.err, nd.ok]); } else { if (/column 0|plain "key:"|starts a (mapping key|sequence entry)/.test(nd.err)) bad.push(["NR", f, p.ok]); c.nodeRefuses++; (globalThis.NR ??= {})[nd.err.replace(/: ".*$/s, "").slice(0, 70)] = ((globalThis.NR ?? {})[nd.err.replace(/: ".*$/s, "").slice(0, 70)] ?? 0) + 1; }
});
console.log(JSON.stringify(c));
for (const b of bad.slice(0, 15)) console.log(JSON.stringify(b));
console.log(globalThis.NR)
