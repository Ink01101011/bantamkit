// J67-7 probe: facts the docs sweep quotes, measured on one side.
// Usage (repo root): node .shiftwork/notes-job67/J67-7-probe.mjs <py|node> <what>
//   what = list     -> served tools: name | title | readOnlyHint | first description sentence
//          recall   -> memory_recall in a cwd with no store on any ancestor (designated sentence)
//          eventlog -> work_plan + shiftwork_plan with BANTAMKIT_EVENT_LOG=on, prints tool:outcome
//          compact  -> eviction order over user/feedback/project/reference facts, prints survivors
//          desc <tool> -> full description of one served tool
//          clip     -> validate_json on a 1 MiB string against maxLength 10: feedback length and text head
//          res      -> resources/templates/list, prompts/list, resources/read of skills/file-graph, prompts/get nope
//          identity -> build_identity's assets_digest and the asset file count
//          yaml     -> a store holding `description: 2026` and one anchored description: recall + save replies
//          wave     -> N1,N2 independent, N3 needs both: plan, clock_in x3, clock_out N2/N3/N1, log line kinds
//          status [budget] -> bantamkit_status over a 2-fact project store (budget: --index-budget), <project> redacts the scratch dir
// HOME/USERPROFILE go to a fresh mkdtemp under $TMPDIR, asserted before any server spawns.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [side, what = 'list', arg] = process.argv.slice(2);
const root = process.cwd();
const W = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'j67-7-')));
const H = path.join(W, 'home');
fs.mkdirSync(H);
const baseEnv = { ...process.env, HOME: H, USERPROFILE: H };
delete baseEnv.BANTAMKIT_EVENT_LOG;
delete baseEnv.BANTAMKIT_MEMORY_DIR;
if (baseEnv.HOME !== H || !H.startsWith(fs.realpathSync(os.tmpdir()))) throw new Error('HOME redirect did not take');

function server({ cwd = W, args = [], env = {} } = {}) {
  const e = { ...baseEnv, ...env };
  let cmd, argv;
  if (side === 'py') {
    cmd = path.join(root, '.venv/bin/python');
    argv = ['-m', 'bantamkit.mcpserver', ...args];
    e.PYTHONPATH = path.join(root, 'runtime-py/src');
  } else {
    cmd = process.execPath;
    argv = [path.join(root, 'runtime-ts/dist/cli.js'), ...args];
  }
  const p = spawn(cmd, argv, { cwd, env: e });
  let buf = '';
  const wait = new Map();
  p.stdout.setEncoding('utf8');
  p.stdout.on('data', (d) => {
    buf += d;
    for (let i; (i = buf.indexOf('\n')) >= 0; ) {
      const l = buf.slice(0, i);
      buf = buf.slice(i + 1);
      try { const m = JSON.parse(l); wait.get(m.id)?.(m); } catch {}
    }
  });
  let id = 0;
  const req = (method, params) =>
    new Promise((r) => { wait.set(++id, r); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
  const call = async (name, a = {}) => {
    const m = await req('tools/call', { name, arguments: a });
    return ((m.result ?? {}).content ?? []).map((c) => c.text).join('') || JSON.stringify(m.error);
  };
  return {
    req, call,
    async init() {
      await req('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'j67-7', version: '0' } });
      p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');
    },
    close: () => new Promise((r) => { p.on('close', r); p.stdin.end(); }),
  };
}

const fact = (n, d, o = {}) => `---\nname: ${n}\ndescription: ${d}\ntype: ${o.type ?? 'project'}\ncreated: '${o.created ?? '2026-10-13'}'\nlast_recalled: null\nlinks: []\n---\n\nbody of ${n}\n`;
function store(dir, facts) {
  const s = path.join(dir, '.bantamkit/memory');
  fs.mkdirSync(path.join(s, 'facts'), { recursive: true });
  for (const [n, d, o] of facts) fs.writeFileSync(path.join(s, 'facts', `${n}.md`), fact(n, d, o), 'utf8');
  fs.writeFileSync(path.join(s, 'index.md'), facts.map(([n, d, o = {}]) => `- [[${n}]] (${o.type ?? 'project'}) — ${d}\n`).sort().join(''), 'utf8');
  return s;
}

if (what === 'list' || what === 'desc') {
  const c = server({ args: ['--store', path.join(W, 'store')] });
  await c.init();
  const tools = (await c.req('tools/list')).result.tools;
  if (what === 'desc') console.log(tools.find((t) => t.name === arg)?.description);
  else for (const t of tools) console.log(`${t.name} | ${t.title} | readOnly=${t.annotations?.readOnlyHint} | ${t.description.split(/(?<=\.)\s/)[0]}`);
  if (what === 'list') console.log(`count=${tools.length}`);
  await c.close();
} else if (what === 'recall') {
  const cwd = path.join(W, 'nostore');
  fs.mkdirSync(cwd);
  const c = server({ cwd });
  await c.init();
  console.log((await c.call('memory_recall', { query: 'x' })).split(H).join('<home>').split(W).join('<tmp>'));
  await c.close();
  console.log('created .bantamkit:', fs.existsSync(path.join(cwd, '.bantamkit')));
} else if (what === 'eventlog') {
  const d = path.join(W, 'p');
  const s = store(d, []);
  const c = server({ cwd: d, env: { BANTAMKIT_EVENT_LOG: 'on' } });
  await c.init();
  await c.call('work_plan', { nodes: [] });
  await c.call('work_plan', { nodes: [{ id: 'a', depends_on: ['b'] }] });
  await c.call('shiftwork_plan', { checkpoint: path.join(d, 'none.json') });
  await c.call('bantamkit_status', {});
  await c.close();
  console.log(fs.readFileSync(path.join(s, 'events/mcp.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)).map((e) => `${e.tool}:${e.outcome}`).join(' '));
} else if (what === 'compact') {
  const d = path.join(W, 'p');
  const s = store(d, [
    ['old-user', 'oldest user fact', { type: 'user', created: '2024-01-01' }],
    ['fb', 'feedback fact', { type: 'feedback', created: '2026-01-01' }],
    ...[1, 2, 3, 4].map((i) => [`proj-${i}`, `project fact ${i}`, { type: i % 2 ? 'project' : 'reference', created: `2026-0${i}-01` }]),
  ]);
  const c = server({ cwd: d, args: ['--index-budget', '200'] });
  await c.init();
  console.log((await c.call('memory_compact', { reserve: 140 })).split('\n')[0]);
  await c.close();
  console.log('still live:', fs.readdirSync(path.join(s, 'facts')).filter((f) => f.endsWith('.md')).sort().join(','));
}
else if (what === 'status') {
  const d = path.join(W, 'project');
  store(d, [['deploy-command', 'how we deploy'], ['style', 'house style']]);
  const c = server({ cwd: d, args: arg ? ['--index-budget', arg] : [] });
  await c.init();
  console.log((await c.call('bantamkit_status', {})).split(d).join('<project>'));
  await c.close();
}
else if (what === 'clip') {
  const c = server({ args: ['--store', path.join(W, 'store')] });
  await c.init();
  const out = JSON.parse(await c.call('validate_json', { output: JSON.stringify({ x: 'y'.repeat(1 << 20) }), schema: { type: 'object', properties: { x: { type: 'string', maxLength: 10 } } } }));
  console.log(`valid=${out.valid} feedback_chars=${[...out.feedback].length} feedback=${out.feedback.slice(0, 120)}`);
  await c.close();
}
else if (what === 'res') {
  const c = server({ args: ['--store', path.join(W, 'store')] });
  await c.init();
  console.log('templates:', (await c.req('resources/templates/list')).result.resourceTemplates.map((t) => t.uriTemplate).join(', '));
  console.log('prompts:', (await c.req('prompts/list')).result.prompts.map((t) => t.name).join(', '));
  console.log('file-graph:', JSON.stringify((await c.req('resources/read', { uri: 'bantamkit://skills/file-graph' })).error));
  console.log('prompts/get nope:', JSON.stringify((await c.req('prompts/get', { name: 'nope' })).error));
  console.log('repo_map:', await c.call('repo_map', { root: '.' }), '| bantamkit_read:', await c.call('bantamkit_read', { path: '.' }));
  console.log('unknown arg:', await c.call('work_plan', { nodes: [], unitId: 'x' }));
  await c.close();
}
else if (what === 'identity') {
  const c = server({ args: ['--store', path.join(W, 'store')] });
  await c.init();
  const id = JSON.parse(await c.call('build_identity', {}));
  console.log(`assets_digest=${JSON.stringify(id.assets_digest)} keys=${Object.keys(id).join(',')}`);
  await c.close();
}
else if (what === 'yaml') {
  const d = path.join(W, 'p');
  const s = store(d, [['deploy', 'how we deploy']]);
  fs.writeFileSync(path.join(s, 'facts', 'hand-edited.md'), fact('hand-edited', '2026'), 'utf8');
  fs.writeFileSync(path.join(s, 'facts', 'anchored.md'), fact('anchored', '&a anchored text'), 'utf8');
  const c = server({ cwd: d });
  await c.init();
  console.log('recall 2026 ->', (await c.call('memory_recall', { query: 'hand-edited' })).split(W).join('<tmp>'));
  console.log('save ->', (await c.call('memory_save', { type: 'project', name: 'another-one', description: 'another', body: 'b' })).split(W).join('<tmp>'));
  await c.close();
}
else if (what === 'wave') {
  const unit = (id, deps = []) => ({ id, title: id, brief_path: 'b.md', status: 'todo', role: 'implementer', depends_on: deps, verify: 'true' });
  const cp = path.join(W, 'cp.json');
  fs.writeFileSync(cp, JSON.stringify({ version: 1, job: { id: 'j', goal: 'g', done_definition: 'd', constraints: [] }, plan: { cursor: 'N1', units: [unit('N1'), unit('N2'), unit('N3', ['N1', 'N2'])] }, state: { repo: { branch: 'b', head_sha: 'h', dirty: false }, artifacts: [], external: [] }, history: [], retro: [], handoff: { next_action: 'n', open_questions: [], do_not: [] } }), 'utf8');
  const c = server({ args: ['--store', path.join(W, 'store')] });
  await c.init();
  const j = async (name, a) => { const t = JSON.parse(await c.call(name, { checkpoint: cp, ...a })); return t.result === 'brief' ? `brief ${t.unit.id}` : JSON.stringify(t); };
  const acc = { tokens: 1, duration_ms: 1 };
  console.log('plan          ', await j('shiftwork_plan', {}));
  console.log('clock_in()    ', await j('shiftwork_clock_in', {}));
  console.log('clock_in(N2)  ', await j('shiftwork_clock_in', { unit_id: 'N2' }));
  console.log('clock_in(N3)  ', await j('shiftwork_clock_in', { unit_id: 'N3' }));
  console.log('clock_out(N2) ', await j('shiftwork_clock_out', { unit_id: 'N2', status: 'done', handoff_patch: {}, history_entry: { unit: 'N2', outcome: 'x' }, accounting: acc }));
  console.log('clock_out(N3) ', await j('shiftwork_clock_out', { unit_id: 'N3', status: 'done', handoff_patch: {}, history_entry: { unit: 'N3', outcome: 'x' }, accounting: acc }));
  console.log('clock_out(N1) ', await j('shiftwork_clock_out', { unit_id: 'N1', status: 'done', handoff_patch: {}, history_entry: { unit: 'N1', outcome: 'x' }, accounting: acc }));
  console.log('reserved key  ', await j('shiftwork_clock_out', { unit_id: 'N3', status: 'done', handoff_patch: {}, history_entry: { unit: 'N3', outcome: 'x' }, accounting: { ...acc, event: 'brief' } }));
  await c.close();
  console.log('log lines:', fs.readFileSync(cp + '.log.jsonl', 'utf8').trim().split('\n').map((l) => JSON.parse(l)).map((e) => `${e.unit}:${e.event ?? e.status}${'briefed' in e ? '/briefed=' + e.briefed : ''}`).join(' '));
}
