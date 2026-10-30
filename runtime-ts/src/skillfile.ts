/**
 * The Agent Skills file (#206, X9): parse, validate, hash, render, atomic write, undo.
 *
 * Port of `runtime-py/src/bantamkit/skillfile.py`; the module docstring there is the design
 * note (the directory shape, the hash reading R8, why one refusal sentence covers every
 * unreadable frontmatter). `tools/conformance/suites/skill-file.mjs` compares the two.
 *
 * Every count here is in CODE POINTS (`[...s].length`), never UTF-16 units or bytes, and
 * every sort is by code point (`cmpCodepoint`), because Python's `len` and `sorted` are.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { FactParseError, parseFrontmatter, wellFormed } from './memory/factfile.js';
import { PyScalar } from './memory/pyyaml.js';
import { dumpJson, fromJs, parseJson, toJs, type PyValue } from './pyjson.js';
import { cmpCodepoint, pyRepr, pyStrip } from './pysem.js';
import { exclusive } from './storage/lock.js';
import { parseNow } from './storage/retention.js';

export const NAME_MAX = 64;
export const DESC_MAX = 1024;
export const BODY_MAX_LINES = 500;
export const GENERIC_NAMES: readonly string[] = ['helper', 'helpers', 'util', 'utils'];
export const HASH_KEY = 'bantamkit-sha256';
export const KEY_PREFIX = 'bantamkit-';
export const SKILL_FILE = 'SKILL.md';
export const ABSENT_MARKER = '.bantamkit-absent';
export const STATE_NAME = 'skills-state.json';
export const STATE_VERSION = 1;

const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const KEY_RE = /^[A-Za-z_][A-Za-z0-9_-]*$/;
const PLAIN_WORDS: readonly string[] = ['yes', 'no', 'on', 'off', 'true', 'false', 'null'];
const HASH_LINE = /^[ \t]*bantamkit-sha256:/;
const HEADING_BREAK = /^#{1,2}(?:[ \t]|$)/;
const BACKUP_NAME = /^(\d{8}T\d{6}\.\d{3}Z)(?:-(\d+))?$/;

/** One counter per process: a temp name is `<target>.<kind>-<pid>-<n>`, never random. */
let counter = 0;

export class SkillFileError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SkillFileError';
  }
}

/** A metadata value as the frontmatter reader produced it; `validate` judges it. */
export type MetaValue = unknown;

export interface SkillDoc {
  name: string;
  description: string;
  metadata: Record<string, MetaValue>;
  body: string;
}

const cpLen = (s: string): number => [...s].length;
const lf = (s: string): string => s.split('\r\n').join('\n');

function isMapping(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof PyScalar);
}

/** `well_formed_value` over a metadata value the store's reader left nested (#212). */
function wellFormedDeep(v: unknown): unknown {
  if (typeof v === 'string') return wellFormed(v);
  if (Array.isArray(v)) return v.map(wellFormedDeep);
  if (isMapping(v)) {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) out[wellFormed(k)] = wellFormedDeep(x);
    return out;
  }
  return v;
}

// ---------------------------------------------------------------------------- parse

export function parseSkill(text: string): SkillDoc {
  text = lf(text);
  if (text.startsWith('﻿')) text = text.slice(1);
  const parts = splitFront(text);
  if (parts === null || parts[0] !== '') {
    throw new SkillFileError('SKILL.md has no frontmatter at the top of the file');
  }
  let meta: Record<string, unknown>;
  try {
    meta = parseFrontmatter(parts[1]) as Record<string, unknown>;
  } catch (e) {
    if (e instanceof FactParseError) throw new SkillFileError('SKILL.md frontmatter is not a readable mapping');
    throw e;
  }
  const name = meta.name;
  if (typeof name !== 'string') throw new SkillFileError('SKILL.md has no string name');
  let description = meta.description;
  if (description === undefined || description === null) description = '';
  if (typeof description !== 'string') throw new SkillFileError('SKILL.md description is not a string');
  let metadata = meta.metadata;
  if (metadata === undefined || metadata === null) metadata = {};
  if (!isMapping(metadata)) throw new SkillFileError('SKILL.md metadata is not a mapping');
  const md: Record<string, MetaValue> = {};
  for (const [k, v] of Object.entries(metadata)) md[k] = wellFormedDeep(v);
  return { name, description, metadata: md, body: pyStrip(parts[2]) };
}

/** `text.split("---\n", 2)` when it yields three parts, else null. */
function splitFront(text: string): [string, string, string] | null {
  const a = text.indexOf('---\n');
  if (a === -1) return null;
  const b = text.indexOf('---\n', a + 4);
  if (b === -1) return null;
  return [text.slice(0, a), text.slice(a + 4, b), text.slice(b + 4)];
}

export function bodyLines(body: string): number {
  return body === '' ? 0 : body.split('\n').length;
}

export function hasSteps(body: string): boolean {
  const lines = body.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i]!.replace(/[ \t]+$/, '') !== '## Steps') continue;
    for (const nxt of lines.slice(i + 1)) {
      if (HEADING_BREAK.test(nxt)) return false;
      if (nxt.replace(/^[ \t]+|[ \t]+$/g, '') !== '') return true;
    }
    return false;
  }
  return false;
}

export function validate(doc: SkillDoc, dirname: string | null = null): string[] {
  const out: string[] = [];
  const name = doc.name;
  if (cpLen(name) > NAME_MAX || !NAME_RE.test(name)) {
    out.push(`name ${pyRepr(name)} must be 1-${NAME_MAX} characters of a-z, 0-9 and single inner hyphens`);
  } else if (GENERIC_NAMES.includes(name)) {
    out.push(`name ${pyRepr(name)} is a generic word; name the action instead`);
  }
  if (dirname !== null && dirname !== name) {
    out.push(`name ${pyRepr(name)} does not match its directory ${pyRepr(dirname)}`);
  }
  const d = cpLen(doc.description);
  if (d > DESC_MAX) out.push(`description is ${d} characters; at most ${DESC_MAX}`);
  const n = bodyLines(doc.body);
  if (n > BODY_MAX_LINES) out.push(`body is ${n} lines; at most ${BODY_MAX_LINES}`);
  for (const key of Object.keys(doc.metadata).sort(cmpCodepoint)) {
    if (typeof doc.metadata[key] !== 'string') out.push(`metadata ${key} must be a string`);
  }
  if (!hasSteps(doc.body)) out.push('## Steps is missing or empty');
  return out;
}

// ----------------------------------------------------------------------------- hash

export function canonicalHash(text: string): string {
  text = wellFormed(lf(text));
  const parts = splitFront(text);
  if (parts !== null && (parts[0] === '' || parts[0] === '﻿')) {
    const lines = parts[1].split('\n').map((l) => {
      const m = HASH_LINE.exec(l);
      return m === null ? l : `${m[0]} ""`;
    });
    text = `${parts[0]}---\n${lines.join('\n')}---\n${parts[2]}`;
  }
  return createHash('sha256').update(Buffer.from(text, 'utf8')).digest('hex');
}

export function isEdited(text: string): boolean {
  let stored: unknown;
  try {
    stored = parseSkill(text).metadata[HASH_KEY];
  } catch (e) {
    if (e instanceof SkillFileError) return true;
    throw e;
  }
  return typeof stored !== 'string' || stored !== canonicalHash(text);
}

export function stamp(text: string, metadataUpdates: Record<string, string>): string {
  const doc = parseSkill(text);
  for (const key of Object.keys(metadataUpdates).sort(cmpCodepoint)) {
    if (!key.startsWith(KEY_PREFIX)) throw new SkillFileError(`metadata key ${pyRepr(key)} is not a ${KEY_PREFIX} key`);
    if (typeof metadataUpdates[key] !== 'string') throw new SkillFileError(`metadata ${key} must be a string`);
  }
  const metadata: Record<string, MetaValue> = { ...doc.metadata, ...metadataUpdates, [HASH_KEY]: '' };
  const draft: SkillDoc = { name: doc.name, description: doc.description, metadata, body: doc.body };
  metadata[HASH_KEY] = canonicalHash(render(draft));
  return render(draft);
}

// --------------------------------------------------------------------------- render

const ESCAPES: Record<string, string> = {
  '"': '\\"',
  '\\': '\\\\',
  '\n': '\\n',
  '\t': '\\t',
  '\r': '\\r',
  '\b': '\\b',
  '\f': '\\f',
};
const ESCAPED = new Set([0x2028, 0x2029, 0xfeff, 0xfffe, 0xffff]);

/** A one-line YAML double-quoted scalar both readers take back as `s` (see the reference). */
export function yamlQuote(s: string): string {
  let out = '"';
  for (const ch of s) {
    const o = ch.codePointAt(0)!;
    const esc = ESCAPES[ch];
    if (esc !== undefined) out += esc;
    else if (o < 0x20 || (o >= 0x7f && o <= 0x9f) || ESCAPED.has(o) || (o >= 0xd800 && o <= 0xdfff)) {
      out += `\\u${o.toString(16).padStart(4, '0')}`;
    } else out += ch;
  }
  return `${out}"`;
}

function nameScalar(name: string): string {
  const plain = NAME_RE.test(name) && name[0]! >= 'a' && name[0]! <= 'z' && !PLAIN_WORDS.includes(name);
  return plain ? name : yamlQuote(name);
}

export function render(doc: SkillDoc): string {
  const lines = ['---', `name: ${nameScalar(doc.name)}`, `description: ${yamlQuote(doc.description)}`];
  const keys = Object.keys(doc.metadata).sort(cmpCodepoint);
  if (keys.length > 0) {
    lines.push('metadata:');
    for (const key of keys) {
      const value = doc.metadata[key];
      if (!KEY_RE.test(key)) throw new SkillFileError(`metadata key ${pyRepr(key)} cannot be written`);
      if (typeof value !== 'string') throw new SkillFileError(`metadata ${key} must be a string`);
      lines.push(`  ${key}: ${yamlQuote(value)}`);
    }
  }
  lines.push('---', '');
  return `${lines.join('\n')}\n${doc.body}\n`;
}

// ------------------------------------------------------------------------ the writes

/** The seams tests and the conformance suite replace to inject a failure at a step. */
export const seams = {
  fsync(fd: number): void {
    fs.fsyncSync(fd);
  },
  write(file: string, data: Uint8Array): void {
    // 'wx': a temp name is predictable, so an entry already at it (a planted symlink, a
    // file another writer owns) is refused, never truncated or followed (#250).
    let fd: number;
    try {
      fd = fs.openSync(file, 'wx', 0o644);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === 'EEXIST') throw taken(file);
      throw e;
    }
    try {
      let off = 0;
      while (off < data.length) off += fs.writeSync(fd, data, off, data.length - off);
      seams.fsync(fd);
    } finally {
      fs.closeSync(fd);
    }
  },
  rename(src: string, dst: string): void {
    fs.renameSync(src, dst);
  },
  temp(target: string, kind: string): string {
    counter += 1;
    return `${target}.${kind}-${process.pid}-${counter}`;
  },
};

const temp = (target: string, kind: string): string => seams.temp(target, kind);

const taken = (p: string): SkillFileError =>
  new SkillFileError(`temp path ${p} already exists; refusing to write through it`);

/** A fresh temp dir, refused like `seams.write` when its name is already taken. */
function mkdirTemp(p: string): void {
  try {
    fs.mkdirSync(p);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'EEXIST') throw taken(p);
    throw e;
  }
}

const rmTree = (p: string): void => {
  try {
    fs.rmSync(p, { recursive: true, force: true });
  } catch {
    /* best effort, as the reference's ignore_errors */
  }
};

const lexists = (p: string): boolean => {
  try {
    fs.lstatSync(p);
    return true;
  } catch {
    return false;
  }
};

function checkRel(rel: string): string[] {
  const parts = rel.split('/');
  if (
    rel === '' ||
    rel.includes('\\') ||
    rel.startsWith('/') ||
    parts.some((p) => p === '' || p === '.' || p === '..') ||
    parts[0]!.includes(':')
  ) {
    throw new SkillFileError(`file path ${pyRepr(rel)} is not a plain relative path`);
  }
  return parts;
}

function build(target: string, files: Record<string, Uint8Array>): string {
  const rels = Object.keys(files).sort(cmpCodepoint);
  for (const rel of rels) checkRel(rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = temp(target, 'tmp');
  mkdirTemp(tmp);
  try {
    for (const rel of rels) {
      const file = path.join(tmp, ...rel.split('/'));
      fs.mkdirSync(path.dirname(file), { recursive: true });
      seams.write(file, files[rel]!);
    }
  } catch (e) {
    rmTree(tmp);
    throw e;
  }
  return tmp;
}

export function writeDirAtomic(target: string, files: Record<string, Uint8Array>): void {
  if (lexists(target)) throw new SkillFileError(`a skill already exists at ${target}`);
  const tmp = build(target, files);
  try {
    seams.rename(tmp, target);
  } catch (e) {
    rmTree(tmp);
    throw e;
  }
}

/** Directories and regular files into the existing `dst`; a symlink is not followed or copied. */
function copyTree(src: string, dst: string): void {
  for (const entry of fs.readdirSync(src).sort(cmpCodepoint)) {
    const s = path.join(src, entry);
    const d = path.join(dst, entry);
    const st = fs.lstatSync(s);
    if (st.isSymbolicLink()) continue;
    if (st.isDirectory()) {
      fs.mkdirSync(d);
      copyTree(s, d);
    } else if (st.isFile()) seams.write(d, fs.readFileSync(s));
  }
}

function swapIn(tmp: string, target: string): void {
  if (!lexists(target)) {
    seams.rename(tmp, target);
    return;
  }
  const old = temp(target, 'old');
  seams.rename(target, old);
  try {
    seams.rename(tmp, target);
  } catch (e) {
    seams.rename(old, target);
    throw e;
  }
  rmTree(old);
}

export function backupStamp(now: string): string {
  let ms: number;
  try {
    ms = parseNow(now);
  } catch {
    throw new SkillFileError(`not a timestamp: ${pyRepr(String(now))}`);
  }
  const t = new Date(ms);
  const p = (n: number, w = 2): string => String(n).padStart(w, '0');
  return (
    `${p(t.getUTCFullYear(), 4)}${p(t.getUTCMonth() + 1)}${p(t.getUTCDate())}` +
    `T${p(t.getUTCHours())}${p(t.getUTCMinutes())}${p(t.getUTCSeconds())}.${p(t.getUTCMilliseconds(), 3)}Z`
  );
}

function newBackup(root: string, name: string, now: string, fill: (tmp: string) => void): string {
  const base = backupStamp(now);
  const home = path.join(root, name);
  fs.mkdirSync(home, { recursive: true });
  let final = path.join(home, base);
  let n = 1;
  while (lexists(final)) {
    n += 1;
    final = path.join(home, `${base}-${n}`);
  }
  const tmp = temp(final, 'tmp');
  mkdirTemp(tmp); // outside the try: a taken name is not ours to remove
  try {
    fill(tmp);
    seams.rename(tmp, final);
  } catch (e) {
    rmTree(tmp);
    throw e;
  }
  return final;
}

export function backupAbsent(root: string, name: string, now: string): string {
  return newBackup(root, name, now, (tmp) => seams.write(path.join(tmp, ABSENT_MARKER), new Uint8Array(0)));
}

export function backupDir(root: string, target: string, now: string): string {
  return newBackup(root, path.basename(target), now, (tmp) => copyTree(target, tmp));
}

export function replaceDirAtomic(
  target: string,
  files: Record<string, Uint8Array>,
  root: string,
  now: string,
): string {
  let st: fs.Stats | null = null;
  try {
    st = fs.lstatSync(target);
  } catch {
    st = null;
  }
  if (st === null || !st.isDirectory()) throw new SkillFileError(`no skill at ${target}`);
  const backup = backupDir(root, target, now);
  try {
    const tmp = build(target, files);
    try {
      swapIn(tmp, target);
    } catch (e) {
      rmTree(tmp);
      throw e;
    }
  } catch (e) {
    rmTree(backup);
    throw e;
  }
  return backup;
}

function backups(root: string, name: string): string[] {
  const home = path.join(root, name);
  let entries: string[];
  try {
    entries = fs.readdirSync(home);
  } catch {
    return [];
  }
  const found: Array<[string, number, string]> = [];
  for (const entry of entries) {
    const m = BACKUP_NAME.exec(entry);
    if (m === null) continue;
    try {
      if (!fs.statSync(path.join(home, entry)).isDirectory()) continue;
    } catch {
      continue;
    }
    found.push([m[1]!, Number(m[2] ?? '1'), entry]);
  }
  found.sort((a, b) => cmpCodepoint(a[0], b[0]) || a[1] - b[1]);
  return found.map((f) => f[2]);
}

export function undo(root: string, name: string, target: string): string {
  const found = backups(root, name);
  if (found.length === 0) throw new SkillFileError(`no backup of ${name} to undo`);
  const entry = found[found.length - 1]!;
  const backup = path.join(root, name, entry);
  let absent = false;
  try {
    absent = fs.statSync(path.join(backup, ABSENT_MARKER)).isFile();
  } catch {
    absent = false;
  }
  if (absent) {
    if (lexists(target)) {
      const old = temp(target, 'old');
      seams.rename(target, old);
      rmTree(old);
    }
    rmTree(backup);
    return `removed ${name}; it did not exist before ${entry}`;
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = temp(target, 'tmp');
  mkdirTemp(tmp); // outside the try: a taken name is not ours to remove
  try {
    copyTree(backup, tmp);
    swapIn(tmp, target);
  } catch (e) {
    rmTree(tmp);
    throw e;
  }
  rmTree(backup);
  return `restored ${name} from its backup of ${entry}`;
}

export function historyAdd(skillDir: string, version: number): void {
  if (typeof version !== 'number' || !Number.isInteger(version) || version < 1) {
    throw new SkillFileError(`version must be a whole number from 1, not ${version}`);
  }
  const data = fs.readFileSync(path.join(skillDir, SKILL_FILE));
  const dst = path.join(skillDir, 'references', 'history', `v${version}.md`);
  if (lexists(dst)) throw new SkillFileError(`history already holds v${version} of ${path.basename(skillDir)}`);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  writeFileAtomic(dst, data);
}

function writeFileAtomic(file: string, data: Uint8Array): void {
  const tmp = temp(file, 'tmp');
  try {
    seams.write(tmp, data);
    seams.rename(tmp, file);
  } catch (e) {
    if (e instanceof SkillFileError) throw e; // the temp name was taken: what sits there is not ours to unlink
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* nothing was written */
    }
    throw e;
  }
}

// ---------------------------------------------------------------------------- paths

export const skillsRoot = (home: string): string => path.join(home, '.bantamkit', 'skills');
export const projectSkillsRoot = (top: string): string => path.join(top, '.bantamkit', 'skills');
export const backupRoot = (home: string): string => path.join(home, '.bantamkit', 'skill-backups');
export const statePath = (home: string): string => path.join(home, '.bantamkit', STATE_NAME);

export type SkillsState = Record<string, unknown> & { version: number; skills: Record<string, unknown> };

const STRICT = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

export function readState(home: string): SkillsState {
  let raw: Buffer;
  try {
    raw = fs.readFileSync(statePath(home));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return { version: STATE_VERSION, skills: {} };
    throw e;
  }
  let py: PyValue;
  try {
    py = parseJson(STRICT.decode(raw));
  } catch {
    throw new SkillFileError(`${STATE_NAME} is not readable JSON`);
  }
  const version = py.t === 'dict' ? py.v.get('version') : undefined;
  const skills = py.t === 'dict' ? py.v.get('skills') : undefined;
  if (version?.t !== 'int' || version.v !== BigInt(STATE_VERSION) || skills?.t !== 'dict') {
    throw new SkillFileError(`${STATE_NAME} is not a version ${STATE_VERSION} skills state`);
  }
  const doc = toJs(py);
  return doc as SkillsState;
}

export function stateBytes(state: Record<string, unknown>): Buffer {
  const doc = { ...state, version: STATE_VERSION };
  return Buffer.from(`${dumpJson(fromJs(doc), { indent: 2, sortKeys: true, ensureAscii: false })}\n`, 'utf8');
}

export function writeState(home: string, state: Record<string, unknown>): void {
  const file = statePath(home);
  const data = stateBytes(state);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  exclusive(file, () => writeFileAtomic(file, data));
}

export function updateState(
  home: string,
  change: (state: SkillsState) => SkillsState | void,
): SkillsState {
  const file = statePath(home);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  return exclusive(file, () => {
    let state = readState(home);
    const changed = change(state);
    if (changed) state = changed;
    writeFileAtomic(file, stateBytes(state));
    return { ...state, version: STATE_VERSION };
  });
}
