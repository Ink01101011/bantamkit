/**
 * reply-native (#292): the pure half — env parsing, the sentence frame, classification and the
 * injection plan — compared side by side AND pinned to literals per side, because a regression
 * landing on both runtimes keeps a differential green.
 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'reply-native';
export const summary = 'reply-native: env modes, the sentence frame, th/ja classification and the injection plan';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'replynative_ref.py');

const ENV_NATIVE = [undefined, 'on', 'ON', ' 1 ', 'off', 'garbage'];
const ENV_LANG = [undefined, 'th', ' TH ', 'th-TH', 'thai', 'en', 'ko', ''];

/** [prompt, golden classify] — the golden is the spec's table, pinned per side. */
const PROMPTS = [
  ['What is this "สวัสดี"?', null],
  ['What is this สวัสดี?', 'th'],
  ['merge main เข้า feat/207', 'th'],
  ['ทำต่อ', 'th'],
  ['fix the login bug', null],
  ['check C:\\Users\\สมชาย\\app.log', null],
  ['check /Users/สมชาย/app.log', null],
  ['open \\\\server\\แชร์\\x.txt', null],
  ['see https://example.com/สวัสดี now', null],
  ['run `echo สวัสดี` please', null],
  ['```\nสวัสดี\n```\nwhy does this fail', null],
  ['why\n```\nunclosed สวัสดี', null],
  ['<pasted_content id="a">ข้อความ</pasted_content> explain this', null],
  ['รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', 'th'],
  ['<ide_opened_file>/Users/a/สวัสดี.ts</ide_opened_file> what is in it', null],
  ['"ship เลย"', 'th'],
  // A KNOWN false positive, pinned so it stays visible: the apostrophe in "don't" opens a
  // single-quote span that closes before สวัสดี, so the Thai word stays in the frame. Per the
  // spec a false positive costs one directive per window and the model still judges by the
  // sentence, so this is accepted rather than fixed with a smarter quote rule.
  ["don't touch 'สวัสดี' ok", 'th'],
  ['これはなぜ壊れていますか', 'ja'],
  ['漢字だけ', 'ja'],
  ['漢字', null],
  ['「こんにちは」 means what', null],
  ['', null],
];

export async function run(ctx) {
  const rn = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'replynative.js')).href);
  const cases = [];
  const notes = [];

  const both = (calls, assets = null) => {
    const py = ctx.runPython(REF, { calls, assets }).results;
    const saved = process.env.BANTAMKIT_ASSETS;
    if (assets) process.env.BANTAMKIT_ASSETS = assets;
    else delete process.env.BANTAMKIT_ASSETS;
    try {
      const node = calls.map((c) => {
        if (c.fn === 'mode') return rn.mode(c.env);
        if (c.fn === 'frame') return rn.frame(c.prompt);
        if (c.fn === 'classify') return rn.classify(c.prompt);
        return rn.plan(c.mode, c.lang, c.seen);
      });
      return [py, node];
    } finally {
      if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
      else process.env.BANTAMKIT_ASSETS = saved;
    }
  };
  const pair = (label, calls, py, node) =>
    calls.forEach((_, i) => cases.push({ name: `${label}/${i}`, kind: 'json', expected: py[i], actual: node[i] }));
  const golden = (label, py, node, expected) => {
    cases.push({ name: `${label} — the reference`, kind: 'json', expected, actual: py });
    cases.push({ name: `${label} — the port`, kind: 'json', expected, actual: node });
  };

  // 1. mode over the env product
  {
    const calls = [];
    for (const n of ENV_NATIVE)
      for (const l of ENV_LANG) {
        const env = {};
        if (n !== undefined) env.BANTAMKIT_REPLY_NATIVE = n;
        if (l !== undefined) env.BANTAMKIT_REPLY_LANG = l;
        calls.push({ fn: 'mode', env });
      }
    calls.push({ fn: 'mode', env: { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: '😀'.repeat(40) } });
    const [py, node] = both(calls);
    pair('mode', calls, py, node);
    // ENV_NATIVE[1] ('on') x ENV_LANG[3] ('th-TH')
    golden('mode/invalid th-TH', py[1 * ENV_LANG.length + 3], node[1 * ENV_LANG.length + 3], {
      kind: 'latest', lang: null, rawLang: 'th-TH', reason: 'invalid-lang',
    });
    golden('mode/raw lang capped at 32 code points', py.at(-1).rawLang, node.at(-1).rawLang, '😀'.repeat(32));
  }

  // 2. frame + classify over the prompt table, classify pinned per side
  {
    const calls = PROMPTS.flatMap(([prompt]) => [{ fn: 'frame', prompt }, { fn: 'classify', prompt }]);
    const [py, node] = both(calls);
    pair('frame+classify', calls, py, node);
    PROMPTS.forEach(([prompt, want], i) => golden(`classify ${JSON.stringify(prompt)}`, py[2 * i + 1], node[2 * i + 1], want));
  }

  // 3. plan over modes and seen-sets, against the real pack, byte counts pinned
  {
    const latest = { kind: 'latest', lang: null, rawLang: null, reason: null };
    const fixed = (lang) => ({ kind: 'fixed', lang, rawLang: null, reason: null });
    const calls = [
      { fn: 'plan', mode: latest, lang: 'th', seen: [] },
      { fn: 'plan', mode: latest, lang: 'th', seen: ['core', 'th'] },
      { fn: 'plan', mode: latest, lang: 'ja', seen: ['core', 'th'] },
      { fn: 'plan', mode: latest, lang: null, seen: [] },
      { fn: 'plan', mode: fixed('th'), lang: 'th', seen: [] },
      { fn: 'plan', mode: fixed('ko'), lang: 'ko', seen: [] },
      { fn: 'plan', mode: fixed('en'), lang: 'en', seen: [] },
      { fn: 'plan', mode: { kind: 'off', lang: null, rawLang: null, reason: null }, lang: 'th', seen: [] },
    ];
    const [py, node] = both(calls);
    pair('plan', calls, py, node);
    const shape = (p) => ({ parts: p.parts, bytes: Buffer.byteLength(p.text), reason: p.reason });
    const want = [
      { parts: ['core', 'th'], bytes: 885, reason: null },
      { parts: [], bytes: 0, reason: null },
      { parts: ['ja'], bytes: 304, reason: null },
      { parts: [], bytes: 0, reason: null },
      { parts: ['core', 'th'], bytes: 898, reason: null },
      { parts: ['core'], bytes: 508, reason: null },
      { parts: [], bytes: 0, reason: 'english' },
      { parts: [], bytes: 0, reason: null },
    ];
    want.forEach((w, i) => golden(`plan/${i} shape`, shape(py[i]), shape(node[i]), w));
  }

  // 4. plan against a doctored pack: over budget, then missing
  {
    const pack = join(ctx.scratch, 'reply-native-pack');
    rmSync(pack, { recursive: true, force: true });
    mkdirSync(join(pack, 'langs'), { recursive: true });
    writeFileSync(join(pack, 'langs', 'core-latest.md'), `${'x'.repeat(601)}\n`);
    writeFileSync(join(pack, 'langs', 'th.md'), 'y\n');
    const latest = { kind: 'latest', lang: null, rawLang: null, reason: null };
    const call = [{ fn: 'plan', mode: latest, lang: 'th', seen: [] }];
    let [py, node] = both(call, pack);
    golden('plan/over-budget', py[0], node[0], { parts: [], text: '', reason: 'over-budget' });
    rmSync(join(pack, 'langs', 'core-latest.md'));
    [py, node] = both(call, pack);
    golden('plan/asset-missing', py[0], node[0], { parts: [], text: '', reason: 'asset-missing' });
    rmSync(pack, { recursive: true, force: true });
  }

  notes.push(`${PROMPTS.length} prompts classified, each pinned per side`);
  return { cases, notes };
}
