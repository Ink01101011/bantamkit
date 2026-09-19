/**
 * Where the real memory store is, and whether the one we found is real.
 *
 * ONE finder, imported by every suite that reads the operator's live store — today that is
 * `store.mjs` alone, `codec.mjs` having moved to the frozen corpus below. There used to
 * be two — `store.mjs` asked for the PAIR (`facts/` and `index.md`) and `codec.mjs` asked
 * for `facts/` alone — and the two drifted into a measured defect (I3-F1): a git worktree
 * in which anything had ever booted the runtime carries an EMPTY `<worktree>/.bantamkit/
 * memory/facts`, created and never written. `codec.mjs`'s finder accepted it, the 96-fact
 * store in the main checkout was never reached, and `--suite codec` fell from 494 cases to
 * 206 while still printing PASS. Measured at 952586e: `--all` was 6199 cases from the main
 * checkout and 5911 from a worktree, and nothing said so.
 *
 * Two rules come out of that, and they are the whole of this module:
 *
 *   1. A candidate is a store only if it has BOTH `facts/` and `index.md`. A directory with
 *      a `facts/` and no `index.md` is not a corpus, it is a store something created and
 *      never wrote. (Also MEASURED, run 32644269451: the server tests left exactly that at
 *      a runner's repository root, `store.mjs`'s finder — before it asked for the pair —
 *      accepted it, and its live-index block died on an uncaught ENOENT reading the
 *      `index.md` that was never there, taking the whole suite with it.)
 *
 *   2. Finding nothing is allowed; finding something SMALL silently is not. On CI there is
 *      no store at all — `.bantamkit/memory/` is gitignored — so every suite here has to
 *      survive its absence, and it does, loudly, by saying the adversarial half ran alone.
 *      What must never happen again is the middle case: a corpus that resolved, shrank by
 *      an order of magnitude, and printed PASS. `corpusIntegrityCase()` is that gate.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

/**
 * The fewest facts a RESOLVED store may carry before the corpus is presumed shadowed.
 *
 * Not a count of today's store — that number moves every time the operator saves or
 * archives a fact, and pinning it would make an unrelated `memory_save` fail the gate. It
 * is a floor far below any real store (this repo's carried 96 when the floor was written,
 * and 65 when `codec.mjs`'s header was) and far above the shadow this exists to catch,
 * which resolves to 0. A store that has genuinely fallen under it is a deliberate change
 * and gets a deliberate amendment here.
 */
export const CORPUS_FLOOR = 32;

const factsIn = (dir) => {
  try {
    return readdirSync(dir).filter((f) => f.endsWith('.md')).length;
  } catch {
    return 0;
  }
};

/**
 * Every place a store could be, in preference order, with what is actually there.
 *
 * `explicit` (--corpus / $BANTAMKIT_CONFORMANCE_CORPUS) names the FACTS directory, which is
 * the spelling both suites already took; its store root is that path's parent.
 */
export function auditCorpus(ctx) {
  const explicit = ctx.options.corpus ?? process.env.BANTAMKIT_CONFORMANCE_CORPUS;
  const roots = [];
  if (explicit) roots.push(dirname(explicit));
  roots.push(join(ctx.repoRoot, '.bantamkit', 'memory'));
  try {
    // In a worktree the store lives in the MAIN checkout, which git can name without
    // anybody hardcoding a sibling path.
    const commonDir = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      cwd: ctx.repoRoot,
      encoding: 'utf8',
    }).trim();
    roots.push(join(dirname(commonDir), '.bantamkit', 'memory'));
  } catch {
    /* not a git checkout; the other candidates still apply */
  }

  // In the MAIN checkout `--git-common-dir` names the repository root itself, so the last
  // two candidates are the same directory; a duplicate would be reported twice by the
  // integrity case and read as two problems.
  const candidates = [...new Set(roots)].map((root) => {
    const facts = join(root, 'facts');
    const hasFacts = existsSync(facts);
    const hasIndex = existsSync(join(root, 'index.md'));
    return { root, facts, hasFacts, hasIndex, factCount: hasFacts ? factsIn(facts) : 0 };
  });
  const found = candidates.find((c) => c.hasFacts && c.hasIndex) ?? null;

  return {
    root: found?.root ?? null,
    facts: found?.facts ?? null,
    factCount: found?.factCount ?? 0,
    /** Human-readable provenance for a note, whether or not anything resolved. */
    source: found?.root ?? roots.join(' | '),
    candidates,
  };
}

/**
 * The same audit shape over a corpus that is COMMITTED rather than found.
 *
 * `codec.mjs` used to build its cases from the live store above, and at three cases per fact
 * that made the suite's size a function of a gitignored directory the operator writes to all
 * day: 8166 / 8169 / 8172 cases at one unchanged commit, and 390 -> 393 on `--suite codec`
 * from a single `memory_save` between two runs (J55-1, measured at `2b5c2ad`). It now reads a
 * frozen snapshot in git, for the reason `tokenledger.mjs`'s header already states.
 *
 * ONE RULE CHANGES, AND IT IS RULE 2 INVERTED. For a live store, finding nothing is legitimate
 * — CI has none. For a committed fixture it never is: an absent or emptied `facts/` is a
 * deletion, not an environment. So the root is reported as RESOLVED whatever is on disk, which
 * puts a missing corpus under `CORPUS_FLOOR` and turns it into a failure instead of letting it
 * vanish into a quieter, smaller run. Rule 1 still applies to the pair, and the suite pins the
 * exact file count besides, because a floor of 32 cannot see a fixture that loses ten files.
 */
export function auditFrozenCorpus(root) {
  const facts = join(root, 'facts');
  const hasFacts = existsSync(facts);
  const hasIndex = existsSync(join(root, 'index.md'));
  const candidate = { root, facts, hasFacts, hasIndex, factCount: hasFacts ? factsIn(facts) : 0 };
  return {
    root,
    facts: hasFacts && hasIndex ? facts : null,
    factCount: candidate.factCount,
    source: root,
    candidates: [candidate],
  };
}

/**
 * The gate that stops a silently shrinking corpus from printing PASS.
 *
 * Two ways the measuring instrument can break, both of which HAVE broken:
 *
 *   below_floor — a store resolved and carries fewer facts than any real one does. This is
 *     what I3-F1 looked like from the inside: `realStoreFacts` resolved an empty `facts/`
 *     and the suite went on to compare 206 cases where it had compared 494.
 *   rejected_with_facts — a directory holding a store's worth of fact files was turned down
 *     for want of an `index.md`. Rule 1 is right to turn it down, but doing so silently
 *     would trade one invisible shrink for another.
 *
 * Nothing found ANYWHERE is not a failure: that is CI, where the store is gitignored, and
 * the suites announce it in a note. This case is not a Python-vs-Node comparison — it is
 * the harness measuring itself — but it rides the same rails on purpose, because a check
 * that lives outside the case list is a check `--all` does not count and cannot fail on.
 */
export function corpusIntegrityCase(audit) {
  const belowFloor =
    audit.root !== null && audit.factCount < CORPUS_FLOOR
      ? { store: audit.root, facts: audit.factCount, floor: CORPUS_FLOOR }
      : null;
  const rejectedWithFacts = audit.candidates
    .filter((c) => c.root !== audit.root && c.factCount >= CORPUS_FLOOR)
    .map((c) => ({ store: c.root, facts: c.factCount, has_index: c.hasIndex }));
  return {
    name: 'corpus: a resolved store clears the floor, and no real store was turned away',
    kind: 'json',
    expected: { below_floor: null, rejected_with_facts: [] },
    actual: { below_floor: belowFloor, rejected_with_facts: rejectedWithFacts },
  };
}
