/**
 * The skill installer (#206 Task 7): the auto rule, the caps, probation and undo.
 *
 * Port of `runtime-py/src/bantamkit/skillinstall.py`; the module docstring there is the design
 * note (the stamp, the evidence file and the Q8 cut, the auto rule, probation, undo).
 * `tools/conformance/suites/skill-install.mjs` compares the two: the bytes every install
 * writes, `skills-state.json`, and every event and sentence.
 *
 * Counts are in CODE POINTS and every sort is by code point (`cmpCodepoint`), as Python's are.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { cmpCodepoint, pyRepr } from './pysem.js';
import {
  HASH_KEY,
  SKILL_FILE,
  SkillFileError,
  backupAbsent,
  backupDir,
  backupRoot,
  canonicalHash,
  isEdited,
  parseSkill,
  projectSkillsRoot,
  readState,
  replaceDirAtomic,
  skillsRoot,
  stamp,
  undo as undoDir,
  updateState,
  validate,
  writeDirAtomic,
} from './skillfile.js';
import type { SkillsState } from './skillfile.js';
import { render as renderSkill } from './skillfile.js';
import { tokenizeV2 } from './memory/retrieval.js';
import { TUNE_KINDS, TUNE_NARROW, TUNE_WIDEN, draftsLog, gate, improve, improveBundle, logLine } from './skilldraft.js';
import type { Bundle, ChainLink } from './skilldraft.js';
import { STEP_SHARE, ngrams } from './skillmine.js';
import { LogSegment } from './storage/logsegment.js';
import { parseNow } from './storage/retention.js';

export const AUTO_ENV = 'BANTAMKIT_SKILL_AUTO';
/** The `skills:` status line's last clause, by the switch (0.37.0: off unless opted in). */
export const AUTO_SAID_ON = 'auto on';
export const AUTO_SAID_OFF = `auto off (${AUTO_ENV}=on to opt in)`;
export const AUTO_PER_DAY = 1;
export const AUTO_LIVE_MAX = 5;
export const PROBATION_DAYS = 30;
export const DAY_MS = 86_400_000;
export const KEYWORDS_MAX = 16;
/** Q8 (user ruling 2026-10-27): a project-level evidence file keeps 80 code points of a prompt. */
export const EVIDENCE_PROJECT_CHARS = 80;
export const EVIDENCE_USER_CHARS = 500;
export const EVIDENCE_FILE = 'references/evidence.md';
export const GENERATED_BY = 'bantamkit';
export const LEVEL_PROJECT = 'project';
export const LEVEL_USER = 'user';
export const AUTO_FROM: readonly string[] = ['new', 'pending', 'drafted'];
export const AUTO_DATES_KEEP = 32;
export const CORRECTED = 'corrected in the next turn: ';

/** The only values that turn automatic installs and edits on (0.37.0: opt-in). Any other
 * value, `off`/`0`/`false`/`no`, an empty one, an unknown word or none at all, leaves them off. */
const ON = new Set(['on', '1', 'true', 'yes']);
const LONE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;

type Rec = Record<string, unknown>;

export class InstallError extends SkillFileError {
  constructor(message: string) {
    super(message);
    this.name = 'InstallError';
  }
}

export interface Installed {
  name: string;
  level: string;
  path: string;
  event: string;
  entry: Rec;
}

/** The reference's `auto_enabled`: true only when `BANTAMKIT_SKILL_AUTO` is `on` (or `1`,
 * `true`, `yes`), any case, trimmed. OFF by default; it gates the automatic installs, their
 * daily draft and `improveStep`'s automatic edits, never the judge or its rollback. */
export function autoEnabled(): boolean {
  return ON.has((process.env[AUTO_ENV] ?? '').trim().toLowerCase());
}

const clean = (s: string): string => s.replace(LONE, '�');
const isObj = (v: unknown): v is Rec => v !== null && typeof v === 'object' && !Array.isArray(v);
const cut = (s: string, n: number): string => Array.from(s).slice(0, n).join('');
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').map(clean) : []);

function int(v: unknown): number | null {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= Number.MAX_SAFE_INTEGER ? v : null;
}

/** `toISOString()`: the reference's `_iso`. */
export const iso = (ms: number): string => new Date(ms).toISOString();

function msOf(now: string): number {
  try {
    return parseNow(now);
  } catch {
    throw new InstallError(`not a timestamp: ${pyRepr(String(now))}`);
  }
}

// ------------------------------------------------------------------------------- evidence

export function evidenceIds(cluster: Rec): string[] {
  const out: string[] = [];
  for (const e of Array.isArray(cluster['evidence']) ? cluster['evidence'] : []) {
    if (isObj(e) && typeof e['id'] === 'string' && e['id']) {
      const i = clean(e['id']);
      if (!out.includes(i)) out.push(i);
    }
  }
  return out;
}

const quote = (text: string): string[] => text.split('\n').map((line) => (line ? `  > ${line}` : '  >'));

function failureNote(failure: string, n: number): string {
  if (failure.startsWith(CORRECTED)) return CORRECTED + cut(failure.slice(CORRECTED.length), n);
  return cut(failure, n);
}

export function evidenceMarkdown(cluster: Rec, name: string, level: string): string {
  const n = level === LEVEL_PROJECT ? EVIDENCE_PROJECT_CHARS : EVIDENCE_USER_CHARS;
  const cid = typeof cluster['id'] === 'string' ? clean(cluster['id']) : '';
  const source = typeof cluster['source'] === 'string' ? clean(cluster['source']) : '';
  const successes = int(cluster['successes']);
  const members = int(cluster['members']);
  const lines = [
    `# Evidence: ${clean(name)}`,
    '',
    `Cluster \`${cid}\` (${source}): ${successes ?? 0} successful of ${members ?? 0} pieces of work, ${level} level.`,
    `Every step in SKILL.md cites one of the ids below. Prompts are cut to ${n} characters.`,
  ];
  for (const e of Array.isArray(cluster['evidence']) ? cluster['evidence'] : []) {
    if (!isObj(e) || typeof e['id'] !== 'string' || !e['id']) continue;
    const ok = e['ok'];
    const result = ok === true ? 'success' : ok === false ? 'failure' : 'not known';
    const signals = isObj(e['signals']) ? e['signals'] : {};
    const on = Object.keys(signals)
      .sort(cmpCodepoint)
      .filter((k) => signals[k] === true)
      .map(clean);
    const tools = strs(e['tools']);
    const paths = strs(e['paths']);
    const commits = strs(e['commits']);
    const ts = typeof e['ts'] === 'string' ? clean(e['ts']) : '';
    lines.push(
      '',
      `## ${clean(e['id'])}`,
      '',
      `- Result: ${result}`,
      `- Time: ${ts || 'not known'}`,
      `- Signals: ${on.length > 0 ? on.join(', ') : 'none'}`,
      `- Tools: ${tools.length > 0 ? tools.join(', ') : 'none'}`,
      `- Paths: ${paths.length > 0 ? paths.map((p) => `\`${p}\``).join(', ') : 'none'}`,
    );
    if (commits.length > 0) {
      lines.push('- Commits:');
      for (const c of commits) lines.push(`  - ${c}`);
    }
    if (typeof e['failure'] === 'string' && e['failure']) lines.push(`- Failure: ${failureNote(clean(e['failure']), n)}`);
    const prompt = typeof e['prompt'] === 'string' ? cut(clean(e['prompt']), n) : '';
    if (prompt) lines.push('- Prompt:', '', ...quote(prompt));
  }
  return `${lines.join('\n')}\n`;
}

// -------------------------------------------------------------------------------- install

export function installRoot(cluster: Rec, levelOverride: string | null, home: string): [string, string] {
  if (levelOverride !== null && levelOverride !== LEVEL_PROJECT && levelOverride !== LEVEL_USER) {
    throw new InstallError('level must be project or user');
  }
  const level = levelOverride || (cluster['level'] === LEVEL_PROJECT ? LEVEL_PROJECT : LEVEL_USER);
  if (level === LEVEL_USER) return [level, skillsRoot(home)];
  const top = cluster['top'];
  if (typeof top !== 'string' || !top) {
    const cid = typeof cluster['id'] === 'string' ? cluster['id'] : '';
    throw new InstallError(`cluster ${cid} names no project to install into`);
  }
  return [level, projectSkillsRoot(top)];
}

export function skillText(cluster: Rec, text: string): string {
  const keywords = strs(cluster['keywords']).slice(0, KEYWORDS_MAX);
  return stamp(clean(text), {
    'bantamkit-cluster': clean(cluster['id'] as string),
    'bantamkit-evidence': evidenceIds(cluster).join(','),
    'bantamkit-generated-by': GENERATED_BY,
    'bantamkit-keywords': keywords.join(','),
    'bantamkit-version': '1',
  });
}

let counter = 0;

/** Out of the way in one rename (a name the `[skill]` layer passes over), then deleted. */
export function removeDir(target: string): void {
  counter += 1;
  const aside = `${target}.old-${process.pid}-${counter}`;
  fs.renameSync(target, aside);
  rmTree(aside);
}

function rmTree(p: string): void {
  try {
    fs.rmSync(p, { recursive: true, force: true });
  } catch {
    /* best effort, as the reference's ignore_errors */
  }
}

/** The backup an install took, and its name's directory when that leaves it empty. */
function dropBackup(backup: string): void {
  rmTree(backup);
  try {
    fs.rmdirSync(path.dirname(backup));
  } catch {
    /* not empty, or gone */
  }
}

const lexists = (p: string): boolean => {
  try {
    fs.lstatSync(p);
    return true;
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

export function install(
  cluster: Rec,
  text: string,
  levelOverride: string | null,
  home: string,
  now: string,
  auto: boolean,
): Installed {
  const cid = cluster['id'];
  if (typeof cid !== 'string' || !cid) throw new InstallError('the cluster has no id');
  const nowMs = msOf(now);
  const [level, root] = installRoot(cluster, levelOverride, home);
  let doc;
  try {
    doc = parseSkill(clean(text));
  } catch (e) {
    if (e instanceof SkillFileError) throw new InstallError(e.message);
    throw e;
  }
  const reasons = validate(doc);
  if (reasons.length > 0) throw new InstallError(reasons[0]!);
  const name = doc.name;
  if (Object.hasOwn(readState(home).skills, name)) throw new InstallError(`a skill named ${pyRepr(name)} is already installed`);
  const target = path.join(root, name);
  if (lexists(target)) throw new InstallError(`a skill already exists at ${target}`);
  let skill: string;
  try {
    skill = skillText(cluster, text);
  } catch (e) {
    if (e instanceof SkillFileError) throw new InstallError(e.message);
    throw e;
  }
  const files: Record<string, Uint8Array> = {
    [SKILL_FILE]: Buffer.from(skill, 'utf8'),
    [EVIDENCE_FILE]: Buffer.from(evidenceMarkdown(cluster, name, level), 'utf8'),
  };
  const entry: Rec = {
    at: now,
    auto,
    cluster: clean(cid),
    level,
    name,
    path: target,
    sha256: canonicalHash(skill),
    version: 1,
    versions: { '1': { false_fires: 0, injects: 0, successes: 0, uses: 0 } },
  };
  if (auto) entry['probation_until'] = iso(nowMs + PROBATION_DAYS * DAY_MS);
  const backup = backupAbsent(backupRoot(home), name, now);
  try {
    writeDirAtomic(target, files);
  } catch (e) {
    dropBackup(backup);
    throw e;
  }
  try {
    updateState(home, (state) => {
      if (Object.hasOwn(state.skills, name)) throw new InstallError(`a skill named ${pyRepr(name)} is already installed`);
      state.skills[name] = entry;
      if (auto) {
        const dates = (Array.isArray(state['auto_dates']) ? state['auto_dates'] : []).filter((d) => typeof d === 'string');
        state['auto_dates'] = [...dates, iso(nowMs).slice(0, 10)].slice(-AUTO_DATES_KEEP);
      }
    });
  } catch (e) {
    removeDir(target);
    dropBackup(backup);
    throw e;
  }
  cluster['status'] = 'installed';
  return { name, level, path: target, event: `installed skill ${name}`, entry };
}

// ------------------------------------------------------------------------------ auto step

export function draftEntry(drafter: string | null, text: string | null, now: string): Rec | null {
  if (typeof text !== 'string') return null;
  return { drafter, ok: true, text, ts: now };
}

export function draftText(rec: Rec): string | null {
  const d = rec['draft'];
  return isObj(d) && d['ok'] === true && typeof d['text'] === 'string' ? d['text'] : null;
}

function autoReady(rec: unknown): rec is Rec {
  if (!isObj(rec) || rec['auto_eligible'] !== true) return false;
  const successes = int(rec['successes']);
  const autoBar = int(rec['auto_bar']);
  return (
    successes !== null &&
    autoBar !== null &&
    successes >= autoBar &&
    typeof rec['status'] === 'string' &&
    AUTO_FROM.includes(rec['status']) &&
    typeof rec['id'] === 'string' &&
    draftText(rec) !== null
  );
}

export function firstTs(rec: Rec): string {
  const ts = (Array.isArray(rec['evidence']) ? rec['evidence'] : [])
    .filter((e): e is Rec => isObj(e) && typeof e['ts'] === 'string')
    .map((e) => e['ts'] as string);
  return ts.length === 0 ? '' : ts.reduce((a, b) => (cmpCodepoint(b, a) < 0 ? b : a));
}

export function liveAuto(state: Rec): string[] {
  const skills = isObj(state['skills']) ? state['skills'] : {};
  return Object.keys(skills)
    .filter((n) => isObj(skills[n]) && (skills[n] as Rec)['auto'] === true)
    .sort(cmpCodepoint);
}

function replaceState(state: Rec, fresh: Rec): void {
  for (const k of Object.keys(state)) delete state[k];
  Object.assign(state, fresh);
}

export function autoStep(proposals: Rec, state: Rec, home: string, now: string): string[] {
  if (!autoEnabled()) return [];
  const today = iso(msOf(now)).slice(0, 10);
  const dates = Array.isArray(state['auto_dates']) ? state['auto_dates'] : [];
  if (dates.filter((d) => d === today).length >= AUTO_PER_DAY) return [];
  if (liveAuto(state).length >= AUTO_LIVE_MAX) return [];
  const clusters = Array.isArray(proposals['clusters']) ? proposals['clusters'] : [];
  const ready = clusters.filter(autoReady);
  ready.sort(
    (a, b) =>
      (b['successes'] as number) - (a['successes'] as number) ||
      cmpCodepoint(firstTs(a), firstTs(b)) ||
      cmpCodepoint(a['id'] as string, b['id'] as string),
  );
  for (const rec of ready) {
    let got: Installed;
    try {
      got = install(rec, draftText(rec)!, null, home, now, true);
    } catch (e) {
      if (e instanceof InstallError) {
        rec['status'] = 'failed';
        continue;
      }
      throw e;
    }
    replaceState(state, readState(home));
    return [got.event];
  }
  return [];
}

// ------------------------------------------------------------------------------ probation

export function probationStep(state: Rec, uses: Record<string, unknown>, home: string, now: string): string[] {
  const nowMs = msOf(now);
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const used: string[] = [];
  const removed: string[] = [];
  const proposed: string[] = [];
  const gone: string[] = [];
  const events: string[] = [];
  for (const name of Object.keys(skills).sort(cmpCodepoint)) {
    const e = skills[name];
    if (!isObj(e) || e['auto'] !== true) continue;
    const until = e['probation_until'];
    if (typeof until !== 'string') continue;
    if ((int(Object.hasOwn(uses, name) ? uses[name] : undefined) ?? 0) > 0) {
      used.push(name);
      continue;
    }
    let untilMs: number;
    try {
      untilMs = parseNow(until);
    } catch {
      continue;
    }
    if (untilMs > nowMs) continue;
    const target = typeof e['path'] === 'string' ? e['path'] : null;
    if (target === null || !isFile(path.join(target, SKILL_FILE))) {
      gone.push(name);
      continue;
    }
    const raw = fs.readFileSync(path.join(target, SKILL_FILE));
    let edited: boolean;
    try {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
      edited = e['edited'] === true || isEdited(text) || canonicalHash(text) !== e['sha256'];
    } catch (err) {
      if (!(err instanceof TypeError)) throw err;
      edited = true;
    }
    if (edited) {
      proposed.push(name);
      events.push(`proposed removing edited skill ${name}`);
      continue;
    }
    backupDir(backupRoot(home), target, now);
    removeDir(target);
    removed.push(name);
    events.push(`removed unused skill ${name}`);
  }
  if (used.length + removed.length + proposed.length + gone.length === 0) return events;
  const written = updateState(home, (fresh) => {
    const live = fresh.skills as Record<string, unknown>;
    for (const name of used) if (isObj(live[name])) delete (live[name] as Rec)['probation_until'];
    for (const name of proposed) {
      if (isObj(live[name])) {
        delete (live[name] as Rec)['probation_until'];
        (live[name] as Rec)['proposal'] = { at: now, kind: 'remove', status: 'pending' };
      }
    }
    for (const name of removed) {
      if (Object.hasOwn(live, name)) {
        const entry = live[name];
        delete live[name];
        if (!isObj(fresh['removed'])) fresh['removed'] = {};
        (fresh['removed'] as Rec)[name] = entry;
      }
    }
    for (const name of gone) delete live[name];
  });
  replaceState(state, written);
  return events;
}

// ----------------------------------------------------------------------------------- undo

export function undo(name: string, home: string): string {
  const state = readState(home);
  const live = Object.hasOwn(state.skills, name) ? state.skills[name] : undefined;
  const removedMap = isObj(state['removed']) ? state['removed'] : {};
  const gone = Object.hasOwn(removedMap, name) ? removedMap[name] : undefined;
  const src = isObj(live) ? live : isObj(gone) ? gone : null;
  if (src === null || typeof src['path'] !== 'string') throw new InstallError(`no skill named ${pyRepr(name)} is installed`);
  const target = src['path'];
  const said = undoDir(backupRoot(home), name, target);
  let restored: string | null = null;
  if (isFile(path.join(target, SKILL_FILE))) {
    try {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(path.join(target, SKILL_FILE)));
      const stored = parseSkill(text).metadata[HASH_KEY];
      restored = typeof stored === 'string' ? stored : null;
    } catch (e) {
      if (!(e instanceof SkillFileError) && !(e instanceof TypeError)) throw e;
      restored = null;
    }
  }
  updateState(home, (fresh: SkillsState) => {
    const removed = isObj(fresh['removed']) ? (fresh['removed'] as Rec) : {};
    const skills = fresh.skills as Record<string, unknown>;
    if (!lexists(target)) {
      delete skills[name];
      delete removed[name];
    } else {
      let entry = Object.hasOwn(skills, name) ? skills[name] : undefined;
      if (!isObj(entry)) {
        entry = Object.hasOwn(removed, name) ? removed[name] : undefined;
        delete removed[name];
        if (!isObj(entry)) {
          if (Object.hasOwn(fresh, 'removed')) fresh['removed'] = removed;
          return;
        }
        delete entry['probation_until'];
        delete entry['proposal'];
        skills[name] = entry;
      }
      if (restored !== null) (entry as Rec)['sha256'] = restored;
    }
    if (Object.hasOwn(fresh, 'removed')) fresh['removed'] = removed;
  });
  return said;
}

// ------------------------------------------------------------- self-improvement (Task 10a)
// The reference's comment block states the design: versions, counting, the judge, the
// edited guard.

export const JUDGE_USES = 5;
export const VERDICT_KEPT = 'kept';
export const VERDICT_ROLLED_BACK = 'rolled back';
export const HISTORY_DIR = 'references/history';
export const VERSION_KINDS: readonly string[] = ['auto', 'approved'];
const COUNTERS = ['false_fires', 'injects', 'successes', 'uses'] as const;
const TURN_ID = /^s([\s\S]{1,8})#([0-9]{1,15})$/u;
const VERSION_KEY = /^[0-9]{1,15}$/;
const UTF8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

function dirFiles(root: string): Record<string, Uint8Array> {
  const out: Record<string, Uint8Array> = {};
  const walk = (d: string, rel: string): void => {
    for (const entry of fs.readdirSync(d).sort(cmpCodepoint)) {
      const p = path.join(d, entry);
      const st = fs.lstatSync(p);
      if (st.isSymbolicLink()) continue;
      if (st.isDirectory()) walk(p, `${rel}${entry}/`);
      else if (st.isFile()) out[`${rel}${entry}`] = fs.readFileSync(p);
    }
  };
  walk(root, '');
  return out;
}

function liveText(entry: Rec): [string, Buffer] | null {
  if (typeof entry['path'] !== 'string') return null;
  const target = entry['path'];
  try {
    return [target, fs.readFileSync(path.join(target, SKILL_FILE))];
  } catch {
    return null;
  }
}

function editedBytes(raw: Uint8Array, entry: Rec): boolean {
  let text: string;
  try {
    text = UTF8.decode(raw);
  } catch {
    return true;
  }
  return isEdited(text) || canonicalHash(text) !== entry['sha256'];
}

/** Edited by hand now (R8), or ever (`edited`: X10's "never changed automatically again"). */
function editedNow(raw: Uint8Array, entry: Rec): boolean {
  return entry['edited'] === true || editedBytes(raw, entry);
}

/** True when the skill's SKILL.md no longer matches its hash (R8), or once was; null without one. */
export function editedByHand(entry: Rec): boolean | null {
  const live = liveText(entry);
  return live === null ? null : editedNow(live[1], entry);
}

function tsOf(v: unknown): number | null {
  try {
    return parseNow(v);
  } catch {
    return null;
  }
}

function rows(sources: Rec, key: string): Rec[] {
  const v = isObj(sources) ? sources[key] : undefined;
  return Array.isArray(v) ? v.filter(isObj) : [];
}

type Turn = [number, number, boolean];

const first8 = (s: string): string => Array.from(s).slice(0, 8).join('');

function turnsOf(sources: Rec): Map<string, Turn[]> {
  const out = new Map<string, Turn[]>();
  for (const t of rows(sources, 'turns')) {
    const m = typeof t['id'] === 'string' ? TURN_ID.exec(t['id']) : null;
    const at = tsOf(t['ts']);
    if (m === null || at === null) continue;
    const list = out.get(m[1]!) ?? [];
    list.push([at, Number(m[2]), t['ok'] === true]);
    out.set(m[1]!, list);
  }
  for (const v of out.values()) v.sort((a, b) => a[0] - b[0] || a[1] - b[1] || Number(a[2]) - Number(b[2]));
  return out;
}

function turnOk(turns: Map<string, Turn[]>, session: string, at: number): boolean {
  let best: Turn | null = null;
  for (const t of turns.get(first8(session)) ?? []) if (t[0] <= at) best = t;
  return best !== null && best[2];
}

/** The reference's `stats_step`: count the new rows of `sources` into each live version. */
export function statsStep(state: Rec, sources: Rec, home: string, now: string): void {
  const nowMs = msOf(now);
  const uses: Array<[string, string, number]> = [];
  for (const u of rows(sources, 'uses')) {
    const at = tsOf(u['ts']);
    if (typeof u['fact'] === 'string' && typeof u['session'] === 'string' && u['session'] && at !== null) {
      uses.push([u['fact'], u['session'], at]);
    }
  }
  const injects: Array<[Set<string>, string, number]> = [];
  for (const i of rows(sources, 'injects')) {
    const at = tsOf(i['ts']);
    if (Array.isArray(i['names']) && typeof i['session'] === 'string' && i['session'] && at !== null) {
      injects.push([new Set(i['names'].filter((n): n is string => typeof n === 'string')), i['session'], at]);
    }
  }
  const turns = turnsOf(sources);
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const counts = new Map<string, [number, Record<string, number>]>();
  for (const name of Object.keys(skills).sort(cmpCodepoint)) {
    const e = skills[name];
    const n = isObj(e) ? int(e['version']) : null;
    if (n === null || n < 1 || !isObj(e)) continue;
    const versions = isObj(e['versions']) ? e['versions'] : {};
    const v = Object.hasOwn(versions, String(n)) && isObj(versions[String(n)]) ? (versions[String(n)] as Rec) : {};
    const mark = tsOf(e['counted_to']);
    const start = typeof v['at'] === 'string' ? tsOf(v['at']) : tsOf(e['at']);
    if (mark === null && start === null) continue;
    const inside = (at: number): boolean => at <= nowMs && (mark !== null ? at > mark : at >= start!);
    const mine = uses.filter(([f, , at]) => f === name && inside(at));
    const usedIn = new Set(uses.filter(([f]) => f === name).map(([, s]) => s));
    const fired = injects.filter(([names, , at]) => names.has(name) && inside(at)).map(([, s]) => s);
    counts.set(name, [
      n,
      {
        false_fires: fired.filter((s) => !usedIn.has(s)).length,
        injects: fired.length,
        successes: mine.filter(([, s, at]) => turnOk(turns, s, at)).length,
        uses: mine.length,
      },
    ]);
  }
  if (counts.size === 0) return;
  const written = updateState(home, (fresh) => {
    const live = fresh.skills as Record<string, unknown>;
    for (const [name, [n, add]] of counts) {
      const e = Object.hasOwn(live, name) ? live[name] : undefined;
      if (!isObj(e) || int(e['version']) !== n) continue;
      if (!isObj(e['versions'])) e['versions'] = {};
      const versions = e['versions'] as Rec;
      let v = Object.hasOwn(versions, String(n)) ? versions[String(n)] : undefined;
      if (!isObj(v)) {
        v = {};
        versions[String(n)] = v;
      }
      for (const k of COUNTERS) (v as Rec)[k] = (int((v as Rec)[k]) ?? 0) + add[k]!;
      e['counted_to'] = now;
    }
  });
  replaceState(state, written);
}

function carried(oldText: string, docMetadata: Record<string, unknown>): Record<string, string> {
  let old: Record<string, unknown>;
  try {
    old = parseSkill(oldText).metadata;
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
    old = {};
  }
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(old)) if (k.startsWith('bantamkit-') && k !== HASH_KEY && typeof v === 'string') out[k] = v;
  for (const k of ['bantamkit-evidence', 'bantamkit-keywords']) {
    const v = Object.hasOwn(docMetadata, k) ? docMetadata[k] : undefined;
    if (typeof v === 'string') out[k] = v;
  }
  return out;
}

/** The reference's `new_version`: the live skill replaced by `text` as its next version. */
export function newVersion(name: string, text: string, home: string, now: string, kind: string, base: string | null = null): string {
  if (!VERSION_KINDS.includes(kind)) throw new InstallError('kind must be auto or approved');
  msOf(now);
  const skills = readState(home).skills;
  const entry = Object.hasOwn(skills, name) ? skills[name] : undefined;
  if (!isObj(entry)) throw new InstallError(`no skill named ${pyRepr(name)} is installed`);
  const live = liveText(entry);
  if (live === null) throw new InstallError(`skill ${name} has no SKILL.md at ${pyStr(entry['path'])}`);
  const [target, raw] = live;
  if (base !== null && createHash('sha256').update(raw).digest('hex') !== base) {
    throw new InstallError(`${name} changed after this change was proposed; reject it and wait for a new one`);
  }
  const wasEdited = editedNow(raw, entry);
  if (wasEdited && !(kind === 'approved' && base !== null)) {
    throw new InstallError(`${name} was edited by hand; it only receives proposed changes`);
  }
  let doc;
  try {
    doc = parseSkill(clean(text));
  } catch (e) {
    if (e instanceof SkillFileError) throw new InstallError(e.message);
    throw e;
  }
  const reasons = validate(doc);
  if (reasons.length > 0) throw new InstallError(reasons[0]!);
  if (doc.name !== name) throw new InstallError(`the new version is named ${pyRepr(doc.name)}, not ${pyRepr(name)}`);
  const n = int(entry['version']) || 1;
  const versions = isObj(entry['versions']) ? entry['versions'] : {};
  const known = Object.keys(versions).filter((k) => VERSION_KEY.test(k)).map(Number);
  const m = Math.max(n, ...known) + 1;
  const updates = carried(UTF8.decode(raw), doc.metadata);
  updates['bantamkit-version'] = String(m);
  let newText: string;
  try {
    newText = stamp(clean(text), updates);
  } catch (e) {
    if (e instanceof SkillFileError) throw new InstallError(e.message);
    throw e;
  }
  const files = dirFiles(target);
  const hist = `${HISTORY_DIR}/v${n}.md`;
  if (Object.hasOwn(files, hist) && !Buffer.from(files[hist]!).equals(raw)) {
    throw new InstallError(`history already holds v${n} of ${name}`);
  }
  files[hist] = raw;
  files[SKILL_FILE] = Buffer.from(newText, 'utf8');
  replaceDirAtomic(target, files, backupRoot(home), now);
  try {
    updateState(home, (fresh) => {
      const live2 = fresh.skills as Record<string, unknown>;
      const e = Object.hasOwn(live2, name) ? live2[name] : undefined;
      if (!isObj(e)) throw new InstallError(`no skill named ${pyRepr(name)} is installed`);
      if (!isObj(e['versions'])) e['versions'] = {};
      (e['versions'] as Rec)[String(m)] = { at: now, false_fires: 0, from: n, injects: 0, kind, successes: 0, uses: 0 };
      e['version'] = m;
      e['sha256'] = canonicalHash(newText);
      e['counted_to'] = now;
      if (wasEdited) e['edited'] = true;
    });
  } catch (e) {
    undoDir(backupRoot(home), name, target);
    throw e;
  }
  return `updated skill ${name} to v${m}`;
}

/** Python's `str()` of a JSON value, for the one sentence that prints a path that may be absent. */
function pyStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v === undefined || v === null) return 'None';
  if (v === true) return 'True';
  if (v === false) return 'False';
  return String(v);
}

function fell(sN: number, uN: number, sF: number, uF: number): boolean {
  if (uN === 0 || uF === 0) return false;
  return sN * uF < sF * uN;
}

function rose(fN: number, iN: number, fF: number, iF: number): boolean {
  if (iN === 0) return false;
  if (iF === 0) return fN > 0;
  return fN * iF > fF * iN;
}

const tally = (v: Rec, k: string): number => int(v[k]) ?? 0;

/** The reference's `judge_step`: judge every live version with `JUDGE_USES` uses; the events. */
export function judgeStep(state: Rec, home: string, now: string): string[] {
  msOf(now);
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const verdicts = new Map<string, [number, string, number, string | null]>();
  const events: string[] = [];
  for (const name of Object.keys(skills).sort(cmpCodepoint)) {
    const e = skills[name];
    if (!isObj(e)) continue;
    const n = int(e['version']);
    const versions = isObj(e['versions']) ? e['versions'] : {};
    const v = n !== null && Object.hasOwn(versions, String(n)) ? versions[String(n)] : undefined;
    if (n === null || n < 2 || !isObj(v) || Object.hasOwn(v, 'verdict')) continue;
    const f = int(v['from']) ?? n - 1;
    const base = Object.hasOwn(versions, String(f)) ? versions[String(f)] : undefined;
    if (!isObj(base) || tally(v, 'uses') < JUDGE_USES) continue;
    const live = liveText(e);
    if (live === null || editedNow(live[1], e)) continue;
    const worse =
      fell(tally(v, 'successes'), tally(v, 'uses'), tally(base, 'successes'), tally(base, 'uses')) ||
      rose(tally(v, 'false_fires'), tally(v, 'injects'), tally(base, 'false_fires'), tally(base, 'injects'));
    if (!worse) {
      verdicts.set(name, [n, VERDICT_KEPT, n, null]);
      continue;
    }
    const [target, raw] = live;
    let restored: string;
    try {
      const old = UTF8.decode(fs.readFileSync(path.join(target, ...HISTORY_DIR.split('/'), `v${f}.md`)));
      restored = stamp(old, {});
      const files = dirFiles(target);
      files[`${HISTORY_DIR}/v${n}.md`] = raw;
      files[SKILL_FILE] = Buffer.from(restored, 'utf8');
      replaceDirAtomic(target, files, backupRoot(home), now);
    } catch (err) {
      if (err instanceof SkillFileError || err instanceof TypeError || (err instanceof Error && typeof (err as NodeJS.ErrnoException).code === 'string')) continue;
      throw err;
    }
    verdicts.set(name, [n, VERDICT_ROLLED_BACK, f, canonicalHash(restored)]);
    events.push(`rolled back ${name} to v${f}`);
  }
  if (verdicts.size === 0) return events;
  const written = updateState(home, (fresh) => {
    const live = fresh.skills as Record<string, unknown>;
    for (const [name, [n, verdict, f, sha]] of verdicts) {
      const e = Object.hasOwn(live, name) ? live[name] : undefined;
      if (!isObj(e) || int(e['version']) !== n) continue;
      const versions = isObj(e['versions']) ? e['versions'] : null;
      const v = versions !== null && Object.hasOwn(versions, String(n)) ? versions[String(n)] : undefined;
      if (!isObj(v)) continue;
      v['verdict'] = verdict;
      if (verdict === VERDICT_ROLLED_BACK) {
        e['version'] = f;
        e['sha256'] = sha;
        e['rolled_back'] = n;
        e['counted_to'] = now;
      }
    }
  });
  replaceState(state, written);
  return events;
}

// ------------------------------------------------------------- self-improvement (Task 10b)
//
// The reference's design note (`skillinstall.py`, Task 10b) is the description: the signals,
// the split by risk, one `auto` version per skill per run, the needs-user proposals and the
// edited guard.

export const TUNE_MIN_INJECTS = 5;
export const FALSE_FIRE_TUNE: readonly [number, number] = [1, 2];
export const MISS_TUNE = 2;
export const PITFALL_CHARS = 200;
export const TOGETHER_SESSIONS = 5;
export const TOGETHER_SHARE: readonly [number, number] = [1, 2];
export const ITEM_KINDS: readonly string[] = ['improve', 'merge', 'remove', 'steps'];
export const PITFALLS = '## Pitfalls';
export const STEPS = '## Steps';
const HEADING = /^#{1,2}(?:[ \t]|$)/;
const NUMBERED = /^[ \t]{0,3}[0-9]{1,9}[.)](?:[ \t]|$)/;
const EDGE = /^[ \t]+|[ \t]+$/g;
const stripSpaceTab = (s: string): string => s.replace(/^[ \t]+|[ \t]+$/g, '');

/** `- [<id>] <note>`: the correcting prompt's first line (or the failure's), cut. */
export function pitfallLine(evidenceId: string, failure: string): string {
  const note0 = failure.startsWith(CORRECTED) ? failure.slice(CORRECTED.length) : failure;
  const note = clean(note0).split('\n')[0]!.replace(EDGE, '');
  return `- [${clean(evidenceId)}] ${cut(note, PITFALL_CHARS)}`;
}

/** The reference's `append_to_section`. */
export function appendToSection(body: string, heading: string, lines: readonly string[]): string {
  const ls = body.split('\n');
  const idx = ls.findIndex((line) => line.replace(/[ \t]+$/, '') === heading);
  if (idx < 0) return (body ? body.replace(/\n+$/, '') + '\n\n' : '') + heading + '\n\n' + lines.join('\n');
  let end = idx + 1;
  while (end < ls.length && !HEADING.test(ls[end]!)) end += 1;
  const content: number[] = [];
  for (let k = idx + 1; k < end; k++) if (stripSpaceTab(ls[k]!)) content.push(k);
  if (content.length === 1 && stripSpaceTab(ls[content[0]!]!) === 'None.') {
    ls.splice(content[0]!, 1, ...lines);
    return ls.join('\n');
  }
  const at = content.length > 0 ? content[content.length - 1]! + 1 : idx + 1;
  const ins = content.length > 0 ? [...lines] : ['', ...lines];
  if (at < ls.length && stripSpaceTab(ls[at]!)) ins.push('');
  ls.splice(at, 0, ...ins);
  return ls.join('\n');
}

export function nextStepNumber(body: string): number {
  const ls = body.split('\n');
  const idx = ls.findIndex((line) => line.replace(/[ \t]+$/, '') === STEPS);
  if (idx < 0) return 1;
  let n = 0;
  for (const line of ls.slice(idx + 1)) {
    if (HEADING.test(line)) break;
    if (NUMBERED.test(line)) n += 1;
  }
  return n + 1;
}

function plainLines(text: string): string[] {
  let t = text;
  try {
    const doc = parseSkill(text);
    t = renderSkill({ name: doc.name, description: doc.description, metadata: {}, body: doc.body });
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
  }
  const ls = t.split('\n');
  if (ls.length > 0 && ls[ls.length - 1] === '') ls.pop();
  return ls;
}

/** The reference's `skill_diff`: one unified hunk with 3 lines of context. */
export function skillDiff(oldText: string, newText: string): string {
  const a = plainLines(oldText);
  const b = plainLines(newText);
  if (a.length === b.length && a.every((x, i) => x === b[i])) return '';
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p += 1;
  let s = 0;
  while (s < a.length - p && s < b.length - p && a[a.length - 1 - s] === b[b.length - 1 - s]) s += 1;
  const lo = Math.max(0, p - 3);
  const hiA = Math.min(a.length, a.length - s + 3);
  const hiB = b.length - s + (hiA - (a.length - s));
  return [
    '--- a/SKILL.md',
    '+++ b/SKILL.md',
    `@@ -${lo + 1},${hiA - lo} +${lo + 1},${hiB - lo} @@`,
    ...a.slice(lo, p).map((x) => ' ' + x),
    ...a.slice(p, a.length - s).map((x) => '-' + x),
    ...b.slice(p, b.length - s).map((x) => '+' + x),
    ...a.slice(a.length - s, hiA).map((x) => ' ' + x),
  ].join('\n');
}

export const csv = (v: unknown): string[] => (typeof v === 'string' ? v.split(',').filter((x) => x) : []);

function withMeta(text: string, body: string | null, metadata: Record<string, string>): string {
  const doc = parseSkill(text);
  return renderSkill({ name: doc.name, description: doc.description, metadata: { ...doc.metadata, ...metadata }, body: body ?? doc.body });
}

/** The reference's `_with_step`: `step` as the next numbered `## Steps` line, `tid` in the evidence. */
function withStep(text: string, tid: string, step: string): string {
  const doc = parseSkill(text);
  const line = `${nextStepNumber(doc.body)}. ${step}`;
  const ids = csv(doc.metadata['bantamkit-evidence']);
  if (!ids.includes(tid)) ids.push(tid);
  return withMeta(text, appendToSection(doc.body, STEPS, [line]), { 'bantamkit-evidence': ids.join(',') });
}

function proposalOf(kind: string, raw: Uint8Array, old: string, text: string, now: string): Rec {
  return {
    at: now,
    base: createHash('sha256').update(raw).digest('hex'),
    diff: skillDiff(old, text),
    kind,
    status: 'pending',
    text,
  };
}

function slotFree(e: Rec): boolean {
  const p = e['proposal'];
  return !(isObj(p) && p['status'] === 'pending');
}

type STurn = [number, number, unknown, string, unknown, string[]];

function sessionTurns(sources: Rec): Map<string, STurn[]> {
  const out = new Map<string, STurn[]>();
  for (const t of rows(sources, 'turns')) {
    const m = typeof t['id'] === 'string' ? TURN_ID.exec(t['id']) : null;
    const at = tsOf(t['ts']);
    if (m === null || at === null) continue;
    const list = out.get(m[1]!) ?? [];
    list.push([at, Number(m[2]), t['ok'], t['id'] as string, t['failure'], strs(t['tools'])]);
    out.set(m[1]!, list);
  }
  for (const v of out.values()) v.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  return out;
}

export { liveText as _liveText, tally as _tally };

/** The reference's `apply_text`: gated, then the next `auto` version, or an `improve`
 * proposal on a skill edited by hand or with `auto` false (automatic edits off).
 * `[event, reasons]`; a gate failure is logged. */
export function applyText(name: string, text: string, home: string, cwd: string | null, now: string, b: Bundle, auto = true): [string | null, string[]] {
  const skills = readState(home).skills;
  const entry = Object.hasOwn(skills, name) ? skills[name] : undefined;
  const live = isObj(entry) ? liveText(entry) : null;
  if (live === null || !isObj(entry)) return [null, [`no skill named ${pyRepr(name)} is installed`]];
  const [target, raw] = live;
  const g = gate(text, b, home, cwd, target);
  if (!g.ok) {
    const o = { drafter: null, ok: false, text: null, reasons: g.reasons, unreachable: [], handoff: null };
    new LogSegment(draftsLog(home)).append(logLine(o, now, b.cluster));
    return [null, g.reasons];
  }
  if (!auto || editedNow(raw, entry)) {
    if (!slotFree(entry)) return [null, [`a change to ${name} already waits on you`]];
    const prop = proposalOf('improve', raw, raw.toString('utf8'), text, now);
    updateState(home, (fresh) => {
      const live2 = fresh.skills as Record<string, unknown>;
      const e = Object.hasOwn(live2, name) ? live2[name] : undefined;
      if (isObj(e) && slotFree(e)) e['proposal'] = prop;
    });
    return [`proposed a change to ${name}`, []];
  }
  let said: string;
  try {
    said = newVersion(name, text, home, now, 'auto');
  } catch (e) {
    if (e instanceof InstallError) return [null, [e.message]];
    throw e;
  }
  return ['improved skill ' + said.slice('updated skill '.length), []];
}

type Mark = [number, number, string[], Rec | null, Rec | null];

/** The reference's `improve_step`: the X10 signals for every live skill; the events. */
export async function improveStep(
  state: Rec,
  sources: Rec,
  doc: Rec | null,
  home: string,
  cwd: string | null,
  now: string,
  chain: readonly ChainLink[],
): Promise<string[]> {
  const nowMs = msOf(now);
  const auto = autoEnabled();
  const skills = isObj(state['skills']) ? state['skills'] : {};
  const records = new Map<string, Rec>();
  const clusters = isObj(doc) ? doc['clusters'] : undefined;
  for (const r of Array.isArray(clusters) ? clusters : []) {
    if (isObj(r) && typeof r['id'] === 'string' && !records.has(r['id'])) records.set(r['id'], r);
  }
  const uses: Array<[string, string, number]> = [];
  for (const u of rows(sources, 'uses')) {
    const at = tsOf(u['ts']);
    if (typeof u['fact'] === 'string' && typeof u['session'] === 'string' && u['session'] && at !== null && at <= nowMs) {
      uses.push([u['fact'], u['session'], at]);
    }
  }
  const injects: Array<[Set<string>, string, number]> = [];
  for (const i of rows(sources, 'injects')) {
    const at = tsOf(i['ts']);
    if (Array.isArray(i['names']) && typeof i['session'] === 'string' && i['session'] && at !== null && at <= nowMs) {
      injects.push([new Set(i['names'].filter((n): n is string => typeof n === 'string')), i['session'], at]);
    }
  }
  const turns = sessionTurns(sources);
  const events: string[] = [];
  const marks = new Map<string, Mark>();
  for (const name of Object.keys(skills).sort(cmpCodepoint)) {
    const e = skills[name];
    if (!isObj(e)) continue;
    const n = int(e['version']);
    const live = n !== null && n >= 1 ? liveText(e) : null;
    if (live === null || n === null) continue;
    const [target, raw] = live;
    let text: string;
    let sdoc;
    try {
      text = UTF8.decode(raw);
      sdoc = parseSkill(text);
    } catch (err) {
      if (err instanceof TypeError || err instanceof SkillFileError) continue;
      throw err;
    }
    const versions = isObj(e['versions']) ? e['versions'] : {};
    const vv = Object.hasOwn(versions, String(n)) ? versions[String(n)] : undefined;
    const v: Rec = isObj(vv) ? vv : {};
    const mark = tsOf(e['improved_to']);
    const start = typeof v['at'] === 'string' ? tsOf(v['at']) : tsOf(e['at']);
    if (mark === null && start === null) continue;
    const inside = (at: number): boolean => (mark !== null ? at > mark : at >= start!);
    const rec = typeof e['cluster'] === 'string' ? records.get(e['cluster']) ?? null : null;
    const seen = new Set<string>();
    for (const [f, s] of uses) if (f === name) seen.add(first8(s));
    for (const [names, s] of injects) if (names.has(name)) seen.add(first8(s));
    const missed: Rec[] = [];
    const evs = rec !== null && Array.isArray(rec['evidence']) ? rec['evidence'] : [];
    for (const ev of evs) {
      if (!isObj(ev) || typeof ev['id'] !== 'string') continue;
      const m = TURN_ID.exec(ev['id']);
      const at = tsOf(ev['ts']);
      if (m === null || at === null || at > nowMs || !inside(at) || seen.has(m[1]!)) continue;
      missed.push(ev);
    }
    const misses = tally(v, 'misses') + missed.length;
    const tried = new Set(strs(v['tried']));
    const inj = tally(v, 'injects');
    const ff = tally(v, 'false_fires');
    let tunes: string[] = [];
    if (inj >= TUNE_MIN_INJECTS && ff * FALSE_FIRE_TUNE[1] > inj * FALSE_FIRE_TUNE[0]) tunes.push(TUNE_NARROW);
    if (misses >= MISS_TUNE) tunes.push(TUNE_WIDEN);
    tunes = tunes.filter((t) => !tried.has(t));
    const pits: Array<[string, string]> = [];
    let stepsFrom: [number, string, string] | null = null;
    const recurring = new Set(rec !== null ? strs(rec['steps']) : []);
    const done = new Set<string>();
    const mine = uses
      .filter((u) => u[0] === name && inside(u[2]))
      .sort((x, y) => x[2] - y[2] || cmpCodepoint(x[1], y[1]));
    for (const [, s, at] of mine) {
      let turn: STurn | null = null;
      for (const t of turns.get(first8(s)) ?? []) if (t[0] <= at) turn = t;
      if (turn === null || done.has(turn[3])) continue;
      done.add(turn[3]);
      const tid = turn[3];
      if (turn[2] === false && typeof turn[4] === 'string' && turn[4]) {
        if (!text.includes(`[${tid}]`)) {
          pits.push([tid, turn[4]]);
          if (stepsFrom === null) {
            const line = pitfallLine(tid, turn[4]);
            const note = line.slice(line.indexOf('] ') + 2);
            stepsFrom = [turn[0], tid, `Before you finish, check for what [${tid}] was corrected for: ${note}`];
          }
        }
      } else if (turn[2] === true && recurring.size > 0) {
        const grams = ngrams(turn[5]);
        const [num, den] = STEP_SHARE;
        let shared = 0;
        for (const g of grams) if (recurring.has(g)) shared += 1;
        if (grams.size > 0 && shared * den < grams.size * num && stepsFrom === null) {
          stepsFrom = [turn[0], tid, `It also worked as ${turn[5].join(' > ')} [${tid}].`];
        }
      }
    }
    const kw = csv(sdoc.metadata['bantamkit-keywords']);
    const newKw = [...kw];
    if (tunes.includes(TUNE_WIDEN) && rec !== null) {
      const words = new Set<string>();
      for (const ev of missed) if (typeof ev['prompt'] === 'string') for (const t of tokenizeV2(ev['prompt'])) words.add(t);
      for (const k of strs(rec['keywords'])) {
        if (newKw.length >= KEYWORDS_MAX) break;
        if (words.has(k) && !newKw.includes(k) && !k.includes(',')) newKw.push(k);
      }
    }
    const ids = csv(sdoc.metadata['bantamkit-evidence']);
    const newIds = [...ids, ...pits.map(([i]) => i).filter((i) => !ids.includes(i))];
    const b = improveBundle(rec, typeof e['cluster'] === 'string' ? e['cluster'] : '', newIds);
    const changed = newKw.length !== kw.length || newKw.some((k, i) => k !== kw[i]) || pits.length > 0;
    let det = text;
    if (changed) {
      const body = pits.length > 0 ? appendToSection(sdoc.body, PITFALLS, pits.map(([i, f]) => pitfallLine(i, f))) : null;
      det = withMeta(text, body, { 'bantamkit-evidence': newIds.join(','), 'bantamkit-keywords': newKw.join(',') });
    }
    let final: string | null = changed ? det : null;
    let wait: string[] = [];
    if (tunes.length > 0) {
      const counts = { false_fires: ff, injects: inj, misses };
      const out = chain.length > 0 ? await improve(tunes, det, b, counts, chain, home, cwd, now, target) : null;
      if (out === null || out.drafter === null) wait = TUNE_KINDS.filter((k) => tunes.includes(k));
      else if (out.ok && out.text !== null) final = out.text;
    }
    if (final !== null) {
      const drafted = final !== det;
      let folded = false;
      if (!auto && stepsFrom !== null) {
        // automatic edits off: this change becomes the skill's ONE proposal, so the steps
        // line rides in it rather than being dropped for want of a free slot
        try {
          const finalS = withStep(final, stepsFrom[1], stepsFrom[2]);
          const detS = drafted ? withStep(det, stepsFrom[1], stepsFrom[2]) : finalS;
          [final, det, folded] = [finalS, detS, true];
        } catch (err) {
          if (!(err instanceof SkillFileError)) throw err;
        }
      }
      let [event] = applyText(name, final, home, cwd, now, b, auto);
      if (event === null && drafted && changed) [event] = applyText(name, det, home, cwd, now, b, auto);
      if (event !== null) {
        events.push(event);
        if (folded) stepsFrom = null;
      }
    }
    let tune: Rec | null = null;
    if (wait.length > 0) {
      const old: Rec = isObj(e['tune']) ? e['tune'] : {};
      const oldKinds = TUNE_KINDS.filter((k) => strs(old['kinds']).includes(k));
      const kinds = TUNE_KINDS.filter((k) => wait.includes(k) || oldKinds.includes(k));
      if (kinds.length !== oldKinds.length) events.push(`waiting on a drafter to tune ${name}`);
      tune = { at: typeof old['at'] === 'string' ? old['at'] : now, kinds };
    }
    let prop: Rec | null = null;
    if (stepsFrom !== null) {
      const fs2 = readState(home).skills;
      const fresh = Object.hasOwn(fs2, name) ? fs2[name] : undefined;
      const nowLive = isObj(fresh) ? liveText(fresh) : null;
      if (nowLive !== null && isObj(fresh) && slotFree(fresh)) {
        try {
          const cur = UTF8.decode(nowLive[1]);
          const ptext = withStep(cur, stepsFrom[1], stepsFrom[2]);
          prop = proposalOf('steps', nowLive[1], cur, ptext, now);
          events.push(`proposed a change to ${name}`);
        } catch (err) {
          if (!(err instanceof TypeError || err instanceof SkillFileError)) throw err;
          prop = null;
        }
      }
    }
    marks.set(name, [n, misses, [...new Set([...tried, ...tunes])].sort(cmpCodepoint), tune, prop]);
  }

  // two skills that fire together: a proposed merge, on the first name
  const fired = new Map<string, Set<string>>();
  for (const [names, s] of injects) {
    for (const nm of names) {
      if (!Object.hasOwn(skills, nm)) continue;
      const set = fired.get(nm) ?? new Set<string>();
      set.add(s);
      fired.set(nm, set);
    }
  }
  const merges = new Map<string, string>();
  const [num, den] = TOGETHER_SHARE;
  const names = [...fired.keys()].sort(cmpCodepoint);
  for (const a of names) {
    for (const b2 of names) {
      if (cmpCodepoint(b2, a) <= 0 || merges.has(a)) continue;
      const sa = fired.get(a)!;
      const sb = fired.get(b2)!;
      let co = 0;
      for (const s of sa) if (sb.has(s)) co += 1;
      if (co < TOGETHER_SESSIONS || co * den < sa.size * num || co * den < sb.size * num) continue;
      const ea = skills[a];
      if (!isObj(ea) || !slotFree(ea) || (marks.has(a) && marks.get(a)![4] !== null)) continue;
      const pa = ea['proposal'];
      if (isObj(pa) && pa['kind'] === 'merge' && pa['with'] === b2) continue;
      merges.set(a, b2);
      events.push(`proposed merging ${a} with ${b2}`);
    }
  }
  if (marks.size === 0 && merges.size === 0) return events;
  const written = updateState(home, (fresh) => {
    const live = fresh.skills as Record<string, unknown>;
    for (const [name, [n, misses, tried, tune, prop]] of marks) {
      const e = Object.hasOwn(live, name) ? live[name] : undefined;
      if (!isObj(e)) continue;
      e['improved_to'] = now;
      if (!isObj(e['versions'])) e['versions'] = {};
      const vs = e['versions'] as Rec;
      let v = Object.hasOwn(vs, String(n)) ? vs[String(n)] : undefined;
      if (!isObj(v)) {
        v = {};
        vs[String(n)] = v;
      }
      if (misses) (v as Rec)['misses'] = misses;
      if (tried.length > 0) (v as Rec)['tried'] = tried;
      if (tune !== null) e['tune'] = tune;
      if (prop !== null && slotFree(e)) e['proposal'] = prop;
    }
    for (const [a, b2] of merges) {
      const e = Object.hasOwn(live, a) ? live[a] : undefined;
      if (isObj(e) && slotFree(e)) e['proposal'] = { at: now, kind: 'merge', status: 'pending', with: b2 };
    }
  });
  replaceState(state, written);
  return events;
}
