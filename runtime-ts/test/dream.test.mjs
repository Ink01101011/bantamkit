/**
 * `dream` on the Node side: the cross-layer consolidation, and `memory_dream` on the wire.
 *
 * TWO ORACLES, and the second is the one this port owes. The nodes below are the SAME
 * nodes `runtime-py/tests/test_memory_dream.py` holds — same fixture, same claims, same
 * assertions — so a behaviour that moved on one side and not the other goes red here rather
 * than in J45-4's differential three units later. That is the fast loop.
 *
 * The slow loop is `tools/conformance/`, which compares the two live answers. What THIS
 * file adds that a differential cannot see is the last section: the five places where
 * JavaScript's default semantics differ from CPython's and the port had to pin them. A
 * differential over an ASCII corpus is green whether or not `collapse` uses CPython's
 * `\s`; these nodes name the exact codepoint, the exact float and the exact digit that
 * separate the two, so the pin cannot be quietly undone by a "simplification".
 *
 * Every node runs against throwaway stores under the OS temp directory. NOTHING here opens
 * the real memory store: `dream` archives out of the machine-wide profile layer, which is a
 * write into the user's home directory, and a test that did it once would be a test that
 * did it on every run.
 */
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

import {
  absolutise,
  blockKey,
  claimSlot,
  collapse,
  dream,
  formatFixed3,
  mergeBodies,
  mergeDescriptions,
  mergeLinks,
  pyIntDigits,
  sortedNames,
  splitBlocks,
  SUPERSEDED_HEADING,
} from '../dist/memory/dream.js';
import { DUPLICATE_JACCARD, jaccard, MemoryStore, tokens } from '../dist/memory/store.js';
import { formatFact } from '../dist/memory/factfile.js';
import { Memory } from '../dist/memory/component.js';
import { CAP_BYTES, EventLog } from '../dist/eventlog.js';
import { buildServer } from '../dist/mcp/server.js';

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-dream-test-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
/** A fresh, empty bed for one test: nothing here is shared with any other. */
const bed = () => {
  const dir = join(scratch, `d${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

// ------------------------------------------------------------------ fixture construction

/**
 * The two halves of the measured shape, rewritten so no private content is committed —
 * character for character the strings `test_memory_dream.py` holds, because the union of
 * two DIFFERENT fixtures proves nothing about two runtimes agreeing.
 *
 * Every structural property J45-1 measured on the real pair is preserved: the project copy
 * carries an amendment dated AFTER the profile copy was created, the profile copy carries
 * claims the project copy has never held, the descriptions overlap only partly, and the two
 * bodies share no paragraph.
 */
const PROJECT_BODY =
  'Deploys are standing: review it, ship it, report afterwards.\n' +
  '\n' +
  '**AMENDED 2026-09-06: publishing is not unconditionally standing.** Opening this job ' +
  'the user reserved the publish decision for themselves, so a grant given in an earlier ' +
  'job is not a grant for this one.\n' +
  '\n' +
  'The reverse also holds and is the more common case: when they say nothing, publishing ' +
  'is standing and the job is not done at main.';
const PROFILE_BODY =
  'DEPLOY IS AUTHORIZED STANDING. The user granted it twice. Review it, deploy it, ' +
  'always report.\n' +
  '\n' +
  'TAGGING IS NOT AUTHORIZED and never has been. Deploy authorization does not extend to ' +
  'tagging.\n' +
  '\n' +
  'THE ONE BLOCKER, AND IT IS NOT THE USER: a context compaction reduces the grant to a ' +
  'claim inside a model-written summary, and the classifier correctly refuses to act on ' +
  'that. After a compaction say so once and ask for one restatement.\n' +
  '\n' +
  'MERGE STYLE for this repo: squash, and KEEP the branch — squashing leaves the commit ' +
  'bodies reachable only through the branch ref.\n' +
  '\n' +
  'VERIFY AFTER MERGING with git, not the API: the GraphQL endpoint throws intermittent ' +
  '503s on this repo.';
const PROJECT_DESCRIPTION = 'whether to ask before deploying tagging or publishing a release';
const PROFILE_DESCRIPTION = 'why a deploy can still get blocked after a context compaction';

const PROJECT_ONLY_CLAIM = 'AMENDED 2026-09-06';
const PROFILE_ONLY_CLAIMS = [
  'TAGGING IS NOT AUTHORIZED',
  'a context compaction reduces the grant',
  'MERGE STYLE for this repo',
  'VERIFY AFTER MERGING with git, not the API',
];

/**
 * One fact file, written directly so the test controls `created` and the mtime.
 *
 * `MemoryStore.save` cannot build these fixtures: it stamps `created` with today and it
 * REFUSES a second fact scoring 0.5 or more, which is the very population the intra-store
 * node has to construct in order to prove it is left alone.
 */
function writeFact(root, name, options = {}) {
  const {
    description,
    body,
    type = 'feedback',
    created = '2026-08-21',
    lastRecalled = '2026-09-06',
    links = [],
    mtime = null,
  } = options;
  mkdirSync(join(root, 'facts'), { recursive: true });
  mkdirSync(join(root, 'archive'), { recursive: true });
  const path = join(root, 'facts', `${name}.md`);
  writeFileSync(
    path,
    formatFact({ name, description, type, created, last_recalled: lastRecalled, links, body }),
    'utf8',
  );
  if (mtime !== null) {
    // Noon UTC of the named day, so no timezone this suite can run in moves the DATE —
    // `pyMtimeDate` is LOCAL, exactly as `date.fromtimestamp` is.
    const [y, m, d] = mtime.split('-').map(Number);
    const seconds = Date.UTC(y, m - 1, d, 12) / 1000;
    utimesSync(path, seconds, seconds);
  }
  return path;
}

const stores = (dir) => [new MemoryStore(join(dir, 'project')), new MemoryStore(join(dir, 'profile'))];

/**
 * The measured shape: same name, diverged bodies, and every cheap clock pointing wrong.
 *
 * `created` runs BACKWARDS against content age — the project copy is the older fact and
 * holds the newer paragraph — which is the property that refutes newest-`created`-wins.
 * `last_recalled` is equal, so it separates nothing. The profile body is the longer one,
 * which refutes longest-body-wins.
 */
function divergedPair(dir) {
  const [project, profile] = stores(dir);
  writeFact(project.root, 'deploy-standing-tag-withheld', {
    description: PROJECT_DESCRIPTION,
    body: PROJECT_BODY,
    created: '2026-08-21',
    links: ['every-change-ships-to-npm-not-just-to-main'],
    mtime: '2026-09-06',
  });
  writeFact(profile.root, 'deploy-standing-tag-withheld', {
    description: PROFILE_DESCRIPTION,
    body: PROFILE_BODY,
    created: '2026-08-27',
    links: ['bantamkit-program-resume-pointer'],
    mtime: '2026-08-27',
  });
  return [project, profile];
}

const factsOf = (store) => store.internals().facts();
const namesOf = (store) => factsOf(store).map((f) => f.name);
const bodyOf = (store, name) => factsOf(store).find((f) => f.name === name).body;
/** `Memory` with a profile layer bound, the way `layered` binds one in production. */
function memoryOver(projectRoot, profile, options = {}) {
  const memory = new Memory(projectRoot, options);
  memory.layers.push(['profile', profile, false]);
  return memory;
}

// ------------------------------------------------------------------ the population itself

test('an intra-store near-duplicate is never merged', () => {
  // J45-1's first finding, as a gate: the within-store population is empty and stays so.
  // This is the node that would go green vacuously if the merge were keyed on similarity,
  // so it also asserts the SCORE, to prove the pair really is one a similarity-keyed
  // deduper would have collapsed.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'alpha-token-budget', { description: 'the token budget for alpha', body: 'one' });
  writeFact(project.root, 'alpha-token-budgets', { description: 'the token budgets for alpha', body: 'two' });
  const score = jaccard(
    tokens('alpha-token-budget the token budget for alpha'),
    tokens('alpha-token-budgets the token budgets for alpha'),
  );
  assert.ok(score >= DUPLICATE_JACCARD, `the fixture is not a duplicate at all: ${score}`);

  const result = dream(project, profile, false);

  assert.deepEqual(result.merged, []);
  assert.deepEqual(namesOf(project).sort(), ['alpha-token-budget', 'alpha-token-budgets']);
});

test('a byte-identical cross-layer pair collapses to one copy', () => {
  const [project, profile] = stores(bed());
  for (const root of [project.root, profile.root]) {
    writeFact(root, 'shared-ruling', { description: 'one ruling', body: 'the same body', mtime: '2026-08-27' });
  }

  const result = dream(project, profile, false);

  assert.deepEqual(result.merged.map((m) => m.kind), ['identical']);
  assert.equal(result.applied, true);
  assert.deepEqual(namesOf(project), ['shared-ruling']);
  assert.deepEqual(factsOf(profile), []);
  assert.deepEqual(profile.archived(), ['shared-ruling']);
});

test('the survivor stays in the writable project layer', () => {
  // A survivor in the read-only layer would be re-forked by the next `memory_save`, which
  // writes to the project store and nowhere else.
  const [project, profile] = divergedPair(bed());

  const result = dream(project, profile, false);

  assert.deepEqual(result.merged.map((m) => m.survivorLayer), ['project']);
  assert.deepEqual(result.merged.map((m) => m.consumedLayer), ['profile']);
  assert.deepEqual(namesOf(project), ['deploy-standing-tag-withheld']);
  assert.deepEqual(factsOf(profile), []);
});

test('the consumed copy is archived and restorable by name', () => {
  const [project, profile] = divergedPair(bed());

  const result = dream(project, profile, false);

  assert.deepEqual(result.consumed, ['deploy-standing-tag-withheld']);
  assert.equal(result.archiveDir, join(profile.root, 'archive'));
  assert.deepEqual(profile.archived(), ['deploy-standing-tag-withheld']);
  profile.restore('deploy-standing-tag-withheld');
  assert.deepEqual(namesOf(profile), ['deploy-standing-tag-withheld']);
});

// ------------------------------------------------------------------ the acceptance test

test('a diverged pair unions every claim from both copies', () => {
  // THE ACCEPTANCE TEST. Not one claim from either input may be missing from the output.
  const [project, profile] = divergedPair(bed());

  dream(project, profile, false);
  const merged = bodyOf(project, 'deploy-standing-tag-withheld');
  const keys = new Set(splitBlocks(merged).map(blockKey));

  assert.ok(merged.includes(PROJECT_ONLY_CLAIM));
  for (const claim of PROFILE_ONLY_CLAIMS) {
    assert.ok(merged.includes(claim), `the union dropped a profile claim: ${claim}`);
  }
  for (const block of [...splitBlocks(PROJECT_BODY), ...splitBlocks(PROFILE_BODY)]) {
    assert.ok(keys.has(blockKey(block)), `the union dropped a block: ${block.slice(0, 60)}`);
  }
});

test('each cheap tie-breaker drops a claim the union keeps', () => {
  // Newest-`created`, longest-body and project-layer-wins, each refuted on the fixture.
  // This makes J45-1's finding a property of the FIXTURE rather than of a note, so a change
  // that quietly reintroduces a winner-takes-all rule has to fail here.
  const [project, profile] = divergedPair(bed());
  const here = factsOf(project).find((f) => f.name === 'deploy-standing-tag-withheld');
  const there = factsOf(profile).find((f) => f.name === 'deploy-standing-tag-withheld');

  assert.ok(there.created > here.created); // newest `created` -> profile -> amendment gone
  assert.ok(!there.body.includes(PROJECT_ONLY_CLAIM));
  assert.ok(there.body.length > here.body.length); // longest body -> profile -> same loss
  for (const claim of PROFILE_ONLY_CLAIMS) assert.ok(!here.body.includes(claim));
  assert.equal(here.last_recalled, there.last_recalled); // separates nothing

  dream(project, profile, false);
  const merged = bodyOf(project, 'deploy-standing-tag-withheld');
  assert.ok(merged.includes(PROJECT_ONLY_CLAIM));
  assert.ok(PROFILE_ONLY_CLAIMS.every((claim) => merged.includes(claim)));
});

test('the diverged pair scores below the runtime own duplicate threshold', () => {
  // Why the key is the NAME. A merge gated on `DUPLICATE_JACCARD` would miss this pair.
  const [project, profile] = divergedPair(bed());

  const result = dream(project, profile, true);

  assert.equal(result.merged.length, 1);
  assert.ok(
    result.merged[0].jaccard < DUPLICATE_JACCARD,
    'the fixture no longer reproduces the measured shape: the diverged pair must score ' +
      'BELOW the threshold the runtime calls a duplicate, or this feature key is moot',
  );
});

test('similarity is reported and never acted on', () => {
  const [project, profile] = stores(bed());
  writeFact(project.root, 'token-budget-alpha', { description: 'the token budget for alpha', body: 'here' });
  writeFact(profile.root, 'token-budgets-alpha', { description: 'the token budgets for alpha', body: 'there' });

  const result = dream(project, profile, false);

  assert.deepEqual(result.merged, []);
  assert.deepEqual(
    result.similarUnmerged.map((p) => [p.projectName, p.profileName]),
    [['token-budget-alpha', 'token-budgets-alpha']],
  );
  assert.ok(result.similarUnmerged[0].jaccard >= DUPLICATE_JACCARD);
  assert.deepEqual(namesOf(profile), ['token-budgets-alpha']);
});

// ------------------------------------------------------------------ dates

test('a relative date resolves against the fact own mtime, not today', () => {
  const [project, profile] = stores(bed());
  writeFact(project.root, 'dated-note', {
    description: 'a note with a relative date',
    body: 'Measured today: the reader cleared 90 percent.',
    mtime: '2026-08-27',
  });

  const result = dream(project, profile, false);
  const body = bodyOf(project, 'dated-note');

  assert.ok(body.includes('today (2026-08-27)'));
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  assert.ok(!body.includes(iso) || iso === '2026-08-27');
  assert.deepEqual(
    result.absolutised.map((h) => [h.term, h.resolved, h.basis]),
    [['today', '2026-08-27', '2026-08-27']],
  );
});

test('yesterday, tomorrow and N units ago resolve by day arithmetic', () => {
  const body = 'yesterday it failed, tomorrow it runs, 3 days ago it began, 2 weeks ago it landed';
  const [out, hits, unresolved] = absolutise(body, '2026-08-27', 'n', 'project');
  assert.ok(out.includes('yesterday (2026-08-26)'));
  assert.ok(out.includes('tomorrow (2026-08-28)'));
  assert.ok(out.includes('3 days ago (2026-08-24)'));
  assert.ok(out.includes('2 weeks ago (2026-08-13)'));
  assert.equal(hits.length, 4);
  assert.deepEqual(unresolved, []);
});

test('absolutising is idempotent', () => {
  // A second dream over the same body writes nothing — the stamp is its own guard.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'dated-note', {
    description: 'a note with a relative date',
    body: 'Measured today: it held.',
    mtime: '2026-08-27',
  });

  dream(project, profile, false);
  const once = bodyOf(project, 'dated-note');
  const second = dream(project, profile, false);

  assert.deepEqual(second.absolutised, []);
  assert.deepEqual(second.rewritten, []);
  assert.equal(bodyOf(project, 'dated-note'), once);
});

test('an unresolvable relative term is reported and never rewritten', () => {
  // "recently" has no exact day. Substituting one would invent a precision nobody had.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'vague-note', {
    description: 'a note with a vague date',
    body: 'Recently the numbers moved, and last month they did not.',
    mtime: '2026-08-27',
  });

  const result = dream(project, profile, false);

  assert.deepEqual(result.absolutised, []);
  assert.deepEqual(result.unresolved.map((h) => h.term.toLowerCase()).sort(), ['last month', 'recently']);
  assert.ok(result.unresolved.every((h) => h.resolved === ''));
  assert.equal(bodyOf(project, 'vague-note'), 'Recently the numbers moved, and last month they did not.');
});

test('a day count no calendar can hold is reported and never raises', () => {
  // `\d+` has no upper bound, so a body a PERSON can write used to take the pass down.
  //
  // MEASURED 2026-09-06, before the guard: `999999999999 days ago` raised OverflowError out
  // of `dream()` on BOTH runtimes — the dry run included, so an operator could not preview a
  // store holding one. And the two did not raise the SAME thing: CPython has three refusals
  // in this arithmetic and this file reproduced two, so at `2147483648 days ago` the
  // reference said `Python int too large to convert to C int` and this port said
  // `days=-2147483648; must have magnitude <= 999999999`. The repair is not a third
  // sentence: an unresolvable relative term already has a home, and this goes there.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'huge-dates', {
    description: 'a note with impossible day counts',
    body:
      'It landed 739864 days ago, or maybe 739865 days ago, or ' +
      '999999999 days ago, or 1000000000 days ago, or 2147483647 days ago, ' +
      'or 2147483648 days ago, or 999999999999 days ago.',
    mtime: '2026-09-06',
  });

  const result = dream(project, profile, false);
  const body = bodyOf(project, 'huge-dates');

  // 739864 days before 2026-09-06 is 0001-01-01, the last day `date` can hold, and it
  // resolves. Everything past it is reported and left exactly as written.
  assert.deepEqual(result.absolutised.map((h) => h.term), ['739864 days ago']);
  assert.ok(body.includes('739864 days ago (0001-01-01)'));
  assert.deepEqual(result.unresolved.map((h) => h.term), [
    '739865 days ago', '999999999 days ago', '1000000000 days ago',
    '2147483647 days ago', '2147483648 days ago', '999999999999 days ago',
  ]);
  assert.ok(result.unresolved.every((h) => h.resolved === ''));
  for (const h of result.unresolved) {
    assert.ok(body.includes(`${h.term},`) || body.endsWith(`${h.term}.`), 'a term moved');
  }
});

test('the calendar edge is the boundary and it is asserted, not assumed', () => {
  // A conformance case compares the two runtimes and cannot see a rule that moves on BOTH
  // of them at once (J45-3 measured exactly that shape surviving 80 nodes). This is the
  // literal that does: the edge is `basis.toordinal() - 1` days back and nothing vaguer.
  const [inside, hits, unresolved] = absolutise('x 739864 days ago y', '2026-09-06', 'n', 'project');
  const [outside, noHits, reported] = absolutise('x 739865 days ago y', '2026-09-06', 'n', 'project');

  assert.equal(inside, 'x 739864 days ago (0001-01-01) y');
  assert.deepEqual(hits.map((h) => h.resolved), ['0001-01-01']);
  assert.deepEqual(unresolved, []);
  assert.equal(outside, 'x 739865 days ago y', 'the body was rewritten for a day that does not exist');
  assert.deepEqual(noHits, []);
  assert.deepEqual(reported.map((h) => [h.term, h.resolved]), [['739865 days ago', '']]);
});

test('a relative date in a profile-only fact is left alone', () => {
  // This pass edits the writable layer. A profile-only fact is not consumed by any merge,
  // so rewriting it would be a write into the user's home directory buying nothing.
  const [project, profile] = stores(bed());
  writeFact(profile.root, 'profile-note', { description: 'a profile note', body: 'Measured today.', mtime: '2026-08-27' });
  const path = join(profile.root, 'facts', 'profile-note.md');
  const before = readFileSync(path);

  const result = dream(project, profile, false);

  assert.deepEqual(result.absolutised, []);
  assert.deepEqual(readFileSync(path), before);
});

// ------------------------------------------------------------------ contradiction

test('a contradicted claim keeps the newer and records the older verbatim', () => {
  // Newer wins, loser preserved. Newer is the FILE's mtime, the only clock that records when
  // the text was last written — `created` is first-landing and points backwards here.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'ruling', {
    description: 'the ruling', mtime: '2026-08-01',
    body: 'Preamble.\n\nIndex budget: 4096 bytes\n\nTail.',
  });
  writeFact(profile.root, 'ruling', {
    description: 'the ruling', mtime: '2026-09-01',
    body: 'Index budget: 24000 bytes\n\nOther.',
  });

  const result = dream(project, profile, false);
  const merged = bodyOf(project, 'ruling');

  assert.deepEqual(result.superseded.map((r) => r.subject), ['index budget']);
  assert.equal(result.superseded[0].keptLayer, 'profile');
  assert.equal(result.superseded[0].lostLayer, 'project');
  assert.ok(merged.includes('Index budget: 24000 bytes'));
  assert.ok(merged.includes(SUPERSEDED_HEADING));
  assert.ok(merged.includes('Index budget: 4096 bytes'), 'the losing claim was silently dropped');
  assert.ok(merged.indexOf('Index budget: 24000') < merged.indexOf(SUPERSEDED_HEADING));
});

test('two claims that are merely different are both kept without superseding', () => {
  // The narrowness of the contradiction rule, as a gate. Different SUBJECTS never fight.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'ruling', { description: 'the ruling', mtime: '2026-08-01', body: 'Index budget: 4096 bytes' });
  writeFact(profile.root, 'ruling', { description: 'the ruling', mtime: '2026-09-01', body: 'Recall budget: 3 facts' });

  const result = dream(project, profile, false);

  assert.deepEqual(result.superseded, []);
  assert.ok(!bodyOf(project, 'ruling').includes(SUPERSEDED_HEADING));
  assert.ok(bodyOf(project, 'ruling').includes('4096'));
  assert.ok(bodyOf(project, 'ruling').includes('3 facts'));
});

test('a contradiction with equal mtimes goes to the writable project layer', () => {
  // The TIE-BREAK, which is a rule and not a coincidence: equal mtimes keep the PROJECT
  // claim, because the project layer is the only writable one and the survivor lands there.
  //
  // Added after this module's own mutant sweep: flipping `> 0` to `>= 0` here survived all
  // 45 nodes of this file AND all 35 of `runtime-py/tests/test_memory_dream.py`. The rule
  // was written on both sides and asserted on neither, which is exactly the shape a
  // two-runtime differential cannot see — both halves would have drifted together and
  // stayed green. The Python node was added in the same change.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'ruling', { description: 'the ruling', mtime: '2026-09-01', body: 'Index budget: 4096 bytes' });
  writeFact(profile.root, 'ruling', { description: 'the ruling', mtime: '2026-09-01', body: 'Index budget: 24000 bytes' });

  const result = dream(project, profile, false);
  const merged = bodyOf(project, 'ruling');

  assert.deepEqual(result.superseded.map((r) => r.keptLayer), ['project']);
  assert.equal(result.superseded[0].lostLayer, 'profile');
  assert.ok(merged.indexOf('Index budget: 4096') < merged.indexOf(SUPERSEDED_HEADING));
  assert.ok(merged.includes('Index budget: 24000 bytes'), 'the losing claim was silently dropped');
});

test('a URL block is not read as a claim slot', () => {
  // `https://a/x` splits on a colon and would collide with `https://b/y` on the subject
  // `https`. A URL is not a claim, and a rule that thought otherwise would supersede a link
  // nobody contradicted.
  assert.equal(claimSlot('https://example.com/one'), null);
  assert.deepEqual(claimSlot('Index budget: 4096'), ['index budget', '4096']);
  assert.deepEqual(claimSlot('- Index budget: 4096'), ['index budget', '4096']);
  assert.equal(claimSlot('Two lines\nsecond: value'), null);
});

// ------------------------------------------------------------------ the union, in the small

test('the union is ordered set union, project first', () => {
  const [body, added, superseded] = mergeBodies('A\n\nB\n\nC', 'B\n\nD', 'project', 'profile', '2026-08-01', '2026-08-02');
  assert.equal(body, 'A\n\nB\n\nC\n\nD');
  assert.equal(added, 1);
  assert.deepEqual(superseded, []);
});

test('block identity ignores whitespace and case only', () => {
  assert.equal(blockKey('  Two   words\nhere '), 'two words here');
  assert.notEqual(blockKey('Done.'), blockKey('Done'));
});

test('descriptions union and links union deterministically', () => {
  assert.equal(mergeDescriptions('one line', 'ONE   LINE'), 'one line');
  assert.equal(mergeDescriptions('about a', 'about b'), 'about a; about b');
  assert.deepEqual(mergeLinks(['a', 'b'], ['b', 'c']), ['a', 'b', 'c']);
});

test('created takes the earlier and last_recalled the later', () => {
  const [project, profile] = stores(bed());
  writeFact(project.root, 'ruling', { description: 'here', body: 'one', created: '2026-08-21', lastRecalled: '2026-09-01', mtime: '2026-09-06' });
  writeFact(profile.root, 'ruling', { description: 'there', body: 'two', created: '2026-08-01', lastRecalled: '2026-09-06', mtime: '2026-08-27' });

  dream(project, profile, false);
  const fact = factsOf(project).find((f) => f.name === 'ruling');

  assert.equal(fact.created, '2026-08-01');
  assert.equal(fact.last_recalled, '2026-09-06');
});

// ------------------------------------------------------------------ the two store traps

test('dream never creates an index in a store that never had one', () => {
  // TRAP 1. The profile store has no `index.md` and never has: its index is derived by
  // `indexText()` and `rebuildIndex` is never reached, because `Memory.layered` mounts it
  // read-only. Creating a file in the user's home directory must be a decision, not a side
  // effect of tidying two copies of a fact into one.
  const [project, profile] = stores(bed());
  for (const root of [project.root, profile.root]) {
    writeFact(root, 'shared-ruling', { description: 'one ruling', body: 'the same body' });
  }
  rmSync(join(project.root, 'index.md'), { force: true });
  assert.ok(!existsSync(join(profile.root, 'index.md')));

  dream(project, profile, false);

  assert.ok(!existsSync(join(profile.root, 'index.md')));
  assert.ok(
    !existsSync(join(project.root, 'index.md')),
    'the rule is one sentence for both stores: never create an index that was not there',
  );
});

test('dream rebuilds an index that was already on disk', () => {
  // The other half of trap 1: where an index DOES exist, it must track the merge.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'shared-ruling', { description: 'one ruling', body: 'here' });
  writeFact(profile.root, 'shared-ruling', { description: 'one ruling', body: 'here' });
  writeFact(project.root, 'other', { description: 'another', body: 'x' });
  project.internals().rebuildIndex();
  const before = readFileSync(join(project.root, 'index.md'), 'utf8');

  dream(project, profile, false);

  assert.equal(readFileSync(join(project.root, 'index.md'), 'utf8'), before);
  assert.ok(!existsSync(join(profile.root, 'index.md')));
});

test('a pair whose profile copy is already archived is refused, not overwritten', () => {
  const [project, profile] = stores(bed());
  writeFact(project.root, 'shared-ruling', { description: 'one ruling', body: 'here' });
  writeFact(profile.root, 'shared-ruling', { description: 'one ruling', body: 'here' });
  writeFileSync(join(profile.root, 'archive', 'shared-ruling.md'), 'older', 'utf8');

  const result = dream(project, profile, false);

  assert.deepEqual(result.merged, []);
  assert.deepEqual(result.refused.map(([name]) => name), ['shared-ruling']);
  assert.ok(result.refused[0][1].includes('refusing to overwrite'));
  assert.equal(readFileSync(join(profile.root, 'archive', 'shared-ruling.md'), 'utf8'), 'older');
  assert.deepEqual(namesOf(profile), ['shared-ruling']);
});

// ------------------------------------------------------------------ preview, budget, diff

test('a dry run writes nothing and still reports the whole plan', () => {
  const [project, profile] = divergedPair(bed());
  const paths = [project.root, profile.root].map((r) => join(r, 'facts', 'deploy-standing-tag-withheld.md'));
  const before = paths.map((p) => readFileSync(p));

  const result = dream(project, profile, true);

  assert.equal(result.dryRun, true);
  assert.equal(result.applied, false);
  assert.equal(result.merged.length, 1);
  assert.deepEqual(result.consumed, ['deploy-standing-tag-withheld']);
  assert.ok(result.indexAfter > 0 && result.factBytesAfter > 0);
  paths.forEach((p, i) => assert.deepEqual(readFileSync(p), before[i]));
  assert.deepEqual(profile.archived(), []);
});

test('the default is a dry run', () => {
  const [project, profile] = divergedPair(bed());
  const result = dream(project, profile);
  assert.equal(result.dryRun, true);
  assert.equal(result.applied, false);
  assert.notDeepEqual(factsOf(profile), []);
});

test('the dry-run projection equals what applying actually produces', () => {
  // A preview whose numbers differ from the run it previews is worse than no preview.
  const [project, profile] = divergedPair(bed());
  const preview = dream(project, profile, true);

  dream(project, profile, false);

  assert.equal(Buffer.byteLength(project.indexText(), 'utf8'), preview.indexAfter);
  const actual = [project, profile]
    .flatMap((s) => factsOf(s).map((f) => statSync(join(s.root, 'facts', `${f.name}.md`)).size))
    .reduce((a, b) => a + b, 0);
  assert.equal(actual, preview.factBytesAfter);
});

test('a projected index over budget refuses the whole pass and names compaction', () => {
  // The budget is `compact()`'s budget, reused. Nothing is written when it would not fit.
  const dir = bed();
  const project = new MemoryStore(join(dir, 'project'), { indexBudget: 140 });
  const profile = new MemoryStore(join(dir, 'profile'));
  writeFact(project.root, 'ruling', { description: 'a'.repeat(60), body: 'here' });
  writeFact(profile.root, 'ruling', { description: 'b'.repeat(60), body: 'there' });
  const memory = memoryOver(project.root, profile, { indexBudget: 140 });

  const outcome = memory.dreamOutcome(false);

  assert.equal(outcome.status, 'refused-budget');
  assert.ok(outcome.reply.includes('memory_compact'));
  assert.equal(outcome.result.applied, false);
  assert.deepEqual(namesOf(profile), ['ruling']);
});

test('the diff names the layers, the bytes and the blocks', () => {
  const [project, profile] = divergedPair(bed());

  const result = dream(project, profile, true);
  const merge = result.merged[0];

  assert.equal(merge.name, 'deploy-standing-tag-withheld');
  assert.equal(merge.kind, 'diverged');
  assert.equal(merge.survivorLayer, 'project');
  assert.equal(merge.consumedLayer, 'profile');
  assert.equal(merge.blocksAdded, splitBlocks(PROFILE_BODY).length);
  assert.ok(merge.bodyAfter > merge.bodyBefore);
  assert.ok(result.profileIndexBefore > result.profileIndexAfter);
  assert.ok(result.factBytesBefore > 0);
  assert.equal(result.projectRoot, project.root);
  assert.equal(result.profileRoot, profile.root);
});

test('dream is idempotent', () => {
  const [project, profile] = divergedPair(bed());
  dream(project, profile, false);
  const body = bodyOf(project, 'deploy-standing-tag-withheld');

  const again = dream(project, profile, false);

  assert.deepEqual(again.merged, []);
  assert.equal(again.changes, 0);
  assert.equal(bodyOf(project, 'deploy-standing-tag-withheld'), body);
});

// ------------------------------------------------------------------ the component seam

test('a read-only grant layer is never consumed', () => {
  // A grant is another operator's store. Consolidating a fact out of one is not this
  // person's move, so `dream` matches the `profile` label exactly and never a prefix.
  const dir = bed();
  const projectRoot = join(dir, 'project');
  const grant = new MemoryStore(join(dir, 'grant'));
  const profile = new MemoryStore(join(dir, 'profile'));
  writeFact(projectRoot, 'shared-ruling', { description: 'one ruling', body: 'here' });
  writeFact(grant.root, 'shared-ruling', { description: 'one ruling', body: 'here' });
  const memory = new Memory(projectRoot);
  memory.layers.push(['extra:grant', grant, false]);
  memory.layers.push(['profile', profile, false]);

  const outcome = memory.dreamOutcome(false);

  assert.equal(outcome.status, 'nothing-to-consolidate');
  assert.deepEqual(namesOf(grant), ['shared-ruling']);
});

test('a memory with no profile layer says so rather than failing', () => {
  const memory = new Memory(join(bed(), 'project'));
  const outcome = memory.dreamOutcome();
  assert.equal(outcome.status, 'no-profile-layer');
  assert.ok(outcome.reply.includes('no profile layer is bound'));
});

test('the outcome status is read off the decision, not the reply', () => {
  // The same seam `SaveOutcome`, `RecallOutcome` and `CompactOutcome` have: a caller that
  // wants to tell the outcomes apart must never have to match prose.
  const [project, profile] = divergedPair(bed());
  const memory = memoryOver(project.root, profile);

  const preview = memory.dreamOutcome(true);
  const applied = memory.dreamOutcome(false);
  const again = memory.dreamOutcome(false);

  assert.equal(preview.status, 'previewed');
  assert.equal(preview.dryRun, true);
  assert.equal(applied.status, 'consolidated');
  assert.equal(applied.merged, 1);
  assert.equal(applied.consumed, 1);
  assert.equal(again.status, 'nothing-to-consolidate');
  assert.equal(preview.budget, project.indexBudget);
});

test('the reply never claims a token saving', () => {
  // J45-1 measured the prize: the profile index is derived and is not loaded from a file,
  // so the token saving is nearer zero than the byte count suggests. The reply must say what
  // the pass actually bought instead of claiming a saving it did not make.
  const [project, profile] = divergedPair(bed());
  const memory = memoryOver(project.root, profile);

  const reply = memory.dream(true);

  assert.ok(reply.includes('not a token saving'));
  assert.ok(reply.includes('one copy of a ruling instead of two that can diverge'));
  assert.ok(reply.includes('DRY RUN: nothing was written'));
  const lowered = reply.toLowerCase();
  for (const claim of ['saves tokens', 'token saving of', 'frees tokens', 'reduces tokens']) {
    assert.ok(!lowered.includes(claim), claim);
  }
});

test('the reply names every consumed fact and where it moved', () => {
  const [project, profile] = divergedPair(bed());
  const memory = memoryOver(project.root, profile);

  const reply = memory.dream(false);

  assert.ok(reply.includes('deploy-standing-tag-withheld'));
  assert.ok(reply.includes(join(profile.root, 'archive')));
  assert.ok(reply.includes('is NOT deleted'));
});

test('a fixture older than its mtime still dates against the file', () => {
  // `created` is first-landing and must never be the basis for a relative date: a fact
  // created in June and rewritten in September says "today" about September.
  const [project, profile] = stores(bed());
  writeFact(project.root, 'dated-note', { description: 'a note', body: 'Measured today.', created: '2026-06-01', mtime: '2026-09-01' });

  const result = dream(project, profile, true);

  assert.deepEqual(result.absolutised.map((h) => h.basis), ['2026-09-01']);
  assert.equal(result.absolutised[0].resolved, '2026-09-01');
});

// ---------------------------------------------- the five CPython semantics this port pins

/**
 * These five nodes are what a Python/Node differential over an ASCII corpus CANNOT see, and
 * every one of them was measured before it was written. The differential itself was run over
 * 24,908 generated cases and agrees on all of them; mutating each pin below in turn broke it
 * on 5,761 / 32 / 1,830 / 2,150 / 3 cases respectively, which is why the pins are load-bearing
 * rather than decorative.
 */

test('collapse uses CPython whitespace, which is not JavaScript whitespace', () => {
  // The two sets disagree on SIX codepoints: Python also strips U+001C..U+001F and U+0085,
  // JS also strips U+FEFF. A `/\s+/` here would eat a BOM that CPython keeps and keep a file
  // separator that CPython eats — and `collapse` is the basis of every comparison key in the
  // module, so both directions change which blocks are called the same.
  assert.equal(collapse('a\u001Cb'), 'a b'); // U+001C: Python whitespace, JS not
  assert.equal(collapse('a\u0085b'), 'a b'); // U+0085: Python whitespace, JS not
  assert.equal(collapse('a\uFEFFb'), 'a\uFEFFb'); // U+FEFF: JS whitespace, Python not
  assert.equal(collapse('\u001C a \u0085'), 'a');
});

test('the .3f in the reply rounds half to EVEN, the way CPython does', () => {
  // `Number.prototype.toFixed` rounds ties AWAY from zero. The reachable ties are the odd
  // sixteenths — a Jaccard of 1/16 is one shared token in a sixteen-token union — and four
  // of the eight disagree. The reply prints this number, so a `toFixed` here is a reply the
  // two servers spell differently.
  assert.equal(formatFixed3(1 / 16), '0.062');
  assert.equal((1 / 16).toFixed(3), '0.063'); // the value this node exists to reject
  assert.equal(formatFixed3(5 / 16), '0.312');
  assert.equal(formatFixed3(9 / 16), '0.562');
  assert.equal(formatFixed3(13 / 16), '0.812');
  assert.equal(formatFixed3(3 / 16), '0.188');
  assert.equal(formatFixed3(1 / 3), '0.333');
  assert.equal(formatFixed3(0), '0.000');
  assert.equal(formatFixed3(1), '1.000');
});

test('a relative date counts in CPython digits, not ASCII ones', () => {
  // CPython's `\d` for a `str` pattern is the Nd category and `int()` reads every one of
  // them. JS's `\d` is `[0-9]`, so an Arabic-Indic count would be annotated by the reference
  // and silently ignored here.
  const [out, hits] = absolutise('٣ days ago it began', '2026-08-27', 'n', 'project');
  assert.equal(out, '٣ days ago (2026-08-24) it began');
  assert.equal(hits.length, 1);
  assert.equal(pyIntDigits('٣'), 3);
  assert.equal(pyIntDigits('۳۱'), 31);
  assert.equal(pyIntDigits('12'), 12);
});

test('the word boundary is CPython word, which includes accented letters', () => {
  // JS's `\b` without the `u` flag is ASCII-only: `étoday` has a boundary before `t` there
  // and none in CPython, so a bare `\b` annotates a word that is not the word.
  assert.deepEqual(absolutise('étoday', '2026-08-27', 'n', 'project')[1], []);
  assert.deepEqual(absolutise('todayé', '2026-08-27', 'n', 'project')[1], []);
  assert.equal(absolutise('é today', '2026-08-27', 'n', 'project')[1].length, 1);
});

test('a claim value may hold a line separator, which JavaScript dot excludes', () => {
  // CPython's `.` without DOTALL is `[^\n]`; JS's also excludes `\r`, U+2028 and U+2029, and
  // U+2028 survives `splitBlocks` because it is whitespace rather than a line end.
  // The VALUE KEY is collapsed, so U+2028 comes back as a plain space; what this node
  // pins is that the slot is FOUND at all, which a JS `.` would not do.
  assert.deepEqual(claimSlot('subject: a\u2028b'), ['subject', 'a b']);
});

test('names sort by codepoint, the way CPython sorts str', () => {
  // `Array.prototype.sort` orders by UTF-16 code unit, so an astral name lands before a BMP
  // one there and after it in CPython — and this order decides which pair is merged first.
  assert.deepEqual(sortedNames(['\u{1F414}', '！']), ['！', '\u{1F414}']);
  assert.deepEqual(['\u{1F414}', '！'].sort(), ['\u{1F414}', '！']);
});

// ------------------------------------------------------------------ memory_dream on the wire

const FIXED_MS = 1_756_029_153_412;

async function connect(memory, log) {
  const wire = { rawLineFor: () => undefined, setExactResult: () => {} };
  const server = buildServer(memory, wire, '0.0.0-test', log);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'dream-test', version: '0' }, { capabilities: {} });
  await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
  return client;
}

const callDream = async (client, args) => {
  const answer = await client.callTool({ name: 'memory_dream', arguments: args });
  return [answer.isError === true, answer.content[0].text];
};

test('memory_dream is served eleventh and its schema is the asset', async () => {
  const dir = bed();
  const [project, profile] = divergedPair(dir);
  const memory = memoryOver(project.root, profile);
  const client = await connect(memory, new EventLog(join(dir, 'log.jsonl'), CAP_BYTES, () => FIXED_MS));
  const listed = (await client.listTools()).tools;

  // Eleventh of FOURTEEN. It was eleventh of twelve when job50 I5 retired `bantamkit_read`
  // (tenth) and `repo_map` (thirteenth); `work_plan` and `shiftwork_plan` were APPENDED
  // (job `workplan-dag`, W5), which moves the total and leaves the index where it was —
  // exactly the case this node is built for. The index is pinned rather than `at(-1)`:
  // this node is about where `memory_dream` sits, and a later tool moving in behind it
  // must not be able to satisfy it.
  assert.equal(listed[10].name, 'memory_dream');
  assert.equal(listed.length, 14);
  const asset = JSON.parse(readFileSync(join(scratchRepoRoot(), 'assets', 'tools', 'memory_dream.json'), 'utf8'));
  const served = listed.find((t) => t.name === 'memory_dream');
  assert.equal(served.description, asset.description);
  assert.deepEqual(served.inputSchema, asset.parameters);
  assert.deepEqual(served.outputSchema, asset.output_schema);
  await client.close();
});

test('memory_dream defaults to a dry run and writes nothing', async () => {
  const dir = bed();
  const [project, profile] = divergedPair(dir);
  const memory = memoryOver(project.root, profile);
  const log = join(dir, 'log.jsonl');
  const client = await connect(memory, new EventLog(log, CAP_BYTES, () => FIXED_MS));

  const [isError, text] = await callDream(client, {});

  assert.equal(isError, false);
  assert.ok(text.includes('DRY RUN: nothing was written'));
  assert.deepEqual(namesOf(profile), ['deploy-standing-tag-withheld']);
  const record = JSON.parse(readFileSync(log, 'utf8').trim().split('\n').at(-1));
  assert.equal(record.tool, 'memory_dream');
  assert.equal(record.outcome, 'previewed');
  assert.equal(record.detail.dry_run, true);
  await client.close();
});

test('memory_dream with dry_run false applies the plan and records the decision', async () => {
  const dir = bed();
  const [project, profile] = divergedPair(dir);
  const memory = memoryOver(project.root, profile);
  const log = join(dir, 'log.jsonl');
  const client = await connect(memory, new EventLog(log, CAP_BYTES, () => FIXED_MS));

  const [isError, text] = await callDream(client, { dry_run: false });

  assert.equal(isError, false);
  assert.ok(!text.includes('DRY RUN'));
  assert.ok(text.includes('not a token saving'));
  assert.deepEqual(factsOf(profile), []);
  assert.deepEqual(profile.archived(), ['deploy-standing-tag-withheld']);
  const record = JSON.parse(readFileSync(log, 'utf8').trim().split('\n').at(-1));
  assert.deepEqual(record.detail, { absolutised: 0, consumed: 1, dry_run: false, merged: 1 });
  assert.equal(record.outcome, 'consolidated');
  await client.close();
});

test('dry_run is the lax pydantic bool, measured against the reference over the wire', async () => {
  // Every arm below came off the real Python server (33 inputs), not off pydantic's docs:
  // `0`/`1` and `0.0`/`1.0` coerce, any other integral number is `bool_parsing`, a
  // FRACTIONAL float is `bool_type`, a string is matched case-insensitively and is NOT
  // stripped first, and a list or dict is `bool_type`.
  const dir = bed();
  const [project, profile] = divergedPair(dir);
  const memory = memoryOver(project.root, profile);
  const client = await connect(memory, new EventLog(join(dir, 'log.jsonl'), CAP_BYTES, () => FIXED_MS));

  for (const accepted of [true, 1, 0, 1.0, 'true', 'FALSE', 'yes', 'n', 'on', 'off', 't', '1', '0']) {
    const [isError] = await callDream(client, { dry_run: accepted });
    assert.equal(isError, false, `${JSON.stringify(accepted)} should validate`);
  }
  for (const [bad, type] of [[2, 'bool_parsing'], [-1, 'bool_parsing'], [2.0, 'bool_parsing'],
                             [0.5, 'bool_type'], [' true ', 'bool_parsing'], ['', 'bool_parsing'],
                             ['maybe', 'bool_parsing'], ['2', 'bool_parsing'],
                             [[], 'bool_type'], [{}, 'bool_type']]) {
    const [isError, text] = await callDream(client, { dry_run: bad });
    assert.equal(isError, true, `${JSON.stringify(bad)} should refuse`);
    assert.ok(text.includes('1 validation error for memory_dreamArguments'), text);
    assert.ok(text.includes(`[type=${type},`), text);
    assert.ok(text.includes(`https://errors.pydantic.dev/2.13/v/${type}`), text);
  }
  await client.close();
});

/** The repository root: `fileURLToPath`, never `URL.pathname` — the latter is a percent-
 *  encoded POSIX path and on Windows it comes back as `/C:/...`, which `join` never fixes. */
function scratchRepoRoot() {
  return dirname(dirname(fileURLToPath(import.meta.url)));
}
