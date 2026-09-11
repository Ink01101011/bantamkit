/**
 * dream — the cross-layer consolidation, Python against Node, over the same two stores.
 *
 * THE PROPERTY: given the same PAIR of stores on disk and the same call, the two runtimes
 * answer the same `DreamResult` and leave BOTH directories in byte-identical states. Three
 * comparisons per scenario, not one — the plan, the project tree, the profile tree —
 * because `dream()` returns a plan AND writes: a survivor into the project layer, the
 * profile copy into that store's `archive/`, and an index rebuild in whichever store
 * already had one. "It returned the right plan" and "it left the right bytes" are separate
 * claims and this pass can fail either.
 *
 * WHY EVERY FIXTURE IS ASYMMETRIC ON PURPOSE. The trap this repository has already been
 * caught by (`tests-that-pick-the-input-that-cannot-fail`, and J45-3's mutant that survived
 * 35 Python nodes and 45 TypeScript nodes) is a differential fixture on which both sides
 * agree no matter what either does. So none of the scenarios below is symmetric between the
 * layers: the mtimes differ, the descriptions differ, the bodies contradict, `created` runs
 * BACKWARDS against content age, and the profile store has no `index.md` while the project
 * store does. A port that picked the wrong layer, the wrong date, the wrong tie-break or
 * the wrong store to rebuild differs on at least one case here.
 *
 * AND WHERE A DIFFERENTIAL IS STRUCTURALLY BLIND, THERE IS A LITERAL. J45-3 measured a
 * mutation — "an mtime tie goes to the OTHER side" — that no test on either side could see,
 * because the rule was written twice and asserted nowhere: change both halves and the two
 * still agree. The four `literalCases(...)` blocks at the end of `run()` pin the tie-break
 * and the calendar edge as TYPED literals against EACH side separately — a shape a
 * symmetric regression cannot stay green through, because neither side is the other's
 * oracle there.
 *
 * NO REAL STORE IS OPENED. `dream()` archives out of the machine-wide profile layer, which
 * is a write into the user's home directory. Every fixture here is built in harness scratch
 * and both `HOME` and the store roots stay inside it.
 */
import {
  cpSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'dream';
export const summary = 'cross-layer consolidation: the plan, and both directories after it';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'dream_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

// ------------------------------------------------------------------------- fixtures

/**
 * One fact file, built through the PORT'S OWN emitter.
 *
 * Deliberate, and it is not circular. `codec.mjs` compares `formatFact` to PyYAML's
 * `safe_dump` byte for byte over 152 facts, so what this writes is what CPython would have
 * written — while a fixture hand-spelled here is a THIRD YAML author, and the first draft
 * of this file proved the point: `links: ` with a trailing space before a block sequence is
 * a document PyYAML reads and this port's frontmatter grammar refuses, and 15 cases failed
 * on the harness's own typo rather than on anything `dream` does. Fixture bytes come from
 * the emitter; codec owns whether the emitter is right.
 *
 * `rawFact` below is the escape hatch for the one scenario that needs frontmatter the
 * emitter would never produce.
 */
let formatFact;
const factFile = (
  n,
  {
    description = `about ${n}`,
    type = 'feedback',
    created = '2026-08-21',
    last = '2026-09-06',
    links = [],
    body = 'b',
  } = {},
) => formatFact({ name: n, description, type, created, last_recalled: last, links, body });

/** Frontmatter spelled by hand, for a scalar shape the emitter cannot be asked for. */
const rawFact = (n, { description, type = 'feedback', created = '2026-08-21', body = 'b' }) =>
  `---\nname: ${n}\ndescription: ${description}\ntype: ${type}\ncreated: '${created}'\n` +
  `last_recalled: '2026-09-06'\nlinks: []\n---\n\n${body}\n`;

/**
 * Noon UTC of a named day.
 *
 * `_mtime_date` is `date.fromtimestamp(...)`, which is LOCAL on both runtimes. Noon UTC
 * keeps the DATE the same in every timezone this harness can run in, so a scenario whose
 * whole point is which side has the later day does not become a different scenario when
 * the laptop moves.
 */
const noon = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return Date.UTC(y, m - 1, d, 12) / 1000;
};

/** Materialise one store spec at `root`. */
function materialise(root, spec) {
  mkdirSync(root, { recursive: true });
  if (spec.copyFrom) cpSync(spec.copyFrom, root, { recursive: true, preserveTimestamps: true });
  for (const dir of spec.dirs ?? ['facts', 'archive']) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), Buffer.from(content, 'utf8'));
  }
  // Applied last: writing a file sets its mtime, so the pins have to come after the writes.
  for (const [path, day] of Object.entries(spec.mtimes ?? {})) {
    const when = noon(day);
    utimesSync(join(root, path), when, when);
  }
}

/**
 * Every path under `root`, with what it is and what it holds.
 *
 * Directory entries and symlink targets are in the manifest, not just file bytes: a port
 * that answered correctly while leaving a `.md.tmp` behind, or that created the `index.md`
 * the profile store has never had, would pass a content-only diff.
 */
function manifest(root) {
  const lines = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch (e) {
      lines.push(`${relative(root, dir) || '.'}\tUNREADABLE\t${e.code}`);
      return;
    }
    for (const entry of entries.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
      const full = join(dir, entry);
      const rel = relative(root, full);
      const st = lstatSync(full);
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${readlinkSync(full)}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else {
        const bytes = readFileSync(full);
        lines.push(`${rel}\tfile\t${bytes.length}\t${bytes.toString('base64')}`);
      }
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

// -------------------------------------------------------------- the Node side, shaped

/** `DreamResult` as `dream_ref.py` spells it: snake_case keys, base64 strings, roots scrubbed. */
function nodeResult(store, result, projectRoot, profileRoot) {
  const scrub = (v) => v.split(projectRoot).join('<PROJECT>').split(profileRoot).join('<PROFILE>');
  const text = (v) => b64(store.pyText(v));
  const hit = (h) => ({
    name: text(h.name),
    layer: b64(h.layer),
    term: b64(h.term),
    resolved: b64(h.resolved),
    basis: b64(h.basis),
  });
  const sup = (r) => ({
    subject: b64(r.subject),
    kept: b64(r.kept),
    kept_layer: b64(r.keptLayer),
    kept_date: b64(r.keptDate),
    lost: b64(r.lost),
    lost_layer: b64(r.lostLayer),
    lost_date: b64(r.lostDate),
  });
  return {
    applied: result.applied,
    dry_run: result.dryRun,
    merged: result.merged.map((m) => ({
      name: text(m.name),
      kind: m.kind,
      jaccard: m.jaccard,
      survivor_layer: b64(m.survivorLayer),
      consumed_layer: b64(m.consumedLayer),
      body_before: m.bodyBefore,
      body_after: m.bodyAfter,
      blocks_added: m.blocksAdded,
      superseded: m.superseded.map(sup),
    })),
    refused: result.refused.map(([n, why]) => [text(n), b64(scrub(why))]),
    absolutised: result.absolutised.map(hit),
    unresolved: result.unresolved.map(hit),
    similar_unmerged: result.similarUnmerged.map((p) => ({
      project_name: text(p.projectName),
      profile_name: text(p.profileName),
      jaccard: p.jaccard,
    })),
    consumed: result.consumed.map(text),
    rewritten: result.rewritten.map(text),
    archive_dir: b64(scrub(result.archiveDir)),
    index_before: result.indexBefore,
    index_after: result.indexAfter,
    budget: result.budget,
    profile_index_before: result.profileIndexBefore,
    profile_index_after: result.profileIndexAfter,
    fact_bytes_before: result.factBytesBefore,
    fact_bytes_after: result.factBytesAfter,
    project_root: b64(scrub(result.projectRoot)),
    profile_root: b64(scrub(result.profileRoot)),
    over_budget: result.overBudget,
    changes: result.changes,
    superseded: result.superseded.map(sup),
  };
}

function runNode(store, dreamer, request) {
  const results = [];
  for (let pass = 0; pass < (request.passes ?? 1); pass += 1) {
    try {
      const project = new store.MemoryStore(request.project, {
        create: request.create ?? true,
        ...(request.index_budget === null ? {} : { indexBudget: request.index_budget }),
      });
      const profile = new store.MemoryStore(request.profile, {
        create: request.create ?? true,
        ...(request.profile_index_budget === null
          ? {}
          : { indexBudget: request.profile_index_budget }),
      });
      const out = dreamer.dream(project, profile, request.dry_run ?? true);
      results.push(nodeResult(store, out, request.project, request.profile));
    } catch (e) {
      const message = String(e?.message ?? e)
        .split(request.project)
        .join('<PROJECT>')
        .split(request.profile)
        .join('<PROFILE>');
      results.push({ error: { type: e?.name ?? 'Error', message: b64(message) } });
    }
  }
  return { results };
}

// ------------------------------------------------------------------------- the corpus

/**
 * The measured shape, rewritten so no private content is committed: same name, DIVERGED
 * bodies, and every cheap clock pointing the wrong way.
 *
 * `created` runs backwards against content age — the project copy is the older fact and
 * holds the newer paragraph — which refutes newest-`created`-wins. The profile body is the
 * longer one, which refutes longest-body-wins. Both carry a `Deploys:` claim slot with
 * DIFFERENT values, so the contradiction rule fires and the mtimes decide it.
 */
const PROJECT_BODY =
  'Deploys: standing, review it and ship it.\n' +
  '\n' +
  '**AMENDED today: publishing is not unconditionally standing.** Opening this job the ' +
  'user reserved the publish decision for themselves.\n' +
  '\n' +
  'The reverse also holds: when they say nothing, publishing is standing.';
const PROFILE_BODY =
  'Deploys: authorized, granted twice, always report.\n' +
  '\n' +
  'TAGGING IS NOT AUTHORIZED and never has been.\n' +
  '\n' +
  'Merge style: squash and KEEP the branch.\n' +
  '\n' +
  'Verify after merging with git and not the API; the endpoint throws 503s.';

const divergedProject = (extra = {}) => ({
  files: {
    'facts/deploy-standing-tag-withheld.md': factFile('deploy-standing-tag-withheld', {
      description: 'whether to ask before deploying tagging or publishing a release',
      created: '2026-08-21',
      links: ['every-change-ships-to-npm-not-just-to-main'],
      body: PROJECT_BODY,
    }),
    'index.md':
      '- [[deploy-standing-tag-withheld]] (feedback) — whether to ask before deploying\n',
    ...(extra.files ?? {}),
  },
  mtimes: { 'facts/deploy-standing-tag-withheld.md': '2026-09-06', ...(extra.mtimes ?? {}) },
  ...(extra.dirs ? { dirs: extra.dirs } : {}),
});

const divergedProfile = (extra = {}) => ({
  files: {
    'facts/deploy-standing-tag-withheld.md': factFile('deploy-standing-tag-withheld', {
      description: 'why a deploy can still get blocked after a context compaction',
      created: '2026-08-27',
      links: ['bantamkit-program-resume-pointer'],
      body: PROFILE_BODY,
    }),
    ...(extra.files ?? {}),
  },
  // The profile store has NO index.md and never has: J45-1 measured that, and a dream that
  // creates one is a visible change to the user's home directory. The tree diff is where a
  // port that rebuilds unconditionally is caught.
  mtimes: { 'facts/deploy-standing-tag-withheld.md': '2026-08-27', ...(extra.mtimes ?? {}) },
  ...(extra.dirs ? { dirs: extra.dirs } : {}),
});

const identicalStore = (name, day) => ({
  files: {
    [`facts/${name}.md`]: factFile(name, {
      description: 'one ruling held under two names',
      body: 'the same body, to the byte',
    }),
  },
  mtimes: { [`facts/${name}.md`]: day },
});

/**
 * A contradiction where the only thing separating the two claims is the fact file's mtime.
 *
 * `day` is the PROFILE side's day; the project side is always 2026-09-01. Passing the same
 * day builds the TIE, which the rule sends to the project layer.
 */
const contradiction = (side, day) => ({
  files: {
    'facts/release-rules.md': factFile('release-rules', {
      description: side === 'project' ? 'the release rules as the repo holds them'
                                      : 'the release rules as the machine holds them',
      body:
        side === 'project'
          ? 'Publish channel: npm only.\n\nProject-only paragraph nobody else holds.'
          : 'Publish channel: npm and PyPI.\n\nProfile-only paragraph nobody else holds.',
    }),
  },
  mtimes: { 'facts/release-rules.md': side === 'project' ? '2026-09-01' : day },
});

// ------------------------------------------------------------------------ scenarios

function scenarios() {
  const list = [];
  const add = (label, project, profile, options = {}) =>
    list.push({ label, project, profile, options });

  // 1-3. THE MEASURED SHAPE, three ways: applied, previewed, and applied twice.
  add('a diverged pair is unioned and the profile copy is archived',
    divergedProject(), divergedProfile(), { dry_run: false });
  add('the same diverged pair as a dry run writes nothing',
    divergedProject(), divergedProfile(), { dry_run: true });
  add('the same diverged pair, applied twice, is idempotent',
    divergedProject(), divergedProfile(), { dry_run: false, passes: 2 });

  // 4. The 13-of-14 shape. The two facts are byte-identical, so `kind` is `identical` and
  // ONLY the project copy is scanned for dates — a port that scanned both reports the same
  // edit twice and differs on `absolutised`.
  add('a byte-identical cross-layer pair collapses to one copy',
    { ...identicalStore('shared-ruling', '2026-09-02'),
      files: { ...identicalStore('shared-ruling', '2026-09-02').files,
               'index.md': '- [[shared-ruling]] (feedback) — one ruling held under two names\n' } },
    identicalStore('shared-ruling', '2026-08-20'),
    { dry_run: false });

  // 5-6. THE TIE-BREAK, both arms. J45-3 measured a mutation of this rule that survived
  // every node on both sides; these two scenarios differ ONLY in the profile file's mtime,
  // so a port that broke the comparison keeps one of them and loses the other.
  add('a contradiction with EQUAL mtimes goes to the project layer',
    contradiction('project'), contradiction('profile', '2026-09-01'), { dry_run: false });
  add('a contradiction the profile layer wrote LATER goes to the profile layer',
    contradiction('project'), contradiction('profile', '2026-09-04'), { dry_run: false });

  // 7. Dates resolve against the FACT FILE's mtime, never today. The two facts carry the
  // same word and different mtimes, so a port resolving against `today` collapses two
  // different answers into one.
  add('relative dates resolve against each fact\'s own mtime, not today',
    {
      files: {
        'facts/older-note.md': factFile('older-note', {
          description: 'a note written in august',
          body: 'Measured today. Filed yesterday. Started 3 weeks ago and 2 days ago.',
        }),
        'facts/newer-note.md': factFile('newer-note', {
          description: 'a note written in september',
          body: 'Measured today. Due tomorrow. Right now it is unfinished.',
        }),
        'facts/already-stamped.md': factFile('already-stamped', {
          description: 'a note a dream has already annotated',
          body: 'Measured today (2026-08-15). Filed yesterday (2026-08-14).',
        }),
        'facts/vague-note.md': factFile('vague-note', {
          description: 'a note whose dates cannot be resolved at all',
          body: 'Measured recently, and again last month, and 3 months ago.',
        }),
        'index.md': '- [[older-note]] (feedback) — a note written in august\n',
      },
      mtimes: {
        'facts/older-note.md': '2026-08-15',
        'facts/newer-note.md': '2026-09-05',
        'facts/already-stamped.md': '2026-08-15',
        'facts/vague-note.md': '2026-07-01',
      },
    },
    { files: {} },
    { dry_run: false });

  // 8. THE OVERFLOW BOUNDARY, in a store rather than in isolation, so the guard is proved
  // where it matters: the pass completes and writes. Before J45-4 this fixture raised
  // `OverflowError` out of `dream()` on BOTH runtimes — with two DIFFERENT sentences.
  add('a body whose day arithmetic leaves the calendar is reported, not raised',
    {
      files: {
        // The basis is 2026-09-06, whose ordinal is 739865. 739864 days back is
        // 0001-01-01, the last day that exists; 739865 is one past it.
        'facts/huge-dates.md': factFile('huge-dates', {
          description: 'a body carrying day counts no calendar can hold',
          body:
            'It landed 739864 days ago, or maybe 739865 days ago.\n' +
            '\n' +
            'Some say 999999999 days ago, some 1000000000 days ago, some ' +
            '2147483647 days ago, some 2147483648 days ago, and one said ' +
            '999999999999 days ago.\n' +
            '\n' +
            'In weeks: 105695 weeks ago and 142857143 weeks ago. And today.',
        }),
        'index.md': '- [[huge-dates]] (feedback) — a body carrying day counts\n',
      },
      mtimes: { 'facts/huge-dates.md': '2026-09-06' },
    },
    { files: {} },
    { dry_run: false });

  // 9. An occupied archive slot. The pair is REFUSED and NEITHER half is touched — the two
  // tree diffs are what proves the second half of that sentence.
  add('an occupied archive entry refuses the pair and moves nothing',
    divergedProject(),
    divergedProfile({
      files: { 'archive/deploy-standing-tag-withheld.md': 'an earlier archived copy\n' },
    }),
    { dry_run: false });

  // 10. The budget. `applied` stays false and NOTHING is written — including the index
  // rebuild, which is the part a port could get wrong while returning the right plan.
  add('a plan that would not fit the index budget writes nothing',
    divergedProject(), divergedProfile(), { dry_run: false, index_budget: 40 });

  // 11. The index that must not be created. The profile store has facts and no `index.md`;
  // after a merge that archives out of it there must still be none.
  add('a profile store with no index.md never grows one',
    divergedProject(), divergedProfile(), { dry_run: false });

  // 12. The twin: a profile store that DOES have an index.md has it rebuilt, and the
  // consumed name has to leave it. Without this pair, `_rebuild_if_present` could be
  // "never rebuild" and case 11 would still pass.
  add('a profile store that has an index.md has it rebuilt without the consumed name',
    divergedProject(),
    divergedProfile({
      files: {
        'facts/profile-only.md': factFile('profile-only', {
          description: 'a fact only the machine-wide layer holds',
          body: 'Written last night and never copied down.',
        }),
        'index.md':
          '- [[deploy-standing-tag-withheld]] (feedback) — stale line\n' +
          '- [[profile-only]] (feedback) — stale line\n',
      },
      mtimes: { 'facts/profile-only.md': '2026-08-19' },
    }),
    { dry_run: false });

  // 13. Similarity is REPORTED and never acted on. The two names differ, the score is over
  // `DUPLICATE_JACCARD`, and nothing merges — a port that keyed the merge on similarity
  // instead of the name consumes a fact here and differs on all three comparisons.
  add('a cross-layer pair over the duplicate threshold with DIFFERENT names is only reported',
    {
      files: {
        'facts/alpha-token-budget.md': factFile('alpha-token-budget', {
          description: 'the token budget for alpha',
          body: 'one',
        }),
        'index.md': '- [[alpha-token-budget]] (feedback) — the token budget for alpha\n',
      },
      mtimes: { 'facts/alpha-token-budget.md': '2026-09-01' },
    },
    {
      files: {
        'facts/alpha-token-budgets.md': factFile('alpha-token-budgets', {
          description: 'the token budgets for alpha',
          body: 'two',
        }),
      },
      mtimes: { 'facts/alpha-token-budgets.md': '2026-09-01' },
    },
    { dry_run: false });

  // 14. A profile-ONLY fact carrying a relative date is left exactly as the writer left it,
  // while a project-only one beside it is rewritten. One scenario, both directions.
  add('a profile-only relative date is left alone and a project-only one is resolved',
    {
      files: {
        'facts/project-only.md': factFile('project-only', {
          description: 'a fact only the repo holds',
          body: 'Measured today and filed yesterday.',
        }),
        'index.md': '- [[project-only]] (feedback) — a fact only the repo holds\n',
      },
      mtimes: { 'facts/project-only.md': '2026-08-30' },
    },
    {
      files: {
        'facts/profile-only.md': factFile('profile-only', {
          description: 'a fact only the machine holds',
          body: 'Measured today and filed yesterday.',
        }),
      },
      mtimes: { 'facts/profile-only.md': '2026-08-30' },
    },
    { dry_run: false });

  // 15. The merge loop walks `sorted(set(project) & set(profile))`. JS sorts by UTF-16 code
  // unit and Python by codepoint, and they DISAGREE across the astral boundary — so the
  // order these three merges are reported in, and the order their archive writes happen in,
  // is a real difference and not a hypothetical one.
  add('the astral name boundary in the merge order',
    {
      files: {
        'facts/\u{1f414}.md': factFile('\u{1f414}', { description: 'shared token one', body: 'a' }),
        'facts/！.md': factFile('！', { description: 'shared token two', body: 'a' }),
        'facts/zz.md': factFile('zz', { description: 'shared token three', body: 'a' }),
        'index.md': '- [[zz]] (feedback) — shared token three\n',
      },
      mtimes: {
        'facts/\u{1f414}.md': '2026-09-01',
        'facts/！.md': '2026-09-01',
        'facts/zz.md': '2026-09-01',
      },
    },
    {
      files: {
        'facts/\u{1f414}.md': factFile('\u{1f414}', { description: 'shared token one', body: 'b' }),
        'facts/！.md': factFile('！', { description: 'shared token two', body: 'b' }),
        'facts/zz.md': factFile('zz', { description: 'shared token three', body: 'b' }),
      },
      mtimes: {
        'facts/\u{1f414}.md': '2026-08-20',
        'facts/！.md': '2026-08-20',
        'facts/zz.md': '2026-08-20',
      },
    },
    { dry_run: false });

  // 16. A frontmatter scalar in the DESCRIPTION. THE NAME OF THIS SCENARIO SAYS WHAT IT
  // ACTUALLY DOES, and the first draft's did not: it said "merge through Python's str()",
  // and the description never reaches the join at all — `merge_descriptions` calls
  // `.strip()` on the value and CPython raises `AttributeError: 'int' object has no
  // attribute 'strip'` before any merging happens, while the port raises its own
  // `TypeError`. MEASURED: mutating `mergeDescriptions` to drop the profile half left this
  // scenario GREEN, because two identical raises are still two identical answers. What it
  // pins is worth pinning — a hand-edited `description: 2026` takes down the whole pass on
  // both runtimes and the harness compares the refusal — but it is a REFUSAL case, and 16b
  // below is the one that exercises the join.
  add('an int description takes the pass down identically on both sides',
    {
      files: {
        'facts/scalar-desc.md': rawFact('scalar-desc', { description: '2026', body: 'a' }),
        'index.md': '- [[scalar-desc]] (feedback) — 2026\n',
      },
      mtimes: { 'facts/scalar-desc.md': '2026-09-01' },
    },
    {
      files: {
        'facts/scalar-desc.md': rawFact('scalar-desc', { description: '2026-08-23', body: 'b' }),
      },
      mtimes: { 'facts/scalar-desc.md': '2026-08-20' },
    },
    { dry_run: false });

  // 16b. The join itself, over the six codepoints `str.strip()` and `String.trim()` DISAGREE
  // about. `merge_descriptions` strips both halves before joining them with `; `, so a port
  // using `trim()` writes a different description into the survivor, into the fact file and
  // into the index line — and the budget is measured on that line. An ASCII fixture is green
  // either way, which is the whole reason this one is not ASCII.
  add('the merged description is stripped at the six codepoints trim() gets wrong',
    {
      files: {
        'facts/stripped-desc.md': factFile('stripped-desc', {
          description: '\u001c the repo half of the description \u0085',
          body: 'a',
        }),
        'index.md': '- [[stripped-desc]] (feedback) — the repo half\n',
      },
      mtimes: { 'facts/stripped-desc.md': '2026-09-01' },
    },
    {
      files: {
        'facts/stripped-desc.md': factFile('stripped-desc', {
          description: '\ufeff the machine half of the description \u001e',
          body: 'b',
        }),
      },
      mtimes: { 'facts/stripped-desc.md': '2026-08-20' },
    },
    { dry_run: false });

  // 17. Nothing to consolidate: no shared name, no relative date. `changes` is 0 and the
  // pass returns without writing even with `dry_run` false. Included because the OTHER
  // sixteen all write, and "returns early" is its own branch.
  add('two stores with nothing in common are left alone',
    {
      files: {
        'facts/aaa.md': factFile('aaa', { description: 'the repo side', body: 'a' }),
        'index.md': '- [[aaa]] (feedback) — the repo side\n',
      },
      mtimes: { 'facts/aaa.md': '2026-09-01' },
    },
    {
      files: { 'facts/bbb.md': factFile('bbb', { description: 'the machine side', body: 'b' }) },
      mtimes: { 'facts/bbb.md': '2026-08-20' },
    },
    { dry_run: false });

  return list;
}

// ------------------------------------- the REGISTRATION: Memory.layered -> dreamOutcome

/**
 * The second entry point, and the only one that can see WHICH two stores a session binds.
 *
 * Everything above drives `dream(project, profile, dry_run)` with both stores handed to it
 * by this harness. That is the algorithm, and it is structurally incapable of catching a
 * binding defect: the pair is the fixture's choice, so a runtime that resolved the WRONG
 * pair — or the same store twice — answers exactly what it is asked and the comparison goes
 * green. `Memory.layered(start).dreamOutcome(...)` is where the pair is CHOSEN: the project
 * store is walked up to from a directory, the profile store is `HOME/.bantamkit/memory`, and
 * whether the profile layer is pushed at all is a decision made there. Until this op existed
 * `dreamOutcome`, `memory_dream` and the `no-profile-layer` branch had no differential
 * coverage on either side — `grep -rn "dreamOutcome\|no-profile-layer" tools/conformance/`
 * returned nothing.
 *
 * `HOME` IS ALWAYS A DIRECTORY THE CASE BUILT. This op archives out of the profile layer,
 * which is a write into a home directory; pointed at a real one it destroys real facts, and
 * on 2026-09-10 it destroyed 20 of 20 of them. Both sides get `HOME`, `USERPROFILE` and an
 * emptied `BANTAMKIT_MEMORY_DIR`, each under that side's own bed.
 */

/** One bed: directories, files, symlinks, then pinned mtimes. Paths are bed-relative. */
function materialiseBed(root, spec) {
  mkdirSync(root, { recursive: true });
  for (const dir of spec.dirs ?? []) mkdirSync(join(root, dir), { recursive: true });
  for (const [path, content] of Object.entries(spec.files ?? {})) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), Buffer.from(content, 'utf8'));
  }
  // Absolute targets, so what the runtime resolves is the bed and never a relative accident.
  for (const [link, target] of spec.symlinks ?? []) {
    mkdirSync(dirname(join(root, link)), { recursive: true });
    symlinkSync(join(root, target), join(root, link));
  }
  for (const [path, day] of Object.entries(spec.mtimes ?? {})) {
    const when = noon(day);
    utimesSync(join(root, path), when, when);
  }
}

/**
 * Every path under the bed, with the bed's own root substituted out of the bytes.
 *
 * Same stance as `manifest` above — entry kinds and symlink targets, not only file bytes —
 * but the two beds differ by their root, so contents and link targets are scrubbed. An
 * unguarded run of the duplicate-layer scenario ARCHIVES, and archiving moves a file: this
 * is where that shows up even if the reply were somehow unchanged.
 */
function bedManifest(root) {
  const real = realpathSync(root);
  const scrub = (v) => v.split(root).join('<BED>').split(real).join('<BED>');
  const lines = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch (e) {
      lines.push(`${relative(root, dir) || '.'}\tUNREADABLE\t${e.code}`);
      return;
    }
    for (const entry of entries.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
      const full = join(dir, entry);
      const rel = relative(root, full);
      const st = lstatSync(full);
      if (st.isSymbolicLink()) lines.push(`${rel}\tlink\t${scrub(readlinkSync(full))}`);
      else if (st.isDirectory()) {
        lines.push(`${rel}\tdir`);
        walk(full);
      } else lines.push(`${rel}\tfile\t${scrub(readFileSync(full).toString('utf8'))}`);
    }
  };
  walk(root);
  return `${lines.join('\n')}\n`;
}

/** The Node side of one `outcome` request, shaped exactly like `dream_ref.py` answers it. */
function runNodeOutcome(component, request, env) {
  const before = new Map(Object.keys(env).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  const scrub = (v) => v.split(request.bed).join('<BED>');
  const err = (e) => ({
    error: { type: e?.name ?? 'Error', message: b64(scrub(String(e?.message ?? e))) },
  });
  try {
    let mem;
    try {
      mem = component.Memory.layered(unb64(request.start), { today: () => request.today });
    } catch (e) {
      return err(e);
    }
    const labels = mem.layerLabels().map(b64);
    const store_root = b64(scrub(mem.store.root));
    let outcome;
    try {
      outcome = mem.dreamOutcome(request.dry_run ?? true);
    } catch (e) {
      return { labels, store_root, ...err(e) };
    }
    return {
      labels,
      store_root,
      outcome: {
        reply: b64(scrub(outcome.reply)),
        status: outcome.status,
        dry_run: outcome.dryRun,
        merged: outcome.merged,
        consumed: outcome.consumed,
        absolutised: outcome.absolutised,
        superseded: outcome.superseded,
        index_before: outcome.indexBefore,
        index_after: outcome.indexAfter,
        budget: outcome.budget,
      },
    };
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

const OUTCOME_TODAY = '2026-09-06';

/**
 * Four beds: two where the walk lands ON the profile store, two where it does not.
 *
 * THE TWO CONTROLS ARE NOT DECORATION. A guard that answered "same directory" for EVERY
 * pair would pass both duplicate scenarios and cost nothing — the third and fourth beds are
 * what make that mutation visible, because there the profile layer MUST still be bound and
 * `dream` must still run across it. And every scenario is `dry_run: false`: an unguarded
 * duplicate bed does not merely report a merge, it ARCHIVES the fact out of the store it
 * just merged it into, which the bed manifest sees.
 */
function outcomeScenarios() {
  const store = (prefix, facts) => {
    const files = {};
    const mtimes = {};
    for (const [n, opts] of Object.entries(facts)) {
      files[`${prefix}/facts/${n}.md`] = factFile(n, opts);
      mtimes[`${prefix}/facts/${n}.md`] = opts.day ?? '2026-09-01';
    }
    return { files, mtimes, dirs: [`${prefix}/facts`, `${prefix}/archive`] };
  };
  const merge = (...specs) => ({
    dirs: specs.flatMap((x) => x.dirs ?? []),
    files: Object.assign({}, ...specs.map((x) => x.files ?? {})),
    mtimes: Object.assign({}, ...specs.map((x) => x.mtimes ?? {})),
    symlinks: specs.flatMap((x) => x.symlinks ?? []),
  });

  const ownFacts = {
    'probe-ruling': { description: 'a ruling the walk found in the home directory',
                      body: 'Deploys: standing, review it and ship it.', day: '2026-09-04' },
    'probe-second': { description: 'a second fact, so an archive would be visible',
                      body: 'Merge style: squash and KEEP the branch.', day: '2026-09-02' },
  };

  return [
    {
      // THE GATE. Nothing with a `.bantamkit` above `work` except the home directory itself,
      // so the walk climbs OUT of it and resolves the profile store as the PROJECT store.
      label: 'the walk lands on the profile store, so there is one layer and nothing to consolidate',
      spec: merge(store('home/.bantamkit/memory', ownFacts), { dirs: ['home/work'] }),
      home: 'home',
      start: 'home/work',
    },
    {
      // The same bed reached through a symlink. A string comparison of the two roots fails
      // here — `home` is spelled `link` on the way in and `real` on the way out — so this
      // gates the realpath choice rather than restating the case above.
      label: 'the same store under two spellings is still one layer, symlink included',
      spec: merge(store('real/.bantamkit/memory', ownFacts), {
        dirs: ['real/work'],
        symlinks: [['link', 'real']],
      }),
      home: 'link',
      start: 'link/work',
    },
    {
      // CONTROL. Two genuinely different directories holding the same fact name: the profile
      // layer must be bound and the pass must consolidate across it.
      label: 'two different directories are two layers, and the colliding fact consolidates',
      spec: merge(
        store('home/.bantamkit/memory', {
          'shared-ruling': { description: 'the rule as the machine holds it',
                             body: 'Publish channel: npm and PyPI.\n\nProfile-only paragraph.',
                             created: '2026-08-27', day: '2026-08-27' },
        }),
        store('proj/.bantamkit/memory', {
          'shared-ruling': { description: 'the rule as the repo holds it',
                             body: 'Publish channel: npm only.\n\nProject-only paragraph.',
                             created: '2026-08-21', day: '2026-09-06' },
        }),
      ),
      home: 'home',
      start: 'proj',
    },
    {
      // CONTROL. Two layers with nothing in common: bound, walked, and left alone.
      label: 'two different directories with nothing in common are two layers and no change',
      spec: merge(
        store('home/.bantamkit/memory', {
          'machine-note': { description: 'the machine side', body: 'b', day: '2026-08-20' },
        }),
        store('proj/.bantamkit/memory', {
          'repo-note': { description: 'the repo side', body: 'a', day: '2026-09-01' },
        }),
      ),
      home: 'home',
      start: 'proj',
    },
  ];
}

// ------------------------------------------------- the pure boundary, and its literals

/**
 * `absolutise` at the two places the day arithmetic stops.
 *
 * These run the function directly rather than through a store, because the boundary is
 * arithmetic and a store fixture would only add noise around it. The basis is fixed at
 * 2026-09-06, whose ordinal is 739865, so the calendar edge is 739864 days back.
 */
const BOUNDARY_BASIS = '2026-09-06';
const BOUNDARY_TERMS = [
  ['0 days', '0 days ago'],
  ['1 day', '1 days ago'],
  ['the calendar edge', '739864 days ago'],
  ['one day past the calendar edge', '739865 days ago'],
  ['one day further still', '739866 days ago'],
  ['the timedelta cap itself', '999999999 days ago'],
  ['one past the timedelta cap', '1000000000 days ago'],
  ['INT_MAX', '2147483647 days ago'],
  // The one that ACTUALLY diverged before J45-4: CPython refuses this with `Python int too
  // large to convert to C int` and the port refused it with `days=...; must have magnitude
  // <= 999999999`. Both now report it and neither spells a sentence.
  ['one past INT_MAX', '2147483648 days ago'],
  ['far past INT_MAX', '999999999999 days ago'],
  ['a count no double can hold', `${'9'.repeat(400)} days ago`],
  ['weeks inside the calendar', '105695 weeks ago'],
  ['weeks past the calendar', '105696 weeks ago'],
  ['weeks past the timedelta cap', '142857143 weeks ago'],
  ['a forward term cannot overflow', 'tomorrow'],
  ['thai digits are digits to int()', '๙๙๙๙๙๙๙๙๙๙๙๙ days ago'],
];

/**
 * The two rules a differential is structurally blind to, pinned as literals against EACH
 * side separately.
 *
 * MEASURED, J45-3: the mutation "an mtime tie goes to the OTHER side" survived all 35
 * Python nodes and all 45 TypeScript nodes, because the rule is written twice and asserted
 * nowhere — flip both halves and the two runtimes still agree, so no comparison between
 * them can see it. The same is true of the calendar edge. A literal is the only shape that
 * reddens for a symmetric regression, so these do not compare the runtimes to each other:
 * each side is compared to a typed constant.
 */
function literalCases(pySide, nodeSide, label, expected) {
  return [
    { name: `${label} — python`, kind: 'json', expected, actual: pySide },
    { name: `${label} — node`, kind: 'json', expected, actual: nodeSide },
  ];
}

// ------------------------------------------------------------------------------- run

export async function run(ctx) {
  const store = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const dreamer = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'dream.js')).href);
  const cases = [];
  const notes = [];

  formatFact = (await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'factfile.js')).href)).formatFact;
  const list = scenarios();
  let n = 0;
  for (const { label, project, profile, options } of list) {
    n += 1;
    const bed = join(ctx.scratch, `d${String(n).padStart(2, '0')}`);
    const roots = {};
    for (const side of ['py', 'node']) {
      roots[side] = { project: join(bed, side, 'project'), profile: join(bed, side, 'profile') };
      materialise(roots[side].project, project);
      materialise(roots[side].profile, profile);
    }
    const request = (side) => ({
      op: 'run',
      project: roots[side].project,
      profile: roots[side].profile,
      dry_run: options.dry_run ?? true,
      index_budget: options.index_budget ?? null,
      profile_index_budget: options.profile_index_budget ?? null,
      create: options.create ?? true,
      passes: options.passes ?? 1,
    });
    const py = ctx.runPython(REF, request('py'));
    const nd = runNode(store, dreamer, request('node'));

    cases.push({ name: `${label} — plan`, kind: 'json', expected: py.results, actual: nd.results });
    cases.push({
      name: `${label} — project tree`,
      kind: 'bytes',
      expected: manifest(roots.py.project),
      actual: manifest(roots.node.project),
    });
    cases.push({
      name: `${label} — profile tree`,
      kind: 'bytes',
      expected: manifest(roots.py.profile),
      actual: manifest(roots.node.profile),
    });
  }
  notes.push(`${list.length} scenarios compared, each on the plan and BOTH directories`);

  // ------------------------------------------------------ the pure boundary, side by side
  const boundaryCases = BOUNDARY_TERMS.map(([, term]) => [
    b64(`It landed ${term}, they said.`),
    BOUNDARY_BASIS,
    b64('huge-dates'),
    'project',
  ]);
  const pyBoundary = ctx.runPython(REF, { op: 'absolutise', cases: boundaryCases }).out;
  const ndBoundary = boundaryCases.map(([body, basis, nm, layer]) => {
    try {
      const [text, hits, unresolved] = dreamer.absolutise(
        Buffer.from(body, 'base64').toString('utf8'),
        basis,
        Buffer.from(nm, 'base64').toString('utf8'),
        layer,
      );
      const hit = (h) => ({
        name: b64(store.pyText(h.name)),
        layer: b64(h.layer),
        term: b64(h.term),
        resolved: b64(h.resolved),
        basis: b64(h.basis),
      });
      return { body: b64(text), hits: hits.map(hit), unresolved: unresolved.map(hit) };
    } catch (e) {
      return { error: { type: e?.name ?? 'Error', message: b64(String(e?.message ?? e)) } };
    }
  });
  BOUNDARY_TERMS.forEach(([why], i) => {
    cases.push({
      name: `absolutise at ${why} (${BOUNDARY_TERMS[i][1]})`,
      kind: 'json',
      expected: pyBoundary[i],
      actual: ndBoundary[i],
    });
  });
  const sentence = (row) => {
    if (row.error) return `RAISED ${row.error.type}`;
    return Buffer.from(row.body, 'base64').toString('utf8');
  };
  notes.push(
    `boundary at basis ${BOUNDARY_BASIS}: "739864 days ago" -> ` +
      `${JSON.stringify(sentence(pyBoundary[2]))}, "739865 days ago" -> ` +
      `${JSON.stringify(sentence(pyBoundary[3]))}; neither side raises on any of the ` +
      `${BOUNDARY_TERMS.length} terms`,
  );

  // ------------------------------------------------------------------ literal 1: the edge
  // Not a differential. Before J45-4 BOTH sides raised here, with two different sentences;
  // a comparison that only asked "do they agree" would have gone green the moment one
  // sentence was copied to the other side, and the crash would have shipped.
  cases.push(
    ...literalCases(
      { text: sentence(pyBoundary[2]), raised: Boolean(pyBoundary[2].error) },
      { text: sentence(ndBoundary[2]), raised: Boolean(ndBoundary[2].error) },
      'the calendar edge resolves and does not raise',
      { text: 'It landed 739864 days ago (0001-01-01), they said.', raised: false },
    ),
    ...literalCases(
      {
        text: sentence(pyBoundary[3]),
        raised: Boolean(pyBoundary[3].error),
        unresolved: (pyBoundary[3].unresolved ?? []).map((h) =>
          Buffer.from(h.term, 'base64').toString('utf8'),
        ),
        rewritten: (pyBoundary[3].hits ?? []).length,
      },
      {
        text: sentence(ndBoundary[3]),
        raised: Boolean(ndBoundary[3].error),
        unresolved: (ndBoundary[3].unresolved ?? []).map((h) =>
          Buffer.from(h.term, 'base64').toString('utf8'),
        ),
        rewritten: (ndBoundary[3].hits ?? []).length,
      },
      'one day past the calendar edge is reported and the body is untouched',
      {
        text: 'It landed 739865 days ago, they said.',
        raised: false,
        unresolved: ['739865 days ago'],
        rewritten: 0,
      },
    ),
  );

  // -------------------------------------------------------------- literal 2: the tie-break
  // Scenarios 5 and 6 differ only in the profile file's mtime. A differential over them is
  // blind to a symmetric flip of the rule; this is not. `kept_layer` is read out of each
  // side's own answer and compared to the constant the rule says it must be.
  {
    const tieIndex = list.findIndex((s) => s.label.includes('EQUAL mtimes'));
    const laterIndex = list.findIndex((s) => s.label.includes('LATER'));
    const keptOf = (results) => {
      const records = results?.[0]?.superseded ?? [];
      return records.map((r) => ({
        subject: Buffer.from(r.subject, 'base64').toString('utf8'),
        kept_layer: Buffer.from(r.kept_layer, 'base64').toString('utf8'),
        lost_layer: Buffer.from(r.lost_layer, 'base64').toString('utf8'),
      }));
    };
    const rerun = (index, side) => {
      const s = list[index];
      const bed = join(ctx.scratch, `tie-${index}-${side}`);
      const project = join(bed, 'project');
      const profile = join(bed, 'profile');
      materialise(project, s.project);
      materialise(profile, s.profile);
      const request = {
        op: 'run', project, profile, dry_run: true, index_budget: null,
        profile_index_budget: null, create: true, passes: 1,
      };
      return side === 'py'
        ? ctx.runPython(REF, request).results
        : runNode(store, dreamer, request).results;
    };
    cases.push(
      ...literalCases(
        keptOf(rerun(tieIndex, 'py')),
        keptOf(rerun(tieIndex, 'node')),
        'an mtime TIE keeps the project claim and retires the profile one',
        [{ subject: 'publish channel', kept_layer: 'project', lost_layer: 'profile' }],
      ),
      ...literalCases(
        keptOf(rerun(laterIndex, 'py')),
        keptOf(rerun(laterIndex, 'node')),
        'a LATER profile mtime keeps the profile claim and retires the project one',
        [{ subject: 'publish channel', kept_layer: 'profile', lost_layer: 'project' }],
      ),
    );
  }

  // ------------------------------------ the registration: Memory.layered -> dreamOutcome
  const component = await import(
    pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'component.js')).href
  );
  // `realpathSync` for the same reason `recall-strings` does it: the walk resolves the
  // directory it started from, so an unresolved scratch root (`/var` on macOS) would be
  // scrubbed out of one side's answer and left in the other's.
  const outcomeScratch = realpathSync(ctx.scratch);
  const outcomes = {};
  let o = 0;
  for (const { label, spec, home, start } of outcomeScenarios()) {
    o += 1;
    const bed = join(outcomeScratch, `o${String(o).padStart(2, '0')}`);
    const roots = {};
    const answers = {};
    for (const side of ['py', 'node']) {
      roots[side] = join(bed, side);
      materialiseBed(roots[side], spec);
    }
    const request = (side) => ({
      op: 'outcome',
      start: b64(join(roots[side], start)),
      bed: roots[side],
      today: OUTCOME_TODAY,
      dry_run: false,
    });
    const envFor = (side) => ({
      HOME: join(roots[side], home),
      USERPROFILE: join(roots[side], home),
      BANTAMKIT_MEMORY_DIR: '',
    });
    answers.py = ctx.runPython(REF, request('py'), envFor('py'));
    answers.node = runNodeOutcome(component, request('node'), envFor('node'));
    outcomes[label] = answers;

    cases.push({ name: `${label} — outcome`, kind: 'json',
                 expected: answers.py, actual: answers.node });
    cases.push({ name: `${label} — bed tree`, kind: 'bytes',
                 expected: bedManifest(roots.py), actual: bedManifest(roots.node) });
  }
  notes.push(
    `${o} Memory.layered scenarios compared through dreamOutcome, each on the outcome and ` +
      'the whole bed, with HOME inside the harness scratch on both sides',
  );

  // ----------------------------------------------- literals 3 and 4: the binding decision
  // The differential above cannot see a SYMMETRIC regression: revert the guard in BOTH
  // runtimes and the two still agree, exactly the blindness J45-3 measured for the tie-break
  // and that `differential-is-blind-to-symmetric-regression` names. So the decision itself is
  // pinned against constants, on each side separately — the duplicate bed's verdict, its
  // sentence, and the control bed's, which is what a guard that fired unconditionally breaks.
  {
    const dup = outcomes[
      'the walk lands on the profile store, so there is one layer and nothing to consolidate'
    ];
    const both = outcomes[
      'two different directories are two layers, and the colliding fact consolidates'
    ];
    const decision = (a) => ({
      labels: (a.labels ?? []).map(unb64),
      status: a.outcome?.status ?? `RAISED ${a.error?.type}`,
      merged: a.outcome?.merged ?? null,
      consumed: a.outcome?.consumed ?? null,
    });
    const reply = (a) => (a.outcome ? unb64(a.outcome.reply) : `RAISED ${a.error?.type}`);
    cases.push(
      ...literalCases(
        decision(dup.py),
        decision(dup.node),
        'the walk landing on the profile store binds ONE layer and consolidates nothing',
        { labels: ['project'], status: 'no-profile-layer', merged: 0, consumed: 0 },
      ),
      ...literalCases(
        { reply: reply(dup.py) },
        { reply: reply(dup.node) },
        'and says so in the sentence that already existed for one-layer sessions',
        {
          reply:
            'nothing to consolidate: no profile layer is bound, so the project store ' +
            '<BED>/home/.bantamkit/memory is the only layer there is.',
        },
      ),
      ...literalCases(
        decision(both.py),
        decision(both.node),
        'two distinct directories still bind TWO layers and still consolidate across them',
        { labels: ['project', 'profile'], status: 'consolidated', merged: 1, consumed: 1 },
      ),
    );
  }

  return { cases, notes };
}
