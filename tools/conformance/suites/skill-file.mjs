/**
 * skill-file — the Agent Skills file (#206 Task 1), Python against Node.
 *
 * THE PROPERTY: the two runtimes read, judge, hash, render and write a skill directory the
 * same way. A `SKILL.md` and its `bantamkit-sha256` are shared on disk between the runtimes
 * (`~/.bantamkit/skills/`, `<repo>/.bantamkit/skills/`), so a hash one side stamps is a hash
 * the other side checks for "edited"; a validation sentence is what the user reads when a
 * draft is refused; and the directory writes are what decide whether a crash leaves half a
 * skill behind.
 *
 * HOW. One op list (see `ref/skillfile_ref.py` for the table) runs twice: by the reference in
 * its own bed and by `runNode` below against `dist/skillfile.js` in another. Each answer is
 * one case. Directory ops answer the whole bed (every path, every file's bytes), so a temp
 * dir left behind, a missing backup or a wrong byte all show as a difference.
 *
 * WHAT THE FIXTURES ARE AIMED AT. Every limit at the limit and one past it (64/65-char names,
 * 1024/1025-code-point descriptions in ASCII, Thai and astral text, 500/501-line bodies);
 * every name rule (doubled, leading, trailing hyphen, upper case, non-ASCII, generic words
 * and a name that only CONTAINS one); nested and non-string metadata; CRLF, a BOM and a
 * block-scalar description; every refusal sentence; the one ruled shape (RULED_TEXTS); names YAML would resolve to a bool, an
 * int or a date; a write that fails at each seam.
 *
 * THE LITERALS. A rule both runtimes lose together (the doubled-hyphen rule, say) leaves every
 * differential green, so the doubled-hyphen sentence, the 1025-character sentence and one
 * stamped hash are also pinned per side against a literal.
 */
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'skill-file';
export const summary = 'the Agent Skills file: validate, hash, render, stamp, atomic write, undo, state';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'skillfile_ref.py');

const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
const NOW = '2026-10-27T12:00:00.000Z';
const BODY =
  '## When to use\n\nWhen a test fails on Windows only.\n\n## Steps\n\n1. Read the failing line (J1-1).\n\n' +
  '## Pitfalls\n\nNone seen.\n\n## Example\n\n`pytest -q`';
const doc = (kw = {}) => ({
  name: 'fixing-windows-encoding',
  description: 'Fixes UTF-8 decode failures. Use when a test fails on Windows only.',
  metadata: { 'bantamkit-generated-by': 'bantamkit' },
  body: BODY,
  ...kw,
});
const lines = (n) => ['## Steps', '', '1. x', ...Array(n - 3).fill('y')].join('\n');

const NAMES = ['', 'a', 'x'.repeat(64), 'x'.repeat(65), 'a-b', 'a1-b2', 'a--b', '-a', 'a-', 'A', 'a_b', 'a b',
  'ไทย', 'naïve', 'helper', 'helpers', 'util', 'utils', 'using-utils', 'helper-x'];
const DESCRIPTIONS = ['', 'd'.repeat(1024), 'd'.repeat(1025), 'ก'.repeat(1024), 'ก'.repeat(1025), '😀'.repeat(1024),
  '😀'.repeat(1025)];
const BODIES = ['', lines(500), lines(501), '## Steps\n', '## Steps\n\n \t\n## Pitfalls\n\nx', '## Stepsx\n\n1. a',
  '# Steps\n\n1. a', '## Steps\n1. a', '## Steps  \n\n### Sub\n\n1. a', '## Steps\n\n- a\n# Next', 'x\n## Steps\n\n```\n## no\n```'];
const METADATA = [
  {},
  { 'bantamkit-a': '1', 'bantamkit-b': 1, 'bantamkit-c': { d: 'e' }, 'bantamkit-d': ['x'], 'bantamkit-e': null, 'bantamkit-f': true },
  { z: '1', 'bantamkit-ไทย': 2, Z: 3 },
];

const STAMPED = (() => {
  // the one render every hash/stamp/edit case starts from
  const d = doc({ metadata: { 'bantamkit-generated-by': 'bantamkit', 'bantamkit-evidence': 'J1-1,a1b2c3d' } });
  return d;
})();

const SKILL_TEXTS = [
  '---\nname: a-b\ndescription: d\n---\n\n## Steps\n\n1. x\n',
  '---\r\nname: a-b\r\ndescription: d\r\nmetadata:\r\n  bantamkit-x: 3\r\n  bantamkit-y: "ok"\r\n---\r\n\r\n## Steps\r\n\r\n1. x\r\n',
  '\ufeff---\nname: a-b\ndescription: "BOM first"\n---\n\n## Steps\n\n1. x\n',
  '---\nname: a-b\ndescription: >\n  folded\n  text\nmetadata:\n  k: [a, 2]\n  j: "x"\n  n: 12\n  b: yes\n  d: 2026-10-27\n  e:\n---\n\n## Steps\n\n1. x\n',
  '---\nname: a-b\ndescription: |\n  kept\n  lines\nmetadata:\n  bantamkit-evidence: "\\u0e44\\ud800x"\n---\n\nbody\n',
  '---\nname: helper\ndescription: d\n---\n',
  'no fences',
  'x\n---\nname: a\n---\n',
  '---\n- a\n---\n',
  '---\nname: [a\n---\n',
  '---\n---\n',
  '---\ndescription: d\n---\n',
  '---\nname: 12\n---\n',
  '---\nname: a\ndescription: [x]\n---\n',
  '---\nname: a\nmetadata: x\n---\n',
  '---\nname: a\nmetadata: [x]\n---\n',
];

/**
 * THE ONE RULING (docs/porting.md, row `skillfile`): a `metadata:` value nested deeper than one
 * level of scalars. PyYAML reads it and `validate` names the key; the port's frontmatter reader
 * refuses every shape it does not implement (#120's standing ruling, the same divergence as
 * `hooks/native-mirror-ruled`), so `parse_skill` refuses the file. Both sides treat it as NOT A
 * VALID SKILL; the refusal-bit twin compares exactly that, and per-side literals pin each answer.
 */
const RULED_TEXTS = [
  ['a mapping under a metadata key', '---\nname: a-b\ndescription: d\nmetadata:\n  bantamkit-x:\n    deep: v\n---\n\n## Steps\n\n1. x\n'],
  ['a block sequence under a metadata key', '---\nname: a-b\ndescription: d\nmetadata:\n  bantamkit-x:\n  - a\n---\n\n## Steps\n\n1. x\n'],
];

/**
 * THE SAME VERDICT ON WHAT THE PORT'S READER REFUSES (job73 C8). Node's frontmatter reader
 * (#120) refuses a flow mapping, an anchor, an alias, a tag and a directive wherever it
 * stands; PyYAML reads them. Unruled: `parse_skill` refuses each with the port's sentence, so
 * a draft holding `metadata: {}` fails the gate on both sides (before C8 it passed in Python
 * and failed in Node). A `{` inside a quoted or plain scalar is text on both sides.
 */
const FLOW_TEXTS = [
  ['an empty flow mapping as metadata', '---\nname: a-b\ndescription: d\nmetadata: {}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping of a non-string', '---\nname: a-b\ndescription: d\nmetadata: {k: 1}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping of a bantamkit string', '---\nname: a-b\ndescription: d\nmetadata: {bantamkit-k: "v"}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping over two lines', '---\nname: a-b\ndescription: d\nmetadata: {\n  k: v}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping under a metadata key', '---\nname: a-b\ndescription: d\nmetadata:\n  k: {}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping with a comment after it', '---\nname: a-b\ndescription: d\nmetadata:\n  k: {a: 1}  # c\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping inside a flow sequence', '---\nname: a-b\ndescription: d\nmetadata:\n  k: [a, {b: c}]\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping as the description', '---\nname: a-b\ndescription: {x: 1}\n---\n\n## Steps\n\n1. x\n'],
  ['a flow mapping as the name', '---\nname: {a: b}\n---\n'],
  ['an anchor', '---\nname: a-b\ndescription: &a d\n---\n\n## Steps\n\n1. x\n'],
  ['a tag', '---\nname: a-b\ndescription: !!str d\n---\n\n## Steps\n\n1. x\n'],
  ['an anchor and an alias', '---\nname: &n a-b\ndescription: *n\n---\n\n## Steps\n\n1. x\n'],
  ['braces inside scalars are text', '---\nname: a-b\ndescription: "{x: 1}"\nmetadata:\n  k: a {b} c\n  j: \'{}\'\n---\n\n## Steps\n\n1. x\n'],
  ['an ampersand and a bang inside a plain scalar', '---\nname: a-b\ndescription: fish & chips!\n---\n\n## Steps\n\n1. x\n'],
];

const HASH_TEXTS = [
  '---\nname: a\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\nbody\n',
  '---\nname: a\nmetadata:\n  bantamkit-sha256: "zzz"\n---\n\nbody\n',
  '---\r\nname: a\r\nmetadata:\r\n  bantamkit-sha256: "abc"\r\n---\r\n\r\nbody\r\n',
  '---\nname: a\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\nbantamkit-sha256: x\n',
  '---\nname: a\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\nbantamkit-sha256: y\n',
  '---\nname: a\nbantamkit-sha256: top\n\tbantamkit-sha256: tab\n---\n',
  '\ufeff---\nname: a\nmetadata:\n  bantamkit-sha256: "q"\n---\n',
  'no frontmatter bantamkit-sha256: x\n',
  '---\nname: ไทย\u2028x\nmetadata:\n  bantamkit-sha256: "abc"\n---\n\n😀\n',
];

const RENDER_DOCS = [
  doc(),
  doc({ description: 'Quotes " and \\ and tab\t and ไทย and \u2028\u2029\x85\x7f\x01\ufeff and 😀. Use when "x".' }),
  doc({ metadata: { 'bantamkit-z': '1', 'bantamkit-a': 'ก\n2', 'bantamkit-m': '' } }),
  doc({ metadata: {} }),
  doc({ body: '' }),
  ...['yes', 'no', 'on', 'off', 'true', 'false', 'null', '123', '0x1a', '2026-10-27', '1-2', 'A', 'a b', 'x: y', 'ไทย'].map((n) =>
    doc({ name: n }),
  ),
  doc({ metadata: { 'bantamkit-n': 1 } }),
  doc({ metadata: { 'bad key': 'x' } }),
];

const FILES = {
  'SKILL.md': b64('---\nname: a-b\n---\n'),
  'references/evidence.md': b64('ev ไทย\n'),
  'references/history/v1.md': b64('old\n'),
};

function opList() {
  const ops = [];
  const label = [];
  const add = (l, op) => {
    label.push(l);
    ops.push(op);
  };
  for (const n of NAMES) add(`validate name ${JSON.stringify(n)}`, { op: 'validate', doc: doc({ name: n }) });
  add('validate name vs directory', { op: 'validate', doc: doc({ name: 'a-b' }), dirname: 'a-c' });
  add('validate name vs Thai directory', { op: 'validate', doc: doc({ name: 'a-b' }), dirname: 'ไทย\n' });
  for (const d of DESCRIPTIONS) add(`validate description of ${[...d].length} code points (${d.slice(0, 1) || 'empty'})`, { op: 'validate', doc: doc({ description: d }) });
  BODIES.forEach((b, i) => add(`validate body #${i}`, { op: 'validate', doc: doc({ body: b }) }));
  METADATA.forEach((m, i) => add(`validate metadata #${i}`, { op: 'validate', doc: doc({ metadata: m }) }));
  add('validate every rule at once, in order', {
    op: 'validate',
    doc: doc({ name: 'utils', description: 'd'.repeat(1025), metadata: { 'bantamkit-x': 3 }, body: lines(501).replace('## Steps', '## Nope') }),
    dirname: 'other',
  });
  SKILL_TEXTS.forEach((t, i) => {
    add(`parse text #${i}`, { op: 'parse', text: t });
    add(`validate text #${i} (dirname a-b)`, { op: 'validate_text', text: t, dirname: 'a-b' });
    add(`edited text #${i}`, { op: 'edited', text: t });
  });
  FLOW_TEXTS.forEach(([l, t]) => {
    add(`port-refused shape: parse ${l}`, { op: 'parse', text: t });
    add(`port-refused shape: validate ${l}`, { op: 'validate_text', text: t, dirname: 'a-b' });
    add(`port-refused shape: edited ${l}`, { op: 'edited', text: t });
  });
  HASH_TEXTS.forEach((t, i) => add(`hash text #${i}`, { op: 'hash', text: t }));
  RENDER_DOCS.forEach((d, i) => {
    add(`render doc #${i}`, { op: 'render', doc: d });
    add(`roundtrip doc #${i}`, { op: 'roundtrip', doc: d });
  });
  return { ops, label };
}

/** Ops whose input is a previous answer: stamp chains, run after the first batch. */
function stampOps(rendered) {
  return [
    ['stamp a rendered doc', { op: 'stamp', text: rendered, updates: { 'bantamkit-version': '1' } }],
    ['stamp refuses a foreign key', { op: 'stamp', text: rendered, updates: { version: '1' } }],
    ['stamp refuses a non-string value', { op: 'stamp', text: rendered, updates: { 'bantamkit-v': 1 } }],
    ['stamp a CRLF text', { op: 'stamp', text: rendered.split('\n').join('\r\n'), updates: {} }],
    ['stamp an unreadable text', { op: 'stamp', text: 'nope', updates: {} }],
  ];
}

const DIR_OPS = [
  ['write a new skill', { op: 'write', target: 'skills/a-b', files: FILES }],
  ['write refuses an existing target', { op: 'write', target: 'skills/a-b', files: FILES }],
  ['write refuses ../', { op: 'write', target: 'skills/x', files: { '../x': b64('x') } }],
  ['write refuses a backslash', { op: 'write', target: 'skills/x', files: { 'a\\b': b64('x') } }],
  ['write refuses an empty segment', { op: 'write', target: 'skills/x', files: { 'a//b': b64('x') } }],
  ['write fails at write', { op: 'write', target: 'skills/w', files: FILES, fail_at: 'write' }],
  ['write fails at fsync', { op: 'write', target: 'skills/f', files: FILES, fail_at: 'fsync' }],
  ['write fails at rename', { op: 'write', target: 'skills/r', files: FILES, fail_at: 'rename' }],
  ['history v1 is refused (it was written)', { op: 'history', target: 'skills/a-b', version: 1 }],
  ['history v2', { op: 'history', target: 'skills/a-b', version: 2 }],
  ['history v0 is refused', { op: 'history', target: 'skills/a-b', version: 0 }],
  ['replace backs up and swaps', { op: 'replace', target: 'skills/a-b', files: { 'SKILL.md': b64('new\n') }, now: NOW }],
  ['replace again in the same millisecond', { op: 'replace', target: 'skills/a-b', files: { 'SKILL.md': b64('newer\n') }, now: NOW }],
  ['replace fails swapping in; old back, backup dropped', { op: 'replace', target: 'skills/a-b', files: { 'SKILL.md': b64('x') }, now: '2026-10-28T00:00:00Z', fail_at: 'rename2' }],
  ['replace refuses a missing skill', { op: 'replace', target: 'skills/none', files: FILES, now: NOW }],
  ['undo the second replace', { op: 'undo', name: 'a-b', target: 'skills/a-b' }],
  ['undo the first replace', { op: 'undo', name: 'a-b', target: 'skills/a-b' }],
  ['undo with nothing left', { op: 'undo', name: 'a-b', target: 'skills/a-b' }],
  ['absent backup before an install', { op: 'absent', name: 'c-d', now: '2026-10-27T13:00:00Z' }],
  ['install c-d', { op: 'write', target: 'skills/c-d', files: { 'SKILL.md': b64('c\n') } }],
  ['undo the install removes c-d', { op: 'undo', name: 'c-d', target: 'skills/c-d' }],
  ['backup stamp of a bad now', { op: 'stamp_dir', now: 'yesterday' }],
  ['backup stamp without milliseconds', { op: 'stamp_dir', now: '2026-01-02T03:04:05Z' }],
  ['state write', { op: 'state_write', state: { version: 9, skills: { b: { n: 1, s: 'ไทย' }, a: {}, '😀': [1, 'x'] }, extra: true } }],
  ['state read back', { op: 'state_read' }],
  ['state read refuses bad JSON', { op: 'state_read', raw: b64('{bad') }],
  ['state read refuses version 2', { op: 'state_read', raw: b64('{"version": 2, "skills": {}}') }],
  ['state read refuses version 1.0', { op: 'state_read', raw: b64('{"version": 1.0, "skills": {}}') }],
  ['state read refuses version true', { op: 'state_read', raw: b64('{"version": true, "skills": {}}') }],
  ['state read refuses skills as a list', { op: 'state_read', raw: b64('{"version": 1, "skills": []}') }],
  ['state read refuses a BOM', { op: 'state_read', raw: Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('{"version": 1, "skills": {}}')]).toString('base64') }],
];

// ------------------------------------------------------------------------- Node side

function plain(v, PyScalar) {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.map((x) => plain(x, PyScalar));
  if (v instanceof PyScalar) return { py: v.pyType.split('.').pop() }; // `type(v).__name__`: `date`, not `datetime.date`
  if (v === null) return { py: 'NoneType' };
  if (typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, plain(x, PyScalar)]));
  return { py: typeof v === 'number' ? (Number.isInteger(v) ? 'int' : 'float') : typeof v === 'boolean' ? 'bool' : typeof v };
}

function tree(bed) {
  const out = {};
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      const r = relative(bed, p).split(sep).join('/');
      if (e.isDirectory()) {
        out[`${r}/`] = null;
        walk(p);
      } else if (e.isFile()) out[r] = readFileSync(p).toString('base64');
    }
  };
  walk(bed);
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

async function runNode(ctx, bed, ops) {
  const dist = (m) => pathToFileURL(join(ctx.runtimeTs, 'dist', m)).href;
  const sf = await import(dist('skillfile.js'));
  const { PyScalar } = await import(dist('memory/pyyaml.js'));
  const docOut = (d) => ({ name: d.name, description: d.description, metadata: plain(d.metadata, PyScalar), body: d.body });
  const docIn = (o) => ({ name: o.name, description: o.description, metadata: { ...(o.metadata ?? {}) }, body: o.body ?? '' });
  const filesIn = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Buffer.from(v, 'base64')]));
  const guarded = (fn) => {
    try {
      return fn() ?? {};
    } catch (e) {
      if (e instanceof sf.SkillFileError) return { error: e.message.split(bed).join('<bed>') };
      return { error: 'raised' };
    }
  };
  const withSeams = (failAt, fn) => {
    const saved = { ...sf.seams };
    let calls = 0;
    if (failAt === 'write') {
      sf.seams.write = (f, d) => {
        calls += 1;
        saved.write(f, d);
        if (calls === 2) throw new Error('injected');
      };
    } else if (failAt === 'fsync') {
      sf.seams.fsync = () => {
        throw new Error('injected');
      };
    } else if (failAt === 'rename' || failAt === 'rename2') {
      sf.seams.rename = (s, d) => {
        calls += 1;
        if (failAt === 'rename' || calls === 2) throw new Error('injected');
        saved.rename(s, d);
      };
    }
    try {
      return fn();
    } finally {
      Object.assign(sf.seams, saved);
    }
  };
  const relOut = (p) => relative(bed, p).split(sep).join('/');
  const home = join(bed, 'home');
  const backups = join(bed, 'backups');
  return ops.map((op) => {
    switch (op.op) {
      case 'parse':
        return guarded(() => ({ doc: docOut(sf.parseSkill(op.text)) }));
      case 'validate':
        return sf.validate(docIn(op.doc), op.dirname ?? null);
      case 'validate_text':
        return guarded(() => ({ found: sf.validate(sf.parseSkill(op.text), op.dirname ?? null) }));
      case 'hash':
        return sf.canonicalHash(op.text);
      case 'edited':
        return sf.isEdited(op.text);
      case 'render':
        return guarded(() => ({ text: sf.render(docIn(op.doc)) }));
      case 'roundtrip':
        return guarded(() => ({ doc: docOut(sf.parseSkill(sf.render(docIn(op.doc)))) }));
      case 'stamp':
        return guarded(() => ({ text: sf.stamp(op.text, op.updates) }));
      case 'stamp_dir':
        return guarded(() => ({ stamp: sf.backupStamp(op.now) }));
      case 'write':
      case 'replace':
      case 'absent':
      case 'undo':
      case 'history': {
        const out = withSeams(op.fail_at, () =>
          guarded(() => {
            if (op.op === 'write') return sf.writeDirAtomic(join(bed, op.target), filesIn(op.files));
            if (op.op === 'replace') return { backup: relOut(sf.replaceDirAtomic(join(bed, op.target), filesIn(op.files), backups, op.now)) };
            if (op.op === 'absent') return { backup: relOut(sf.backupAbsent(backups, op.name, op.now)) };
            if (op.op === 'undo') return { said: sf.undo(backups, op.name, join(bed, op.target)) };
            return sf.historyAdd(join(bed, op.target), op.version);
          }),
        );
        return { ...out, tree: tree(bed) };
      }
      case 'state_write':
        sf.writeState(home, op.state);
        return { tree: tree(bed) };
      case 'state_read':
        if (op.raw !== undefined) {
          mkdirSync(dirname(sf.statePath(home)), { recursive: true });
          writeFileSync(sf.statePath(home), Buffer.from(op.raw, 'base64'));
        }
        return guarded(() => ({ state: sf.readState(home) }));
      default:
        throw new Error(`skill-file: unknown op ${op.op}`);
    }
  });
}

// ---------------------------------------------------------------------------- cases

export async function run(ctx) {
  const cases = [];
  const bed = (side) => {
    const d = mkdtempSync(join(ctx.scratch, `skill-file-${side}-`));
    return d;
  };

  // 1. the pure ops
  const { ops, label } = opList();
  const py1 = ctx.runPython(REF, { bed: bed('py-pure'), ops }).results;
  const nd1 = await runNode(ctx, bed('node-pure'), ops);
  ops.forEach((op, i) => {
    const kind = op.op === 'render' && py1[i].text !== undefined ? 'string' : 'json';
    cases.push({
      name: label[i],
      kind,
      expected: kind === 'string' ? py1[i].text : py1[i],
      actual: kind === 'string' ? (nd1[i].text ?? JSON.stringify(nd1[i])) : nd1[i],
    });
  });

  // 2. stamp chains off Python's own render of one doc (each side stamps the SAME text)
  const rendered = ctx.runPython(REF, { bed: bed('py-r'), ops: [{ op: 'render', doc: STAMPED }] }).results[0].text;
  const s = stampOps(rendered);
  const py2 = ctx.runPython(REF, { bed: bed('py-stamp'), ops: s.map(([, o]) => o) }).results;
  const nd2 = await runNode(ctx, bed('node-stamp'), s.map(([, o]) => o));
  s.forEach(([l], i) => cases.push({ name: l, kind: 'json', expected: py2[i], actual: nd2[i] }));
  // the stamped text read back: hash, edited, a one-byte edit, a restamp is a no-op
  const stamped = py2[0].text;
  const tail = [
    ['hash of the stamped text', { op: 'hash', text: stamped }],
    ['the stamped text is not edited', { op: 'edited', text: stamped }],
    ['a one-byte description edit is edited', { op: 'edited', text: stamped.replace('Fixes', 'fixes') }],
    ['a restamp with no change is the same text', { op: 'stamp', text: stamped, updates: {} }],
    ['the stamped text validates clean', { op: 'validate_text', text: stamped, dirname: 'fixing-windows-encoding' }],
  ];
  const py3 = ctx.runPython(REF, { bed: bed('py-tail'), ops: tail.map(([, o]) => o) }).results;
  const nd3 = await runNode(ctx, bed('node-tail'), tail.map(([, o]) => o));
  tail.forEach(([l], i) => cases.push({ name: l, kind: 'json', expected: py3[i], actual: nd3[i] }));

  // 3. the directory ops, one bed per side, in sequence
  const py4 = ctx.runPython(REF, { bed: bed('py-dir'), ops: DIR_OPS.map(([, o]) => o) }).results;
  const nd4 = await runNode(ctx, bed('node-dir'), DIR_OPS.map(([, o]) => o));
  DIR_OPS.forEach(([l], i) => cases.push({ name: l, kind: 'json', expected: py4[i], actual: nd4[i] }));

  // 4. per-side literals: the answers a symmetric regression would move on both sides at once
  const LIT = [
    ['doubled hyphen', { op: 'validate', doc: doc({ name: 'a--b' }) },
      ["name 'a--b' must be 1-64 characters of a-z, 0-9 and single inner hyphens"]],
    ['65-char name', { op: 'validate', doc: doc({ name: 'x'.repeat(65) }) },
      [`name '${'x'.repeat(65)}' must be 1-64 characters of a-z, 0-9 and single inner hyphens`]],
    ['1025 Thai code points', { op: 'validate', doc: doc({ description: 'ก'.repeat(1025) }) },
      ['description is 1025 characters; at most 1024']],
    ['1024 Thai code points pass', { op: 'validate', doc: doc({ description: 'ก'.repeat(1024) }) }, []],
    ['metadata: {} is refused', { op: 'validate_text', text: FLOW_TEXTS[0][1], dirname: 'a-b' },
      { error: 'SKILL.md frontmatter is not a readable mapping' }],
    ['hash of a blanked line', { op: 'hash', text: HASH_TEXTS[0] },
      // sha256 of the same text with `""` in place of `"abc"`, computed by node:crypto here
      null],
  ];
  const { createHash } = await import('node:crypto');
  LIT[5][2] = createHash('sha256').update(HASH_TEXTS[0].replace('"abc"', '""')).digest('hex');
  const py5 = ctx.runPython(REF, { bed: bed('py-lit'), ops: LIT.map(([, o]) => o) }).results;
  const nd5 = await runNode(ctx, bed('node-lit'), LIT.map(([, o]) => o));
  LIT.forEach(([l, , want], i) => {
    cases.push({ name: `literal (python): ${l}`, kind: 'json', expected: want, actual: py5[i] });
    cases.push({ name: `literal (node): ${l}`, kind: 'json', expected: want, actual: nd5[i] });
  });
  // the temp-dir property, per side: a failed write leaves the bed as it was
  const failIdx = DIR_OPS.findIndex(([l]) => l === 'write fails at rename');
  const before = DIR_OPS.findIndex(([l]) => l === 'write fails at fsync');
  cases.push({ name: 'literal (python): a failed rename leaves no temp', kind: 'json', expected: py4[before].tree, actual: py4[failIdx].tree });
  cases.push({ name: 'literal (node): a failed rename leaves no temp', kind: 'json', expected: nd4[before].tree, actual: nd4[failIdx].tree });

  // 5. the ruling, its refusal-bit twin and the per-side literals
  const rops = RULED_TEXTS.map(([, t]) => ({ op: 'validate_text', text: t, dirname: 'a-b' }));
  const py6 = ctx.runPython(REF, { bed: bed('py-ruled'), ops: rops }).results;
  const nd6 = await runNode(ctx, bed('node-ruled'), rops);
  const valid = (r) => r.error === undefined && r.found.length === 0;
  RULED_TEXTS.forEach(([l], i) => {
    cases.push({
      name: `ruled: ${l}`,
      kind: 'json',
      expected: py6[i],
      actual: nd6[i],
      ruling:
        'RULED DIFFERENT (docs/porting.md, row `skillfile`): PyYAML reads a metadata value nested ' +
        'below one level and validate names it (`metadata bantamkit-x must be a string`); the ' +
        "port's frontmatter reader refuses every shape it does not implement (#120), so parse " +
        'refuses the file (`SKILL.md frontmatter is not a readable mapping`). Both refuse the skill.',
    });
    cases.push({ name: `ruled twin: ${l} is not a valid skill on either side`, kind: 'json', expected: valid(py6[i]), actual: valid(nd6[i]) });
    cases.push({ name: `literal (python): ${l}`, kind: 'json', expected: { found: ['metadata bantamkit-x must be a string'] }, actual: py6[i] });
    cases.push({ name: `literal (node): ${l}`, kind: 'json', expected: { error: 'SKILL.md frontmatter is not a readable mapping' }, actual: nd6[i] });
  });

  return { cases, notes: [] };
}
