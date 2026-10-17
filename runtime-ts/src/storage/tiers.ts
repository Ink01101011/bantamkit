/**
 * Capability tiers and the storage lines `bantamkit_status` prints (#204, S2; job69 J69-7).
 * Port of `runtime-py/src/bantamkit/storage/tiers.py`, whose docstring carries the contract;
 * `tools/conformance/suites/storage-tiers.mjs` compares the two over an MCP-only host profile.
 *
 * THREE TIERS. (1) **core** needs only an MCP client and is always on. (2) **hook** is on when
 * a host settings file carries one of bantamkit's own hooks, read the way `hostinstall` reads
 * them: `~/.claude/settings.json`, plus the project's `.claude/settings.json` and
 * `.claude/settings.local.json` under `cwd`. (3) **host data** is on when the native resolver
 * (RULING Q1.2, without the transcript branch only a hook receives) answers a directory. Tiers
 * 2 and 3 are absent SILENTLY: nothing here throws, and nothing here runs on a tool's hot path.
 */
import fs from 'node:fs';
import path from 'node:path';

import { nativeMemoryDir } from '../hookadapter.js';
import { hasBantamkitHooks } from '../hostinstall.js';
import type { Memory } from '../memory/component.js';
import type { MemoryStore } from '../memory/store.js';
import { parseJson } from '../pyjson.js';
import { FAMILIES, SHARDS } from './hotindex.js';
import { LogSegment } from './logsegment.js';
import { enabled, statePath } from './retention.js';

export interface Tiers {
  core: true;
  hook: boolean;
  host_data: boolean;
}

const plural = (count: number, word: string): string => (count === 1 ? `${count} ${word}` : `${count} ${word}s`);

/**
 * The settings files a hook can be registered in: user scope, then the project's two. `cwd` is
 * `null` when the process has none (a deleted working directory, job48): user scope only.
 */
export function settingsPaths(home: string, cwd: string | null): string[] {
  const paths = [path.join(home, '.claude', 'settings.json')];
  if (cwd !== null) {
    const project = path.join(cwd, '.claude');
    paths.push(path.join(project, 'settings.json'), path.join(project, 'settings.local.json'));
  }
  return paths;
}

/** `process.cwd()`, or `null` when the working directory is gone. Never throws. */
export function currentCwd(): string | null {
  try {
    return process.cwd();
  } catch {
    return null;
  }
}

export function hookTier(home: string, cwd: string | null): boolean {
  return settingsPaths(home, cwd).some((p) => hasBantamkitHooks(p));
}

export function hostDataTier(home: string): boolean {
  try {
    return nativeMemoryDir(home) !== null;
  } catch {
    return false; // a tier that cannot be probed is a tier that is off
  }
}

/** `{core: true, hook, host_data}`. Never throws. */
export function tiers(home: string, cwd: string | null): Tiers {
  return { core: true, hook: hookTier(home, cwd), host_data: hostDataTier(home) };
}

const on = (flag: boolean): string => (flag ? 'on' : 'off');

export function tierLine(found: Tiers): string {
  return `storage: core ${on(found.core)}; hooks ${on(found.hook)}; host data ${on(found.host_data)}`;
}

/** `dir`, `file`, or `''` — the reference's `_kind`, from one `stat`. */
function kindOf(p: string): string {
  try {
    const st = fs.statSync(p);
    return st.isDirectory() ? 'dir' : st.isFile() ? 'file' : '';
  } catch {
    return '';
  }
}

function sizeOf(p: string): number {
  try {
    return fs.statSync(p).size;
  } catch {
    return 0;
  }
}

/** One line per memory layer whose `facts/` is a directory, refreshed as recall would. */
export function indexLines(memory: Memory): string[] {
  const layers = memory['layers'] as ReadonlyArray<readonly [string, MemoryStore, boolean]>;
  const out: string[] = [];
  for (const [label, store] of layers) {
    if (kindOf(path.join(store.root, 'facts')) !== 'dir') continue;
    const kind = label.split(':')[0]!;
    let docs: number;
    let idx;
    try {
      idx = store.index();
      idx.refresh('fast');
      docs = idx.names().size;
    } catch {
      out.push(`index facts ${kind}: unreadable`);
      continue;
    }
    const files = [idx.path];
    for (const family of FAMILIES) for (let i = 0; i < SHARDS; i += 1) files.push(idx.shardPath(family, i));
    const held = files.reduce((sum, p) => sum + sizeOf(p), 0);
    out.push(`index facts ${kind}: ${plural(docs, 'doc')}, ${held} bytes, ${idx.persisted ? 'persisted' : 'in-memory'}`);
  }
  return out;
}

function logs(base: string): Array<[string, string]> {
  const found: Array<[string, string]> = [['hook-log', path.join(base, 'hooks', 'hook-log.jsonl')]];
  let names: string[] = [];
  try {
    names = fs.readdirSync(path.join(base, 'usage')).sort();
  } catch {
    /* no usage ledgers */
  }
  for (const n of names) {
    if (n.endsWith('.jsonl')) found.push([`usage/${n.slice(0, -'.jsonl'.length)}`, path.join(base, 'usage', n)]);
  }
  let touched: string[] = [];
  try {
    touched = fs.readdirSync(path.join(base, 'touch')).sort();
  } catch {
    /* no touch logs (#200) */
  }
  for (const n of touched) {
    if (n.endsWith('.jsonl')) found.push([`touch/${n.slice(0, -'.jsonl'.length)}`, path.join(base, 'touch', n)]);
  }
  return found;
}

export function logLines(home: string): string[] {
  const out: string[] = [];
  for (const [name, p] of logs(path.join(home, '.bantamkit'))) {
    const seg = new LogSegment(p);
    const segments = seg.segments();
    if (kindOf(p) !== 'file' && segments.length === 0) continue;
    const held = sizeOf(p) + segments.reduce((sum, s) => sum + sizeOf(s), 0);
    seg.read();
    out.push(`logs: ${name} ${held} (${segments.length} rotated, ${seg.skipped} skipped)`);
  }
  return out.length > 0 ? out : ['logs: none'];
}

/**
 * `touch: none`, or how many touch-log writes the hook log records as missed (#200). `none`
 * only when there is no touch directory AND no miss: a miss is most often exactly a touch
 * directory that could not be made, and `none` would hide it.
 */
export function touchLine(home: string): string {
  const base = path.join(home, '.bantamkit');
  const misses = new LogSegment(path.join(base, 'hooks', 'hook-log.jsonl')).read().filter((r) => r['touch'] === 'miss').length;
  if (misses === 0 && kindOf(path.join(base, 'touch')) !== 'dir') return 'touch: none';
  return `touch: ${plural(misses, 'missed write')} (hook log)`;
}

const STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

export function retentionLine(home: string): string {
  let ran = 'never';
  let refused = 0;
  try {
    // `parseJson` is `json.loads`, so a record the reference reads, this reads the same.
    const data = parseJson(STRICT.decode(fs.readFileSync(statePath(home))));
    if (data.t === 'dict') {
      const at = data.v.get('ran_at');
      if (at !== undefined && at.t === 'str') ran = at.v;
      const report = data.v.get('report');
      if (report !== undefined && report.t === 'dict') {
        const list = report.v.get('refused');
        if (list !== undefined && list.t === 'list') refused = list.v.length;
      }
    }
  } catch {
    /* absent, unreadable, not UTF-8, not JSON: never ran, as far as this can tell */
  }
  return `retention: ${enabled() ? '' : 'off; '}last ran ${ran}; refused ${refused}`;
}

/** Every storage line of `bantamkit_status`, in order. Never throws. */
export function statusLines(memory: Memory, home: string, cwd: string | null): string[] {
  return [tierLine(tiers(home, cwd)), ...indexLines(memory), ...logLines(home), touchLine(home), retentionLine(home)];
}
