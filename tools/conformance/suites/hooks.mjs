/**
 * hooks — `--hook`, `--install-hooks`, and the export into the host's own auto-memory, as
 * two PROCESSES driven over ONE bed.
 *
 * WHY THIS SUITE EXISTS. job62 put a seven-event hook adapter, a host-settings installer and
 * an auto-memory exporter into both runtimes across six units, and until this file nothing in
 * `node tools/conformance/run.mjs --all` compared any of it. The repository's own rule is that
 * a feature is not ported because someone wrote it twice — it is ported when the harness
 * compares the two answers and they match. Six units' worth of claimed parity was a claim
 * nobody could rerun.
 *
 * WHAT IS COMPARED, AND WHY IT IS NOT STDOUT FOR THE EXPORT. The exporter's effect on the
 * injected SessionStart block is an ABSENCE: when it finds the host's directory it exports
 * into it and does NOT inject bantamkit's own project index, so stdout shows the same thing
 * whether the export wrote four files or none. The comparable surfaces are the SessionStart
 * LOG RECORD (ten `native*` fields) and the bytes left in the directory. Both are compared
 * here; stdout is compared too, as a necessary-but-not-sufficient companion, and it is
 * labelled as such rather than left to look like the gate.
 *
 * ONE BED, TWO RUNS, IN TURN. Every scenario builds its bed at ONE absolute path, runs the
 * reference, restores the bed from a pristine copy, and runs the port. Nothing compared below
 * can therefore be a path difference, and the paths that appear inside the compared bytes —
 * the native directory, the store root, the checkpoint filename — are compared WITH the path
 * in them rather than relativised into agreement. Only `HOME` is per side, because the two
 * hook logs cannot be one file; nothing compared here names `HOME` except `--install-hooks`,
 * where it is masked.
 *
 * EVERY PROBE THAT WRITES A HOME ASSERTS THE REDIRECT TOOK BEFORE IT READS A BYTE. `runHook`
 * refuses to return until `<home>/.bantamkit/hooks/hook-log.jsonl` exists under the throwaway
 * home it was given. Both `HOME` and `USERPROFILE` are set, always, on both sides.
 *
 * WHAT IS RULED AND WHAT IS NOT. Four differences are ruled here, and every one of them
 * carries the companion the rule demands:
 *
 *   - `nativeError`'s OS sentence — a REFUSAL, so the ruling is accompanied by a non-ruled
 *     case over the refusal BIT and by per-side literals, because a ruling only ever proves
 *     the two sides still DIFFER and never that either still refuses.
 *   - `--install-hooks`' recorded command — a spelling, so no refusal companion; the rest of
 *     the written document is compared unruled with the one command masked.
 *   - the 600/400 cut on the compact child's output (`docs/porting.md`, job62 J62-9 row 7).
 *   - the `.shiftwork` scan's filename tie-break (row 8).
 *
 * THE LAST TWO ARE NOT DELIBERATE, AND THE RULINGS SAY SO. They are latent parity bugs found
 * by J62-3B, written down as documentation, and MEASURED here for the first time. A ruling is
 * how this harness pins a difference that exists; it is not an endorsement. Both rulings name
 * the repair and the unit that owns it, and both carry per-side literals so that a repair
 * landing on ONE side reddens the ruling (stale) while a repair landing on BOTH reddens the
 * literals — which is the pair of failures that tells a reader what happened.
 */
import { spawnSync } from 'node:child_process';
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'hooks';
export const summary = 'the hook adapter, the hook installer and the native export, as processes over one bed';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(here));
/** The same process runner `cli` uses: argv, env, cwd, stdin in; the two streams and the exit out. */
const CLI_REF = join(here, 'ref', 'cli_ref.py');
const CLI = join(repoRoot, 'runtime-ts', 'dist', 'cli.js');

/**
 * Removed from BOTH children, always.
 *
 * `BANTAMKIT_MEMORY_DIR` and `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` are the two seams that
 * decide which store a hook binds and which directory the exporter resolves; an operator with
 * either one set would otherwise be an input to a conformance result. `TOOL_METRICS_DIR` and
 * `BANTAMKIT_DREAM_TIMEOUT_MS` are the arms' other two seams. `BANTAMKIT_ASSETS`, `COLUMNS`
 * and `LINES` are scrubbed for the reasons `cli.mjs` scrubs them.
 */
const SCRUBBED = [
  'BANTAMKIT_MEMORY_DIR',
  'CLAUDE_COWORK_MEMORY_PATH_OVERRIDE',
  'TOOL_METRICS_DIR',
  'BANTAMKIT_DREAM_TIMEOUT_MS',
  'BANTAMKIT_ASSETS',
  'COLUMNS',
  'LINES',
];

const dec = (buf) => new TextDecoder('utf-8', { fatal: false }).decode(buf);
const unb64 = (s) => Buffer.from(s ?? '', 'base64');
const writeFile = (path, text) => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
};
/** Code points above the BMP: the characters `slice()` counts twice and `[:n]` counts once. */
const astralCount = (s) => [...s].filter((c) => c.codePointAt(0) > 0xffff).length;
/**
 * How many CODE POINTS a string holds — `[...s].length`, never `s.length`.
 *
 * MEASURED, and it cost this file a red run before it was written down: `String.length` is a
 * count of UTF-16 code units, so a draft of the row-7 literals below "measured" the
 * reference's 400-code-point cut as 408 and concluded the reference was wrong. Every length
 * this suite compares is a count of the thing PYTHON counts, because that is the unit the
 * divergence is about.
 */
const codePoints = (s) => [...s].length;

// ------------------------------------------------------------------------------- the runs

function runNode(_ctx, { argv, cwd, home, env = {}, stdin = '' }) {
  const childEnv = { ...process.env };
  for (const key of SCRUBBED) delete childEnv[key];
  childEnv['HOME'] = home;
  childEnv['USERPROFILE'] = home;
  for (const [k, v] of Object.entries(env)) {
    if (v === null) delete childEnv[k];
    else childEnv[k] = String(v);
  }
  const r = spawnSync(process.execPath, [CLI, ...argv], {
    input: stdin,
    cwd,
    env: childEnv,
    timeout: 120_000,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.error && r.error.code !== 'ETIMEDOUT') throw r.error;
  return { stdout: r.stdout ?? Buffer.alloc(0), stderr: r.stderr ?? Buffer.alloc(0), exit: r.status };
}

function runPy(ctx, { argv, cwd, home, env = {}, stdin = '' }) {
  const overrides = { HOME: home, USERPROFILE: home, ...env };
  for (const key of SCRUBBED) if (!(key in overrides)) overrides[key] = null;
  const answer = ctx.runPython(CLI_REF, {
    argv,
    cwd,
    env: overrides,
    timeout: 120,
    stdin: Buffer.from(stdin, 'utf8').toString('base64'),
  });
  if (answer.error) throw new Error(`cli_ref.py: ${answer.error}`);
  return { stdout: unb64(answer.stdout), stderr: unb64(answer.stderr), exit: answer.exit };
}

const HOOK_LOG = (home) => join(home, '.bantamkit', 'hooks', 'hook-log.jsonl');

/**
 * One hook run, with the home assertion fired before a single byte it wrote is read.
 *
 * THE ASSERTION IS NOT DECORATION. A hook whose home resolution regressed would write into
 * the OPERATOR's `~/.bantamkit` and this suite would then compare two empty logs and call
 * them equal — and an earlier unit in this job did exactly that to a real
 * `~/.claude/settings.json`. The adapter logs on every event without exception, so "no log
 * under the throwaway home" means "the redirect did not take", and it stops the suite.
 */
function runHook(ctx, side, { payload, cwd, home, env = {} }) {
  const run = side === 'py' ? runPy : runNode;
  const r = run(ctx, { argv: ['--hook'], cwd, home, env, stdin: JSON.stringify(payload) });
  const log = HOOK_LOG(home);
  if (!existsSync(log)) {
    throw new Error(
      `hooks: the ${side} adapter did not follow HOME=${home}: no log at ${log}.\n` +
        `  exit ${r.exit}\n  stderr: ${dec(r.stderr).slice(0, 400)}\n` +
        '  NOTHING below may be read until this holds — an unredirected run writes the ' +
        "operator's own home and then compares two empty logs.",
    );
  }
  const records = readFileSync(log, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
  return { ...r, records, last: records[records.length - 1] };
}

/** The bed, pristine, restored before the second runtime is let near it. */
function bed(root) {
  const pristine = `${root}.pristine`;
  return {
    root,
    snapshot() {
      rmSync(pristine, { recursive: true, force: true });
      cpSync(root, pristine, { recursive: true });
    },
    restore() {
      rmSync(root, { recursive: true, force: true });
      cpSync(pristine, root, { recursive: true });
    },
  };
}

/** Compare each side to a typed constant — the only shape a symmetric regression reddens. */
function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — the reference`, kind, expected, actual: pySide },
    { name: `${label} — the port`, kind, expected, actual: nodeSide },
  ];
}

// -------------------------------------------------------------------------------- the beds

/**
 * A project store written by the reference's own `MemoryStore`, so the bed both runtimes read
 * is one the product made rather than one this file guessed the shape of.
 */
function seedStore(ctx, storeRoot, facts) {
  const r = spawnSync(
    ctx.python,
    [
      '-c',
      'import json,sys;sys.path.insert(0,sys.argv[1]);from bantamkit.memory.component import Memory;' +
        'm=Memory(store=sys.argv[2]);\n' +
        'for f in json.loads(sys.argv[3]):\n' +
        '    out=m.save(f["type"],f["name"],f["description"],f.get("body","body"))\n' +
        '    assert isinstance(out,str) and out.startswith("saved"), (f["name"],out)\n',
      join(repoRoot, 'runtime-py', 'src'),
      storeRoot,
      JSON.stringify(facts),
    ],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) throw new Error(`hooks: could not seed ${storeRoot}\n${r.stderr}`);
}

/** Every file under `dir`, path -> content, so "what A wrote" is compared byte for byte. */
function treeOf(dir) {
  const out = {};
  const walk = (d, prefix) => {
    for (const entry of readdirSync(d, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(join(d, entry.name), rel);
      else out[rel] = entry.isFile() ? readFileSync(join(d, entry.name), 'utf8') : `<not a regular file>`;
    }
  };
  walk(dir, '');
  return out;
}

const NATIVE_FIELDS = (rec) => Object.fromEntries(Object.entries(rec).filter(([k]) => k.startsWith('native')));

// ------------------------------------------------------------------------------------ run

export async function run(ctx) {
  const cases = [];
  const notes = [];
  const root = join(ctx.scratch, 'hooks');
  mkdirSync(root, { recursive: true });

  const home = (id, side) => {
    const h = join(root, 'homes', `${id}-${side}`);
    mkdirSync(h, { recursive: true });
    return h;
  };

  // =========================================================== A, the export: the full bed
  //
  // U7 §2.1's bed, rebuilt here: one project store, one native directory carrying a host
  // index, a SENTINEL file with no index line (`alpha.md`) and an index line with no file
  // (`beta`), so the file gate and the line gate are exercised INDEPENDENTLY in one run. Plus
  // a hand-written fact whose frontmatter says `name: ../escape`, which `facts()` hands out
  // unvalidated and the filename guard must refuse.
  {
    const id = 'native-export';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    const store = join(cwd, '.bantamkit', 'memory');
    const nativeParent = join(b.root, 'host');
    const nativeDir = join(nativeParent, 'memory');
    mkdirSync(cwd, { recursive: true });
    seedStore(ctx, store, [
      { type: 'reference', name: 'alpha', description: 'the first fact' },
      { type: 'reference', name: 'beta', description: 'a second note about the deployment path' },
      { type: 'reference', name: 'gamma', description: 'a description with an em dash — a "quote" and a \\ backslash' },
      { type: 'reference', name: 'delta', description: 'unicode: café 中文 😀 nbsp here' },
    ]);
    // `MemoryStore.save` enforces `^[a-z0-9][a-z0-9-]*$`; `facts()` does NOT revalidate on
    // read, so a hand-written file gets its name handed out verbatim. This is the reachable
    // path into the filename guard, and it is written by hand for exactly that reason.
    writeFile(
      join(store, 'facts', 'weird.md'),
      '---\nname: ../escape\ndescription: a name that must never be joined into a path\ntype: reference\n' +
        "created: '2026-09-20'\nlast_recalled: null\nlinks: []\n---\n\nbody\n",
    );
    writeFile(
      join(nativeDir, 'MEMORY.md'),
      '# Memory index\n\n## Project\n\n- [host-fact](host-fact.md) — the host wrote this\n' +
        '- [beta](beta.md) — a description the host reworded\n',
    );
    writeFile(join(nativeDir, 'alpha.md'), 'a file the host already has, and A must not touch it\n');
    writeFile(join(nativeParent, 'session.jsonl'), '');
    b.snapshot();

    const payload = {
      hook_event_name: 'SessionStart',
      source: 'startup',
      cwd,
      session_id: 'native-export',
      transcript_path: join(nativeParent, 'session.jsonl'),
    };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    const pyTree = treeOf(nativeDir);
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });
    const ndTree = treeOf(nativeDir);

    // THE LOG RECORD — the surface stdout cannot show, because what A changes in the injected
    // block is an absence.
    cases.push({
      name: 'native-export: the ten native* fields of the SessionStart record',
      kind: 'json',
      expected: NATIVE_FIELDS(py.last),
      actual: NATIVE_FIELDS(nd.last),
    });
    // AND THE BYTES. Same bed, same absolute paths, so the fact files and `MEMORY.md` are
    // compared with their content as each runtime wrote it — no masking, no normalisation.
    cases.push({
      name: 'native-export: every byte A left in the host directory',
      kind: 'json',
      expected: pyTree,
      actual: ndTree,
    });
    // The two gates, PINNED PER SIDE. The differential above is satisfied by two runtimes
    // that both stopped exporting; these are what see that. `exported 4` against `files 3` is
    // the file gate and the line gate working separately.
    const summary_ = (r) => ({
      branch: r.last['nativeBranch'],
      tried: r.last['nativeTried'],
      exported: r.last['nativeExported'],
      files: r.last['nativeFiles'],
      indexLines: r.last['nativeIndexLines'],
      index: r.last['nativeIndex'],
      skipped: r.last['nativeSkipped'],
    });
    cases.push(
      ...literalCases(summary_(py), summary_(nd), 'native-export: what the export did, against a literal', {
        branch: 'transcript',
        tried: ['env', 'settings'],
        exported: 4,
        files: 3,
        indexLines: 3,
        index: 'present',
        skipped: ['../escape'],
      }),
    );
    // The sentinel is the one-way rule, pinned per side: `alpha.md` was there before either
    // run and neither runtime may have touched it.
    cases.push(
      ...literalCases(
        pyTree['alpha.md'],
        ndTree['alpha.md'],
        'native-export: the file the host already had is byte-unchanged',
        'a file the host already has, and A must not touch it\n',
        'string',
      ),
    );
    // Necessary, NOT sufficient, and labelled: the injected block is the same on both sides.
    // It cannot show what the export did — that is the whole reason the two cases above
    // exist — but a port that started injecting the project index as WELL as exporting would
    // be visible here and nowhere else.
    cases.push({
      name: 'native-export: stdout — the injected block (necessary, not sufficient: A’s effect here is an absence)',
      kind: 'bytes',
      expected: py.stdout,
      actual: nd.stdout,
    });
    cases.push({
      name: 'native-export: exit and stderr',
      kind: 'json',
      expected: { exit: py.exit, stderr: dec(py.stderr) },
      actual: { exit: nd.exit, stderr: dec(nd.stderr) },
    });
    notes.push(`native-export: ${JSON.stringify(NATIVE_FIELDS(nd.last))}`);
  }

  // ============================================ A, the export: the one divergence, and its bit
  //
  // Branch 1 takes its directory UNVERIFIED — it is the host's own top-precedence override —
  // so naming a directory that is not there is the one shape where A's write fails. Both
  // runtimes catch it, record it, export nothing and exit 0. What differs is the sentence the
  // operating system's own standard library spells, and nothing else.
  {
    const id = 'native-missing-dir';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    seedStore(ctx, join(cwd, '.bantamkit', 'memory'), [
      { type: 'reference', name: 'alpha', description: 'the first fact' },
      { type: 'reference', name: 'beta', description: 'a second note about the deployment path' },
    ]);
    b.snapshot();
    const missing = join(b.root, 'nope');
    const payload = { hook_event_name: 'SessionStart', source: 'startup', cwd, session_id: id };
    const env = { CLAUDE_COWORK_MEMORY_PATH_OVERRIDE: missing };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py'), env });
    // Read PER SIDE and BEFORE the restore: `missing` lives under the bed, so a directory the
    // reference created would be wiped by `restore()` and the port would then be blamed for
    // it — or neither would. One boolean read after both runs is not a per-side fact.
    const pyMadeIt = existsSync(missing);
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node'), env });
    const ndMadeIt = existsSync(missing);

    // THE RULING. One field, and its content is the operating system's sentence rather than
    // bantamkit's: libuv's `CODE: message, syscall 'path'` against CPython's
    // `[Errno n] strerror: 'path'`.
    cases.push({
      name: 'native-missing-dir: nativeError carries each runtime’s own OS sentence',
      kind: 'string',
      expected: py.last['nativeError'],
      actual: nd.last['nativeError'],
      ruling:
        'RULED DIFFERENT, and carried in `docs/porting.md` (job62 J62-9). `nativeError` holds ' +
        'the sentence each language’s standard library spells for one `open()` that failed — ' +
        "libuv's `ENOENT: no such file or directory, open '<p>'` on the port, CPython's " +
        "`[Errno 2] No such file or directory: '<p>'` on the reference. It is not a bantamkit " +
        'sentence, and there is no third spelling both could adopt without one of them ' +
        "hand-rolling the other's strerror table — the same class as the three `open()` rows " +
        'already in that table. The field is LOG-ONLY: it never reaches stdout. The refusal ' +
        'BIT is compared unruled below, and pinned per side, because this case would stay ' +
        'green if one runtime stopped refusing and started writing.',
    });
    // THE REFUSAL BIT — the case the ruling cannot be. A ruling proves the two sides still
    // DIFFER; it never proves either still refuses.
    const bit = (r) => ({
      errorPresent: typeof r.last['nativeError'] === 'string' && r.last['nativeError'].length > 0,
      exported: r.last['nativeExported'],
      files: r.last['nativeFiles'],
      indexLines: r.last['nativeIndexLines'],
      bytes: r.last['nativeBytes'],
      exit: r.exit,
      stdoutObjects: dec(r.stdout).trim() === '' ? 0 : dec(r.stdout).trim().split('\n').length,
    });
    cases.push({
      name: 'native-missing-dir: the refusal BIT — both log an error, export nothing, exit 0, emit one object',
      kind: 'json',
      expected: bit(py),
      actual: bit(nd),
    });
    // And per side, against a literal, because a differential over a bit is blind to both
    // sides losing it at once.
    cases.push(
      ...literalCases(bit(py), bit(nd), 'native-missing-dir: the refusal bit against a literal', {
        errorPresent: true,
        exported: 0,
        files: 0,
        indexLines: 0,
        bytes: 0,
        exit: 0,
        stdoutObjects: 1,
      }),
    );
    // The half the ruling does not license: everything else in the record is identical.
    const masked = (r) => ({ ...NATIVE_FIELDS(r.last), nativeError: '<ruled above>' });
    cases.push({
      name: 'native-missing-dir: every other native* field agrees, with the ruled sentence masked',
      kind: 'json',
      expected: masked(py),
      actual: masked(nd),
    });
    // The directory really is not there afterwards. `mkdir` is a thing A must never do, and a
    // runtime that created it would turn this scenario into a successful export next session.
    cases.push(...literalCases(pyMadeIt, ndMadeIt, 'native-missing-dir: A created no directory', false));
  }

  // ================================================== --install-hooks: what each side records
  {
    const id = 'install-hooks';
    const cwd = join(root, id, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const homes = { py: home(id, 'py'), node: home(id, 'node') };
    const py = runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py });
    const nd = runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node });
    const settings = (h) => join(h, '.claude', 'settings.json');
    const docOf = (h) => JSON.parse(readFileSync(settings(h), 'utf8'));
    const pyDoc = docOf(homes.py);
    const ndDoc = docOf(homes.node);
    const commandsOf = (doc) => {
      const out = [];
      for (const entries of Object.values(doc.hooks ?? {})) {
        for (const entry of entries) for (const h of entry.hooks ?? []) out.push(h.command);
      }
      return out;
    };
    const pyCommands = commandsOf(pyDoc);
    const ndCommands = commandsOf(ndDoc);

    // THE RULING: the one string that cannot be the same sentence on both sides.
    cases.push({
      name: 'install-hooks: the recorded command — each runtime registers ITSELF, by absolute path',
      kind: 'string',
      expected: pyCommands[0],
      actual: ndCommands[0],
      ruling:
        'RULED DIFFERENT, and carried in `docs/porting.md`. `--install-hooks` writes a command ' +
        'a HOST will launch, so it must name the interpreter and the entry point of the ' +
        'install the host should run: `<absolute python> -m bantamkit.mcpserver --hook` on the ' +
        'reference, `<absolute node> <absolute dist/cli.js> --hook` on the port. This is the ' +
        "same genuinely-different-object as `--install`'s recorded command, one surface " +
        'further out — a pure-npm install has no Python in it, and CPython installs no ' +
        '`cli.js`. It is a SPELLING and not a refusal: both sides write, both write seven ' +
        'entries, and everything else in the document is compared unruled below.',
    });
    // PER SIDE, against this file. A port that went back to `npx -y bantamkit-mcp` would still
    // differ from the reference and leave the ruling above green.
    const maskCommand = (s, h) =>
      s
        .split(realNode())
        .join('<NODE>')
        .split(String(ctx.python))
        .join('<PYTHON>')
        .split(pythonResolved(ctx))
        .join('<PYTHON>')
        .split(CLI)
        .join('<CLI>')
        .split(h)
        .join('<HOME>');
    cases.push({
      name: 'install-hooks: PINNED PER SIDE: each runtime names its own interpreter and entry point',
      kind: 'json',
      expected: { python: '<PYTHON> -m bantamkit.mcpserver --hook', node: '<NODE> <CLI> --hook' },
      actual: {
        python: maskCommand(pyCommands[0], homes.py),
        node: maskCommand(ndCommands[0], homes.node),
      },
    });
    // ONE command for all seven events, on both sides — the property `--install-hooks` is
    // built around (the event comes from stdin, never from argv). Pinned per side because a
    // differential over "how many distinct commands" is blind to both sides growing a second.
    cases.push(
      ...literalCases(
        { entries: pyCommands.length, distinct: new Set(pyCommands).size },
        { entries: ndCommands.length, distinct: new Set(ndCommands).size },
        'install-hooks: seven entries, one command',
        { entries: 7, distinct: 1 },
      ),
    );
    // EVERYTHING THE RULING DOES NOT LICENSE: the whole document, byte for byte, with the one
    // ruled string replaced by the same marker on both sides. Matchers, event names, ordering,
    // timeouts and the JSON formatting are all compared here.
    const maskedDoc = (h) => readFileSync(settings(h), 'utf8').split(commandsOf(docOf(h))[0]).join('<COMMAND>');
    cases.push({
      name: 'install-hooks: the written settings.json, byte for byte, with the ruled command masked',
      kind: 'bytes',
      expected: maskedDoc(homes.py),
      actual: maskedDoc(homes.node),
    });
    const maskStream = (buf, h, commands) => {
      let text = dec(buf);
      for (const c of commands) text = text.split(c).join('<COMMAND>');
      return text.split(h).join('<HOME>');
    };
    cases.push({
      name: 'install-hooks: stdout, with the ruled command masked',
      kind: 'bytes',
      expected: maskStream(py.stdout, homes.py, pyCommands),
      actual: maskStream(nd.stdout, homes.node, ndCommands),
    });
    cases.push({
      name: 'install-hooks: stderr and exit',
      kind: 'json',
      expected: { stderr: maskStream(py.stderr, homes.py, pyCommands), exit: py.exit },
      actual: { stderr: maskStream(nd.stderr, homes.node, ndCommands), exit: nd.exit },
    });
  }

  // ========================================== --install-hooks with no terminal: B MUST ASK
  //
  // The rule this job ran under is that the installer asks before it writes a settings file.
  // With stdin at EOF there is nobody to ask, and the measurable property is that NEITHER
  // runtime writes. A differential over the two sentences is satisfied by two runtimes that
  // both stopped asking, so what was written is ALSO pinned per side.
  {
    const id = 'install-hooks-no-tty';
    const cwd = join(root, id, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const homes = { py: home(id, 'py'), node: home(id, 'node') };
    const py = runPy(ctx, { argv: ['--install-hooks'], cwd, home: homes.py });
    const nd = runNode(ctx, { argv: ['--install-hooks'], cwd, home: homes.node });
    const mask = (buf, h) => dec(buf).split(h).join('<HOME>');
    cases.push({
      name: 'install-hooks-no-tty: the same refusal, on the same stream, with the same exit code',
      kind: 'json',
      expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit },
      actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit },
    });
    const wrote = (h) => existsSync(join(h, '.claude', 'settings.json'));
    cases.push(
      ...literalCases(
        { wroteSettings: wrote(homes.py), exit: py.exit },
        { wroteSettings: wrote(homes.node), exit: nd.exit },
        'install-hooks-no-tty: nothing was written, against a literal',
        { wroteSettings: false, exit: 2 },
      ),
    );
  }

  // ============================== docs/porting.md row 7: the 600 and 400 cuts, MEASURED
  //
  // `out.slice(0, 600)` counts UTF-16 code units; `out[:600]` counts code points. J62-3B wrote
  // the row and called it latent because the compact report has no astral characters in it —
  // but the report NAMES THE STORE PATH, twice, and a project directory is a name the operator
  // chose. A directory with eight emoji in it puts eight astral characters in front of both
  // cuts, and the two runtimes then cut the same text at two different places.
  //
  // THIS IS A LATENT PARITY BUG, NOT A DESIGN. It is ruled here because it EXISTS and nothing
  // compared it; the ruling names the repair and says who owns it. The cut lands inside the
  // archived-names block, BEFORE the `restore one with:` line, so the memory CLI's ruled `prog`
  // divergence is not in the compared bytes at all and no second substitution is needed.
  const emojiDir = (() => {
    try {
      const d = join(root, 'row7', 'proj-\u{1F600}\u{1F600}\u{1F600}\u{1F600}\u{1F600}\u{1F600}\u{1F600}\u{1F600}-deck');
      mkdirSync(d, { recursive: true });
      return statSync(d).isDirectory() ? d : null;
    } catch {
      return null;
    }
  })();
  if (emojiDir === null) {
    notes.push(
      'row 7: SKIPPED — this filesystem would not take a directory name containing astral ' +
        'characters, so the cut cannot be driven past one and the comparison would prove nothing.',
    );
  } else {
    const id = 'row7';
    const b = bed(join(root, id));
    const cwd = emojiDir;
    // The budget comes from the registration the session launched, so it is configured here
    // rather than guessed: 300 B budget -> compact at 270, target 240, reserve 60.
    writeFile(join(cwd, '.mcp.json'), `${JSON.stringify({ mcpServers: { bantamkit: { command: 'node', args: ['--index-budget', '300'] } } })}\n`);
    seedStore(
      ctx,
      join(cwd, '.bantamkit', 'memory'),
      [
        'quarterly revenue dashboards and the sheet they live in',
        'deployment rollback procedure for the payment gateway',
        'python packaging traps with editable installs',
        'the onboarding checklist for new contract designers',
        'mutation testing survivors on the parser branch',
        'growth cohort definitions used by the analytics team',
        'rotating the signing keys on the release machine',
        'where the legal archive keeps signed statements of work',
        'satellite imagery vendor contacts and their quotas',
        'the ramen place near the office that opens late',
        'midi controller mapping for the studio rig',
        'thread pool sizing measured on the import job',
        'invoice numbering scheme the finance team insists on',
        'the flaky integration test nobody has bisected yet',
        'conference travel budget approvals and who signs them',
        'backup restore drill notes from the october exercise',
      ].map((description, i) => ({ type: 'reference', name: `fact-${String(i).padStart(2, '0')}`, description })),
    );
    b.snapshot();
    const payload = {
      hook_event_name: 'PostToolUse',
      tool_name: 'mcp__bantamkit__memory_save',
      cwd,
      session_id: id,
    };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });

    const ctxOf = (r) => JSON.parse(dec(r.stdout))['hookSpecificOutput']['additionalContext'];
    const recOf = (r) => r.records.filter((x) => x['action'] === 'auto-compact').slice(-1)[0];
    const pyCtx = ctxOf(py);
    const ndCtx = ctxOf(nd);
    const pyRec = recOf(py);
    const ndRec = recOf(nd);
    // The prefix is fixed text this arm assembles from three numbers both sides agree on, so
    // the literal below is the CUT and not the bed's size.
    const prefixLen = (rec) => codePoints(`[bantamkit] memory index was ${rec['bytes']}/${rec['budget']} B; auto-compacted to ≤${rec['target']} B. `);

    // THE PRECONDITION, AS A CASE. If the bed ever stops producing an `out` longer than the
    // cut, or stops putting an astral character in front of it, everything below is green for
    // the wrong reason.
    cases.push(
      ...literalCases(
        { astralInStorePath: astralCount(join(cwd, '.bantamkit', 'memory')), cutFired: codePoints(pyCtx) > prefixLen(pyRec) + 599 },
        { astralInStorePath: astralCount(join(cwd, '.bantamkit', 'memory')), cutFired: codePoints(ndCtx) > prefixLen(ndRec) + 500 },
        'row7: precondition — eight astral characters sit in front of both cuts and both cuts fired',
        { astralInStorePath: 8, cutFired: true },
      ),
    );

    cases.push({
      name: 'row7: the compact report cut into additionalContext — 600 code points against 600 UTF-16 units',
      kind: 'string',
      expected: pyCtx,
      actual: ndCtx,
      ruling:
        'RULED DIFFERENT AND IT IS A BUG, recorded rather than endorsed — `docs/porting.md` ' +
        'row 7 (job62, J62-3B; the row itself is J62-9’s to write). `postSave` cuts the compact ' +
        "child's output with `out.slice(0, 600)` on the port and `out[:600]` on the reference. " +
        'Those are not the same cut: JavaScript counts UTF-16 code units, Python counts code ' +
        'points, so every astral character before the cut costs the port one character of ' +
        'content. MEASURED here for the first time, over a project directory carrying eight ' +
        'emoji — which the compact report prints, twice — the port emits 8 code points fewer ' +
        'than the reference ON STDOUT, into the model’s context. The repair is one line per ' +
        'runtime (cut by code point on both: `[...out].slice(0, 600).join("")`), it lands in ' +
        'BOTH or in neither, and when it lands this ruling goes stale and reddens, which is ' +
        'the point of writing it down as a case instead of as a sentence. The unruled ' +
        'companion below pins that the divergence is a CUT POINT and nothing else.',
    });
    // The half the ruling does not license: the port's text is a PREFIX of the reference's,
    // so the two agree on every character they both emitted and differ only in where they
    // stopped. A port that also changed the wording would redden here while the ruling stayed
    // green.
    cases.push({
      name: 'row7: the divergence is a cut point and nothing else — the port’s text is a prefix of the reference’s',
      kind: 'json',
      expected: { prefix: true, shorterByCodePoints: 8 },
      actual: { prefix: pyCtx.startsWith(ndCtx), shorterByCodePoints: codePoints(pyCtx) - codePoints(ndCtx) },
    });
    // PER SIDE, against a literal: how many code points survived each cut. 600 on the
    // reference; 600 units minus the eight astral characters = 592 on the port. A repair
    // landing on BOTH sides reddens these two while the ruling above reddens as stale — the
    // pair of failures that tells a reader which of the two things happened.
    cases.push(
      {
        name: 'row7: code points that survived the 600 cut, against a literal — the reference',
        kind: 'json',
        expected: 600,
        actual: codePoints(pyCtx) - prefixLen(pyRec),
      },
      {
        name: 'row7: code points that survived the 600 cut, against a literal — the port (600 units, eight of them paired)',
        kind: 'json',
        expected: 592,
        actual: codePoints(ndCtx) - prefixLen(ndRec),
      },
    );
    // The SAME divergence in the log, under the 400 cut. Ruled for the same reason, and the
    // two lengths are a literal per side for the same reason.
    cases.push({
      name: 'row7: the same cut in the log record’s `out`, at 400',
      kind: 'string',
      expected: pyRec['out'],
      actual: ndRec['out'],
      ruling:
        'RULED DIFFERENT AND IT IS THE SAME BUG one field over — `docs/porting.md` row 7. ' +
        '`out[:400]` against `out.slice(0, 400)` in the `auto-compact` log line. This half is ' +
        'log-only and costs nobody context; it is ruled beside the stdout half because the two ' +
        'lines are repaired together or the repair is half done. The unruled companion below ' +
        'pins that every OTHER field of that record agrees.',
    });
    cases.push(
      {
        name: 'row7: code points that survived the 400 cut, against a literal — the reference',
        kind: 'json',
        expected: 400,
        actual: codePoints(pyRec['out']),
      },
      {
        name: 'row7: code points that survived the 400 cut, against a literal — the port (400 units, eight of them paired)',
        kind: 'json',
        expected: 392,
        actual: codePoints(ndRec['out']),
      },
    );
    cases.push({
      name: 'row7: every other field of the auto-compact record agrees, with the ruled `out` masked',
      kind: 'json',
      expected: { ...pyRec, out: '<ruled above>', ts: '<clock>', ms: '<clock>' },
      actual: { ...ndRec, out: '<ruled above>', ts: '<clock>', ms: '<clock>' },
    });
    notes.push(
      `row 7: additionalContext is ${codePoints(pyCtx)} code points on the reference and ${codePoints(ndCtx)} on the port; ` +
        `the log's \`out\` is ${codePoints(pyRec['out'])} and ${codePoints(ndRec['out'])}`,
    );
  }

  // ============ docs/porting.md row 8: the .shiftwork scan's filename tie-break, MEASURED
  //
  // `candidates.sort((a, b) => b.mtimeMs - a.mtimeMs || a.file.localeCompare(b.file))` against
  // `candidates.sort(key=lambda c: (-c[1], c[0]))`. Reached when two checkpoints share an
  // mtime to the millisecond and their names order differently under ICU collation than by
  // code point. `checkpoint-Banana.json` and `checkpoint-apple.json` are such a pair: by code
  // point `B` (0x42) precedes `a` (0x61); under `localeCompare` `apple` precedes `Banana`.
  //
  // THE PAIR DIFFERS IN MORE THAN CASE ON PURPOSE. A pair differing only in case cannot be
  // built on this machine at all — APFS is case-insensitive and the second write replaces the
  // first — so a case-only fixture would silently become a one-file directory and the tie-break
  // would never be reached. MEASURED, not assumed: the first attempt at this bed produced one
  // file.
  {
    const id = 'row8';
    const dir = join(root, id, 'cwd', '.shiftwork');
    const checkpoint = (cursorTitle) =>
      `${JSON.stringify({ plan: { cursor: 'U1', units: [{ id: 'U1', status: 'todo', title: cursorTitle }] } })}\n`;
    writeFile(join(dir, 'checkpoint-Banana.json'), checkpoint('the code-point sort picks this one'));
    writeFile(join(dir, 'checkpoint-apple.json'), checkpoint('localeCompare picks this one'));
    const same = new Date(1_700_000_000_123);
    for (const n of readdirSync(dir)) utimesSync(join(dir, n), same, same);
    const cwd = join(root, id, 'cwd');
    const payload = {
      hook_event_name: 'PreCompact',
      trigger: 'manual',
      cwd,
      session_id: id,
      transcript_path: join(root, id, 'transcript.jsonl'),
    };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });

    // THE PRECONDITION, AS A CASE: the two files really do share an mtime to the millisecond,
    // and there really are two of them. Without this the ruling could go stale because a
    // filesystem collapsed the bed rather than because anyone repaired anything.
    // ONE case, not a per-side pair: this is a fact about the BED, which both runtimes read,
    // so spelling it twice would be the same boolean printed under two names.
    const mtimes = readdirSync(dir).map((n) => statSync(join(dir, n)).mtimeMs);
    cases.push({
      name: 'row8: precondition — two checkpoints, one mtime, in one directory both runtimes read',
      kind: 'json',
      expected: { files: ['checkpoint-Banana.json', 'checkpoint-apple.json'], distinctMtimes: 1 },
      actual: { files: readdirSync(dir).sort(), distinctMtimes: new Set(mtimes).size },
    });

    cases.push({
      name: 'row8: which checkpoint wins a tie — ICU collation against a code-point sort',
      kind: 'string',
      expected: String(py.last['checkpoint']),
      actual: String(nd.last['checkpoint']),
      ruling:
        'RULED DIFFERENT AND IT IS A BUG, recorded rather than endorsed — `docs/porting.md` ' +
        'row 8 (job62, J62-3B; the row itself is J62-9’s to write). The `.shiftwork` scan ' +
        'orders candidates newest-first and breaks a tie on the filename: the port uses ' +
        '`String.prototype.localeCompare`, which is ICU collation, and the reference uses a ' +
        'plain code-point sort. MEASURED here for the first time: given two OPEN checkpoints ' +
        'written in the same millisecond, the port steers the summariser at ' +
        '`checkpoint-apple.json` and the reference at `checkpoint-Banana.json` — two different ' +
        'jobs, on stdout, with nothing saying so. The repair is one line on the port ' +
        '(`a.file < b.file ? -1 : a.file > b.file ? 1 : 0`), it lands in BOTH runtimes or in ' +
        'neither, and when it lands this ruling goes stale and reddens. The unruled companion ' +
        'below pins that the SCAN agrees — only the tie-break does not.',
    });
    cases.push({
      name: 'row8: PINNED PER SIDE: which file each runtime actually chose, against this file',
      kind: 'json',
      expected: { python: 'checkpoint-Banana.json', node: 'checkpoint-apple.json' },
      actual: {
        python: String(py.last['checkpoint']).split('/').pop(),
        node: String(nd.last['checkpoint']).split('/').pop(),
      },
    });
    // Everything the ruling does not license: the scan read the same number of files, skipped
    // the same number, spent the same bytes, and stopped at the first open one.
    const scan = (r) => ({ cursor: r.last['cursor'], scanned: r.last['cpScanned'], skipped: r.last['cpSkipped'], bytesEqual: r.last['cpBytes'] > 0 });
    cases.push({
      name: 'row8: the scan itself agrees — same cursor, same files read, same files skipped',
      kind: 'json',
      expected: scan(py),
      actual: scan(nd),
    });
  }

  // ===================================== row8's control: a scan with NO tie has one answer
  //
  // The case above is a divergence, so on its own it would be satisfied by two runtimes that
  // disagree about the scan for ANY reason. This bed has the same two filenames and two
  // DIFFERENT mtimes, so the tie-break is never reached and the two runtimes must agree byte
  // for byte — on stdout, which is where the steering line actually goes.
  {
    const id = 'row8-control';
    const b = bed(join(root, id));
    const dir = join(b.root, 'cwd', '.shiftwork');
    const checkpoint = (title) =>
      `${JSON.stringify({ plan: { cursor: 'U1', units: [{ id: 'U1', status: 'todo', title }] } })}\n`;
    writeFile(join(dir, 'checkpoint-Banana.json'), checkpoint('the older one'));
    writeFile(join(dir, 'checkpoint-apple.json'), checkpoint('the newer one, and the only honest winner'));
    utimesSync(join(dir, 'checkpoint-Banana.json'), new Date(1_700_000_000_000), new Date(1_700_000_000_000));
    utimesSync(join(dir, 'checkpoint-apple.json'), new Date(1_700_000_500_000), new Date(1_700_000_500_000));
    b.snapshot();
    const cwd = join(b.root, 'cwd');
    const payload = {
      hook_event_name: 'PreCompact',
      trigger: 'manual',
      cwd,
      session_id: id,
      transcript_path: join(b.root, 'transcript.jsonl'),
    };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });
    cases.push({
      name: 'row8-control: with no tie to break, the steering line is byte-identical on stdout',
      kind: 'bytes',
      expected: py.stdout,
      actual: nd.stdout,
    });
    cases.push(
      ...literalCases(
        String(py.last['checkpoint']).split('/').pop(),
        String(nd.last['checkpoint']).split('/').pop(),
        'row8-control: the newest open checkpoint wins on both sides, against a literal',
        'checkpoint-apple.json',
        'string',
      ),
    );
  }

  notes.push(
    'every hook run in this suite asserted that the adapter followed the throwaway HOME ' +
      '(both HOME and USERPROFILE) before a byte it wrote was read; a run that did not stops the suite',
  );
  return { cases, notes };
}

/** `process.execPath`, which is what the port records as the interpreter half of its command. */
function realNode() {
  return process.execPath;
}

/**
 * How the reference spells its own interpreter in the command it records:
 * `Path(sys.executable).resolve()`, and `cli_ref.py` launches the child with the harness's
 * python. Resolved here so the per-side literal can say `<PYTHON>` without pinning this
 * laptop's interpreter path into the file.
 */
function pythonResolved(ctx) {
  try {
    return realpathSync(String(ctx.python));
  } catch {
    return String(ctx.python);
  }
}
