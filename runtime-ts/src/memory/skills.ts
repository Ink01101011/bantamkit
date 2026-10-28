/**
 * bantamkit's own learned skills as a read-only recall layer, tagged `[skill]` (#206, X8).
 * Port of `runtime-py/src/bantamkit/memory/skills.py`; the reference's docstring is the
 * contract (roots, what is left out silently and what is named, read-only, no hot index).
 * `tools/conformance/suites/skill-layer.mjs` compares the two.
 */
import * as fs from 'node:fs';

import { BantamError } from '../errors.js';
import { cmpCodepoint, pyStrip } from '../pysem.js';
import { parseSkill, readState, SKILL_FILE, SkillFileError, skillsRoot, validate } from '../skillfile.js';
import { DUPLICATE } from '../storage/hotindex.js';
import type { Fact } from './factfile.js';
import { asPyOSError, pyDecodeUtf8, pyHome, pyIsFile, pyJoin, pyName, pyParent } from './pyfs.js';
import { oneLine, poolOf, type Pool, type SkippedFact } from './store.js';

/** The label the layer's hits carry: `[skill] [name] (skill) description`. */
export const SKILL_LAYER = 'skill';
/** The type every skill fact carries; absent from `W_TYPE`, so it weighs `W_TYPE_OTHER`. */
export const SKILL_TYPE = 'skill';
/** The metadata key whose comma-separated value is the fact's `keywords` (R9). */
export const KEYWORDS_KEY = 'bantamkit-keywords';

// What `skillfile`'s temp naming calls a directory it is building or has set aside.
const NOT_A_SKILL_DIR = /^[\s\S]+\.(?:tmp|old)-[0-9]+-[0-9]+$/;
const EMPTY: ReadonlySet<string> = new Set();

/** The layer's roots for a project store: its `.bantamkit/skills`, then the user's. */
export function skillRoots(projectStore: string, home: string): string[] {
  const roots: string[] = [];
  const parent = pyParent(projectStore);
  if (pyName(parent) === '.bantamkit') roots.push(pyJoin(parent, 'skills'));
  const user = skillsRoot(home);
  if (!roots.some((r) => same(user, r))) roots.push(user);
  return roots;
}

function same(a: string, b: string): boolean {
  return realpath(a) === realpath(b);
}

/** `os.path.realpath`: the resolved path, or the longest existing prefix resolved. */
function realpath(p: string): string {
  try {
    return fs.realpathSync.native(p);
  } catch {
    const parent = pyParent(p);
    if (parent === p) return p;
    return pyJoin(realpath(parent), pyName(p));
  }
}

/**
 * Names `skills-state.json` records as promoted: an entry whose `promoted` is set — present,
 * not `null` and not `false`. A state file that cannot be read excludes nothing.
 */
export function promotedNames(home: string): ReadonlySet<string> {
  let skills: Record<string, unknown>;
  try {
    skills = readState(home).skills;
  } catch (e) {
    if (e instanceof SkillFileError || (e !== null && typeof e === 'object' && 'code' in e)) return EMPTY;
    throw e;
  }
  const out = new Set<string>();
  for (const [name, entry] of Object.entries(skills)) {
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) continue;
    if (!Object.prototype.hasOwnProperty.call(entry, 'promoted')) continue;
    const value = (entry as Record<string, unknown>).promoted;
    if (value !== null && value !== undefined && value !== false) out.add(name);
  }
  return out;
}

/** `metadata.bantamkit-keywords` split on `,`, each stripped, the empty ones dropped. */
export function keywordsOf(value: unknown): string[] {
  if (typeof value !== 'string') return [];
  return value
    .split(',')
    .map((part) => pyStrip(part))
    .filter((k) => k !== '');
}

export class SkillStore {
  readonly roots: string[];
  /** The store's identity for the queries sidecar and the unreadable-layer report. */
  readonly root: string;
  private readonly home: string | null;

  constructor(roots: readonly string[], home: string | null = null) {
    this.roots = [...roots];
    this.root = this.roots[0]!;
    this.home = home;
  }

  private stateHome(): string {
    return this.home ?? pyHome();
  }

  /** This layer keeps no hot index (see the reference's docstring). */
  index(): never {
    throw new BantamError('the skill layer keeps no hot index');
  }

  /** Every `<root>/<dir>/SKILL.md`, roots in order, directories in code-point order. */
  private listing(): string[] {
    const out: string[] = [];
    for (const root of this.roots) {
      let names: string[];
      try {
        names = fs.readdirSync(root);
      } catch (e) {
        const code = (e as NodeJS.ErrnoException).code;
        if (code === 'ENOENT' || code === 'ENOTDIR') continue; // not there: nothing, silently
        throw asPyOSError(e, root);
      }
      const dirs = names
        .filter((n) => !n.startsWith('.') && !NOT_A_SKILL_DIR.test(n) && isDir(pyJoin(root, n)))
        .sort(cmpCodepoint);
      for (const n of dirs) {
        const p = pyJoin(root, n, SKILL_FILE);
        if (pyIsFile(p)) out.push(p);
      }
    }
    return out;
  }

  /** One `SKILL.md` as a `Fact`; throws `BantamError` with the `malformed skill` sentence. */
  private read(p: string): Fact {
    let raw: Buffer;
    try {
      raw = fs.readFileSync(p);
    } catch {
      throw new BantamError(`malformed skill ${p}: SKILL.md could not be read`);
    }
    let text: string;
    try {
      text = pyDecodeUtf8(raw);
    } catch {
      throw new BantamError(`malformed skill ${p}: SKILL.md is not UTF-8`);
    }
    let doc;
    try {
      doc = parseSkill(text);
    } catch (e) {
      if (e instanceof SkillFileError) throw new BantamError(`malformed skill ${p}: ${e.message}`);
      throw e;
    }
    const broken = validate(doc, pyName(pyParent(p)));
    if (broken.length > 0) throw new BantamError(`malformed skill ${p}: ${broken.join('; ')}`);
    return {
      name: doc.name,
      description: oneLine(doc.description),
      type: SKILL_TYPE,
      body: doc.body,
      links: [],
      last_recalled: null,
      source: p,
      keywords: keywordsOf(doc.metadata[KEYWORDS_KEY]),
    };
  }

  /**
   * Every offered skill, in listing order; the promoted and the shadowed left out. A skill that
   * cannot be offered, and the second one claiming a name, go to `skipped`.
   */
  candidates(skipped?: SkippedFact[], shadow: ReadonlySet<string> = EMPTY): Fact[] {
    const promoted = promotedNames(this.stateHome());
    const out: Fact[] = [];
    const held = new Map<string, string>();
    for (const p of this.listing()) {
      const file = `${pyName(pyParent(p))}/${SKILL_FILE}`;
      let fact: Fact;
      try {
        fact = this.read(p);
      } catch (e) {
        if (!(e instanceof BantamError)) throw e;
        skipped?.push({ file, reason: e.message });
        continue;
      }
      const name = fact.name as string;
      const first = held.get(name);
      if (first !== undefined) {
        skipped?.push({ file, reason: `${DUPLICATE} '${name}': ${first} holds it` });
        continue;
      }
      held.set(name, p);
      if (!shadow.has(name) && !promoted.has(name)) out.push(fact);
    }
    return out;
  }

  /** How many skill directories the roots list; 0 when none is there. */
  count(): number {
    return this.listing().length;
  }

  /** This layer's share of a pooled recall, the `shadow` names taken out before scoring. */
  pool(q: readonly string[], skipped?: SkippedFact[], shadow: ReadonlySet<string> = EMPTY, everyRow = false): Pool {
    return poolOf(this.candidates(skipped, shadow), q, everyRow);
  }

  /** The fact a row stands for: the files answered, so the pool holds it. */
  resolve(pool: Pool, row: number): Fact | null {
    return pool.facts![row]!;
  }

  /** The offered skill named exactly `name`, or `null`. `stamp` never writes. */
  lookup(name: string, _stamp = false, skipped?: SkippedFact[]): Fact | null {
    return this.candidates(skipped).find((f) => f.name === name) ?? null;
  }

  /** A skill has no archive this layer reads. */
  archivedRecall(_query: string, _k: number, _exclude: Iterable<string> = []): Fact[] {
    return [];
  }
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}
