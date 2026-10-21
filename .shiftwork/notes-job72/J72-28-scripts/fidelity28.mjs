// J72-28 (#207 amendment 3, plan Task 4 step 4): the Node product's inject reproduces the probe's G6 lists.
// Reads $S/fid-<mode>.json (written by fidelity28.py: id, native, prompt, head, expected; private, scratch) and the
// sidecars fidelity28.py `load` wrote under $HOME (the sandbox). Calls the bantamkit-207q build:
// `Memory.layeredForEval(project, profile, 'v2', native).injectCandidates(prompt, head)`.
// Prints counts only; on a mismatch, the first differing id (never its text) and both name lists, exit 1.
// usage: node $P/J72-28-scripts/fidelity28.mjs {dev|gold} S
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [mode, S] = process.argv.slice(2);
const R = '/Users/kktest/Documents/Claude/Projects/bantamkit-207q';
const mod = path.join(R, 'runtime-ts/dist/memory/component.js');
const { Memory } = await import(mod);
if (!os.homedir().startsWith(S)) throw new Error(`HOME is not the sandbox: ${os.homedir()}`);
const stores = path.join(S, 'stores');
const rows = JSON.parse(fs.readFileSync(path.join(S, `fid-${mode}.json`), 'utf8'));
const mems = new Map();
function mem(nk) {
  if (!mems.has(nk)) {
    const d = nk ? path.join(stores, 'automem', nk) : null;
    const native = d && fs.existsSync(d) && fs.statSync(d).isDirectory() ? d : null;
    mems.set(nk, Memory.layeredForEval(path.join(stores, 'project'), path.join(stores, 'profile'), 'v2', native));
  }
  return mems.get(nk);
}
let same = 0;
let heads = 0;
let first = null;
for (const r of rows) {
  heads += r.head !== null;
  const got = mem(r.native).injectCandidates(r.prompt, r.head).map((f) => f.name);
  if (JSON.stringify(got) === JSON.stringify(r.expected)) same += 1;
  else if (first === null) first = [r.id, got, r.expected];
}
console.log(`${mode.toUpperCase()} node`, JSON.stringify({ module: mod, prompts: rows.length, inject_equal: same, head_used: heads }));
if (first !== null) {
  console.log('FIRST MISMATCH id', first[0], 'product', JSON.stringify(first[1]), 'probe', JSON.stringify(first[2]));
  process.exit(1);
}
