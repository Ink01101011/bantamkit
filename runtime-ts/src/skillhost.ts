/**
 * Where the skill audit's host facts come from (#205, K3). Port of
 * `runtime-py/src/bantamkit/skillhost.py`, whose docstring carries the contract;
 * `tools/conformance/suites/skill-host.mjs` compares the two.
 *
 * `skillaudit` reads nothing from the machine, on purpose. This module is the layer that reads:
 * an ADAPTER answers `Gathered` — the skill roots, the switched-on plugins, the served version
 * directories and the call counts. Read-only: nothing here writes, and nothing here ever writes
 * under `~/.claude`.
 *
 * TWO SHAPES OF A CALL (Amendment A2): a `Skill` `tool_use` block, and a non-meta `type: "user"`
 * record whose string content carries `<command-name>/<name></command-name>`, counted only when
 * `<name>` is a skill the roots hold (built-in commands use the same record).
 *
 * THE POINTS A PORT GETS WRONG, each held here: the transcript is searched as BYTES, never
 * decoded whole; a candidate line is decoded with a FATAL decoder that KEEPS a leading U+FEFF
 * (`ignoreBOM: true`), so a BOM line is refused as Python's `json.loads` refuses it; the walk
 * never descends a symlinked directory and treats a symlink to a file as a file, as `os.walk`
 * does; mtime is `st_mtime_ns // 1_000_000`.
 */
import fs from 'node:fs';
import path from 'node:path';

import { cmpCodepoint } from './pysem.js';
import { parseNow } from './storage/retention.js';
import { settingsPaths } from './storage/tiers.js';

export const HOST_CLAUDE_CODE = 'claude-code';
export const HOST_NONE = 'none';
export const USAGE_DAYS = 30;
export const DAY_MS = 86_400_000;
export const SKILL_TOOL = 'Skill';
export const SKILL_FILE = 'SKILL.md';
/** `<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md`, as `skillaudit` reads it. */
const PLUGIN_PATH_SEGMENTS = 6;
const SKILLS_SEGMENT = 'skills';
const NEEDLE = Buffer.from('"Skill"', 'utf8');
const TOOL_USE = Buffer.from('"tool_use"', 'utf8');
const COMMAND = Buffer.from('<command-name>', 'utf8');
const COMMAND_NAME = /<command-name>\/([^<]*)<\/command-name>/;
const NL = 0x0a;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const own = (o: Obj, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);

const STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

/** `JSON.parse` over strict UTF-8; `null` on any failure (Python `_read_json`). */
function readJson(p: string): unknown {
  try {
    return JSON.parse(STRICT.decode(fs.readFileSync(p)));
  } catch {
    return null;
  }
}

/** `os.path.realpath`; `path.resolve` for a path that does not exist (Python never throws). */
function real(p: string): string {
  try {
    return fs.realpathSync.native(p);
  } catch {
    return path.resolve(p);
  }
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

export interface UsageSummary {
  calls: number;
  counts: Record<string, number>;
  span_days: number;
  transcripts: number;
  unreadable: number;
  skipped_lines: number;
}

export class UsageScan {
  constructor(
    readonly counts: ReadonlyMap<string, number>,
    readonly spanDays: number,
    readonly transcripts: number,
    readonly unreadable: number,
    readonly skippedLines: number,
  ) {}

  summary(): UsageSummary {
    const entries = [...this.counts.entries()].sort(([x], [y]) => cmpCodepoint(x, y));
    let calls = 0;
    for (const [, n] of entries) calls += n;
    return {
      calls,
      // `fromEntries` DEFINES each key, so a skill named `__proto__` is a key, not a prototype.
      counts: Object.fromEntries(entries),
      span_days: this.spanDays,
      transcripts: this.transcripts,
      unreadable: this.unreadable,
      skipped_lines: this.skippedLines,
    };
  }
}

export interface GatheredDict {
  enabled: string[];
  host: string;
  roots: [string, string][];
  sources: Record<string, string>;
  usage: UsageSummary | null;
  versions: Record<string, string> | null;
}

const sortedRecord = (r: Record<string, string> | ReadonlyMap<string, string>): Record<string, string> =>
  Object.fromEntries((r instanceof Map ? [...r.entries()] : Object.entries(r)).sort(([x], [y]) => cmpCodepoint(x, y)));

export class Gathered {
  constructor(
    readonly host: string,
    readonly roots: readonly (readonly [string, string])[] = [],
    readonly enabled: readonly string[] = [],
    readonly versions: Record<string, string> | null = null,
    readonly sources: Record<string, string> = {},
    readonly usage: UsageScan | null = null,
  ) {}

  asDict(): GatheredDict {
    return {
      enabled: [...this.enabled],
      host: this.host,
      roots: this.roots.map(([l, p]) => [l, p]),
      sources: sortedRecord(this.sources),
      usage: this.usage === null ? null : this.usage.summary(),
      versions: this.versions === null ? null : sortedRecord(this.versions),
    };
  }
}

/**
 * `os.walk(root)` in sorted order: yields `[dir as path parts under root, file names]`. A
 * directory is descended only when it is not a symlink; an entry whose `stat` (following a
 * link) is not a directory is a file name, as `os.scandir().is_dir()` decides it. A directory
 * that cannot be listed is skipped (`onerror=None`).
 */
function* walk(root: string): Generator<[string[], string[]]> {
  const pending: string[][] = [[]];
  while (pending.length > 0) {
    const rel = pending.shift()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(path.join(root, ...rel), { withFileTypes: true });
    } catch {
      continue;
    }
    const dirs: string[] = [];
    const files: string[] = [];
    for (const entry of entries) {
      const link = entry.isSymbolicLink();
      let directory = entry.isDirectory();
      if (link) directory = isDir(path.join(root, ...rel, entry.name));
      if (directory) {
        if (!link) dirs.push(entry.name);
      } else {
        files.push(entry.name);
      }
    }
    dirs.sort(cmpCodepoint);
    files.sort(cmpCodepoint);
    yield [rel, files];
    // Depth first, in sorted order, as `os.walk` (topdown) visits.
    pending.unshift(...dirs.map((d) => [...rel, d]));
  }
}

export function jsonlFiles(root: string): string[] {
  const out: string[] = [];
  for (const [rel, files] of walk(root)) {
    for (const f of files) if (f.endsWith('.jsonl')) out.push(path.join(root, ...rel, f));
  }
  return out;
}

/** Every skill id the roots hold, spelled as `skillaudit` spells a skill's `id`. */
export function knownSkills(roots: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const root of roots) {
    for (const [rel, files] of walk(root)) {
      if (!files.includes(SKILL_FILE)) continue;
      const parts = [...rel, SKILL_FILE];
      const directory = parts.length > 1 ? parts[parts.length - 2]! : path.basename(root);
      if (parts.length === PLUGIN_PATH_SEGMENTS && parts[3] === SKILLS_SEGMENT) out.add(`${parts[1]}:${directory}`);
      else out.add(directory);
    }
  }
  return out;
}

/** Each line that can hold a call, once: `"Skill"` with `"tool_use"`, or `<command-name>`. */
function* candidateLines(data: Buffer): Generator<Buffer> {
  let i = 0;
  let a = data.indexOf(NEEDLE);
  let b = data.indexOf(COMMAND);
  for (;;) {
    if (a >= 0 && a < i) a = data.indexOf(NEEDLE, i);
    if (b >= 0 && b < i) b = data.indexOf(COMMAND, i);
    if (a < 0 && b < 0) return;
    const j = a < 0 ? b : b < 0 ? a : Math.min(a, b);
    // Python `rfind(b"\n", 0, j)`: the last newline strictly before j. `lastIndexOf` with a
    // NEGATIVE offset counts from the end, so j === 0 is answered without it.
    const start = j === 0 ? 0 : data.lastIndexOf(NL, j - 1) + 1;
    let end = data.indexOf(NL, j);
    if (end < 0) end = data.length;
    const line = data.subarray(start, end);
    if (line.includes(COMMAND) || (line.includes(NEEDLE) && line.includes(TOOL_USE))) yield line;
    i = end + 1;
  }
}

function tsMs(value: unknown): number | null {
  try {
    return parseNow(value);
  } catch {
    return null;
  }
}

/** The skill a typed `/<name>` invoked, or null (Python `_command`). */
function command(rec: Obj, known: ReadonlySet<string>): string | null {
  if (own(rec, 'type') !== 'user' || own(rec, 'isMeta') === true) return null;
  const message = own(rec, 'message');
  const content = isObj(message) ? own(message, 'content') : undefined;
  if (typeof content !== 'string') return null;
  const m = COMMAND_NAME.exec(content);
  if (m === null || !known.has(m[1]!)) return null;
  return m[1]!;
}

/** `tool-usage.mjs --group skill --since <days>d --no-events`, ported (Python `count_skill_usage`). */
export function countSkillUsage(
  projects: string,
  nowMs: number,
  days: number = USAGE_DAYS,
  known: ReadonlySet<string> | null = null,
): UsageScan {
  const cutoff = nowMs - days * DAY_MS;
  const counts = new Map<string, number>();
  const seen = new Set<string>();
  const seenCommands = new Set<string>();
  let oldest: number | null = null;
  let transcripts = 0;
  let unreadable = 0;
  let skipped = 0;
  const bump = (skill: string): void => {
    counts.set(skill, (counts.get(skill) ?? 0) + 1);
  };
  for (const p of jsonlFiles(projects)) {
    let mtimeMs: number;
    try {
      mtimeMs = Number(fs.statSync(p, { bigint: true }).mtimeNs / 1_000_000n);
    } catch {
      unreadable += 1;
      continue;
    }
    if (mtimeMs < cutoff) {
      oldest = oldest === null ? mtimeMs : Math.min(oldest, mtimeMs);
      continue;
    }
    let data: Buffer;
    try {
      data = fs.readFileSync(p);
    } catch {
      unreadable += 1;
      continue;
    }
    transcripts += 1;
    for (const line of candidateLines(data)) {
      let rec: unknown;
      try {
        rec = JSON.parse(STRICT.decode(line));
      } catch {
        skipped += 1;
        continue;
      }
      if (!isObj(rec)) continue;
      const ts = tsMs(own(rec, 'timestamp'));
      if (ts !== null) {
        oldest = oldest === null ? ts : Math.min(oldest, ts);
        if (ts < cutoff) continue;
      }
      if (known !== null) {
        const typed = command(rec, known);
        if (typed !== null) {
          const uid = own(rec, 'uuid');
          if (!(typeof uid === 'string' && uid)) {
            bump(typed);
          } else if (!seenCommands.has(uid)) {
            seenCommands.add(uid);
            bump(typed);
          }
        }
      }
      const message = own(rec, 'message');
      const content = isObj(message) ? own(message, 'content') : undefined;
      if (!Array.isArray(content)) continue;
      for (const block of content) {
        if (!isObj(block)) continue;
        if (own(block, 'type') !== 'tool_use' || own(block, 'name') !== SKILL_TOOL) continue;
        const bid = own(block, 'id');
        if (typeof bid === 'string' && bid) {
          if (seen.has(bid)) continue;
          seen.add(bid);
        }
        const given = own(block, 'input');
        const skill = isObj(given) ? own(given, 'skill') : undefined;
        if (typeof skill === 'string' && skill) bump(skill);
      }
    }
  }
  const span = oldest === null ? 0 : Math.max(0, Math.min(days, Math.floor((nowMs - oldest) / DAY_MS)));
  return new UsageScan(counts, span, transcripts, unreadable, skipped);
}

function enabledPlugins(home: string, cwd: string | null): [string[], Record<string, string>] {
  const won = new Map<string, [boolean, string]>();
  for (const f of settingsPaths(home, cwd)) {
    const doc = readJson(f);
    const plugins = isObj(doc) ? own(doc, 'enabledPlugins') : undefined;
    if (!isObj(plugins)) continue;
    for (const [pid, on] of Object.entries(plugins)) {
      if (typeof on === 'boolean') won.set(pid, [on, f]);
    }
  }
  const ids = [...won.entries()].filter(([, [v]]) => v).map(([pid]) => pid).sort(cmpCodepoint);
  return [ids, Object.fromEntries(ids.map((pid) => [pid, won.get(pid)![1]]))];
}

function installedVersions(home: string, cwd: string | null): Record<string, string> | null {
  const doc = readJson(path.join(home, '.claude', 'plugins', 'installed_plugins.json'));
  const plugins = isObj(doc) ? own(doc, 'plugins') : undefined;
  if (!isObj(plugins)) return null;
  const here = cwd !== null ? real(cwd) : null;
  const out = new Map<string, string>();
  for (const [pid, value] of Object.entries(plugins)) {
    const entries = isObj(value) ? [value] : value;
    if (!Array.isArray(entries)) continue;
    let project: string | null = null;
    let other: string | null = null;
    for (const e of entries) {
      if (!isObj(e) || typeof own(e, 'installPath') !== 'string') continue;
      const installPath = own(e, 'installPath') as string;
      if (own(e, 'scope') === 'project') {
        const where = own(e, 'projectPath');
        if (project === null && here !== null && typeof where === 'string' && real(where) === here) project = installPath;
      } else if (other === null) {
        other = installPath;
      }
    }
    const chosen = project || other;
    const name = chosen ? chosen.replace(/[\\/]+$/, '').split(/[\\/]/).pop()! : '';
    if (name) out.set(pid, name);
  }
  return sortedRecord(out);
}

export interface Adapter {
  readonly host: string;
  gather(home: string, cwd: string | null, nowMs: number): Gathered;
}

export class NullAdapter implements Adapter {
  readonly host = HOST_NONE;

  gather(_home: string, _cwd: string | null, _nowMs: number): Gathered {
    return new Gathered(HOST_NONE);
  }
}

export class ClaudeCodeAdapter implements Adapter {
  readonly host = HOST_CLAUDE_CODE;

  /** Roots in the order `plugins, project, user` (Amendment A1: the personal copy wins). */
  gather(home: string, cwd: string | null, nowMs: number): Gathered {
    const claude = path.join(home, '.claude');
    const user = path.join(claude, 'skills');
    const candidates: [string, string][] = [['plugins', path.join(claude, 'plugins', 'cache')]];
    if (cwd !== null) {
      const project = path.join(cwd, '.claude', 'skills');
      if (real(project) !== real(user)) candidates.push(['project', project]);
    }
    candidates.push(['user', user]);
    const roots = candidates.filter(([, p]) => isDir(p));
    const [enabled, sources] = enabledPlugins(home, cwd);
    // job73 C15 (#206 Component 7): a typed `/<name>` of a skill bantamkit promoted by symlink
    // names a directory under `.bantamkit/skills` (the walk never follows the link), so those
    // roots' names are known too; the audit reads them as roots of its own (`skillreport`).
    const own = [...(cwd !== null ? [path.join(cwd, '.bantamkit', 'skills')] : []), path.join(home, '.bantamkit', 'skills')];
    const known = knownSkills([...roots.map(([, p]) => p), ...own.filter(isDir)]);
    return new Gathered(
      HOST_CLAUDE_CODE,
      roots,
      enabled,
      installedVersions(home, cwd),
      sources,
      countSkillUsage(path.join(claude, 'projects'), nowMs, USAGE_DAYS, known),
    );
  }
}

export function selectAdapter(home: string): Adapter {
  return isDir(path.join(home, '.claude')) ? new ClaudeCodeAdapter() : new NullAdapter();
}
