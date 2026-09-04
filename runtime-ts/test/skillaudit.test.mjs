/**
 * `skillaudit` and `skill_audit` on the Node side: the catalogue auditor, and the tool.
 *
 * TWO ORACLES, DELIBERATELY, and they are the SAME TWO the reference's
 * `runtime-py/tests/test_skillaudit.py` uses. The committed fixture tree
 * (`tools/conformance/fixtures/skill-audit/`) is the one that matters — nineteen `SKILL.md`
 * laid out the way a plugin cache lays them out, with a README that states, per file, which
 * clause it exists to trigger, and the AUTHOR'S HAND ARITHMETIC beside it. Those numbers were
 * written before either implementation existed, so the nodes below assert this runtime's
 * answer AGAINST them rather than against Python's: a port checked only against the thing it
 * was ported from agrees with it through any shared mistake.
 *
 * The byte-for-byte differential against the Python module IS run, and it is
 * `tools/conformance/suites/skillaudit.mjs`, not this file. What is here is the half a
 * differential cannot see — that a finding which must NOT fire still does not, and that the
 * numbers are the README's rather than merely equal to each other's.
 *
 * WHAT EVERY NODE HERE IS FOR: the fixture tree is engineered so that a plausible-but-wrong
 * reader is VISIBLE rather than merely wrong. Three of the nodes assert that a finding does
 * NOT fire — the contraction pair, the router, and the value that opens and ends with a quote
 * without being one scalar — and those three are the ones that separate a correct
 * implementation from one that looks correct. Simplifying any of them is how the guard is
 * lost.
 */
import assert from 'node:assert/strict';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

import * as skillaudit from '../dist/skillaudit.js';
import { CAP_BYTES, EventLog, SCHEMA_VERSION } from '../dist/eventlog.js';
import { Memory } from '../dist/memory/component.js';
import { buildServer } from '../dist/mcp/server.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const FIXTURE = join(repoRoot, 'tools', 'conformance', 'fixtures', 'skill-audit');
const CACHE = join(FIXTURE, 'cache');

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-skillaudit-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
/** A fresh, empty room for one test: nothing here is shared with any other. */
const room = () => {
  const dir = join(scratch, `r${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const FIXED_MS = 1_756_029_153_412;
const FIXED_TS = '2025-08-24T09:52:33.412Z';

/**
 * The README's table, transcribed. NOT computed from anything the tool does — that is the
 * whole point of having it here, and it is the same transcription the reference's tests hold.
 */
const README_BYTES = {
  'trigger-kit:race-review': 136,
  'trigger-kit:race-debug': 125,
  'trigger-kit:deadlock-hunt': 124,
  'trigger-kit:contraction-a': 104,
  'trigger-kit:contraction-b': 97,
  'trigger-kit:worktree-sweep': 107,
  'trigger-kit:loop-router': 174,
  'trigger-kit:folded-note': 141,
  'trigger-kit:quoted-scalar': 88,
  'trigger-kit:quoted-edge': 84,
  'trigger-kit:quoted-single': 83,
  'trigger-kit:astral-a': 96,
  'trigger-kit:astral-b': 96,
  'trigger-kit:thai-race': 187,
  'trigger-kit:thai-review': 169,
  'frontmatter-kit:misnamed': 84,
  'frontmatter-kit:no-description': 0,
  'dup-kit:echo-check': 112,
  'hash-kit:hashed-check': 162,
  'solo-check': 92,
};
const README_SKILLS = 20;
const README_CATALOGUE_BYTES = 2261;
/** Five RECORDS over six files — `duplicate-skill` carries two, one per multi-version plugin. */
const README_OMISSIONS = 5;
const README_OMITTED_FILES = 8;
const README_FILES = 28;
const README_BUDGET = 1024;

/**
 * The four descriptions in the tree that are NOT pure ASCII, as `[utf8 bytes, code points]`.
 * Before they existed every counted description was ASCII, so the two numbers were equal for
 * all sixteen and nothing in the corpus could tell a byte count from a character count.
 */
const NON_ASCII_BYTES = {
  'trigger-kit:astral-a': [96, 34],
  'trigger-kit:astral-b': [96, 34],
  'trigger-kit:thai-race': [187, 65],
  'trigger-kit:thai-review': [169, 59],
};
/** The phrase the Thai pair shares: the only non-ASCII text the emitted document carries. */
const THAI_PHRASE = 'ภาวะแข่งขัน';

/**
 * What the two WRONG readings of a whole-value quoted scalar answer over the same tree. The
 * literal rule keeps both outer quotes and both `\"` backslashes; the eager rule strips a
 * quote off `quoted-edge`, which is not one scalar at all. Three distinct numbers, so a
 * `catalogue_bytes` that moved says WHICH mistake was made.
 */
const LITERAL_QUOTE_BYTES = 2268;
const EAGER_STRIP_BYTES = 2259;

/**
 * What the two WRONG version rules answer over the same tree, as `[skills, catalogueBytes]`.
 * `MERGED_VERSIONS` is the pre-2026-09-05 dedupe, which resolves nothing and merges the two
 * version directories, so `dup-kit:retired-check` — deleted in `1.1.0` — is resurrected.
 * `INVERTED_TIE_BREAK` resolves the FIRST version directory in byte order instead of the last.
 * Three distinct pairs, so a headline that moved says WHICH mistake was made.
 */
const MERGED_VERSIONS = [21, 2398];
const INVERTED_TIE_BREAK = [21, 2255];
/**
 * …and what the tree answers when the version is resolved over the SURVIVING SKILLS rather
 * than over the directories on disk, which is what both runtimes did until 2026-09-05:
 * `ghost-kit/2.0.0` holds nothing that parses, so it stops being a candidate, `1.0.0` wins by
 * default, and `ghost-kit:present` — which the host does not serve — is counted.
 */
const RESOLVED_OVER_SURVIVORS = [21, 2388];

const enabled = () => JSON.parse(readFileSync(join(FIXTURE, 'enabled.json'), 'utf8'));
const usage = () => JSON.parse(readFileSync(join(FIXTURE, 'usage.json'), 'utf8'));
const usageMap = () => new Map(Object.entries(usage()));

/** The committed tree, audited exactly the way the README says to audit it. */
const fixtureAudit = (overrides = {}) =>
  skillaudit.audit(CACHE, { enabled: enabled(), usage: usageMap(), budget: README_BUDGET, ...overrides });

const kinds = (audit, kind) => audit.findings.filter((f) => f.kind === kind);
const details = (findings) => findings.map((f) => f.detail);
const subjects = (audit) => Object.fromEntries(audit.omissions.map((o) => [o.subject, o]));
const scanned = (root, on = null) => Object.fromEntries(skillaudit.scan(root, on).map((s) => [s.id, s]));

/** One `SKILL.md` in a throwaway tree, written where the caller says. */
function skill(root, relpath, body) {
  const dir = join(root, ...relpath.split('/'));
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'SKILL.md'), body, 'utf8');
  return join(dir, 'SKILL.md');
}

function frontmatter(name, description, extra = '') {
  const lines = ['---', `name: ${name}`];
  if (extra) lines.push(extra);
  lines.push(`description: ${description}`);
  lines.push('---', '', `# ${name}`, '');
  return lines.join('\n');
}

/** Every `SKILL.md` under a directory, the way a `glob` that knows nothing about the reader sees it. */
function everySkillFile(root) {
  return readdirSync(root, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && e.name === 'SKILL.md')
    .map((e) => join(e.parentPath ?? e.path, e.name));
}

/** The raw `description:` line of a fixture file, as written, with no unwrapping at all. */
function literalDescription(relpath) {
  const raw = readFileSync(join(CACHE, ...relpath.split('/'), 'SKILL.md'), 'utf8');
  const line = raw.split('\n').find((l) => l.startsWith('description:'));
  const cut = line.indexOf(':');
  return line.slice(cut + 1).trim();
}

// ------------------------------------------------------ the committed tree's arithmetic

test('the tool answers the headline numbers the README states by hand', () => {
  // They are asserted separately rather than as one tuple so a failure says WHICH of the
  // three moved: a wrong dedupe winner moves only `catalogue_bytes`, a dropped omission moves
  // only `skills`, and a shape check that stopped matching moves all three.
  const audit = fixtureAudit();
  assert.equal(audit.skills, README_SKILLS);
  assert.equal(audit.catalogueBytes, README_CATALOGUE_BYTES);
  assert.equal(audit.omissions.length, README_OMISSIONS);
});

test('counted skills plus omissions account for every skill file on disk', () => {
  // The node that notices a file dropped in SILENCE — the failure mode omissions exist to
  // make impossible. It counts the tree itself rather than trusting the README's twenty-two,
  // and asserts the README's twenty-two too.
  const onDisk = everySkillFile(CACHE);
  assert.equal(onDisk.length, README_FILES);
  const audit = fixtureAudit();
  assert.equal(audit.skills + audit.omissions.reduce((n, o) => n + o.count, 0), onDisk.length);
  assert.equal(audit.omissions.reduce((n, o) => n + o.count, 0), README_OMITTED_FILES);
});

test('every counted skill costs the bytes the README says it does', () => {
  // The headline can be right for the wrong reasons — two errors that cancel — so the
  // per-skill table is checked as a whole mapping. `solo-check` carries no plugin prefix and
  // `frontmatter-kit:no-description` costs zero, and both are identities a reader could get
  // wrong without moving the sum.
  const counted = skillaudit.scan(CACHE, enabled()).filter((s) => s.omitted === null);
  assert.deepEqual(Object.fromEntries(counted.map((s) => [s.id, s.bytes])), README_BYTES);
});

// ------------------------------------------------------------------ shared-trigger-phrase

test('exactly the three shared phrases the README names are reported', () => {
  // `'race condition'` is single-quoted and `"flaky in prod"` is double-quoted on purpose: a
  // reader that implements only one delimiter reports one finding and is visible here rather
  // than in a count that happens to look plausible. The MEMBERSHIP is where the quoted-scalar
  // rule shows — three of the five skills holding `flaky in prod` and one of the three holding
  // `race condition` write their whole description as a quoted YAML scalar. `ภาวะแข่งขัน` is
  // the third and it is the only non-ASCII text the emitted document carries.
  const findings = kinds(fixtureAudit(), skillaudit.KIND_SHARED_PHRASE);
  assert.deepEqual(
    findings.map((f) => [f.detail, [...f.skills]]),
    [
      [
        'flaky in prod',
        [
          'trigger-kit:deadlock-hunt',
          'trigger-kit:quoted-edge',
          'trigger-kit:quoted-scalar',
          'trigger-kit:quoted-single',
          'trigger-kit:race-debug',
        ],
      ],
      ['race condition', ['trigger-kit:quoted-edge', 'trigger-kit:race-debug', 'trigger-kit:race-review']],
      [THAI_PHRASE, ['trigger-kit:thai-race', 'trigger-kit:thai-review']],
    ],
  );
  assert.deepEqual([...new Set(findings.map((f) => f.severity))], ['high']);
});

test('a contraction is not a quoted phrase', () => {
  // THE GUARD. `contraction-a` and `contraction-b` were written so the text BETWEEN their two
  // apostrophes is byte-identical, so a reader that treats every `'` as a delimiter reports a
  // FOURTH finding over that junk string. Four findings is the failure, not three — and the
  // junk string is named as well as counted, because a count alone would also go red for
  // reasons that have nothing to do with apostrophes.
  const findings = kinds(fixtureAudit(), skillaudit.KIND_SHARED_PHRASE);
  assert.equal(findings.length, 3);
  assert.ok(!details(findings).includes('t happen locally and asks why the last run didn'));
  assert.deepEqual(skillaudit.phrases("the bug don't happen and it didn't catch"), []);
});

test('a non-BMP letter flanking an apostrophe suppresses it the same as an ascii one', () => {
  // THE THIRD GUARD, and it guards INDEXING rather than the rule. `astral-a` and `astral-b`
  // write `𠀀'并发'𠀁` and `𠀂'并发'𠀃`: both apostrophes are flanked by letters, so neither
  // delimits and neither skill quotes anything. The letters are above U+FFFF, which is where
  // `text[index]` stops being a character — it is a UTF-16 code UNIT, so the flank test was
  // handed a lone SURROGATE, `\p{L}` was false, and both apostrophes became delimiters that
  // the reference suppressed. Measured 2026-09-05, that invented a `shared-trigger-phrase`
  // over `并发` on this side and none on the reference's, and no fixture in the tree held a
  // non-BMP character to say so.
  const audit = fixtureAudit();
  for (const finding of kinds(audit, skillaudit.KIND_SHARED_PHRASE)) {
    assert.notEqual(finding.detail, '并发');
    assert.ok(!finding.skills.includes('trigger-kit:astral-a'));
    assert.ok(!finding.skills.includes('trigger-kit:astral-b'));
  }
  assert.deepEqual(skillaudit.phrases("\u{20000}'并发'\u{20001}"), []);
  // …and the same text with the flanking letters removed IS a phrase, so this cannot pass
  // because the reader stopped finding phrases at all. The slice is code points too: a
  // UTF-16 slice would cut the astral letter inside the phrase in half.
  assert.deepEqual(skillaudit.phrases(" '并发' "), ['并发']);
  assert.deepEqual(skillaudit.phrases(" '\u{20000}并发' "), ['\u{20000}并发']);
});

test('a router neither raises a finding nor joins one and is still counted', () => {
  // THE SECOND GUARD, and a distinct symptom from the first. `loop-router` quotes
  // `'stale worktree'`, which only `worktree-sweep` also quotes; drop the exemption and a
  // third finding appears over THAT phrase — a different string from the contraction failure,
  // so the two cannot be confused. Its 174 bytes stay in the bill either way.
  const audit = fixtureAudit();
  for (const finding of kinds(audit, skillaudit.KIND_SHARED_PHRASE)) {
    assert.ok(!finding.skills.includes('trigger-kit:loop-router'), finding.detail);
  }
  assert.ok(!details(kinds(audit, skillaudit.KIND_SHARED_PHRASE)).includes('stale worktree'));
  assert.equal(README_BYTES['trigger-kit:loop-router'], 174);
  assert.equal(scanned(CACHE, enabled())['trigger-kit:loop-router'].router, true);
  assert.ok(scanned(CACHE, enabled())['trigger-kit:loop-router'].phrases.includes('stale worktree'));
});

test('a phrase only one skill quotes is not a finding', () => {
  // `'ledger sweep'` is held by `folded-note` alone. One holder is not a collision.
  assert.ok(!details(kinds(fixtureAudit(), skillaudit.KIND_SHARED_PHRASE)).includes('ledger sweep'));
});

test('a disabled plugin phrase cannot join a finding', () => {
  // `off-kit:never-loaded` quotes `'race condition'` and must contribute to nothing. Not the
  // count, not the bytes, and — this node — not the phrase index either. A reader that
  // filtered `enabled` AFTER building the index would still report the right two findings,
  // with three skills in one of them.
  for (const finding of kinds(fixtureAudit(), skillaudit.KIND_SHARED_PHRASE)) {
    assert.ok(!finding.skills.includes('off-kit:never-loaded'), finding.detail);
  }
});

test('a phrase with no letter or digit is ignored', () => {
  // `" - "` between two quoted phrases is punctuation, not a trigger both skills share.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/a', frontmatter('a', 'use "x" - "y" here'));
  skill(dir, 'm/p/1.0.0/skills/b', frontmatter('b', 'use "z" - "w" here'));
  assert.deepEqual(kinds(skillaudit.audit(dir), skillaudit.KIND_SHARED_PHRASE), []);
  assert.deepEqual(skillaudit.phrases('a " - " b'), []);
});

test('double quotes delimit even between letters', () => {
  // The apostrophe rule is the apostrophe's alone. `"` has no contraction to protect.
  assert.deepEqual(skillaudit.phrases('a"bc"d'), ['bc']);
  assert.deepEqual(skillaudit.phrases("a'bc'd"), []);
});

// ------------------------------------------------------- the whole-value quoted scalar

test('a description quoted whole is unwrapped before it is counted or scanned', () => {
  // `quoted-scalar` writes its whole description as one `"..."` YAML scalar. Measured on this
  // tree both ways: the literal reading prices the file at 92 bytes and finds the two junk
  // strings either side of the escapes; the corrected reading prices it at 88 and finds the
  // one phrase. BOTH numbers are asserted, because 88 alone would also be reached by a reader
  // that dropped four bytes for a different reason.
  const note = scanned(CACHE, enabled())['trigger-kit:quoted-scalar'];
  assert.equal(note.bytes, README_BYTES['trigger-kit:quoted-scalar']);
  assert.equal(note.bytes, 88);
  assert.ok(!note.description.startsWith('"') && !note.description.endsWith('"'));
  assert.ok(note.description.startsWith('Use when a suite is '));
  assert.deepEqual(note.phrases, ['flaky in prod']);
  const literal = literalDescription('kit-market/trigger-kit/1.0.0/skills/quoted-scalar');
  assert.equal(Buffer.byteLength(literal, 'utf8'), 92);
  assert.deepEqual(skillaudit.phrases(literal), [
    'Use when a suite is \\',
    ' and the whole description is one quoted YAML scalar.',
  ]);
});

test('a value that merely opens and ends with a quote is not one scalar', () => {
  // THE THIRD GUARD, and the reason unwrapping is not `startsWith` and `endsWith`.
  // `quoted-edge` opens with `"race condition"` and ends with `"flaky in prod"`, so its first
  // and last characters are both `"` and it is still not one scalar — its opening quote closes
  // at index 15. An eager reader strips those two characters, welds the middle into one junk
  // phrase, loses BOTH of its real phrases and answers 2259.
  const edge = scanned(CACHE, enabled())['trigger-kit:quoted-edge'];
  assert.equal(edge.bytes, README_BYTES['trigger-kit:quoted-edge']);
  assert.equal(edge.bytes, 84);
  assert.ok(edge.description.startsWith('"') && edge.description.endsWith('"'));
  assert.deepEqual(edge.phrases, ['race condition', 'flaky in prod']);
  assert.equal(skillaudit.unwrapScalar(edge.description), edge.description);
  for (const finding of kinds(fixtureAudit(), skillaudit.KIND_SHARED_PHRASE)) {
    if (finding.detail === 'race condition' || finding.detail === 'flaky in prod') {
      assert.ok(finding.skills.includes('trigger-kit:quoted-edge'), finding.detail);
    }
  }
});

test('a single quoted scalar unwraps and a doubled apostrophe is one apostrophe', () => {
  // `quoted-single` pins YAML's OTHER escape, and the order the two rules compose in. Inside a
  // `'` scalar, `''` is one literal apostrophe — so it does not close the scalar, and once
  // unwrapped it is the `'` of `it's`, which the contraction guard then protects. The literal
  // reading keeps three characters nobody pays for (86, not 83) and reports two junk phrases
  // torn out of the middle of the description.
  const single = scanned(CACHE, enabled())['trigger-kit:quoted-single'];
  assert.equal(single.bytes, README_BYTES['trigger-kit:quoted-single']);
  assert.equal(single.bytes, 83);
  assert.ok(single.description.includes("says it's "));
  assert.ok(!single.description.includes("''"));
  assert.deepEqual(single.phrases, ['flaky in prod']);
  const literal = literalDescription('kit-market/trigger-kit/1.0.0/skills/quoted-single');
  assert.equal(Buffer.byteLength(literal, 'utf8'), 86);
  assert.equal(skillaudit.phrases(literal).length, 3);
});

test('the two wrong readings of a quoted scalar answer two other byte counts', () => {
  // The headline separates all three readings, so a regression names itself. 1713 is correct,
  // 1558 keeps the quotes and the backslashes, 1549 strips one off a value that is not a
  // scalar. The three are asserted as DISTINCT rather than merely unequal to the right one,
  // because two mistakes that happened to agree would hide behind a single `!==`.
  assert.equal(fixtureAudit().catalogueBytes, README_CATALOGUE_BYTES);
  assert.equal(README_CATALOGUE_BYTES, 2261);
  assert.equal(new Set([README_CATALOGUE_BYTES, LITERAL_QUOTE_BYTES, EAGER_STRIP_BYTES]).size, 3);
  const extra = Object.entries({
    'trigger-kit:quoted-scalar': 'kit-market/trigger-kit/1.0.0/skills/quoted-scalar',
    'trigger-kit:quoted-edge': 'kit-market/trigger-kit/1.0.0/skills/quoted-edge',
    'trigger-kit:quoted-single': 'kit-market/trigger-kit/1.0.0/skills/quoted-single',
  }).reduce((sum, [id, rel]) => sum + Buffer.byteLength(literalDescription(rel), 'utf8') - README_BYTES[id], 0);
  assert.equal(README_CATALOGUE_BYTES + extra, LITERAL_QUOTE_BYTES);
});

/**
 * The rule as a table, including the case the fixture tree deliberately cannot hold.
 *
 * `"ends on an escape\"` OPENS a scalar and never closes one — its final quote is escaped —
 * and is therefore a LITERAL. That is a choice, stated here rather than left to whoever reads
 * it: there is no end point to unwrap to, so guessing one would delete a byte the reader
 * cannot prove is YAML's. It is not a `frontmatter-malformed` finding either, because those
 * three tokens name failures of the BLOCK and this value still reads, still costs bytes and
 * still contributes whatever phrases pair inside it.
 */
const UNWRAP_TABLE = [
  ['"one scalar"', 'one scalar'],
  ["'one scalar'", 'one scalar'],
  ['"a" and "b"', '"a" and "b"'],
  ["'a' and 'b'", "'a' and 'b'"],
  ['"never closed', '"never closed'],
  ["'never closed", "'never closed"],
  ['"ends on an escape\\"', '"ends on an escape\\"'],
  ['"say \\"hi\\""', 'say "hi"'],
  ["'it''s'", "it's"],
  ['"a backslash \\\\"', 'a backslash \\'],
  ['plain value', 'plain value'],
  ['a "quote" inside', 'a "quote" inside'],
  ['""', ''],
  ['"', '"'],
];

for (const [value, unwrapped] of UNWRAP_TABLE) {
  test(`unwrapScalar is the whole-value rule and nothing wider: ${JSON.stringify(value)}`, () => {
    assert.equal(skillaudit.unwrapScalar(value), unwrapped);
  });
}

test('a quoted name and a quoted router flag unwrap too', () => {
  // One rule at one place, because it is a fact about YAML scalars and not about one key.
  // `name: "s"` is the name `s`, so it is not a `name-mismatch`; and `router: "true"` is a
  // router, so its phrases stay out of the index. A reader that unwrapped `description:` alone
  // would answer a spurious finding for the first and a real one for the second.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/s', '---\nname: "s"\nrouter: "true"\ndescription: quotes a \'shared phrase\' here\n---\n');
  skill(dir, 'm/p/1.0.0/skills/t', frontmatter('t', "also a 'shared phrase' here"));
  const audit = skillaudit.audit(dir);
  assert.deepEqual(kinds(audit, skillaudit.KIND_NAME_MISMATCH), []);
  assert.deepEqual(kinds(audit, skillaudit.KIND_SHARED_PHRASE), []);
  assert.equal(audit.skills, 2);
});

test('a scalar quoted whole and folded over lines is unwrapped after the fold', () => {
  // The closing quote is not on the line the value starts on, so the order is not optional. A
  // reader that unwrapped each line as it arrived would find no closing quote on the first and
  // strip nothing, then leave the second line's quote in the middle of the value.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/s', '---\nname: s\ndescription: "one \'kept phrase\'\n  and two"\n---\n');
  assert.equal(skillaudit.audit(dir).catalogueBytes, "one 'kept phrase' and two".length);
  assert.deepEqual(skillaudit.scan(dir)[0].phrases, ['kept phrase']);
});

// ------------------------------------------------------------------ catalogue-over-budget

test('the budget finding states the overage and only fires when a budget is given', () => {
  // 2261 against 1024 is 1237 over; no budget at all is not a budget of zero.
  const over = kinds(fixtureAudit(), skillaudit.KIND_OVER_BUDGET);
  assert.equal(over.length, 1);
  assert.equal(over[0].detail, '2261 > 1024, over by 1237');
  assert.equal(over[0].severity, 'high');
  assert.deepEqual(over[0].skills, []);
  assert.deepEqual(kinds(fixtureAudit({ budget: null }), skillaudit.KIND_OVER_BUDGET), []);
  assert.deepEqual(kinds(fixtureAudit({ budget: README_CATALOGUE_BYTES }), skillaudit.KIND_OVER_BUDGET), []);
});

// ------------------------------------------------------------------------- never-invoked

test('the three uncalled skills are reported and absent means zero', () => {
  // Two ways of being zero, and the difference must not matter. `deadlock-hunt` and
  // `solo-check` are in `usage.json` with the value `0`; `no-description` is ABSENT from it,
  // which means zero and not unknown. A reader that only looked at present keys reports two.
  const never = kinds(fixtureAudit(), skillaudit.KIND_NEVER_INVOKED);
  assert.deepEqual(
    never.map((f) => f.skills[0]),
    ['frontmatter-kit:no-description', 'solo-check', 'trigger-kit:deadlock-hunt'],
  );
  assert.deepEqual([...new Set(never.map((f) => f.severity))], ['low']);
  assert.ok(!('frontmatter-kit:no-description' in usage()));
});

test('usage omitted reports nothing never-invoked and usage empty reports everything', () => {
  // An absent measurement is not a measurement of zero. Reporting every skill as
  // never-invoked because the caller supplied no counts would be an assertion about data this
  // tool was never given. An EMPTY map is a different thing: it says the caller measured and
  // found nothing, and every counted skill is then a finding.
  assert.deepEqual(kinds(fixtureAudit({ usage: null }), skillaudit.KIND_NEVER_INVOKED), []);
  assert.equal(kinds(fixtureAudit({ usage: new Map() }), skillaudit.KIND_NEVER_INVOKED).length, README_SKILLS);
});

test('usage is keyed by the id the host uses and has no version in it', () => {
  // `dup-kit:echo-check` has 7 calls under one key though two copies are on disk.
  assert.equal(usage()['dup-kit:echo-check'], 7);
  const never = kinds(fixtureAudit(), skillaudit.KIND_NEVER_INVOKED).map((f) => f.skills[0]);
  assert.ok(!never.includes('dup-kit:echo-check'));
});

// ----------------------------------------------------------------- frontmatter-malformed

test('both malformed blocks are reported and only one of them is counted', () => {
  // The two cases differ in whether the skill survives, and that is the whole point.
  // `broken-open` is opened and never closed: nothing in it can be trusted, so it is also
  // omitted and reaches neither `skills` nor `catalogue_bytes`. `no-description` parses and
  // carries no `description:`, so it IS a skill — one costing zero bytes. `ghost-kit:broken`
  // is a third of the first kind, reported even though its plugin has no counted skill at
  // all: it is the only file under the version directory that was RESOLVED, which is what
  // makes that directory the resolved one.
  const bad = kinds(fixtureAudit(), skillaudit.KIND_FRONTMATTER);
  assert.deepEqual(
    bad.map((f) => [f.skills[0], f.detail]),
    [
      ['frontmatter-kit:broken-open', skillaudit.BAD_UNTERMINATED],
      ['frontmatter-kit:no-description', skillaudit.BAD_NO_DESCRIPTION],
      ['ghost-kit:broken', skillaudit.BAD_UNTERMINATED],
    ],
  );
  assert.deepEqual([...new Set(bad.map((f) => f.severity))], ['medium']);
  assert.equal(README_BYTES['frontmatter-kit:no-description'], 0);
  assert.ok(!('frontmatter-kit:broken-open' in README_BYTES));
});

test('a file with no frontmatter block at all is the third malformed case', () => {
  // A `SKILL.md` that is only prose. Named as its own token, not folded into the other two.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/prose', '# Prose\n\nNo frontmatter here.\n');
  const audit = skillaudit.audit(dir);
  assert.deepEqual(
    kinds(audit, skillaudit.KIND_FRONTMATTER).map((f) => [f.skills[0], f.detail]),
    [['p:prose', skillaudit.BAD_NO_BLOCK]],
  );
  assert.equal(audit.skills, 0);
  assert.equal(subjects(audit)[skillaudit.OMIT_UNPARSED].count, 1);
});

// ---------------------------------------------------------------------- name-mismatch

test('the frontmatter name that disagrees with its directory is the one that is wrong', () => {
  // The host loads by directory, so the id stays `frontmatter-kit:misnamed`. The finding
  // carries the frontmatter's spelling as its detail — the fact a caller needs in order to fix
  // the file — and the directory's spelling is already in `skills`.
  const mismatch = kinds(fixtureAudit(), skillaudit.KIND_NAME_MISMATCH);
  assert.deepEqual(
    mismatch.map((f) => [f.skills[0], f.detail, f.severity]),
    [['frontmatter-kit:misnamed', 'renamed-elsewhere', 'medium']],
  );
  assert.ok('frontmatter-kit:misnamed' in README_BYTES);
});

test('a name that matches its directory is not a finding', () => {
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/agrees', frontmatter('agrees', 'a description'));
  assert.deepEqual(kinds(skillaudit.audit(dir), skillaudit.KIND_NAME_MISMATCH), []);
});

// --------------------------------------------------------------------------- omissions

test('the five omission subjects carry the counts, bytes and paths the README states', () => {
  // One record per subject, in a fixed order, each naming the file behind it. `size` is what
  // the omission COST the catalogue: 112 bytes that enabling `off-kit` would add, 44 + 87 for
  // the two displaced copies, 137 + 127 for the two skills the resolved version does not
  // serve. It is `0` for the three files whose description could not be read at all — an
  // unknowable cost, stated rather than guessed.
  const audit = fixtureAudit();
  assert.deepEqual(
    audit.omissions.map((o) => [o.subject, o.count, o.size]),
    [
      [skillaudit.OMIT_NOT_ENABLED, 1, 112],
      [skillaudit.OMIT_DUPLICATE, 2, 131],
      [skillaudit.OMIT_STALE_VERSION, 2, 264],
      [skillaudit.OMIT_UNREADABLE, 1, 0],
      [skillaudit.OMIT_UNPARSED, 2, 0],
    ],
  );
  const by = subjects(audit);
  assert.equal(by[skillaudit.OMIT_NOT_ENABLED].what, 'kit-market/off-kit/1.0.0/skills/never-loaded/SKILL.md');
  assert.equal(
    by[skillaudit.OMIT_DUPLICATE].what,
    'kit-market/dup-kit/1.0.0/skills/echo-check/SKILL.md, ' +
      'kit-market/hash-kit/0120fb83da5d/skills/hashed-check/SKILL.md',
  );
  assert.equal(
    by[skillaudit.OMIT_STALE_VERSION].what,
    'kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md, ' +
      'kit-market/ghost-kit/1.0.0/skills/present/SKILL.md',
  );
  assert.equal(by[skillaudit.OMIT_UNREADABLE].what, 'kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md');
  assert.equal(
    by[skillaudit.OMIT_UNPARSED].what,
    'kit-market/frontmatter-kit/2.3.1/skills/broken-open/SKILL.md, ' +
      'kit-market/ghost-kit/2.0.0/skills/broken/SKILL.md',
  );
});

test('an invalid utf8 byte is a record and not a crash and not a replacement character', () => {
  // `bad-bytes` ends its description line with a lone `0x80`. A permissive decoder would
  // substitute `U+FFFD` and count a description nobody wrote — which is exactly what
  // `Buffer.toString('utf8')` does, and the reason this reader holds a `fatal: true`
  // `TextDecoder`. A strict one that let the error escape would refuse the whole audit over
  // one file. This is the third option: the file is a record and the other twenty-seven are
  // still answered.
  const raw = readFileSync(join(CACHE, 'kit-market/frontmatter-kit/2.3.1/skills/bad-bytes/SKILL.md'));
  assert.ok(raw.includes(0x80));
  assert.throws(() => new TextDecoder('utf-8', { fatal: true }).decode(raw), TypeError);
  assert.ok(raw.toString('utf8').includes('�'), 'the permissive decoder repairs it, which is the mistake');
  const audit = fixtureAudit();
  assert.equal(subjects(audit)[skillaudit.OMIT_UNREADABLE].count, 1);
  assert.ok(!audit.asJson().includes('�'));
});

test('an omission subject with no members is not reported at all', () => {
  // A clean tree has an EMPTY omission list, not five records of zero.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/fine', frontmatter('fine', 'a description'));
  assert.deepEqual(skillaudit.audit(dir).omissions, []);
});

// -------------------------------------------------------------------- enabled and identity

test('enabled omitted counts everything and enabled empty counts no plugin skill', () => {
  // Omitted and empty are different states. Omitted: every skill under the root counts,
  // disabled plugin and all — twenty-one. Empty: no plugin is switched on, so only the skill
  // outside a plugin survives. The version rule runs in BOTH cases: `off-kit` has one version
  // directory, so switching it on adds exactly one skill and not two.
  const everything = skillaudit.audit(CACHE, { usage: usageMap() });
  assert.equal(everything.skills, README_SKILLS + 1);
  assert.ok(!(skillaudit.OMIT_NOT_ENABLED in subjects(everything)));
  const noneOn = skillaudit.audit(CACHE, { enabled: [], usage: usageMap() });
  assert.equal(noneOn.skills, 1);
  // Twenty-four: the twenty-eight files, less `solo-check` (still counted), less the three
  // whose own file failed first — an unreadable byte and two unparsable blocks outrank a
  // plugin that is merely switched off, because none of them can say what enabling it would
  // cost. A plugin that is off never reaches the version rule either, so no `stale-version`
  // and no duplicate here.
  assert.equal(subjects(noneOn)[skillaudit.OMIT_NOT_ENABLED].count, README_FILES - 4);
  assert.ok(!(skillaudit.OMIT_STALE_VERSION in subjects(noneOn)));
  assert.ok(!(skillaudit.OMIT_DUPLICATE in subjects(noneOn)));
  assert.equal(noneOn.skills + noneOn.omissions.reduce((n, o) => n + o.count, 0), README_FILES);
  // The one record here holds twenty-four paths, which is the only place in this file that
  // scan ORDER is visible. It is path order, sorted, because two machines hand back directory
  // entries in two different orders and the document is byte-compared.
  const listed = subjects(noneOn)[skillaudit.OMIT_NOT_ENABLED].what.split(', ');
  assert.deepEqual(listed, [...listed].sort());
  assert.equal(listed.length, README_FILES - 4);
});

test('a skill outside a plugin keeps its bare name and enabled cannot speak to it', () => {
  // `personal/skills/solo-check/` is four segments below the root, not six. No marketplace,
  // plugin or version can be read off that path, so its id is the bare directory name — and a
  // plugin list cannot disable a skill that belongs to no plugin.
  assert.equal(README_BYTES['solo-check'], 92);
  const never = kinds(fixtureAudit(), skillaudit.KIND_NEVER_INVOKED).map((f) => f.skills[0]);
  assert.ok(never.includes('solo-check'));
  assert.equal(skillaudit.audit(CACHE, { enabled: [] }).skills, 1);
});

test('a path that is not the plugin shape is a skill outside a plugin', () => {
  // Six segments AND `skills` fourth. Anything else is identified by directory alone.
  const dir = room();
  skill(dir, 'm/p/1.0.0/plugins/deep', frontmatter('deep', 'wrong fourth segment'));
  skill(dir, 'm/p/1.0.0/skills/nested/more', frontmatter('more', 'seven segments'));
  const audit = skillaudit.audit(dir, { usage: new Map() });
  assert.deepEqual(
    kinds(audit, skillaudit.KIND_NEVER_INVOKED)
      .map((f) => f.skills[0])
      .sort(),
    ['deep', 'more'],
  );
});

// ----------------------------------------- the version resolution and the dedupe

test('the version directory that did not win is omitted whole', () => {
  // `1.1.0` is resolved for `dup-kit`, so BOTH files under `1.0.0` are omitted. The two
  // `echo-check` descriptions differ in length on purpose, so WHICH directory was resolved is
  // visible in `catalogueBytes` and not only in the omission record.
  const audit = fixtureAudit();
  assert.equal(audit.catalogueBytes, README_CATALOGUE_BYTES);
  assert.equal(README_BYTES['dup-kit:echo-check'], 112);
  const by = subjects(audit);
  assert.ok(by[skillaudit.OMIT_DUPLICATE].what.includes('kit-market/dup-kit/1.0.0/skills/echo-check/SKILL.md'));
  assert.ok(by[skillaudit.OMIT_STALE_VERSION].what.startsWith('kit-market/dup-kit/1.0.0/'));
});

test('a skill the resolved version dropped is a stale-version and not resurrected', () => {
  // THE DEFECT THIS RULE FIXES, over the committed tree.
  // `dup-kit/1.0.0/skills/retired-check/` exists and `1.1.0` does not have it. Deduping by the
  // (marketplace, plugin, name) triple has nothing to displace it with, so it counts a skill
  // the newer release DELETED. Measured 2026-09-05 on a real plugin cache, that is nine of
  // `kkskills-essentials`'s `0.4.0` skills — 31 skills / 9,280 bytes against a host serving
  // 22 / 3,396. Four independent things say so over this tree, and all four are asserted,
  // because a headline alone cannot distinguish "the rule works" from "two errors cancelled".
  assert.ok(existsSync(join(CACHE, 'kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md')));
  assert.ok(!existsSync(join(CACHE, 'kit-market/dup-kit/1.1.0/skills/retired-check')));
  const audit = fixtureAudit();
  assert.deepEqual([audit.skills, audit.catalogueBytes], [README_SKILLS, README_CATALOGUE_BYTES]);
  assert.notDeepEqual([audit.skills, audit.catalogueBytes], MERGED_VERSIONS);
  const stale = subjects(audit)[skillaudit.OMIT_STALE_VERSION];
  assert.deepEqual([stale.count, stale.size], [2, 264]);
  assert.ok(stale.what.includes('kit-market/dup-kit/1.0.0/skills/retired-check/SKILL.md'));
  assert.ok(!audit.findings.some((f) => f.skills.includes('dup-kit:retired-check')));
  const race = kinds(audit, skillaudit.KIND_SHARED_PHRASE).filter((f) => f.detail === 'race condition');
  assert.equal(race.length, 1);
  assert.ok(!race[0].skills.includes('dup-kit:retired-check'));
});

test('the resolved version is the directory on disk over the committed tree', () => {
  // `ghost-kit` in the committed tree, which is the same rule under the differential.
  // `ghost-kit/2.0.0/skills/` holds one file and it does not parse, so the plugin serves
  // NOTHING; `ghost-kit/1.0.0/skills/present/` is readable and is not what the host serves.
  // Resolving over surviving skills counts `present` and answers 21 skills / 2388 bytes —
  // which BOTH runtimes did, and both agreed, so the cross-runtime suite compared 71 cases
  // and found nothing.
  assert.ok(existsSync(join(CACHE, 'kit-market/ghost-kit/2.0.0/skills/broken/SKILL.md')));
  assert.ok(!existsSync(join(CACHE, 'kit-market/ghost-kit/2.0.0/skills/present')));
  const audit = fixtureAudit();
  assert.deepEqual([audit.skills, audit.catalogueBytes], [README_SKILLS, README_CATALOGUE_BYTES]);
  assert.notDeepEqual([audit.skills, audit.catalogueBytes], RESOLVED_OVER_SURVIVORS);
  assert.ok(!('ghost-kit:present' in README_BYTES));
  assert.ok(subjects(audit)[skillaudit.OMIT_STALE_VERSION].what.includes('ghost-kit/1.0.0/skills/present'));
  assert.ok(!audit.findings.some((f) => f.skills.includes('ghost-kit:present')));
  // The resolved directory serves nothing, and the ONE file under it is still reported, which
  // is how an operator sees which directory was read.
  assert.ok(kinds(audit, skillaudit.KIND_FRONTMATTER).some((f) => f.skills[0] === 'ghost-kit:broken'));
  assert.ok(subjects(audit)[skillaudit.OMIT_UNPARSED].what.includes('ghost-kit/2.0.0/skills/broken'));
});

test('a version directory with no readable skill in it still wins', () => {
  // THE RESURRECTION DEFECT THROUGH THE OTHER DOOR, and the differential was blind to it: a
  // version directory exists on disk whether or not anything under it can be read, and the
  // host serves the one it serves. Resolving over the SURVIVING SKILLS instead — which is
  // what both runtimes did until 2026-09-05 — means an empty `2.0.0` is never a candidate,
  // `1.0.0` wins by default, and the audit answers from a directory the host is not serving
  // with no omission, no finding and no mention of `2.0.0` in the document.
  //
  // Four shapes a version directory can be invisible in: empty, holding an unreadable file,
  // holding an unparsable one, and holding only an empty skill subdirectory. In every one
  // `2.0.0` wins and `1.0.0`'s skill is a `stale-version` — the file is on disk, the host
  // does not serve it, and the plugin's counted skills are zero.
  const cases = {
    empty: (root) => mkdirSync(join(root, 'm/p/2.0.0/skills'), { recursive: true }),
    unreadable: (root) => {
      mkdirSync(join(root, 'm/p/2.0.0/skills/x'), { recursive: true });
      writeFileSync(
        join(root, 'm/p/2.0.0/skills/x/SKILL.md'),
        Buffer.concat([Buffer.from('---\nname: x\ndescription: bad '), Buffer.from([0x80]), Buffer.from(' byte\n---\n')]),
      );
    },
    unparsable: (root) => {
      mkdirSync(join(root, 'm/p/2.0.0/skills/x'), { recursive: true });
      writeFileSync(join(root, 'm/p/2.0.0/skills/x/SKILL.md'), '---\nname: x\n');
    },
    'empty-skill-directory': (root) => mkdirSync(join(root, 'm/p/2.0.0/skills/x'), { recursive: true }),
  };
  for (const [name, build] of Object.entries(cases)) {
    const dir = room();
    skill(dir, 'm/p/1.0.0/skills/served', frontmatter('served', 'the older copy'));
    build(dir);
    const audit = skillaudit.audit(dir);
    assert.equal(audit.skills, 0, name);
    assert.equal(audit.catalogueBytes, 0, name);
    const stale = subjects(audit)[skillaudit.OMIT_STALE_VERSION];
    assert.ok(stale !== undefined, name);
    assert.deepEqual([stale.count, stale.size], [1, 'the older copy'.length], name);
    assert.equal(stale.what, 'm/p/1.0.0/skills/served/SKILL.md', name);
    assert.ok(!(skillaudit.OMIT_DUPLICATE in subjects(audit)), name);
    // …and the sum still accounts for every file on disk.
    assert.equal(
      audit.skills + audit.omissions.reduce((n, o) => n + o.count, 0),
      everySkillFile(dir).length,
      name,
    );
  }
});

test('a directory that is not a version directory declares no version', () => {
  // The candidate is `<marketplace>/<plugin>/<version>/skills`, and nothing wider: four
  // segments AND the fourth spelled `skills`, the same shape a counted skill's path matches.
  // A plugin directory with a stray sibling — notes, a `.git`, a half-extracted download —
  // must not become a version that outranks the real one and empties the plugin.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/served', frontmatter('served', 'the only copy'));
  for (const stray of ['m/p/zzz-notes', 'm/p/9.9.9/not-skills', 'm/zzz-loose/skills', 'm/p/1.0.0/docs']) {
    mkdirSync(join(dir, stray), { recursive: true });
  }
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 1);
  assert.equal(audit.catalogueBytes, 'the only copy'.length);
  assert.deepEqual(audit.omissions, []);
});

test('the two version subjects split on whether the resolved version has the name', () => {
  // One rule, two subjects, and folding them together is what hid the defect. `kept` is
  // dropped from `2.0.0`, `shared` is not. Both live under a version directory that did not
  // win; only one has a counted skill standing in for it. Reporting both as `duplicate-skill`
  // would inflate the duplicate count by every skill a release removed and make the removal
  // invisible, which is exactly how the defect survived.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/shared', frontmatter('shared', 'old shared'));
  skill(dir, 'm/p/1.0.0/skills/kept', frontmatter('kept', 'dropped in 2.0.0'));
  skill(dir, 'm/p/2.0.0/skills/shared', frontmatter('shared', 'new shared'));
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 1);
  assert.equal(audit.catalogueBytes, 'new shared'.length);
  const by = subjects(audit);
  assert.deepEqual(
    [by[skillaudit.OMIT_DUPLICATE].count, by[skillaudit.OMIT_DUPLICATE].size],
    [1, 'old shared'.length],
  );
  assert.equal(by[skillaudit.OMIT_DUPLICATE].what, 'm/p/1.0.0/skills/shared/SKILL.md');
  assert.equal(by[skillaudit.OMIT_STALE_VERSION].what, 'm/p/1.0.0/skills/kept/SKILL.md');
  assert.equal(by[skillaudit.OMIT_STALE_VERSION].size, 'dropped in 2.0.0'.length);
});

test('every version directory but one is skipped however many there are', () => {
  // The resolution is per PLUGIN, so three stale directories cost three omissions.
  const dir = room();
  for (const version of ['1.0.0', '2.0.0', '3.0.0', '4.0.0']) {
    skill(dir, `m/p/${version}/skills/s`, frontmatter('s', version));
    skill(dir, `m/p/${version}/skills/only-${version}`, frontmatter('x', version));
  }
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 2);
  assert.equal(audit.catalogueBytes, 2 * '4.0.0'.length);
  const by = subjects(audit);
  assert.equal(by[skillaudit.OMIT_DUPLICATE].count, 3);
  assert.equal(by[skillaudit.OMIT_STALE_VERSION].count, 3);
  assert.equal(audit.skills + audit.omissions.reduce((n, o) => n + o.count, 0), 8);
});

test('a version directory name that is not a version takes the same byte order', () => {
  // `hash-kit` spells its two directories `0120fb83da5d` and `unknown`. That shape is real:
  // `frontend-design` on this machine has nine content-hash directories plus the literal
  // `unknown`, and semver has nothing to compare there. Byte order is total over all of them —
  // `u` after `0` — so `unknown` is resolved. The answer is deterministic and it is ARBITRARY,
  // which is the honest state and the reason the fixture pins the determinism.
  assert.equal(README_BYTES['hash-kit:hashed-check'], 162);
  const audit = fixtureAudit();
  assert.ok(
    subjects(audit)[skillaudit.OMIT_DUPLICATE].what.includes(
      'kit-market/hash-kit/0120fb83da5d/skills/hashed-check/SKILL.md',
    ),
  );
  assert.equal(audit.catalogueBytes - 162 + 87, 2186);
});

test('the tie-break is byte order and the semver case it gets wrong is stated', () => {
  // A KNOWN LIMITATION, pinned here and deliberately not in the shared fixture. Byte order
  // resolves `9.0.0` over `10.0.0`. A semver comparison would be right, would be a second thing
  // the two runtimes must agree about character for character, and would still leave the
  // content-hash case above undecided; the byte order is free, and the omission record always
  // names the loser. Pinning it HERE says out loud what this half does, and it is the same
  // sentence `test_skillaudit.py` pins for the other half.
  const dir = room();
  skill(dir, 'm/p/9.0.0/skills/s', frontmatter('s', 'nine'));
  skill(dir, 'm/p/10.0.0/skills/s', frontmatter('s', 'ten, which is longer'));
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 1);
  assert.equal(audit.catalogueBytes, 'nine'.length);
  assert.ok(subjects(audit)[skillaudit.OMIT_DUPLICATE].what.startsWith('m/p/10.0.0/'));
});

test('the version is resolved per plugin and never across them', () => {
  // A newer version of one plugin cannot displace another plugin's skill. `one` is at `2.0.0`
  // and `two` at `1.0.0`; both have a skill called `s`. Resolving one version per MARKETPLACE,
  // or globally, would drop `two:s` on a version number that has nothing to do with it.
  const dir = room();
  skill(dir, 'm/one/2.0.0/skills/s', frontmatter('s', 'first'));
  skill(dir, 'm/two/1.0.0/skills/s', frontmatter('s', 'second'));
  skill(dir, 'other/one/1.0.0/skills/s', frontmatter('s', 'third'));
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 3);
  assert.deepEqual(audit.omissions, []);
});

test('the dedupe key is the marketplace plugin name triple', () => {
  // Same name under two different plugins is two skills, not a duplicate.
  const dir = room();
  skill(dir, 'm/one/1.0.0/skills/s', frontmatter('s', 'first'));
  skill(dir, 'm/two/1.0.0/skills/s', frontmatter('s', 'second'));
  skill(dir, 'other/one/1.0.0/skills/s', frontmatter('s', 'third'));
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 3);
  assert.deepEqual(audit.omissions, []);
});

test('a skill outside a plugin is never touched by the version rule', () => {
  // No plugin, no version — so every bare skill is in its group's resolved version. They still
  // dedupe by NAME, which is the one case the within-version dedupe is reachable at all: two
  // files claiming the same bare name are a `duplicate-skill`, never a `stale-version`,
  // because there is no version directory that lost.
  const dir = room();
  skill(dir, 'a/skills/solo', frontmatter('solo', 'first on disk'));
  skill(dir, 'b/skills/solo', frontmatter('solo', 'second on disk, and longer'));
  skill(dir, 'c/skills/other', frontmatter('other', 'unrelated'));
  const audit = skillaudit.audit(dir);
  assert.equal(audit.skills, 2);
  assert.equal(audit.catalogueBytes, 'second on disk, and longer'.length + 'unrelated'.length);
  const by = subjects(audit);
  assert.ok(!(skillaudit.OMIT_STALE_VERSION in by));
  assert.equal(by[skillaudit.OMIT_DUPLICATE].what, 'a/skills/solo/SKILL.md');
});

// ------------------------------------------------------------------- the folded scalar

test('a folded description is joined with single spaces before it is counted or scanned', () => {
  // `folded-note`'s description is one YAML scalar over two lines: 141 bytes, not 73. BOTH
  // numbers are asserted. A reader that keeps only the first line reports 73 and would
  // otherwise pass every other node in this file, because nothing else in the tree folds.
  assert.equal(README_BYTES['trigger-kit:folded-note'], 141);
  const note = scanned(CACHE, enabled())['trigger-kit:folded-note'];
  assert.equal(note.bytes, 141);
  assert.equal(Buffer.byteLength(note.description.split('\n')[0], 'utf8'), 141);
  assert.ok(note.description.includes('the transcripts on disk'));
  assert.deepEqual(note.phrases, ['ledger sweep']);
});

test('the fold joins with one space however deep the indent is', () => {
  // Leading indentation is YAML's, not the description's, and never reaches the bytes.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/s', '---\nname: s\ndescription: one\n      two\n   three\n---\n');
  assert.equal(skillaudit.audit(dir).catalogueBytes, 'one two three'.length);
});

// ------------------------------------------------------------------------------ `check`

test('check selects a family and the measurement is reported whatever it says', () => {
  // Five kinds in three families, and `skills`/`catalogue_bytes`/`omissions` in all of them.
  // The families are asserted as a PARTITION — every kind in exactly one — rather than one
  // membership at a time, so a kind added later cannot quietly fall out of every family.
  const families = {
    phrase: [skillaudit.KIND_SHARED_PHRASE],
    budget: [skillaudit.KIND_OVER_BUDGET, skillaudit.KIND_NEVER_INVOKED],
    frontmatter: [skillaudit.KIND_FRONTMATTER, skillaudit.KIND_NAME_MISMATCH],
  };
  const seen = new Set();
  for (const [check, expected] of Object.entries(families)) {
    const audit = fixtureAudit({ check });
    assert.deepEqual([...new Set(audit.findings.map((f) => f.kind))].sort(), [...expected].sort(), check);
    assert.equal(audit.skills, README_SKILLS, check);
    assert.equal(audit.catalogueBytes, README_CATALOGUE_BYTES, check);
    assert.equal(audit.omissions.length, README_OMISSIONS, check);
    for (const kind of expected) {
      assert.ok(!seen.has(kind), `${kind} is in two families`);
      seen.add(kind);
    }
  }
  assert.deepEqual([...seen].sort(), [...skillaudit.FINDING_ORDER].sort());
  assert.deepEqual([...new Set(fixtureAudit({ check: 'all' }).findings.map((f) => f.kind))].sort(), [...seen].sort());
});

test('findings come back in the contract own kind order', () => {
  // Order is part of the document two runtimes byte-compare, so it is pinned.
  const order = fixtureAudit().findings.map((f) => f.kind);
  const rank = (k) => skillaudit.FINDING_ORDER.indexOf(k);
  assert.deepEqual(order, [...order].sort((a, b) => rank(a) - rank(b)));
  assert.equal(order[0], skillaudit.KIND_SHARED_PHRASE);
  assert.equal(order.at(-1), skillaudit.KIND_NAME_MISMATCH);
});

// ---------------------------------------------------------------------------- refusals

for (const [options, fragment] of [
  [{ check: 'phrases' }, "unknown check 'phrases'"],
  [{ budget: -1 }, 'budget must not be negative'],
]) {
  test(`an argument the tool does not take is refused by name: ${JSON.stringify(options)}`, () => {
    assert.throws(
      () => skillaudit.audit(CACHE, options),
      (e) => e instanceof skillaudit.SkillAuditError && e.message.includes(fragment),
    );
  });
}

test('a root that is missing and a root that is a file refuse differently', () => {
  // Two different mistakes, two different sentences: neither is "0 skills".
  const dir = room();
  assert.throws(
    () => skillaudit.audit(join(dir, 'nowhere')),
    (e) => e instanceof skillaudit.SkillAuditError && e.message.includes('no such directory'),
  );
  const plain = join(dir, 'a-file');
  writeFileSync(plain, 'not a directory', 'utf8');
  assert.throws(
    () => skillaudit.audit(plain),
    (e) => e instanceof skillaudit.SkillAuditError && e.message.includes('is a file, not a directory of skills'),
  );
});

test('an empty directory is zero skills and not a refusal', () => {
  // Nothing to audit is an answer. A tree with no skills in it is a real state.
  const audit = skillaudit.audit(room());
  assert.equal(audit.skills, 0);
  assert.equal(audit.catalogueBytes, 0);
  assert.deepEqual(audit.findings, []);
  assert.deepEqual(audit.omissions, []);
});

// -------------------------------------------------------------------------- determinism

test('the answer does not move between two runs over the same tree', () => {
  assert.equal(fixtureAudit().asJson(), fixtureAudit().asJson());
});

test('the json is two-space indented', () => {
  // `json.dumps(..., indent=2, ensure_ascii=False)` on the reference has to produce the same
  // bytes, and `JSON.stringify(doc, null, 2)` is what makes that true.
  //
  // FORMATTING ONLY. This node used to carry the byte-count assertion below as well, which
  // made the description's PRICE a property nothing named — see the reference's
  // `test_the_json_is_two_space_indented`.
  const dir = room();
  skill(dir, 'm/p/1.0.0/skills/s', frontmatter('s', 'รายงาน'));
  const text = skillaudit.audit(dir).asJson();
  assert.ok(text.includes('\n  "skills": 1,'));
  assert.ok(text.includes('\n  "catalogue_bytes": '));
});

test('a description is priced in utf8 bytes and never in characters', () => {
  // `catalogue_bytes` is BYTES. The two numbers only differ on a non-ASCII description, and
  // until 2026-09-05 every counted description in the tree was ASCII — so `length` and
  // `Buffer.byteLength` were the same number for all sixteen and nothing here or in the
  // cross-runtime suite could tell them apart. The four skills below are what separate them,
  // each asserted with BOTH numbers so a reader that switched to characters lands on a figure
  // this table already names as the wrong one.
  const found = skillaudit.scan(CACHE, enabled());
  const byId = Object.fromEntries(found.map((s) => [s.id, s]));
  for (const [id, [utf8Bytes, characters]] of Object.entries(NON_ASCII_BYTES)) {
    assert.notEqual(utf8Bytes, characters, id);
    assert.equal(byId[id].bytes, utf8Bytes, id);
    assert.equal([...byId[id].description].length, characters, id);
    assert.equal(README_BYTES[id], utf8Bytes);
  }
  const characterTotal = found
    .filter((s) => s.omitted === null)
    .reduce((sum, s) => sum + [...s.description].length, 0);
  assert.notEqual(characterTotal, README_CATALOGUE_BYTES);
  assert.equal(fixtureAudit().catalogueBytes, README_CATALOGUE_BYTES);
});

test('the document does not escape non-ascii', () => {
  // `ensure_ascii=False` on the reference, and `JSON.stringify` has no escaping to match.
  // Nothing in the tree could catch this before 2026-09-05: every emitted string was ASCII,
  // so the reference's `ensure_ascii=True` mutant produced byte-identical output and was
  // caught by NOTHING. The Thai collision is what puts a non-ASCII string into a finding's
  // `detail`, and the character itself is asserted present rather than merely that no `\u`
  // appears — an absent escape and a present character are two claims.
  const text = fixtureAudit().asJson();
  assert.ok(text.includes(THAI_PHRASE));
  assert.ok(!text.includes('\\u'));
  assert.equal(JSON.parse(text).findings[2].detail, THAI_PHRASE);
});

test('the roots field echoes what was scanned', () => {
  const audit = fixtureAudit();
  assert.deepEqual(audit.asDict().roots, [CACHE]);
  assert.deepEqual(Object.keys(audit.asDict()), ['roots', 'skills', 'catalogue_bytes', 'findings', 'omissions']);
});

// --------------------------------------------------------------- the tool on the wire

function make(dir, { clock = () => FIXED_MS } = {}) {
  const memory = new Memory(join(dir, 'store'));
  const path = join(dir, 'log.jsonl');
  return { memory, path, log: new EventLog(path, CAP_BYTES, clock) };
}

/** Drive a real `Server` through the SDK's in-memory pair — never by calling the handler. */
async function connect(memory, log) {
  const wire = { rawLineFor: () => undefined, setExactResult: () => {} };
  const server = buildServer(memory, wire, '0.0.0-test', log);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'skillaudit-test', version: '0' }, { capabilities: {} });
  await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
  return client;
}

const callAudit = async (client, args) => {
  const answer = await client.callTool({ name: 'skill_audit', arguments: args });
  return [answer.isError === true, answer.content[0].text];
};

const records = (path) =>
  readFileSync(path, 'utf8')
    .split('\n')
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line));

test('the tool serves the same document the module computes', async () => {
  // Off the wire, through the registration — never by calling the function. A node that
  // called the function would agree with itself through any registration mistake, and the
  // registration is half of what this unit added.
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const [isError, text] = await callAudit(client, {
    root: CACHE,
    enabled: enabled(),
    usage: usage(),
    budget: README_BUDGET,
  });
  assert.equal(isError, false, text);
  assert.equal(text, fixtureAudit().asJson());
  assert.equal(JSON.parse(text).skills, README_SKILLS);
  await client.close();
});

test('the tool defaults to every finding when check is not sent', async () => {
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const [, sent] = await callAudit(client, { root: CACHE, enabled: enabled(), usage: usage(), check: 'all' });
  const [, omitted] = await callAudit(client, { root: CACHE, enabled: enabled(), usage: usage() });
  assert.equal(sent, omitted);
  await client.close();
});

test('a bad root reaches the model as a sentence and not an exception', async () => {
  // `isError` frames carrying a stack trace are what `tool_failed` exists to prevent.
  const dir = room();
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [isError, text] = await callAudit(client, { root: join(dir, 'nowhere') });
  assert.equal(isError, false);
  assert.ok(text.startsWith('error: skill_audit failed: no such directory:'), text);
  assert.ok(!text.includes('at '), text);
  await client.close();
});

test('the event log records the decision and no argument of it', async () => {
  // Four counts the host cannot see, and not one byte the operator typed. `root` is a path
  // from the operator's own machine and `findings[].skills` are the names of their skills;
  // neither is a decision this handler made. The sentinels are in every path segment, so a
  // record that leaked any of them reddens.
  const dir = room();
  const { memory, log, path } = make(dir);
  const client = await connect(memory, log);
  const root = join(dir, 'SENTINEL-ROOT');
  skill(
    root,
    'SENTINEL-MARKET/SENTINEL-PLUGIN/1.0.0/skills/SENTINEL-SKILL',
    frontmatter('SENTINEL-SKILL', "SENTINEL-DESCRIPTION about 'SENTINEL-PHRASE'"),
  );
  const [isError, text] = await callAudit(client, { root, usage: {}, budget: 0 });
  assert.equal(isError, false);
  assert.ok(text.includes('SENTINEL-SKILL'));
  assert.ok(!readFileSync(path).includes('SENTINEL'));
  assert.deepEqual(records(path), [
    {
      v: SCHEMA_VERSION,
      ts: FIXED_TS,
      tool: 'skill_audit',
      outcome: 'audited',
      detail: { bytes: 44, findings: 2, omissions: 0, skills: 1 },
    },
  ]);
  await client.close();
});

test('a refusal is recorded with no detail at all', async () => {
  const dir = room();
  const { memory, log, path } = make(dir);
  const client = await connect(memory, log);
  await callAudit(client, { root: join(dir, 'SENTINEL-MISSING') });
  assert.ok(!readFileSync(path).includes('SENTINEL'));
  assert.deepEqual(records(path), [
    { v: SCHEMA_VERSION, ts: FIXED_TS, tool: 'skill_audit', outcome: 'refused', detail: {} },
  ]);
  await client.close();
});

test('the tool is served eleventh and its schema is the assets', async () => {
  // Registration order IS served order, and the schema comes from the manifest.
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const listed = (await client.listTools()).tools;
  assert.equal(listed.at(-1).name, 'skill_audit');
  assert.equal(listed.length, 11);
  const asset = JSON.parse(readFileSync(join(repoRoot, 'assets', 'tools', 'skill_audit.json'), 'utf8'));
  const served = listed.find((t) => t.name === 'skill_audit');
  assert.equal(served.description, asset.description);
  assert.deepEqual(served.inputSchema, asset.parameters);
  assert.deepEqual(served.outputSchema, asset.output_schema);
  await client.close();
});

test('a usage value that is not an integer is refused the way pydantic refuses it', async () => {
  // `usage: dict[str, int]` — the values are validated, and the location is the KEY. The
  // reference's model refuses `{'a': 'x'}` before the handler is entered, so this port's
  // `dictInt` field has to as well, or the two servers disagree about which calls are legal.
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const [isError, text] = await callAudit(client, { root: CACHE, usage: { 'a:b': 'x' } });
  assert.equal(isError, true);
  // The SDK prefixes a failing tool result with its own `Error executing tool <name>: `; what
  // this port owns is everything after it, and the whole frame is compared against the Python
  // server's by `tools/conformance/suites/wire.mjs`.
  assert.ok(text.includes('1 validation error for skill_auditArguments\nusage.a:b\n'), text);
  assert.ok(text.includes("[type=int_parsing, input_value='x', input_type=str]"), text);
  // …and a string that SPELLS an integer is coerced, exactly as `k` and `reserve` are, so the
  // skill is a `never-invoked` finding only when the coerced value is zero.
  const [ok, doc] = await callAudit(client, { root: CACHE, enabled: enabled(), usage: { 'solo-check': '4' } });
  assert.equal(ok, false, doc);
  const never = JSON.parse(doc).findings.filter((f) => f.kind === 'never-invoked').map((f) => f.skills[0]);
  assert.ok(!never.includes('solo-check'), doc);
  await client.close();
});
