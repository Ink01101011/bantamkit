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
 *      replaced. Then the ONE ruled difference: `str.isalpha()` and `\p{L}` are compiled
 *      against different Unicode revisions, so U+1C89 is a letter on one side and unassigned
 *      on the other. Two ruled cases (it reaches the apostrophe guard AND the punctuation
 *      filter, in opposite directions), each with a literal companion naming which side
 *      answers what, plus FOUR NON-ruled ascii twins — two per site, in both polarities —
 *      because a ruling only proves the two differ. Measured: killing `phrases` entirely
 *      leaves the apostrophe-guard ruling GREEN, and only a twin whose expected answer is
 *      non-empty catches that.
 *   5. The per-file record of every `SKILL.md` in the tree — id, relpath, description bytes,
 *      router flag, omission token, malformed token, phrases and the decoded description. The
 *      headline can be right for the wrong reasons; this is the table that says which skill
 *      paid what, and it is where a scan-ORDER difference between `os.walk` and `readdirSync`
 *      would surface even when the sums happen to agree. It is also the only place the two
 *      halves are compared on WHICH version directory each resolved: `duplicate-skill` and
 *      `stale-version` are per-file tokens here, and a runtime that resolved the other
 *      directory would swap them on eight of the twenty-eight rows while the headline moved
 *      by a number a reader would have to look up. `ghost-kit` is the one whose resolved
 *      version serves NOTHING, so it is also where a runtime that resolved over surviving
 *      skills rather than over directories on disk would count a skill the host never serves.
 *
 * Every string travels as base64, in both directions. The descriptions in the fixture carry
 * quotes, backslashes and escaped quotes, which is precisely the material a JSON round trip
 * through two different encoders is most likely to launder.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
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

/**
 * THE ONE RULED DIFFERENCE, and the two sites it reaches.
 *
 * `str.isalpha()` asks CPython's own Unicode database and `\p{L}` asks V8/ICU's, and the two
 * are compiled against different revisions of the standard. Measured 2026-09-05 on this
 * machine by brute force over all 1,112,064 code points (0x0000-0x10FFFF less the surrogate
 * range): CPython 3.12.13 carries `unicodedata.unidata_version` 15.0.0 and Node 25.2.1 carries
 * `process.versions.unicode` 16.0 / ICU 77.1. **4,924 code points disagree for alpha and 5,004
 * for alnum, and every one of them is one-directional** — the port says letter where the
 * reference does not, never the other way round, because 16.0 only ADDED characters. The first
 * is U+1C89 (CYRILLIC CAPITAL LETTER TJE), which is `Cn` — unassigned — in 15.0.0.
 *
 * `_is_letter` is the apostrophe guard, so a letter on one side and not the other flips
 * whether an apostrophe delimits: the REFERENCE finds a phrase here where the port finds
 * none. `_has_content` is the punctuation filter, so it flips the other way: the PORT keeps a
 * phrase the reference drops. Both directions are ruled below, each with a literal companion
 * saying which side answers what. See docs/porting.md, "`str.isalpha()` against `\p{L}`".
 */
const UNICODE_VERSION_TEXTS = [
  // The guard. `'` flanked by U+1C89 on the left and `r`/`n` on the right and left: the
  // reference sees a non-letter flank and delimits, the port sees a letter and does not.
  ["the apostrophe guard", "\u1C89'race condition'\u1C89", ['race condition'], []],
  // The filter. A phrase whose entire content is U+1C89: the reference finds no alnum in it
  // and drops it as punctuation, the port keeps it.
  ['the punctuation filter', '"\u1C89"', [], ['\u1C89']],
];

/**
 * …and the SAME two constructions with ASCII in the place of U+1C89, in both polarities.
 *
 * These are NOT ruled and they are the reason the rulings above are not the whole story: a
 * ruling only proves the two answers DIFFER, so a port whose `phrases` stopped working
 * altogether would keep a ruling green wherever the reference's answer is the non-empty one.
 * MEASURED 2026-09-05 by making `phrases` return `[]` for every input: the punctuation-filter
 * ruling self-detects (it goes `STALE RULING`, because both sides then answer `[]`), the
 * apostrophe-guard ruling does NOT, and only a companion can catch it.
 *
 * So each ruled site gets two twins: one where the shared rule SUPPRESSES the phrase (the two
 * sides agree on `[]`, which says the rule itself is still there) and one where it KEEPS the
 * phrase (the two sides agree on a non-empty list, which is the case a dead reader fails).
 * Without the second of each pair the first is vacuous — it passes for a reader that finds
 * nothing at all, which is precisely the mistake a ruling is blind to.
 */
const UNICODE_VERSION_TWINS = [
  // The guard fires on an ASCII letter exactly as the ruling says it does on U+1C89 for one
  // side: both answer `[]`.
  ["the apostrophe guard, ascii twin, guard fires", "A'race condition'A", []],
  // …and where it does not fire, both find the phrase. This is the one a dead `phrases` fails.
  ["the apostrophe guard, ascii twin, guard does not fire", " 'race condition' ", ['race condition']],
  // The filter keeps an ASCII letter on both sides — the case a dead `phrases` fails.
  ['the punctuation filter, ascii twin, content kept', '"A"', ['A']],
  // …and drops a phrase with no letter and no digit on both sides.
  ['the punctuation filter, ascii twin, filter fires', '"-"', []],
];

/** The reason both cases above are allowed to differ, quoted in the failure when one stops. */
const UNICODE_VERSION_RULING =
  '`str.isalpha()` reads CPython\'s own Unicode database and `\\p{L}` reads V8/ICU\'s, and the ' +
  'two are compiled against different revisions of the standard: measured 2026-09-05 by brute ' +
  'force over all 1,112,064 code points, CPython 3.12.13 carries unidata 15.0.0 and Node ' +
  '25.2.1 carries Unicode 16.0 (ICU 77.1), 4,924 code points disagree for alpha and 5,004 for ' +
  'alnum, and every disagreement is one-directional — the port says letter where the reference ' +
  'does not, never the reverse, because 16.0 only added characters. U+1C89 is the first of ' +
  'them: a letter in 16.0 and unassigned (Cn) in 15.0.0. It reaches two sites. In `_is_letter` ' +
  'it is the apostrophe guard, so the REFERENCE emits a `shared-trigger-phrase` the port does ' +
  'not; in `_has_content` it is the punctuation filter, so the PORT keeps a phrase the ' +
  'reference drops. Not lifted, because the fix is one of two things this program will not ' +
  'do: vendor a 136,104-entry category table into `runtime-ts` and re-vendor it on every ' +
  'CPython upgrade, or make the reference stop asking CPython and consult a table of its own. ' +
  'Neither side is wrong — each is telling the truth about the Unicode version it was built ' +
  'against — and no `SKILL.md` in either measured corpus contains a code point from the ' +
  'disagreeing set. docs/porting.md, "`str.isalpha()` against `\\p{L}`".';

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
  const served = JSON.parse(readFileSync(join(FIXTURE, 'versions.json'), 'utf8'));
  const asMap = (u) => (u === null || u === undefined ? null : new Map(Object.entries(u)));
  const usageMap = asMap;

  // ------------------------------------------------------- 1 & 2. the document, and refusals

  const missing = join(ctx.scratch, 'nowhere-at-all');
  const plainFile = join(repoRoot, 'tools', 'conformance', 'fixtures', 'skill-audit', 'enabled.json');

  // A `SKILL.md` sitting DIRECTLY at the root, which is the one input where the root's own
  // name is the skill's only identity — `Path(root).name` on the reference, `basename` here.
  // The fixture tree cannot hold it (a `cache/SKILL.md` would join every headline), and the
  // spellings below are the ones the two disagreed on: `Path('D/.')` is the path `D` and its
  // name is `D`, where `basename('D/.')` is `'.'`. That name is the key `usage` is looked up
  // by, so the difference is a silently missed call count, not a cosmetic one.
  const rootSkill = join(ctx.scratch, 'root-level-skill');
  mkdirSync(rootSkill, { recursive: true });
  writeFileSync(
    join(rootSkill, 'SKILL.md'),
    '---\nname: root-level-skill\ndescription: Use when a SKILL.md sits at the root itself.\n---\n',
  );

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
    // `versions` — the caller naming the version directory the host serves, which OVERRIDES
    // the byte-order guess. `hash-kit` is the plugin whose two directories are content-hash
    // names, so byte order picks `unknown` and the caller picks the other one: the headline
    // moves by 75 bytes and the two `hash-kit` rows swap their omission tokens.
    ['versions/named', { root: CACHE, enabled, usage, check: null, budget: 1024, versions: served }],
    ['versions/empty', { root: CACHE, enabled, usage, check: null, budget: 1024, versions: {} }],
    // A plugin with no version directory under this root: nothing to resolve, nothing moves.
    ['versions/unknown-plugin', { root: CACHE, enabled, usage, check: null, budget: 1024, versions: { 'no-such-kit@kit-market': '1.0.0' } }],
    // A directory that is not there. Every directory that IS there loses, so the plugin
    // serves nothing and every file it holds is a `stale-version` record — an answer, not a
    // refusal, for the reason `enabled` does not refuse an unknown plugin id either.
    ['versions/absent-directory', { root: CACHE, enabled, usage, check: null, budget: 1024, versions: { 'dup-kit@kit-market': '9.9.9' } }],
    // `Path(root).name`, over the four spellings of one directory. `usage: {}` is what puts
    // the id into the document: every counted skill becomes a `never-invoked` finding, and
    // `findings[].skills` is the only field that carries it.
    ['pathname/plain', { root: rootSkill, enabled: null, usage: {}, check: null, budget: null }],
    ['pathname/dot', { root: `${rootSkill}/.`, enabled: null, usage: {}, check: null, budget: null }],
    ['pathname/dot-slash', { root: `${rootSkill}/./`, enabled: null, usage: {}, check: null, budget: null }],
    ['pathname/dot-slash-slash', { root: `${rootSkill}/.//`, enabled: null, usage: {}, check: null, budget: null }],
    // A `usage` value that is not an integer. `usage.get(id, 0) == 0` on the reference never
    // raises — `0.0 == 0` is True and `2.5 == 0` is False — where `BigInt(2.5)` throws an
    // uncaught RangeError. `pyargs` refuses a fractional value before the MCP handler is
    // entered, but `audit` is an exported entry point and this suite calls it directly.
    ['usage/fractional', { root: CACHE, enabled, usage: { 'solo-check': 2.5, 'trigger-kit:deadlock-hunt': 0.0 }, check: null, budget: null }],
    // The refusals. Each is an ARGUMENT failure and each has its own sentence; a suite that
    // stopped at the first would compare none of the others.
    ['refuse/check', { root: CACHE, enabled: null, usage: null, check: 'phrases', budget: null }],
    ['refuse/budget', { root: CACHE, enabled: null, usage: null, check: null, budget: -1 }],
    ['refuse/missing-root', { root: missing, enabled: null, usage: null, check: null, budget: null }],
    ['refuse/file-root', { root: plainFile, enabled: null, usage: null, check: null, budget: null }],
    // `''` passes JSON-schema `string` and pydantic `str`, so it reaches the module. It used
    // to be `Path(".")` on the reference — an audit of whatever directory the SERVER stood
    // in — and `statSync('')`'s throw here.
    ['refuse/empty-root', { root: '', enabled: null, usage: null, check: null, budget: null }],
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
          versions: asMap(config.versions ?? null),
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

  // ------------------------------------------- 4b. the one ruled difference, and its twins

  const ruledTexts = UNICODE_VERSION_TEXTS.map(([, text]) => text);
  const twinTexts = UNICODE_VERSION_TWINS.map(([, text]) => text);
  const pyRuled = ctx.runPython(REF, { op: 'phrases', texts: [...ruledTexts, ...twinTexts].map(b64) })
    .results.map((r) => r.map(unb64));

  // THE DISCRIMINATOR IS THE TWO TABLES, NOT THE TWO ANSWERS.
  //
  // Asking "did the answers differ, and if so rule it" would be a gate that can never go red:
  // agree and it compares, differ and it rules. So each side is asked what ITS OWN Unicode
  // table says about U+1C89 — a fact about the runtime, not about `phrases` — and the
  // expectation for each side is derived from that. `phrases` can still be wrong while the
  // tables agree, and this catches it.
  //
  // WHY THIS IS NOT DEFENSIVE PROGRAMMING. Both directions have been MEASURED, 2026-09-05:
  // node 18 carries ICU 15.1 and AGREES with CPython 3.12, which turned the ruling stale in
  // CI while every laptop on node 22 stayed green; and CPython 3.14 carries Unicode 16.0 and
  // agrees with a modern Node, which will do the same from the reference's side. The floor
  // moved to node 20 for the first of those. This is the fix for both.
  const pyUnicode = ctx.runPython(REF, { op: 'unicode' });
  const nodeLetter1C89 = /\p{L}/u.test('\u1C89');
  const tablesAgree = pyUnicode.letter_1c89 === nodeLetter1C89;
  notes.push(
    `skillaudit: U+1C89 is a letter to CPython ${pyUnicode.unidata_version}: ` +
      `${pyUnicode.letter_1c89}; to Node ${process.versions.unicode}: ${nodeLetter1C89}. ` +
      `The two tables ${tablesAgree ? 'AGREE, so the U+1C89 cases are compared like any other' : 'DIFFER, so those cases are ruled'}.`,
  );

  for (let i = 0; i < UNICODE_VERSION_TEXTS.length; i += 1) {
    const [label, text, wantPython, wantNode] = UNICODE_VERSION_TEXTS[i];
    // Each side is required to answer as ITS OWN table dictates: the `wantNode` shape when it
    // calls U+1C89 a letter, the `wantPython` shape when it does not.
    const expectPy = pyUnicode.letter_1c89 ? wantNode : wantPython;
    const expectNode = nodeLetter1C89 ? wantNode : wantPython;
    cases.push({
      name: tablesAgree
        ? `phrases: ${label} over U+1C89 (NOT ruled: both tables agree at ${pyUnicode.unidata_version})`
        : `phrases: ${label} over U+1C89: the Unicode version is RULED`,
      kind: 'json',
      expected: pyRuled[i],
      actual: skillaudit.phrases(text),
      ...(tablesAgree ? {} : { ruling: UNICODE_VERSION_RULING }),
    });
    // THE COMPANION. A ruling only proves the two answers differ; this one says what each
    // answer IS, as a literal, so a reference that started calling U+1C89 a letter (a CPython
    // Unicode upgrade) or a port that stopped (an ICU downgrade) fails on its own line rather
    // than behind "they still differ". This is not a refusal-shaped difference — neither side
    // refuses, both answer a list — so there is no refusal bit to compare side to side.
    cases.push({
      name: `phrases: ${label} over U+1C89: the answer each side is required to carry`,
      kind: 'json',
      expected: { python: expectPy, node: expectNode },
      actual: { python: pyRuled[i], node: skillaudit.phrases(text) },
    });
  }
  for (let i = 0; i < UNICODE_VERSION_TWINS.length; i += 1) {
    const [label, text, both] = UNICODE_VERSION_TWINS[i];
    cases.push({
      name: `phrases: ${label} (NOT ruled: the rule is shared, only the table is not)`,
      kind: 'json',
      expected: pyRuled[UNICODE_VERSION_TEXTS.length + i],
      actual: skillaudit.phrases(text),
    });
    // …and the literal both sides are required to reach, so a twin cannot pass because both
    // runtimes broke the same way. This is the case that fails when `phrases` stops finding
    // anything, which no ruling can catch.
    cases.push({
      name: `phrases: ${label}: the answer BOTH sides are required to carry`,
      kind: 'json',
      expected: { python: both, node: both },
      actual: { python: pyRuled[UNICODE_VERSION_TEXTS.length + i], node: skillaudit.phrases(text) },
    });
  }

  // ------------------------------------------------------------------ 5. the per-file table

  for (const [label, on, told] of [
    ['enabled', enabled, null],
    ['everything', null, null],
    ['none', [], null],
    // The per-file table is where `versions` is worth comparing: `duplicate-skill` and
    // `stale-version` are per-file tokens here, so a runtime that ignored the caller's
    // version would swap them on the two `hash-kit` rows.
    ['versions', enabled, served],
  ]) {
    const py = ctx
      .runPython(REF, { op: 'skills', root: CACHE, enabled: on, versions: told })
      .results.map((s) => ({
        ...s,
        id: unb64(s.id),
        relpath: unb64(s.relpath),
        phrases: s.phrases.map(unb64),
        description: unb64(s.description),
      }));
    const node = skillaudit.scan(CACHE, on, asMap(told)).map((s) => ({
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
    `fixture: ${CACHE} — 28 SKILL.md, 20 counted, 2261 catalogue bytes, ` +
      `5 omission records over 8 files`,
    `${cases.length} cases: ${configs.length} documents, ${UNWRAP_VALUES.length} unwrap values, ` +
      `${phraseTexts.length} phrase texts, 4 per-file tables, ` +
      `${UNICODE_VERSION_TEXTS.length} RULED (the Unicode version under \`isalpha\`/\`\\p{L}\`) ` +
      `with ${UNICODE_VERSION_TEXTS.length} literal companions and ${UNICODE_VERSION_TWINS.length} ` +
      `NON-ruled ascii twins, each with its own both-sides literal`,
    'ruled: CPython 3.12.13 unidata 15.0.0 against Node 25.2.1 Unicode 16.0 (ICU 77.1) — ' +
      '4,924 of 1,112,064 code points disagree for alpha and 5,004 for alnum, all one-directional ' +
      '(the port says letter where the reference does not). U+1C89 is the first. See ' +
      'docs/porting.md, "`str.isalpha()` against `\\p{L}`"',
  );
  return { cases, notes };
}
