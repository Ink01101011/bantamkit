/**
 * storage-tiers — capability tiers and the storage lines of `bantamkit_status` (#204, S2;
 * job69 J69-7), Python against Node, over the wire.
 *
 * THE PROPERTY: on an MCP-ONLY host profile — a HOME with no `.claude/`, no hook registered, no
 * native directory, a cwd with no project settings — every one of the fifteen served tools
 * answers on both runtimes and no answer is an error: tier 1 runs complete with tiers 2 and 3
 * absent, silently. `bantamkit_status` names the tiers (`storage: core on; hooks off; host data
 * off`), one line per hot index, every log and the last retention run, and the two runtimes
 * print the same bytes. The same status on a HOOKED profile (a bantamkit hook in the user's
 * settings, an `autoMemoryDirectory` holding a `MEMORY.md`, a hook log with a rotated segment
 * and a bad line, a retention record) says `hooks on; host data on`; a hook registered only in
 * the project's `settings.local.json` turns the hook tier on alone; and an index directory that
 * cannot be written is reported `in-memory` while recall still answers (the spec's error row).
 *
 * HOW. The sessions are driven exactly as `wire` drives them — `ref/wire_ref.py` for the
 * reference, `wire.mjs`'s `runNode` for the port — both over the identical scratch paths,
 * rebuilt from nothing before each side. ONE MASK: line 2's build digest, the value
 * `docs/porting.md` already rules divergent; `build_identity`'s reply is ruled un-comparable
 * and is compared by its `isError` alone.
 *
 * THE LITERALS. A change made on both sides leaves every differential green, so per side:
 * the error bit of every tool call on the MCP-only profile, the storage block on each profile
 * (byte counts the harness can derive are derived; the index's own bytes are compared across
 * sides and shape-checked per side), and recall answering over the unwritable index directory.
 */
import { pep440ToSemver } from './version.mjs';
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';

import { runNode } from './wire.mjs';

export const name = 'storage-tiers';
export const summary = 'capability tiers: an MCP-only host runs every tool; bantamkit_status names the tiers, indexes, logs, retention';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'wire_ref.py');
const ASSETS = join(repoRoot, 'assets');
const REAL_CHECKPOINT = join(repoRoot, 'tools', 'shiftwork', 'example-codefix-checkpoint.json');
const SKILL_FIXTURE = join(repoRoot, 'tools', 'conformance', 'fixtures', 'skill-audit');
const LEDGER_FIXTURE = join(repoRoot, 'tools', 'ledger', 'fixtures', 'token-ledger', 'projects');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const unb64 = (s) => Buffer.from(s, 'base64').toString('utf8');
const INIT = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'conformance', version: '0' } },
});
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const rpc = (id, method, params) => JSON.stringify({ jsonrpc: '2.0', id, method, params });
const callTool = (id, tool, args) => rpc(id, 'tools/call', { name: tool, arguments: args });

/** A hook entry carrying bantamkit's marker, as `--install-hooks` writes it. */
const OURS = { matcher: '', hooks: [{ type: 'command', command: 'bantamkit-mcp --hook', timeout: 10, bantamkit: 'hook' }] };
const THEIRS = { matcher: '', hooks: [{ type: 'command', command: 'notify-send done' }] };
const RAN_AT = '2026-10-16T01:40:13.095Z';

export async function run(ctx) {
  const { dumpJson, parseJson } = await import(pathToFileURL(join(repoRoot, 'runtime-ts', 'dist', 'pyjson.js')).href);
  const canonical = (line) => {
    try {
      return dumpJson(parseJson(line), { sortKeys: true, indent: 2 });
    } catch (e) {
      return `NOT-A-FRAME(${e.message}): ${line}`;
    }
  };
  const maskBuild = (text) => text.replace(/build sha256:[0-9a-f]{64}/g, 'build sha256:<masked>');
  // A prerelease has two spellings of one version (docs/porting.md, "a prerelease version's
  // spelling"; the `version` suite pins each side's). Compare the reference AFTER mapping its
  // PEP 440 spelling to semver, as that ruling says; a stable version maps to itself.
  const semverPy = (text) => text.replace(/(version )([0-9][0-9A-Za-z.]*)(, build)/g, (_, a, v, b) => a + pep440ToSemver(v) + b);

  const root = join(ctx.scratch, 'storage-tiers');
  const home = join(root, 'home');
  const project = join(root, 'project');
  const store = join(project, 'store');
  const native = join(root, 'native');
  const idx = join(root, 'idx');
  const blocker = join(root, 'not-a-dir');
  const checkpoint = join(root, 'cp.json');
  const SKILL_ENABLED = JSON.parse(readFileSync(join(SKILL_FIXTURE, 'enabled.json'), 'utf8'));
  const SKILL_USAGE = JSON.parse(readFileSync(join(SKILL_FIXTURE, 'usage.json'), 'utf8'));
  const cursor = JSON.parse(readFileSync(REAL_CHECKPOINT, 'utf8')).plan.cursor;

  const write = (p, data) => {
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, data);
  };
  const hookLog = join(home, '.bantamkit', 'hooks', 'hook-log.jsonl');
  const HOOK_LOG = '{"event":"SessionStart","ts":"2026-10-16T00:00:00.000Z"}\nnot a json line\n';
  const HOOK_SEG = gzipSync(Buffer.from('{"event":"Stop","ts":"2026-10-01T00:00:00.000Z"}\n'));
  const USAGE_LINES = '{"ts":"2026-10-15T00:00:00Z","fact":"a","kind":"recall"}\n{"ts":NaN}\n';

  /** The world one profile names, rebuilt from nothing before EACH side. */
  const profiles = {
    'mcp-only': () => {},
    hooked: () => {
      write(join(home, '.claude', 'settings.json'), JSON.stringify({ autoMemoryDirectory: native, hooks: { SessionStart: [OURS], Stop: [THEIRS] } }));
      write(join(native, 'MEMORY.md'), '# memory\n');
      write(hookLog, HOOK_LOG);
      write(`${hookLog}.1.gz`, HOOK_SEG);
      write(join(home, '.bantamkit', 'usage', 'abc123.jsonl'), USAGE_LINES);
      write(join(home, '.bantamkit', 'usage', 'not-a-ledger.txt'), 'ignored');
      write(join(home, '.bantamkit', 'retention.json'), JSON.stringify({ ran_at: RAN_AT, report: { refused: [{ path: 'p', reason: 'delete failed' }] } }));
    },
    'project-hook': () => {
      write(join(home, '.claude', 'settings.json'), JSON.stringify({ hooks: { Stop: [THEIRS] } }));
      write(join(project, '.claude', 'settings.local.json'), JSON.stringify({ hooks: { UserPromptSubmit: [OURS] } }));
    },
    'unwritable-index': () => write(blocker, 'a file where the index directory goes'),
    // J68-10 (#199 D5 error row): a FILE where the usage directory belongs, so every append is
    // lost. A file in the way refuses the mkdir on POSIX and on Windows alike; chmod does not.
    'unwritable-ledger': () => write(join(home, '.bantamkit', 'usage'), 'a file where the usage directory goes'),
  };
  const setup = (profile) => {
    rmSync(root, { recursive: true, force: true });
    for (const d of [home, project]) mkdirSync(d, { recursive: true });
    cpSync(REAL_CHECKPOINT, checkpoint);
    profiles[profile]();
  };
  const env = (extra = {}) => ({
    HOME: home,
    USERPROFILE: home,
    BANTAMKIT_ASSETS: ASSETS,
    BANTAMKIT_MEMORY_DIR: null,
    BANTAMKIT_INDEX_DIR: idx,
    CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: null,
    BANTAMKIT_EVENT_LOG: null,
    ...extra,
  });

  // Every served tool, with arguments it answers without an error. The order puts the save
  // first, so the store the rest read exists, and the status last, after recall built the index.
  const TOOLS = [
    ['memory_save', { type: 'project', name: 'tier-probe', description: 'a probe for the capability tiers', body: 'body' }],
    ['memory_recall', { query: 'capability tiers probe' }],
    ['validate_json', { output: '{"a": 1}', schema: { type: 'object' } }],
    ['shiftwork_status', { checkpoint }],
    ['shiftwork_plan', { checkpoint }],
    ['shiftwork_clock_in', { checkpoint }],
    ['shiftwork_clock_out', { checkpoint, unit_id: cursor, status: 'in_progress', handoff_patch: {}, history_entry: { unit: cursor, outcome: 'probe' } }],
    ['build_identity', {}],
    ['memory_compact', {}],
    ['skill_audit', { root: join(SKILL_FIXTURE, 'cache'), enabled: SKILL_ENABLED, usage: SKILL_USAGE, budget: 1024 }],
    ['memory_dream', { dry_run: true }],
    ['token_ledger', { root: LEDGER_FIXTURE }],
    ['work_plan', { nodes: [] }],
    ['memory_queries', {}], // #207 amendment 3: lists, writes nothing
    ['bantamkit_status', {}],
  ];
  const FIRST_TOOL_ID = 3;
  const STATUS_ID = FIRST_TOOL_ID + TOOLS.length - 1;
  const PROMPT_ID = STATUS_ID + 1;
  const sessions = [
    {
      name: 'mcp-only',
      profile: 'mcp-only',
      argv: ['--store', store],
      env: env(),
      cwd: project,
      lines: [
        INIT,
        INITIALIZED,
        rpc(2, 'tools/list', {}),
        ...TOOLS.map(([tool, args], i) => callTool(FIRST_TOOL_ID + i, tool, args)),
        rpc(PROMPT_ID, 'prompts/get', { name: 'bantamkit_status' }),
      ],
    },
    { name: 'hooked', profile: 'hooked', argv: ['--store', store], env: env(), cwd: project, lines: [INIT, INITIALIZED, callTool(2, 'bantamkit_status', {})] },
    { name: 'project-hook', profile: 'project-hook', argv: ['--store', store], env: env(), cwd: project, lines: [INIT, INITIALIZED, callTool(2, 'bantamkit_status', {})] },
    {
      name: 'unwritable-index',
      profile: 'unwritable-index',
      argv: ['--store', store],
      env: env({ BANTAMKIT_INDEX_DIR: join(blocker, 'idx') }),
      cwd: project,
      lines: [
        INIT,
        INITIALIZED,
        callTool(2, 'memory_save', { type: 'project', name: 'tier-probe', description: 'a probe for the capability tiers', body: 'body' }),
        callTool(3, 'memory_recall', { query: 'capability tiers probe' }),
        callTool(4, 'bantamkit_status', {}),
      ],
    },
    {
      name: 'unwritable-ledger',
      profile: 'unwritable-ledger',
      argv: ['--store', store],
      env: env(),
      cwd: project,
      lines: [
        INIT,
        INITIALIZED,
        callTool(2, 'memory_save', { type: 'project', name: 'tier-probe', description: 'a probe for the capability tiers', body: 'body' }),
        callTool(3, 'memory_recall', { query: 'capability tiers probe' }),
        callTool(4, 'bantamkit_status', {}),
      ],
    },
  ];

  const results = new Map();
  for (const spec of sessions) {
    const { profile, ...wire } = spec;
    setup(profile);
    const [py] = ctx.runPython(REF, { sessions: [{ ...wire, lines: wire.lines.map(b64) }] }).sessions;
    setup(profile);
    const nd = await runNode(wire);
    results.set(spec.name, {
      python: { frames: py.frames.map(unb64), stderr: unb64(py.stderr) },
      node: { frames: nd.frames, stderr: nd.stderr },
    });
  }

  const byId = (frames) => {
    const map = new Map();
    for (const line of frames) {
      try {
        const parsed = JSON.parse(line);
        if (parsed && parsed.id !== undefined) map.set(parsed.id, parsed);
      } catch {
        /* a non-frame line shows up in the frame comparison */
      }
    }
    return map;
  };
  const cases = [];
  const notes = [];

  // ------------------------------------------------------------------- the differential
  for (const [session, r] of results) {
    const py = byId(r.python.frames);
    const nd = byId(r.node.frames);
    const ids = [...new Set([...py.keys(), ...nd.keys()])].sort((a, b) => a - b);
    for (const id of ids) {
      if (id === 1) continue; // `initialize` is the `wire` suite's; nothing this suite pins moves it
      const isIdentity = session === 'mcp-only' && id === FIRST_TOOL_ID + TOOLS.findIndex(([t]) => t === 'build_identity');
      const view = (frame) => {
        if (frame === undefined) return 'MISSING';
        if (isIdentity) return `isError: ${JSON.stringify(frame.result?.isError ?? null)}`;
        return maskBuild(canonical(JSON.stringify(frame)));
      };
      const expected = view(py.get(id));
      cases.push({ name: `${session}: id ${id}`, kind: 'string', expected: semverPy(expected), actual: view(nd.get(id)) });
    }
  }

  // ------------------------------------------------------------------- the literals
  const textOf = (side, session, id) => byId(results.get(session)[side].frames).get(id)?.result?.content?.[0]?.text ?? null;
  const storageBlock = (text) => {
    if (typeof text !== 'string') return null;
    const lines = text.split('\n');
    const at = lines.findIndex((l) => l.startsWith('storage: '));
    if (at === -1) return null;
    const block = [];
    for (const l of lines.slice(at)) {
      if (!/^(storage|index|logs|touch|retention)[: ]/.test(l)) break; // `touch` since #200
      block.push(l);
    }
    return block;
  };
  /** The index line's own byte count is compared ACROSS sides above; per side, its shape. */
  // A usage ledger is named by its store's id, a hash of the store's real path in this run's
  // scratch, so the id is masked per side; its size is not (#199, J68-5).
  const shaped = (block) =>
    block?.map((l) =>
      l
        .replace(/^(index facts \w+: \d+ docs?, )\d+( bytes, persisted)$/, '$1<n>$2')
        .replace(/^logs: usage\/[0-9a-f]{16} /, 'logs: usage/<id> '),
    ) ?? null;

  const hookLogBytes = Buffer.byteLength(HOOK_LOG) + HOOK_SEG.length;
  // AMENDED job70 T200-1 (#200, plan Task 1: "`bantamkit_status` gains ... one line `touch:`"):
  // every block WAS without the `touch: none` line, which sits between the logs and retention.
  const expected = {
    // #199 D5: the session's `memory_recall` appends one `recall_hit` (70 bytes) to the usage
    // ledger, and the status lists it. WAS 'logs: none': recall wrote `last_recalled` instead.
    // AMENDED job68 J68-6 (#199, plan Task 6: "`Memory.save` must append the `save` event, with
    // keywords"): WAS 70; the session's `memory_save` now appends its `save` event (78 bytes).
    'mcp-only': [
      'storage: core on; hooks off; host data off',
      'index facts project: 1 doc, <n> bytes, persisted',
      'logs: usage/<id> 148 (0 rotated, 0 skipped)',
      'touch: none',
      'retention: off; last ran never; refused 0',
    ],
    hooked: [
      'storage: core on; hooks on; host data on',
      `logs: hook-log ${hookLogBytes} (1 rotated, 1 skipped)`,
      `logs: usage/abc123 ${Buffer.byteLength(USAGE_LINES)} (0 rotated, 1 skipped)`,
      'touch: none',
      `retention: off; last ran ${RAN_AT}; refused 1`,
    ],
    'project-hook': ['storage: core on; hooks on; host data off', 'logs: none', 'touch: none', 'retention: off; last ran never; refused 0'],
    'unwritable-index': [
      'storage: core on; hooks off; host data off',
      'index facts project: 1 doc, 0 bytes, in-memory',
      'logs: usage/<id> 148 (0 rotated, 0 skipped)', // #199 D5 and J68-6, as for mcp-only
      'touch: none',
      'retention: off; last ran never; refused 0',
    ],
  };
  const statusId = { 'mcp-only': STATUS_ID, hooked: 2, 'project-hook': 2, 'unwritable-index': 4 };
  for (const side of ['python', 'node']) {
    for (const session of Object.keys(expected)) {
      cases.push({
        name: `LITERAL: ${session} storage block (#200 touch line) — ${side}`,
        kind: 'json',
        expected: expected[session],
        actual: shaped(storageBlock(textOf(side, session, statusId[session]))),
      });
    }
    // Tier 1 runs complete: every served tool answered, and none of the answers is an error.
    const frames = byId(results.get('mcp-only')[side].frames);
    cases.push({
      name: `LITERAL: mcp-only every served tool answers without an error — ${side}`,
      kind: 'json',
      expected: TOOLS.map(([tool]) => [tool, false]),
      actual: TOOLS.map(([tool], i) => [tool, frames.get(FIRST_TOOL_ID + i)?.result?.isError ?? 'no result']),
    });
    const served = (frames.get(2)?.result?.tools ?? []).map((t) => t.name).sort();
    cases.push({
      name: `LITERAL: mcp-only drives every tool tools/list serves — ${side}`,
      kind: 'json',
      expected: TOOLS.map(([tool]) => tool).sort(),
      actual: served,
    });
    // #199 Task 6: the two lines after the storage block — the read-repair count and the usage
    // ledger, its path masked (a hash of this run's scratch store) and its counts not.
    const tail = (text) => {
      if (typeof text !== 'string') return null;
      const lines = text.split('\n');
      const at = lines.findIndex((l) => l.startsWith('read-repaired: '));
      return at === -1 ? null : lines.slice(at, at + 2).map((l) => l.replace(/^usage ledger: .*[\\/]\.bantamkit[\\/]usage[\\/][0-9a-f]{16}\.jsonl /, 'usage ledger: <home>/.bantamkit/usage/<id>.jsonl '));
    };
    // J68-10: the unwritable ledger lost the save's event and the recall's, and says so; the
    // writable sessions above keep the line they printed before the missed count existed.
    for (const [session, id, ledger] of [
      ['mcp-only', STATUS_ID, '(2 lines, 0 skipped)'],
      ['unwritable-index', 4, '(2 lines, 0 skipped)'],
      ['project-hook', 2, '(0 lines, 0 skipped)'],
      ['unwritable-ledger', 4, '(0 lines, 0 skipped, 2 missed writes)'],
    ]) {
      cases.push({
        name: `LITERAL: ${session} read-repair and usage ledger lines — ${side}`,
        kind: 'json',
        expected: ['read-repaired: 0 this process', `usage ledger: <home>/.bantamkit/usage/<id>.jsonl ${ledger}`],
        actual: tail(textOf(side, session, id)),
      });
    }
    // The spec's error rows: an unwritable index directory is the slow path, not a failure, and
    // an unwritable usage ledger (J68-10) loses its events without failing the recall either.
    for (const session of ['unwritable-index', 'unwritable-ledger']) {
      const recall = textOf(side, session, 3);
      cases.push({
        name: `LITERAL: ${session} recall still answers from the files — ${side}`,
        kind: 'json',
        expected: true,
        actual: typeof recall === 'string' && recall.includes('[tier-probe]'),
      });
    }
  }
  for (const session of Object.keys(expected)) {
    notes.push(`${session} storage block (python): ${JSON.stringify(storageBlock(textOf('python', session, statusId[session])))}`);
  }
  notes.push(`${sessions.length} sessions, both runtimes, over identical paths under ${root}`);
  return { cases, notes };
}
