/**
 * Reply-native (#292): think in English, reply in the user's language. Port of
 * `runtime-py/src/bantamkit/replynative.py`; every regex is written to mean the same thing in
 * Python `re` (no `\w`, `\b`, `\s`, `$`). Lengths are code points, never UTF-16 units.
 */
import * as fs from 'node:fs';
import { join } from 'node:path';

import { AssetNotFound, loadLang } from './assets.js';
import { pyStrip } from './pysem.js';

export const NATIVE_ENV = 'BANTAMKIT_REPLY_NATIVE';
export const LANG_ENV = 'BANTAMKIT_REPLY_LANG';
export const CORE_MAX = 600;
export const PACK_MAX = 450;
export const INJECT_MAX = 1050;
export const RAW_LANG_MAX = 32;
export const STATE_FILE = 'reply-native.json';
const ON = new Set(['on', '1', 'true', 'yes']);
const ISO = /^[a-z]{2}$/;

// Every pattern below is linear: a scan that can fail stops at the next opening character
// (`[^<>]`, `[^“”]`, ...) or is bounded (`{0,31}`), so a long unbroken token or a run of opening
// quotes cannot make frame() quadratic (g1, 0.39.0 release gate).
const END = '(?![\\s\\S])';
const STRIP: RegExp[] = [
  new RegExp(`<(pasted_content|ide_[a-z_]+|system-reminder)[^<>]*>[\\s\\S]*?(?:</\\1>|${END})`, 'g'),
  new RegExp(`\`\`\`[\\s\\S]*?(?:\`\`\`|${END})`, 'g'),
  /`[^`\n]*`/g,
  /[A-Za-z][A-Za-z0-9+.-]{0,31}:\/\/[^ \t\r\n]+/g,
  /(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}\\)[^ \t\r\n"'<>|]+/g,
  /(?:~|\.{1,2})?\/[^ \t\r\n"'<>|]+/g,
  /"[^"\n]*"|“[^“”\n]*”|'[^'\n]{2,}'|「[^「」\n]*」|『[^『』\n]*』/g,
];
const BLANK = /^[ \t\r\n]*$/;
const THAI = /[\u0E01-\u0E2E]/;
const KANA = /[\u3040-\u309F\u30A0-\u30FF]/;

export interface ReplyMode {
  kind: 'off' | 'latest' | 'fixed';
  lang: string | null;
  rawLang: string | null;
  reason: string | null;
}

export interface ReplyPlan {
  parts: string[];
  text: string;
  reason: string | null;
}

// Python's `str.strip()`, not JS `trim()`: the two strip different whitespace (U+0085, U+001F,
// U+FEFF), and one env value must give one mode on both runtimes.
const lower = (s: string): string => pyStrip(s).toLowerCase();

export function mode(env: Record<string, string | undefined>): ReplyMode {
  if (!ON.has(lower(env[NATIVE_ENV] ?? ''))) return { kind: 'off', lang: null, rawLang: null, reason: null };
  const raw = env[LANG_ENV];
  if (raw === undefined || BLANK.test(raw)) return { kind: 'latest', lang: null, rawLang: null, reason: null };
  const norm = lower(raw);
  if (ISO.test(norm)) return { kind: 'fixed', lang: norm, rawLang: null, reason: null };
  return { kind: 'latest', lang: null, rawLang: [...raw].slice(0, RAW_LANG_MAX).join(''), reason: 'invalid-lang' };
}

export function frame(prompt: string): string {
  let out = prompt;
  for (const rx of STRIP) out = out.replace(rx, ' ');
  return BLANK.test(out) ? prompt : out;
}

export function classify(prompt: string): 'th' | 'ja' | null {
  const f = frame(prompt);
  if (THAI.test(f)) return 'th';
  if (KANA.test(f)) return 'ja';
  return null;
}

function pack(lang: string): string | null {
  try {
    return loadLang(lang);
  } catch (e) {
    if (e instanceof AssetNotFound) return null;
    throw e;
  }
}

const empty = (reason: string | null = null): ReplyPlan => ({ parts: [], text: '', reason });

export function plan(m: ReplyMode, lang: string | null, seen: Iterable<string>): ReplyPlan {
  if (m.kind === 'off' || lang === null) return empty();
  if (m.kind === 'fixed' && lang === 'en') return empty('english');
  let core: string;
  try {
    core = loadLang(m.kind === 'fixed' ? 'core-fixed' : 'core-latest');
  } catch (e) {
    if (e instanceof AssetNotFound) return empty('asset-missing');
    throw e;
  }
  if (m.kind === 'fixed') core = core.split('{lang}').join(lang);
  const p = pack(lang);
  if (m.kind === 'latest' && p === null) return empty('asset-missing');
  if (Buffer.byteLength(core) > CORE_MAX || (p !== null && Buffer.byteLength(p) > PACK_MAX)) return empty('over-budget');
  const have = new Set(seen);
  const parts: string[] = [];
  const texts: string[] = [];
  if (!have.has('core')) {
    parts.push('core');
    texts.push(core);
  }
  if (p !== null && !have.has(lang)) {
    parts.push(lang);
    texts.push(p);
  }
  const text = texts.join('\n');
  if (Buffer.byteLength(text) > INJECT_MAX) return empty('over-budget');
  return { parts, text, reason: null };
}

/** The `reply-native:` line of `bantamkit_status`. Never throws. */
export function statusLine(home: string): string {
  const path = join(home, '.bantamkit', 'hooks', STATE_FILE);
  try {
    let exists = true;
    try {
      fs.lstatSync(path);
    } catch {
      exists = false;
    }
    if (!exists) return 'reply-native: off';
    const rec = JSON.parse(fs.readFileSync(path, 'utf8')) as Record<string, unknown>;
    for (const k of ['mode', 'event', 'ts', 'parts', 'bytes']) if (!(k in rec)) throw new Error(k);
    const parts = rec.parts as string[];
    const head = `reply-native: ${String(rec.mode)}` + (rec.mode === 'fixed' ? ` ${String(rec.lang)}` : '');
    const what = parts.length
      ? `injected ${parts.join('+')} (${String(rec.bytes)} bytes)`
      : `nothing injected (${(rec.reason as string | null | undefined) || 'nothing to inject'})`;
    const tail = rec.rawLang !== undefined && rec.rawLang !== null ? `; ${LANG_ENV}=${String(rec.rawLang)} invalid, fell back to latest` : '';
    return `${head}; last ${String(rec.event)} at ${String(rec.ts)}: ${what}${tail}`;
  } catch {
    return 'reply-native: the last record is unreadable';
  }
}
