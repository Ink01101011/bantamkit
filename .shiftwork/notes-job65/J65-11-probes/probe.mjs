import { VALUES, FRONTS } from './inputs.mjs';
import { spawnSync } from 'node:child_process';
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit';
const ff = await import(R + '/runtime-ts/dist/memory/factfile.js');
const fronts = [...VALUES.map((v) => `name: n\ndescription: ${v}\ntype: project\n`), ...FRONTS];
const py = JSON.parse(spawnSync(R + '/.venv/bin/python', ['-I', 'probe_py.py'], { input: JSON.stringify(fronts) }).stdout);
const jn = (v) => v === null ? null : Array.isArray(v) ? v.map(jn) : typeof v === 'object' ? `<python ${v.pyType.replace('datetime.', '')} ${v.text}>` : v;
const rows = [];
let agree = 0, misread = 0, nodeRefuses = 0, bothRefuse = 0;
fronts.forEach((f, i) => {
  let nd; try { const m = ff.parseFrontmatter(f); nd = { ok: Object.fromEntries(Object.entries(m).map(([k, v]) => [k, jn(v)])) }; } catch (e) { nd = { err: e.constructor.name + ': ' + e.message }; }
  const p = py[i]; let verdict;
  if (p.ok !== undefined && nd.ok !== undefined) verdict = JSON.stringify(p.ok) === JSON.stringify(nd.ok) ? 'SAME' : 'MISREAD';
  else if (p.err && nd.err) verdict = 'both-refuse'; else if (p.err) verdict = 'NODE-ANSWERS-PY-REFUSES'; else verdict = 'node-refuses';
  if (verdict === 'SAME') agree++; else if (verdict.startsWith('MIS') || verdict.startsWith('NODE-ANS')) misread++; else if (verdict === 'node-refuses') nodeRefuses++; else bothRefuse++;
  rows.push(`${verdict.padEnd(24)} ${JSON.stringify(i < VALUES.length ? VALUES[i] : f)}\n    py: ${JSON.stringify(p.ok?.description ?? p.ok?.links ?? p.ok ?? p.err)}\n    nd: ${JSON.stringify(nd.ok?.description ?? nd.ok?.links ?? nd.ok ?? nd.err)}`);
});
console.log(rows.join('\n'));
console.log(`\nTOTAL ${fronts.length}: same ${agree}, misread(or node answers where py refuses) ${misread}, node-only refusal ${nodeRefuses}, both refuse ${bothRefuse}`);
