/**
 * skill-propose — the `skill_propose` command, server-side sampling and the skills SessionStart
 * line (#206 Task 11), Python against Node.
 *
 * THE PROPERTY: a person who runs `/mcp__bantamkit__skill_propose` gets the same answer and the
 * same files from either runtime, and a session starts with the same skills line (or none). The
 * proposals file, `skills-state.json` and every skill written are shared on disk between the two
 * runtimes, so each op answers the whole home with every file's text.
 *
 * PART 1 (ops). One op list runs in order twice, by `ref/skillpropose_ref.py` in its own bed and
 * by `runNode` below against `dist/skillpropose.js` in another; each answer is one case:
 *   - list: empty (the fixed text), and a full home — four pending records in the file (three
 *     listed, PENDING_MAX), a rejected and a new one (never listed), live skills on probation,
 *     promoted, refused a promotion, and two needs-user items (a removal, a change with a diff);
 *   - approve with a stored gated draft (installed, not on probation), then undo (removed, and
 *     the proposal marked rejected so the daily run does not install it again);
 *   - approve with no draft through a sampling stub (one request, installed, the endpoint never
 *     configured), and a sampling answer that fails the gate (discarded and logged, no fall
 *     through to the host agent);
 *   - approve with no sampling and no endpoint: the host agent's hand-off naming the exact
 *     path; a file there that fails the gate (nothing installed, the file kept); a good file
 *     (installed, the hand-off directory removed);
 *   - approve on a host with no Claude Code directory: the stamped file printed, nothing written;
 *   - reject (rejected_at = successes), promote / undo-as-demote / undo, a needs-user removal
 *     approved and undone, a needs-user change rejected, and every refusal sentence;
 *   - the line: nothing new is null with the home unchanged (the 0-byte bar); seven items are
 *     cut on an item boundary within 200 bytes; the next call is null; a long name is clipped on
 *     a code point; `BANTAMKIT_SKILL_AUDIT=off` silences it and writes nothing.
 *
 * PART 2 (wire). Both servers as subprocesses over one bed rebuilt before each side at the same
 * path, the harness as a client that omits or declares `sampling` and answers
 * `sampling/createMessage` from a fixture: `prompts/list`, `prompts/get skill_propose` (list,
 * approve without sampling = the hand-off, an unknown action) and `tools/call bantamkit_status`
 * without sampling; approve WITH sampling (the request the server sends is compared, and the
 * skill installed) and the status line after it.
 *
 * THE LITERALS. A rule both runtimes lose together leaves every differential green, so the
 * constants, the prompt names in order, the line's bytes and the sampling request are pinned
 * per side.
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-propose';
export const summary = 'the skill_propose command, server-side sampling and the skills SessionStart line';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
const REF = join(here, 'ref', 'skillpropose_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');
const ASSETS = join(repoRoot, 'assets');

const NOW = '2026-10-27T12:00:00.000Z';
const COMMAND = '/mcp__bantamkit__skill_propose';
const PLANT = 'PLANTED TOOL OUTPUT 7f3a';

const draft = (n, cite = 'job1/U1') =>
  `---\nname: ${n}\ndescription: Does ${n}. Use when ${n} is asked.\n---\n\n` +
  `## When to use\n\nWhen asked.\n\n## Steps\n\n1. Do it [${cite}].\n\n## Pitfalls\n\nNone.\n\n## Example\n\nx\n`;

function record(n, successes = 6, o = {}) {
  const bar = o.bar ?? 3;
  const rec = {
    auto_bar: 2 * bar,
    auto_eligible: successes >= 2 * bar,
    bar,
    eligible: o.eligible ?? successes >= bar,
    evidence: Array.from({ length: successes }, (_, i) => ({
      commits: [],
      failure: null,
      id: `job1/U${i + 1}`,
      ok: true,
      paths: ['src/a.py'],
      prompt: `fix the thing number ${i}`,
      repo: '/r/.git',
      signals: { commit: true, tests: false },
      source: 'shiftwork',
      tools: ['Read', 'Edit'],
      ts: '2026-01-01T00:00:00Z',
      tool_result: PLANT,
    })),
    id: `c-${n}`,
    keywords: ['fix', n],
    level: o.level ?? 'user',
    members: successes,
    pitfalls: o.pitfalls ?? [],
    repos: [],
    source: 'shiftwork',
    status: o.status ?? 'pending',
    steps: o.steps ?? ['Read>Edit'],
    successes,
    top: o.top ?? null,
  };
  if (o.stored) rec.draft = { drafter: 'endpoint m', ok: true, text: draft(n), ts: NOW };
  return rec;
}

const proposals = (clusters) =>
  `${JSON.stringify({ clusters, miner: { error: null, ms: 0, pieces: { session: 0, shiftwork: 6 } }, ts: NOW, version: 1 }, null, 2)}\n`;
const stateText = (skills, extra = {}) => `${JSON.stringify({ skills, version: 1, ...extra }, null, 2)}\n`;
const entry = (n, o = {}) => ({
  at: NOW,
  auto: o.auto ?? false,
  cluster: `c-${n}`,
  level: 'user',
  name: n,
  path: `<bed>/${o.home ?? 'h2'}/.bantamkit/skills/${n}`,
  sha256: 'x',
  version: o.version ?? 1,
  versions: { 1: { false_fires: 0, injects: 0, successes: 0, uses: 0 } },
  ...(o.extra ?? {}),
});

function opList() {
  const ops = [];
  const label = [];
  const add = (l, op) => {
    label.push(l);
    ops.push(op);
  };
  const R = (home, action, target, o = {}) => ({ op: 'render', home, cwd: 'cwd', action, target, level: o.level ?? null, now: o.now ?? NOW, sampler: o.sampler ?? null });
  const claude = (home) => add(`${home}: a Claude Code home`, { op: 'put', home, rel: '.claude/settings.json', text: '{}\n' });

  add('constants', { op: 'constants' });
  add('list: an empty home is the fixed text', R('h1', null, null));
  add('line: nothing at all is null', { op: 'line', home: 'h1' });

  // h2: a full home for list and the line
  const longName = `a${'b'.repeat(62)}c`;
  add('h2: four pending, a rejected and a new proposal', {
    op: 'put',
    home: 'h2',
    rel: '.bantamkit/skill-proposals.json',
    text: proposals([
      record('p-one', 6, { pitfalls: [{ failure: 'blocked: the unit failed', id: 'job2/U9' }, { failure: null, id: 'job2/U8' }] }),
      record('p-two', 4),
      record('p-three', 3, { level: 'project', top: '<bed>/proj' }),
      record('p-four', 3),
      record('p-rejected', 9, { status: 'rejected' }),
      record('p-new', 2, { status: 'new' }),
    ]),
  });
  add('h2: skills on probation, promoted, refused, waiting on the user; seven events', {
    op: 'put',
    home: 'h2',
    rel: '.bantamkit/skills-state.json',
    text: stateText(
      {
        'on-probation': entry('on-probation', { auto: true, extra: { probation_until: '2026-11-26T12:00:00.000Z' } }),
        promoted: entry('promoted', { version: 3, extra: { promoted: { at: NOW, link: '<bed>/l', mode: 'copy', tree_sha256: 'y' } } }),
        refused: entry('refused', { extra: { promote_refused: { at: NOW, reason: 'promoting refused would take the catalogue to 9000 bytes, over the budget of 8192' } } }),
        'edited-old': entry('edited-old', { auto: true, extra: { proposal: { at: NOW, kind: 'remove', status: 'pending' } } }),
        'steps-change': entry('steps-change', { extra: { proposal: { at: NOW, diff: '-1. old [a]\n+1. new [b]', kind: 'steps', status: 'pending', text: draft('steps-change') } } }),
        'done-before': entry('done-before', { extra: { proposal: { at: NOW, kind: 'remove', status: 'rejected' } } }),
      },
      {
        events: [
          { at: '2026-10-26T00:00:00.000Z', event: 'installed skill on-probation' },
          { at: '2026-10-26T00:00:00.000Z', event: 'removed unused skill gone-one' },
          { at: '2026-10-26T00:00:00.000Z', event: 'proposed removing edited skill edited-old' },
          { at: '2026-10-27T00:00:00.000Z', event: 'promoted skill promoted' },
          { at: '2026-10-27T00:00:00.000Z', event: 'rolled back steps-change to v1' },
          { at: 7, event: 'not a stamp' },
          'not an event',
        ],
      },
    ),
  });
  add('list: a full home', R('h2', null, null));
  add('list: `action=list` reads as list', R('h2', 'action=list', null));
  add('line: eight new items, cut on an item boundary', { op: 'line', home: 'h2' });
  add('line: the second call is null', { op: 'line', home: 'h2' });
  add('h3: the full home again, for the switch', { op: 'put', home: 'h3', rel: '.bantamkit/skill-proposals.json', text: proposals([record('p-one')]) });
  add('line: BANTAMKIT_SKILL_AUDIT=off is null and writes nothing', { op: 'line', home: 'h3', env: 'off' });
  add('line: BANTAMKIT_SKILL_AUDIT=No is null too', { op: 'line', home: 'h3', env: 'No' });
  add('line: on, one new proposal', { op: 'line', home: 'h3', env: 'on' });
  add('render_line: a first item too long for the line is clipped on a code point', { op: 'render_line', items: [`installed ${'ก'.repeat(70)} on probation`, 'x'] });
  add('event_item: an install names its undo route', { op: 'event_item', event: `installed skill ${longName}` });
  add('event_item: an unknown event is said as it is', { op: 'event_item', event: 'rolled back x to v2' });

  // h4: approve a stored draft, list, undo
  claude('h4');
  add('h4: one proposal with a stored gated draft, one not eligible, one installed', {
    op: 'put',
    home: 'h4',
    rel: '.bantamkit/skill-proposals.json',
    text: proposals([record('stored-a', 6, { stored: true }), record('below', 2, { stored: true, status: 'new' }), record('already', 6, { status: 'installed' })]),
  });
  add('approve a stored draft: installed, not on probation', R('h4', 'approve', 'c-stored-a'));
  add('approve again: already installed', R('h4', 'approve', 'c-stored-a'));
  add('list after the approve', R('h4', 'list', null));
  add('promote it', R('h4', 'promote', 'stored-a'));
  add('undo a promoted skill demotes it', R('h4', 'undo', 'stored-a'));
  add('undo again removes the install and rejects its proposal', R('h4', 'undo', 'stored-a'));
  add('refused: approve below the bar', R('h4', 'approve', 'c-below'));
  add('refused: reject an installed proposal', R('h4', 'reject', 'c-already'));
  add('refused: unknown action', R('h4', 'bogus', 'x'));
  add('refused: no target', R('h4', 'approve', null));
  add('refused: a bad level', R('h4', 'approve', 'c-below', { level: 'global' }));
  add('refused: an unknown target', R('h4', 'reject', 'nope'));
  add('refused: promote an unknown skill', R('h4', 'promote', 'nope'));
  add('refused: demote a skill that is not installed', R('h4', 'demote', 'nope'));
  add('refused: undo an unknown skill', R('h4', 'undo', 'nope'));
  add('reject: rejected_at is the successes', R('h4', 'reject', 'target=c-below'));

  // h5: sampling
  claude('h5');
  add('h5: two proposals with no draft', { op: 'put', home: 'h5', rel: '.bantamkit/skill-proposals.json', text: proposals([record('sampled-a'), record('sampled-b')]) });
  add('approve through a sampling stub: one request, installed', R('h5', 'approve', 'c-sampled-a', { sampler: { answer: draft('sampled-a') } }));
  add('a sampling draft that fails the gate is discarded, no fall through', R('h5', 'approve', 'c-sampled-b', { sampler: { answer: draft('sampled-b', 'job9/U9') } }));
  add('sampling that gives no text falls through to the host agent', R('h5', 'approve', 'c-sampled-b', { sampler: { answer: null } }));

  // h6: the host agent
  claude('h6');
  add('h6: a proposal with no draft, project level', { op: 'put', home: 'h6', rel: '.bantamkit/skill-proposals.json', text: proposals([record('handed-a', 6, { level: 'project', top: '<bed>/proj' })]) });
  add('approve with no sampling and no endpoint: the hand-off and its path', R('h6', 'approve', 'c-handed-a'));
  add('the agent writes a SKILL.md that fails the gate', { op: 'put', home: 'h6', rel: '.bantamkit/skill-handoff/c-handed-a/SKILL.md', text: draft('handed-a', 'job9/U9') });
  add('approve again: the gate refuses, nothing installed, the file kept', R('h6', 'approve', 'c-handed-a'));
  add('the agent fixes the file', { op: 'put', home: 'h6', rel: '.bantamkit/skill-handoff/c-handed-a/SKILL.md', text: draft('handed-a') });
  add('approve again: installed in the project, the hand-off removed', R('h6', 'approve', 'c-handed-a'));

  // h7: no Claude Code directory
  add('h7: a stored draft on a host with no adapter', { op: 'put', home: 'h7', rel: '.bantamkit/skill-proposals.json', text: proposals([record('printed-a', 6, { stored: true })]) });
  add('approve with no adapter prints the file, writes nothing', R('h7', 'approve', 'c-printed-a'));

  // h8: needs-user items
  claude('h8');
  add('h8: an installed skill and its directory', { op: 'put', home: 'h8', rel: '.bantamkit/skills/edited-x/SKILL.md', text: draft('edited-x') });
  add('h8: its state, a removal waiting on the user; a change waiting too', {
    op: 'put',
    home: 'h8',
    rel: '.bantamkit/skills-state.json',
    text: stateText({
      'edited-x': entry('edited-x', { home: 'h8', auto: true, extra: { proposal: { at: NOW, kind: 'remove', status: 'pending' } } }),
      'change-y': entry('change-y', { home: 'h8', extra: { proposal: { at: NOW, kind: 'steps', status: 'pending' } } }),
    }),
  });
  add('approve the removal: removed with a backup', R('h8', 'approve', 'edited-x'));
  add('undo it: restored', R('h8', 'undo', 'edited-x'));
  add('approve a change that carries no text', R('h8', 'approve', 'change-y'));
  add('reject the change: kept, dropped', R('h8', 'reject', 'change-y'));
  add('line after all that: nothing the daily run did', { op: 'line', home: 'h8' });
  return { ops, label };
}

// ------------------------------------------------------------------------- Node side

function tree(home) {
  const out = [];
  const walk = (d) => {
    let names;
    try {
      names = fs.readdirSync(d);
    } catch {
      return;
    }
    names.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    for (const n of names) {
      const p = join(d, n);
      const rel = relative(home, p).split(sep).join('/');
      const st = fs.lstatSync(p);
      if (st.isSymbolicLink()) out.push(`${rel} -> ${fs.readlinkSync(p).split(sep).join('/')}`);
      else if (st.isDirectory()) {
        out.push(`${rel}/`);
        walk(p);
      } else out.push(`${rel}: ${fs.readFileSync(p).toString('utf8')}`);
    }
  };
  walk(home);
  return out;
}

const subst = (v, bed) =>
  typeof v === 'string' ? v.split('<bed>').join(bed) : Array.isArray(v) ? v.map((x) => subst(x, bed)) : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, subst(x, bed)])) : v;
const mask = (v, bed) =>
  typeof v === 'string' ? v.split(bed).join('<bed>') : Array.isArray(v) ? v.map((x) => mask(x, bed)) : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, mask(x, bed)])) : v;

async function runNode(ctx, bed, ops) {
  const sp = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'skillpropose.js')).href);
  const results = [];
  for (const raw of ops) {
    const op = subst(raw, bed);
    let out;
    if (op.op === 'constants') {
      out = [sp.SKILL_PROPOSE_NAME, sp.SKILL_PROPOSE_PROMPT_TITLE, sp.SKILL_PROPOSE_PROMPT_DESCRIPTION, sp.ARGUMENTS.map((a) => [...a]), [...sp.ACTIONS], sp.COMMAND, sp.SAMPLING_MAX_TOKENS, sp.HANDOFF_DIR, sp.LINE_MAX_BYTES, sp.EMPTY];
    } else if (op.op === 'render_line') {
      out = { line: sp.renderLine(op.items) };
    } else if (op.op === 'event_item') {
      out = { item: sp.eventItem(op.event) };
    } else {
      const home = join(bed, op.home);
      if (op.op === 'put') {
        const p = join(home, op.rel);
        fs.mkdirSync(dirname(p), { recursive: true });
        fs.writeFileSync(p, op.text, 'utf8');
        out = {};
      } else if (op.op === 'render') {
        const calls = [];
        let sampler = null;
        if (op.sampler !== null && op.sampler !== undefined) {
          const answer = op.sampler.answer ?? null;
          sampler = async (system, user) => {
            calls.push(createHash('sha256').update(`${system}\0${user}`, 'utf8').digest('hex'));
            return answer;
          };
        }
        const cwd = join(bed, op.cwd);
        fs.mkdirSync(cwd, { recursive: true });
        const text = await sp.render(op.action, op.target, op.level, home, cwd, op.now, sampler);
        out = { text, calls, tree: tree(home) };
      } else if (op.op === 'line') {
        const saved = process.env.BANTAMKIT_SKILL_AUDIT;
        delete process.env.BANTAMKIT_SKILL_AUDIT;
        if (op.env !== undefined && op.env !== null) process.env.BANTAMKIT_SKILL_AUDIT = op.env;
        try {
          out = { line: sp.sessionLine(home), tree: tree(home) };
        } finally {
          if (saved === undefined) delete process.env.BANTAMKIT_SKILL_AUDIT;
          else process.env.BANTAMKIT_SKILL_AUDIT = saved;
        }
      } else {
        throw new Error(`skill-propose: unknown op ${op.op}`);
      }
    }
    results.push(mask(JSON.parse(JSON.stringify(out)), bed));
  }
  return results;
}

// ------------------------------------------------------------------------- the wire

/**
 * One MCP session, lock-step: each request is written once the previous one has answered; a
 * request FROM the server (`sampling/createMessage`) is answered by `answer(frame)` and kept.
 *
 * platform-checked: the kill below is a hard stop on a session already declared stuck, with the
 * `reject()` beside it reporting the failure; nothing waits for a signal handler to run.
 */
function converse(command, args, { env, cwd, lines, answer }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });
    const frames = new Map();
    const asked = [];
    let out = '';
    let err = '';
    let i = 0;
    let waiting = null;
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`skill-propose: session timed out\nstderr:\n${err}`));
    }, 60_000);
    const next = () => {
      while (i < lines.length) {
        const line = lines[i++];
        child.stdin.write(`${line}\n`);
        const id = JSON.parse(line).id;
        if (id !== undefined) {
          waiting = id;
          return;
        }
      }
      waiting = null;
      child.stdin.end();
    };
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      let at;
      while ((at = out.indexOf('\n')) !== -1) {
        const line = out.slice(0, at);
        out = out.slice(at + 1);
        let f;
        try {
          f = JSON.parse(line);
        } catch {
          continue;
        }
        if (f.method !== undefined && f.id !== undefined) {
          asked.push(f);
          child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id: f.id, result: answer(f) })}\n`);
          continue;
        }
        if (f.id !== undefined && f.method === undefined) {
          frames.set(f.id, f);
          if (f.id === waiting) next();
        }
      }
    });
    child.stderr.on('data', (c) => {
      err += c.toString('utf8');
    });
    child.on('close', () => {
      clearTimeout(timer);
      resolve({ frames, asked, stderr: err });
    });
    child.on('error', reject);
    next();
  });
}

const rpc = (id, method, params) => JSON.stringify({ jsonrpc: '2.0', id, method, params });
const INITIALIZED = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' });
const init = (caps) => rpc(1, 'initialize', { protocolVersion: '2025-06-18', capabilities: caps, clientInfo: { name: 'conformance', version: '0' } });

function wireBed(base) {
  fs.rmSync(base, { recursive: true, force: true });
  const home = join(base, 'home');
  fs.mkdirSync(join(home, '.claude'), { recursive: true });
  fs.mkdirSync(join(base, 'cwd'), { recursive: true });
  fs.mkdirSync(join(home, '.bantamkit'), { recursive: true });
  fs.writeFileSync(join(home, '.bantamkit', 'skill-proposals.json'), proposals([record('wire-a')]));
  const env = { ...process.env, BANTAMKIT_ASSETS: ASSETS, HOME: home, USERPROFILE: home, BANTAMKIT_INDEX_DIR: join(base, 'idx'), BANTAMKIT_RETENTION: 'off', BANTAMKIT_SKILL_AUDIT: 'off', BANTAMKIT_SKILL_AUTO: 'off' };
  for (const k of ['BANTAMKIT_MEMORY_DIR', 'BANTAMKIT_EVENT_LOG', 'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE', 'BANTAMKIT_LLM_URL', 'BANTAMKIT_LLM_MODEL']) delete env[k];
  return { env, cwd: join(base, 'cwd'), store: join(base, 'store'), home };
}

async function wire(ctx) {
  const sessions = {};
  const plain = [
    init({}),
    INITIALIZED,
    rpc(2, 'prompts/list', {}),
    rpc(3, 'prompts/get', { name: 'skill_propose' }),
    rpc(4, 'prompts/get', { name: 'skill_propose', arguments: { action: 'approve', target: 'c-wire-a' } }),
    rpc(5, 'prompts/get', { name: 'skill_propose', arguments: { action: 'bogus' } }),
    rpc(6, 'tools/call', { name: 'bantamkit_status', arguments: {} }),
  ];
  const sampled = [
    init({ sampling: {} }),
    INITIALIZED,
    rpc(2, 'prompts/get', { name: 'skill_propose', arguments: { action: 'approve', target: 'c-wire-a' } }),
    rpc(3, 'tools/call', { name: 'bantamkit_status', arguments: {} }),
    rpc(4, 'prompts/get', { name: 'skill_propose', arguments: {} }),
  ];
  const answer = () => ({ content: { text: draft('wire-a'), type: 'text' }, model: 'stub', role: 'assistant', stopReason: 'endTurn' });
  const base = join(ctx.scratch, 'skill-propose-wire');
  for (const side of ['py', 'nd']) {
    sessions[side] = {};
    for (const [label, lines] of [
      ['plain', plain],
      ['sampled', sampled],
    ]) {
      const bed = wireBed(join(base, label));
      const [command, args] = side === 'py' ? [ctx.python, ['-m', 'bantamkit.mcpserver', '--store', bed.store]] : [process.execPath, [CLI, '--store', bed.store]];
      // As `ref/wire_ref.py` does: the reference server imports THIS tree's source, never the
      // checkout an editable install happens to point at.
      const env = side === 'py' ? { ...bed.env, PYTHONPATH: join(repoRoot, 'runtime-py', 'src'), PYTHONSAFEPATH: '1' } : bed.env;
      const got = await converse(command, args, { env, cwd: bed.cwd, lines, answer });
      // The server's `now` is the wall clock: every stamp in a file, and the backup's name, is masked.
      got.tree = tree(bed.home).map((l) =>
        l
          .split(base)
          .join('<base>')
          .replace(/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z/g, '<now>')
          .replace(/\d{8}T\d{6}\.\d{3}Z/g, '<stamp>'),
      );
      sessions[side][label] = got;
    }
  }
  return sessions;
}

// ---------------------------------------------------------------------------- cases

export async function run(ctx) {
  const cases = [];
  const bed = (side) => mkdtempSync(join(ctx.scratch, `skill-propose-${side}-`));
  const { ops, label } = opList();
  const py = ctx.runPython(REF, { bed: bed('py'), ops }).results;
  const nd = await runNode(ctx, bed('node'), ops);
  ops.forEach((op, i) => {
    if (op.op === 'put') return;
    cases.push({ name: label[i], kind: 'json', expected: py[i], actual: nd[i] });
  });

  const find = (l) => {
    const i = label.indexOf(l);
    if (i < 0) throw new Error(`skill-propose: no op labelled ${l}`);
    return i;
  };
  const LINE =
    `[bantamkit] skills: installed on-probation on probation (undo: ${COMMAND} undo on-probation); +7 more — ${COMMAND} lists them.`;
  for (const [side, got] of [
    ['python', py],
    ['node', nd],
  ]) {
    cases.push({
      name: `LITERAL: constants — ${side}`,
      kind: 'json',
      expected: [
        'skill_propose',
        'bantamkit skill proposals',
        'List the skills bantamkit proposes from your repeated, successful work and the ones it installed, or approve, reject, undo, promote or demote one by its id or name.',
        [
          ['action', 'list (the default), approve, reject, undo, promote or demote'],
          ['target', 'a proposal id, or the name of an installed skill'],
          ['level', 'project or user: where an approved skill is installed'],
        ],
        ['list', 'approve', 'reject', 'undo', 'promote', 'demote'],
        COMMAND,
        4096,
        'skill-handoff',
        200,
        'bantamkit skill proposals: nothing is pending and no skill is installed. The daily run proposes a skill once the same work has succeeded 3 times in shiftwork units or 5 times in sessions.',
      ],
      actual: got[0],
    });
    const listed = got[find('list: a full home')].text;
    cases.push({
      name: `LITERAL: list shows three of four pending, never the rejected or the new one — ${side}`,
      kind: 'json',
      expected: { pending: 'Pending (3 of at most 3):', four: false, rejected: false, fresh: false, waiting: 2 },
      actual: {
        pending: listed.split('\n').find((l) => l.startsWith('Pending')) ?? null,
        four: listed.includes('c-p-four'),
        rejected: listed.includes('c-p-rejected'),
        fresh: listed.includes('c-p-new'),
        waiting: listed.split('\n').filter((l) => /^- (edited-old|steps-change|done-before):/.test(l)).length,
      },
    });
    const line = got[find('line: eight new items, cut on an item boundary')].line;
    cases.push({
      name: `LITERAL: the line over eight items, its bytes, then null — ${side}`,
      kind: 'json',
      expected: { line: LINE, bytes: Buffer.byteLength(LINE), fits: true, again: null },
      actual: { line, bytes: line === null ? null : Buffer.byteLength(line), fits: line !== null && Buffer.byteLength(line) <= 200, again: got[find('line: the second call is null')].line },
    });
    const off = got[find('line: BANTAMKIT_SKILL_AUDIT=off is null and writes nothing')];
    cases.push({
      name: `LITERAL: the switch off is null and writes nothing; on names the one proposal — ${side}`,
      kind: 'json',
      expected: { off: null, written: false, on: `[bantamkit] skills: new proposal c-p-one — ${COMMAND} lists them.` },
      actual: { off: off.line, written: off.tree.some((l) => l.startsWith('.bantamkit/skills-state.json')), on: got[find('line: on, one new proposal')].line },
    });
    const sampledA = got[find('approve through a sampling stub: one request, installed')];
    const failedB = got[find('a sampling draft that fails the gate is discarded, no fall through')];
    cases.push({
      name: `LITERAL: sampling asked once and installed; a failed gate is not a fall-through — ${side}`,
      kind: 'json',
      expected: { calls: 1, installed: true, failedCalls: 1, failed: true, handoff: false },
      actual: {
        calls: sampledA.calls.length,
        installed: sampledA.text.startsWith('installed skill sampled-a at '),
        failedCalls: failedB.calls.length,
        failed: failedB.text.startsWith('The draft from sampling did not pass the gate'),
        handoff: failedB.text.includes('so you draft it'),
      },
    });
    const refused = got[find('approve again: the gate refuses, nothing installed, the file kept')];
    cases.push({
      name: `LITERAL: a hand-off file that fails the gate installs nothing — ${side}`,
      kind: 'json',
      expected: { refused: true, skill: false, kept: true },
      actual: {
        refused: refused.text.includes('did not pass the gate, so nothing was installed'),
        skill: refused.tree.some((l) => l.includes('.bantamkit/skills/handed-a')),
        kept: refused.tree.some((l) => l.startsWith('.bantamkit/skill-handoff/c-handed-a/SKILL.md: ')),
      },
    });
  }

  // ------------------------------------------------------------------- Part 2: the wire
  const { dumpJson, parseJson } = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'pyjson.js')).href);
  const canonical = (frame) => (frame === undefined ? 'MISSING' : dumpJson(parseJson(JSON.stringify(frame)), { sortKeys: true, indent: 2 }));
  const s = await wire(ctx);
  for (const [label, ids] of [
    ['plain', [2, 3, 4, 5]],
    ['sampled', [2, 4]],
  ]) {
    for (const id of ids) {
      cases.push({ name: `wire ${label}: id ${id}`, kind: 'string', expected: canonical(s.py[label].frames.get(id)), actual: canonical(s.nd[label].frames.get(id)) });
    }
    cases.push({ name: `wire ${label}: the home after the session`, kind: 'json', expected: s.py[label].tree, actual: s.nd[label].tree });
  }
  const strip = (f) => (f === undefined ? null : { method: f.method, params: f.params });
  cases.push({ name: 'wire sampled: the sampling request the server sent', kind: 'string', expected: canonical(strip(s.py.sampled.asked[0])), actual: canonical(strip(s.nd.sampled.asked[0])) });
  const skillsLine = (f) => (f?.result?.content?.[0]?.text ?? '').split('\n').find((l) => l.startsWith('skills: ')) ?? null;
  for (const side of ['py', 'nd']) {
    const who = side === 'py' ? 'python' : 'node';
    const w = s[side];
    cases.push({
      name: `LITERAL: wire prompts/list names, in order — ${who}`,
      kind: 'json',
      expected: ['bantamkit_status', 'skill_audit', 'skill_propose'],
      actual: (w.plain.frames.get(2)?.result?.prompts ?? []).map((p) => p.name),
    });
    cases.push({
      name: `LITERAL: wire status line 3 and the drafter, without and with sampling — ${who}`,
      kind: 'json',
      expected: {
        line3: 'serving 15 tools, 3 prompts, 2 resource templates',
        plain: 'skills: off; mined 2026-10-27T12:00:00.000Z in 0 ms; 1 pending, 0 of 5 auto-installed live, 0 promoted; drafter host agent',
        sampled: 'skills: off; mined 2026-10-27T12:00:00.000Z in 0 ms; 0 pending, 0 of 5 auto-installed live, 0 promoted; drafter sampling',
        askedPlain: 0,
      },
      actual: {
        line3: (w.plain.frames.get(6)?.result?.content?.[0]?.text ?? '').split('\n')[2] ?? null,
        plain: skillsLine(w.plain.frames.get(6)),
        sampled: skillsLine(w.sampled.frames.get(3)),
        askedPlain: w.plain.asked.length,
      },
    });
    const req = w.sampled.asked[0]?.params ?? {};
    cases.push({
      name: `LITERAL: wire the sampling request: method, maxTokens, system prompt, one user message — ${who}`,
      kind: 'json',
      expected: { method: 'sampling/createMessage', maxTokens: 4096, system: true, messages: 1, role: 'user', installed: true },
      actual: {
        method: w.sampled.asked[0]?.method ?? null,
        maxTokens: req.maxTokens ?? null,
        system: typeof req.systemPrompt === 'string' && req.systemPrompt.startsWith('You turn evidence of repeated, successful work'),
        messages: req.messages?.length ?? 0,
        role: req.messages?.[0]?.role ?? null,
        installed: (w.sampled.frames.get(2)?.result?.messages?.[0]?.content?.text ?? '').startsWith('installed skill wire-a at '),
      },
    });
  }
  return { cases, notes: [] };
}
