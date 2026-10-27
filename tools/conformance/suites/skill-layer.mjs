/**
 * skill-layer — bantamkit's learned skills as the read-only `[skill]` recall layer (#206 Task 2).
 *
 * THE PROPERTY: over one fixture, the two runtimes bind the same layers in the same order
 * (`project`, `profile`, `skill`, `native`), offer the same skills, inject the same one header
 * line per matching skill, return the same body by name, name the same skipped skills with the
 * same sentences, write the same usage-ledger lines, and leave every skills directory
 * byte-identical: the layer is read-only.
 *
 * HOW. Each scenario is materialised twice (`py/`, `node/`) from one spec, the beds realpath'd,
 * each side's `HOME`/`USERPROFILE`/`BANTAMKIT_INDEX_DIR` inside its own bed and
 * `BANTAMKIT_MEMORY_DIR` unset, so neither side can reach a real store. The reference is
 * `ref/skilllayer_ref.py`; the Node side drives `dist/memory/component.js` in-process. Every
 * answer is compared after the bed path is replaced by `<bed>`.
 *
 * WHAT THE FIXTURE IS AIMED AT. A skill matched by its description, one matched ONLY by a
 * `bantamkit-keywords` term, one shadowed by a project fact of its name, one recorded promoted
 * in `skills-state.json`, one held by both roots (the user copy is skipped), a user-only one,
 * a host fact the skill shadows, every way a skill is refused (no `## Steps`, no frontmatter,
 * a directory that does not match its name, a generic name, bytes that are not UTF-8), a build
 * directory `skillfile` leaves while it works, and the scenario with no skills root at all
 * (no layer is bound, so a machine with no skill keeps the layers it had).
 * Nested `metadata` is NOT in it: that shape is ruled different in `skill-file` and both
 * runtimes refuse it there.
 *
 * THE LITERALS. A tag both runtimes change together (`[skills]`) leaves every differential
 * green, so the header line, the layer order and the promoted exclusion are also pinned per
 * side against literals.
 */
import { mkdirSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-layer';
export const summary = 'the [skill] recall layer: order, gate, shadow, promoted, invalid, read-only';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skilllayer_ref.py');
const TODAY = '2026-10-27';
const STEPS = '## Steps\n\n1. Read the failing line.\n2. Name the encoding.\n';

const skill = (name, description, { keywords = null, body = STEPS, front = null } = {}) =>
  front ??
  `---\nname: ${name}\ndescription: "${description}"\n` +
    (keywords === null ? '' : `metadata:\n  bantamkit-generated-by: bantamkit\n  bantamkit-keywords: "${keywords}"\n`) +
    `---\n\n${body}`;
const fact = (name, description, body) =>
  `---\nname: ${name}\ndescription: ${description}\ntype: project\ncreated: '2026-10-01'\n` +
  `last_recalled: null\nlinks: []\n---\n\n${body}\n`;
const hostFact = (name, description, body) =>
  `---\nname: ${name}\ndescription: ${description}\nmetadata:\n  type: reference\n---\n\n${body}\n`;

const PROJ = 'proj/.bantamkit/skills';
const USER = 'home/.bantamkit/skills';

/** The full fixture: `{relpath: string | Buffer}`. */
const FULL = {
  'proj/.bantamkit/memory/facts/deploy.md': fact('deploy', 'how we deploy', 'real deploy'),
  'proj/.bantamkit/memory/facts/kafka.md': fact('kafka', 'kafka brokers', 'brokers'),
  [`${PROJ}/fixing-windows-encoding/SKILL.md`]: skill(
    'fixing-windows-encoding',
    'Fixes UTF-8 decode failures. Use when a test fails on Windows only.',
    { keywords: 'cp1252, mojibake' },
  ),
  [`${PROJ}/deploy/SKILL.md`]: skill('deploy', 'deploy deploy deploy runbook', { body: '## Steps\n\n1. skill copy\n' }),
  [`${PROJ}/promoted-skill/SKILL.md`]: skill('promoted-skill', 'rotating signing certificates'),
  [`${PROJ}/no-steps/SKILL.md`]: skill('no-steps', 'decode failures without steps', { body: 'nothing\n' }),
  [`${PROJ}/bad-yaml/SKILL.md`]: 'no fences at all\n',
  [`${PROJ}/other/SKILL.md`]: skill('misnamed', 'decode failures misnamed'),
  [`${PROJ}/utils/SKILL.md`]: skill('utils', 'decode failures generic'),
  [`${PROJ}/latin/SKILL.md`]: Buffer.from('---\nname: latin\ndescription: d\xe9code\n---\n', 'latin1'),
  [`${PROJ}/fixing-windows-encoding.tmp-9-0/SKILL.md`]: skill('fixing-windows-encoding', 'half built decode'),
  [`${USER}/fixing-windows-encoding/SKILL.md`]: skill('fixing-windows-encoding', 'user copy of decode failures'),
  [`${USER}/tracing-flaky-tests/SKILL.md`]: skill('tracing-flaky-tests', 'Traces flaky tests to a shared fixture.'),
  'home/.bantamkit/skills-state.json':
    JSON.stringify({ version: 1, skills: { 'promoted-skill': { promoted: 'symlink' }, deploy: { promoted: null } } }, null, 2) + '\n',
  'host/kafka-lag.md': hostFact('kafka-lag', 'kafka consumer lag runbook', 'lag'),
  'host/tracing-flaky-tests.md': hostFact('tracing-flaky-tests', 'flaky tests flaky tests host copy', 'host copy'),
};

const recall = (q, { k = null, stamp = false } = {}) => ({ op: 'recall', q, k, stamp });

const SCENARIOS = [
  {
    label: 'full fixture',
    files: FULL,
    native: 'host',
    calls: [
      ['the layers, in order', { op: 'labels' }],
      ['a prompt matching a description', recall('windows decode failures')],
      ['a prompt matching only a keyword', recall('mojibake')],
      ['a fact of the same name shadows the skill', recall('deploy runbook')],
      ['a promoted skill is never injected', recall('rotating signing certificates')],
      ['a user-root skill, and the skill shadows the host copy', recall('flaky tests fixture')],
      ['a host fact still answers', recall('kafka consumer lag')],
      ['a prompt matching nothing', recall('kubernetes ingress controller')],
      ['the body by name (a body_read)', recall('fixing-windows-encoding', { stamp: true })],
      ['a promoted skill by name is not there', recall('promoted-skill', { stamp: true })],
      ['a stamped recall (a recall_hit)', recall('windows decode failures', { k: 5, stamp: true })],
    ],
  },
  {
    label: 'no skills root',
    files: { 'proj/.bantamkit/memory/facts/deploy.md': fact('deploy', 'how we deploy', 'real deploy') },
    native: null,
    calls: [
      ['the layers, in order', { op: 'labels' }],
      ['a recall', recall('deploy')],
    ],
  },
  {
    label: 'the user root only, project store is the profile store',
    files: {
      'home/.bantamkit/memory/facts/deploy.md': fact('deploy', 'how we deploy', 'real deploy'),
      [`${USER}/tracing-flaky-tests/SKILL.md`]: skill('tracing-flaky-tests', 'Traces flaky tests to a shared fixture.'),
    },
    start: 'elsewhere',
    native: null,
    calls: [
      ['the layers, in order', { op: 'labels' }],
      ['a user skill', recall('flaky tests')],
    ],
  },
];

function materialise(root, files, extraDirs) {
  for (const [rel, data] of Object.entries(files)) {
    const p = join(root, ...rel.split('/'));
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, data);
  }
  for (const d of extraDirs) mkdirSync(join(root, d), { recursive: true });
}

function tree(root) {
  const out = {};
  let entries;
  try {
    if (!statSync(root).isDirectory()) return out;
    entries = readdirSync(root, { recursive: true });
  } catch {
    return out;
  }
  for (const rel of entries.map(String).sort()) {
    const p = join(root, rel);
    if (statSync(p).isFile()) out[rel.split(sep).join('/')] = readFileSync(p).toString('base64');
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

function outcome(o) {
  return {
    reply: o.reply,
    headers: [...o.headers],
    skipped: o.skipped.map((s) => ({ ...s })),
    status: o.status,
    layers: o.layers,
    reached: o.reached,
    returned: o.returned,
    candidates: o.candidates,
    unreadable: o.unreadable,
  };
}

async function runNode(ctx, req, env) {
  const mod = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'component.js')).href);
  const store = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'memory', 'store.js')).href);
  const before = new Map(Object.keys(env).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    const options = { today: () => req.today, now: () => `${req.today}T00:00:00Z` };
    if (req.native !== null) options.native = req.native;
    const mem = mod.Memory.layered(req.start, options);
    const results = req.calls.map((call) => {
      if (call.op === 'labels') return mem.layerLabels();
      return outcome(mem.recallOutcome(call.q, call.k, store.RECALL_MIN_SCORE_RATIO, call.stamp));
    });
    const usage = join(env.HOME, '.bantamkit', 'usage');
    let ledgers = [];
    try {
      ledgers = readdirSync(usage)
        .sort()
        .map((n) => readFileSync(join(usage, n), 'utf8'));
    } catch {
      ledgers = [];
    }
    const trees = Object.fromEntries(req.watch.map((w) => [w, tree(w)]));
    return { results, trees, ledgers };
  } finally {
    for (const [k, v] of before) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

/** Every string in `value` with `bed` replaced by `<bed>`. */
function scrub(value, bed) {
  if (typeof value === 'string') return value.split(bed).join('<bed>');
  if (Array.isArray(value)) return value.map((v) => scrub(v, bed));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [scrub(k, bed), scrub(v, bed)]));
  }
  return value;
}

export async function run(ctx) {
  const cases = [];
  const scratch = realpathSync(ctx.scratch);
  const answers = [];
  for (const [n, sc] of SCENARIOS.entries()) {
    const sides = {};
    for (const side of ['py', 'node']) {
      const bed = join(scratch, `skill-layer-${n}`, side);
      materialise(bed, sc.files, ['home', 'index', sc.start ?? 'proj']);
      const env = {
        HOME: join(bed, 'home'),
        USERPROFILE: join(bed, 'home'),
        BANTAMKIT_INDEX_DIR: join(bed, 'index'),
        BANTAMKIT_MEMORY_DIR: undefined,
      };
      const req = {
        start: join(bed, sc.start ?? 'proj'),
        native: sc.native === null ? null : join(bed, sc.native),
        today: TODAY,
        watch: [join(bed, PROJ), join(bed, USER)],
        calls: sc.calls.map(([, c]) => c),
      };
      const before = Object.fromEntries(req.watch.map((w) => [w, tree(w)]));
      const got =
        side === 'py'
          ? ctx.runPython(REF, req, { ...env, BANTAMKIT_MEMORY_DIR: '' })
          : await runNode(ctx, req, env);
      sides[side] = { got: scrub(got, bed), before: scrub(before, bed) };
    }
    const { py, node } = sides;
    sc.calls.forEach(([l], i) => {
      cases.push({ name: `${sc.label}: ${l}`, kind: 'json', expected: py.got.results[i], actual: node.got.results[i] });
    });
    cases.push({ name: `${sc.label}: the skills directories after every call`, kind: 'json', expected: py.got.trees, actual: node.got.trees });
    cases.push({ name: `${sc.label}: the usage ledger lines`, kind: 'json', expected: py.got.ledgers, actual: node.got.ledgers });
    // read-only, per side: a symmetric write into a skills dir leaves the differential green
    for (const side of ['py', 'node']) {
      const s = sides[side];
      cases.push({
        name: `literal (${side === 'py' ? 'python' : 'node'}): ${sc.label}: recall wrote nothing into a skills directory`,
        kind: 'json',
        expected: s.before,
        actual: s.got.trees,
      });
    }
    answers.push(sides);
  }

  // per-side literals over the full fixture: what a symmetric regression moves on both sides
  const LIT = [
    [0, ['project', 'profile', 'skill', 'native'], (r) => r, 'the layer order'],
    [1, ['[skill] [fixing-windows-encoding] (skill) Fixes UTF-8 decode failures. Use when a test fails on Windows only.'],
      (r) => r.headers, 'the header line'],
    [2, ['[skill] [fixing-windows-encoding] (skill) Fixes UTF-8 decode failures. Use when a test fails on Windows only.'],
      (r) => r.headers, 'a keyword alone injects the skill'],
    [4, [], (r) => r.headers, 'a promoted skill injects nothing'],
    [5, ['[skill] [tracing-flaky-tests] (skill) Traces flaky tests to a shared fixture.'], (r) => r.headers,
      'the user-root skill, not the host copy'],
  ];
  for (const [i, want, pick, l] of LIT) {
    for (const side of ['py', 'node']) {
      cases.push({
        name: `literal (${side === 'py' ? 'python' : 'node'}): ${l}`,
        kind: 'json',
        expected: want,
        actual: pick(answers[0][side].got.results[i]),
      });
    }
  }
  for (const side of ['py', 'node']) {
    cases.push({
      name: `literal (${side === 'py' ? 'python' : 'node'}): no skills root binds no layer`,
      kind: 'json',
      expected: ['project', 'profile'],
      actual: answers[1][side].got.results[0],
    });
  }
  return { cases, notes: [] };
}

