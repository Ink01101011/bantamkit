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
import { parseNow } from './storage/retention.js';

export const AUTO_ENV = 'BANTAMKIT_SKILL_AUTO';
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

const OFF = new Set(['off', '0', 'false', 'no']);
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

export function autoEnabled(): boolean {
  return !OFF.has((process.env[AUTO_ENV] ?? '').trim().toLowerCase());
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
      edited = isEdited(text) || canonicalHash(text) !== e['sha256'];
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

/** True when the skill's SKILL.md no longer matches its hash (R8); null without one. */
export function editedByHand(entry: Rec): boolean | null {
  const live = liveText(entry);
  return live === null ? null : editedBytes(live[1], entry);
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
export function newVersion(name: string, text: string, home: string, now: string, kind: string): string {
  if (!VERSION_KINDS.includes(kind)) throw new InstallError('kind must be auto or approved');
  msOf(now);
  const skills = readState(home).skills;
  const entry = Object.hasOwn(skills, name) ? skills[name] : undefined;
  if (!isObj(entry)) throw new InstallError(`no skill named ${pyRepr(name)} is installed`);
  const live = liveText(entry);
  if (live === null) throw new InstallError(`skill ${name} has no SKILL.md at ${pyStr(entry['path'])}`);
  const [target, raw] = live;
  if (editedBytes(raw, entry)) throw new InstallError(`${name} was edited by hand; it only receives proposed changes`);
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
    if (live === null || editedBytes(live[1], e)) continue;
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
