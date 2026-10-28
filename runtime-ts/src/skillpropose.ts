/**
 * #206 Task 11: the `skill_propose` prompt and the skills SessionStart line — the port of
 * `runtime-py/src/bantamkit/skillpropose.py`, which carries the full rationale. Same text, same
 * files, same sentences; `render` is async here because the drafter's chain is.
 *
 * Loaded by the server, and by the hook only on SessionStart (a dynamic import), so the other
 * hook events never pay for the modules the command needs.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import { cmpCodepoint } from './pysem.js';
import {
  DRAFTER_HOST,
  bundle,
  bundleJson,
  defaultChain,
  draft,
  draftsLog,
  gate,
  logLine,
  type Handoff,
} from './skilldraft.js';
import { backupDir, backupRoot, readState, SkillFileError, updateState, type SkillsState } from './skillfile.js';
import { HOST_CLAUDE_CODE, selectAdapter } from './skillhost.js';
import { draftEntry, draftText, install, InstallError, installRoot, newVersion, removeDir, skillText, undo } from './skillinstall.js';
import { PENDING_MAX, ProposalsError, readProposals, writeProposals } from './skillmine.js';
import { demote, promote } from './skillpromote.js';
import { LogSegment } from './storage/logsegment.js';
import { auditEnabled } from './storage/retention.js';

type Rec = Record<string, unknown>;

export const SKILL_PROPOSE_NAME = 'skill_propose';
export const SKILL_PROPOSE_PROMPT_TITLE = 'bantamkit skill proposals';
export const SKILL_PROPOSE_PROMPT_DESCRIPTION =
  'List the skills bantamkit proposes from your repeated, successful work and the ones it ' +
  'installed, or approve, reject, undo, promote or demote one by its id or name.';
/** `[name, description]` of the prompt's arguments, all optional, in Claude Code's fill order. */
export const ARGUMENTS: readonly (readonly [string, string])[] = [
  ['action', 'list (the default), approve, reject, undo, promote or demote'],
  ['target', 'a proposal id, or the name of an installed skill'],
  ['level', 'project or user: where an approved skill is installed'],
];
export const ACTIONS: readonly string[] = ['list', 'approve', 'reject', 'undo', 'promote', 'demote'];
export const COMMAND = '/mcp__bantamkit__skill_propose';
/** The `maxTokens` of the one `sampling/createMessage` request a draft sends. */
export const SAMPLING_MAX_TOKENS = 4096;
/** Where the host agent writes its draft: `~/.bantamkit/skill-handoff/<proposal id>/SKILL.md`. */
export const HANDOFF_DIR = 'skill-handoff';
export const LINE_MAX_BYTES = 200;

export const EMPTY =
  'bantamkit skill proposals: nothing is pending and no skill is installed. The daily run ' +
  'proposes a skill once the same work has succeeded 3 times in shiftwork units or 5 times ' +
  'in sessions.';

export type Sampler = (system: string, user: string) => Promise<unknown>;

const isObj = (v: unknown): v is Rec => v !== null && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string';

function int(v: unknown): number | null {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= Number.MAX_SAFE_INTEGER ? v : null;
}

const num = (v: unknown): string => {
  const n = int(v);
  return n === null ? '?' : String(n);
};

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter(str) : []);

/** An argument as typed: absent or "" is null; `name=value` is read as `value`. */
function arg(value: unknown, name: string): string | null {
  if (!str(value) || value === '') return null;
  const prefix = `${name}=`;
  const v = value.startsWith(prefix) ? value.slice(prefix.length) : value;
  return v || null;
}

export function handoffPath(home: string, cid: string): string {
  return path.join(home, '.bantamkit', HANDOFF_DIR, cid, 'SKILL.md');
}

function records(doc: Rec | null): Rec[] {
  if (doc === null) return [];
  return (doc['clusters'] as unknown[]).filter((r): r is Rec => isObj(r) && str(r['id']));
}

function pending(doc: Rec | null): Rec[] {
  return records(doc)
    .filter((r) => r['status'] === 'pending')
    .slice(0, PENDING_MAX);
}

function skills(state: SkillsState | null): Map<string, Rec> {
  const out = new Map<string, Rec>();
  if (state === null) return out;
  for (const [n, e] of Object.entries(state.skills)) if (isObj(e)) out.set(n, e);
  return out;
}

function waiting(state: SkillsState | null): [string, Rec][] {
  const all = skills(state);
  const out: [string, Rec][] = [];
  for (const name of [...all.keys()].sort(cmpCodepoint)) {
    const p = all.get(name)!['proposal'];
    if (isObj(p) && p['status'] === 'pending' && str(p['kind'])) out.push([name, p]);
  }
  return out;
}

function stateOrNull(home: string): SkillsState | null {
  try {
    return readState(home);
  } catch (e) {
    if (e instanceof SkillFileError) return null;
    throw e;
  }
}

// --------------------------------------------------------------------------------- list

function proposalLines(r: Rec): string[] {
  const pitfalls: string[] = [];
  for (const p of Array.isArray(r['pitfalls']) ? r['pitfalls'] : []) {
    if (isObj(p) && str(p['id'])) {
      const f = p['failure'];
      pitfalls.push(str(f) && f ? `${p['id']} (${f})` : p['id']);
    }
  }
  const ids = (Array.isArray(r['evidence']) ? r['evidence'] : [])
    .filter((e): e is Rec => isObj(e) && str(e['id']))
    .map((e) => e['id'] as string);
  const source = str(r['source']) ? r['source'] : '?';
  const level = str(r['level']) ? r['level'] : '?';
  const id = r['id'] as string;
  return [
    `- ${id}: ${source}, ${num(r['successes'])} of ${num(r['bar'])} successes, ${level} level`,
    `  keywords: ${strs(r['keywords']).join(', ') || '-'}`,
    `  steps: ${strs(r['steps']).join('; ') || '-'}`,
    `  pitfalls: ${pitfalls.join('; ') || '-'}`,
    `  evidence: ${ids.join(', ') || '-'}`,
    `  approve: ${COMMAND} approve ${id}   reject: ${COMMAND} reject ${id}`,
  ];
}

function waitingLines(name: string, p: Rec): string[] {
  const what =
    p['kind'] === 'remove'
      ? 'remove it (unused through probation, but edited by hand, so never removed for you)'
      : `a proposed ${p['kind'] as string} change`;
  const out = [`- ${name}: ${what}`];
  const diff = p['diff'];
  if (str(diff) && diff) out.push('  ```diff', ...diff.split('\n').map((line) => `  ${line}`), '  ```');
  out.push(`  approve: ${COMMAND} approve ${name}   reject: ${COMMAND} reject ${name}`);
  return out;
}

function skillLine(name: string, e: Rec): string {
  const parts = [`- ${name} v${num(e['version'])}`, e['auto'] === true ? 'auto' : 'approved', `${str(e['level']) ? e['level'] : '?'} level`];
  const until = e['probation_until'];
  if (str(until)) parts.push(`on probation until ${until.slice(0, 10)}`);
  const promoted = e['promoted'];
  if (isObj(promoted)) parts.push(`promoted (${str(promoted['mode']) ? promoted['mode'] : '?'})`);
  const refused = e['promote_refused'];
  if (isObj(refused) && str(refused['reason'])) parts.push(`promotion refused: ${refused['reason']}`);
  return parts.join(', ');
}

export function renderList(home: string): string {
  const out: string[] = [];
  let doc: Rec | null = null;
  try {
    doc = readProposals(home);
  } catch (e) {
    if (!(e instanceof ProposalsError)) throw e;
    out.push(`The proposals could not be read: ${e.message}.`);
  }
  let state: SkillsState | null = null;
  try {
    state = readState(home);
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
    out.push(`The installed skills could not be read: ${e.message}.`);
  }
  const open = pending(doc);
  const items = waiting(state);
  const live = skills(state);
  if (!out.length && !open.length && !items.length && !live.size) return EMPTY;
  const lines = ['bantamkit skill proposals', '', ...out, ...(out.length ? [''] : [])];
  if (open.length) {
    lines.push(`Pending (${open.length} of at most ${PENDING_MAX}):`);
    for (const r of open) lines.push(...proposalLines(r));
  } else {
    lines.push('No proposal is pending.');
  }
  if (items.length) {
    lines.push('', 'Waiting on you:');
    for (const [name, p] of items) lines.push(...waitingLines(name, p));
  }
  lines.push('');
  if (live.size) {
    lines.push('Installed:');
    for (const n of [...live.keys()].sort(cmpCodepoint)) lines.push(skillLine(n, live.get(n)!));
    lines.push(`  undo: ${COMMAND} undo <name>   promote: ${COMMAND} promote <name>   demote: ${COMMAND} demote <name>`);
  } else {
    lines.push('No skill is installed.');
  }
  return lines.join('\n');
}

// ------------------------------------------------------------------------------ approve

function handoffText(rec: Rec, handoff: Handoff, home: string): string {
  const id = rec['id'] as string;
  return (
    `No sampling client or endpoint drafted proposal ${id}, so you draft it.\n\n` +
    `1. Write ONE file, ${handoffPath(home, id)}, with your own file tools, following these instructions:\n\n` +
    `${handoff.instructions}\n\n` +
    `The evidence bundle:\n\n\`\`\`json\n${bundleJson(handoff.bundle)}\n\`\`\`\n\n` +
    `2. Then run ${COMMAND} approve ${id} again. bantamkit gates the file, adds its metadata and installs it under ` +
    `${handoff.target}, with references/evidence.md written from the evidence. Write nothing else.`
  );
}

const gateFailed = (where: string, reasons: readonly string[], tail: string): string =>
  [`${where} did not pass the gate, so nothing was installed:`, ...reasons.map((r) => `- ${r}`), tail].join('\n');

function installNow(rec: Rec, doc: Rec, text: string, level: string | null, home: string, now: string): string {
  const id = rec['id'] as string;
  if (selectAdapter(home).host !== HOST_CLAUDE_CODE) {
    let root: string;
    let stamped: string;
    try {
      [, root] = installRoot(rec, level, home);
      stamped = skillText(rec, text);
    } catch (e) {
      if (!(e instanceof SkillFileError)) throw e;
      return `could not prepare proposal ${id}: ${e.message}`;
    }
    return (
      'No Claude Code skill directory was found on this host, so nothing was written. ' +
      `Place this file yourself, as ${root}/<name>/SKILL.md where <name> is its name:\n\n` +
      `\`\`\`markdown\n${stamped}\`\`\``
    );
  }
  let got;
  try {
    got = install(rec, text, level, home, now, false);
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
    return `could not install proposal ${id}: ${e.message}`;
  }
  writeProposals(home, doc);
  fs.rmSync(path.dirname(handoffPath(home, id)), { recursive: true, force: true });
  return `installed skill ${got.name} at ${got.path} (${got.level} level).\nundo: ${COMMAND} undo ${got.name}`;
}

async function approveProposal(
  rec: Rec,
  doc: Rec,
  level: string | null,
  home: string,
  cwd: string | null,
  now: string,
  sampler: Sampler | null,
): Promise<string> {
  const cid = rec['id'] as string;
  if (rec['status'] === 'installed') return `proposal ${cid} is already installed`;
  if (rec['eligible'] !== true) {
    return `proposal ${cid} has not cleared its bar: ${num(rec['successes'])} of ${num(rec['bar'])} successes`;
  }
  const stored = draftText(rec);
  if (stored !== null) return installNow(rec, doc, stored, level, home, now);
  const staged = handoffPath(home, cid);
  let isFile = false;
  try {
    isFile = fs.statSync(staged).isFile();
  } catch {
    isFile = false;
  }
  if (isFile) {
    let text: string;
    try {
      text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(staged));
    } catch {
      return `${staged} is not UTF-8 text; nothing was installed`;
    }
    const g = gate(text, bundle(rec), home, cwd);
    const outcome = { drafter: DRAFTER_HOST, ok: g.ok, text: g.ok ? text : null, reasons: g.reasons, unreachable: [], handoff: null };
    new LogSegment(draftsLog(home)).append(logLine(outcome, now, cid));
    if (!g.ok) return gateFailed(`The SKILL.md at ${staged}`, g.reasons, `Fix it and run ${COMMAND} approve ${cid} again.`);
    return installNow(rec, doc, text, level, home, now);
  }
  const out = await draft(rec, defaultChain(sampler, true), home, cwd, now);
  if (out.handoff !== null) return handoffText(rec, out.handoff, home);
  if (!out.ok || out.text === null) {
    return gateFailed(`The draft from ${String(out.drafter)}`, out.reasons, `It was discarded and logged; proposal ${cid} stays as it is.`);
  }
  rec['draft'] = draftEntry(out.drafter, out.text, now);
  writeProposals(home, doc);
  return installNow(rec, doc, out.text, level, home, now);
}

function dropProposal(home: string, name: string, status: string | null = null): void {
  updateState(home, (fresh) => {
    const entry = fresh.skills[name];
    if (isObj(entry) && isObj(entry['proposal'])) {
      if (status === null) delete entry['proposal'];
      else entry['proposal']['status'] = status;
    }
  });
}

function approveItem(name: string, p: Rec, home: string, now: string): string {
  if (p['kind'] === 'remove') {
    const entry = skills(stateOrNull(home)).get(name) ?? {};
    if (isObj(entry['promoted'])) {
      try {
        demote(name, home);
      } catch (e) {
        if (!(e instanceof SkillFileError)) throw e;
        return `could not remove skill ${name}: ${e.message}`;
      }
    }
    const target = str(entry['path']) ? entry['path'] : null;
    let isDir = false;
    try {
      isDir = target !== null && fs.statSync(target).isDirectory();
    } catch {
      isDir = false;
    }
    if (target !== null && isDir) {
      backupDir(backupRoot(home), target, now);
      removeDir(target);
    }
    updateState(home, (fresh) => {
      const gone = fresh.skills[name];
      delete fresh.skills[name];
      if (isObj(gone)) {
        delete gone['proposal'];
        if (!isObj(fresh['removed'])) fresh['removed'] = {};
        (fresh['removed'] as Rec)[name] = gone;
      }
    });
    return `removed skill ${name}.\nundo: ${COMMAND} undo ${name}`;
  }
  const text = p['text'];
  if (!str(text)) return `the proposed ${p['kind'] as string} change to ${name} carries no text to apply`;
  let said: string;
  try {
    said = newVersion(name, text, home, now, 'approved');
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
    return `could not apply the proposed change to ${name}: ${e.message}`;
  }
  dropProposal(home, name);
  return said;
}

// ------------------------------------------------------------------------------- render

/** The text of the one user message `prompts/get skill_propose` answers; never throws for input. */
export async function render(
  actionIn: unknown,
  targetIn: unknown,
  levelIn: unknown,
  home: string,
  cwd: string | null,
  now: string,
  sampler: Sampler | null = null,
): Promise<string> {
  const action = arg(actionIn, 'action') ?? 'list';
  const target = arg(targetIn, 'target');
  const level = arg(levelIn, 'level');
  if (!ACTIONS.includes(action)) return `unknown action '${action}'; one of ${ACTIONS.join(', ')}`;
  if (action === 'list') return renderList(home);
  if (target === null) return `action ${action} needs a target: ${COMMAND} ${action} <id or name>`;
  if (level !== null && level !== 'project' && level !== 'user') return 'level must be project or user';
  if (action === 'approve' || action === 'reject') {
    let doc: Rec | null;
    try {
      doc = readProposals(home);
    } catch (e) {
      if (!(e instanceof ProposalsError)) throw e;
      return `could not ${action} ${target}: ${e.message}`;
    }
    const rec = records(doc).find((r) => r['id'] === target);
    if (rec !== undefined && doc !== null) {
      if (action === 'approve') return approveProposal(rec, doc, level, home, cwd, now, sampler);
      if (rec['status'] === 'installed') return `proposal ${target} is installed; ${COMMAND} undo <name> removes its skill`;
      const successes = int(rec['successes']) ?? 0;
      rec['status'] = 'rejected';
      rec['rejected_at'] = successes;
      writeProposals(home, doc);
      return `rejected proposal ${target}; it is offered again once it has ${2 * successes} successes`;
    }
    const item = new Map(waiting(stateOrNull(home))).get(target);
    if (item === undefined) return `no pending proposal or change is named '${target}'`;
    if (action === 'approve') return approveItem(target, item, home, now);
    dropProposal(home, target, 'rejected');
    return `kept skill ${target}; the proposed ${item['kind'] as string} change is dropped`;
  }
  if (action === 'promote') {
    try {
      return promote(target, home, cwd, now).reason;
    } catch (e) {
      if (!(e instanceof SkillFileError)) throw e;
      return e.message;
    }
  }
  if (action === 'demote') {
    try {
      return demote(target, home);
    } catch (e) {
      if (!(e instanceof SkillFileError)) throw e;
      return e.message;
    }
  }
  // undo: a promoted skill is demoted first; else the newest backup is put back. An install
  // undone marks its proposal rejected, so the daily run does not install it again.
  const entry = skills(stateOrNull(home)).get(target);
  let said: string;
  try {
    if (entry !== undefined && isObj(entry['promoted'])) return demote(target, home);
    said = undo(target, home);
  } catch (e) {
    if (!(e instanceof SkillFileError)) throw e;
    return e.message;
  }
  if (entry !== undefined && !skills(stateOrNull(home)).has(target)) {
    const cid = entry['cluster'];
    let doc: Rec | null;
    try {
      doc = readProposals(home);
    } catch (e) {
      if (!(e instanceof ProposalsError)) throw e;
      doc = null;
    }
    const rec = records(doc).find((r) => r['id'] === cid);
    if (rec !== undefined && doc !== null && rec['status'] === 'installed') {
      rec['status'] = 'rejected';
      rec['rejected_at'] = int(rec['successes']) ?? 0;
      writeProposals(home, doc);
      said += `; proposal ${cid as string} is marked rejected`;
    }
  }
  return said;
}

// --------------------------------------------------------------------- the SessionStart line

const ELLIPSIS = '…';
const HEAD = '[bantamkit] skills: ';
const TAIL = ` — ${COMMAND} lists them.`;
const b = (text: string): number => Buffer.byteLength(text, 'utf8');

function clip(text: string, room: number): string {
  let out = '';
  for (const ch of text) {
    if (b(out + ch) + b(ELLIPSIS) > room) break;
    out += ch;
  }
  return out + ELLIPSIS;
}

/** The line's words for one daily event (the strings `skillinstall`/`skillpromote` make). */
export function eventItem(event: string): string {
  const forms: [string, (n: string) => string][] = [
    ['installed skill ', (n) => `installed ${n} on probation (undo: ${COMMAND} undo ${n})`],
    ['removed unused skill ', (n) => `removed unused ${n} (undo: ${COMMAND} undo ${n})`],
    ['proposed removing edited skill ', (n) => `${n} unused but edited: removal waits on you`],
    ['promoted skill ', (n) => `promoted ${n} (undo: ${COMMAND} demote ${n})`],
  ];
  for (const [prefix, fmt] of forms) if (event.startsWith(prefix)) return fmt(event.slice(prefix.length));
  return event;
}

/** `[bantamkit] skills: a; b; +k more — <command> lists them.`, at most `LINE_MAX_BYTES` bytes. */
export function renderLine(items: readonly string[]): string {
  const room = LINE_MAX_BYTES - b(HEAD) - b(TAIL);
  let body = '';
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!;
    const left = items.length - i - 1;
    const more = left ? `; +${left} more` : '';
    const cand = body ? `${body}; ${item}` : item;
    if (b(cand + more) <= room) {
      body = cand;
      continue;
    }
    body = body ? `${body}; +${items.length - i} more` : clip(item, room - b(more)) + more;
    break;
  }
  return HEAD + body + TAIL;
}

function lineItems(home: string, state: SkillsState): [string, string][] {
  const out: [string, string][] = [];
  const events = Array.isArray(state['events']) ? state['events'] : [];
  for (const e of events) {
    if (isObj(e) && str(e['at']) && str(e['event'])) out.push([`event\t${e['at']}\t${e['event']}`, eventItem(e['event'])]);
  }
  let doc: Rec | null;
  try {
    doc = readProposals(home);
  } catch (e) {
    if (!(e instanceof ProposalsError)) throw e;
    doc = null;
  }
  for (const r of pending(doc)) out.push([`pending\t${r['id'] as string}`, `new proposal ${r['id'] as string}`]);
  return out;
}

/** One SessionStart line for what `surfaced` has not seen; null, with no write, when nothing is new. Never throws. */
export function sessionLine(home: string): string | null {
  try {
    if (!auditEnabled()) return null;
    const state = readState(home);
    const shown = new Set(strs(state['surfaced']));
    const items = lineItems(home, state);
    const fresh = items.filter(([k]) => !shown.has(k));
    if (!fresh.length) return null;
    const line = renderLine(fresh.map(([, w]) => w));
    const current = new Set(items.map(([k]) => k));
    updateState(home, (s) => {
      const kept = strs(s['surfaced']).filter((k) => current.has(k));
      s['surfaced'] = [...new Set([...kept, ...fresh.map(([k]) => k)])].sort(cmpCodepoint);
    });
    return line;
  } catch {
    return null;
  }
}
