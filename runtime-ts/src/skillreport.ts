/**
 * The skill audit as a record and a rendered report, with its disable proposals (#205). Port of
 * `runtime-py/src/bantamkit/skillreport.py`, whose docstring carries the contract;
 * `tools/conformance/suites/skill-host.mjs` compares the two (ops `record`, `render`, `propose`).
 *
 * THE DAILY RUN (Task 4): `daily` writes `~/.bantamkit/skill-audit.json` (`dumpIndex(record) + '\n'`,
 * temp-then-rename under `exclusive`), keeping the previous `surfaced` keys that are still findings;
 * `statusLine` is the `skill audit:` line of `bantamkit_status`, its `off; ` prefix reading
 * `BANTAMKIT_SKILL_AUDIT` (Amendment A3). Ops `daily`, `status`, `child` in the suite.
 *
 * THE SESSIONSTART LINE (Task 5): `sessionLine` names, in one line of at most `LINE_MAX_BYTES`
 * UTF-8 bytes, the surfaceable findings whose `surfaceKey` is not yet in `surfaced`, then adds
 * those keys, so nothing repeats; with nothing new it returns null and writes nothing. Op `line`.
 * `BANTAMKIT_SKILL_AUDIT=off` silences it too: null and no write, even over an older record that
 * still holds unseen findings (orchestrator ruling, job73 A6).
 *
 * THE PROMPT (Task 6): `skill_audit`, the second MCP prompt, answers
 * `renderReport(runLive(home, cwd, now)) + '\n\n' + SKILL_AUDIT_PROMPT_TAIL` as one user message.
 *
 * #206'S SKILLS (spec Component 7, job73 C15): `runLive` audits bantamkit's own skills roots too
 * (`bantamkit-project`, `bantamkit-user`), after `plugins` and before the host's `project` and
 * `user`; the record gains `generated` (counted skills whose metadata carries a
 * `bantamkit-generated-by` string) and `layer` (counted skills in a bantamkit root no host root
 * links to: not in `catalogue_bytes`, never `never-invoked`). The reference's docstring says why.
 *
 * K2: it REPORTS and PROPOSES a `settings.json` diff; it never edits the file — nothing here
 * opens a file for writing. A plugin is proposed only when usage is present, the transcripts span
 * at least `USAGE_DAYS` days, and every one of its counted skills had zero calls. Skills outside
 * a plugin are reported and never proposed.
 *
 * THE POINTS A PORT GETS WRONG, each held here: every list is sorted by code point
 * (`cmpCodepoint`), never `localeCompare`; the settings file is decoded with a FATAL decoder
 * that keeps a leading U+FEFF, as Python's strict `decode("utf-8")` does; `str.partition(':')`
 * is the FIRST colon; `strip(" \t")` strips spaces and tabs only.
 */
import fs from 'node:fs';
import path from 'node:path';

import { cmpCodepoint } from './pysem.js';
import { auditRoots, KIND_NEVER_INVOKED, scanRoots } from './skillaudit.js';
import type { FindingDict, LabelledRoot, OmissionDict, ScannedSkill } from './skillaudit.js';
import { parseSkill } from './skillfile.js';
import { Gathered, HOST_NONE, USAGE_DAYS, selectAdapter } from './skillhost.js';
import type { UsageSummary } from './skillhost.js';
import { dumpIndex } from './storage/hotindex.js';
import { exclusive } from './storage/lock.js';
import { auditEnabled, parseNow } from './storage/retention.js';

export const STATE_NAME = 'skill-audit.json';
export const STATE_VERSION = 1;
export const NO_ROOTS = 'no skill directory was found for this host';
export const GATHER_FAILED = 'the gather failed';
export const NOT_APPLIED = 'NOT applied; bantamkit never edits settings.json';
/** Component 7 (#206): the labels of bantamkit's own skills roots, and the stamp of a skill it wrote. */
export const OWN_PROJECT = 'bantamkit-project';
export const OWN_USER = 'bantamkit-user';
export const GENERATED_KEY = 'bantamkit-generated-by';
const HOST_LOCAL = ['project', 'user'];

/** The `skill_audit` MCP prompt (#205 Task 6), a PERSON's command; both servers serve these bytes. */
export const SKILL_AUDIT_NAME = 'skill_audit';
export const SKILL_AUDIT_PROMPT_TITLE = 'bantamkit skill audit';
export const SKILL_AUDIT_PROMPT_DESCRIPTION =
  'Audit the skills this host loads: catalogue bytes, shared trigger phrases, malformed ' +
  'frontmatter and, where the host keeps transcripts, skills with no call in 30 days. Inserts ' +
  'the report and a proposed settings.json change that is never applied for you.';
export const SKILL_AUDIT_PROMPT_TAIL =
  'Show me this report as it stands. Do not edit settings.json yourself; if a change is ' +
  'proposed above, ask me before applying it.';

/** The injection point a unit test overrides, as `retentionFs` is overridden. */
export const skillreportDeps = { selectAdapter };

export interface Proposal {
  plugin: string;
  file: string;
  line: number | null;
  before: string | null;
  after: string | null;
  skills: string[];
}

export interface AuditRecord {
  version: number;
  ts: string;
  host: string;
  roots: [string, string][];
  skills: number;
  catalogue_bytes: number;
  findings: FindingDict[];
  omissions: OmissionDict[];
  usage: UsageSummary | null;
  proposals: Proposal[];
  surfaced: string[];
  /** Component 7: present only when a bantamkit-written or `[skill]`-layer skill was counted. */
  generated?: string[];
  layer?: string[];
}

export interface ErrorRecord {
  version: number;
  ts: string;
  host: string;
  error: string;
  surfaced: string[];
}

export type SkillRecord = AuditRecord | ErrorRecord;

const plural = (count: number, word: string): string => (count === 1 ? `${count} ${word}` : `${count} ${word}s`);
const stripWs = (s: string): string => s.replace(/^[ \t]+|[ \t]+$/g, '');

/**
 * The line of `file` that switches `plugin` on, and that line switched off: the first line
 * AFTER the one naming `"enabledPlugins"` that is exactly `<ws>"<plugin>"<ws>:<ws>true<ws>[,]<ws>`
 * (a trailing `\r` dropped). Anything else is "not located". Read-only.
 */
function locate(file: string, plugin: string): [number | null, string | null, string | null] {
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(file));
  } catch {
    return [null, null, null];
  }
  let armed = false;
  const raws = text.split('\n');
  for (let i = 0; i < raws.length; i += 1) {
    const raw = raws[i]!;
    const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
    if (!armed) {
      armed = line.includes('"enabledPlugins"');
      continue;
    }
    const colon = line.indexOf(':');
    if (colon < 0 || stripWs(line.slice(0, colon)) !== `"${plugin}"`) continue;
    if (stripWs(line.slice(colon + 1)).replace(/,+$/, '').replace(/[ \t]+$/, '') !== 'true') continue;
    const at = line.lastIndexOf('true');
    return [i + 1, line, line.slice(0, at) + 'false' + line.slice(at + 4)];
  }
  return [null, null, null];
}

const pluginId = (s: ScannedSkill): string => `${s.plugin}@${s.marketplace}`;

/**
 * The plugins to switch off, each with the settings line that would do it. `found` is
 * `scanRoots`' answer; `sources` maps an enabled plugin id to the settings file its `true` won in.
 */
export function propose(
  found: readonly ScannedSkill[],
  usage: ReadonlyMap<string, number> | null,
  spanDays: number,
  sources: Readonly<Record<string, string>>,
): Proposal[] {
  if (usage === null || spanDays < USAGE_DAYS) return [];
  const plugins = new Map<string, Set<string>>();
  for (const s of found) {
    if (s.omitted === null && s.plugin !== '') {
      const pid = pluginId(s);
      if (!plugins.has(pid)) plugins.set(pid, new Set());
      plugins.get(pid)!.add(s.id);
    }
  }
  const out: Proposal[] = [];
  for (const pid of [...plugins.keys()].sort(cmpCodepoint)) {
    const ids = [...plugins.get(pid)!].sort(cmpCodepoint);
    if (ids.some((i) => (usage.get(i) ?? 0) > 0)) continue;
    if (!Object.prototype.hasOwnProperty.call(sources, pid)) continue;
    const file = sources[pid]!;
    const [line, before, after] = locate(file, pid);
    out.push({ plugin: pid, file, line, before, after, skills: ids });
  }
  return out;
}

const errorRecord = (now: string, host: string, error: string): ErrorRecord => ({
  version: STATE_VERSION,
  ts: now,
  host,
  error,
  surfaced: [],
});

/** The stored record (`skill-audit.json`, written by the daily run), or its error form. */
const realOr = (p: string): string | null => {
  try {
    return fs.realpathSync(p);
  } catch {
    return null;
  }
};
const isDir = (p: string): boolean => {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
};
const isLink = (p: string): boolean => {
  try {
    return fs.lstatSync(p).isSymbolicLink();
  } catch {
    return false;
  }
};

/** bantamkit's skills roots that exist: `<cwd>/.bantamkit/skills`, then `~/.bantamkit/skills`; a
 * root whose real path was already listed is left out (a cwd at the home). */
export function ownRoots(home: string, cwd: string | null): [string, string][] {
  const candidates: [string, string][] = [];
  if (cwd !== null) candidates.push([OWN_PROJECT, path.join(cwd, '.bantamkit', 'skills')]);
  candidates.push([OWN_USER, path.join(home, '.bantamkit', 'skills')]);
  const out: [string, string][] = [];
  const seen = new Set<string>();
  for (const [label, p] of candidates) {
    const real = isDir(p) ? realOr(p) : null;
    if (real === null || seen.has(real)) continue;
    seen.add(real);
    out.push([label, p]);
  }
  return out;
}

/** Whether the `SKILL.md` at `file` carries a `bantamkit-generated-by` string; any failure is false. */
function stamped(file: string): boolean {
  try {
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(file));
    const value = parseSkill(text).metadata[GENERATED_KEY];
    return typeof value === 'string' && value !== '';
  } catch {
    return false; // unreadable, not UTF-8 or not an X9 shape: the audit already reports it
  }
}

/** `[generated ids, layer ids, layer bytes]` over the counted skills outside a plugin. */
function ownership(found: readonly ScannedSkill[], roots: [string, string][]): [string[], string[], number] {
  const where = new Map(roots);
  const host = HOST_LOCAL.filter((l) => where.has(l)).map((l) => where.get(l)!);
  const generated = new Set<string>();
  const layer = new Set<string>();
  let layerBytes = 0;
  for (const s of found) {
    if (s.omitted !== null || s.plugin !== '') continue;
    const slash = s.relpath.indexOf('/');
    const label = s.relpath.slice(0, slash);
    const file = path.join(where.get(label)!, s.relpath.slice(slash + 1));
    if (stamped(file)) generated.add(s.id);
    if (label !== OWN_PROJECT && label !== OWN_USER) continue;
    const real = realOr(path.dirname(file));
    const linked = host.some((r) => {
      const p = path.join(r, s.directory);
      return isLink(p) && real !== null && realOr(p) === real;
    });
    if (!linked) {
      layer.add(s.id);
      layerBytes += s.bytes;
    }
  }
  return [[...generated].sort(cmpCodepoint), [...layer].sort(cmpCodepoint), layerBytes];
}

/**
 * The stored record (`skill-audit.json`, written by the daily run), or its error form. `own` is
 * `ownRoots(home, cwd)`: bantamkit's skills roots, audited after the plugins and before the
 * host's project and user roots (Component 7).
 */
export function buildRecord(g: Gathered, now: string, own: [string, string][] = []): SkillRecord {
  const hostRoots: [string, string][] = g.roots.map(([l, p]) => [l, p]);
  const all: [string, string][] = [...hostRoots.filter(([l]) => l === 'plugins'), ...own, ...hostRoots.filter(([l]) => l !== 'plugins')];
  if (all.length === 0) return errorRecord(now, g.host, NO_ROOTS);
  const roots: LabelledRoot[] = all.map(([label, path]) => ({ label, path }));
  const counts = g.usage === null ? null : g.usage.counts;
  const versions = g.versions === null ? null : new Map(Object.entries(g.versions));
  const found = scanRoots(roots, [...g.enabled], versions);
  const result = auditRoots(roots, { enabled: [...g.enabled], usage: counts, versions });
  const span = g.usage === null ? 0 : g.usage.spanDays;
  const [generated, layer, layerBytes] = ownership(found, all);
  const findings = result.findings
    .map((f) => f.asDict())
    .filter((f) => !(f.kind === KIND_NEVER_INVOKED && f.skills.length > 0 && layer.includes(f.skills[0]!)));
  const record: AuditRecord = {
    version: STATE_VERSION,
    ts: now,
    host: g.host,
    roots: all,
    skills: result.skills,
    catalogue_bytes: result.catalogueBytes - layerBytes,
    findings,
    omissions: result.omissions.map((o) => o.asDict()),
    usage: g.usage === null ? null : g.usage.summary(),
    proposals: propose(found, counts, span, g.sources),
    surfaced: [],
  };
  if (generated.length > 0 || layer.length > 0) {
    record.generated = generated;
    record.layer = layer;
  }
  return record;
}

/** Gather and audit now. Never throws: a failure is the error record (spec, "Gather fails"). */
export function runLive(home: string, cwd: string | null, now: string): SkillRecord {
  let host = HOST_NONE;
  try {
    const adapter = skillreportDeps.selectAdapter(home);
    host = adapter.host;
    return buildRecord(adapter.gather(home, cwd, parseNow(now)), now, ownRoots(home, cwd));
  } catch {
    // The report says it failed; no hook or tool fails.
    return errorRecord(now, host, GATHER_FAILED);
  }
}

function diffLines(record: AuditRecord): string[] {
  const usage = record.usage;
  const props = record.proposals;
  if (usage === null) {
    return [
      'proposed change: none — this host has no usage adapter, so no skill is called never-invoked and nothing is proposed',
    ];
  }
  if (usage.span_days < USAGE_DAYS) {
    return [`proposed change: none — the transcripts span ${usage.span_days} days; a change needs ${USAGE_DAYS}`];
  }
  if (props.length === 0) {
    return [`proposed change: none — no enabled plugin has every skill at 0 calls over ${USAGE_DAYS} days`];
  }
  const out = [`proposed change — ${NOT_APPLIED}:`];
  for (const file of [...new Set(props.map((p) => p.file))].sort(cmpCodepoint)) {
    const mine = props.filter((p) => p.file === file);
    const located = mine
      .filter((p) => p.line !== null)
      .sort((x, y) => x.line! - y.line! || cmpCodepoint(x.plugin, y.plugin));
    if (located.length > 0) {
      out.push(`--- ${file}`, `+++ ${file}`);
      for (const p of located) out.push(`@@ -${p.line} +${p.line} @@`, `-${p.before}`, `+${p.after}`);
    }
    for (const p of mine.filter((q) => q.line === null).sort((x, y) => cmpCodepoint(x.plugin, y.plugin))) {
      out.push(`set enabledPlugins["${p.plugin}"] to false in ${file} (the line could not be located)`);
    }
  }
  for (const p of [...props].sort((x, y) => cmpCodepoint(x.plugin, y.plugin))) {
    out.push(`${p.plugin}: every skill had 0 calls in ${USAGE_DAYS} days — ${p.skills.join(', ')}`);
  }
  out.push('edit the lines yourself, or save the hunks to a file and run `git apply --unidiff-zero <file>` from `/` (the paths are absolute)');
  return out;
}

/** The report a person reads: the prompt's body, byte-identical across runtimes. */
export function renderReport(record: SkillRecord): string {
  if ('error' in record) {
    return `skill audit — could not run: ${record.error}. The \`skill_audit\` tool still audits any directory you name as \`root\`.`;
  }
  const sev = new Map<string, number>();
  for (const f of record.findings) sev.set(f.severity, (sev.get(f.severity) ?? 0) + 1);
  const lines = [
    `skill audit — ${record.host}, ${plural(record.skills, 'skill')}, ${record.catalogue_bytes} catalogue bytes`,
    'roots: ' + record.roots.map(([label, path]) => `${label} ${path}`).join('; '),
  ];
  const usage = record.usage;
  if (usage === null) {
    lines.push('usage: none — this host has no usage adapter');
  } else {
    lines.push(
      `usage: ${plural(usage.calls, 'skill call')} over ${usage.span_days} days in ` +
        `${plural(usage.transcripts, 'transcript')} (${usage.unreadable} unreadable, ` +
        `${usage.skipped_lines} lines skipped)`,
    );
  }
  const generated = record.generated ?? [];
  const layer = record.layer ?? [];
  lines.push(`findings: ${sev.get('high') ?? 0} high, ${sev.get('medium') ?? 0} medium, ${sev.get('low') ?? 0} low`);
  for (const f of record.findings) {
    const named = f.skills.map((s) => (generated.includes(s) ? `${s} (generated)` : s));
    const who = named.length > 0 ? named.join(', ') : 'the catalogue';
    lines.push(`- ${f.severity} ${f.kind}: ${who} — ${f.detail}`);
  }
  if (generated.length > 0) lines.push(`generated by bantamkit (${GENERATED_KEY}): ${generated.length} — ${generated.join(', ')}`);
  if (layer.length > 0) {
    lines.push(`in bantamkit's [skill] layer only, so not in the catalogue bytes and never called never-invoked: ${layer.length} — ${layer.join(', ')}`);
  }
  if (record.omissions.length > 0) {
    lines.push('omissions: ' + record.omissions.map((o) => `${o.subject} ${o.count} (${o.size} bytes)`).join('; '));
  }
  lines.push(...diffLines(record));
  return lines.join('\n');
}

// ------------------------------------------------------------------------- the daily run

export function statePath(home: string): string {
  return path.join(home, '.bantamkit', STATE_NAME);
}

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
/** Python's `_is_int`: a whole number a JS number holds exactly; `true` is not one. */
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v);

/**
 * The stored record, or null: missing, unreadable, not JSON, `version !== 1`, or a shape the
 * status line cannot print. A null is recomputed by the next day's run. The bytes are decoded
 * with a FATAL decoder that keeps a leading U+FEFF, so a BOM is refused, as Python refuses it.
 */
export function readState(home: string): SkillRecord | null {
  let doc: unknown;
  try {
    doc = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(statePath(home))));
  } catch {
    return null;
  }
  if (!isRecord(doc) || !isInt(doc['version']) || doc['version'] !== STATE_VERSION) return null;
  if (typeof doc['ts'] !== 'string' || typeof doc['host'] !== 'string') return null;
  const surfaced = doc['surfaced'];
  if (!Array.isArray(surfaced) || !surfaced.every((s) => typeof s === 'string')) return null;
  if (Object.hasOwn(doc, 'error')) return typeof doc['error'] === 'string' ? (doc as unknown as ErrorRecord) : null;
  const findings = doc['findings'];
  const usage = doc['usage'];
  const ok =
    isInt(doc['skills']) &&
    isInt(doc['catalogue_bytes']) &&
    Array.isArray(findings) &&
    findings.every(isRecord) &&
    Array.isArray(doc['proposals']) &&
    Array.isArray(doc['roots']) &&
    Array.isArray(doc['omissions']) &&
    (usage === null || (isRecord(usage) && isInt(usage['span_days'])));
  return ok ? (doc as unknown as AuditRecord) : null;
}

/** `kind<TAB>skills,joined<TAB>detail`: what `surfaced` remembers was already shown. */
export function surfaceKey(finding: FindingDict | Record<string, unknown>): string {
  const f = finding as Record<string, unknown>;
  const skills = Array.isArray(f['skills']) ? (f['skills'] as unknown[]).join(',') : '';
  return `${String(f['kind'] ?? 'None')}\t${skills}\t${String(f['detail'] ?? 'None')}`;
}

function writeRecord(p: string, record: SkillRecord): void {
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${dumpIndex(record)}\n`, 'utf8');
  fs.renameSync(tmp, p);
}

/** The once-a-day run the Retention child makes (K1). Silent; never throws. */
export function daily(home: string, cwd: string | null, now: string): void {
  try {
    const record = runLive(home, cwd, now);
    const p = statePath(home);
    exclusive(p, (held) => {
      if (!held) return;
      const prev = readState(home);
      if (prev !== null && !('error' in record)) {
        const keys = new Set(record.findings.map((f) => surfaceKey(f)));
        record.surfaced = prev.surfaced.filter((k) => keys.has(k)).sort(cmpCodepoint);
      }
      writeRecord(p, record);
    });
  } catch {
    /* recomputed at the next day's run */
  }
}

/** The `skill audit:` line of `bantamkit_status`. Never throws. */
export function statusLine(home: string): string {
  const prefix = auditEnabled() ? '' : 'off; ';
  const unreadable = `skill audit: ${prefix}the last record is unreadable; the next run recomputes it`;
  try {
    let exists = true;
    try {
      fs.lstatSync(statePath(home));
    } catch {
      exists = false;
    }
    if (!exists) return `skill audit: ${prefix}never ran; usage adapter ${skillreportDeps.selectAdapter(home).host}`;
    const record = readState(home);
    if (record === null) return unreadable;
    if ('error' in record) return `skill audit: ${prefix}last ran ${record.ts}; no report — ${record.error}`;
    const sev = new Map<unknown, number>();
    for (const f of record.findings) sev.set(f.severity, (sev.get(f.severity) ?? 0) + 1);
    const usage = record.usage;
    const clause =
      usage === null
        ? `usage: none — ${record.host} has no usage adapter, so nothing is called never-invoked`
        : usage.span_days < USAGE_DAYS
          ? `usage over ${usage.span_days} days (a proposed change needs ${USAGE_DAYS})`
          : `usage over ${USAGE_DAYS} days; ${plural(record.proposals.length, 'change')} proposed`;
    return (
      `skill audit: ${prefix}last ran ${record.ts} on ${record.host}; ` +
      `${plural(record.skills, 'skill')}, ${record.catalogue_bytes} catalogue bytes; ` +
      `findings ${sev.get('high') ?? 0} high, ${sev.get('medium') ?? 0} medium, ${sev.get('low') ?? 0} low; ${clause}`
    );
  } catch {
    return unreadable;
  }
}

// --------------------------------------------------------------------- the SessionStart line

export const LINE_MAX_BYTES = 200;
export const COMMAND = '/mcp__bantamkit__skill_audit';
const TAIL = ` — ${COMMAND} has the report.`;
const ELLIPSIS = '…';
const bytes = (text: string): number => Buffer.byteLength(text, 'utf8');

/** The longest prefix of whole code points that fits `room` bytes with the ellipsis. */
function clip(text: string, room: number): string {
  let out = '';
  for (const ch of text) {
    if (bytes(out + ch) + bytes(ELLIPSIS) > room) break;
    out += ch;
  }
  return out + ELLIPSIS;
}

/** Python's `_well_formed`: a finding the line can name and `surfaced` can key. */
function wellFormed(f: Record<string, unknown>): boolean {
  const skills = f['skills'];
  return (
    typeof f['kind'] === 'string' &&
    typeof f['detail'] === 'string' &&
    Array.isArray(skills) &&
    skills.every((s) => typeof s === 'string')
  );
}

/** Every `high` finding, and `never-invoked` only once usage spans `USAGE_DAYS` days. Record order. */
export function surfaceable(record: AuditRecord): FindingDict[] {
  const usage = record.usage;
  const longEnough = isRecord(usage) && (usage.span_days ?? 0) >= USAGE_DAYS;
  return record.findings.filter((f) => {
    const d = f as unknown as Record<string, unknown>;
    return wellFormed(d) && (d['severity'] === 'high' || (d['kind'] === 'never-invoked' && longEnough));
  });
}

function item(f: FindingDict): string {
  if (f.kind === 'never-invoked' && f.skills.length) return `${f.skills[0]} ${USAGE_DAYS} days without a call`;
  return `${f.kind}: ${f.skills.length ? f.skills.join(', ') : f.detail}`;
}

/** Python's `render_line`: whole items while they fit; a first item that cannot is clipped. */
export function renderLine(items: string[]): string {
  const head = `[bantamkit] skill audit: ${items.length} new — `;
  const room = LINE_MAX_BYTES - bytes(head) - bytes(TAIL);
  let body = '';
  for (const [i, it] of items.entries()) {
    const left = items.length - i - 1;
    const more = left ? `; +${left} more` : '';
    const cand = body ? `${body}; ${it}` : it;
    if (bytes(cand + more) <= room) {
      body = cand;
      continue;
    }
    body = body ? `${body}; +${items.length - i} more` : clip(it, room - bytes(more)) + more;
    break;
  }
  return head + body + TAIL;
}

/**
 * One line for SessionStart, only for what `surfaced` has not seen (K1). null — and no write —
 * when nothing is new, so SessionStart adds 0 bytes. Otherwise the shown keys join `surfaced`
 * under the lock, if the record is still the one read (same `ts`). Never throws.
 * `BANTAMKIT_SKILL_AUDIT=off` silences it: null, nothing written, whatever the record holds.
 */
export function sessionLine(home: string): string | null {
  try {
    if (!auditEnabled()) return null;
    const record = readState(home);
    if (record === null || 'error' in record) return null;
    const shown = new Set(record.surfaced);
    const fresh = surfaceable(record).filter((f) => !shown.has(surfaceKey(f)));
    if (!fresh.length) return null;
    const line = renderLine(fresh.map(item));
    const p = statePath(home);
    exclusive(p, (held) => {
      if (!held) return;
      const again = readState(home);
      if (again !== null && !('error' in again) && again.ts === record.ts) {
        const keys = new Set([...again.surfaced, ...fresh.map((f) => surfaceKey(f))]);
        again.surfaced = [...keys].sort(cmpCodepoint);
        writeRecord(p, again);
      }
    });
    return line;
  } catch {
    return null;
  }
}
