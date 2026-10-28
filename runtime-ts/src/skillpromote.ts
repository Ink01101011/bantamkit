/**
 * Promotion and demotion of a learned skill (#206 Task 9, X8 second half).
 *
 * Port of `runtime-py/src/bantamkit/skillpromote.py`; the module docstring there is the design
 * note (the relative link, the copy fallback and its tree hash, the refusal order, the Q4
 * budget, the state record, demotion). `tools/conformance/suites/skill-promote.mjs` compares
 * the two: every result, every sentence, the state and the whole home after each op.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { cmpCodepoint, pyRepr } from './pysem.js';
import { auditRoots } from './skillaudit.js';
import { readState, SKILL_FILE, SkillFileError, updateState, writeDirAtomic } from './skillfile.js';
import type { SkillsState } from './skillfile.js';
import { Gathered, HOST_CLAUDE_CODE, selectAdapter } from './skillhost.js';
import { autoEnabled, InstallError, iso } from './skillinstall.js';
import { parseNow } from './storage/retention.js';

export const PROMOTE_USES = 3;
export const PROMOTE_DAYS = 30;
export const BUDGET_ENV = 'BANTAMKIT_SKILL_BUDGET';
export const BUDGET_DEFAULT = 8192;
export const MODE_SYMLINK = 'symlink';
export const MODE_COPY = 'copy';
/** Windows `ERROR_PRIVILEGE_NOT_HELD`; libuv reports it as `EPERM`. */
export const WIN_PRIVILEGE = 1314;
/** The symlink failures that mean "no right to link here": the directory is copied instead. */
export const NO_RIGHT: readonly string[] = ['EPERM', 'EACCES'];
export const CANDIDATE_LABEL = 'candidate';

const DIGITS = /^[0-9]{1,15}$/;

type Rec = Record<string, unknown>;
export type Symlink = (target: string, link: string) => void;

export class PromoteError extends SkillFileError {
  constructor(message: string) {
    super(message);
    this.name = 'PromoteError';
  }
}

export interface PromoteResult {
  ok: boolean;
  mode: string | null;
  reason: string;
}

export interface PromoteOptions {
  symlink?: Symlink | null;
  gathered?: Gathered | null;
}

const isObj = (v: unknown): v is Rec => v !== null && typeof v === 'object' && !Array.isArray(v);
const own = (o: Rec, k: string): unknown => (Object.hasOwn(o, k) ? o[k] : undefined);

function int(v: unknown): number | null {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= Number.MAX_SAFE_INTEGER ? v : null;
}

function msOf(now: string): number {
  try {
    return parseNow(now);
  } catch {
    throw new InstallError(`not a timestamp: ${pyRepr(String(now))}`);
  }
}

/** `BANTAMKIT_SKILL_BUDGET` when it is a run of ASCII digits, else `BUDGET_DEFAULT`. */
export function skillBudget(): number {
  const raw = (process.env[BUDGET_ENV] ?? '').trim();
  return DIGITS.test(raw) ? Number(raw) : BUDGET_DEFAULT;
}

function defaultSymlink(target: string, link: string): void {
  fs.symlinkSync(target, link, 'dir');
}

/** `<base>/.claude/skills/<name>` for a source at `<base>/.bantamkit/skills/<name>`. */
export function linkPath(source: string): string {
  const base = path.dirname(path.dirname(path.dirname(source)));
  return path.join(base, '.claude', 'skills', path.basename(source));
}

const lstat = (p: string): fs.Stats | null => {
  try {
    return fs.lstatSync(p);
  } catch {
    return null;
  }
};
const isLink = (p: string): boolean => lstat(p)?.isSymbolicLink() ?? false;
const isDir = (p: string): boolean => {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
};
const isFile = (p: string): boolean => {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
};

/** `os.path.realpath` (non-strict): a dangling link is followed, a missing tail kept. */
function real(p: string, depth = 0): string {
  try {
    return fs.realpathSync.native(p);
  } catch {
    const abs = path.resolve(p);
    if (depth < 40 && isLink(abs)) {
      try {
        return real(path.resolve(path.dirname(abs), fs.readlinkSync(abs)), depth + 1);
      } catch {
        /* fall through */
      }
    }
    const parent = path.dirname(abs);
    if (parent === abs) return abs;
    return path.join(real(parent, depth + 1), path.basename(abs));
  }
}

/** Every regular file under `root`, by `/`-joined relative path; symlinks not followed. */
function files(root: string): Record<string, Uint8Array> {
  const out: Record<string, Uint8Array> = {};
  const walk = (d: string, rel: string): void => {
    for (const entry of fs.readdirSync(d).sort(cmpCodepoint)) {
      const p = path.join(d, entry);
      const r = `${rel}${entry}`;
      if (isLink(p)) continue;
      if (isDir(p)) walk(p, `${r}/`);
      else if (isFile(p)) out[r] = fs.readFileSync(p);
    }
  };
  walk(root, '');
  return out;
}

/** SHA-256 over `<rel>\0<sha256 of the bytes>\n` per file, code-point order of `rel`. */
export function treeHash(root: string): string {
  const got = files(root);
  const lines = Object.keys(got)
    .sort(cmpCodepoint)
    .map((rel) => `${rel}\0${createHash('sha256').update(got[rel]!).digest('hex')}\n`)
    .join('');
  return createHash('sha256').update(lines, 'utf8').digest('hex');
}

const record = (entry: Rec): Rec | null => {
  const rec = own(entry, 'promoted');
  return isObj(rec) ? rec : null;
};

const isPromoted = (entry: Rec): boolean => {
  if (!Object.hasOwn(entry, 'promoted')) return false;
  const v = entry['promoted'];
  return v !== null && v !== false;
};

function ours(link: string, source: string, entry: Rec): boolean {
  if (isLink(link)) return real(link) === real(source);
  const rec = record(entry);
  return isDir(link) && rec !== null && rec['mode'] === MODE_COPY && rec['link'] === link;
}

const codeOf = (e: unknown): string => {
  const c = (e as { code?: unknown } | null)?.code;
  return typeof c === 'string' && c !== '' ? c : 'EUNKNOWN';
};

const isOsError = (e: unknown): boolean => e instanceof Error && typeof (e as { code?: unknown }).code === 'string';

function rootsOf(gathered: Gathered, home: string, cwd: string | null): [string, string][] {
  const roots: [string, string][] = gathered.roots.filter(([label]) => label === 'plugins').map(([l, p]) => [l, p]);
  const user = path.join(home, '.claude', 'skills');
  if (cwd !== null) {
    const project = path.join(cwd, '.claude', 'skills');
    if (real(project) !== real(user) && isDir(project)) roots.push(['project', project]);
  }
  if (isDir(user)) roots.push(['user', user]);
  return roots;
}

/**
 * The catalogue's description bytes the way #205 measures them, with the symlinked skill
 * directories of the project and user roots, and `candidate` (a skill directory), added.
 */
export function catalogueBytes(gathered: Gathered, home: string, cwd: string | null, candidate: string | null): number {
  const roots = rootsOf(gathered, home, cwd);
  const links: [string, string][] = [];
  for (const [label, root] of roots) {
    if (label === 'plugins') continue;
    for (const entry of fs.readdirSync(root).sort(cmpCodepoint)) {
      const p = path.join(root, entry);
      if (isLink(p) && isDir(p) && isFile(path.join(p, SKILL_FILE))) links.push([`${label}-link-${entry}`, p]);
    }
  }
  const every = [...roots, ...links];
  if (candidate !== null) every.push([CANDIDATE_LABEL, candidate]);
  if (every.length === 0) return 0;
  return auditRoots(
    every.map(([label, p]) => ({ label, path: p })),
    {
      enabled: [...gathered.enabled],
      check: 'budget',
      versions: gathered.versions === null ? null : new Map(Object.entries(gathered.versions)),
    },
  ).catalogueBytes;
}

function entryOf(home: string, name: string): Rec | null {
  const skills = readState(home).skills as Rec;
  const entry = own(skills, name);
  return isObj(entry) && typeof entry['path'] === 'string' ? entry : null;
}

/** A native link for one installed skill, or the sentence saying why not. */
export function promote(
  name: string,
  home: string,
  cwd: string | null,
  now: string,
  budget: number | null = null,
  opts: PromoteOptions = {},
): PromoteResult {
  const nowMs = msOf(now);
  const refuse = (reason: string): PromoteResult => ({ ok: false, mode: null, reason });
  const entry = entryOf(home, name);
  if (entry === null) return refuse(`no skill named ${pyRepr(name)} is installed`);
  const source = entry['path'] as string;
  if (!isFile(path.join(source, SKILL_FILE))) return refuse(`skill ${name} has no ${SKILL_FILE} at ${source}`);
  const gathered = opts.gathered ?? selectAdapter(home).gather(home, cwd, nowMs);
  if (gathered.host !== HOST_CLAUDE_CODE) return refuse('promotion is Claude Code only; this host has no skill directory');
  const link = linkPath(source);
  if (lstat(link) !== null) {
    if (ours(link, source, entry)) {
      const mode = record(entry)?.['mode'];
      return { ok: true, mode: mode === MODE_COPY ? MODE_COPY : MODE_SYMLINK, reason: `${name} is already promoted` };
    }
    return refuse(`${link} already exists and is not this skill's link`);
  }
  const limit = budget ?? skillBudget();
  const total = catalogueBytes(gathered, home, cwd, source);
  if (total > limit) {
    return refuse(`promoting ${name} would take the catalogue to ${total} bytes, over the budget of ${limit}`);
  }
  fs.mkdirSync(path.dirname(link), { recursive: true });
  const rec: Rec = { at: now, link };
  try {
    (opts.symlink ?? defaultSymlink)(path.relative(path.dirname(link), source), link);
    rec['mode'] = MODE_SYMLINK;
  } catch (e) {
    if (!isOsError(e)) throw e;
    if (!NO_RIGHT.includes(codeOf(e))) return refuse(`could not link ${link}: ${codeOf(e)}`);
    writeDirAtomic(link, files(source));
    rec['mode'] = MODE_COPY;
    rec['tree_sha256'] = treeHash(link);
  }
  updateState(home, (state: SkillsState) => {
    const live = own(state.skills as Rec, name);
    if (isObj(live)) {
      live['promoted'] = rec;
      delete live['promote_refused'];
    }
  });
  return { ok: true, mode: rec['mode'] as string, reason: `promoted skill ${name}` };
}

let counter = 0;

function removeDir(target: string): void {
  counter += 1;
  const aside = `${target}.old-${process.pid}-${counter}`;
  fs.renameSync(target, aside);
  try {
    fs.rmSync(aside, { recursive: true, force: true });
  } catch {
    /* best effort, as the reference's ignore_errors */
  }
}

/** Remove the native link (a copy only while unchanged); the source is never touched. */
export function demote(name: string, home: string): string {
  const entry = entryOf(home, name);
  if (entry === null) throw new PromoteError(`no skill named ${pyRepr(name)} is installed`);
  if (!isPromoted(entry)) throw new PromoteError(`skill ${name} is not promoted`);
  const source = entry['path'] as string;
  const rec = record(entry) ?? {};
  const link = typeof rec['link'] === 'string' ? rec['link'] : linkPath(source);
  const changed = `${link} was changed after promotion; remove it yourself or keep it`;
  if (isLink(link)) {
    if (real(link) !== real(source)) throw new PromoteError(changed);
    fs.unlinkSync(link);
  } else if (lstat(link) !== null) {
    if (rec['mode'] !== MODE_COPY || !isDir(link) || treeHash(link) !== rec['tree_sha256']) throw new PromoteError(changed);
    removeDir(link);
  }
  updateState(home, (state: SkillsState) => {
    const live = own(state.skills as Rec, name);
    if (isObj(live)) {
      delete live['promoted'];
      delete live['promote_refused'];
    }
  });
  return `demoted skill ${name}`;
}

function refusedToday(entry: Rec, today: string): boolean {
  const r = own(entry, 'promote_refused');
  if (!isObj(r) || typeof r['at'] !== 'string') return false;
  try {
    return iso(msOf(r['at'])).slice(0, 10) === today;
  } catch (e) {
    if (e instanceof SkillFileError) return false;
    throw e;
  }
}

/**
 * Promote every live skill with `PROMOTE_USES` uses in the last `PROMOTE_DAYS`; the events.
 * `uses[name]` is the caller's count over that window (R10). A refusal is recorded on the
 * skill (`promote_refused`) and that skill is not tried again the same UTC day. `state` is
 * read for the decisions and replaced in place by the state written. With
 * `BANTAMKIT_SKILL_AUTO` off (the 0.37.0 default) it does nothing at all: no promotion, no
 * refusal recorded, no gather (job73 ruling; `promote` itself never reads the switch).
 */
export function promoteStep(
  state: Rec,
  uses: Record<string, unknown>,
  home: string,
  cwd: string | null,
  now: string,
  budget: number | null = null,
  opts: PromoteOptions = {},
): string[] {
  const nowMs = msOf(now);
  if (!autoEnabled()) return [];
  const today = iso(nowMs).slice(0, 10);
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const due = Object.keys(skills)
    .sort(cmpCodepoint)
    .filter((n) => {
      const e = skills[n];
      return isObj(e) && !isPromoted(e) && (int(own(uses, n)) ?? 0) >= PROMOTE_USES && !refusedToday(e, today);
    });
  if (due.length === 0) return [];
  const gathered = opts.gathered ?? selectAdapter(home).gather(home, cwd, nowMs);
  const events: string[] = [];
  for (const name of due) {
    const got = promote(name, home, cwd, now, budget, { symlink: opts.symlink ?? null, gathered });
    if (got.ok) {
      events.push(got.reason);
      continue;
    }
    updateState(home, (fresh: SkillsState) => {
      const live = own(fresh.skills as Rec, name);
      if (isObj(live)) live['promote_refused'] = { at: now, reason: got.reason };
    });
  }
  const fresh = readState(home);
  for (const k of Object.keys(state)) delete state[k];
  Object.assign(state, fresh);
  return events;
}
