// Read-only baseline / after probe. Runs against whatever HOME + cwd it is given,
// so it measures a SANDBOX COPY without touching the user's real store.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
// Repo-relative so this stays rerunnable from any checkout: docs/eval-data → repo root.
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST = path.join(REPO, 'runtime-ts', 'dist', 'memory');
const { Memory } = await import(path.join(DIST, 'component.js'));
const cwd = process.argv[2];
const queries = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const HEADER = /^\[([^\]]+)\] \[([^\]]+)\] \(([a-z]+)\) (.*)$/;

const m = Memory.layered(cwd);
const [bytes, budget] = m.indexAccounting();
const projFacts = m.store.root;
const profRoot = m.layers.find(([l]) => l === 'profile')?.[1]?.root ?? null;
const names = (d) => { try { return new Set(fs.readdirSync(path.join(d,'facts')).filter(n=>n.endsWith('.md'))); } catch { return new Set(); } };
const p = names(projFacts), q = names(profRoot);
const dup = [...p].filter(n => q.has(n)).sort();

const top1 = {};
for (const query of queries) {
  const reply = m.recall(query, 3);
  const line = reply.split('\n').map(l => l.match(HEADER)).find(Boolean);
  top1[query] = line ? `${line[1]}/${line[2]}` : null;
}
console.log(JSON.stringify({
  projectRoot: projFacts, profileRoot: profRoot,
  projectFacts: p.size, profileFacts: q.size,
  duplicateNames: dup.length, duplicates: dup.map(n=>n.replace(/\.md$/,'')),
  indexBytes: bytes, indexBudget: budget,
  factBytesProject: [...p].reduce((a,n)=>a+fs.statSync(path.join(projFacts,'facts',n)).size,0),
  factBytesProfile: [...q].reduce((a,n)=>a+fs.statSync(path.join(profRoot,'facts',n)).size,0),
  top1,
}, null, 2));
