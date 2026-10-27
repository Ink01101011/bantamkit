/**
 * The skill drafter (#206 Task 6): bundle, prompt, gate, and the X5 chain.
 *
 * Port of `runtime-py/src/bantamkit/skilldraft.py`; the module docstring there is the design
 * note (why the bundle copies named fields only, the gate's fixed reason order, why the first
 * drafter that ANSWERS ends the walk). `tools/conformance/suites/skill-draft.mjs` compares the
 * two. The walk is async here because the client is; everything else is synchronous.
 *
 * Every length is in CODE POINTS and every sort by code point, as Python's are.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { OpenAICompatible } from './client.js';
import { dumpJson, fromJs } from './pyjson.js';
import { cmpCodepoint, pyRepr } from './pysem.js';
import { KIND_SHARED_PHRASE, auditRoots } from './skillaudit.js';
import type { LabelledRoot } from './skillaudit.js';
import {
  SKILL_FILE,
  SkillFileError,
  parseSkill,
  projectSkillsRoot,
  render,
  skillsRoot,
  validate,
} from './skillfile.js';
import type { SkillDoc } from './skillfile.js';
import { selectAdapter } from './skillhost.js';
import { LogSegment } from './storage/logsegment.js';

export const EVIDENCE_PROMPT_CHARS = 500;
export const DRAFTS_LOG = 'skill-drafts.jsonl';
export const LLM_URL_ENV = 'BANTAMKIT_LLM_URL';
export const LLM_MODEL_ENV = 'BANTAMKIT_LLM_MODEL';
export const DRAFTER_SAMPLING = 'sampling';
export const DRAFTER_HOST = 'host agent';
export const DRAFTER_ENDPOINT = 'endpoint';

/** The directory the draft is audited under: a leading hyphen is no valid skill name. */
export const DRAFT_DIR = '-draft';

/** A "now" so far ahead that the gatherer's usage walk stats every transcript and reads none. */
const NO_USAGE_MS = Number.MAX_SAFE_INTEGER;

export const DRAFT_SYSTEM =
  'You turn evidence of repeated, successful work into one Agent Skill. ' +
  'You answer with the text of one SKILL.md file and nothing else.';

export const DRAFT_INSTRUCTIONS = [
  'Write one SKILL.md in the Agent Skills format (agentskills.io/specification) for the work in',
  "the evidence bundle below. The bundle holds a user's own requests, the tools used in order,",
  'the files touched, and whether each piece of work succeeded.',
  '',
  'The format:',
  '- Start with a frontmatter block between two lines of three hyphens, holding exactly two keys,',
  '  name and description. Leave metadata out: bantamkit adds it.',
  '- name: 1-64 characters of a-z, 0-9 and single inner hyphens, in action or gerund form, for',
  '  example fixing-windows-encoding. Never a generic word such as helper or utils.',
  '- description: at most 1024 characters, third person. What the skill does in half a',
  '  sentence, then Use when... with the words a user would type. No steps in the description:',
  '  an agent that reads a workflow there follows it and skips the body.',
  '- The body after the frontmatter is at most 500 lines, with these four sections in this order:',
  '  ## When to use',
  '  ## Steps',
  '  ## Pitfalls',
  '  ## Example',
  '- ## Steps is a numbered list. Every step cites at least one evidence id from the bundle in',
  '  square brackets, for example [job72/C3] or [s1a2b3c4#2].',
  "- ## Pitfalls names the mistakes in the bundle's pitfalls, each citing its evidence id.",
  '- Use only what the bundle holds. Never invent an evidence id, a file or a command.',
  '',
  'Answer with the SKILL.md text only: no preamble, no explanation, no code fence around it.',
].join('\n');

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
const ITEM = /^[ \t]{0,3}(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]|$)/;
const CITE = /\[([^[\] \t\r\n\f\v]+)\](?!\()/g;
const HEADING_BREAK = /^#{1,2}(?:[ \t]|$)/;
const FENCE_OPEN = /^```[A-Za-z0-9_-]*[ \t]*\n/;
const EDGE_WS = /^[ \t\r\n]+|[ \t\r\n]+$/g;
const SAFE_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// --------------------------------------------------------------------------------- bundle

export interface EvidenceItem {
  id: string;
  paths: string[];
  prompt: string;
  signals: Record<string, boolean>;
  tools: string[];
}

export interface Bundle {
  cluster: string;
  evidence: EvidenceItem[];
  keywords: string[];
  level: string;
  pitfalls: { failure: string | null; id: string }[];
  steps: string[];
}

const clean = (s: string): string => s.replace(LONE_SURROGATE, '�');
const str = (v: unknown): string => (typeof v === 'string' ? clean(v) : '');
const strs = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').map(clean) : [];
const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);
const cpCut = (s: string, n: number): string => {
  const cps = [...s];
  return cps.length <= n ? s : cps.slice(0, n).join('');
};

function signals(v: unknown): Record<string, boolean> {
  if (!isObj(v)) return {};
  const out: Record<string, boolean> = {};
  for (const k of Object.keys(v).sort(cmpCodepoint)) {
    if (typeof v[k] === 'boolean') out[clean(k)] = v[k] as boolean;
  }
  return out;
}

/** The evidence bundle for one proposals record, built from named fields only (X4). */
export function bundle(cluster: Record<string, unknown>): Bundle {
  const evidence: EvidenceItem[] = [];
  const ev = cluster.evidence;
  for (const e of Array.isArray(ev) ? ev : []) {
    if (!isObj(e)) continue;
    // Cut on the raw text, then clean: Python's `str[:n]` counts a lone surrogate as one.
    const prompt = typeof e.prompt === 'string' ? clean(cpCut(e.prompt, EVIDENCE_PROMPT_CHARS)) : '';
    evidence.push({
      id: str(e.id),
      paths: strs(e.paths),
      prompt,
      signals: signals(e.signals),
      tools: strs(e.tools),
    });
  }
  const pitfalls: Bundle['pitfalls'] = [];
  const pf = cluster.pitfalls;
  for (const p of Array.isArray(pf) ? pf : []) {
    if (!isObj(p)) continue;
    pitfalls.push({ failure: typeof p.failure === 'string' ? clean(p.failure) : null, id: str(p.id) });
  }
  return {
    cluster: str(cluster.id),
    evidence,
    keywords: strs(cluster.keywords),
    level: str(cluster.level),
    pitfalls,
    steps: strs(cluster.steps),
  };
}

export function bundleJson(b: Bundle): string {
  return dumpJson(fromJs(b), { indent: 2, sortKeys: true, ensureAscii: false });
}

/** `[system, user]`: the exact two messages every drafter that drafts is sent. */
export function prompt(b: Bundle): [string, string] {
  return [DRAFT_SYSTEM, `${DRAFT_INSTRUCTIONS}\n\nThe evidence bundle:\n\n\`\`\`json\n${bundleJson(b)}\n\`\`\`\n`];
}

export function evidenceIds(b: Bundle): Set<string> {
  const ids = new Set<string>();
  for (const e of b.evidence) ids.add(e.id);
  for (const p of b.pitfalls) ids.add(p.id);
  ids.delete('');
  return ids;
}

/** The answer with surrounding blank space cut, and one code fence around it all removed. */
export function unfence(answer: string): string {
  let text = clean(answer).split('\r\n').join('\n').replace(EDGE_WS, '');
  const m = FENCE_OPEN.exec(text);
  if (m !== null && text.endsWith('\n```')) {
    text = text.slice(m[0].length, text.length - '\n```'.length).replace(EDGE_WS, '');
  }
  return text;
}

// ----------------------------------------------------------------------------------- gate

export interface GateResult {
  ok: boolean;
  reasons: string[];
  doc: SkillDoc | null;
}

/** The `## Steps` items: list items, or every non-blank line when there is no list. */
function steps(body: string): string[] {
  const lines = body.split('\n');
  let section: string[] | null = null;
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i]!.replace(/[ \t]+$/, '') !== '## Steps') continue;
    section = [];
    for (const nxt of lines.slice(i + 1)) {
      if (HEADING_BREAK.test(nxt)) break;
      section.push(nxt);
    }
    break;
  }
  if (section === null || section.length === 0) return [];
  const items: string[] = [];
  let started = false;
  for (const line of section) {
    if (ITEM.test(line)) {
      items.push(line);
      started = true;
    } else if (started) {
      items[items.length - 1] += `\n${line}`;
    }
  }
  if (items.length > 0) return items;
  return section.filter((line) => line.replace(/^[ \t]+|[ \t]+$/g, '') !== '');
}

function citations(body: string, ids: Set<string>): string[] {
  const out: string[] = [];
  steps(body).forEach((item, i) => {
    const n = i + 1;
    const cited: string[] = [];
    for (const m of item.matchAll(CITE)) if (!cited.includes(m[1]!)) cited.push(m[1]!);
    if (cited.length === 0) {
      out.push(`step ${n} cites no evidence id`);
      return;
    }
    for (const c of cited) if (!ids.has(c)) out.push(`step ${n} cites ${c}, which is not in the evidence`);
  });
  return out;
}

function real(p: string): string {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}

function exists(p: string): boolean {
  try {
    fs.lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/** `[label, path]` of bantamkit's own skills roots: the project's, then the user's. */
function bantamkitRoots(home: string, cwd: string | null): [string, string][] {
  const candidates: [string, string][] = [];
  if (cwd !== null) candidates.push(['bantamkit-project', projectSkillsRoot(cwd)]);
  candidates.push(['bantamkit-user', skillsRoot(home)]);
  const seen = new Set<string>();
  const out: [string, string][] = [];
  for (const [label, p] of candidates) {
    const r = real(p);
    if (seen.has(r)) continue;
    seen.add(r);
    out.push([label, p]);
  }
  return out;
}

function collisions(
  name: string,
  hostRoots: readonly (readonly [string, string])[],
  own: readonly (readonly [string, string])[],
  itself: string | null = null,
): string[] {
  if (!SAFE_NAME.test(name)) return [];
  const out: string[] = [];
  for (const [label, root] of [...hostRoots, ...own]) {
    if (label === 'plugins') continue; // a plugin skill is namespaced `<plugin>:<name>`
    const target = path.join(root, name);
    if (itself !== null && real(target) === itself) continue; // the skill being improved, or a link to it
    if (exists(target)) out.push(`a skill named ${pyRepr(name)} already exists at ${target}`);
  }
  return out;
}

function shared(
  doc: SkillDoc,
  roots: readonly (readonly [string, string])[],
  enabled: readonly string[],
  versions: Record<string, string> | null,
  itself: string | null = null,
): string[] {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bantamkit-draft-'));
  let findings;
  try {
    const d = path.join(tmp, DRAFT_DIR);
    fs.mkdirSync(d);
    // What the installer would write, so a key the X9 shape drops cannot hide the draft.
    const text = render({ name: doc.name, description: doc.description, metadata: {}, body: '' });
    fs.writeFileSync(path.join(d, SKILL_FILE), Buffer.from(text, 'utf8'));
    const labelled: LabelledRoot[] = [...roots, ['draft', tmp] as const].map(([label, p]) => ({ label, path: p }));
    findings = auditRoots(labelled, {
      enabled: [...enabled],
      check: 'phrase',
      versions: versions === null ? null : new Map(Object.entries(versions)),
    }).findings;
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const out: string[] = [];
  for (const f of findings) {
    if (f.kind !== KIND_SHARED_PHRASE || !f.skills.includes(DRAFT_DIR)) continue;
    for (const s of f.skills) {
      if (s !== DRAFT_DIR && s !== itself) out.push(`trigger phrase ${pyRepr(f.detail)} is shared with ${s}`);
    }
  }
  return out;
}

/** Every reason `text` may not be kept, in the fixed order; `ok` when there is none. */
/**
 * `own` is the directory of the installed skill `text` would become a new version of (Task 10a):
 * the reference's `gate` says what it leaves out.
 */
export function gate(text: string, b: Bundle, home: string, cwd: string | null, own: string | null = null): GateResult {
  // A lone surrogate is U+FFFD before any reader sees it (PyYAML refuses one raw).
  text = clean(text);
  let doc: SkillDoc;
  try {
    doc = parseSkill(text);
  } catch (e) {
    if (e instanceof SkillFileError) return { ok: false, reasons: [e.message], doc: null };
    throw e;
  }
  const reasons = validate(doc);
  const gathered = selectAdapter(home).gather(home, cwd, NO_USAGE_MS);
  const hostRoots = gathered.roots;
  const ownRoots = bantamkitRoots(home, cwd);
  const itself = own !== null ? real(own) : null;
  reasons.push(...collisions(doc.name, hostRoots, ownRoots, itself));
  const audit = [...hostRoots, ...ownRoots.filter(([, p]) => isDir(p))];
  reasons.push(...shared(doc, audit, gathered.enabled, gathered.versions, itself !== null ? path.basename(itself) : null));
  reasons.push(...citations(doc.body, evidenceIds(b)));
  return { ok: reasons.length === 0, reasons, doc };
}

// ------------------------------------------------------------------------------- drafters

export interface Drafter {
  readonly label: string;
  ask(system: string, user: string): Promise<string>;
}

export class Unreachable extends Error {}

/** MCP sampling, inside the server only. `send` null: no `sampling` capability declared. */
export class SamplingDrafter implements Drafter {
  readonly label = DRAFTER_SAMPLING;
  constructor(readonly send: ((system: string, user: string) => Promise<unknown>) | null) {}

  async ask(system: string, user: string): Promise<string> {
    if (this.send === null) throw new Unreachable('the client did not declare sampling');
    const answer = await this.send(system, user);
    if (typeof answer !== 'string') throw new Unreachable('sampling gave no text');
    return answer;
  }
}

/** `[url, model]` when `BANTAMKIT_LLM_URL` and `BANTAMKIT_LLM_MODEL` are both set. */
export function endpointConfig(): [string, string] | null {
  const url = (process.env[LLM_URL_ENV] ?? '').replace(EDGE_WS, '');
  const model = (process.env[LLM_MODEL_ENV] ?? '').replace(EDGE_WS, '');
  return url && model ? [url, model] : null;
}

export interface EndpointOptions {
  maxRetries?: number;
  /** The client's backoff wait; a test seam only. */
  sleep?: (ms: number) => Promise<void>;
}

/** A configured OpenAI-compatible endpoint (`client.ts`). */
export class EndpointDrafter implements Drafter {
  readonly url: string;
  readonly model: string;
  constructor(
    url: string | null = null,
    model: string | null = null,
    readonly options: EndpointOptions = {},
  ) {
    if (url === null || model === null) [url, model] = endpointConfig() ?? ['', ''];
    this.url = url;
    this.model = model;
  }

  get label(): string {
    return `${DRAFTER_ENDPOINT} ${this.model}`;
  }

  async ask(system: string, user: string): Promise<string> {
    if (!this.url || !this.model) throw new Unreachable('no endpoint is configured');
    const client = new OpenAICompatible(this.url, this.model, {
      maxRetries: this.options.maxRetries ?? 3,
      ...(this.options.sleep ? { sleep: this.options.sleep } : {}),
    });
    const r = await client.chat([
      { role: 'system', content: system },
      { role: 'user', content: user },
    ]);
    if (typeof r.message.content !== 'string') throw new Unreachable('the endpoint gave no text');
    return r.message.content;
  }
}

/** Never drafts. Ends the walk with what the host agent needs to draft it itself. */
export class HostAgentDrafter {
  readonly label = DRAFTER_HOST;
}

export type ChainLink = Drafter | HostAgentDrafter;

/** Where the skill goes (X3/X7): the project's root for a project cluster with a top. */
export function targetRoot(cluster: Record<string, unknown>, home: string): string {
  const top = cluster.top;
  if (cluster.level === 'project' && typeof top === 'string' && top) return projectSkillsRoot(top);
  return skillsRoot(home);
}

/** Sampling when the client declared it, the endpoint when configured, then the host agent. */
export function defaultChain(
  send: ((system: string, user: string) => Promise<unknown>) | null = null,
  hostAgent = true,
): ChainLink[] {
  const chain: ChainLink[] = [];
  if (send !== null) chain.push(new SamplingDrafter(send));
  if (endpointConfig() !== null) chain.push(new EndpointDrafter());
  if (hostAgent) chain.push(new HostAgentDrafter());
  return chain;
}

/** `sampling` | `endpoint <model>` | `host agent`, for the status line. */
export function activeDrafter(sampling: boolean): string {
  if (sampling) return DRAFTER_SAMPLING;
  const cfg = endpointConfig();
  return cfg !== null ? `${DRAFTER_ENDPOINT} ${cfg[1]}` : DRAFTER_HOST;
}

// ---------------------------------------------------------------------------------- draft

export interface Handoff {
  bundle: Bundle;
  instructions: string;
  target: string;
}

export interface DraftOutcome {
  drafter: string | null;
  ok: boolean;
  text: string | null;
  reasons: string[];
  unreachable: string[];
  /** The host agent's hand-off; null for every other end. */
  handoff: Handoff | null;
}

export const draftsLog = (home: string): string => path.join(home, '.bantamkit', DRAFTS_LOG);

export function logLine(o: DraftOutcome, ts: string, cluster: string): Record<string, unknown> {
  return {
    ts,
    cluster,
    drafter: o.drafter,
    ok: o.ok,
    reasons: [...o.reasons],
    unreachable: [...o.unreachable],
  };
}

/** Walk `chain` for one proposals record; log the outcome; never write a skill. */
export async function draft(
  cluster: Record<string, unknown>,
  chain: readonly ChainLink[],
  home: string,
  cwd: string | null,
  now: string,
): Promise<DraftOutcome> {
  const b = bundle(cluster);
  const [system, user] = prompt(b);
  const unreachable: string[] = [];
  let outcome: DraftOutcome | null = null;
  for (const d of chain) {
    if (d instanceof HostAgentDrafter) {
      const handoff = { bundle: b, instructions: DRAFT_INSTRUCTIONS, target: targetRoot(cluster, home) };
      outcome = { drafter: d.label, ok: false, text: null, reasons: [], unreachable, handoff };
      break;
    }
    let answer: string;
    try {
      answer = await d.ask(system, user);
    } catch {
      unreachable.push(d.label); // every failure to answer is "unreachable" (R11)
      continue;
    }
    const text = unfence(answer);
    const g = gate(text, b, home, cwd);
    outcome = { drafter: d.label, ok: g.ok, text: g.ok ? text : null, reasons: g.reasons, unreachable, handoff: null };
    break;
  }
  if (outcome === null) outcome = { drafter: null, ok: false, text: null, reasons: [], unreachable, handoff: null };
  new LogSegment(draftsLog(home)).append(logLine(outcome, now, b.cluster));
  return outcome;
}

/** SHA-256 of the UTF-8 system message, a NUL, and the user message: the per-side literal. */
export function promptSha256(b: Bundle): string {
  const [system, user] = prompt(b);
  return createHash('sha256').update(Buffer.from(`${system}\0${user}`, 'utf8')).digest('hex');
}
