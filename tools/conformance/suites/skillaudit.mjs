/**
 * skillaudit — the catalogue auditor, Python against Node, byte for byte.
 *
 * THE PROPERTY: over the same tree and the same three caller-supplied inputs, Node emits the
 * BYTE-IDENTICAL JSON document Python emits. That document is not a diagnostic — `skill_audit`
 * hands the model `as_json()` verbatim — so a caller comparing `catalogue_bytes` against a
 * budget it set, or acting on the ids in `findings[].skills`, is acting on these exact bytes.
 * Both halves were written from `assets/tools/skill_audit.json`; this is what makes the claim
 * that they agree something anybody can rerun rather than something two people read and
 * believed.
 *
 * WHAT IS COMPARED
 *   1. `audit()` over the committed fixture tree, in SIXTEEN configurations: the README's own
 *      (enabled + usage + budget), each `check` family, `enabled` omitted and `enabled` empty,
 *      `usage` omitted and `usage` empty, three budgets, and the four refusals. The whole
 *      `as_json()` string is the case, so key order, two-space indent and `ensure_ascii=False`
 *      are all under test and not merely the numbers — and since 2026-09-05 the tree carries a
 *      shared THAI phrase, so `ensure_ascii=False` is a claim these cases can actually check:
 *      before it, every emitted string was ASCII and `ensure_ascii=True` was byte-identical.
 *   2. The three REFUSALS, as strings: an unknown `check`, a negative `budget`, a `root` that
 *      is missing and a `root` that is a file. A port that refused with different words would
 *      hand the model a different recovery instruction, which is a product difference.
 *   3. `unwrap_scalar` over a table the fixture tree deliberately CANNOT hold — a value that
 *      opens a quote and never closes one is a property of the reader, not of a catalogue —
 *      plus every escape edge either runtime could get wrong.
 *   4. `phrases` over the delimiter corpus: contractions, both quote characters, punctuation
 *      -only phrases, unpaired delimiters, non-BMP letters flanking an apostrophe (the class
 *      where `str[i]` is a code POINT on one side and a UTF-16 code UNIT on the other), and
 *      the four fixture descriptions read LITERALLY, which is the reading the unwrap rule
 *      replaced.
 *   5. The per-file record of every `SKILL.md` in the tree — id, relpath, description bytes,
 *      router flag, omission token, malformed token, phrases and the decoded description. The
 *      headline can be right for the wrong reasons; this is the table that says which skill
 *      paid what, and it is where a scan-ORDER difference between `os.walk` and `readdirSync`
 *      would surface even when the sums happen to agree. It is also the only place the two
 *      halves are compared on WHICH version directory each resolved: `duplicate-skill` and
 *      `stale-version` are per-file tokens here, and a runtime that resolved the other
 *      directory would swap them on six of the twenty-six rows while the headline moved by a
 *      number a reader would have to look up.
 *
 * Every string travels as base64, in both directions. The descriptions in the fixture carry
 * quotes, backslashes and escaped quotes, which is precisely the material a JSON round trip
 * through two different encoders is most likely to launder.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skillaudit';
export const summary = 'the catalogue auditor: one JSON document, the same bytes on both sides';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'skillaudit_ref.py');
const FIXTURE = join(here, 'fixtures', 'skill-audit');
const CACHE = join(FIXTURE, 'cache');

const b64 = (text) => Buffer.from(text, 'utf8').toString('base64');
const unb64 = (text) => Buffer.from(text, 'base64').toString('utf8');

/**
 * The unwrap table. Eleven of these are in both runtimes' own test files as literals; they
 * are here as well because a table asserted twice against the same expectation is still one
 * claim, and this is the case that compares the two ANSWERS.
 */
const UNWRAP_VALUES = [
  '"one scalar"',
  "'one scalar'",
  '"a" and "b"',
  "'a' and 'b'",
  '"never closed',
  "'never closed",
  '"ends on an escape\\"',
  '"say \\"hi\\""',
  "'it''s'",
  '"a backslash \\\\"',
  'plain value',
  'a "quote" inside',
  '""',
  '"',
  "''",
  "'",
  '',
  '"\\n is not a newline here"',
  '"trailing backslash \\',
  "'''",
  "''''",
  '"a" ',
  ' "a"',
  '"ends with an escaped backslash \\\\\\"',
  "'don''t' and 'do'",
  '"มีคำไทย"',
  '"emoji 🙂 inside"',
];

/** The delimiter corpus, including the three fixture descriptions read LITERALLY. */
const PHRASE_TEXTS = [
  "the bug don't happen and it didn't catch",
  "quotes a 'shared phrase' here",
  'a"bc"d',
  "a'bc'd",
  'a " - " b',
  "use 'x' - 'y' here",
  "an unpaired ' delimiter",
  'an unpaired " delimiter',
  "'race condition' and \"flaky in prod\" together",
  "s'il vous plaît, 'this one' counts",
  "it's 'a phrase' and it isn't",
  '"" empty and "real"',
  "'' empty and 'real'",
  'nested "outer \'inner\' outer" end',
  '"ตัวอักษรไทย" and "digits 123"',
  '"🙂" alone is punctuation to nobody',
  // The non-BMP flank. `str[i]` is a code POINT on the reference and a UTF-16 code UNIT here,
  // so a reader that indexes units inspects a lone surrogate, calls it not-a-letter, and lets
  // the apostrophe delimit a phrase the reference suppressed. Five shapes: flanked on both
  // sides (no phrase), the same twice over, a non-BMP letter INSIDE the phrase so the SLICE is
  // compared and not only the guard, a non-BMP letter standing where a contraction's letters
  // stand, and a phrase whose whole content is one non-BMP character.
  "𠀀'并发'𠀁",
  "𠀂'并发'𠀃 和 𠀀'并发'𠀁",
  " '并发𠀀并发' ",
  "don𠀀t and didn𠀀t",
  "a'𠀀'b",
];

const LITERAL_DESCRIPTIONS = [
  'kit-market/trigger-kit/1.0.0/skills/quoted-scalar',
  'kit-market/trigger-kit/1.0.0/skills/quoted-edge',
  'kit-market/trigger-kit/1.0.0/skills/quoted-single',
  'kit-market/trigger-kit/1.0.0/skills/folded-note',
];

function literalDescription(rel) {
  const raw = readFileSync(join(CACHE, ...rel.split('/'), 'SKILL.md'), 'utf8');
  const line = raw.split('\n').find((l) => l.startsWith('description:'));
  return line.slice(line.indexOf(':') + 1).trim();
}

export async function run(ctx) {
  const cases = [];
  const notes = [];
  const nodeUrl = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', `${m}.js`)).href;
  const skillaudit = await import(nodeUrl('skillaudit'));

  const enabled = JSON.parse(readFileSync(join(FIXTURE, 'enabled.json'), 'utf8'));
  const usage = JSON.parse(readFileSync(join(FIXTURE, 'usage.json'), 'utf8'));
  const usageMap = (u) => (u === null ? null : new Map(Object.entries(u)));

  // ------------------------------------------------------- 1 & 2. the document, and refusals

  const missing = join(ctx.scratch, 'nowhere-at-all');
  const plainFile = join(repoRoot, 'tools', 'conformance', 'fixtures', 'skill-audit', 'enabled.json');

  const configs = [
    ['readme', { root: CACHE, enabled, usage, check: null, budget: 1024 }],
    ['check/phrase', { root: CACHE, enabled, usage, check: 'phrase', budget: 1024 }],
    ['check/budget', { root: CACHE, enabled, usage, check: 'budget', budget: 1024 }],
    ['check/frontmatter', { root: CACHE, enabled, usage, check: 'frontmatter', budget: 1024 }],
    ['check/all', { root: CACHE, enabled, usage, check: 'all', budget: 1024 }],
    ['enabled/omitted', { root: CACHE, enabled: null, usage, check: null, budget: null }],
    ['enabled/empty', { root: CACHE, enabled: [], usage, check: null, budget: null }],
    ['usage/omitted', { root: CACHE, enabled, usage: null, check: null, budget: null }],
    ['usage/empty', { root: CACHE, enabled, usage: {}, check: null, budget: null }],
    ['budget/none', { root: CACHE, enabled, usage, check: null, budget: null }],
    ['budget/exact', { root: CACHE, enabled, usage, check: null, budget: 2261 }],
    ['budget/zero', { root: CACHE, enabled, usage, check: null, budget: 0 }],
    // The refusals. Each is an ARGUMENT failure and each has its own sentence; a suite that
    // stopped at the first would compare none of the others.
    ['refuse/check', { root: CACHE, enabled: null, usage: null, check: 'phrases', budget: null }],
    ['refuse/budget', { root: CACHE, enabled: null, usage: null, check: null, budget: -1 }],
    ['refuse/missing-root', { root: missing, enabled: null, usage: null, check: null, budget: null }],
    ['refuse/file-root', { root: plainFile, enabled: null, usage: null, check: null, budget: null }],
  ];

  const pyAudits = ctx.runPython(REF, { op: 'audit', cases: configs.map(([, c]) => c) }).results;
  for (let i = 0; i < configs.length; i += 1) {
    const [caseName, config] = configs[i];
    const py = pyAudits[i];
    const expected = 'json' in py ? unb64(py.json) : `${py.error.type}: ${unb64(py.error.message)}`;
    let actual;
    try {
      actual = skillaudit
        .audit(config.root, {
          enabled: config.enabled,
          usage: usageMap(config.usage),
          check: config.check === null ? 'all' : config.check,
          budget: config.budget,
        })
        .asJson();
    } catch (e) {
      // `SkillAuditError` is the reference's class name too, so the refusals compare as one
      // string carrying both the type and the sentence. Any OTHER exception reaching here is
      // a difference and is reported as one rather than swallowed.
      actual = `${e.constructor.name}: ${e.message}`;
    }
    cases.push({ name: `audit/${caseName}`, kind: 'string', expected, actual });
  }

  // ------------------------------------------------------------------- 3. unwrap_scalar

  const pyUnwrap = ctx.runPython(REF, { op: 'unwrap', values: UNWRAP_VALUES.map(b64) }).results;
  for (let i = 0; i < UNWRAP_VALUES.length; i += 1) {
    cases.push({
      name: `unwrap/${JSON.stringify(UNWRAP_VALUES[i])}`,
      kind: 'string',
      expected: unb64(pyUnwrap[i]),
      actual: skillaudit.unwrapScalar(UNWRAP_VALUES[i]),
    });
  }

  // ------------------------------------------------------------------------- 4. phrases

  const phraseTexts = [...PHRASE_TEXTS, ...LITERAL_DESCRIPTIONS.map(literalDescription)];
  const pyPhrases = ctx.runPython(REF, { op: 'phrases', texts: phraseTexts.map(b64) }).results;
  for (let i = 0; i < phraseTexts.length; i += 1) {
    cases.push({
      name: `phrases/${JSON.stringify(phraseTexts[i]).slice(0, 60)}`,
      kind: 'json',
      expected: pyPhrases[i].map(unb64),
      actual: skillaudit.phrases(phraseTexts[i]),
    });
  }

  // ------------------------------------------------------------------ 5. the per-file table

  for (const [label, on] of [
    ['enabled', enabled],
    ['everything', null],
    ['none', []],
  ]) {
    const py = ctx.runPython(REF, { op: 'skills', root: CACHE, enabled: on }).results.map((s) => ({
      ...s,
      id: unb64(s.id),
      relpath: unb64(s.relpath),
      phrases: s.phrases.map(unb64),
      description: unb64(s.description),
    }));
    const node = skillaudit.scan(CACHE, on).map((s) => ({
      id: s.id,
      relpath: s.relpath,
      bytes: s.bytes,
      router: s.router,
      omitted: s.omitted,
      malformed: s.malformed,
      phrases: [...s.phrases],
      description: s.description,
    }));
    cases.push({ name: `skills/${label}`, kind: 'json', expected: py, actual: node });
  }

  notes.push(
    `fixture: ${CACHE} — 26 SKILL.md, 20 counted, 2261 catalogue bytes, ` +
      `5 omission records over 6 files`,
    `${cases.length} cases: ${configs.length} documents, ${UNWRAP_VALUES.length} unwrap values, ` +
      `${phraseTexts.length} phrase texts, 3 per-file tables`,
  );
  return { cases, notes };
}
