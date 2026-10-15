// J66-6 (#174) probe: pyIntStrict against CPython int() over generated strings.
// Run from the repo root after `cd runtime-ts && npm run build`:
//   node .shiftwork/notes-job66/J66-6-intparity.mjs
import { spawnSync } from 'node:child_process';
import { pyIntStrict } from '../../runtime-ts/dist/pyargparse.js';

const GEN = String.raw`
import json, sys, unicodedata, random
random.seed(7)
nd = [c for c in range(sys.maxunicode+1) if unicodedata.category(chr(c)) == "Nd"]
cases = [chr(c) for c in nd] + [chr(c)+chr(nd[(i*7)%len(nd)]) for i,c in enumerate(nd)]
alpha = ["1","٣","\U0001d7d1","_"," ","\t","\x1c","\x85","　","﻿","+","-","a","0","²",".","\n","​"]
for _ in range(20000):
    cases.append("".join(random.choice(alpha) for _ in range(random.randint(0,6))))
cases += ["1"*4300, "1"*4301, "1_"*4300+"1", "-0", "+0", "007"]
out = []
for c in cases:
    try: out.append([c, str(int(c))])
    except ValueError: out.append([c, None])
sys.stdout.buffer.write(json.dumps(out).encode("utf-8"))
`;
const r = spawnSync('.venv/bin/python', ['-I', '-c', GEN], { encoding: 'utf8', maxBuffer: 1 << 28 });
if (r.status !== 0) throw new Error(r.stderr);
const cases = JSON.parse(r.stdout);
let bad = 0;
for (const [text, want] of cases) {
  let got;
  try {
    got = pyIntStrict(text);
  } catch {
    got = null;
  }
  const same = want === null ? got === null : got !== null && got === Number(want);
  if (!same && bad++ < 8) console.log('MISMATCH', JSON.stringify(text), want, got);
}
console.log(`cases ${cases.length} mismatches ${bad}`);
