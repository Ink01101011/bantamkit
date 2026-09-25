/**
 * instructions — every instruction bantamkit emits, checked against the surface it names.
 *
 * THIS SUITE NEVER COMPARES PYTHON WITH NODE. Every other suite in this directory does, and
 * that is exactly the blindness this one exists for: job59 found fourteen instructions whose
 * surface refuses the call the instruction describes, and all fourteen are BYTE-IDENTICAL on
 * both runtimes, because the strings live in `assets/tools/*.json`, `assets/skills/*.md`,
 * `tools/hooks/bantamkit-hook.mjs` and the two CLAUDE.md files, which both servers share.
 * `--all` was green on every one of them. A differential cannot see a lie both sides tell
 * (`differential-is-blind-to-symmetric-regression`).
 *
 * So here `expected` is THE CLAIM — what the sentence promises — and `actual` is WHAT THE
 * SURFACE ANSWERED when called in the shape the sentence describes. The runner still prints a
 * mismatch as `python :` / `node :`; in this suite read those two lines as `claim :` /
 * `surface :`. Every case runs once per server, named `<clause>/<row>/<side>/<what>`, so a
 * drift that lands on both sides is red twice, not green once.
 *
 * EVERY STRING IS FETCHED FROM A RUNNING SURFACE, NOT FROM SOURCE. Tool descriptions and
 * schemas come from `tools/list` over stdio; the instructions block from `initialize`; skills
 * from `resources/read`; the budget refusal from a real `memory_save` over a 300-byte budget;
 * the hook's sentences from running `tools/hooks/bantamkit-hook.mjs` on each event. The only
 * strings read from disk are the two CLAUDE.md files, because a file is its own surface.
 *
 * THE FIVE CLAUSES (job59 N1 §"The missing gate", N3 §5 and §7(ii)):
 *
 *   (a) every name resolves — a tool, parameter or flag named inside an emitted string must
 *       exist on the surface it points at. Rows 6 (`memory_recall` "with the name"), 40
 *       (`run compact()`), 46 (the `file_graph` tool), 51 (accounting `duration`), and 58 (the operator
 *       CLI's unlistable-`archive/` refusal spelling `compact()` — F2's find in job60, not on N1's list).
 *   (b) validated sub-schemas are served — where a call is validated against a shape the
 *       served `inputSchema` does not express, that shape must be in the served schema, and a
 *       call in the served shape must not be refused. Rows 28, 29, 30, 31, and N3's
 *       `handoff_patch`-required row (56 here).
 *   (c) modal sentences get a case whose FAILING shape was written first. Row 27 ("it never
 *       refuses"), row 32 ("Required").
 *   (d) CLAUDE.md's backticked commands run from a throwaway worktree and exit 0, after the
 *       prerequisites the file itself states, in document order. Rows 48 and 49.
 *   (e) advertised-actionable is accepted — a value one tool advertises as actionable must be
 *       accepted by the tool that acts on it, or the advertisement must say which. N3's
 *       plan-vs-cursor row (57 here).
 *
 * THE FAILING SHAPE IS ON RECORD. `.shiftwork/notes-job60/F1-baseline.txt` is this suite's
 * output at 56772d8 with no row fixed. A suite first seen green proves nothing
 * (`feedback-gate-counts-are-co-moving`); that file is the proof this one is not vacuous.
 *
 * HOW A SENTENCE IS PARSED. Clause (a) reads prose, so it has a grammar, and the grammar is
 * small and written down in `namesIn()` below: `mcp__bantamkit__X`, `X()`, "the `X` tool",
 * "with the P" after a tool reference, a JSON key after a tool reference, and the
 * parenthesised list after the word "accounting". Each case's `actual` is the list of names
 * that did NOT resolve, so a reviewer sees what was parsed, not a boolean.
 */
import { spawn, spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'instructions';
export const summary = 'every instruction bantamkit emits, checked against the surface it names — never Python against Node';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const MEMORY_CLI = join(repoRoot, 'runtime-ts', 'dist', 'memory', 'cli.js');
const HOOK = join(repoRoot, 'tools', 'hooks', 'bantamkit-hook.mjs');
const ASSETS = join(repoRoot, 'assets');
const TOOL_FILES_ON_DISK = join(ASSETS, 'tools');
const SKILL_FILES_ON_DISK = join(ASSETS, 'skills');
const CHECKPOINT_SCHEMA = join(ASSETS, 'schemas', 'shiftwork-checkpoint.json');
const TEMPLATE = join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json');
const REPO_CLAUDE_MD = join(repoRoot, 'CLAUDE.md');
/**
 * The user-level file is read when it exists, because it is delivered to every session on the
 * machine that runs this gate — row 51 was found there. `BANTAMKIT_INSTRUCTIONS_USER_CLAUDE_MD`
 * names another path, or, set empty, turns the check off. A runner with no such file gets a
 * note, not a failure.
 */
const USER_CLAUDE_MD =
  process.env.BANTAMKIT_INSTRUCTIONS_USER_CLAUDE_MD !== undefined
    ? process.env.BANTAMKIT_INSTRUCTIONS_USER_CLAUDE_MD
    : join(homedir(), '.claude', 'CLAUDE.md');

const SIDES = ['py', 'node'];
const SESSION_TIMEOUT_MS = 60_000;
/** One CLAUDE.md command in the throwaway worktree. `npm ci && npm run build` is the slow one. */
const COMMAND_TIMEOUT_MS = 600_000;

// ------------------------------------------------------------------- request composition

const INIT = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance-instructions', version: '0' } },
});
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const rpc = (id, method, params) =>
  JSON.stringify(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const callTool = (id, name_, args) => rpc(id, 'tools/call', { name: name_, arguments: args });

// ------------------------------------------------------------------------- one session

/**
 * Drive ONE server over stdio: lock-step, one request at a time, stdin held open until every
 * id has answered. Both facts are measured, not chosen (`ref/wire_ref.py` has the numbers): a
 * pipelined batch is answered concurrently, so a `clock_out` sent behind another could be
 * answered about the wrong state; and a closed stdin drops in-flight responses while every
 * side effect still lands — a driver that wrote 13 requests and closed got 8 answers.
 *
 * The Python side is spawned HERE rather than through a `ref/*.py` script, on purpose: in this
 * suite Python is not the reference, it is one of two subjects, and the driver must be the
 * same bytes for both. `PYTHONPATH` pins the checkout's source so a worktree is answered by
 * its own code and not by the venv's editable install of main
 * (`feedback-worktree-pytest-tests-mains-source`).
 */
function session(ctx, side, spec) {
  const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS };
  delete env.BANTAMKIT_MEMORY_DIR;
  if (side === 'py') {
    env.PYTHONPATH = join(repoRoot, 'runtime-py', 'src');
    env.PYTHONSAFEPATH = '1';
  }
  for (const [key, value] of Object.entries(spec.env ?? {})) {
    if (value === null) delete env[key];
    else env[key] = value;
  }
  const [command, ...prefix] =
    side === 'py' ? [ctx.python, '-m', 'bantamkit.mcpserver'] : [process.execPath, CLI];
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...prefix, ...(spec.argv ?? [])], {
      cwd: spec.cwd ?? repoRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const byId = new Map();
    const wanted = new Set();
    for (const line of spec.lines) {
      try {
        const id = JSON.parse(line).id;
        if (id !== undefined && id !== null) wanted.add(JSON.stringify(id));
      } catch {
        /* not a request */
      }
    }
    let out = '';
    let err = '';
    let pending = null;
    const timer = setTimeout(() => {
      // platform-checked: this is cleanup of a child whose session has already ended (every id
      // answered, or the deadline passed), so no handler in it is relied on; on Windows the
      // signal name is ignored and `kill()` is TerminateProcess, which is the whole intent.
      child.kill('SIGKILL');
      reject(new Error(`instructions: ${side} session ${spec.name} timed out\nstderr:\n${err}`));
    }, SESSION_TIMEOUT_MS);
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        try {
          const frame = JSON.parse(line);
          if (frame.id !== undefined && frame.id !== null) byId.set(JSON.stringify(frame.id), frame);
        } catch {
          /* a non-frame line is not an answer */
        }
      }
      if (pending !== null && byId.has(pending.id)) {
        const resume = pending.resolve;
        pending = null;
        resume();
      }
      if ([...wanted].every((id) => byId.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', () => {
      clearTimeout(timer);
      resolve({ byId, stderr: err });
    });
    child.on('error', reject);
    void (async () => {
      for (const line of spec.lines) {
        if (child.exitCode !== null) break;
        let id = null;
        try {
          const parsed = JSON.parse(line);
          if (parsed.id !== undefined && parsed.id !== null) id = JSON.stringify(parsed.id);
        } catch {
          /* still sent */
        }
        child.stdin.write(`${line}\n`);
        if (id !== null && !byId.has(id)) {
          await new Promise((resolve) => {
            pending = { id, resolve };
          });
        }
      }
    })();
  });
}

const frameOf = (s, id) => s.byId.get(JSON.stringify(id));
/** A tool call's outcome as `{ ok, text }`: `ok` is the inverse of `isError`, `text` the joined text. */
function outcome(s, id) {
  const frame = frameOf(s, id);
  if (!frame) return { ok: false, text: 'NO RESPONSE' };
  if (frame.error) return { ok: false, text: `JSON-RPC error: ${JSON.stringify(frame.error)}` };
  const result = frame.result ?? {};
  const text = (result.content ?? [])
    .filter((c) => c.type === 'text')
    .map((c) => c.text)
    .join('');
  return { ok: !result.isError, text, structured: result.structuredContent };
}
/** The dict a shiftwork tool returns, read from `structuredContent` or parsed from the text. */
function dictOf(s, id) {
  const o = outcome(s, id);
  if (o.structured && typeof o.structured === 'object') return o.structured;
  try {
    return JSON.parse(o.text);
  } catch {
    return { result: o.ok ? 'text' : 'error', reason: o.text };
  }
}
/**
 * The first two lines of a refusal. A pydantic sentence runs to four lines and embeds the
 * scratch path in `input_value=`, which would make two runs of this suite differ on a path.
 */
const brief = (text) => String(text ?? '').split('\n').slice(0, 2).join(' | ').slice(0, 300);
/** `accepted` or the refusal sentence — the two answers a clock_out can give. */
const verdict = (d) => (d.result === 'error' ? `refused: ${brief(d.reason)}` : 'accepted');

// --------------------------------------------------------------------- clause (a) grammar

/**
 * Names an emitted string points at, and whether each resolves on the served surface.
 *
 * Returns the UNRESOLVED references, spelled `<kind>:<what>`, so the case's `actual` shows the
 * parse. The rules, each one a measured drift's shape:
 *
 *   R1  `mcp__bantamkit__X`                  → X is in tools/list
 *   R2  `X()`                                → a call spelling; X is in tools/list (never true:
 *                                              no tool is spelled with parentheses — row 40)
 *   R3  "the `X` tool" / a retired tool name → X is in tools/list. Retired = has a file under
 *                                              assets/tools but is not served (row 46)
 *   R4  after a tool reference: "with [the] P" or `{"P"` → P is a property of X's inputSchema
 *                                              (row 6)
 *   R5  "accounting (A, B, and the C …)"     → each of A, B, C is a property of the served
 *                                              `shiftwork_clock_out.accounting` object (row 51)
 */
function namesIn(text, surface) {
  const unresolved = [];
  const served = surface.tools;
  const has = (t) => Object.prototype.hasOwnProperty.call(served, t);
  for (const m of text.matchAll(/mcp__bantamkit__(\w+)/g)) {
    if (!has(m[1])) unresolved.push(`tool:mcp__bantamkit__${m[1]}`);
  }
  for (const m of text.matchAll(/\b([A-Za-z_]\w*)\(\)/g)) {
    if (!has(m[1])) unresolved.push(`call-spelling:${m[1]}()`);
  }
  for (const m of text.matchAll(/`(\w+)` tool\b/g)) {
    if (!has(m[1])) unresolved.push(`tool:${m[1]}`);
  }
  for (const retired of surface.retired) {
    if (new RegExp(`\`${retired}\``).test(text)) unresolved.push(`retired-tool:${retired}`);
  }
  // R4: the parameter a sentence hands a tool. Only the 60 characters after the reference.
  for (const m of text.matchAll(/(?:mcp__bantamkit__|`)(\w+)`?/g)) {
    const tool = m[1];
    if (!has(tool)) continue;
    const tail = text.slice(m.index + m[0].length, m.index + m[0].length + 60);
    const p = /^\s+with\s+(?:the\s+|its\s+|a\s+)?(?:\{"(\w+)"|(\w+))/.exec(tail);
    if (!p) continue;
    const param = p[1] ?? p[2];
    const properties = served[tool].inputSchema?.properties ?? {};
    if (!Object.prototype.hasOwnProperty.call(properties, param)) unresolved.push(`parameter:${tool}.${param}`);
  }
  // R5: the accounting keys CLAUDE.md spells out.
  const accounting = surface.accountingProperties;
  for (const m of text.matchAll(/\baccounting\s*\(([^)]*)\)/g)) {
    const inner = m[1].split(/\s[—–]\s/)[0];
    for (const fragment of inner.split(/,|\band\b/)) {
      const word = /^\s*(?:the\s+)?([a-z_]\w*)/.exec(fragment)?.[1];
      if (!word) continue;
      if (!Object.prototype.hasOwnProperty.call(accounting, word)) unresolved.push(`parameter:shiftwork_clock_out.accounting.${word}`);
    }
  }
  return unresolved;
}

/** The parameter R4 read for one tool — the name the sentence tells the model to pass. */
function parameterNamed(text, tool) {
  const m = new RegExp(`(?:mcp__bantamkit__|\`)${tool}\`?\\s+with\\s+(?:the\\s+|its\\s+|a\\s+)?(?:\\{"(\\w+)"|(\\w+))`).exec(text);
  return m ? (m[1] ?? m[2]) : null;
}

/** The sentence of `text` in which every one of `words` appears, or null. */
function sentenceWith(text, ...words) {
  for (const sentence of text.split(/(?<=[.;])\s+/)) {
    if (words.every((w) => (w instanceof RegExp ? w.test(sentence) : sentence.includes(w)))) return sentence.trim();
  }
  return null;
}

/** The smallest object a JSON-schema object shape accepts: every required key, typed. */
function minimalObject(schema) {
  const out = {};
  const properties = schema?.properties ?? {};
  for (const key of schema?.required ?? []) {
    const p = properties[key] ?? {};
    if (Array.isArray(p.enum) && p.enum.length) out[key] = p.enum[0];
    else if (p.type === 'integer' || p.type === 'number') out[key] = 1;
    else if (p.type === 'array') out[key] = [];
    else if (p.type === 'object') out[key] = {};
    else if (p.type === 'boolean') out[key] = true;
    else out[key] = 'x';
  }
  return out;
}

// -------------------------------------------------------------------------- fixtures

function copyTemplate(dir, tag, mutate) {
  const path = join(dir, `${tag}.json`);
  const doc = JSON.parse(readFileSync(TEMPLATE, 'utf8'));
  if (mutate) mutate(doc);
  writeFileSync(path, `${JSON.stringify(doc, null, 2)}\n`);
  rmSync(`${path}.log.jsonl`, { force: true });
  return path;
}

/** Run one hook event and hand back what it emitted on stdout, parsed. */
function hook(event, env) {
  const r = spawnSync(process.execPath, [HOOK], {
    input: JSON.stringify(event),
    encoding: 'utf8',
    env: { ...process.env, ...env },
    cwd: repoRoot,
    timeout: SESSION_TIMEOUT_MS,
  });
  const text = (r.stdout ?? '').trim();
  if (!text) return { raw: '', emitted: null };
  try {
    return { raw: text, emitted: JSON.parse(text) };
  } catch {
    return { raw: text, emitted: null };
  }
}

/** Every string inside a JSON value, joined — a tool's description and every property's. */
/**
 * Row 58's surface: the operator CLI (`python -m bantamkit.memory` / `bantamkit-memory`) run
 * as `status` over a store whose `archive/` exists and cannot be listed. `archived()` has no
 * MCP caller on either side (grep `mcpserver.py` and `mcp/server.ts`), so the CLI is the only
 * process that ever prints this sentence, and a model that runs the CLI in a shell is the
 * reader it reaches. Both streams are returned: the Python CLI writes the refusal to stderr
 * before the report lands on stdout, the Node CLI after; the sentence is the datum, not the
 * order. Answers `null` where the mode cannot deny a listing.
 */
function unlistableArchiveRefusal(ctx, side, dir) {
  // platform-checked: on Windows `chmod` cannot remove directory-list permission (the mode
  // bits are advisory there), so the sentence would never be produced and the guard case would
  // be red for the platform, not for the row — the caller skips this fixture on win32 with a
  // note instead. Root ignores the mode too; that case the guard reports as "no sentence".
  if (process.platform === 'win32') return null;
  const archive = join(dir, 'archive');
  mkdirSync(join(dir, 'facts'), { recursive: true });
  mkdirSync(archive, { recursive: true });
  writeFileSync(join(archive, 'gone.md'), '---\nname: gone\ntype: project\ndescription: a fact compaction moved\n---\nBODY\n');
  const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS };
  delete env.BANTAMKIT_MEMORY_DIR;
  if (side === 'py') {
    env.PYTHONPATH = join(repoRoot, 'runtime-py', 'src');
    env.PYTHONSAFEPATH = '1';
  }
  const [command, ...prefix] = side === 'py' ? [ctx.python, '-m', 'bantamkit.memory'] : [process.execPath, MEMORY_CLI];
  chmodSync(archive, 0o311);
  try {
    const r = spawnSync(command, [...prefix, 'status', '--store', dir], { cwd: repoRoot, env, encoding: 'utf8', timeout: SESSION_TIMEOUT_MS });
    return `${r.stderr ?? ''}${r.stdout ?? ''}`;
  } finally {
    chmodSync(archive, 0o755);
  }
}

function stringsOf(value, acc = []) {
  if (typeof value === 'string') acc.push(value);
  else if (Array.isArray(value)) value.forEach((v) => stringsOf(v, acc));
  else if (value && typeof value === 'object') Object.values(value).forEach((v) => stringsOf(v, acc));
  return acc;
}

// ---------------------------------------------------------------------------- the run

export async function run(ctx) {
  const cases = [];
  const notes = [
    'in this suite the runner\'s `python :` line is the CLAIM and its `node :` line is what the ' +
      'SURFACE answered; nothing here compares the two runtimes with each other',
  ];
  const push = (name_, expected, actual, kind = 'json') => cases.push({ name: name_, kind, expected, actual });

  const checkpointSchema = JSON.parse(readFileSync(CHECKPOINT_SCHEMA, 'utf8'));
  const onDiskToolNames = readdirSync(TOOL_FILES_ON_DISK)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -5));
  const skillNames = readdirSync(SKILL_FILES_ON_DISK)
    .filter((f) => f.endsWith('.md'))
    .map((f) => f.slice(0, -3));

  const root = join(ctx.scratch, 'instructions');
  const home = join(root, 'home');
  mkdirSync(join(home, '.claude'), { recursive: true });
  const baseEnv = { HOME: home, USERPROFILE: home };

  // ============================================================ per-side surfaces

  const surfaces = {};
  for (const side of SIDES) {
    const store = join(root, `store-${side}`);
    mkdirSync(store, { recursive: true }); // a pinned dir that does not exist ends the server before `initialized`
    const env = { ...baseEnv, BANTAMKIT_MEMORY_DIR: store };

    // ---- 1. advertisement + resources + the row-6 fact
    const skillReads = skillNames.map((n, i) => rpc(10 + i, 'resources/read', { uri: `bantamkit://skills/${n}` }));
    const s1 = await session(ctx, side, {
      name: 'advertisement',
      env,
      lines: [
        INIT,
        INITIALIZED,
        rpc(2, 'tools/list'),
        callTool(3, 'memory_save', {
          type: 'project',
          name: 'instructions-probe-fact',
          description: 'instructions probe kestrel deploy path fact',
          body: 'PROBE-BODY',
        }),
        ...skillReads,
      ],
    });
    const initFrame = frameOf(s1, 1);
    const instructions = initFrame?.result?.instructions ?? '';
    const toolList = frameOf(s1, 2)?.result?.tools ?? [];
    const tools = Object.fromEntries(toolList.map((t) => [t.name, t]));
    const retired = onDiskToolNames.filter((n) => !Object.prototype.hasOwnProperty.call(tools, n));
    const skills = {};
    skillNames.forEach((n, i) => {
      const frame = frameOf(s1, 10 + i);
      const contents = frame?.result?.contents;
      skills[n] = Array.isArray(contents) ? contents.map((c) => c.text ?? '').join('') : null; // null = not served
    });
    const clockOut = tools.shiftwork_clock_out ?? { inputSchema: { properties: {} } };
    const accountingObject = (clockOut.inputSchema.properties.accounting?.anyOf ?? []).find((a) => a.type === 'object') ?? {};
    const surface = {
      side,
      env,
      instructions,
      tools,
      retired,
      skills,
      accountingProperties: accountingObject.properties ?? {},
      accountingObject,
      clockOut,
      hook: {},
    };

    // ---- 2. the budget refusal sentence (row 40): two saves over a 300-byte index.
    // The two descriptions share NO words. With near-identical ones the DEDUPE refusal
    // answers first (N3 §4 row 40 hit this, and so did this suite's first run), the budget
    // sentence is never produced, and the row-40 case passes green over a sentence that
    // never existed. Either refusal comes back with `isError: false` and a text that starts
    // `error:`, so `ok` cannot tell them apart; the guard case below reads the sentence.
    const store2 = join(root, `store2-${side}`);
    mkdirSync(store2, { recursive: true });
    const s2 = await session(ctx, side, {
      name: 'budget',
      env: { ...baseEnv, BANTAMKIT_MEMORY_DIR: store2 },
      argv: ['--index-budget', '300'],
      lines: [
        INIT,
        INITIALIZED,
        callTool(2, 'memory_save', { type: 'project', name: 'big-one', description: 'heron lantern quartz meadow '.repeat(8), body: 'b1' }),
        callTool(3, 'memory_save', { type: 'project', name: 'big-two', description: 'violet anchor timber cobalt '.repeat(8), body: 'b2' }),
      ],
    });
    surface.budgetRefusal = outcome(s2, 3);

    surfaces[side] = surface;
  }

  // ============================================================ the hook, once (Node-only code; its sentences name both servers' tools)

  const hookHome = join(root, 'hook-home');
  mkdirSync(join(hookHome, '.claude'), { recursive: true });
  const hookEnv = { HOME: hookHome, USERPROFILE: hookHome, BANTAMKIT_MEMORY_DIR: join(root, 'store-node') };
  const project = join(root, 'hook-project');
  mkdirSync(project, { recursive: true });
  const readMe = join(project, 'README.md');
  writeFileSync(readMe, '# probe\n');
  const transcript = join(project, 'transcript.jsonl');
  writeFileSync(transcript, Array.from({ length: 25 }, (_, i) => JSON.stringify({ type: 'assistant', message: { content: [{ type: 'tool_use', id: `t${i}`, name: 'Bash' }] } })).join('\n'));
  const sessionId = 'instructions-hook-session';
  const hookOut = {
    SessionStart: hook({ hook_event_name: 'SessionStart', source: 'startup', session_id: sessionId, cwd: project }, hookEnv),
    UserPromptSubmit: hook({ hook_event_name: 'UserPromptSubmit', session_id: sessionId, cwd: project, prompt: 'instructions probe kestrel deploy path fact' }, hookEnv),
    PreToolUse1: hook({ hook_event_name: 'PreToolUse', tool_name: 'Read', session_id: sessionId, transcript_path: transcript, cwd: project, tool_input: { file_path: readMe } }, hookEnv),
    PreToolUse2: hook({ hook_event_name: 'PreToolUse', tool_name: 'Read', session_id: sessionId, transcript_path: transcript, cwd: project, tool_input: { file_path: readMe } }, hookEnv),
    Stop: hook({ hook_event_name: 'Stop', session_id: sessionId, transcript_path: transcript, cwd: project }, hookEnv),
  };
  const hookStrings = {
    'session-start': hookOut.SessionStart.emitted?.hookSpecificOutput?.additionalContext ?? '',
    'recall-header': hookOut.UserPromptSubmit.emitted?.hookSpecificOutput?.additionalContext ?? '',
    'read-refusal': hookOut.PreToolUse2.emitted?.hookSpecificOutput?.permissionDecisionReason ?? '',
    'stop-nudge': hookOut.Stop.emitted?.reason ?? '',
  };
  for (const [arm, text] of Object.entries(hookStrings)) {
    if (!text) notes.push(`hook arm ${arm} emitted nothing; its sentence could not be checked (raw: ${JSON.stringify(hookOut[arm === 'session-start' ? 'SessionStart' : arm === 'recall-header' ? 'UserPromptSubmit' : arm === 'read-refusal' ? 'PreToolUse2' : 'Stop'].raw.slice(0, 200))})`);
  }

  const repoClaudeMd = readFileSync(REPO_CLAUDE_MD, 'utf8');
  const userClaudeMd = USER_CLAUDE_MD && existsSync(USER_CLAUDE_MD) ? readFileSync(USER_CLAUDE_MD, 'utf8') : null;
  if (userClaudeMd === null) notes.push(`user-level CLAUDE.md not checked: ${USER_CLAUDE_MD ? `${USER_CLAUDE_MD} is absent` : 'turned off by BANTAMKIT_INSTRUCTIONS_USER_CLAUDE_MD='}`);

  // ============================================================ clauses (a), (b), (c), (e) per side

  for (const side of SIDES) {
    const S = surfaces[side];
    const N = (clause, row, what) => `${clause}/${row}/${side}/${what}`;

    // -------------------------------------------------------------- (a) every name resolves
    // Row 6: the hook's recall header names a parameter; the served schema must have it, and
    // the literal call in the header's shape must be answered.
    push(N('a', 'row06', 'hook-recall-header-names-a-served-parameter'), [], namesIn(hookStrings['recall-header'], S));
    const param = parameterNamed(hookStrings['recall-header'], 'memory_recall');
    const sRecall = await session(ctx, side, {
      name: 'row06-literal-call',
      env: S.env,
      lines: [INIT, INITIALIZED, callTool(2, 'memory_recall', { [param ?? 'name']: 'instructions-probe-fact' })],
    });
    const recall = outcome(sRecall, 2);
    push(
      N('a', 'row06', `memory_recall-called-as-the-header-says-{${param ?? 'name'}}`),
      'answered with the fact body',
      recall.ok && recall.text.includes('PROBE-BODY') ? 'answered with the fact body' : `refused: ${brief(recall.text)}`,
      'string',
    );

    // Row 40: the budget refusal sentence names what to run. The guard case first: a run in
    // which the sentence was never produced must be red, not green over an empty string.
    const budgetSentence = /budget is \d+/.test(S.budgetRefusal.text);
    push(
      N('a', 'row40', 'budget-refusal-was-produced'),
      'the 300-byte index refused the second save',
      budgetSentence ? 'the 300-byte index refused the second save' : `no budget sentence: ${S.budgetRefusal.text.split('\n')[0].slice(0, 200)}`,
      'string',
    );
    push(N('a', 'row40', 'budget-refusal-names-only-served-tools'), [], budgetSentence ? namesIn(S.budgetRefusal.text, S) : ['(no budget sentence to read)']);

    // Row 46: a served skill names a tool; the tool must be served, and callable.
    for (const [skill, text] of Object.entries(S.skills)) {
      if (text === null) {
        push(N('a', skill === 'file-graph' ? 'row46' : 'sweep', `skill-${skill}`), [], []);
        notes.push(`${side}: bantamkit://skills/${skill} is not served, nothing to resolve`);
        continue;
      }
      push(N('a', skill === 'file-graph' ? 'row46' : 'sweep', `skill-${skill}-names-only-served-tools`), [], namesIn(text, S));
      const named = [...text.matchAll(/`(\w+)` tool\b/g)].map((m) => m[1]);
      if (named.length) {
        const s = await session(ctx, side, {
          name: `skill-${skill}-call`,
          env: S.env,
          lines: [INIT, INITIALIZED, ...named.map((t, i) => callTool(2 + i, t, {}))],
        });
        push(
          N('a', skill === 'file-graph' ? 'row46' : 'sweep', `skill-${skill}-named-tools-are-callable`),
          named.map((t) => `${t}: callable`),
          named.map((t, i) => {
            const o = outcome(s, 2 + i);
            return `${t}: ${o.ok || !/unknown tool|not found|no such tool|Unknown tool/i.test(o.text) ? 'callable' : `refused: ${o.text.slice(0, 160)}`}`;
          }),
        );
      }
    }

    // Row 58: the operator CLI's unlistable-archive refusal names what moved the facts. The
    // guard case first, as for row 40: a run in which the sentence was never produced (root,
    // a filesystem that ignores the mode) must be red, not green over an empty string.
    const archiveRefusal = unlistableArchiveRefusal(ctx, side, join(root, `archive-${side}`));
    if (archiveRefusal === null) {
      notes.push(`${side}: row 58 skipped on win32: chmod cannot deny a directory listing there`);
    } else {
      const archiveSentence = /archive that could not be listed/.test(archiveRefusal);
      push(
        N('a', 'row58', 'archive-refusal-was-produced'),
        'the unlistable archive/ refused `status`',
        archiveSentence ? 'the unlistable archive/ refused `status`' : `no archive sentence: ${archiveRefusal.split('\n')[0].slice(0, 200)}`,
        'string',
      );
      push(N('a', 'row58', 'archive-refusal-names-only-served-tools'), [], archiveSentence ? namesIn(archiveRefusal, S) : ['(no archive sentence to read)']);
    }

    // Row 51: both CLAUDE.md files spell the accounting keys.
    push(N('a', 'row51', 'repo-claude-md-names-only-served-parameters'), [], namesIn(repoClaudeMd, S));
    if (userClaudeMd !== null) push(N('a', 'row51', 'user-claude-md-names-only-served-parameters'), [], namesIn(userClaudeMd, S));
    // …and the literal call CLAUDE.md describes must be accepted (a roles-free checkpoint, so only the shape is judged).
    const keysNamed = (() => {
      const m = /\baccounting\s*\(([^)]*)\)/.exec(repoClaudeMd);
      if (!m) return [];
      return m[1]
        .split(/\s[—–]\s/)[0]
        .split(/,|\band\b/)
        .map((f) => /^\s*(?:the\s+)?([a-z_]\w*)/.exec(f)?.[1])
        .filter(Boolean);
    })();
    const accountingAsWritten = Object.fromEntries(keysNamed.map((k) => [k, k === 'model' ? 'claude-x' : 1]));

    // -------------------------------------------------------------- (b) sub-schemas served
    const served = S.clockOut.inputSchema.properties;
    const cp = checkpointSchema.properties;
    const historyItems = cp.history.items;
    const handoff = cp.handoff;
    const statusEnum = cp.plan.properties.units.items.properties.status.enum;
    const sortedKeys = (o) => Object.keys(o ?? {}).sort();

    push(N('b', 'row28', 'history_entry-served-schema-requires-what-the-writer-requires'), [...historyItems.required].sort(), [...(served.history_entry?.required ?? [])].sort());
    push(
      N('b', 'row29', 'handoff_patch-served-schema-is-as-closed-as-the-writer'),
      { additionalProperties: handoff.additionalProperties, keys: sortedKeys(handoff.properties) },
      { additionalProperties: served.handoff_patch?.additionalProperties ?? true, keys: sortedKeys(served.handoff_patch?.properties) },
    );
    push(N('b', 'row30', 'status-served-enum-is-the-writer-enum'), statusEnum, served.status?.enum ?? []);
    const unitIdText = `${served.unit_id?.description ?? ''} ${S.clockOut.description ?? ''}`;
    push(
      N('b', 'row31', 'cursor-precondition-stated-in-served-text'),
      'a served sentence names both unit_id and the cursor',
      sentenceWith(unitIdText, 'unit_id', 'cursor') ? 'a served sentence names both unit_id and the cursor' : 'no served sentence says unit_id must be the cursor unit',
      'string',
    );

    // The calls in the SERVED shape. One session, one fresh checkpoint copy per call.
    const dir = join(root, `checkpoints-${side}`);
    mkdirSync(dir, { recursive: true });
    const base = { status: 'done', handoff_patch: {}, history_entry: { unit: 'CF1', outcome: 'ok' } };
    const shapes = {
      row28: { ...base, history_entry: minimalObject(served.history_entry) },
      row29: {
        ...base,
        handoff_patch: served.handoff_patch?.additionalProperties === false ? minimalObject(served.handoff_patch) : { instructions_probe_key: 'x' },
      },
      row30: { ...base, status: served.status?.enum?.length ? served.status.enum[served.status.enum.length - 1] : 'finished' },
      row56: (() => {
        const { handoff_patch: _omitted, ...rest } = base;
        return rest;
      })(),
      row32: { ...base }, // no accounting at all
      row51: { ...base, accounting: accountingAsWritten },
    };
    const paths = Object.fromEntries(Object.keys(shapes).map((k) => [k, copyTemplate(dir, k)]));
    const width2 = copyTemplate(dir, 'row57-plan', (doc) => {
      doc.plan.units[1].depends_on = [];
    });
    const sClock = await session(ctx, side, {
      name: 'clock-out-shapes',
      env: S.env,
      lines: [
        INIT,
        INITIALIZED,
        ...Object.entries(shapes).map(([k, args], i) => callTool(2 + i, 'shiftwork_clock_out', { checkpoint: paths[k], unit_id: 'CF1', ...args })),
        callTool(20, 'shiftwork_plan', { checkpoint: width2 }),
      ],
    });
    const answers = Object.fromEntries(Object.keys(shapes).map((k, i) => [k, dictOf(sClock, 2 + i)]));

    push(N('b', 'row28', 'history_entry-in-served-shape-is-accepted'), 'accepted', verdict(answers.row28), 'string');
    push(N('b', 'row29', 'handoff_patch-in-served-shape-is-accepted'), 'accepted', verdict(answers.row29), 'string');
    push(N('b', 'row30', 'status-in-served-shape-is-accepted'), 'accepted', verdict(answers.row30), 'string');
    const requiredList = S.clockOut.inputSchema.required ?? [];
    const handoffRequiredDisclosed = sentenceWith(S.clockOut.description ?? '', 'handoff_patch', /\brequired\b/i);
    push(
      N('b', 'row56', 'handoff_patch-optional-as-described-or-described-as-required'),
      'accepted without handoff_patch, or the description says it is required',
      requiredList.includes('handoff_patch')
        ? handoffRequiredDisclosed
          ? 'accepted without handoff_patch, or the description says it is required'
          : `the served schema requires handoff_patch and the description never says so; omitting it: ${verdict(answers.row56)}`
        : verdict(answers.row56) === 'accepted'
          ? 'accepted without handoff_patch, or the description says it is required'
          : verdict(answers.row56),
      'string',
    );
    push(N('a', 'row51', 'accounting-as-claude-md-spells-it-is-accepted'), 'accepted', verdict(answers.row51), 'string');

    // -------------------------------------------------------------- (c) modal sentences
    const claimsNever = /never refuses/.test(S.clockOut.description ?? '');
    const refusals = ['row28', 'row29', 'row30', 'row56'].map((k) => verdict(answers[k])).filter((v) => v !== 'accepted');
    push(
      N('c', 'row27', 'it-never-refuses'),
      claimsNever ? [] : ['the description makes no unconditional promise'],
      claimsNever ? refusals : ['the description makes no unconditional promise'],
    );
    const tokensDesc = `${S.accountingProperties.tokens?.description ?? ''} ${S.accountingProperties.duration_ms?.description ?? ''}`;
    const claimsRequired = /\bRequired\b/.test(tokensDesc) && !requiredList.includes('accounting');
    push(
      N('c', 'row32', 'accounting-Required-means-omitting-it-is-refused'),
      claimsRequired ? 'refused' : 'the schema no longer says Required, or accounting is required at the top',
      claimsRequired ? (verdict(answers.row32) === 'accepted' ? 'accepted (logged with no tokens and no duration)' : 'refused') : 'the schema no longer says Required, or accounting is required at the top',
      'string',
    );

    // Job64, J64-4: the served `memory_recall` description makes two claims about the surface
    // — "never fewer than the store default of 3 when that many match" (RB-P1's floor, which
    // the old sentence "Returns at most k matching facts" contradicted) and "a query that is
    // exactly a fact's name returns that fact alone" — and both are checked against the
    // surface here, per side, so the sentence cannot outlive the behaviour. The wording is
    // pinned as a literal beside them: clause (a)'s sweep only checks that NAMES resolve, and
    // this sentence names none. Three facts share one word (`osprey`) and nothing else, so
    // the duplicate gate lets all three in and `k: 1` over the three is the floor's own test.
    const recallTool = S.tools.memory_recall ?? { description: '', inputSchema: { properties: {} } };
    push(
      N('c', 'j64', 'memory_recall-description-wording'),
      'Search persistent memory. Call BEFORE starting a task that resembles past work. Returns the top word matches, never fewer than the store default of 3 when that many match; a query that is exactly a fact\'s name returns that fact alone.',
      recallTool.description ?? '',
      'string',
    );
    push(
      N('c', 'j64', 'memory_recall-k-description-states-the-floor'),
      'Facts wanted. Raised to the store default of 3 when smaller; never lowered below it.',
      recallTool.inputSchema?.properties?.k?.description ?? '',
      'string',
    );
    const floorFacts = [
      ['floor-probe-a', 'osprey alpha wren'],
      ['floor-probe-b', 'osprey beta heron'],
      ['floor-probe-c', 'osprey gamma crane'],
    ];
    const sNamed = await session(ctx, side, {
      name: 'j64-recall-claims',
      env: S.env,
      lines: [
        INIT,
        INITIALIZED,
        ...floorFacts.map(([n, d], i) => callTool(2 + i, 'memory_save', { type: 'project', name: n, description: d, body: `BODY-${n}` })),
        callTool(5, 'memory_recall', { query: 'osprey', k: 1 }),
        callTool(6, 'memory_recall', { query: 'floor-probe-b' }),
      ],
    });
    const heads = (id) => outcome(sNamed, id).text.match(/^\[project\] \[[^\]]+\]/gm) ?? [];
    push(
      N('c', 'j64', 'the-three-probe-facts-were-saved'),
      floorFacts.map(([n]) => `${n}: saved`),
      floorFacts.map(([n], i) => `${n}: ${/^saved /.test(outcome(sNamed, 2 + i).text) ? 'saved' : brief(outcome(sNamed, 2 + i).text)}`),
    );
    push(N('c', 'j64', 'k-1-over-three-matches-answers-three-as-the-description-says'), 3, heads(5).length);
    push(N('c', 'j64', 'an-exact-name-answers-that-fact-alone-as-the-description-says'), ['[project] [floor-probe-b]'], heads(6));

    // -------------------------------------------------------------- (e) advertised-actionable
    const plan = dictOf(sClock, 20);
    const ready = Array.isArray(plan.ready) ? plan.ready : [];
    const others = ready.filter((id) => id !== plan.cursor);
    const planDesc = S.tools.shiftwork_plan?.description ?? '';
    const readyDisclosed = sentenceWith(planDesc, /`?ready`?/, /\bclock/i);
    let clockRefusals = [];
    if (others.length) {
      const copies = others.map((id) => copyTemplate(dir, `row57-${id}`, (doc) => { doc.plan.units[1].depends_on = []; }));
      const sE = await session(ctx, side, {
        name: 'plan-ready-clock-out',
        env: S.env,
        lines: [
          INIT,
          INITIALIZED,
          ...others.map((id, i) => callTool(2 + i, 'shiftwork_clock_out', { checkpoint: copies[i], unit_id: id, ...base, history_entry: { unit: id, outcome: 'ok' } })),
        ],
      });
      clockRefusals = others.map((id, i) => `${id}: ${verdict(dictOf(sE, 2 + i))}`).filter((v) => !v.endsWith(': accepted'));
    }
    push(
      N('e', 'row57', `plan-ready-${JSON.stringify(ready)}-is-clockable-or-the-description-says-not`),
      readyDisclosed ? [`disclosed: ${readyDisclosed}`] : [],
      readyDisclosed ? [`disclosed: ${readyDisclosed}`] : clockRefusals,
    );
    if (!others.length) notes.push(`${side}: shiftwork_plan advertised no unit beyond the cursor on the width-2 checkpoint (ready=${JSON.stringify(ready)}); clause (e) had nothing to clock`);

    // -------------------------------------------------------------- (a) sweeps: every other delivered string
    push(N('a', 'sweep', 'instructions-block'), [], namesIn(S.instructions, S));
    push(
      N('a', 'sweep', 'tool-descriptions-and-schemas'),
      [],
      Object.values(S.tools).flatMap((t) => namesIn(stringsOf(t).join('\n'), S).map((u) => `${t.name}: ${u}`)),
    );
    push(N('a', 'sweep', 'hook-session-start'), [], namesIn(hookStrings['session-start'], S));
    push(N('a', 'sweep', 'hook-read-refusal'), [], namesIn(hookStrings['read-refusal'], S));
    push(N('a', 'sweep', 'hook-stop-nudge'), [], namesIn(hookStrings['stop-nudge'], S));
  }

  // ============================================================ (d) CLAUDE.md commands, from a throwaway worktree

  if (process.platform === 'win32') {
    notes.push('clause (d) skipped on win32: the CLAUDE.md commands are POSIX shell lines');
  } else {
    const commands = [...repoClaudeMd.matchAll(/`([^`\n]+)`/g)]
      .map((m) => m[1])
      .filter((c) => /^(?:cd\s|PYTHONPATH=|BANTAMKIT_\w+=|\.?\.?\/?[\w./-]*(?:python3?|node|npm|npx|git|ruff|pytest)\b)/.test(c) && !/[<>]/.test(c));
    const wt = join(root, 'wt');
    const added = spawnSync('git', ['worktree', 'add', '--detach', wt, 'HEAD'], { cwd: repoRoot, encoding: 'utf8' });
    if (added.status !== 0) {
      notes.push(`clause (d) could not add a throwaway worktree: ${(added.stderr ?? '').trim().slice(0, 300)}`);
    } else {
      try {
        // The throwaway carries the WORKING TREE, not just HEAD: a CLAUDE.md fix that has not
        // been committed yet is the one this clause exists to test.
        const changed = spawnSync('git', ['ls-files', '--modified', '--others', '--exclude-standard', '-z'], { cwd: repoRoot, encoding: 'utf8' }).stdout.split('\0').filter(Boolean);
        for (const rel of changed) {
          if (/^(runtime-ts\/(node_modules|dist)|\.venv|\.shiftwork|\.claude)\//.test(rel)) continue;
          const src = join(repoRoot, rel);
          if (!existsSync(src)) continue;
          mkdirSync(dirname(join(wt, rel)), { recursive: true });
          copyFileSync(src, join(wt, rel));
        }
        const env = { ...process.env };
        delete env.PYTHONPATH;
        delete env.PYTHONSAFEPATH;
        delete env.BANTAMKIT_MEMORY_DIR;
        // Two substitutions, each keeping the property under test and dropping only cost:
        //   * `run.mjs --all` → `--suite workplan`: the row-49 failure is the runner not building
        //     cases from a worktree, and `--all` would recurse into this very suite;
        //   * `-m pytest …` gains `--collect-only`: the row-48 failure is the interpreter path, which
        //     fails before collection; collection still imports every test module.
        for (const [i, command] of commands.entries()) {
          let ran = command;
          if (/tools\/conformance\/run\.mjs\s+--all\b/.test(ran)) ran = ran.replace(/--all\b/, '--suite workplan');
          if (/-m pytest\b/.test(ran) && !/--collect-only/.test(ran)) ran = `${ran} --collect-only`;
          const r = spawnSync('sh', ['-c', ran], { cwd: wt, env, encoding: 'utf8', timeout: COMMAND_TIMEOUT_MS, maxBuffer: 64 * 1024 * 1024 });
          const tail = `${r.stderr ?? ''}${r.stdout ?? ''}`.trim().split('\n').slice(-3).join(' | ').slice(0, 300);
          push(
            `d/claude-md/${String(i + 1).padStart(2, '0')}/${command.replace(/[^\w.-]+/g, '-').slice(0, 60)}`,
            'exit 0 from a throwaway worktree',
            r.status === 0 ? 'exit 0 from a throwaway worktree' : `exit ${r.status ?? `signal ${r.signal}`}: ${tail}`,
            'string',
          );
        }
        notes.push(`clause (d) ran ${commands.length} CLAUDE.md command(s) in document order from ${basename(wt)} (a detached worktree of HEAD plus the working tree's changes)`);
      } finally {
        spawnSync('git', ['worktree', 'remove', '--force', wt], { cwd: repoRoot, encoding: 'utf8' });
        spawnSync('git', ['worktree', 'prune'], { cwd: repoRoot, encoding: 'utf8' });
      }
    }
  }

  return { cases, notes };
}
