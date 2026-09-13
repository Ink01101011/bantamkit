/**
 * `repo_map` (job45, roadmap row 10): the ranked definition map on the MCP surface, Node half.
 *
 * WHAT THIS FILE IS FOR, AND WHAT IT IS NOT FOR. `repomap.test.mjs` owns the engine — the
 * scanner, the graph, the ranking, the budget and every omission. This file owns the SURFACE:
 * the registration, the three refusals, the reply's shape, and the event log's silence about
 * the paths it was handed. Nothing here calls the handler directly; every node drives a real
 * `Server` through the SDK's in-memory pair, because a node that called the function would
 * agree with itself through any registration mistake — and the registration is half of what
 * this unit added.
 *
 * IT IS THE REFERENCE'S `runtime-py/tests/test_repo_map_tool.py`, NODE FOR NODE. The
 * byte-for-byte differential against the Python handler is `tools/conformance/suites/
 * repomap.mjs`, not this file; what is here is the half a differential cannot see — the
 * LITERAL assertions, which are the only shape that reddens when a rule is changed on both
 * sides at once (`differential-is-blind-to-symmetric-regression`).
 *
 * THE FIXTURE IS A BUILT TREE, NEVER THE REPOSITORY. J45-10 measured three separate wrong
 * answers from using this repository as a repo-map corpus while the unit was writing into
 * it: adding a test file produced 40 phantom edge rows, and creating one note moved
 * `unknown-language` from 1689 to 1690 and scored four equivalent mutants as KILLED.
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';

import { CAP_BYTES, EventLog } from '../dist/eventlog.js';
import { Memory } from '../dist/memory/component.js';
import { REPO_MAP_EMPTY, REPO_MAP_TAIL, buildServer } from '../dist/mcp/server.js';
import { repoMap } from '../dist/repomap.js';

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(packageRoot);
const FIXED_MS = 1756029153412;

/** Every path segment and file name in the fixture is a sentinel, so the privacy node
 *  below asserts on BYTES rather than on a policy someone read. */
const SENTINEL = 'SECRET-TREE-4c1b';

const SERVED_ORDER = [
  'memory_save',
  'memory_recall',
  'validate_json',
  'shiftwork_clock_in',
  'shiftwork_clock_out',
  'shiftwork_status',
  'build_identity',
  'bantamkit_status',
  'memory_compact',
  'bantamkit_read',
  'skill_audit',
  'memory_dream',
  'repo_map',
  'token_ledger',
];

/**
 * RETIRED FROM THE ROSTER, NOT DELETED. `repo_map` left `tools/list` on the user's ruling of
 * 2026-09-12 (job50 I5): measured over the transcript corpus it was never called, and every
 * request re-sent its description. Every node here drives the tool THROUGH the server by
 * design (see the module docstring), so none can run while the handler is DORMANT in
 * `server.ts`. The module stays as the record of what the surface promised and what will have
 * to hold again if the roster line returns — `SERVED_ORDER` above and the "thirteenth" pin
 * below are left as they were served, not silently renumbered; the skip is the honest state.
 * `repomap.test.mjs`, the engine's own suite, is untouched and still runs. `server.test.mjs`'s
 * retired-tools node pins that `repo_map` is off; this file mirrors the reference's
 * `test_repo_map_tool.py`, which is skipped the same way.
 */
const RETIRED = { skip: 'repo_map left the MCP roster by ruling (job50 I5, 2026-09-12); handler DORMANT' };

const scratch = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-repomap-tool-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

let seq = 0;
const room = () => {
  const dir = join(scratch, `r${(seq += 1)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
};

function make(dir) {
  const memory = new Memory(join(dir, 'store'));
  const path = join(dir, 'log.jsonl');
  return { memory, path, log: new EventLog(path, CAP_BYTES, () => FIXED_MS) };
}

async function connect(memory, log) {
  const wire = { rawLineFor: () => undefined, setExactResult: () => {} };
  const server = buildServer(memory, wire, '0.0.0-test', log);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: 'repomap-tool-test', version: '0' }, { capabilities: {} });
  await Promise.all([server.connect(serverSide), client.connect(clientSide)]);
  return client;
}

const callMap = async (client, args) => {
  const answer = await client.callTool({ name: 'repo_map', arguments: args });
  return [answer.isError === true, answer.content[0].text];
};

const records = (path) =>
  readFileSync(path, 'utf8')
    .split('\n')
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line));

/**
 * A two-file Python package plus one file the scanner has no dialect for.
 *
 * BYTE-IDENTICAL TO THE REFERENCE'S `tree()`. `dream.py` names `Store`, `save` and `load`,
 * all of which only `store.py` defines, so there is exactly one edge and the ranking is not
 * a coin toss. `README` is the `unknown-language` omission, which is what proves the footer
 * reaches the reply.
 */
function tree(dir) {
  const root = join(dir, SENTINEL);
  mkdirSync(join(root, 'pkg'), { recursive: true });
  writeFileSync(
    join(root, 'pkg', 'store.py'),
    '"""A docstring naming Store, so the strip is load-bearing."""\n' +
      'class Store:\n' +
      '    def save(self, fact):\n' +
      '        return fact\n' +
      '    def load(self, key):\n' +
      '        return key\n',
  );
  writeFileSync(
    join(root, 'pkg', 'dream.py'),
    'from pkg.store import Store\n' +
      'def dream(store):\n' +
      '    s = Store()\n' +
      '    s.save(1)\n' +
      '    return s.load(2)\n',
  );
  writeFileSync(join(root, 'README'), 'not source\n');
  return root;
}

// ------------------------------------------------------------------ registration

test('repo_map is served thirteenth and its schema is the asset', RETIRED, async () => {
  // The index is pinned rather than `at(-1)`: this node is about where `repo_map` sits, and
  // a later tool moving in behind it must not be able to satisfy it.
  const { memory, log } = make(room());
  const client = await connect(memory, log);
  const listed = (await client.listTools()).tools;
  assert.deepEqual(listed.map((t) => t.name), SERVED_ORDER);
  assert.equal(listed[12].name, 'repo_map');
  assert.equal(listed.length, 14);
  const asset = JSON.parse(readFileSync(join(repoRoot, 'assets', 'tools', 'repo_map.json'), 'utf8'));
  const served = listed[12];
  assert.equal(served.description, asset.description);
  assert.deepEqual(served.inputSchema, asset.parameters);
  assert.deepEqual(served.outputSchema, asset.output_schema);
  await client.close();
});

// ---------------------------------------------------------------------- refusals

test('an empty root is refused and never the server\'s own cwd', RETIRED, async () => {
  const dir = room();
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);
  const [isError, text] = await callMap(client, { root: '' });
  assert.equal(isError, false);
  assert.ok(text.includes('root must not be empty; name the directory to map'), text);
  assert.deepEqual(records(path).map((r) => r.outcome), ['refused']);
  assert.deepEqual(records(path)[0].detail, {});
  await client.close();
});

test('a missing root and a file root refuse differently', RETIRED, async () => {
  const dir = room();
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const missing = join(dir, 'nowhere');
  const [, gone] = await callMap(client, { root: missing });
  assert.ok(gone.includes(`no such directory: ${missing}`), gone);

  const plain = join(dir, 'plain.py');
  writeFileSync(plain, 'def f():\n    return 1\n');
  const [, file] = await callMap(client, { root: plain });
  assert.ok(file.includes(`${plain} is a file, not a directory to map`), file);
  await client.close();
});

test('a negative budget is refused and zero is not', RETIRED, async () => {
  const dir = room();
  const root = tree(dir);
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [, negative] = await callMap(client, { root, budget: -1 });
  assert.ok(negative.includes('budget must not be negative; got -1'), negative);
  const [, zero] = await callMap(client, { root, budget: 0 });
  assert.ok(!zero.includes('budget must not be negative'), zero);
  assert.ok(zero.includes('budget='), zero);
  await client.close();
});

test(
  'a dangling symlink root is a missing directory and not a crash',
  RETIRED, // was: skip on win32 — 'a dangling directory symlink needs a privilege Windows may not grant'
  async () => {
    // The reference gets this free from `Path.exists()`, which follows and swallows ENOENT.
    // Here it is `statSync` plus `EXISTS_IGNORED` — real logic, not a translated line, which
    // is J45-10 §3.1's finding applied to the surface rather than to the walk.
    const dir = room();
    const link = join(dir, 'dangling');
    symlinkSync(join(dir, 'nowhere'), link);
    const { memory, log } = make(dir);
    const client = await connect(memory, log);
    const [, text] = await callMap(client, { root: link });
    assert.ok(text.includes(`no such directory: ${link}`), text);
    await client.close();
  },
);

// ------------------------------------------------------------------------ answers

test("the reply is the module's own map plus the header and the tail", RETIRED, async () => {
  const dir = room();
  const root = tree(dir);
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [, text] = await callMap(client, { root, focus: ['pkg/dream.py'] });
  const result = repoMap(root, { focus: ['pkg/dream.py'] });
  assert.ok(text.includes(result.text), text);
  assert.ok(
    text.startsWith(
      `repo map: ${result.nodes} files scanned, ${result.definitions} definitions, ` +
        `${result.edges} edges.\n`,
    ),
    text,
  );
  assert.ok(text.includes('focus: pkg/dream.py\n'), text);
  assert.ok(text.endsWith(REPO_MAP_TAIL), text);
  // The footer travels: `README` has no dialect and must be counted, not dropped.
  assert.ok(text.includes('# omitted:'), text);
  assert.ok(text.includes('unknown-language=1'), text);
  await client.close();
});

test('no focus is plain centrality and says so', RETIRED, async () => {
  const dir = room();
  const root = tree(dir);
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [, text] = await callMap(client, { root });
  assert.ok(text.includes('focus: (none) — plain centrality over the whole tree\n'), text);
  await client.close();
});

test('an empty tree names the reason rather than rendering nothing', RETIRED, async () => {
  const dir = room();
  const empty = join(dir, 'empty');
  mkdirSync(empty, { recursive: true });
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [, text] = await callMap(client, { root: empty });
  assert.ok(text.includes(REPO_MAP_EMPTY), text);
  assert.ok(text.includes('repo map: 0 files scanned, 0 definitions, 0 edges.'), text);
  await client.close();
});

test('a focus that is not a scanned source is ignored and never refused', RETIRED, async () => {
  const dir = room();
  const root = tree(dir);
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [isError, text] = await callMap(client, { root, focus: ['docs/nothing-here.md'] });
  assert.equal(isError, false);
  assert.ok(text.includes('focus: docs/nothing-here.md\n'), text);
  await client.close();
});

test('the tail never claims a token saving', RETIRED, async () => {
  // The one sentence this feature is not allowed to say. Row 10's build gate was REFUTED
  // (`docs/roadmap-toolbox.md`): discovery is 0.114 % of real prompt tokens. A reply that
  // implied otherwise would be the product contradicting the measurement that let it ship.
  const dir = room();
  const root = tree(dir);
  const { memory, log } = make(dir);
  const client = await connect(memory, log);
  const [, text] = await callMap(client, { root });
  assert.ok(text.includes('precision pass, not a token saving'), text);
  assert.ok(text.includes('0.114%'), text);
  assert.ok(text.includes('REFUTED'), text);
  assert.ok(text.includes('UTF-8 BYTES'), text);
  // `cheaper` appears once, negated, so the search runs over the text with that clause
  // removed — otherwise the node passes on the very sentence it exists to police.
  const rest = text.replace('so a map does not make a session cheaper', '');
  for (const claim of ['saves tokens', 'fewer tokens', 'cheaper', 'saving of']) {
    assert.ok(!rest.includes(claim), claim);
  }
  await client.close();
});

// --------------------------------------------------------------------- the record

test('the event log records the decision and no path of it', RETIRED, async () => {
  const dir = room();
  const root = tree(dir);
  const { memory, path, log } = make(dir);
  const client = await connect(memory, log);
  await callMap(client, { root, focus: ['pkg/dream.py'] });
  const written = records(path);
  assert.deepEqual(written.map((r) => r.tool), ['repo_map']);
  assert.equal(written[0].outcome, 'mapped');
  assert.deepEqual(Object.keys(written[0].detail).sort(), [
    'definitions',
    'edges',
    'files_rendered',
    'listing_bytes',
    'nodes',
  ]);
  const raw = readFileSync(path);
  assert.ok(!raw.includes(SENTINEL), 'the root leaked into the log');
  assert.ok(!raw.includes('dream.py'), 'a focus path leaked into the log');
  assert.ok(!raw.includes('store.py'), 'a mapped path leaked into the log');
  await client.close();
});
