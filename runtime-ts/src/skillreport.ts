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
import { auditRoots, scanRoots } from './skillaudit.js';
import type { FindingDict, LabelledRoot, OmissionDict, ScannedSkill } from './skillaudit.js';
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
export function buildRecord(g: Gathered, now: string): SkillRecord {
  if (g.roots.length === 0) return errorRecord(now, g.host, NO_ROOTS);
  const roots: LabelledRoot[] = g.roots.map(([label, path]) => ({ label, path }));
  const counts = g.usage === null ? null : g.usage.counts;
  const versions = g.versions === null ? null : new Map(Object.entries(g.versions));
  const found = scanRoots(roots, [...g.enabled], versions);
  const result = auditRoots(roots, { enabled: [...g.enabled], usage: counts, versions });
  const span = g.usage === null ? 0 : g.usage.spanDays;
  return {
    version: STATE_VERSION,
    ts: now,
    host: g.host,
    roots: g.roots.map(([l, p]) => [l, p]),
    skills: result.skills,
    catalogue_bytes: result.catalogueBytes,
    findings: result.findings.map((f) => f.asDict()),
    omissions: result.omissions.map((o) => o.asDict()),
    usage: g.usage === null ? null : g.usage.summary(),
    proposals: propose(found, counts, span, g.sources),
    surfaced: [],
  };
}

/** Gather and audit now. Never throws: a failure is the error record (spec, "Gather fails"). */
export function runLive(home: string, cwd: string | null, now: string): SkillRecord {
  let host = HOST_NONE;
  try {
    const adapter = skillreportDeps.selectAdapter(home);
    host = adapter.host;
    return buildRecord(adapter.gather(home, cwd, parseNow(now)), now);
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
  lines.push(`findings: ${sev.get('high') ?? 0} high, ${sev.get('medium') ?? 0} medium, ${sev.get('low') ?? 0} low`);
  for (const f of record.findings) {
    const who = f.skills.length > 0 ? f.skills.join(', ') : 'the catalogue';
    lines.push(`- ${f.severity} ${f.kind}: ${who} — ${f.detail}`);
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
