/**
 * wire — the two MCP servers, frame for frame.
 *
 * THE PROPERTY: a client cannot tell which runtime answered, except where the two SDKs make
 * that impossible, and every such place is a `ruling` case below with its reason.
 *
 * WHAT IS COMPARED, AND WHY IT IS NOT THE RAW LINE. Both servers are driven with the SAME
 * request bytes, and every stdout line is canonicalised as
 *
 *     dumpJson(parseJson(line), { sortKeys: true, indent: 2 })
 *
 * before the two are compared as exact strings. That canonicaliser is chosen, not
 * convenient. `parseJson` is N6's, so it keeps `5.0` a float and an integer past 2^53 exact
 * — a `JSON.parse`/`JSON.stringify` round trip would erase the one difference this suite was
 * built to catch. Sorting the keys drops JSON object ORDER, which no conforming client can
 * observe and which the SDKs disagree about in exactly one place they both control (the
 * `initialize` result); that disagreement is itself a ruled case, so it is named rather than
 * hidden. Everything else — every string, every number literal, every present-or-absent key
 * — survives the canonicalisation and is compared.
 *
 * PATHS ARE THE SAME PATHS ON BOTH SIDES. Half the sentences on this wire embed an absolute
 * path (`checkpoint unreadable: [Errno 2] ... '/x'`, the empty-store refusal, `log`). So
 * Python runs first over `${scratch}/w<N>`, the directory is deleted and rebuilt, and Node
 * runs over the identical path. Two temp directories would fail this suite for a reason that
 * is not the port's.
 *
 * NOTHING TOUCHES A REAL STORE. `HOME` is redirected to a scratch directory for every
 * session, so `Memory.layered`'s profile layer is an empty scratch store and not the
 * operator's; `cwd` is a scratch project. The real checkpoint is COPIED before it is written.
 *
 * THE EVENT LOG RIDES ON THESE SESSIONS RATHER THAN ON A SUITE OF ITS OWN (`docs/eventlog.md`).
 * The log is a SIDE EFFECT of exactly the sessions above, and a second suite would mean a
 * second copy of the path-identity and `HOME`-redirection machinery — the part most likely to
 * be got subtly wrong, and getting it wrong means a conformance run writing into the
 * operator's real memory store. So one extra session sets `BANTAMKIT_EVENT_LOG` for itself,
 * its `<store>/events/mcp.jsonl` is captured beside the checkpoint, and the two files are
 * compared with only `ts` masked. Every other session leaves the variable unset and is the
 * evidence that OFF IS THE DEFAULT in both runtimes.
 */
import { spawn } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'wire';
export const summary = 'the MCP surface: twelve tools, one prompt, two templates, and the frames themselves';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'wire_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');
/**
 * The tracked template, not the live job checkpoint — same reason as
 * tools/conformance/suites/shiftwork.mjs. `.shiftwork/` is gitignored, so this suite could
 * only ever have run in a checkout that happened to be mid-job, and the live file's
 * `plan.cursor` moves underneath it while the job advances. `cursorUnit` below already
 * reads the cursor out of the document rather than hardcoding it, so nothing else changes.
 */
const REAL_CHECKPOINT = join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json');

/**
 * `docs/eventlog.md`'s switch and its default location, named here rather than spelled twice.
 *
 * OFF IS THE DEFAULT IN BOTH RUNTIMES and this suite is the reason: `run.mjs --all` reads the
 * operator's LIVE memory store by design and read-only, so a log that were on by default
 * would turn every conformance run into a write against real user data. Only the `eventlog`
 * session below sets it, and only for its own scratch store.
 */
const EVENT_LOG_ENV = 'BANTAMKIT_EVENT_LOG';
const EVENT_LOG_RELATIVE = ['events', 'mcp.jsonl'];

/**
 * The one sentence on this wire that names a command for the OPERATOR to run, and the two
 * spellings of it.
 *
 * `index-budget-low` tells whoever is reading the degraded report how to get the index back
 * under its budget. `mcpserver.py` spells that `python -m bantamkit.memory compact`;
 * `runtime-ts/src/mcp/status.ts` spells it `bantamkit-memory compact`, because a pure-npm
 * install has neither the interpreter nor the `bantamkit.memory` module, and an npm install
 * of `bantamkit-mcp` DOES put `bantamkit-memory` on PATH. There is no third spelling either
 * side could print and mean, which is why this is ruled rather than fixed. Same reasoning,
 * same two literals and the same substitution direction as
 * `tools/conformance/suites/memorycli.mjs`, which compares the CLIs those names invoke.
 *
 * A ruling proves the two sides DIFFER and nothing else. So the substitution below is what
 * keeps every other byte of the sentence compared, and the three cases at the bottom of this
 * file pin the sentences themselves: RULED raw, UNRULED after the substitution, and the
 * backticked command on each side against the literal that install actually provides.
 */
const PY_MEMORY_PROG = 'python -m bantamkit.memory';
const NODE_MEMORY_PROG = 'bantamkit-memory';
const substituteMemoryProg = (text) => text.split(PY_MEMORY_PROG).join(NODE_MEMORY_PROG);

/** The `index-budget-low` sentence's opening words, which no other sentence on the wire uses. */
const REMEDY_HEAD = 'the memory index is ';

/**
 * Every `index-budget-low` sentence a session's frames carry, in the order they appear.
 *
 * The frames are walked as PARSED JSON rather than scanned as text, so the copy in the
 * report, the copy in `structuredContent`, the copy in the prompt's message and the copies
 * inside every footer are all found by one rule, none of them through a hand-written escape.
 * The LIST is what the cases compare, not one element of it: a runtime that moved the
 * sentence in the report and left the footer alone changes the list's length, and a runtime
 * that stopped printing it at all produces an empty list, which no other list matches.
 */
function remedySentences(frames) {
  const found = [];
  const walk = (value) => {
    if (typeof value === 'string') {
      for (const part of value.split('\n')) {
        const at = part.indexOf(REMEDY_HEAD);
        if (at !== -1) found.push(part.slice(at));
      }
    } else if (Array.isArray(value)) value.forEach(walk);
    else if (value !== null && typeof value === 'object') Object.values(value).forEach(walk);
  };
  for (const line of frames) {
    try {
      walk(JSON.parse(line));
    } catch {
      /* a line that is not a frame is another case's failure, not this helper's */
    }
  }
  return found;
}

/** The backticked command inside a remedy sentence: the text the operator is told to type. */
const remedyCommands = (sentences) => [...new Set(sentences.map((s) => (/`([^`]*)`/.exec(s) ?? [, null])[1]))];

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');

// ------------------------------------------------------------------- request composition

const INIT = (version = '2025-06-18') =>
  JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: { protocolVersion: version, capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
  });
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const rpc = (id, method, params) =>
  JSON.stringify(params === undefined ? { jsonrpc: '2.0', id, method } : { jsonrpc: '2.0', id, method, params });
const callTool = (id, name_, args) => rpc(id, 'tools/call', { name: name_, arguments: args });

// ------------------------------------------------------------------------- the Node side

/**
 * Drive `dist/cli.js` with the same bytes, holding stdin open until every id has answered.
 *
 * platform-checked: the 60-second `child.kill('SIGKILL')` below is portable, and it is the
 * one shape of signal use that is. Nothing here waits for a HANDLER to run — the kill is a
 * hard stop on a session that has already been declared stuck, and the `reject()` beside it
 * is what reports the failure. `TerminateProcess`, which is what Node maps every signal to on
 * Windows, ends the child just as `SIGKILL` does; a handler would have been the part that did
 * not survive, and there is none. Contrast the 2026-09-05 CI failure this gate was built from,
 * where a watcher WROTE ITS VERDICT from a `SIGTERM` handler and produced nothing on Windows.
 */
function runNode(spec) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS };
    for (const [key, value] of Object.entries(spec.env ?? {})) {
      if (value === null) delete env[key];
      else env[key] = value;
    }
    const child = spawn(process.execPath, [CLI, ...(spec.argv ?? [])], {
      cwd: spec.cwd ?? repoRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const wanted = new Set(
      spec.lines
        .map((line) => {
          try {
            return JSON.parse(line).id;
          } catch {
            return undefined;
          }
        })
        .filter((id) => id !== undefined && id !== null)
        .map((id) => JSON.stringify(id)),
    );
    const frames = [];
    const seen = new Set();
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`wire: node session ${spec.name} timed out\nstderr:\n${err}`));
    }, 60_000);
    let pending = null;
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        frames.push(line);
        try {
          seen.add(JSON.stringify(JSON.parse(line).id));
        } catch {
          /* a non-frame line is itself a failure; the comparison will show it */
        }
      }
      if (pending !== null && seen.has(pending.id)) {
        const resume = pending.resolve;
        pending = null;
        resume();
      }
      if ([...wanted].every((id) => seen.has(id))) child.stdin.end();
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (out !== '') frames.push(out);
      resolve({ name: spec.name, frames, stderr: err, exit: code });
    });
    child.on('error', reject);
    // LOCK-STEP, for the reason `wire_ref.py` gives at length: `MCPServer` answers a
    // pipelined batch concurrently, so a `recall` sent behind a `save` can be answered from
    // the store as it stood before it. One request at a time is the only shape in which the
    // two runtimes are being asked about the same state.
    void (async () => {
      for (const line of spec.lines) {
        if (child.exitCode !== null) break;
        let id = null;
        try {
          const parsed = JSON.parse(line);
          // A HARNESS DIRECTIVE, not a request: performed here and never written to stdin.
          // A session that must rewrite a file mid-session sends one; `ref/wire_ref.py`'s
          // `_run_session` performs the same line, so both servers meet the same disk state.
          if (parsed && parsed.conformance === 'write') {
            writeFileSync(parsed.path, Buffer.from(parsed.b64, 'base64'));
            continue;
          }
          if (parsed.id !== undefined && parsed.id !== null) id = JSON.stringify(parsed.id);
        } catch {
          /* a deliberately malformed line still goes down the pipe */
        }
        child.stdin.write(`${line}\n`);
        if (id !== null && !seen.has(id)) {
          await new Promise((resolve) => {
            pending = { id, resolve };
          });
        }
      }
    })();
  });
}

// ------------------------------------------------------------------------------ the run

export async function run(ctx) {
  const { dumpJson, parseJson } = await import(pathToFileURL(join(repoRoot, 'runtime-ts', 'dist', 'pyjson.js')).href);
  /**
   * One frame, key-sorted and re-indented, with every number literal intact.
   *
   * A frame that does not parse comes back tagged rather than throwing: a server that put a
   * log line on stdout must fail as a DIFFERENCE naming the line, not as a harness crash.
   */
  const canonical = (line) => {
    try {
      return dumpJson(parseJson(line), { sortKeys: true, indent: 2 });
    } catch (e) {
      return `NOT-A-FRAME(${e.message}): ${line}`;
    }
  };

  const scratch = ctx.scratch;
  const home = join(scratch, 'home');
  const project = join(scratch, 'project');
  const store = join(scratch, 'store');
  const checkpoint = join(scratch, 'cp.json');
  const missing = join(scratch, 'nope', 'gone.json');

  /**
   * THE ONE FILE ON DISK A SESSION NAMES, written ONCE outside `setup()` because nothing reads
   * it for writing: both servers are handed the same absolute path. It exists so that the
   * `retired` session's `bantamkit_read` call is a call the tool WOULD have answered — a
   * readable file — and its refusal is therefore the roster's doing and not the reader's.
   * `docs` is also the parent `skill_audit` is pointed at for its missing-catalogue refusal.
   */
  const docs = join(scratch, 'docs');
  mkdirSync(docs, { recursive: true });
  const doc = (file, bytes) => {
    writeFileSync(join(docs, file), bytes);
    return join(docs, file);
  };
  const notesMd = doc('notes.md', '# Title\n\nline one\nline two — ทดสอบ\n');

  /**
   * `skill_audit`'s corpus is the COMMITTED fixture tree, read where it lives.
   *
   * Not copied into scratch like the checkpoint: nothing in this session writes, the tree is
   * tracked, and `roots[0]` echoes the path back into the document both sides are compared
   * on — so it has to be one path, not two. `enabled.json` and `usage.json` are the caller's
   * two maps, handed to the tool as arguments exactly as `docs/skill-audit` says a host would.
   */
  const SKILL_FIXTURE = join(repoRoot, 'tools', 'conformance', 'fixtures', 'skill-audit');
  const SKILL_CACHE = join(SKILL_FIXTURE, 'cache');
  const SKILL_ENABLED = JSON.parse(readFileSync(join(SKILL_FIXTURE, 'enabled.json'), 'utf8'));
  const SKILL_USAGE = JSON.parse(readFileSync(join(SKILL_FIXTURE, 'usage.json'), 'utf8'));
  const SKILL_VERSIONS = JSON.parse(readFileSync(join(SKILL_FIXTURE, 'versions.json'), 'utf8'));

  const baseEnv = { HOME: home, USERPROFILE: home, BANTAMKIT_MEMORY_DIR: null, BANTAMKIT_ASSETS: ASSETS };

  /**
   * The same pack, plus the bytecode cache `pip install` leaves in it.
   *
   * The pack ships `.py` fixture files, so installing the wheel byte-compiles them and the
   * installed pack gains a `__pycache__` the npm pack never has. Measured on the published
   * 0.27.0 artifacts: the Python endpoint reported `sha256:fa8372f6…` over 98 files where
   * Node reported `sha256:d47dcf4b…` over 87, and `cross_runtime` was at that moment telling
   * callers that `assets_digest` is the field to compare across runtimes. Both runtimes now
   * exclude `__pycache__`, and this pack is what makes that comparable rather than asserted.
   *
   * It is a REAL directory rather than a mocked walk because the defect lived in the walk.
   * The `.pyc` payloads are not valid bytecode and do not need to be: nothing imports them,
   * and a digest over bytes cannot tell a real cache from these.
   */
  const PYCACHE_ASSETS = join(scratch, 'assets-with-pycache');
  const PYCACHE_DIR = join(PYCACHE_ASSETS, 'evals', 'devteam', 'repo', 'src', 'ledger', '__pycache__');

  /** Rebuild the on-disk world both runtimes are pointed at, from nothing. */
  const setup = () => {
    for (const dir of [home, project, store]) {
      rmSync(dir, { recursive: true, force: true });
      mkdirSync(dir, { recursive: true });
    }
    rmSync(checkpoint, { force: true });
    rmSync(`${checkpoint}.log.jsonl`, { force: true });
    cpSync(REAL_CHECKPOINT, checkpoint);
    rmSync(PYCACHE_ASSETS, { recursive: true, force: true });
    cpSync(ASSETS, PYCACHE_ASSETS, { recursive: true });
    mkdirSync(PYCACHE_DIR, { recursive: true });
    for (const stem of ['config', 'errors', 'posting']) {
      writeFileSync(join(PYCACHE_DIR, `${stem}.cpython-312.pyc`), `not real bytecode: ${stem}\n`);
    }
  };

  const cursorUnit = JSON.parse(readFileSync(REAL_CHECKPOINT, 'utf8')).plan.cursor;

  // ------------------------------------------------------------------------- sessions

  const sessions = [];
  const add = (name_, lines, over = {}) =>
    sessions.push({ name: name_, argv: ['--store', store], env: baseEnv, cwd: project, lines, ...over });

  add('handshake', [INIT(), INITIALIZED, rpc(2, 'ping')]);

  add('advertisement', [
    INIT(),
    INITIALIZED,
    rpc(2, 'tools/list'),
    rpc(3, 'resources/templates/list'),
    rpc(4, 'resources/list'),
    rpc(5, 'prompts/list'),
  ]);

  add('resources', [
    INIT(),
    INITIALIZED,
    rpc(2, 'resources/read', { uri: 'bantamkit://skills/memory' }),
    rpc(3, 'resources/read', { uri: 'bantamkit://skills/file-graph' }),
    rpc(4, 'resources/read', { uri: 'bantamkit://rubrics/code-quality' }),
    rpc(5, 'resources/read', { uri: 'bantamkit://rubrics/task-completion' }),
    rpc(6, 'resources/read', { uri: 'bantamkit://skills/nosuch' }),
    rpc(7, 'resources/read', { uri: 'bantamkit://rubrics/nosuch' }),
    rpc(8, 'resources/read', { uri: 'bantamkit://other/x' }),
    // The template variable matches ONE segment, so a traversal is not a match at all.
    rpc(9, 'resources/read', { uri: 'bantamkit://skills/../../etc/passwd' }),
    rpc(10, 'resources/read', { uri: 'bantamkit://skills/' }),
  ]);

  add('memory-store', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_recall', { query: 'anything at all' }),
    callTool(3, 'memory_save', { type: 'project', name: 'Wire_Case One', description: 'the wire, byte for byte — ทดสอบ', body: 'a fact with an em dash — and a DEL \u007f', links: ['other-fact'] }),
    callTool(4, 'memory_recall', { query: 'wire byte' }),
    // SIX facts sharing one token, so the RECALL BUDGET is observable: the default is 3, the
    // advertised ceiling is 5, and `k` is clamped to it. With fewer facts than the budget
    // every setting returns the same list and the clamp is unmeasurable — which is exactly
    // how a mutation that deleted it survived the first sweep.
    callTool(5, 'memory_save', { type: 'project', name: 'budget-a', description: 'budget probe alpha', body: 'a' }),
    callTool(6, 'memory_save', { type: 'project', name: 'budget-b', description: 'budget probe bravo', body: 'b' }),
    callTool(7, 'memory_save', { type: 'project', name: 'budget-c', description: 'budget probe charlie', body: 'c' }),
    callTool(8, 'memory_save', { type: 'project', name: 'budget-d', description: 'budget probe delta', body: 'd' }),
    callTool(9, 'memory_save', { type: 'project', name: 'budget-e', description: 'budget probe echo', body: 'e' }),
    callTool(10, 'memory_save', { type: 'project', name: 'budget-f', description: 'budget probe foxtrot', body: 'f' }),
    callTool(11, 'memory_recall', { query: 'budget probe' }),
    callTool(12, 'memory_recall', { query: 'budget probe', k: 5 }),
    callTool(13, 'memory_recall', { query: 'budget probe', k: 99 }),
    callTool(14, 'memory_recall', { query: 'budget probe', k: 1 }),
    callTool(15, 'memory_save', { type: 'bogus', name: 'x', description: 'd', body: 'b' }),
    callTool(16, 'memory_save', { type: 'project', name: 'wire-case-one', description: 'the wire, byte for byte — ทดสอบ', body: 'updated' }),
    callTool(17, 'memory_recall', { query: 'nothing like this exists' }),
  ]);

  // PRODUCTION SHAPE: no `--store`, so `Memory.layered` runs and recall lines carry `[project] `.
  sessions.push({
    name: 'memory-layered',
    argv: [],
    env: baseEnv,
    cwd: project,
    lines: [
      INIT(),
      INITIALIZED,
      callTool(2, 'memory_recall', { query: 'anything at all' }),
      callTool(3, 'memory_save', { type: 'feedback', name: 'layered', description: 'the layered path', body: 'body' }),
      callTool(4, 'memory_recall', { query: 'layered path' }),
      // PRODUCTION SHAPE for `memory_compact` too: `Memory.layered` binds the profile layer
      // (an empty scratch store under the redirected `HOME`) and the tool reaches only the
      // writable project store. The `memory-compact` session below is where the store is
      // actually driven over its budget; this call is the layered path answering at all.
      callTool(5, 'memory_compact', {}),
    ],
  });

  add('validate', [
    INIT(),
    INITIALIZED,
    callTool(2, 'validate_json', { output: '{"a": 1}', schema: { type: 'object', required: ['b'] } }),
    callTool(3, 'validate_json', { output: '{"a": 1}', schema: { type: 'object', properties: { a: { type: 'string' } } } }),
    callTool(4, 'validate_json', { output: 'not json at all', schema: { type: 'object' } }),
    callTool(5, 'validate_json', { output: 'prose then {"a": 1} then more', schema: { type: 'object' } }),
    callTool(6, 'validate_json', { output: '{}', schema: {} }),
    callTool(7, 'validate_json', { output: '{"a": {"b": [1, 2]}}', schema: { type: 'object', properties: { a: { type: 'object', properties: { b: { type: 'array', items: { type: 'string' } } } } } } }),
  ]);

  add('shiftwork', [
    INIT(),
    INITIALIZED,
    callTool(2, 'shiftwork_status', { checkpoint: checkpoint }),
    callTool(3, 'shiftwork_clock_in', { checkpoint: checkpoint }),
    callTool(4, 'shiftwork_status', { checkpoint: missing }),
    callTool(5, 'shiftwork_clock_in', { checkpoint: missing }),
    callTool(6, 'shiftwork_clock_out', { checkpoint: checkpoint, unit_id: 'NOPE', status: 'done', handoff_patch: {}, history_entry: { unit: 'NOPE', outcome: 'x' } }),
    // The float is written by hand: `JSON.stringify` would emit `5` and the whole case is
    // about the literal surviving from the request line to the `.log.jsonl`.
    callTool(7, 'shiftwork_clock_out', {
      checkpoint,
      unit_id: cursorUnit,
      status: 'done',
      handoff_patch: { next_action: 'the wire suite wrote this — ทดสอบ' },
      // THE NUMERIC CORPUS RIDES IN `history_entry`, not in `accounting`, and that is the
      // point: `accounting` only ever reaches the `.log.jsonl`, while `history_entry` is
      // echoed back by `shiftwork_status` as `last_history` and therefore lands in
      // `structuredContent` — the one place a float has to survive OUTBOUND as well as
      // inbound. `1e-5` and `1e-6` straddle serde's decimal/scientific boundary, `1e+300`
      // and `-0.0` and 2^53+1 are the other three shapes `JSON.stringify` gets wrong.
      history_entry: {
        unit: cursorUnit,
        outcome: 'done',
        duration_min: 5.0,
        ratio: 0.5,
        tiny: 1e-5,
        tinier: 1e-6,
        huge: 1e300,
        negzero: -0.0,
        big: 9007199254740993,
        nested: { seen: [1.0, 2.5, 100.0] },
      },
      accounting: { tokens: 1000, duration_min: 5.0, ratio: 0.5, big: 9007199254740993 },
    })
      .replace(/"duration_min":5,/g, '"duration_min":5.0,')
      .replace(/"big":9007199254740992/g, '"big":9007199254740993')
      .replace('"negzero":0', '"negzero":-0.0')
      .replace('"seen":[1,2.5,100]', '"seen":[1.0,2.5,100.0]'),
    callTool(8, 'shiftwork_status', { checkpoint: checkpoint }),
    callTool(9, 'shiftwork_clock_in', { checkpoint: checkpoint }),
  ]);

  add('argument-refusals', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_recall', { query: 123 }),
    callTool(3, 'memory_recall', {}),
    rpc(4, 'tools/call', { name: 'memory_recall' }),
    callTool(5, 'memory_recall', { query: null }),
    callTool(6, 'memory_recall', { query: ['a'] }),
    callTool(7, 'memory_recall', { query: { a: 1 } }),
    callTool(8, 'memory_recall', { query: 'a', k: 2.5 }),
    callTool(9, 'memory_recall', { query: 'a', k: 'notanint' }),
    callTool(10, 'memory_recall', { query: 'a', k: [1] }),
    callTool(11, 'memory_recall', { query: 'a', k: true }),
    callTool(12, 'memory_recall', { query: 'a', k: '  3  ' }),
    callTool(13, 'memory_recall', { query: 'a', k: '3.0' }),
    callTool(14, 'memory_recall', { query: 'a', k: '2_0' }),
    callTool(15, 'memory_recall', { query: 'a', k: null }),
    callTool(16, 'memory_save', {}),
    callTool(17, 'memory_save', { body: 'b', name: 1, description: 'd', type: 2 }),
    callTool(18, 'memory_save', { type: 'project', name: 'n', description: 'd', body: 'b', links: 'notalist' }),
    callTool(19, 'memory_save', { type: 'project', name: 'n', description: 'd', body: 'b', links: [1, 'ok', null, 2.5] }),
    callTool(20, 'validate_json', { output: 1, schema: [] }),
    callTool(21, 'validate_json', { output: '{}', schema: 'notadict' }),
    callTool(22, 'shiftwork_clock_out', { checkpoint: '/x', unit_id: 'A', status: 'd', handoff_patch: null, history_entry: {} }),
    callTool(23, 'shiftwork_clock_out', { checkpoint: '/x', unit_id: 'A', status: 'd', handoff_patch: {}, history_entry: {}, accounting: 5 }),
    // Over 50 UTF-8 bytes of `repr`, which is where pydantic truncates.
    callTool(24, 'memory_recall', { query: { a: 'b'.repeat(43) } }),
    callTool(25, 'memory_recall', { query: ['ก'.repeat(30)] }),
    callTool(26, 'memory_recall', { query: { 'ก': 'ข'.repeat(40) } }),
    callTool(27, 'memory_recall', { query: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] }),
    callTool(28, 'memory_recall', { query: 'a', extra: 1 }),
  ]);

  add('unknown-tools', [
    INIT(),
    INITIALIZED,
    callTool(2, 'document_read', { path: 'x' }),
    callTool(3, 'document_list', {}),
    callTool(4, 'file_graph', {}),
    callTool(5, 'nope', {}),
    callTool(6, '', {}),
  ]);

  add('unknown-methods', [
    INIT(),
    INITIALIZED,
    rpc(2, 'logging/setLevel', { level: 'debug' }),
    rpc(3, 'completion/complete', { ref: { type: 'ref/resource', uri: 'bantamkit://skills/{name}' }, argument: { name: 'name', value: 'm' } }),
    rpc(4, 'resources/subscribe', { uri: 'bantamkit://skills/memory' }),
    rpc(5, 'nosuch/method'),
  ]);

  add('bad-params', [INIT(), INITIALIZED, rpc(2, 'tools/call', { name: 'memory_recall', arguments: 'notanobject' })]);

  add('identity', [INIT(), INITIALIZED, callTool(2, 'build_identity', {})]);
  add('identity-pycache', [INIT(), INITIALIZED, callTool(2, 'build_identity', {})], {
    env: { ...baseEnv, BANTAMKIT_ASSETS: PYCACHE_ASSETS },
  });

  /**
   * `bantamkit_status`, its prompt, and the degraded footer — in the TWO STATES that are the
   * only proof the footer is conditional (`docs/status.md`).
   *
   * ONE MASK AND ONE ONLY. Line 2 of the report carries `build_id`, which fingerprints the
   * executing tree, and these are two trees — `docs/porting.md`'s divergence table already
   * rules exactly that, and `assets_digest` is the field that IS identical. So the digest is
   * masked and every other byte of both reports is compared. A SECOND mask would not be a
   * fix: it would mean something is diverging that the contract says should not.
   *
   * AND ONE SUBSTITUTION, ON THE REFERENCE SIDE OF `status-degraded` ONLY. The
   * `index-budget-low` remedy names a command for the operator to RUN, and the two installs
   * provide different ones: `python -m bantamkit.memory compact` where there is an
   * interpreter and a `bantamkit.memory` module, `bantamkit-memory compact` where there is
   * an npm `bin`. Ruled in `docs/porting.md`; `substituteMemoryProg` below is what lets the
   * rest of the sentence — the two byte counts, the wording, the footer it rides in and the
   * count of places it appears — still be compared as bytes. It is a `refMask` and NOT a
   * `mask`: applied to the reference only, so a Node report that regressed to spelling
   * `python -m …` would go red on these frames rather than be normalised into agreement.
   * `status-active` deliberately does NOT carry it — a remedy that leaked into a HEALTHY
   * report should fail this suite, not be substituted inside it.
   *
   * THE STRADDLE IS ONE BYTE OF BUDGET WIDE, and both sides of it are driven. One
   * `memory_save` writes a 46-byte `index.md`; 46 * 100 = 4600, so at a 51-byte budget
   * 90 * 51 = 4590 <= 4600 and the store is degraded, while at 52 it is 4680 > 4600 and it is
   * not. The comparison is integer cross-multiplication in both runtimes precisely so that
   * one byte either way lands on the same side in both — a float each had rounded its own way
   * is the defect this shape exists to make impossible, and a threshold asserted from one side
   * only is a threshold that could be anywhere below it.
   *
   * The tool calls that follow are the two RESULT KINDS the footer reaches differently: prose
   * (`memory_save`, `memory_recall`) takes `reply + "\n\n" + notice`, and structured
   * (`validate_json`, `shiftwork_status`) takes a `bantamkit_degraded` key, last. `build_identity`
   * is the third structured tool and is deliberately NOT here — its reply is ruled
   * un-comparable, so the footer on it is pinned by `runtime-ts/test/server.test.mjs` instead.
   */
  const STATUS_LINES = [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_save', { type: 'project', name: 'status-probe', description: 'a probe fact', body: 'body' }),
    callTool(3, 'bantamkit_status', {}),
    rpc(4, 'prompts/get', { name: 'bantamkit_status' }),
    callTool(5, 'memory_recall', { query: 'probe' }),
    callTool(6, 'validate_json', { output: '{}', schema: { type: 'object' } }),
    callTool(7, 'shiftwork_status', { checkpoint: checkpoint }),
  ];
  const maskBuild = (text) => text.replace(/build sha256:[0-9a-f]{64}/g, 'build sha256:<masked>');
  add('status-active', STATUS_LINES, {
    argv: ['--store', store, '--index-budget', '52'],
    mask: maskBuild,
  });
  add('status-degraded', STATUS_LINES, {
    argv: ['--store', store, '--index-budget', '51'],
    mask: maskBuild,
    refMask: substituteMemoryProg,
  });

  /**
   * THE EVENT LOG: one session, every outcome the host collapses into "completed
   * successfully", and the file both runtimes write compared byte for byte.
   *
   * The variable is set for THIS SESSION ONLY. `--store store` puts the log at the default
   * `<store>/events/mcp.jsonl`, which `setup()` already deletes and rebuilds between the two
   * runs, so the two files are written to the identical absolute path — the same reason the
   * rest of this suite runs both sides over `${scratch}/w<N>`.
   *
   * SEQUENTIAL BY CONSTRUCTION, and that is load-bearing for `index_bytes`. U5 measured that
   * the field is sampled AFTER the decision rather than transactionally: two saves pipelined
   * without waiting both recorded the same `index_bytes`, and a recall sent last was logged
   * first. `outcome` stayed faithful in every case. The driver above is lock-step — one
   * request written, then awaited — so every record here is about the store as it stood when
   * the decision was made, and `index_bytes` is compared rather than masked.
   *
   * The calls are chosen to reach every branch that decides an outcome without matching text:
   * the three-way empty verdict, all four `save` outcomes, both `validate_json` bools, the
   * register's own `result` on a good and on a missing checkpoint, and `build_identity`'s
   * count of underivable fields.
   */
  sessions.push({
    name: 'eventlog',
    argv: ['--store', store],
    env: { ...baseEnv, [EVENT_LOG_ENV]: '1' },
    cwd: project,
    lines: [
      INIT(),
      INITIALIZED,
      callTool(2, 'memory_recall', { query: 'anything at all' }),
      callTool(3, 'memory_save', { type: 'project', name: 'wire-event-one', description: 'the event log, byte for byte — ทดสอบ', body: 'a fact with an em dash — and a DEL ' }),
      callTool(4, 'memory_recall', { query: 'event log byte' }),
      callTool(5, 'memory_save', { type: 'project', name: 'wire-event-two', description: 'the event log, byte for byte — ทดสอบ', body: 'a near-duplicate of the one above' }),
      callTool(6, 'memory_save', { type: 'bogus', name: 'x', description: 'd', body: 'b' }),
      callTool(7, 'memory_recall', { query: 'nothing like this exists' }),
      callTool(8, 'validate_json', { output: '{"a": 1}', schema: { type: 'object' } }),
      callTool(9, 'validate_json', { output: 'not json at all', schema: { type: 'object' } }),
      callTool(10, 'shiftwork_status', { checkpoint: checkpoint }),
      callTool(11, 'shiftwork_status', { checkpoint: missing }),
      callTool(12, 'shiftwork_clock_in', { checkpoint: checkpoint }),
    ],
  });

  /**
   * The fourth `save` outcome, which needs a budget too small for its own index to fit.
   *
   * `docs/eventlog.md` calls `Memory.save` the sharpest case in the table — four outcomes,
   * one word to the host — so all four are compared, and this is the only one that cannot
   * share a process with the other three because the budget is fixed at construction.
   */
  add('eventlog-budget', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_save', { type: 'project', name: 'wire-event-one', description: 'the event log, byte for byte — ทดสอบ', body: 'body' }),
  ], { argv: ['--store', store, '--index-budget', '20'], env: { ...baseEnv, [EVENT_LOG_ENV]: '1' } });

  /**
   * `memory_compact`, the ninth tool, driven through the one story it exists for
   * (`docs/memory.md`): a save is refused for budget, the refusal names the tool, the tool
   * archives, the retry lands. Then every shape of `reserve`.
   *
   * THE BUDGET IS 320 BYTES AND THE LINES ARE ~53, measured on the reference before the
   * session was written: five `compaction probe <word>` saves put `index.md` at 266 bytes;
   * the sixth would make it 321 and is refused; the default `reserve` is the largest line
   * the store holds (55), so the target is 265 and the 266-byte index is one byte over it —
   * `memory_compact` archives exactly ONE fact, the stalest, and the retry fits. One byte
   * either way on either side is a different reply and a different event-log record. The
   * reply embeds `archive_dir`, an absolute path, which is why this suite runs both sides
   * over the identical `${scratch}/store`.
   *
   * AMENDED (job46, J46-6). THE TARGET ARITHMETIC IN THE PARAGRAPH ABOVE IS NO LONGER THE
   * ARITHMETIC THIS SESSION RUNS, and it stays because it is the measurement the session was
   * built on. "the default `reserve` is the largest line the store holds (55), so the target
   * is 265" was true until `87cc1f7` / `55575c3`; since then the default `reserve` is
   * `(budget - undegraded_index_ceiling(budget)) + largest line`, which at 320 is
   * (320 - 287) + 55 = 88 and puts the target at 232 rather than 265.
   *
   * WHAT DID NOT CHANGE IS THIS SESSION'S ANSWER, and that is worth stating rather than
   * leaving to be re-derived: 266 is above BOTH targets and one 53-byte archive lands at 213,
   * which is under both, so exactly one fact still moves and every literal below still reads
   * the same. This session is therefore NOT the one that measures the change — a session
   * whose answer is the same on either side of a fix cannot be. `index-band` below is, and it
   * is built to sit in the band this one is nowhere near: at a 320-byte budget the band
   * `[0.9 * budget, budget - largest line]` = [288, 265] is EMPTY, because 320 < 10 * 55.
   * The `reserve: 9999` arm is untouched for a different reason — an explicit `reserve` opts
   * out of the new floor, so its cap at `budget // 2` = 160 is the same number it always was.
   *
   * THE EVICTION ORDER MUST NOT DEPEND ON THE WALL-CLOCK DATE OF THE RUN. The staleness key
   * is `(last_recalled or created, name)`, and every date in this session is "today" — so a
   * midnight between the saves and a recall that stamped SOME survivors would make the
   * unstamped ones the stalest and move the archive listing. The recall at id 11 therefore
   * asks for `k: 5`, every fact left in the index, and stamps all five in ONE call: after it
   * the five share a date whatever the calendar did, and the name alone decides.
   *
   * `reserve` then takes every shape `k` does in `argument-refusals`: `0` (the target is
   * the budget itself), `9999` (capped at half the budget, 160, which the three survivors'
   * lines reach by equality, so two more leave — `compact-b` and `-c`, the first two names
   * among five equally-stale facts — and the archive holds `-a`, `-b`, `-c`), a negative
   * (clamped to 0 by `MemoryStore.compact` on both sides — the manifest's `minimum: 0` is advisory to the client),
   * `2.5` (`int_from_float`), `'notanint'` (`int_parsing`), `true` (lax `int`, so 1),
   * `null` (the default), `'3.0'` (lax again), no `arguments` at all, and an extra key.
   *
   * THE EVENT LOG IS ON for this session so the `archived` / `nothing-archived` records —
   * the outcome the host collapses into "completed successfully" — are compared byte for
   * byte below, `ts` masked, beside the fourth `save` outcome they answer.
   */
  add('memory-compact', [
    INIT(),
    INITIALIZED,
    callTool(2, 'memory_compact', {}),
    callTool(3, 'memory_save', { type: 'project', name: 'compact-a', description: 'compaction probe alpha', body: 'alpha' }),
    callTool(4, 'memory_save', { type: 'project', name: 'compact-b', description: 'compaction probe bravo', body: 'bravo' }),
    callTool(5, 'memory_save', { type: 'project', name: 'compact-c', description: 'compaction probe charlie', body: 'charlie' }),
    callTool(6, 'memory_save', { type: 'project', name: 'compact-d', description: 'compaction probe delta', body: 'delta' }),
    callTool(7, 'memory_save', { type: 'project', name: 'compact-e', description: 'compaction probe echo', body: 'echo' }),
    callTool(8, 'memory_save', { type: 'project', name: 'compact-f', description: 'compaction probe foxtrot', body: 'foxtrot' }),
    callTool(9, 'memory_compact', {}),
    callTool(10, 'memory_save', { type: 'project', name: 'compact-f', description: 'compaction probe foxtrot', body: 'foxtrot' }),
    callTool(11, 'memory_recall', { query: 'compaction probe alpha', k: 5 }),
    callTool(12, 'memory_compact', { reserve: 0 }),
    callTool(13, 'memory_compact', { reserve: 9999 }),
    callTool(14, 'memory_compact', { reserve: -5 }),
    callTool(15, 'memory_compact', { reserve: 2.5 }),
    callTool(16, 'memory_compact', { reserve: 'notanint' }),
    callTool(17, 'memory_compact', { reserve: true }),
    callTool(18, 'memory_compact', { reserve: null }),
    callTool(19, 'memory_compact', { reserve: '3.0' }),
    rpc(20, 'tools/call', { name: 'memory_compact' }),
    callTool(21, 'memory_compact', { extra: 1 }),
    callTool(22, 'memory_compact', { reserve: [1] }),
  ], { argv: ['--store', store, '--index-budget', '320'], env: { ...baseEnv, [EVENT_LOG_ENV]: '1' } });

  /**
   * THE BAND: the report warns, the remedy it names runs, and the warning goes away.
   *
   * This is `docs/porting.md` register item 7 turned into a comparison. The register's own
   * words: `index-budget-low` fires at `INDEX_PRESSURE_PERCENT` (90) percent of the budget and
   * NAMES `compact`, while `compact`'s default target sat at `budget - largest index line` —
   * so everything between the two was a band in which the command the operator was told to run
   * exited 0 having archived nothing. `87cc1f7` and `55575c3` closed it on the two sides by
   * measuring the default `reserve` from the warning line instead of from the budget. Nothing
   * in this repository compared the two answers until this session, and the unit that changed
   * the reference verified with `pytest`, which does not run this harness at all.
   *
   * THE FIXTURE IS BUILT TO SIT INSIDE THE BAND, AND EVERY EDGE OF IT IS DERIVED. A band
   * exists at all only when `budget >= 10 * largest line`, because it is `[0.9 * budget,
   * budget - largest line]` and below that the interval is empty. So:
   *
   *   - seven `feedback` facts whose index lines are 105 bytes and five `project` facts whose
   *     lines are 52, for an index of 7*105 + 5*52 = 995 bytes against a budget of 1101;
   *   - the LOWER edge: 995 * 100 = 99500 >= 90 * 1101 = 99090, so the store is degraded and
   *     `bantamkit_status` prints the sentence naming the remedy;
   *   - the UPPER edge: the OLD default target was `budget - largest line` = 1101 - 105 = 996,
   *     and 995 < 996, so the old `compact` archived NOTHING here. The fixture is strictly
   *     inside the band rather than on either edge of it, which is what stops the case being
   *     the kind whose fixture agrees with the threshold by coincidence.
   *
   * 1101 IS NOT A ROUND NUMBER ON PURPOSE: 90 * 1101 = 99090 is not divisible by 100, so the
   * ceiling is a real floor division (990, not 990.9) rather than an exact one. The `- 1` in
   * `undegraded_index_ceiling` is invisible at this budget and is swept separately, over the
   * multiples of ten, by `store.mjs` — see the corpus-membership case there.
   *
   * THE ORDER IS THE OTHER HALF, and the names are chosen so a wrong order is visible rather
   * than merely different. Every fact is saved on the same day, so the staleness key falls
   * back to the name, and `band-f*` sorts BEFORE `band-p*`: an eviction order that ignored the
   * class would archive `band-f1, band-f2, band-f3` — the user's standing instructions. What
   * both runtimes must archive is `band-p1, band-p2, band-p3`, in that order, with all seven
   * feedback facts left in the index and two project facts still standing, so the loop is seen
   * to have STOPPED at the target rather than run out of candidates.
   *
   * ONE MASK AND ONE SUBSTITUTION, both the same as `status-degraded`'s and for the same
   * reasons: `build sha256:` fingerprints two different trees, and the remedy sentence names
   * the command THIS install provides.
   */
  const bandDesc = (word, n) => `${word} ${word.repeat(40)}`.slice(0, n);
  const BAND_FEEDBACK = ['alfa', 'bravo', 'coral', 'delta', 'ember', 'falcon', 'gamma'];
  const BAND_PROJECT = ['hotel', 'india', 'juliet', 'kilo', 'lima'];
  add('index-band', [
    INIT(),
    INITIALIZED,
    // A `feedback` line is `- [[<name>]] (feedback) — <description>\n`: 15 fixed bytes (the em
    // dash is three of them) plus the name, the type word and the description. 7 + 8 + 75 + 15
    // = 105. A `project` line is 7 + 7 + 23 + 15 = 52. Every description is built from a word
    // no other fact uses, because `memory_save` DEDUPES on token overlap and twelve facts
    // padded from one phrase would be eleven refusals and an empty band.
    ...BAND_FEEDBACK.map((word, i) =>
      callTool(2 + i, 'memory_save', { type: 'feedback', name: `band-f${i + 1}`, description: bandDesc(word, 75), body: 'b' }),
    ),
    ...BAND_PROJECT.map((word, i) =>
      callTool(9 + i, 'memory_save', { type: 'project', name: `band-p${i + 1}`, description: bandDesc(word, 23), body: 'b' }),
    ),
    callTool(14, 'bantamkit_status', {}),
    callTool(15, 'memory_compact', {}),
    callTool(16, 'bantamkit_status', {}),
    callTool(17, 'memory_compact', {}),
  ], {
    argv: ['--store', store, '--index-budget', '1101'],
    mask: maskBuild,
    refMask: substituteMemoryProg,
  });

  /**
   * THE RETIRED TOOLS, on the wire — job50 I5, the user's ruling of 2026-09-12.
   *
   * `bantamkit_read` (once tenth) and `repo_map` (once thirteenth) left both rosters. Their
   * assets stayed and claim no surface, their handlers are DORMANT rather than deleted, and the
   * reader's parity is still gated at the library layer in `tools/conformance/suites/docread.mjs`.
   * What this session pins is the half of a retirement that `tools/list` cannot show: that
   * calling either name is REFUSED, on both sides, with the same words — inspected as literals
   * in the `retired` block below, and frame for frame by the generic loop.
   *
   *   2  `repo_map` with the argument it used to accept (an existing directory);
   *   3  `bantamkit_read` with the argument it used to accept (an existing, readable file) — a
   *      server that still dispatched off its argument model would answer a manifest here;
   *   4  `bantamkit_read` with NO arguments — the roster check has to come BEFORE validation,
   *      so this is `Unknown tool:` and not the validator's `path` sentence;
   *   5  a name that never existed, the control.
   *
   * THE EVENT LOG IS ON so that "nothing was recorded" is a measured zero and not an absence.
   *
   * This session REPLACES the six `bantamkit_read` sessions that used to sit here (`read`,
   * `read-ruled`, `read-edges`, `read-round2`, `read-round3`, `read-cache`: 65 calls to the
   * tool). Measured on 2026-09-13, before this edit: 53 of this suite's 458 cases were red,
   * every one of them in those six sessions or the fourteen-tool pin — every literal described
   * a reader that no longer answers, and every `ruling:` had gone STALE because both sides now
   * say the same four words. They were not gating a retired tool; they were failing, and the
   * reader they described is gated where it still runs. The harness directive both drivers
   * perform (`{"conformance":"write",...}`) stays supported for the next session that needs
   * a file rewritten mid-session; nothing here uses it today.
   */
  add('retired', [
    INIT(),
    INITIALIZED,
    callTool(2, 'repo_map', { root: project }),
    callTool(3, 'bantamkit_read', { path: notesMd }),
    callTool(4, 'bantamkit_read', {}),
    callTool(5, 'no_such_tool', {}),
  ], { env: { ...baseEnv, [EVENT_LOG_ENV]: '1' } });

  /**
   * `skill_audit`, the eleventh tool, over the committed fixture tree: every branch it has.
   *
   *   2     the README's own configuration — `enabled` + `usage` + a budget under the bill —
   *         so the whole JSON document, findings and omissions and all, is compared verbatim;
   *   3-5   the three `check` families, which select findings and never the measurement;
   *   6-7   `enabled` omitted (the disabled plugin joins the count) and `enabled` empty
   *         (only the skill outside a plugin survives) — two states, not one;
   *   8-9   `usage` omitted (no `never-invoked` at all) and `usage` empty (every counted
   *         skill is one), which is the same distinction for the other map;
   *   10-11 no budget at all, and a budget exactly equal to the bill — neither fires;
   *   12-14 three of the refusals the module authors, reaching the model as `tool_failed`
   *         sentences and NOT as `isError` frames: an unknown `check`, a negative `budget`,
   *         a root that is not there;
   *   15-19 the argument shapes pydantic settles before the handler runs: a non-string
   *         `root`, a missing one, a non-list `enabled`, a `usage` value that is not an
   *         integer (the `dict[str, int]` VALUE check, whose location is the key), and a
   *         `usage` value that is a string spelling one (lax, so it is NOT a refusal);
   *   20-22 `versions`, the caller naming the version directory the host serves: one that
   *         MOVES the answer (`hash-kit` at its content-hash directory, which byte order
   *         would not have picked), one naming a directory that is not there (an answer —
   *         every directory that is there loses — and never a refusal), and a value that is
   *         not a string, which is the `dict[str, str]` VALUE check and is STRICT where the
   *         `usage` one is lax: `1` is `string_type` here and would coerce there;
   *   23    the EMPTY root, which passes JSON-schema `string` and pydantic `str` and reaches
   *         the module — where the reference used to resolve it to `Path(".")` and audit the
   *         server's own working directory while this port threw from `statSync('')`.
   *
   * THE EVENT LOG IS ON so the two outcomes — `audited` with its four counts, `refused` with
   * nothing at all — are compared as records, `ts` masked, in the block below.
   *
   * `root` is an absolute path into the checkout and is therefore the same string for both
   * runtimes; `roots[0]` in the reply echoes it, which is why it may not be a temp directory
   * created per side.
   */
  add('skill-audit', [
    INIT(),
    INITIALIZED,
    callTool(2, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024 }),
    callTool(3, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024, check: 'phrase' }),
    callTool(4, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024, check: 'budget' }),
    callTool(5, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024, check: 'frontmatter' }),
    callTool(6, 'skill_audit', { root: SKILL_CACHE, usage: SKILL_USAGE }),
    callTool(7, 'skill_audit', { root: SKILL_CACHE, enabled: [], usage: SKILL_USAGE }),
    callTool(8, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED }),
    callTool(9, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: {} }),
    callTool(10, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, check: 'all' }),
    callTool(11, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1551 }),
    callTool(12, 'skill_audit', { root: SKILL_CACHE, check: 'phrases' }),
    callTool(13, 'skill_audit', { root: SKILL_CACHE, budget: -1 }),
    callTool(14, 'skill_audit', { root: join(docs, 'no-such-catalogue') }),
    callTool(15, 'skill_audit', { root: 123 }),
    callTool(16, 'skill_audit', {}),
    callTool(17, 'skill_audit', { root: SKILL_CACHE, enabled: 'trigger-kit@kit-market' }),
    callTool(18, 'skill_audit', { root: SKILL_CACHE, usage: { 'solo-check': 'x' } }),
    callTool(19, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: { 'solo-check': '0' } }),
    callTool(20, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024, versions: SKILL_VERSIONS }),
    callTool(21, 'skill_audit', { root: SKILL_CACHE, enabled: SKILL_ENABLED, usage: SKILL_USAGE, versions: { 'dup-kit@kit-market': '9.9.9' } }),
    callTool(22, 'skill_audit', { root: SKILL_CACHE, versions: { 'hash-kit@kit-market': 1 } }),
    callTool(23, 'skill_audit', { root: '' }),
  ], { env: { ...baseEnv, [EVENT_LOG_ENV]: '1' } });

  /**
   * `build_identity` gets a session of its own, and the split is the point being made.
   *
   * Its REPLY is not comparable — `runtime`, `code_digest`, `build_id` and the Python-only
   * environment fields are ruled different in the block below — so this session's frames are
   * ruled with the rest of `identity`. Its RECORD is comparable, and must be: the record
   * carries the COUNT of underivable fields and no digest at all, precisely so that a
   * byte-compared log stays portable across two trees that can never hash alike. A session
   * whose answer differs and whose record does not is the sharpest available evidence that
   * the record was designed for this comparison rather than derived from the reply.
   */
  sessions.push({
    name: 'eventlog-identity',
    argv: ['--store', store],
    env: { ...baseEnv, [EVENT_LOG_ENV]: '1' },
    cwd: project,
    lines: [INIT(), INITIALIZED, callTool(2, 'build_identity', {})],
  });

  for (const version of ['2024-10-07', '2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25', '2026-07-28', '1999-01-01']) {
    add(`negotiate-${version}`, [INIT(version)]);
  }

  // ---------------------------------------------------------------------- run them both

  const cases = [];
  const notes = [];
  /** Sessions whose frames are compared verbatim; the rest are inspected case by case. */
  const RULED_SESSIONS = new Set([
    'identity',
    // Ruled for exactly the reasons `identity` is — `build_id`, `code_digest` and the paths
    // are domain-separated by construction. The field this session exists for, `assets_digest`
    // over a pack carrying a `__pycache__`, is compared in the `identity` block below and is
    // NOT ruled there: a ruling would only prove the two sides still differ.
    'identity-pycache',
    // Same reply, same ruling, and the `identity` block below already compares every field
    // of it that IS comparable. What this session exists for is its event-log record, which
    // is compared byte for byte in the `eventlog` block.
    'eventlog-identity',
    'unknown-methods',
    'bad-params',
    'negotiate-2024-10-07',
  ]);

  const results = new Map();
  for (const spec of sessions) {
    setup();
    const [pythonSide] = ctx.runPython(REF, { sessions: [{ ...spec, lines: spec.lines.map(b64) }] }).sessions;
    const pythonExtra = captureArtifacts();
    setup();
    const nodeSide = await runNode(spec);
    const nodeExtra = captureArtifacts();
    results.set(spec.name, {
      python: { frames: pythonSide.frames.map(unb64), stderr: unb64(pythonSide.stderr), exit: pythonSide.exit, ...pythonExtra },
      node: { frames: nodeSide.frames, stderr: nodeSide.stderr, exit: nodeSide.exit, ...nodeExtra },
    });
  }

  function captureArtifacts() {
    const eventlog = join(store, ...EVENT_LOG_RELATIVE);
    return {
      checkpoint: existsSync(checkpoint) ? readFileSync(checkpoint, 'utf8') : null,
      log: existsSync(`${checkpoint}.log.jsonl`) ? readFileSync(`${checkpoint}.log.jsonl`, 'utf8') : null,
      // Read for EVERY session, not only the one that asked for a log: a session that did
      // not set the variable and wrote a file anyway is the defect the default exists to
      // prevent, and it is only visible if the file is looked for unconditionally.
      eventlog: existsSync(eventlog) ? readFileSync(eventlog, 'utf8') : null,
      // The fact files `memory_compact` moved: still on disk, out of the index. Listed for
      // every session so a compaction that ran where none was asked for is visible too —
      // and listed for EVERY store a session can reach, not only `--store`: the layered
      // session writes the project store under `cwd` and binds the profile store under the
      // redirected `HOME`, and a compaction that archived in either would otherwise pass
      // unseen. `Memory.compact` must reach the writable project layer and never the profile.
      archive: listingOf(join(store, 'archive')),
      archiveProject: listingOf(join(project, '.bantamkit', 'memory', 'archive')),
      archiveProfile: listingOf(join(home, '.bantamkit', 'memory', 'archive')),
      // `index.md` as the session left it: its byte size and its longest line, the two
      // numbers the `memory-compact` session's budget arithmetic stands on.
      index: indexOf(join(store, 'index.md')),
    };
  }
  /** The sorted names in a directory, or `null` if there is no such directory. */
  function listingOf(dir) {
    return existsSync(dir) ? readdirSync(dir).sort() : null;
  }
  /**
   * `{ bytes, largestLine }` of an index file in UTF-8 bytes, or `null`. A line is measured
   * WITH its terminator, as `Memory.compact` measures `_index_line(fact)` for the default
   * `reserve` — a bare `split('\\n')` reads one byte short and pins the wrong number.
   */
  function indexOf(path) {
    if (!existsSync(path)) return null;
    const text = readFileSync(path, 'utf8');
    const bytes = Buffer.byteLength(text, 'utf8');
    const largestLine = Math.max(0, ...(text.match(/[^\n]*\n?/g) ?? []).map((line) => Buffer.byteLength(line, 'utf8')));
    return { bytes, largestLine };
  }

  /**
   * One case PER FRAME, keyed by JSON-RPC id, plus one for the id set.
   *
   * Comparing a whole session as one blob would report "these 34 KB differ at byte 25827",
   * which names a session and not a defect. Keyed by id, a failure names the request.
   */
  /** Every frame of a side that parses, in arrival order; an unparseable line is dropped. */
  const framesOf = (side) =>
    side.frames
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter((frame) => frame !== null);
  /** The parsed frame for one id, or `null` if the session never answered it. */
  const frameOf = (side, id) => framesOf(side).find((frame) => frame.id === id) ?? null;
  /** The rendered text of a tool result — the half a person actually reads — or `null`. */
  const toolTextOf = (side, id) => frameOf(side, id)?.result?.content?.[0]?.text ?? null;
  const byId = (frames) => {
    const map = new Map();
    for (const line of frames) {
      let id;
      try {
        id = JSON.parse(line).id;
      } catch {
        id = `unparseable:${map.size}`;
      }
      map.set(JSON.stringify(id), line);
    }
    return map;
  };
  for (const spec of sessions) {
    const { python, node } = results.get(spec.name);
    if (RULED_SESSIONS.has(spec.name)) continue;
    const left = byId(python.frames);
    const right = byId(node.frames);
    /**
     * A session's own mask, applied to BOTH sides of every comparison below, or identity.
     *
     * Only `status-active` and `status-degraded` set one, and it covers exactly one value:
     * the report's `build sha256:<64 hex>`, which is a fingerprint of the executing tree and
     * cannot agree across two trees. Every other byte of those frames — including the whole
     * of the fifth line, the problem list and the footer — is compared as it left the process.
     */
    const mask = spec.mask ?? ((text) => text);
    /**
     * The reference side's EXTRA transform, applied after `mask` and to the left side only.
     *
     * A `mask` hides a value neither side can be held to. A `refMask` rewrites the reference
     * into the port's spelling of a RULED difference, so that everything around it stays a
     * byte comparison — and, because it runs on one side only, so that the port drifting INTO
     * the reference's spelling still fails. Only `status-degraded` sets one today: the
     * `index-budget-low` remedy names a command, and the two installs provide different ones.
     */
    const refMask = spec.refMask ?? ((text) => text);
    const maskRef = (text) => refMask(mask(text));
    cases.push({
      name: `${spec.name}: the answered ids`,
      kind: 'json',
      expected: [...left.keys()].sort(),
      actual: [...right.keys()].sort(),
    });
    for (const id of [...new Set([...left.keys(), ...right.keys()])].sort()) {
      cases.push({
        name: `${spec.name}: id ${id}`,
        kind: 'string',
        expected: maskRef(canonical(left.get(id) ?? '{"missing":true}')),
        actual: mask(canonical(right.get(id) ?? '{"missing":true}')),
      });
    }
    // AND THE RAW LINE, for every frame the port builds itself. The canonicaliser above
    // deliberately drops key order and re-indents, which is right for "can a client tell
    // them apart" and wrong for "are these the same bytes" — a compact separator or a
    // reordered envelope would pass it. `initialize` is excluded and is the ONE ruled
    // order difference; everything else is compared as it left the process.
    const rawOf = (map) =>
      [...map]
        .filter(([id, line]) => id !== '1' && !line.includes('"inputSchema"'))
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([, line]) => line)
        .join('\n');
    cases.push({
      name: `${spec.name}: raw frame bytes`,
      kind: 'bytes',
      expected: maskRef(rawOf(left)),
      actual: mask(rawOf(right)),
    });
  }

  // ------------------------------------------- the one remedy the two installs spell apart

  /**
   * The `index-budget-low` sentence, pinned three ways so the ruling cannot become a licence.
   *
   * A `ruling:` case asserts the two sides DIFFER and stops there. On its own it would let
   * either half of this sentence drift to anything at all, as long as the other half stayed
   * different — and the drifting half is the one an operator is told to TYPE. So:
   *
   *   `remedy-lines-raw`  RULED. The sentences as they left the two processes, as a LIST, so
   *                       a runtime that moved the report's copy and forgot the footer's is a
   *                       different list. It goes red as a STALE RULING the moment the two
   *                       sides agree — which is what makes "the port copied the reference's
   *                       command back" a failure rather than a silent regression.
   *   `remedy-lines`      UNRULED, the same two lists after `substituteMemoryProg`. Everything
   *                       that is NOT the prog — the byte counts, the wording, the footer's
   *                       own tail, the number of places the sentence appears — must match.
   *                       Changing EITHER side's sentence alone reddens here.
   *   `remedy-commands`   UNRULED, the backticked command each side prints against the literal
   *                       that install provides. This is the case that says which spelling is
   *                       RIGHT: the two above would both stay green if the two runtimes swapped
   *                       their sentences, and a Node report naming `python -m …` is precisely
   *                       the defect this whole row exists to close.
   *
   * `runtime-ts/test/server.test.mjs` holds the other half of `remedy-commands` — that
   * `bantamkit-memory` is a `bin` `package.json` actually ships — and
   * `runtime-py/tests/test_status_surface.py` holds the reference's. A conformance suite can
   * say the two sentences name different commands; only those two can say the commands exist.
   */
  {
    const { python, node } = results.get('status-degraded');
    const pySentences = remedySentences(python.frames);
    const nodeSentences = remedySentences(node.frames);
    cases.push({
      name: 'status-degraded: the remedy lines, raw',
      kind: 'json',
      expected: pySentences,
      actual: nodeSentences,
      ruling:
        'the index remedy names a command for the operator to RUN, and the two installs ' +
        'provide different ones: `python -m bantamkit.memory compact` needs an interpreter ' +
        'and the `bantamkit.memory` module, `bantamkit-memory compact` is the npm bin. ' +
        'docs/porting.md, "the index-budget-low remedy".',
    });
    cases.push({
      name: 'status-degraded: the remedy lines, after the one substitution',
      kind: 'json',
      expected: pySentences.map(substituteMemoryProg),
      actual: nodeSentences,
    });
    cases.push({
      name: 'status-degraded: the command each side tells the operator to type',
      kind: 'json',
      expected: { python: [`${PY_MEMORY_PROG} compact`], node: [`${NODE_MEMORY_PROG} compact`] },
      actual: { python: remedyCommands(pySentences), node: remedyCommands(nodeSentences) },
    });
    notes.push(`the Node index remedy: ${JSON.stringify(remedyCommands(nodeSentences))}`);
  }

  // -------------------------------------------------------- the files clock_out writes

  {
    const { python, node } = results.get('shiftwork');
    cases.push({
      name: 'shiftwork: the rewritten checkpoint, byte for byte',
      kind: 'bytes',
      expected: python.checkpoint,
      actual: node.checkpoint,
    });
    // `ts` is `time.time()` at call time and cannot agree across two processes; everything
    // else on the line — including the `5.0` and the 2^53+1 integer — must.
    const maskTs = (text) => (text ?? '').replace(/"ts": "[^"]*"/g, '"ts": "<masked>"');
    cases.push({
      name: 'shiftwork: the accounting line, with only `ts` masked',
      kind: 'bytes',
      expected: maskTs(python.log),
      actual: maskTs(node.log),
    });
    notes.push(`accounting line (node): ${maskTs(node.log).trim()}`);
  }

  // ------------------------------------------------- the event log both runtimes write

  {
    const { python, node } = results.get('eventlog');
    /**
     * `ts` CANNOT BE COMPARED AS A VALUE — the two runtimes run at different wall-clock
     * instants — so it is masked, exactly as the accounting line above masks its own. But
     * masking a field is not the same as not testing it: the FORMAT is the thing the Python
     * half pinned itself to (`format_timestamp` was checked against a real
     * `new Date(ms).toISOString()` over seven samples), so the shape is asserted separately
     * and per side, below.
     */
    const maskTs = (text) => (text ?? '').replace(/"ts":"[^"]*"/g, '"ts":"<masked>"');
    cases.push({
      name: 'eventlog: the record stream, with only `ts` masked',
      kind: 'bytes',
      expected: maskTs(python.eventlog),
      actual: maskTs(node.eventlog),
    });

    // Keyed by call, so a failure names the outcome that moved rather than a byte offset in
    // a file. `detail` rides in the byte comparison above; this is the decision itself.
    const outcomesOf = (text) =>
      (text ?? '')
        .split('\n')
        .filter((line) => line !== '')
        .map((line) => {
          const record = JSON.parse(line);
          return [record.tool, record.outcome];
        });
    cases.push({
      name: 'eventlog: the (tool, outcome) sequence',
      kind: 'json',
      expected: outcomesOf(python.eventlog),
      actual: outcomesOf(node.eventlog),
    });

    /**
     * The one record whose REPLY is ruled un-comparable and whose RECORD is not.
     *
     * `build_identity` answers two different trees' digests by construction. The record
     * carries the COUNT of underivable fields instead, and nothing else, so it is the same
     * bytes on both sides — which is the whole reason no digest was put in it.
     *
     * ONE SUBSTITUTION, FOR THE SAME REASON THE `unavailable` CASE IS SPLIT. AS-7 added three
     * fields whose availability is decided by how the server was INSTALLED, and this harness
     * does not install its two sides alike — the reference through an editable install of
     * `runtime-py`, the port out of `runtime-ts/dist`. At `c9372ca` that made this record
     * `{"unavailable":1}` against `{"unavailable":3}` with no code difference behind it. So
     * the count compared here is the count NET of the install fields, taken from each side's
     * own reply in the same session; every other byte of the record still reaches the
     * comparison as the runtime wrote it, and the raw counts are printed in the note below.
     *
     * The substitution deletes nothing, because the case underneath it is stronger than what
     * it replaces: the record's count must equal the length of the reply's own `unavailable`
     * list, which is the property that says the record was DERIVED from the answer rather
     * than computed a second time — and it is pinned per side, so both runtimes miscounting
     * together still reddens.
     */
    const identityLog = results.get('eventlog-identity');
    const INSTALL_FIELDS_LOGGED = ['install_shape', 'install_source', 'install_source_exists'];
    const identityReplyOf = (side) => frameOf(side, 2)?.result?.structuredContent ?? {};
    const installNamed = (side) =>
      (identityReplyOf(side).unavailable ?? []).filter((k) => INSTALL_FIELDS_LOGGED.includes(k)).length;
    const netCount = (text, side) =>
      maskTs(text ?? '').replace(/"unavailable":(\d+)/g, (_m, n) => `"unavailable":${Number(n) - installNamed(side)}`);
    cases.push({
      name: 'eventlog: build_identity answers differently and records identically, net of the install fields',
      kind: 'bytes',
      expected: netCount(identityLog.python.eventlog, identityLog.python),
      actual: netCount(identityLog.node.eventlog, identityLog.node),
    });
    const recordedCount = (side) => {
      const line = (side.eventlog ?? '').split('\n').find((l) => l.includes('"build_identity"'));
      return line === undefined ? null : JSON.parse(line).detail.unavailable;
    };
    const countMatchesReply = (side) =>
      `${recordedCount(side) === (identityReplyOf(side).unavailable ?? []).length}`;
    cases.push({
      name: "eventlog: the recorded count is the reply's own unavailable list, counted — the reference",
      kind: 'string',
      expected: 'true',
      actual: countMatchesReply(identityLog.python),
    });
    cases.push({
      name: "eventlog: the recorded count is the reply's own unavailable list, counted — the port",
      kind: 'string',
      expected: 'true',
      actual: countMatchesReply(identityLog.node),
    });
    notes.push(
      `eventlog: build_identity recorded unavailable=${recordedCount(identityLog.python)} (reference) and ` +
        `unavailable=${recordedCount(identityLog.node)} (port); of those, ${installNamed(identityLog.python)} and ` +
        `${installNamed(identityLog.node)} are the AS-7 install fields, whose availability is a fact about how ` +
        'this harness is installed and not about either runtime. The bytes case above compares the counts net of them.',
    );

    const budgetLog = results.get('eventlog-budget');
    cases.push({
      name: 'eventlog: the fourth save outcome, refused by the budget',
      kind: 'bytes',
      expected: maskTs(budgetLog.python.eventlog),
      actual: maskTs(budgetLog.node.eventlog),
    });

    /**
     * `memory_compact`'s two outcomes, and the `detail` that carries the count as a number.
     *
     * The frames of the `memory-compact` session are compared above like any other; this is
     * the RECORD, which `docs/eventlog.md` says is read off `CompactResult.archived` being
     * empty or not and never off the reply. The sequence case names the call that moved.
     */
    const compactLog = results.get('memory-compact');
    cases.push({
      name: 'eventlog: memory_compact records archived / nothing-archived, with only `ts` masked',
      kind: 'bytes',
      expected: maskTs(compactLog.python.eventlog),
      actual: maskTs(compactLog.node.eventlog),
    });
    cases.push({
      name: 'eventlog: the (tool, outcome) sequence of the memory-compact session',
      kind: 'json',
      expected: outcomesOf(compactLog.python.eventlog),
      actual: outcomesOf(compactLog.node.eventlog),
    });

    /**
     * A name off the roster records NOTHING, on each side — as a literal, not a differential.
     *
     * The `retired` session ran four refused calls with the log switched on. An `Unknown tool:`
     * refusal never enters a handler, and the log records only what handlers decide, so the
     * measured value on both sides is: no file was created at all (the log opens lazily, on
     * the first record) and so zero records. Pinned per side because two servers that both
     * logged a `refused` record for a name they do not serve would agree with each other and
     * pass the byte comparison — this is the case that says the count is zero.
     */
    const retiredLog = results.get('retired');
    cases.push({
      name: 'eventlog: four calls to names off the roster created no log and recorded nothing, on each side',
      kind: 'json',
      expected: { python: { created: false, records: 0 }, node: { created: false, records: 0 } },
      actual: {
        python: { created: retiredLog.python.eventlog !== null, records: outcomesOf(retiredLog.python.eventlog).length },
        node: { created: retiredLog.node.eventlog !== null, records: outcomesOf(retiredLog.node.eventlog).length },
      },
    });

    /**
     * `skill_audit`'s records: both outcomes, and the `detail` that is four counts and no
     * argument. `audited` carries `skills`, `bytes`, `findings` and `omissions` — none of
     * which the host can see — and `refused` carries an empty object. The five
     * argument-shaped calls record nothing at all, because pydantic (and `validateArguments`
     * here) refuses before the handler is entered, so the record COUNT is part of what is
     * compared: 17 records for 22 calls, with the two `usage`-coercion calls and the two
     * `versions` calls among the seventeen — a lax int is not a refusal, and neither is a
     * `versions` entry naming a directory this root does not hold. The empty root IS one, and
     * it is recorded, because the module refuses it rather than the model doing so.
     */
    const auditLog = results.get('skill-audit');
    cases.push({
      name: 'eventlog: skill_audit records audited / refused, with only `ts` masked',
      kind: 'bytes',
      expected: maskTs(auditLog.python.eventlog),
      actual: maskTs(auditLog.node.eventlog),
    });
    cases.push({
      name: 'eventlog: the (tool, outcome) sequence of the skill-audit session',
      kind: 'json',
      expected: outcomesOf(auditLog.python.eventlog),
      actual: outcomesOf(auditLog.node.eventlog),
    });
    cases.push({
      name: 'eventlog: the skill-audit session reached both skill_audit outcomes, 17 records for 22 calls',
      kind: 'json',
      expected: { outcomes: ['audited', 'refused'], records: 17 },
      actual: {
        outcomes: [...new Set(outcomesOf(auditLog.node.eventlog).map(([, outcome]) => outcome))].sort(),
        records: outcomesOf(auditLog.node.eventlog).length,
      },
    });

    /**
     * The shape of `ts`, asserted PER SIDE against its own record count.
     *
     * Not a differential: two runtimes that drifted the same way would agree with each other
     * and both be wrong, which is precisely the failure mode a hand-built timestamp has. The
     * contract is 24 characters, a `Z` suffix and three fractional digits, and each side is
     * required to hit it on every record it wrote.
     */
    const SHAPE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
    const stampsOf = (text) => [...(text ?? '').matchAll(/"ts":"([^"]*)"/g)].map((m) => m[1]);
    for (const [side, text] of [
      ['the reference', python.eventlog],
      ['the port', node.eventlog],
    ]) {
      const stamps = stampsOf(text);
      const good = stamps.filter((t) => t.length === 24 && t.endsWith('Z') && SHAPE.test(t));
      cases.push({
        name: `eventlog: every \`ts\` ${side} wrote is the 24-char millisecond format`,
        kind: 'string',
        expected: `${stamps.length} of ${stamps.length} well-formed`,
        actual: `${good.length} of ${stamps.length} well-formed`,
      });
    }

    /**
     * OFF IS THE DEFAULT, measured over every other session in this suite.
     *
     * Not a differential either, and deliberately: two runtimes that both logged uninvited
     * would compare equal and pass. `run.mjs --all` reads the operator's live store, so a
     * default-on log is a write into real user data and the only acceptable count is zero.
     */
    const strays = [];
    for (const spec of sessions) {
      if ((spec.env ?? {})[EVENT_LOG_ENV] !== undefined) continue;
      const side = results.get(spec.name);
      if (side.python.eventlog !== null) strays.push(`python:${spec.name}`);
      if (side.node.eventlog !== null) strays.push(`node:${spec.name}`);
    }
    cases.push({
      name: 'eventlog: off by default — a session that did not ask for one wrote no log',
      kind: 'json',
      expected: [],
      actual: strays,
    });

    notes.push(`event log: ${outcomesOf(node.eventlog).length} records, identical but for \`ts\``);
  }

  // ------------------------------------------------ the roster: twelve tools, pinned per side

  /**
   * The advertisement session's `tools/list` is compared canonically above (`advertisement:
   * id 2`) and its raw order is ruled. Both of those are DIFFERENTIAL, and a differential
   * cannot see a roster that is wrong on both sides: two runtimes that both dropped
   * `memory_dream`, or both kept `repo_map`, agree with each other and pass. So the roster is
   * a LITERAL on each side — the exact names, in served order, and the count — written down
   * from a stdio `tools/list` against each server on 2026-09-13 (job50 J50-16, I5), not
   * copied from the other side.
   *
   * It was FOURTEEN with `token_ledger` last until the user's ruling of 2026-09-12 (job50,
   * I5) took `bantamkit_read` (tenth) and `repo_map` (thirteenth) off both rosters; the
   * assets stayed, claiming no surface, and the handlers went dormant. `skill_audit` moved
   * from eleventh to tenth and `memory_dream` from twelfth to eleventh, and the list below is
   * the whole of what moved. A tool re-added on ONE side fails `advertisement: id 2` and the
   * literal; a tool re-added on BOTH fails only the literal, which is why it exists.
   */
  {
    const ROSTER = [
      'memory_save',
      'memory_recall',
      'validate_json',
      'shiftwork_clock_in',
      'shiftwork_clock_out',
      'shiftwork_status',
      'build_identity',
      'bantamkit_status',
      'memory_compact',
      'skill_audit',
      'memory_dream',
      'token_ledger',
    ];
    const RETIRED = ['bantamkit_read', 'repo_map'];
    const { python, node } = results.get('advertisement');
    const toolNames = (side) => frameOf(side, 2)?.result?.tools?.map((t) => t.name) ?? null;
    const rosterOf = (side) => ({
      count: toolNames(side)?.length ?? null,
      retired: RETIRED.filter((name_) => (toolNames(side) ?? []).includes(name_)),
    });
    cases.push({ name: 'roster: the tool names, in order, side to side', kind: 'json', expected: toolNames(python), actual: toolNames(node) });
    cases.push({
      name: 'roster: the twelve served tool names, in order, as a literal on each side',
      kind: 'json',
      expected: { python: ROSTER, node: ROSTER },
      actual: { python: toolNames(python), node: toolNames(node) },
    });
    cases.push({
      name: 'roster: twelve tools, and neither repo_map nor bantamkit_read among them, on each side',
      kind: 'json',
      expected: { python: { count: 12, retired: [] }, node: { count: 12, retired: [] } },
      actual: { python: rosterOf(python), node: rosterOf(node) },
    });
  }

  // ------------------------------------------- the retired tools: refused on tools/call, per side

  /**
   * Absence from `tools/list` and refusal on `tools/call` are two properties, and job50 proved
   * they come apart: J50-15 found Node's dispatcher selecting the handler off `ARG_MODELS[name]`,
   * a table that still held both dormant models, so a retired tool was unadvertised AND would
   * have executed. The roster block above pins the first property; this one pins the second,
   * as a literal on each side and never only as a differential — both servers refusing the
   * same wrong way, or both executing, would compare equal.
   *
   * Every reply here is required to be the four-word sentence the reference's
   * `tool_manager.call_tool` raises (`ToolError(f"Unknown tool: {name}")`), delivered as an
   * `isError` RESULT with one text block and no `structuredContent` — the shape of a call that
   * never entered a handler. Id 3 is the case that would have caught J50-15's bug: a readable
   * file, so a server that still dispatched answers a manifest, not a refusal. Id 4 pins the
   * ORDER of the two checks — no `path` at all, and still `Unknown tool:` rather than the
   * validator's sentence. Id 5 is the control: a name that never existed gets the same
   * sentence, so a retired name and an unknown one are indistinguishable to a client.
   */
  {
    const { python, node } = results.get('retired');
    const table = [
      [2, 'repo_map over an existing directory', 'Unknown tool: repo_map'],
      [3, 'bantamkit_read over a readable file — a dispatcher still wired to its model would have answered a manifest', 'Unknown tool: bantamkit_read'],
      [4, 'bantamkit_read with no arguments — the roster is checked before the validator', 'Unknown tool: bantamkit_read'],
      [5, 'a name that never existed, the control', 'Unknown tool: no_such_tool'],
    ];
    const ids = table.map(([id]) => id);
    for (const [id, label, sentence] of table) {
      cases.push({
        name: `retired: id ${id}: ${label}: refused as \`${sentence}\`, as a literal on each side`,
        kind: 'json',
        expected: { python: sentence, node: sentence },
        actual: { python: toolTextOf(python, id), node: toolTextOf(node, id) },
      });
    }
    const refusalShaped = (side, id) => {
      const result = frameOf(side, id)?.result;
      return result?.isError === true && Array.isArray(result.content) && result.content.length === 1 && !('structuredContent' in result);
    };
    cases.push({
      name: 'retired: every reply is an isError frame with one text block and no structuredContent — no handler ran, on either side',
      kind: 'json',
      expected: { python: ids, node: ids },
      actual: { python: ids.filter((id) => refusalShaped(python, id)), node: ids.filter((id) => refusalShaped(node, id)) },
    });
    notes.push(`retired: ${table.length} calls to names off the roster, refused on both sides as ${JSON.stringify(toolTextOf(node, 2))} and its two siblings`);
  }

  // ----------------------------------------------------------- build_identity, in parts

  {
    const { python, node } = results.get('identity');
    const identityOf = (side) => {
      return frameOf(side, 2).result.structuredContent;
    };
    const py = identityOf(python);
    const nd = identityOf(node);
    // THE ONE FIELD THAT IS COMPARABLE, and the reason all 84 asset files ship.
    cases.push({
      name: 'build_identity: assets_digest agrees across the two runtimes',
      kind: 'string',
      expected: `${py.assets_digest} over ${py.assets_files} files`,
      actual: `${nd.assets_digest} over ${nd.assets_files} files`,
    });
    // The same field over a pack that carries the bytecode cache `pip install` leaves behind.
    // This is the shape that actually shipped: on the published 0.27.0 artifacts the Python
    // endpoint answered `sha256:fa8372f6…` over 98 files where Node answered `sha256:d47dcf4b…`
    // over 87, so `cross_runtime`'s own instruction — compare `assets_digest` across runtimes —
    // returned a false "different" on every real install. Nothing could see it, because both
    // runtimes are exercised from a source checkout where no `__pycache__` exists.
    const pyc = results.get('identity-pycache');
    const pycPy = identityOf(pyc.python);
    const pycNd = identityOf(pyc.node);
    cases.push({
      name: 'build_identity: assets_digest agrees across the two runtimes, over a pack carrying __pycache__',
      kind: 'string',
      expected: `${pycPy.assets_digest} over ${pycPy.assets_files} files`,
      actual: `${pycNd.assets_digest} over ${pycNd.assets_files} files`,
    });
    // And the stronger property, per side: a bytecode cache must not move the digest AT ALL.
    // Cross-runtime agreement alone would survive both sides counting the `.pyc` files, which
    // is the symmetric regression a differential gate cannot see.
    cases.push({
      name: 'build_identity: a __pycache__ does not move assets_digest — the reference',
      kind: 'string',
      expected: `${py.assets_digest} over ${py.assets_files} files`,
      actual: `${pycPy.assets_digest} over ${pycPy.assets_files} files`,
    });
    cases.push({
      name: 'build_identity: a __pycache__ does not move assets_digest — the port',
      kind: 'string',
      expected: `${nd.assets_digest} over ${nd.assets_files} files`,
      actual: `${pycNd.assets_digest} over ${pycNd.assets_files} files`,
    });
    // The note reports what was measured, never what the cases are supposed to prove: in the
    // mutation run that took the exclusion back out, both sides moved together to
    // `sha256:e740af3f…` over 90 files and the CROSS-RUNTIME case still passed — the two
    // per-side cases above are the only ones that went red. A note asserting "unchanged"
    // would have printed a falsehood in exactly the run where it mattered.
    notes.push(
      `identity: clean pack ${py.assets_digest} over ${py.assets_files} files; ` +
        `with __pycache__ ${pycPy.assets_digest} over ${pycPy.assets_files} (reference), ` +
        `${pycNd.assets_digest} over ${pycNd.assets_files} (port)`,
    );
    cases.push({ name: 'build_identity: version agrees', kind: 'string', expected: py.version, actual: nd.version });
    cases.push({
      name: 'build_identity: server_name agrees',
      kind: 'string',
      expected: py.server_name,
      actual: nd.server_name,
    });
    cases.push({
      name: 'build_identity: both report a real SDK version and neither reports a sentinel',
      kind: 'string',
      expected: `${typeof py.mcp_sdk_version} ${/^\d+\.\d+\.\d+/.test(String(py.mcp_sdk_version))}`,
      actual: `${typeof nd.mcp_sdk_version} ${/^\d+\.\d+\.\d+/.test(String(nd.mcp_sdk_version))}`,
    });
    cases.push({
      name: 'build_identity: the SDK versions themselves are two lineages and MUST differ',
      kind: 'string',
      expected: py.mcp_sdk_version,
      actual: nd.mcp_sdk_version,
      ruling:
        'RULED DIFFERENT. `mcp` 2.0.0 against `@modelcontextprotocol/sdk` 1.30.0 — two ' +
        'unrelated version lineages, and the field exists precisely so a caller can see which ' +
        'one answered. Reported as environment and kept OUT of `build_id`, exactly as the ' +
        'reference keeps it out. The case above is the one that has teeth: it asserts BOTH ' +
        'sides report a semver STRING, which is what caught this field silently being `null` ' +
        'on the Node side.',
    });
    /**
     * THE UNAVAILABLE LIST, SPLIT BY WHAT DECIDES EACH ENTRY. Read this before changing it.
     *
     * This case used to compare the two lists whole, and at `c9372ca` it went red with no
     * code difference behind it. AS-7 added three fields whose availability is decided by
     * how the SERVER WAS INSTALLED, and the harness does not install its two sides alike:
     * the reference is imported from an editable install of `runtime-py` (`linked`, an
     * origin that exists, nothing added to the list) and the port is run out of the checkout
     * (`checkout`, no origin path at all, so `install_source` and `install_source_exists`
     * are both named as unavailable). Same code, two environments — and a colleague whose
     * laptop carries a `pip install` and an `npm i` would see the two lists agree again.
     *
     * A case whose colour is decided by how the developer set their laptop up is not an
     * instrument, so the list is split rather than narrowed:
     *
     *   * everything the CODE decides is still compared whole, below, and still reddens if
     *     either side starts or stops refusing a field;
     *   * the three install fields are compared for the RULE they follow, per side against a
     *     literal, so a symmetric regression cannot hide in a differential;
     *   * their VALUES are compared across the two runtimes in the `install` suite, over ten
     *     matched installs both sides are handed, which is strictly more than this case ever
     *     saw — it only ever compared the one shape this machine happened to be in.
     *
     * If you are here because one of these went red: the note at the end of this suite prints
     * both sides' `install_shape`. Two different shapes is an ENVIRONMENT difference and no
     * case below should see it. The same shape with different answers is a code difference.
     */
    const INSTALL_FIELDS = ['install_shape', 'install_source', 'install_source_exists'];
    // Written out rather than imported from either runtime, so this file is not testing a
    // vocabulary against itself. That the two runtimes DECLARE the same five words, in the
    // same order, is pinned per side in the `install` suite.
    const INSTALL_SHAPES = ['registry', 'local-file', 'linked', 'checkout', 'ephemeral'];
    const codeDecided = (identity) => (identity.unavailable ?? []).filter((k) => !INSTALL_FIELDS.includes(k));
    cases.push({
      name: 'build_identity: the unavailable list agrees, over every field whose availability the CODE decides',
      kind: 'json',
      expected: codeDecided(py),
      actual: codeDecided(nd),
    });
    // THE CASE THAT COULD NOT FAIL, CLOSED. `codeDecided` reads `identity.unavailable ?? []`,
    // so two runtimes that both stopped reporting the key at all would compare `[]` against
    // `[]` and pass — and the case above would have said the lists agree while neither side
    // had one. That hole is in the case this replaced, too. The literal is what shuts it: a
    // correctly provisioned harness refuses exactly `git_commit` and derives everything else,
    // which is a property of the code (both sides refuse a commit by rule) and of the harness
    // (`BANTAMKIT_ASSETS` is pinned, so the pack is never the missing thing).
    cases.push({
      name: 'build_identity: the code-decided refusals against a literal — the reference',
      kind: 'json',
      expected: ['git_commit'],
      actual: codeDecided(py),
    });
    cases.push({
      name: 'build_identity: the code-decided refusals against a literal — the port',
      kind: 'json',
      expected: ['git_commit'],
      actual: codeDecided(nd),
    });
    /**
     * And the install fields, as the rule they are supposed to follow rather than as the
     * shape this machine is in. Each clause is a property of the code:
     *
     *   * the shape is one of the five words, or the whole triple is a named gap;
     *   * `install_source` is a non-empty path, or a named gap — never dropped, never `""`;
     *   * `install_source_exists` is a bool EXACTLY when `install_source` is a path;
     *   * and a named gap in one is a named gap in the other.
     *
     * Pinned per side against the same literal, which is the only shape that reddens when
     * both runtimes break together — the failure mode this job has now measured five times.
     */
    const named = (value) =>
      value !== null && typeof value === 'object' && typeof value.unavailable === 'string' && value.unavailable !== '';
    const installFieldRule = (identity) => {
      const shape = identity.install_shape;
      const source = identity.install_source;
      const exists = identity.install_source_exists;
      if (named(shape)) {
        return `shape undetermined and named; source and exists named too: ${named(source) && named(exists)}`;
      }
      return [
        `shape is one of the five words: ${INSTALL_SHAPES.includes(shape)}`,
        `source is a non-empty path or a named gap: ${typeof source === 'string' ? source !== '' : named(source)}`,
        `exists is a bool exactly when source is a path: ${(typeof exists === 'boolean') === (typeof source === 'string')}`,
        `exists is a named gap exactly when source is: ${named(exists) === named(source)}`,
      ].join('; ');
    };
    const INSTALL_FIELD_RULE =
      'shape is one of the five words: true; source is a non-empty path or a named gap: true; ' +
      'exists is a bool exactly when source is a path: true; exists is a named gap exactly when source is: true';
    cases.push({
      name: 'build_identity: the three install fields follow their rule — the reference',
      kind: 'string',
      expected: INSTALL_FIELD_RULE,
      actual: installFieldRule(py),
    });
    cases.push({
      name: 'build_identity: the three install fields follow their rule — the port',
      kind: 'string',
      expected: INSTALL_FIELD_RULE,
      actual: installFieldRule(nd),
    });
    notes.push(
      `identity: install_shape — reference ${JSON.stringify(py.install_shape)}, port ${JSON.stringify(nd.install_shape)}. ` +
        'These are ENVIRONMENT facts about how this harness is installed, not answers being compared: the reference ' +
        'is imported from whatever install owns `runtime-py` and the port is run from `runtime-ts/dist`. If they ' +
        'differ, that is the harness and not the code. The `install` suite compares the three fields over matched ' +
        'installs, where a difference IS the code.',
    );
    cases.push({
      name: 'build_identity: build_id is domain-separated and MUST differ',
      kind: 'string',
      expected: py.build_id,
      actual: nd.build_id,
      ruling:
        'RULED DIFFERENT BY DESIGN. `code_digest` on the Python side hashes 24 `.py` files; a ' +
        'Node build has none, so it hashes `dist/**/*.js` instead, and `runtime: "node"` is ' +
        'folded INTO the hash so the two can never collide even by accident. The tool says so ' +
        'in its own output, in `cross_runtime`. A future change that made these agree would be ' +
        'a change that made `build_id` mean nothing, so this case is required to differ.',
    });
    cases.push({
      name: 'build_identity: the Python-only environment fields are absent, not empty',
      kind: 'json',
      expected: ['python_implementation', 'python_version'].filter((k) => k in py),
      actual: ['python_implementation', 'python_version'].filter((k) => k in nd),
      ruling:
        'RULED DIFFERENT. `python_version` and `python_implementation` are not underivable ' +
        'here, they are INAPPLICABLE, and `{"unavailable": ...}` reads as "this build failed to ' +
        'derive it" (RB-P51). They are omitted and `runtime: "node"`, `node_version` and ' +
        '`v8_version` are reported instead; `runtime` is the key that tells a caller which set ' +
        'to expect.',
    });
    cases.push({
      name: 'build_identity: git_commit says wheel on one side and npm tarball on the other',
      kind: 'string',
      expected: py.git_commit.unavailable,
      actual: nd.git_commit.unavailable,
      ruling:
        'RULED DIFFERENT, one noun. The refusal is identical in reasoning and differs only in ' +
        'naming the artefact that carries no repository — "an installed wheel" vs "an installed ' +
        'npm tarball". Copying the Python sentence verbatim would have a Node server talking ' +
        'about wheels.',
    });
    notes.push(`python build_id ${py.build_id} / node build_id ${nd.build_id} — not comparable, by construction`);
  }

  // ------------------------------------------ the status surface, and the footer's PAIR

  /**
   * PER SIDE, NOT DIFFERENTIAL, and that is the point of this block.
   *
   * The frame comparisons above already prove the two runtimes agree. They cannot prove the
   * two are RIGHT: a footer emitted on every result, and a footer emitted on none, would each
   * make both sides agree with each other and fail nothing. So each side is separately held to
   * the pair — present on every one of the degraded session's other-tool replies, absent from
   * every one of the healthy session's — and to the key ORDER a structured reply puts it in.
   */
  {
    const FOOTER = '⚠️ bantamkit degraded (';
    /** The four OTHER tools in `STATUS_LINES`: two prose replies and two structured ones. */
    const OTHER_TOOLS = [2, 5, 6, 7];

    for (const [label, key] of [
      ['the reference', 'python'],
      ['the port', 'node'],
    ]) {
      const hot = results.get('status-degraded')[key];
      const cool = results.get('status-active')[key];
      const carrying = (side) => OTHER_TOOLS.filter((id) => (toolTextOf(side, id) ?? '').includes(FOOTER)).length;
      cases.push({
        name: `status: ${label} puts the footer on every degraded reply and no healthy one`,
        kind: 'string',
        expected: `degraded 4 of 4, healthy 0 of 4, and bantamkit_status itself never`,
        actual:
          `degraded ${carrying(hot)} of 4, healthy ${carrying(cool)} of 4, and bantamkit_status ` +
          `itself ${[hot, cool].some((side) => (toolTextOf(side, 3) ?? '').includes(FOOTER)) ? 'sometimes' : 'never'}`,
      });
      cases.push({
        name: `status: ${label} answers Active on one budget and Degraded one byte tighter`,
        kind: 'string',
        expected: 'bantamkit Active 🟢 then bantamkit Degraded 🟠',
        actual: `${(toolTextOf(cool, 3) ?? '').split('\n')[0]} then ${(toolTextOf(hot, 3) ?? '').split('\n')[0]}`,
      });
      cases.push({
        name: `status: ${label} puts \`bantamkit_degraded\` LAST in a structured reply, and omits it when healthy`,
        kind: 'json',
        expected: [
          ['valid', 'feedback', 'bantamkit_degraded'],
          ['valid', 'feedback'],
        ],
        actual: [
          Object.keys(frameOf(hot, 6)?.result?.structuredContent ?? {}),
          Object.keys(frameOf(cool, 6)?.result?.structuredContent ?? {}),
        ],
      });
      cases.push({
        name: `status: ${label}'s prompt carries the report itself, not an instruction to fetch it`,
        kind: 'string',
        expected: 'user text, first line bantamkit Degraded 🟠, report then 1 instruction line',
        actual: (() => {
          const message = frameOf(hot, 4)?.result?.messages?.[0];
          const text = message?.content?.text ?? '';
          const [report, ...rest] = text.split('\n\n');
          return (
            `${message?.role} ${message?.content?.type}, first line ${report.split('\n')[0]}, ` +
            `report then ${rest.length} instruction line${rest.length === 1 ? '' : 's'}`
          );
        })(),
      });
    }
    notes.push(
      'status: the index straddle is one byte of budget wide — a 46-byte index.md is Active at ' +
        'a 52-byte budget (90*52 = 4680 > 4600) and Degraded at 51 (90*51 = 4590 <= 4600), on ' +
        'both sides, by integer cross-multiplication.',
    );
    notes.push(
      'status: ONE mask over both reports — `build sha256:<64 hex>`, the value docs/porting.md ' +
        'already rules divergent — and, on `status-degraded` only, ONE substitution on the ' +
        'REFERENCE side: `python -m bantamkit.memory` -> `bantamkit-memory` in the ' +
        'index-budget-low remedy, also ruled. Every other byte of the report, the prompt and ' +
        'the footer is compared as it left the process.',
    );
  }

  // ------------------------------------------------ memory_compact, held to its own story

  /**
   * PER SIDE, NOT DIFFERENTIAL, like the status block above: the frame comparisons prove the
   * two runtimes agree, and these prove each is RIGHT about the four things the tool is for.
   * Two runtimes that both archived nothing, or both refused nothing, would agree and fail
   * nothing above.
   *
   *   - the sixth save is refused for budget and the refusal NAMES the tool (`docs/memory.md`:
   *     the last sentence is the model's remedy, everything before it the operator's);
   *   - the compaction after it archives exactly one fact, the stalest, and says which;
   *   - the retry of the refused save then lands;
   *   - what the reply says moved is what is on disk under `archive/`, and NOTHING else in
   *     this suite wrote there — archived is not deleted, and a compaction nobody asked for
   *     is the defect that would show up as a listing from a session not named here.
   */
  {
    const textOf = (side, id) => toolTextOf(side, id) ?? '';
    for (const [label, key] of [
      ['the reference', 'python'],
      ['the port', 'node'],
    ]) {
      const side = results.get('memory-compact')[key];
      const refused = textOf(side, 8);
      const compacted = textOf(side, 9);
      const retried = textOf(side, 10);
      // Four facts, four keys, so the clause that failed is the one the diff names.
      cases.push({
        name: `memory_compact: ${label} refuses the sixth save for budget and the refusal names the tool`,
        kind: 'json',
        expected: { refused_for_budget: true, names_the_tool: true, then_archived: 'archived 1 memories;', then_retried: "saved 'compact-f'" },
        actual: {
          refused_for_budget: refused.startsWith('error: memory index is '),
          names_the_tool: refused.includes('call `memory_compact`'),
          then_archived: compacted.split(' the index went from ')[0],
          then_retried: retried,
        },
      });
      /** The names a compaction reply says it moved — one bullet each, `- <name> (<type>) — …`. */
      const namedBy = (id) => [...textOf(side, id).matchAll(/^- (\S+) \(/gm)].map((m) => m[1]);
      const recalled = textOf(side, 11);
      cases.push({
        name: `memory_compact: ${label} archived the stalest fact and it is on disk, out of the index`,
        kind: 'json',
        expected: { archived: ['compact-a'], recall_names_a_survivor: true, recall_names_the_archived: false },
        // Positive on the survivor: a missing frame or an error reply says nothing about
        // `compact-a` either, and must not pass as "not found".
        actual: { archived: namedBy(9), recall_names_a_survivor: recalled.includes('compact-b'), recall_names_the_archived: recalled.includes('compact-a') },
      });
      cases.push({
        name: `memory_compact: ${label} at reserve 9999 archived the two first-named of five equally-stale facts`,
        kind: 'json',
        expected: ['compact-b', 'compact-c'],
        actual: namedBy(13),
      });
      // The store creates an empty `archive/` when it opens, on both sides; a LISTING is
      // what compaction leaves, so an empty directory is "did not compact". Every store a
      // session could reach is listed — `--store`, the layered session's project store and
      // its profile store under `HOME` — and the one listing expected is what the two
      // archiving replies (ids 9 and 13) SAID moved, so disk and reply are held to each other.
      const wroteArchive = [];
      for (const spec of sessions) {
        const extra = results.get(spec.name)[key];
        for (const [where, listing] of [['store', extra.archive], ['project', extra.archiveProject], ['profile', extra.archiveProfile]]) {
          if ((listing ?? []).length > 0) wroteArchive.push(`${spec.name} (${where}): ${listing.join(',')}`);
        }
      }
      // WIDENED (job46, J46-6) FROM ONE SESSION TO A LIST OF THEM, and it is a widening and
      // not a loosening: the expectation is still built from what the REPLIES said moved, and
      // it still forbids every other session and every other store. `index-band` is the second
      // session in this suite that compacts — it is register item 7's own story, and before it
      // this case's one-element literal would have failed on its existence rather than on
      // anything it did. The ids are the archiving calls of each session, named here so a
      // session that started compacting silently is still a failure.
      const COMPACTING = [['memory-compact', [9, 13]], ['index-band', [15]]];
      const expectedArchives = COMPACTING.map(([session, ids]) => {
        const from = results.get(session)[key];
        const said = ids
          .flatMap((id) => [...(toolTextOf(from, id) ?? '').matchAll(/^- (\S+) \(/gm)].map((m) => `${m[1]}.md`))
          .sort();
        return `${session} (store): ${said.join(',')}`;
      });
      cases.push({
        name: `memory_compact: ${label} wrote \`archive/\` in the sessions that compacted, in no other store, and only what the replies named`,
        kind: 'json',
        expected: expectedArchives,
        actual: wroteArchive,
      });
      // The arithmetic the whole session stands on, pinned on disk rather than in prose:
      // five ~53-byte lines make 266 against a 320 budget, one over the 265 default target
      // (the largest line is 55), and the three survivors' lines reach 160 by equality.
      // AMENDED (job46, J46-6): "the 265 default target" is the PRE-job46 number and stays
      // as the record of what this case was built against; the default target at a 320-byte
      // budget is now 232, and 266 is over both. See the session's own comment for why its
      // answer is unchanged either way, and `index-band` for the case that is not.
      const savedRecords = (side.eventlog ?? '')
        .split('\n')
        .filter((line) => line !== '')
        .map((line) => JSON.parse(line))
        .filter((record) => record.tool === 'memory_save' && record.outcome === 'saved');
      cases.push({
        name: `memory_compact: ${label} index arithmetic — 266 after five saves, 320 budget, largest line 55, 160 left`,
        kind: 'json',
        expected: { afterFive: 266, budget: 320, largestLine: 55, atEnd: 160 },
        actual: {
          afterFive: savedRecords[4]?.detail?.index_bytes ?? null,
          budget: savedRecords[4]?.detail?.budget ?? null,
          largestLine: side.index?.largestLine ?? null,
          atEnd: side.index?.bytes ?? null,
        },
      });
    }
    notes.push(`memory_compact (node): ${textOf(results.get('memory-compact').node, 9).split('\n')[0]}`);
  }

  // -------------------------------------------------- the band, held to register item 7

  /**
   * PER SIDE AND AS LITERALS, for the reason the block above gives and one more that is
   * specific to this change: `87cc1f7` and `55575c3` moved the SAME arithmetic on both
   * runtimes in one job, so a differential comparison of the two cannot see whether either of
   * them is right. That is this repository's third named vacuity — a symmetric regression —
   * and the only defence against it is a literal each side has to reach on its own. Both sides
   * of every case below are therefore fixed numbers and fixed name lists, not one runtime's
   * answer handed to the other.
   *
   * Four things, one case each, in the order the operator meets them:
   *
   *   1. IN THE BAND: the report warns, and the command it names is not a no-op there. The
   *      band is DERIVED from what the session actually left on disk — the index size the
   *      compaction reply quotes and the largest line `index.md` still carries — and never
   *      from a percentage. A percentage would rot: the register wrote 99.2% off a store whose
   *      largest index line was 186 bytes, and the same store measures 98.50% today at 361,
   *      because the upper edge is a function of store CONTENT.
   *   2. CLEARED: the condition the report printed before is absent from the report after.
   *   3. IDEMPOTENT: the second run archives nothing.
   *   4. ORDER: the same three names, in the same order, on both sides, all of them
   *      non-feedback — while the three facts a key that ignored the class would have taken
   *      are all `feedback` and all still in the index.
   */
  {
    const textOf = (side, id) => toolTextOf(side, id) ?? '';
    /** `- <name> (<type>) — <description>`: the bullets a compaction reply lists, in reply order. */
    const movedBy = (side, id) =>
      [...textOf(side, id).matchAll(/^- (\S+) \((\w+)\) — /gm)].map((m) => ({ name: m[1], type: m[2] }));
    const ALL_BAND_NAMES = [
      ...BAND_FEEDBACK.map((_, i) => `band-f${i + 1}`),
      ...BAND_PROJECT.map((_, i) => `band-p${i + 1}`),
    ];
    for (const [label, key] of [
      ['the reference', 'python'],
      ['the port', 'node'],
    ]) {
      const side = results.get('index-band')[key];
      const before = textOf(side, 14);
      const compacted = textOf(side, 15);
      const after = textOf(side, 16);
      const again = textOf(side, 17);
      // "the index went from 995 to 839 bytes against a 1101-byte budget" — the two sizes and
      // the budget read out of the reply the operator is shown, so the arithmetic pinned here
      // is the arithmetic that was printed and not a second computation of it.
      const went = /the index went from (\d+) to (\d+) bytes against a (\d+)-byte budget/.exec(compacted);
      const indexAfter = went ? Number(went[2]) : null;
      // THE BAND IS MEASURED FROM THE WARNING'S OWN NUMBERS, not from the remedy's. The
      // degraded sentence is `the memory index is <n> bytes of a <b>-byte budget, …`, and
      // reading the pair out of THAT is what lets the band case still measure a band when the
      // remedy has gone back to being a no-op and printed no numbers at all. The remedy's
      // `from` is compared against it below rather than substituted for it.
      const warned = /the memory index is (\d+) bytes of a (\d+)-byte budget/.exec(before);
      const indexBefore = warned ? Number(warned[1]) : null;
      const budget = warned ? Number(warned[2]) : null;
      const largestLine = side.index?.largestLine ?? null;
      cases.push({
        name: `index-band: ${label} is inside the band — degraded at the warning line, and under the target the OLD default would have aimed at`,
        kind: 'json',
        expected: {
          indexBefore: 995,
          budget: 1101,
          largestLine: 105,
          // 995 * 100 = 99500 >= 90 * 1101 = 99090. Derived from the two numbers above rather
          // than asserted, so a fixture that drifted out of the band fails here and does not
          // quietly go on to test nothing.
          degradedAtTheWarningLine: true,
          // 995 <= 1101 - 105 = 996: the OLD default target, which is why the remedy used to
          // exit 0 having archived nothing exactly here.
          underTheOldDefaultTarget: true,
          // …and the band is non-empty at all only because 1101 >= 10 * 105.
          theBandIsNonEmpty: true,
          reportNamesTheRemedy: true,
        },
        actual: {
          indexBefore,
          budget,
          largestLine,
          degradedAtTheWarningLine: indexBefore !== null && budget !== null && indexBefore * 100 >= 90 * budget,
          underTheOldDefaultTarget:
            indexBefore !== null && budget !== null && largestLine !== null && indexBefore <= budget - largestLine,
          theBandIsNonEmpty: budget !== null && largestLine !== null && budget >= 10 * largestLine,
          reportNamesTheRemedy: before.includes(REMEDY_HEAD),
        },
      });
      cases.push({
        name: `index-band: ${label} — the remedy the degraded report names archives something, and the condition has cleared afterwards`,
        kind: 'json',
        expected: {
          archivedCount: 3,
          indexAfter: 839,
          remedyAgreesWithTheWarningAboutTheSize: true,
          stillDegraded: false,
          reportStillNamesTheRemedy: false,
        },
        actual: {
          archivedCount: movedBy(side, 15).length,
          indexAfter,
          // The report and the remedy are two surfaces reading one store; a job that moved
          // one of them and not the other is the whole defect this session exists for.
          remedyAgreesWithTheWarningAboutTheSize: went !== null && Number(went[1]) === indexBefore,
          stillDegraded: indexAfter !== null && budget !== null && indexAfter * 100 >= 90 * budget,
          // The report AFTER, read for the same sentence the report BEFORE carried. A runtime
          // that stopped printing the sentence altogether would pass this half and fail the
          // `reportNamesTheRemedy` half of the case above.
          reportStillNamesTheRemedy: after.includes(REMEDY_HEAD),
        },
      });
      cases.push({
        name: `index-band: ${label} — running the remedy a second time archives nothing`,
        kind: 'json',
        expected: { archived: [], saysNothingToArchive: true },
        actual: {
          archived: movedBy(side, 17).map((m) => m.name),
          // The reply's own words for the empty outcome. A positive check, so a run that
          // errored — and archived nothing because it never got that far — fails here rather
          // than passing as "idempotent".
          saysNothingToArchive: again.includes('nothing archived: the index is '),
        },
      });
      cases.push({
        name: `index-band: ${label} — the names and the order, with feedback exhausted last`,
        kind: 'json',
        expected: {
          moved: [
            { name: 'band-p1', type: 'project' },
            { name: 'band-p2', type: 'project' },
            { name: 'band-p3', type: 'project' },
          ],
          onDisk: ['band-p1.md', 'band-p2.md', 'band-p3.md'],
          // What a key that ranked by staleness ALONE would have archived here: every fact was
          // saved on the same day, so the name breaks the tie, and `band-f*` sorts first. The
          // three it would have taken are the user's standing instructions.
          whatATemporalKeyWouldTake: ['band-f1', 'band-f2', 'band-f3'],
          everyFeedbackFactSurvived: true,
          // Two project facts are still in the index, so the loop STOPPED at the target
          // rather than running out of non-feedback candidates — without this the case would
          // pass under a rule that simply archived every project fact it could find.
          projectFactsLeftStanding: 2,
        },
        actual: {
          moved: movedBy(side, 15),
          onDisk: side.archive ?? null,
          whatATemporalKeyWouldTake: [...ALL_BAND_NAMES].sort().slice(0, 3),
          everyFeedbackFactSurvived: BAND_FEEDBACK.every((_, i) => !(side.archive ?? []).includes(`band-f${i + 1}.md`)),
          projectFactsLeftStanding: BAND_PROJECT.filter((_, i) => !(side.archive ?? []).includes(`band-p${i + 1}.md`)).length,
        },
      });
    }
    notes.push(`index-band (node): ${textOf(results.get('index-band').node, 15).split('\n')[0]}`);
    notes.push(
      `index-band: the band on this fixture — degraded from 90% of 1101 = 990.9 up to the old ` +
        `default target 1101 - 105 = 996, index 995, new target ` +
        `${Math.floor((90 * 1101 - 1) / 100) - 105}; every edge derived, no percentage pinned`,
    );
  }

  // --------------------------------------------------- the SDK-lineage rulings, in full

  {
    const { python, node } = results.get('unknown-methods');
    const errorsOf = (side) =>
      framesOf(side)
        .filter((f) => f.error)
        .sort((a, b) => a.id - b.id)
        .map((f) => f.error);
    cases.push({
      name: 'unknown method: the reference names the method in `data`, the TS SDK sends none',
      kind: 'json',
      expected: errorsOf(python),
      actual: errorsOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage, not reachable from this package. Both answer -32601 ' +
        '"Method not found". `mcp` 2.0.0 attaches `data: "<method>"`; the TS SDK 1.30.0 builds ' +
        'that response inside `Protocol._onrequest` before any handler exists, so there is no ' +
        'seam to add the field from. Registering a handler per method would only move the ' +
        'problem to the next unregistered method, which is unbounded.',
    });
  }

  {
    const { python, node } = results.get('bad-params');
    const errorOf = (side) => frameOf(side, 2)?.error ?? null;
    cases.push({
      name: 'tools/call with a non-object `arguments`: pydantic vs zod, on the ERROR channel',
      kind: 'json',
      expected: errorOf(python),
      actual: errorOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage. Both refuse with -32602 before any bantamkit code runs; ' +
        'the request never reaches a handler, so the port has no seam. Python says "Invalid ' +
        'request parameters" with `data: ""`; the TS SDK says "Invalid tools/call request: ' +
        '<zod issue list>". This is the ONE argument-shaped refusal the port cannot own — every ' +
        'refusal inside a well-formed `arguments` object IS reproduced, in pydantic\'s words, ' +
        'by `src/mcp/pyargs.ts`.',
    });
  }

  {
    const { python, node } = results.get('negotiate-2024-10-07');
    const versionOf = (side) => frameOf(side, 1)?.result?.protocolVersion;
    cases.push({
      name: 'protocol negotiation: 2024-10-07 is supported by the TS SDK and not by the Python one',
      kind: 'string',
      expected: versionOf(python),
      actual: versionOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage. `mcp` 2.0.0 supports {2024-11-05, 2025-03-26, ' +
        '2025-06-18, 2025-11-25} and falls back to 2025-11-25; the TS SDK also supports ' +
        '2024-10-07 and echoes it. Measured over all seven requested versions: the two agree on ' +
        'six and differ on this one. Narrowing the TS SDK\'s supported set is not reachable from ' +
        'the public API, and refusing a version the SDK can actually speak would make this ' +
        'server worse than either reference.',
    });
    const both = ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25', '2026-07-28', '1999-01-01'];
    cases.push({
      name: 'protocol negotiation: the other six agree, fallback included',
      kind: 'json',
      expected: both.map((v) => versionOfSession(results, `negotiate-${v}`, 'python')),
      actual: both.map((v) => versionOfSession(results, `negotiate-${v}`, 'node')),
    });
  }

  // `tools/list` is the second payload whose key order is not the port's to choose — not
  // because the port does not build it (it does, out of the manifests) but because the
  // REFERENCE does not emit it in manifest order.
  {
    const { python, node } = results.get('advertisement');
    const listFrame = (side) => side.frames.find((f) => f.includes('"inputSchema"'));
    cases.push({
      name: 'tools/list: the reference reorders keys the port emits in manifest order',
      kind: 'bytes',
      expected: listFrame(python),
      actual: listFrame(node),
      ruling:
        'RULED DIFFERENT — key order only, inside `mcp` 2.0.0\'s outbound serializer, and the ' +
        'CONTENT is proven identical by the `advertisement: id 2` case above, which sorts keys ' +
        'and passes. Measured, three levels: the tool entry arrives as `description, ' +
        'inputSchema, name, outputSchema` where the pydantic model dumps `name, title, ' +
        'description, inputSchema, ...`; `memory_save` and `memory_recall` arrive with ' +
        '`inputSchema` as `properties, required, type` where their manifests say `type, ' +
        'required, properties`; `memory_compact` arrives as `properties, type` where its ' +
        'manifest says `type, properties`; and the other six, whose manifests already read ' +
        '`properties, [required,] type[, title]` (`bantamkit_status` and `build_identity` take ' +
        'no argument and have no `required`), arrive unchanged. `Tool.input_schema` is a plain ' +
        '`dict[str, Any]` and `ListToolsResult(...).model_dump_json(by_alias=True, ' +
        'exclude_unset=True)` was measured to PRESERVE manifest order, so the reordering is ' +
        'downstream of the model and has no seam this package can reach. The port serves the ' +
        'manifest bytes as written, which is the answer that is defensible from here.',
    });
  }

  // The `initialize` result is the one payload BOTH servers build inside their SDK, so it is
  // the one place key order is not the port's to choose.
  {
    const { python, node } = results.get('handshake');
    const keysOf = (side) => Object.keys(JSON.parse(side.frames.find((f) => f.includes('"serverInfo"'))).result);
    cases.push({
      name: 'initialize: the result key ORDER is the SDK\'s, and the two disagree',
      kind: 'json',
      expected: keysOf(python),
      actual: keysOf(node),
      ruling:
        'RULED DIFFERENT — SDK lineage, and invisible to any conforming client. `mcp` 2.0.0 ' +
        'dumps its pydantic model alphabetically (capabilities, instructions, protocolVersion, ' +
        'serverInfo); the TS SDK builds an object literal (protocolVersion, capabilities, ' +
        'serverInfo, instructions) inside `Server._oninitialize`, which this package does not ' +
        'call. The CONTENT is compared and must match — see the `handshake: frames` case, which ' +
        'sorts keys — so only the order is ruled. Every payload the port builds itself ' +
        '(`tools/list`, `resources/templates/list`, every tool result, the JSON-RPC envelope) ' +
        'is emitted in the reference\'s order instead of the SDK\'s.',
    });
  }

  notes.push(`${sessions.length} sessions, both runtimes, over identical paths under ${scratch}`);
  return { cases, notes };
}

function versionOfSession(results, name_, side) {
  const frames = results.get(name_)[side].frames;
  return frames.map((f) => JSON.parse(f)).find((f) => f.id === 1)?.result?.protocolVersion ?? null;
}
