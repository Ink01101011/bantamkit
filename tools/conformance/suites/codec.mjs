/**
 * codec — the fact-file bytes, Python against Node, both directions.
 *
 * The property: for every fact in the corpus the bytes Node writes and the bytes Python
 * writes are IDENTICAL, and each runtime parses what the other wrote. A codec that only
 * round-trips its own output is the failure mode this suite exists to catch — the live
 * store already holds files Python wrote, and `_stamp` rewrites one on every recall hit.
 *
 * The corpus is the real 65-fact store (copied to scratch — never opened in place; a defect
 * in this area destroyed its index once) plus an adversarial set, because the real corpus
 * is not adversarial enough: it has no non-ASCII in any frontmatter, no quoted scalar and
 * no empty description.
 */
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'codec';
export const summary = 'fact-file frontmatter: emit byte-identically, and parse each other';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'codec_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const sha = (s) => createHash('sha256').update(s, 'utf8').digest('hex');

/**
 * Where the real store lives.
 *
 * Never read in place. This copies the directory to the harness scratch and reads only the
 * copy, which is also what makes the suite safe to run while a server is live. If no store
 * is found the adversarial half still runs and the suite SAYS so — a silently shrinking
 * corpus is the way a conformance gate stops meaning anything.
 */
function realStoreFacts(ctx) {
  const explicit = ctx.options.corpus ?? process.env.BANTAMKIT_CONFORMANCE_CORPUS;
  const candidates = [];
  if (explicit) candidates.push(explicit);
  candidates.push(join(ctx.repoRoot, '.bantamkit', 'memory', 'facts'));
  try {
    // In a worktree the store lives in the MAIN checkout, which git can name without
    // anybody hardcoding a sibling path.
    const commonDir = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: ctx.repoRoot,
      encoding: 'utf8',
    }).trim();
    candidates.push(join(dirname(commonDir), '.bantamkit', 'memory', 'facts'));
  } catch {
    /* not a git checkout; the other candidates still apply */
  }
  for (const c of candidates) {
    if (existsSync(c)) {
      const copy = join(ctx.scratch, 'real-facts');
      cpSync(c, copy, { recursive: true });
      return { dir: copy, source: c };
    }
  }
  return { dir: null, source: candidates.join(' | ') };
}

/** The adversarial cases. Each one is here because something about it can silently differ. */
function adversarialFacts() {
  const ruler = Array(30).fill('aaaa').join(' ');
  const f = (name, over) => ({
    name,
    description: 'd',
    type: 'project',
    body: 'body',
    links: [],
    last_recalled: null,
    created: null,
    ...over,
  });
  const cases = [
    // the wrap boundary, from both sides
    f('wrap-78', { description: ruler.slice(0, 78) }),
    f('wrap-79', { description: ruler.slice(0, 79) }),
    f('wrap-80', { description: ruler.slice(0, 80) }),
    f('wrap-81', { description: ruler.slice(0, 81) }),
    f('wrap-82', { description: ruler.slice(0, 82) }),
    f('wrap-twice', { description: ruler.slice(0, 180) }),
    f('wrap-thrice', { description: Array(80).fill('aaaa').join(' ') }),
    f('no-space-120', { description: 'w'.repeat(120) }),
    f('wrap-at-a-double-space', { description: `${ruler.slice(0, 70)}  ${ruler.slice(0, 40)}` }),
    // Three-letter words put a word end at column EXACTLY 80, which four-letter words
    // never do. Without these two, `bestWidth = 79` and `column >= bestWidth` both survive
    // the entire corpus — measured.
    f('column-exactly-80', { description: Array(19).fill('aaa').join(' ') }),
    f('column-exactly-80-plus-one', { description: Array(20).fill('aaa').join(' ') }),
    // The guards `start != 0 and end != len(text)` that only the single-quoted writer has.
    // Without a case where the column is already past 80 when the TRAILING space arrives,
    // deleting them survives the corpus — measured.
    f('quoted-trailing-space-past-80', { description: `a: ${'w'.repeat(90)} ` }),
    f('quoted-trailing-space-under-80', { description: `a: ${'w'.repeat(20)} ` }),
    // unicode: the column is codepoints, and allow_unicode keeps these raw
    f('em-dash', { description: 'an em dash — in the middle of an otherwise ordinary description' }),
    f('thai', { description: 'ภาษาไทย ปนกับ ascii ที่ยาวพอจะดันคอลัมน์ให้เกินแปดสิบ และต้องตัดบรรทัดให้ตรงกัน' }),
    f('emoji', { description: 'emoji 🐔 and 👨‍👩‍👧‍👦 a zwj sequence, long enough to push the wrap past the eighty column' }),
    f('astral-at-the-boundary', { description: `aa🐔🐔 ${ruler.slice(0, 76)}` }),
    // the characters that force PyYAML out of plain style
    f('colon-space', { description: 'a: b — a colon and a space' }),
    f('hash-space', { description: 'a #b — a hash after a space' }),
    f('leading-dash', { description: '- a leading dash and a space' }),
    f('trailing-space', { description: 'a trailing space ' }),
    f('leading-space', { description: ' a leading space' }),
    f('lone-quote', { description: "it's got a lone apostrophe" }),
    f('leading-quote', { description: "'a leading apostrophe" }),
    f('quote-in-quoted', { description: "a: it's both" }),
    f('leading-indicators', { description: '#[]{}&*!|>%@` all at the front' }),
    f('document-marker', { description: '--- looks like a document start' }),
    f('dots-marker', { description: '... looks like a document end' }),
    f('control-char', { description: 'a\x01b control character forces double quotes' }),
    f('tab', { description: 'a\tb' }),
    f('newline', { description: 'a\nb' }),
    f('two-newlines', { description: 'a\n\nb' }),
    f('space-then-newline', { description: 'a \nb' }),
    f('newline-then-space', { description: 'a\n b' }),
    f('backslash', { description: 'a\\b and a "quote"' }),
    f('nbsp', { description: 'a\u00a0b non-breaking space' }),
    f('bom-inside', { description: 'a\ufeffb' }),
    // values the resolver would steal back
    f('resolves-null', { description: 'null' }),
    f('resolves-bool', { description: 'yes' }),
    f('resolves-int', { description: '12' }),
    f('resolves-float', { description: '1.5' }),
    f('resolves-date', { description: '2026-08-23' }),
    f('resolves-merge', { description: '<<' }),
    f('empty-description', { description: '' }),
    // links: 0, 1, 3, and awkward items
    f('links-none', { links: [] }),
    f('links-one', { links: ['a'] }),
    f('links-three', { links: ['a', 'b', 'c'] }),
    f('links-awkward', { links: ['a: b', '- c', "it's", '', '2026-08-23', 'x'.repeat(120)] }),
    // dates
    f('dates-both', { created: '2026-08-23', last_recalled: '2026-08-22' }),
    f('dates-created-only', { created: '2026-08-23' }),
    f('dates-null', { created: null, last_recalled: null }),
    // bodies
    f('body-empty', { body: '' }),
    f('body-one-line', { body: 'one line' }),
    f('body-trailing-blanks', { body: 'one\n\n\n\n' }),
    f('body-leading-blanks', { body: '\n\n\none' }),
    f('body-doc-marker-inside', { body: 'one\n---\ntwo' }),
    f('body-python-only-space', { body: '\x1cone\x85' }),
    f('body-js-only-space', { body: '\ufeffone\ufeff' }),
    f('body-ideographic-space', { body: '\u3000one\u3000' }),
    // names at both ends of ^[a-z0-9][a-z0-9-]*$
    f('a', {}),
    f('0', {}),
    f('on', {}),
    f('0-', {}),
    f('z'.repeat(120), {}),
    f('a-b-c-0-1-2', {}),
  ];
  return cases.map((c, i) => ({ ...c, __case: `adv/${c.name}#${i}` }));
}

export async function run(ctx) {
  const factfile = await import(
    pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'factfile.js')).href
  );
  const cases = [];
  const notes = [];

  // ---------------------------------------------------------------- assemble the corpus
  const { dir, source } = realStoreFacts(ctx);
  let realFacts = [];
  if (dir) {
    const files = readdirSync(dir).filter((f) => f.endsWith('.md')).sort();
    const parsed = ctx.runPython(REF, {
      op: 'parse',
      texts_b64: files.map((f) => readFileSync(join(dir, f)).toString('base64')),
    }).parsed;
    realFacts = parsed.map((p, i) => {
      if (p.error) throw new Error(`real fact ${files[i]} did not parse in Python: ${p.error}`);
      return {
        name: p.meta.name,
        description: p.meta.description,
        type: p.meta.type,
        body: p.body,
        links: p.meta.links ?? [],
        last_recalled: p.meta.last_recalled ?? null,
        // `_facts` falls back to the file mtime when `created` is absent; that fallback is
        // the store's, not the codec's, so the codec case uses what the file carries.
        created: p.meta.created ?? null,
        __case: `real/${files[i]}`,
      };
    });
    notes.push(`real corpus: ${realFacts.length} facts copied from ${source}`);
  } else {
    notes.push(`real corpus: NOT FOUND (looked in ${source}) — only the adversarial set ran`);
  }

  const corpus = [...realFacts, ...adversarialFacts()];
  notes.push(`corpus: ${corpus.length} facts (${realFacts.length} real + ${corpus.length - realFacts.length} adversarial)`);

  // ------------------------------------------------------------------- direction 1: emit
  const pyEmitted = ctx
    .runPython(REF, { op: 'emit', facts: corpus })
    .emitted_b64.map(unb64);

  const nodeEmitted = corpus.map((f) => factfile.formatFact(f));

  for (let i = 0; i < corpus.length; i += 1) {
    cases.push({
      name: `emit ${corpus[i].__case}`,
      kind: 'bytes',
      expected: pyEmitted[i],
      actual: nodeEmitted[i],
    });
  }
  const wrapped = pyEmitted.filter((t) => /\n {2}\S/.test(t.split('---\n', 2)[1] ?? t)).length;
  const digest = sha(pyEmitted.join('\0'));
  notes.push(`${wrapped} of ${corpus.length} emitted files carry PyYAML's 80-column wrap`);
  notes.push(`corpus sha256 (python side, NUL-joined): ${digest}`);
  notes.push(`corpus sha256 (node side,   NUL-joined): ${sha(nodeEmitted.join('\0'))}`);

  // ------------------------------- direction 2: each runtime parses what the other wrote
  // Node's emit is what Python parses, and Python's emit is what Node parses. Doing it
  // the other way round on both sides is the whole point: a codec that only reads its own
  // output proves nothing about a store Python has been writing for months.
  const pyParsedNode = ctx.runPython(REF, {
    op: 'parse',
    texts_b64: nodeEmitted.map(b64),
  }).parsed;

  for (let i = 0; i < corpus.length; i += 1) {
    const f = corpus[i];
    const expectedMeta = {
      name: f.name,
      description: f.description,
      type: f.type,
      created: f.created ?? null,
      last_recalled: f.last_recalled ?? null,
      links: f.links,
    };
    cases.push({
      name: `python parses node's ${f.__case}`,
      kind: 'json',
      expected: { meta: expectedMeta, body: factfile.pyStrip(f.body) },
      actual: pyParsedNode[i],
    });
    let nodeParsed;
    try {
      nodeParsed = factfile.parseFactText(pyEmitted[i]);
    } catch (e) {
      nodeParsed = { error: `${e.name}: ${e.message}` };
    }
    cases.push({
      name: `node parses python's ${f.__case}`,
      kind: 'json',
      expected: { meta: expectedMeta, body: factfile.pyStrip(f.body) },
      actual: nodeParsed,
    });
  }

  // ---------------------------------------------- a file already on disk with CRLF endings
  // Python's `read_text` translates on the way IN; `readFileSync(p,'utf8')` does not. This
  // arm writes a real CRLF file and reads it through both real read paths, so the
  // translation is exercised rather than simulated.
  const crlfDir = join(ctx.scratch, 'crlf');
  mkdirSync(crlfDir, { recursive: true });
  const crlfSamples = [0, 1, 2, 3].map((k) => corpus[Math.floor((k * corpus.length) / 4)]);
  const crlfPaths = [];
  for (const [k, f] of crlfSamples.entries()) {
    const p = join(crlfDir, `crlf-${k}.md`);
    writeFileSync(p, Buffer.from(factfile.formatFact(f).replace(/\n/g, '\r\n'), 'utf8'));
    crlfPaths.push(p);
  }
  const pyRead = ctx.runPython(REF, { op: 'read_file', paths: crlfPaths }).parsed;
  for (const [k, p] of crlfPaths.entries()) {
    let nodeRead;
    try {
      nodeRead = factfile.parseFactText(factfile.decodeFactBytes(readFileSync(p)));
    } catch (e) {
      nodeRead = { error: `${e.name}: ${e.message}` };
    }
    cases.push({
      name: `crlf on disk: ${crlfSamples[k].__case}`,
      kind: 'json',
      expected: pyRead[k],
      actual: nodeRead,
    });
  }

  // ------------------------------------------------------------------------- the clock
  // `created` and `last_recalled` come from `date.today()`, which is LOCAL, while
  // shift-work's `ts` is UTC. `new Date().toISOString().slice(0,10)` is the wrong clock for
  // seven hours a day at UTC+7. Both runtimes are asked for the same instants under a
  // pinned $TZ, so this compares two answers instead of two beliefs about local time.
  const instants = [
    1755990000, // 2025-08-23T21:40Z — already tomorrow east of UTC
    1756000000, // 2025-08-24T00:26Z — still yesterday west of UTC
    1755950000,
    1767225599, // either side of a new year
    1767225600,
    951782400, // a leap day
    4102444799,
  ];
  const zones = ['Asia/Bangkok', 'UTC', 'America/Los_Angeles', 'Pacific/Kiritimati', 'Pacific/Apia'];
  for (const tz of zones) {
    const py = ctx.runPython(REF, { op: 'today', ts: instants }, { TZ: tz }).dates;
    // A separate Node process: V8 caches the zone, and mutating `process.env.TZ` in-process
    // is not a supported way to ask this question.
    const modUrl = pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'factfile.js')).href;
    const script =
      `const {todayLocal}=await import(${JSON.stringify(modUrl)});` +
      `console.log(JSON.stringify(${JSON.stringify(instants)}.map((t)=>todayLocal(new Date(t*1000)))));`;
    const out = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
      env: { ...process.env, TZ: tz },
      encoding: 'utf8',
    });
    cases.push({ name: `date.today() under TZ=${tz}`, kind: 'json', expected: py, actual: JSON.parse(out) });
  }

  // -------------------------------------------------------------------- the one ruling
  // On Windows Python's `newline=None` turns every `\n` into `\r\n` on the way out, so a
  // fact file Python writes there is CRLF while every byte count the store computes is LF.
  // This port writes LF everywhere. On macOS and Linux `os.linesep` is `\n` and there is
  // nothing to differ, so the ruling is stated as a case that MUST differ from a simulated
  // Windows write — if it ever stops differing, the simulation has drifted and the ruling
  // needs re-reading rather than trusting.
  const sample = factfile.formatFact(corpus[0]);
  cases.push({
    name: 'ruling: node writes LF where python-on-windows writes CRLF',
    kind: 'bytes',
    expected: sample.replace(/\n/g, '\r\n'),
    actual: sample,
    ruling:
      'Python opens fact files with newline=None, so on Windows every one is CRLF while ' +
      'the index budget and the digests are all computed on LF text. This port writes LF ' +
      'on every platform: the CRLF is incidental to newline=None, it already disagrees ' +
      'with the store\'s own arithmetic, and reproducing it would make the same Fact emit ' +
      'different bytes on two machines. Reads stay universal-newline on both sides.',
  });

  return { cases, notes };
}
