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
 *
 * AMENDED 2026-09-21 (job63, J63-4): THE MARKER-PRESENCE PROPERTY IS GATED HERE NOW. J62-22
 * decides whether a hook entry is bantamkit's by the PRESENCE of the `bantamkit` key on the
 * inner hook object and never by its value (`_is_ours` in `runtime-py/src/bantamkit/hostinstall.py`,
 * `isOurs` in `runtime-ts/src/hostinstall.ts`), so that a release writing a different value
 * cannot orphan what the previous one wrote. MEASURED BLIND FIRST: rewriting BOTH predicates
 * to a value test (`hook.get(HOOK_MARKER_KEY) == HOOK_MARKER_VALUE` on the reference,
 * `hook[HOOK_MARKER_KEY] === HOOK_MARKER_VALUE` on the port), rebuilding and running this
 * suite left it at 81 cases, 0 failures — every bed carried the current value and the mutation
 * was symmetric. The `hook-marker-presence` block below adds 24 cases: seven values that are
 * NOT the current one (`"some-future-release"`, `""`, `0`, `1`, `false`, `null`, `{"v":1}`),
 * each removed over its own pair of homes and pinned per side against a literal that says the
 * report claimed a removal and the file holds no marker, plus `--install-hooks` over seven
 * stale foreign-valued entries pinned at seven-not-fourteen. Under the same symmetric mutation
 * the 16 per-side literals go red and the 8 differentials stay green (105 cases, 16 failures);
 * under the mutation on ONE side only, 16 go red on either side — the 8 differentials plus
 * that side's 8 literals — and the other side's literals stay green. The unit tests that also
 * hold this (`runtime-py/tests/test_hostinstall_hooks.py`, `runtime-ts/test/hostinstall-hooks.test.mjs`)
 * are the in-process half and stay; this block is the process half.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  symlinkSync,
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
/** ONE pty, allocated by a neutral third party and handed to whichever side is measured. */
const TTY_REF = join(here, 'ref', 'cli_tty_ref.py');

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

function runNode(_ctx, { argv, cwd, home, env = {}, stdin = '', cli = CLI }) {
  const childEnv = { ...process.env };
  for (const key of SCRUBBED) delete childEnv[key];
  childEnv['HOME'] = home;
  childEnv['USERPROFILE'] = home;
  for (const [k, v] of Object.entries(env)) {
    if (v === null) delete childEnv[k];
    else childEnv[k] = String(v);
  }
  const r = spawnSync(process.execPath, [cli, ...argv], {
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

/**
 * An explicit recall through the reference's own `MemoryStore` — the ONE path that still
 * dates a fact on disk after J64-1 — so "re-dated by a recall" is what the product writes and
 * not a line this file spelled. Asserts the name was a hit, or the re-dating never happened.
 */
function recallStore(ctx, storeRoot, query, expectName) {
  const r = spawnSync(
    ctx.python,
    [
      '-c',
      'import sys;sys.path.insert(0,sys.argv[1]);from bantamkit.memory.component import Memory;' +
        'out=Memory(store=sys.argv[2]).recall(sys.argv[3]);assert sys.argv[4] in out,out',
      join(repoRoot, 'runtime-py', 'src'),
      storeRoot,
      query,
      expectName,
    ],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) throw new Error(`hooks: could not recall in ${storeRoot}\n${r.stderr}`);
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

/**
 * Every fact file under `<store>/facts`, name -> { sha256, mtimeNs, lastRecalled }.
 *
 * Three fields because a stamp moves all three and a same-day re-stamp moves only ONE:
 * J64-0 measured that a fact already dated today is rewritten with identical bytes and only
 * its mtime carries the write (`.shiftwork/notes-job64/J64-0.md`, Q4). A case that compared
 * contents alone would therefore pass green on a bed whose facts were already stamped, which
 * is why `mtimeNs` is read as a BigInt string and compared as a literal. `lastRecalled` is
 * the frontmatter line itself, so a failure names the field that moved and not just the file.
 */
function factsState(factsDir) {
  const out = {};
  if (!existsSync(factsDir)) return out;
  for (const name of readdirSync(factsDir).filter((n) => n.endsWith('.md')).sort()) {
    const path = join(factsDir, name);
    const text = readFileSync(path, 'utf8');
    out[name] = {
      sha256: createHash('sha256').update(text, 'utf8').digest('hex'),
      mtimeNs: String(statSync(path, { bigint: true }).mtimeNs),
      lastRecalled: (/^last_recalled: (.*)$/m.exec(text) ?? [, '<no last_recalled line>'])[1],
    };
  }
  return out;
}

/** Which facts moved between two `factsState` snapshots, per field, so `[]` means "none". */
function factsDiff(before, after) {
  const names = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  const moved = (field) => names.filter((n) => (before[n] ?? {})[field] !== (after[n] ?? {})[field]);
  return { rewritten: moved('sha256'), mtimeMoved: moved('mtimeNs'), stamped: moved('lastRecalled') };
}

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
    // WHAT A WROTE, PINNED PER SIDE — added by J62-10 (review) after a MEASURED blind spot.
    // Everything above compares A's output side to side, and the only literal is a summary of
    // COUNTS. That leaves the bytes A puts into the host's auto-memory held by a differential
    // alone, and a differential is blind to a regression that lands in both runtimes. Measured
    // 2026-09-20: changing the file's own body prose in BOTH runtimes to say *"bantamkit
    // rewrites this file every session"* — the exact opposite of the one-way rule this whole
    // section exists to keep — left `--suite hooks` at 42 cases / 0 failures, and left
    // `runtime-py/tests/test_nativeexport.py` and `runtime-ts/test/nativeexport.test.mjs`
    // green too, because neither pins that paragraph. These two literals are what sees it.
    //
    // `gamma` is the escaping-sensitive one: an em dash, a `"quote"` and a `\` backslash, all
    // of which have to survive a JSON string used as a YAML double-quoted scalar identically
    // on both sides.
    cases.push(
      ...literalCases(
        pyTree['gamma.md'],
        ndTree['gamma.md'],
        'native-export: one exported file, byte for byte, against a literal',
        '---\n' +
          'name: gamma\n' +
          'description: "a description with an em dash — a \\"quote\\" and a \\\\ backslash"\n' +
          'metadata:\n' +
          '  node_type: memory\n' +
          '  type: reference\n' +
          '  source: bantamkit\n' +
          '---\n' +
          '\n' +
          "Exported from bantamkit's project memory store. The body of this fact is not here: call\n" +
          '`mcp__bantamkit__memory_recall` with the name `gamma` to read it.\n' +
          '\n' +
          'Written once, only because the name was absent from this directory. bantamkit never\n' +
          'rewrites and never deletes an entry here, so whatever the host does to this file stands.\n',
        'string',
      ),
    );
    // AND THE INDEX, whole. This is the non-destructiveness rule as a literal rather than as a
    // comparison: the host's own two lines are still the first two lines, in the host's own
    // words (`beta` stays "a description the host reworded" even though bantamkit's store
    // describes it differently), A's section is APPENDED under its own heading, and `beta` has
    // no second line because the host's index already named it.
    cases.push(
      ...literalCases(
        pyTree['MEMORY.md'],
        ndTree['MEMORY.md'],
        'native-export: the host index A appended to, byte for byte, against a literal',
        '# Memory index\n' +
          '\n' +
          '## Project\n' +
          '\n' +
          '- [host-fact](host-fact.md) — the host wrote this\n' +
          '- [beta](beta.md) — a description the host reworded\n' +
          '\n' +
          '## bantamkit\n' +
          '\n' +
          '- [alpha](alpha.md) — the first fact\n' +
          '- [delta](delta.md) — unicode: café 中文 😀 nbsp here\n' +
          '- [gamma](gamma.md) — a description with an em dash — a "quote" and a \\ backslash\n',
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


  // ================================================ --remove-hooks: THE SAME GATE, BOTH WAYS
  //
  // THIS FLAG HAD NO CONFORMANCE CASE AT ALL UNTIL THIS UNIT — J62-10's finding. It shipped in
  // both runtimes, it rewrites the operator's own settings file, and nothing in `--all`
  // compared the two answers. On 2026-09-20 it rewrote the operator's REAL
  // `~/.claude/settings.json` with no terminal, no `--yes` and exit 0, the user overturned
  // RULING Q3.7, and both runtimes grew `--install-hooks`' three-state gate. The cases below
  // are that gate's first measurement across the two.
  //
  // FOUR STATES ARE MEASURED: refused (no terminal, no `--yes`), consented (`--yes`), DECLINED
  // AT A REAL TERMINAL, and nothing-of-ours (the no-op that returns BEFORE the gate).
  //
  // EVERY REFUSAL CARRIES A SECOND, NON-RULED CASE OVER THE REFUSAL BIT. A differential over
  // two sentences is satisfied by two runtimes that both stopped refusing, so what was written
  // and what came back are ALSO pinned per side against a literal in this file.
  //
  // THE REDIRECT IS ASSERTED, NOT BELIEVED, and it is asserted from the runtime's own report:
  // each side's `--install-hooks` seed must have named a path inside the throwaway home before
  // a single removal runs. This is the flag whose unsandboxed probe did the damage.
  {
    const id = 'remove-hooks';
    const cwd = join(root, id, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const settings = (h) => join(h, '.claude', 'settings.json');
    const backupsIn = (h) => {
      const d = join(h, '.claude');
      return existsSync(d) ? readdirSync(d).filter((n) => n.includes('.backup-')).sort() : [];
    };
    // A hook entry nobody named bantamkit wrote. It must survive every case below, on both
    // sides, which is what makes "only bantamkit's own entries are removed" a measurement.
    const FOREIGN = { matcher: 'Bash', hooks: [{ type: 'command', command: '/opt/acme/audit.sh', timeout: 5 }] };
    const mask = (buf, h) => dec(buf).split(h).join('<HOME>');
    /**
     * ONE FRESH PAIR OF HOMES PER STATE, AND THAT IS NOT TIDINESS — IT IS THE DIFFERENCE
     * BETWEEN A CASE AND A VACUOUS ONE. A first draft of this block seeded once and ran the
     * four states down one pair of homes; measured against the PRE-PORT reference, only 5 of
     * the 13 cases could go red, because the first state's un-gated removal emptied the
     * reference's file and every later state then compared two runtimes that both had nothing
     * left to do. Each state now starts from the same seeded bed, so each one fails on its own.
     */
    const seeded = (state) => {
      const homes = { py: home(`${id}-${state}`, 'py'), node: home(`${id}-${state}`, 'node') };
      for (const side of ['py', 'node']) {
        writeFile(settings(homes[side]), `${JSON.stringify({ model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, null, 2)}\n`);
      }
      const out = {
        py: runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py }),
        node: runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node }),
      };
      for (const side of ['py', 'node']) {
        if (out[side].exit !== 0) throw new Error(`hooks/${id}/${state}: the ${side} seed failed: ${dec(out[side].stderr)}`);
        // THE REDIRECT, FROM INSIDE THE RUNTIME. The report names the file it wrote; if that
        // path is not under the throwaway home, nothing below may run.
        const named = dec(out[side].stdout).split('\n')[0] ?? '';
        if (!named.includes(homes[side])) {
          throw new Error(`hooks/${id}/${state}: the ${side} seed wrote outside the scratch home: ${named}`);
        }
        if (!existsSync(settings(homes[side]))) throw new Error(`hooks/${id}/${state}: the ${side} seed wrote no settings file`);
      }
      return homes;
    };

    // ---------------------------------------------------- state 1: no terminal, no `--yes`
    {
      const homes = seeded('refused');
      const before = { py: readFileSync(settings(homes.py), 'utf8'), node: readFileSync(settings(homes.node), 'utf8') };
      const backupsBefore = { py: backupsIn(homes.py).length, node: backupsIn(homes.node).length };
      const py = runPy(ctx, { argv: ['--remove-hooks'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--remove-hooks'], cwd, home: homes.node });
      cases.push({
        name: 'remove-hooks-no-tty: the same refusal, on the same stream, with the same exit code',
        kind: 'json',
        expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit },
        actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit },
      });
      // THE REFUSAL BIT, PER SIDE. Two runtimes that both went back to rewriting the file
      // unasked would still agree with each other, and the differential above would stay green.
      const outcome = (side, r, h) => ({
        exit: r.exit,
        settingsByteIdentical: readFileSync(settings(h), 'utf8') === before[side],
        backupsAdded: backupsIn(h).length - backupsBefore[side],
        stdout: mask(r.stdout, h),
        saysItNeedsATerminal: mask(r.stderr, h).startsWith(
          '--remove-hooks rewrites your ~/.claude/settings.json and needs a terminal to ask.',
        ),
      });
      cases.push(
        ...literalCases(
          outcome('py', py, homes.py),
          outcome('node', nd, homes.node),
          'remove-hooks-no-tty: it REFUSED and wrote nothing, against a literal',
          { exit: 2, settingsByteIdentical: true, backupsAdded: 0, stdout: '', saysItNeedsATerminal: true },
        ),
      );
    }

    // ------------------------------- state 2: declined at a REAL TERMINAL — exit 1, no write
    //
    // The seam cases in each runtime's own suite cannot reach this: they inject the answer and
    // never touch a terminal reader. `cli_tty_ref.py` allocates ONE `pty.openpty()` and hands
    // the slave to whichever side is being measured — one terminal implementation for both,
    // because measuring each side through its own fake would compare the fakes. It writes EOF
    // down the master, and EOF is a NO: the ruled default is `[y/N]`.
    {
      const homes = seeded('declined');
      const before = { py: readFileSync(settings(homes.py), 'utf8'), node: readFileSync(settings(homes.node), 'utf8') };
      const backupsBefore = { py: backupsIn(homes.py).length, node: backupsIn(homes.node).length };
      const atATerminal = (side) => {
        const answer = ctx.runPython(TTY_REF, {
          side,
          argv: ['--remove-hooks'],
          env: { HOME: homes[side], USERPROFILE: homes[side], ...Object.fromEntries(SCRUBBED.map((k) => [k, null])) },
          cwd,
          timeout: 60,
          node: { exec: process.execPath, cli: CLI },
        });
        if (answer.unsupported) return null;
        if (answer.error) throw new Error(`hooks/${id} (${side}): ${answer.error}`);
        return { stdout: unb64(answer.stdout), stderr: unb64(answer.stderr), exit: answer.exit };
      };
      const pyTty = atATerminal('py');
      const ndTty = pyTty === null ? null : atATerminal('node');
      if (pyTty === null || ndTty === null) {
        notes.push(
          'remove-hooks-declined: NOT MEASURED HERE — `pty.openpty()` is POSIX-only and this is ' +
            `${process.platform}. The declined branch IS exercised on every platform by each runtime's ` +
            "own suite through the `ask` seam (`runtime-py/tests/test_hostinstall_hooks.py`, " +
            '`runtime-ts/test/hostinstall-hooks.test.mjs`); what a Windows run cannot tell you is ' +
            'whether the two still agree about a REAL terminal. The other three states are measured everywhere.',
        );
      } else {
        cases.push({
          name: 'remove-hooks-declined: the same question, the same refusal, the same exit code, at one pty',
          kind: 'json',
          expected: { stdout: mask(pyTty.stdout, homes.py), stderr: mask(pyTty.stderr, homes.py), exit: pyTty.exit },
          actual: { stdout: mask(ndTty.stdout, homes.node), stderr: mask(ndTty.stderr, homes.node), exit: ndTty.exit },
        });
        const declined = (side, r, h) => ({
          exit: r.exit,
          settingsByteIdentical: readFileSync(settings(h), 'utf8') === before[side],
          backupsAdded: backupsIn(h).length - backupsBefore[side],
          askedTheRemovalQuestion: mask(r.stderr, h).includes('Remove these hook entries? [y/N] '),
          saidNothingWasRemoved: mask(r.stderr, h).includes('no hooks were removed'),
        });
        cases.push(
          ...literalCases(
            declined('py', pyTty, homes.py),
            declined('node', ndTty, homes.node),
            'remove-hooks-declined: it ASKED, was told no, and wrote nothing, against a literal',
            { exit: 1, settingsByteIdentical: true, backupsAdded: 0, askedTheRemovalQuestion: true, saidNothingWasRemoved: true },
          ),
        );
      }
    }

    // ------------------------------------------------- state 3: `--yes`, the consented write
    {
      const homes = seeded('consented');
      // THE BACKUP IS CHECKED BY ITS CONTENTS, NOT BY COUNTING FILES, and that took two tries.
      // The seed takes a backup of its own, and the name is DATED — one file per day — so the
      // removal's backup overwrites the seed's and the count never moves. A literal reading
      // `backups: 1` was satisfied by a port with `backup()` deleted; so was `backupsAdded: 1`.
      // What only a real backup can produce is the PRE-REMOVAL bytes, which is what is pinned.
      const before = { py: readFileSync(settings(homes.py), 'utf8'), node: readFileSync(settings(homes.node), 'utf8') };
      const py = runPy(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.node });
      cases.push({
        name: 'remove-hooks-yes: stdout, stderr and exit — the four-line plan and the report',
        kind: 'json',
        expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit },
        actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit },
      });
      // WHAT IS LEFT ON DISK, byte for byte. No ruled string is in this document: the removal
      // plan has no `command:` line and the entries naming bantamkit are gone, so the only
      // thing left is the operator's own file.
      cases.push({
        name: 'remove-hooks-yes: the settings.json left behind, byte for byte',
        kind: 'bytes',
        expected: readFileSync(settings(homes.py), 'utf8'),
        actual: readFileSync(settings(homes.node), 'utf8'),
      });
      const left = (side, h) => {
        const copies = backupsIn(h);
        return {
          exit: 0,
          doc: JSON.parse(readFileSync(settings(h), 'utf8')),
          backupHoldsThePreRemovalBytes:
            copies.length === 1 && readFileSync(join(h, '.claude', copies[0]), 'utf8') === before[side],
        };
      };
      // PER SIDE: the foreign entry survived, the non-`hooks` key survived, an event left with
      // nothing lost its KEY rather than holding `[]`, and the dated backup was taken — the one
      // thing that made 2026-09-20's damage recoverable.
      cases.push(
        ...literalCases(
          { ...left('py', homes.py), exit: py.exit },
          { ...left('node', homes.node), exit: nd.exit },
          'remove-hooks-yes: only ours came out, and a backup was taken, against a literal',
          { exit: 0, doc: { model: 'opus', hooks: { PreToolUse: [FOREIGN] } }, backupHoldsThePreRemovalBytes: true },
        ),
      );
    }

    // ------------------------ state 4: nothing of ours — the no-op RETURNS BEFORE THE GATE
    //
    // A second `--remove-hooks` has no write to consent to, so it must stay exit 0 with no
    // terminal and no `--yes` — otherwise a teardown script that runs it twice starts
    // refusing. This is the ORDER, and the order is the property.
    {
      const homes = seeded('noop');
      // The first removal is the SETUP, consented so it cannot itself be the thing measured.
      for (const [side, run] of [['py', runPy], ['node', runNode]]) {
        const r = run(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes[side] });
        if (r.exit !== 0) throw new Error(`hooks/${id}/noop: the ${side} setup removal failed: ${dec(r.stderr)}`);
      }
      const before = { py: readFileSync(settings(homes.py), 'utf8'), node: readFileSync(settings(homes.node), 'utf8') };
      const backupsBefore = { py: backupsIn(homes.py).length, node: backupsIn(homes.node).length };
      const py = runPy(ctx, { argv: ['--remove-hooks'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--remove-hooks'], cwd, home: homes.node });
      cases.push({
        name: 'remove-hooks-noop: nothing of ours — the same report, the same streams, the same exit',
        kind: 'json',
        expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit },
        actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit },
      });
      const noop = (side, r, h) => ({
        exit: r.exit,
        stdout: mask(r.stdout, h),
        stderr: mask(r.stderr, h),
        settingsByteIdentical: readFileSync(settings(h), 'utf8') === before[side],
        backupsAdded: backupsIn(h).length - backupsBefore[side],
      });
      cases.push(
        ...literalCases(
          noop('py', py, homes.py),
          noop('node', nd, homes.node),
          'remove-hooks-noop: exit 0 with NO terminal and NO --yes, against a literal',
          {
            exit: 0,
            stdout: 'no bantamkit hooks are installed in <HOME>/.claude/settings.json\n',
            stderr: '',
            settingsByteIdentical: true,
            backupsAdded: 0,
          },
        ),
      );
    }
  }

  // ================================ OWNERSHIP IS A PROPERTY OF THE ENTRY (J62-22), NOT OF THE
  //                                  PATH THE BINARY HAPPENS TO SIT AT
  //
  // THE BUG THIS BLOCK EXISTS FOR, MEASURED BEFORE IT WAS FIXED. `isOurs` asked whether an
  // entry's JSON happened to contain the literal `bantamkit`. Every checkout on the machine
  // this was written on is called `bantamkit*`, so the entry's own command carried the word and
  // the test looked right. From an install tree whose path does not carry it — an npm install
  // under another name, a Docker image with `dist/` at `/app/dist/`, any vendored build — three
  // `--install-hooks --yes` left TWENTY-ONE entries instead of seven, and `--remove-hooks --yes`
  // then answered `no bantamkit hooks are installed` on BOTH runtimes. Hook entries in a user's
  // settings that neither runtime could ever take back out, growing by seven per reinstall.
  //
  // WHY THIS BLOCK NEVER COPIES A TREE TO A NEUTRAL PATH. It does not have to, and a suite that
  // did would be measuring the copy. The property is that ownership is decidable FROM THE ENTRY
  // ALONE, so the entries are SEEDED: a marker-bearing entry whose command names no path of
  // ours, a `tools/hooks/install.mjs` entry from before the marker existed, and four foreign
  // entries chosen to be exactly the ones the old substring test would have eaten. Nothing in
  // the bed depends on where either runtime lives, which is the whole claim.
  //
  // AND IT IS THE SAME BED ON BOTH SIDES, BYTE FOR BYTE — no interpreter path, no home, no
  // `dist/cli.js` appears in it. That is why the removal case below compares the two documents
  // with no masking at all: if a path could leak into the answer, the comparison would say so.
  {
    const id = 'hook-ownership';
    const cwd = join(root, id, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const settings = (h) => join(h, '.claude', 'settings.json');

    /** What 0.35.4 writes, from an install path with no `bantamkit` anywhere in it. */
    const marked = (command) => ({
      type: 'command',
      command,
      timeout: 10,
      bantamkit: 'hook',
    });
    const NEUTRAL = '/opt/vendor/bin/node /opt/vendor/app/dist/cli.js --hook';
    /** `tools/hooks/install.mjs`, which never carried a marker and is on real machines today. */
    const LEGACY = {
      type: 'command',
      command: 'node /srv/checkouts/toolbox/tools/hooks/bantamkit-hook.mjs',
      timeout: 10,
    };
    // THE FOUR FOREIGN ENTRIES, AND EACH ONE IS A WAY THE OLD TEST WIDENED. The first three
    // were CLAIMED AND DELETED by it; the fourth never was, and is here so that narrowing the
    // test cannot be mistaken for narrowing it to nothing.
    const FOREIGN_MATCHER = { matcher: 'bantamkit', hooks: [{ type: 'command', command: '/opt/acme/audit.sh', timeout: 5 }] };
    const FOREIGN_MENTIONS = { hooks: [{ type: 'command', command: '/home/dev/bin/backup-bantamkit-notes.sh', timeout: 5 }] };
    const FOREIGN_MESSAGE = { hooks: [{ type: 'command', command: '/opt/acme/lint.sh', timeout: 5, statusMessage: 'linting for bantamkit' }] };
    const FOREIGN_HOOKFLAG = { hooks: [{ type: 'command', command: '/opt/acme/acmetool --hook', timeout: 5 }] };

    /** The bed. Identical bytes for both runtimes; `Notification` is outside the seven. */
    const BED = {
      model: 'opus',
      hooks: {
        SessionStart: [{ matcher: 'startup|resume|clear|compact', hooks: [marked(NEUTRAL)] }, FOREIGN_MENTIONS],
        PreToolUse: [{ matcher: 'Read', hooks: [LEGACY] }, FOREIGN_HOOKFLAG],
        PostToolUse: [{ hooks: [marked(NEUTRAL)] }, FOREIGN_MESSAGE],
        Stop: [FOREIGN_MATCHER],
        Notification: [FOREIGN_MATCHER],
      },
    };
    const BED_BYTES = `${JSON.stringify(BED, null, 2)}\n`;

    // ------------------------------------ removal: ours come out wherever the binary lives
    {
      const homes = { py: home(id, 'py'), node: home(id, 'node') };
      for (const side of ['py', 'node']) writeFile(settings(homes[side]), BED_BYTES);
      const py = runPy(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.node });
      const mask = (buf, h) => dec(buf).split(h).join('<HOME>');
      cases.push({
        name: 'hook-ownership: the same streams and the same exit, removing entries neither runtime wrote',
        kind: 'json',
        expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit },
        actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit },
      });
      cases.push({
        name: 'hook-ownership: the settings.json left behind, byte for byte, unmasked',
        kind: 'bytes',
        expected: readFileSync(settings(homes.py), 'utf8'),
        actual: readFileSync(settings(homes.node), 'utf8'),
      });
      // PER SIDE, AND THIS IS THE CASE THAT CATCHES THE BUG. The differential above is blind to
      // it: before the fix BOTH runtimes answered `no bantamkit hooks are installed` over this
      // bed and BOTH left it byte-identical, so the two agreed perfectly while orphaning every
      // entry in it. Only a literal in this file can fail on that.
      const removed = (r, h) => ({
        exit: r.exit,
        doc: JSON.parse(readFileSync(settings(h), 'utf8')),
        reportedRemoval: mask(r.stdout, h).split('\n')[0],
      });
      cases.push(
        ...literalCases(
          removed(py, homes.py),
          removed(nd, homes.node),
          'hook-ownership: the marker and the legacy adapter came out, the four foreign entries stayed, against a literal',
          {
            exit: 0,
            doc: {
              model: 'opus',
              hooks: {
                SessionStart: [FOREIGN_MENTIONS],
                PreToolUse: [FOREIGN_HOOKFLAG],
                PostToolUse: [FOREIGN_MESSAGE],
                Stop: [FOREIGN_MATCHER],
                Notification: [FOREIGN_MATCHER],
              },
            },
            reportedRemoval: 'removed bantamkit hooks from <HOME>/.claude/settings.json',
          },
        ),
      );
    }

    // ------------------------------------------------- install over the same foreign entries
    //
    // IDEMPOTENCE IS THE OTHER HALF OF THE SAME DEFECT, and it is the half the `21` came from.
    // A reinstall over seven marker-bearing entries this build did not write — the shape an
    // `npm -g` upgrade leaves, or a second machine's image — must leave SEVEN, not fourteen.
    {
      const homes = { py: home(`${id}-install`, 'py'), node: home(`${id}-install`, 'node') };
      const seed = {
        model: 'opus',
        hooks: Object.fromEntries([
          ...[
            ['SessionStart', 'startup|resume|clear|compact'],
            ['PreToolUse', 'Read'],
            ['PostToolUse', null],
            ['UserPromptSubmit', null],
            ['PreCompact', null],
            ['PostCompact', null],
            ['Stop', null],
          ].map(([event, matcher]) => [
            event,
            [matcher === null ? { hooks: [marked(NEUTRAL)] } : { matcher, hooks: [marked(NEUTRAL)] }],
          ]),
          ['Notification', [FOREIGN_MATCHER]],
        ]),
      };
      const seedBytes = `${JSON.stringify(seed, null, 2)}\n`;
      for (const side of ['py', 'node']) writeFile(settings(homes[side]), seedBytes);
      const py = runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node });
      const shape = (r, h) => {
        const doc = JSON.parse(readFileSync(settings(h), 'utf8'));
        const entries = Object.entries(doc.hooks ?? {}).filter(([event]) => event !== 'Notification');
        const commands = entries.flatMap(([, list]) => list.flatMap((e) => (e.hooks ?? []).map((x) => x.command)));
        return {
          exit: r.exit,
          ourEvents: entries.length,
          ourEntries: entries.reduce((n, [, list]) => n + list.length, 0),
          distinctCommands: new Set(commands).size,
          neutralSurvivors: commands.filter((c) => c === NEUTRAL).length,
          everyEntryCarriesTheMarker: entries.every(([, list]) =>
            list.every((e) => (e.hooks ?? []).every((x) => Object.hasOwn(x, 'bantamkit'))),
          ),
          notificationUntouched: JSON.stringify(doc.hooks?.Notification) === JSON.stringify([FOREIGN_MATCHER]),
        };
      };
      cases.push({
        name: 'hook-ownership-install: reinstalling over entries this build did not write — the same shape',
        kind: 'json',
        expected: shape(py, homes.py),
        actual: shape(nd, homes.node),
      });
      // PER SIDE. `ourEntries: 7` is the whole `21` failure in one number, and it is pinned
      // here rather than only compared because before the fix BOTH sides produced 14.
      cases.push(
        ...literalCases(
          shape(py, homes.py),
          shape(nd, homes.node),
          'hook-ownership-install: seven entries, none of them duplicated, against a literal',
          {
            exit: 0,
            ourEvents: 7,
            ourEntries: 7,
            distinctCommands: 1,
            neutralSurvivors: 0,
            everyEntryCarriesTheMarker: true,
            notificationUntouched: true,
          },
        ),
      );
      // AND AGAIN, over what this build itself just wrote. `--install-hooks` twice is the case
      // an operator actually reaches, and it is pinned per side for the same reason.
      const again = {
        py: runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py }),
        node: runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node }),
      };
      const repeat = (r, h) => ({
        exit: r.exit,
        ourEntries: Object.entries(JSON.parse(readFileSync(settings(h), 'utf8')).hooks ?? [])
          .filter(([event]) => event !== 'Notification')
          .reduce((n, [, list]) => n + list.length, 0),
        saidAlreadyInstalled: dec(r.stdout).includes('bantamkit hooks are already installed'),
      });
      cases.push(
        ...literalCases(
          repeat(again.py, homes.py),
          repeat(again.node, homes.node),
          'hook-ownership-install: a second --install-hooks is a no-op, against a literal',
          { exit: 0, ourEntries: 7, saidAlreadyInstalled: true },
        ),
      );
    }
    // -------------------------------- and the real thing: a Node install tree with a NEUTRAL name
    //
    // THE SEEDED CASES ABOVE DECIDE OWNERSHIP FROM A HAND-WRITTEN ENTRY. This one makes the
    // runtime write the entry itself, from a copy of `dist/` at a path that does not carry the
    // product's name — the `21` in the defect report, reproduced inside the harness.
    //
    // ONLY THE PORT CAN REACH IT, and that asymmetry is the measurement, not a gap. The
    // reference's `this_command()` returns either a `bantamkit-mcp*` console script or
    // `<python> -m bantamkit.mcpserver`, so the reference's own command names the product
    // WHATEVER path it was installed at, and the reference could always recognise its own
    // entries. The port's returns `process.execPath` plus `<dir>/cli.js`, whose only occurrence
    // of the word is whatever the install path happens to carry. So the port is driven from a
    // neutral tree, the reference from its ordinary invocation, and the two answers are
    // compared: ownership must not depend on which side you are on OR where it sits.
    //
    // THE NEUTRAL PATH IS ASSERTED, NOT ASSUMED. If the harness's own temporary root contains
    // the word — a `TMPDIR` inside this repository would do it — the copy proves nothing and
    // the sub-case says so instead of passing.
    {
      const neutralRoot = join(root, 'hook-ownership-neutral', 'vendor-app');
      const neutralCli = join(neutralRoot, 'dist', 'cli.js');
      const usable = (() => {
        if (neutralCli.toLowerCase().includes('bantamkit')) return 'named';
        try {
          mkdirSync(neutralRoot, { recursive: true });
          cpSync(dirname(CLI), join(neutralRoot, 'dist'), { recursive: true });
          cpSync(join(repoRoot, 'runtime-ts', 'package.json'), join(neutralRoot, 'package.json'));
          // A junction on Windows, which needs no elevation; a directory symlink elsewhere.
          symlinkSync(
            join(repoRoot, 'runtime-ts', 'node_modules'),
            join(neutralRoot, 'node_modules'),
            process.platform === 'win32' ? 'junction' : 'dir',
          );
          return 'ok';
        } catch (e) {
          return `link: ${e.code ?? e.message}`;
        }
      })();
      if (usable !== 'ok') {
        notes.push(
          `hook-ownership-neutral: NOT MEASURED — ${
            usable === 'named'
              ? `the harness's temporary root ${root} contains "bantamkit", so a copy under it ` +
                'would carry the word in its path and the comparison would prove nothing'
              : `this tree's dependencies could not be linked into the copy (${usable})`
          }. The entry-local cases above are measured everywhere; what is lost here is the ` +
            'end-to-end reproduction of the duplication itself.',
        );
      } else {
        const homes = { py: home(`${id}-neutral`, 'py'), node: home(`${id}-neutral`, 'node') };
        const entriesIn = (h) =>
          Object.values(JSON.parse(readFileSync(settings(h), 'utf8')).hooks ?? {}).reduce(
            (n, list) => n + list.length,
            0,
          );
        const INSTALLS = 3;
        let lastPy;
        let lastNode;
        for (let i = 0; i < INSTALLS; i++) {
          lastPy = runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py });
          lastNode = runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node, cli: neutralCli });
        }
        const installed = { py: entriesIn(homes.py), node: entriesIn(homes.node) };
        const rmPy = runPy(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.py });
        const rmNode = runNode(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.node, cli: neutralCli });
        const shape = (side, install, remove, h) => ({
          installExit: install.exit,
          entriesAfterThreeInstalls: installed[side],
          removeExit: remove.exit,
          entriesAfterRemoval: entriesIn(h),
          removalFoundThem: !dec(remove.stdout).includes('no bantamkit hooks are installed'),
        });
        const shapePy = shape('py', lastPy, rmPy, homes.py);
        const shapeNode = shape('node', lastNode, rmNode, homes.node);
        cases.push({
          name: 'hook-ownership-neutral: three installs and a removal — the same answer whatever the tree is called',
          kind: 'json',
          expected: shapePy,
          actual: shapeNode,
        });
        // PER SIDE, AND THE PORT'S ROW IS THE DEFECT ITSELF. Before the fix this side read
        // `entriesAfterThreeInstalls: 21`, `removalFoundThem: false`, `entriesAfterRemoval: 21`.
        cases.push(
          ...literalCases(shapePy, shapeNode, 'hook-ownership-neutral: seven, then none, against a literal', {
            installExit: 0,
            entriesAfterThreeInstalls: 7,
            removeExit: 0,
            entriesAfterRemoval: 0,
            removalFoundThem: true,
          }),
        );
      }
    }
  }

  // ======================= THE MARKER'S PRESENCE IS THE TEST, AND THE VALUE IS NEVER READ
  //                          (J62-22's rule; job63 J63-4 is its first conformance case)
  //
  // THE HOLE THIS BLOCK CLOSES WAS MEASURED, NOT SUSPECTED. `isOurs` / `_is_ours` decide
  // ownership from the PRESENCE of the `bantamkit` key on the inner hook object; the value is
  // informational, so that a release which writes a different value does not orphan every
  // entry the previous one wrote. Rewrite BOTH sides to a VALUE test
  // (`hook.get(HOOK_MARKER_KEY) == HOOK_MARKER_VALUE` on the reference,
  // `hook[HOOK_MARKER_KEY] === HOOK_MARKER_VALUE` on the port), rebuild, and on 2026-09-21
  // this suite stayed at 81 cases, 0 failures. Every entry either runtime writes carries the
  // CURRENT value, every bed above is either written by a runtime or hand-seeded with
  // `bantamkit: 'hook'`, and the mutation is symmetric — so the two sides agreed with each
  // other while both orphaned exactly what the rule protects. Until this block the property
  // was held only by each runtime's own unit test (`runtime-py/tests/test_hostinstall_hooks.py`,
  // `runtime-ts/test/hostinstall-hooks.test.mjs`), and a reader asking "is this gated?" of
  // the conformance suite was told no.
  //
  // WHAT IS SEEDED. Marker-bearing entries whose value is NOT what this build writes: a string
  // a future release might choose, and the falsy and non-string shapes the unit tests promise
  // (`''`, `0`, `false`, `null`, an object) — the values a truthiness test or a
  // `typeof === 'string'` test would drop. ONE PAIR OF HOMES PER VALUE, so a red line names the
  // value that was orphaned instead of reporting one combined bed as "differed".
  //
  // WHAT IS PINNED, PER SIDE. (i) the report's first line says the entries were removed, and
  // (ii) the document left behind holds NO hook object carrying the marker key, while the
  // foreign entry that sat beside ours in the same event survived. The differential is kept
  // too: it is the case that catches ONE side regressing, and the literals catch both.
  //
  // AND `--install-hooks` OVER THE SAME SHAPE, because the ownership decision is what turns
  // "replace the stale entry" into "append beside it": under a value test the seed's seven are
  // foreign, ours are appended after them, and the file holds fourteen — the `21` defect's
  // shape by a different road.
  {
    const id = 'hook-marker-presence';
    const cwd = join(root, id, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const settings = (h) => join(h, '.claude', 'settings.json');
    const mask = (buf, h) => dec(buf).split(h).join('<HOME>');
    const FOREIGN = { matcher: 'Bash', hooks: [{ type: 'command', command: '/opt/acme/audit.sh', timeout: 5 }] };
    const NEUTRAL = '/opt/vendor/bin/node /opt/vendor/app/dist/cli.js --hook';
    /** An entry a build OTHER than this one wrote: our marker key, somebody else's value. */
    const markedWith = (value) => ({ type: 'command', command: NEUTRAL, timeout: 10, bantamkit: value });
    /** How many hook objects under `hooks` carry the marker key, whatever its value. */
    const markedHooksIn = (doc) =>
      Object.values(doc.hooks ?? {})
        .flat()
        .flatMap((e) => (Array.isArray(e?.hooks) ? e.hooks : []))
        .filter((x) => x !== null && typeof x === 'object' && Object.hasOwn(x, 'bantamkit')).length;
    // The label is what a red line prints, so a non-string value is spelled as JSON, never coerced.
    const VALUES = [
      ['a string a future release might write', 'some-future-release'],
      ['the empty string', ''],
      ['the number 0', 0],
      ['the number 1', 1],
      ['false', false],
      ['null', null],
      ['an object', { v: 1 }],
    ];

    // ----------------------------------- removal: ours come out whatever the value says
    for (const [i, [label, value]] of VALUES.entries()) {
      const tag = `${JSON.stringify(value)} (${label})`;
      const homes = { py: home(`${id}-remove-${i}`, 'py'), node: home(`${id}-remove-${i}`, 'node') };
      // Ours with a matcher, ours without one, and ours SHARING an event with a foreign entry
      // that must be the only thing left in it. `Notification` is outside the seven.
      const bed = {
        model: 'opus',
        hooks: {
          SessionStart: [{ matcher: 'startup|resume|clear|compact', hooks: [markedWith(value)] }],
          PreToolUse: [FOREIGN, { matcher: 'Read', hooks: [markedWith(value)] }],
          Stop: [{ hooks: [markedWith(value)] }],
          Notification: [FOREIGN],
        },
      };
      for (const side of ['py', 'node']) writeFile(settings(homes[side]), `${JSON.stringify(bed, null, 2)}\n`);
      const py = runPy(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--remove-hooks', '--yes'], cwd, home: homes.node });
      const docOf = (h) => JSON.parse(readFileSync(settings(h), 'utf8'));
      cases.push({
        name: `hook-marker-presence: value ${tag} — the same streams, the same exit, the same file left behind`,
        kind: 'json',
        expected: { stdout: mask(py.stdout, homes.py), stderr: mask(py.stderr, homes.py), exit: py.exit, doc: docOf(homes.py) },
        actual: { stdout: mask(nd.stdout, homes.node), stderr: mask(nd.stderr, homes.node), exit: nd.exit, doc: docOf(homes.node) },
      });
      // PER SIDE, AND THIS IS THE CASE THE MUTATION REDDENS. Under a value test both runtimes
      // answer `no bantamkit hooks are installed`, exit 0, file untouched — and agree.
      const removed = (r, h) => {
        const doc = docOf(h);
        return {
          exit: r.exit,
          reportedRemoval: mask(r.stdout, h).split('\n')[0],
          markedHooksLeft: markedHooksIn(doc),
          doc,
        };
      };
      cases.push(
        ...literalCases(
          removed(py, homes.py),
          removed(nd, homes.node),
          `hook-marker-presence: value ${tag} — removed, and no marker left in the file, against a literal`,
          {
            exit: 0,
            reportedRemoval: 'removed bantamkit hooks from <HOME>/.claude/settings.json',
            markedHooksLeft: 0,
            doc: { model: 'opus', hooks: { PreToolUse: [FOREIGN], Notification: [FOREIGN] } },
          },
        ),
      );
    }

    // --------------------------------- install over seven stale entries, one value per event
    //
    // Seven events, seven foreign values — each event's stale entry carries a different one, so
    // a test that drops SOME values leaves SOME duplicates, and `ourEntries` says how many.
    {
      const homes = { py: home(`${id}-install`, 'py'), node: home(`${id}-install`, 'node') };
      const seed = {
        model: 'opus',
        hooks: Object.fromEntries([
          ...[
            ['SessionStart', 'startup|resume|clear|compact'],
            ['PreToolUse', 'Read'],
            ['PostToolUse', null],
            ['UserPromptSubmit', null],
            ['PreCompact', null],
            ['PostCompact', null],
            ['Stop', null],
          ].map(([event, matcher], i) => [
            event,
            [matcher === null ? { hooks: [markedWith(VALUES[i][1])] } : { matcher, hooks: [markedWith(VALUES[i][1])] }],
          ]),
          ['Notification', [FOREIGN]],
        ]),
      };
      for (const side of ['py', 'node']) writeFile(settings(homes[side]), `${JSON.stringify(seed, null, 2)}\n`);
      const py = runPy(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.py });
      const nd = runNode(ctx, { argv: ['--install-hooks', '--yes'], cwd, home: homes.node });
      const shape = (r, h) => {
        const doc = JSON.parse(readFileSync(settings(h), 'utf8'));
        const entries = Object.entries(doc.hooks ?? {}).filter(([event]) => event !== 'Notification');
        const hooks = entries.flatMap(([, list]) => list.flatMap((e) => e.hooks ?? []));
        return {
          exit: r.exit,
          ourEvents: entries.length,
          ourEntries: entries.reduce((n, [, list]) => n + list.length, 0),
          staleSurvivors: hooks.filter((x) => x.command === NEUTRAL).length,
          hooksCarryingThisBuildsValue: hooks.filter((x) => x.bantamkit === 'hook').length,
          notificationUntouched: JSON.stringify(doc.hooks?.Notification) === JSON.stringify([FOREIGN]),
        };
      };
      cases.push({
        name: 'hook-marker-presence-install: reinstalling over seven foreign-valued markers — the same shape',
        kind: 'json',
        expected: shape(py, homes.py),
        actual: shape(nd, homes.node),
      });
      // PER SIDE. Under a value test this reads `ourEntries: 14, staleSurvivors: 7` on BOTH
      // sides, and the differential above stays green.
      cases.push(
        ...literalCases(
          shape(py, homes.py),
          shape(nd, homes.node),
          'hook-marker-presence-install: seven replaced, none duplicated, against a literal',
          {
            exit: 0,
            ourEvents: 7,
            ourEntries: 7,
            staleSurvivors: 0,
            hooksCarryingThisBuildsValue: 7,
            notificationUntouched: true,
          },
        ),
      );
    }
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

  // ========================================= the stale-install line: the row nothing compared
  //
  // ADDED BY J62-10 (review). `docs/porting.md`'s stale-install row said in its own words that
  // it was "held by a sentence, not by a rerunnable gate", and named its owner as "whichever
  // unit next touches `hooks.mjs`". This unit is that unit.
  //
  // THE COMPANION SHAPE IS NOT `nativeError`'s, and the difference matters. There, BOTH sides
  // refuse, so the refusal bit is the SAME on both and a differential over it is the
  // companion. Here exactly ONE side emits, so a differential over the bit could only ever be
  // red — the honest companion is the bit PINNED PER SIDE, plus an unruled differential over
  // everything the ruling does not license (the block with the update line taken out).
  {
    const id = 'stale-install';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    seedStore(ctx, join(cwd, '.bantamkit', 'memory'), [
      { type: 'project', name: 'seeded', description: 'a fact so the session block is not empty' },
    ]);
    b.snapshot();
    // Each side gets its OWN home (the two hook logs cannot be one file), so the kept install
    // is seeded into each and the home is masked out of everything compared below.
    const seedHome = (h) => {
      writeFile(
        join(h, '.bantamkit', 'mcp', 'node_modules', 'bantamkit-mcp', 'package.json'),
        JSON.stringify({ name: 'bantamkit-mcp', version: '0.35.1' }),
      );
      // `checked_at` is stamped NOW on purpose: a record inside the 24 h TTL makes the probe
      // report `fresh` and the adapter spawn NOTHING. A stale stamp would have this suite
      // launching detached child processes on the operator's machine.
      writeFile(
        join(h, '.bantamkit', 'update-check.json'),
        JSON.stringify({ checked_at: new Date().toISOString(), npm: { latest: '0.36.0' } }),
      );
      return h;
    };
    const pyHome = seedHome(home(id, 'py'));
    const ndHome = seedHome(home(id, 'node'));
    const payload = {
      hook_event_name: 'SessionStart',
      source: 'startup',
      cwd,
      session_id: id,
      transcript_path: join(b.root, 'session.jsonl'),
    };
    writeFile(payload.transcript_path, '');
    const py = runHook(ctx, 'py', { payload, cwd, home: pyHome });
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: ndHome });

    const ctxOf = (r, h) => {
      const objs = dec(r.stdout)
        .split('\n')
        .filter((l) => l.trim())
        .map((l) => JSON.parse(l));
      const out = objs[objs.length - 1]?.hookSpecificOutput?.additionalContext ?? '';
      return String(out).split(h).join('<HOME>');
    };
    const pyCtx = ctxOf(py, pyHome);
    const ndCtx = ctxOf(nd, ndHome);
    // The update line is APPENDED, separator and all, so removing it has to remove the
    // separator the port added with it — otherwise this companion reddens on a trailing
    // newline the reference never had a reason to write, which is what it did first.
    const withoutUpdate = (s) => s.replace(/\n*\[bantamkit\] bantamkit-mcp [^\n]*\n*$/, '');

    // PRECONDITION. A bed where the port ALSO emitted nothing — a kept install the reader
    // could not parse, a record outside the TTL — would make every case below pass by
    // agreement instead of by measurement.
    if (!ndCtx.includes('the package index has 0.36.0')) {
      throw new Error(
        'hooks: stale-install bed did not arm — the port emitted no update line. ' +
          `updateState=${nd.last['updateState']} updateProbe=${nd.last['updateProbe']}`,
      );
    }
    cases.push({
      name: 'stale-install: the SessionStart block — the port names the kept install, the reference cannot',
      kind: 'string',
      expected: pyCtx,
      actual: ndCtx,
      ruling:
        'RULED DIFFERENT, AND THIS ONE IS A DESIGN — `docs/porting.md`, *the hook’s ' +
        'stale-install line, and the probe that feeds it (job62)*. The port decides the line ' +
        'from the KEPT npm install under `~/.bantamkit/mcp`, which `npminstall.ts` makes and ' +
        'which has no Python counterpart under the pure-node-install ruling, so the reference ' +
        'emits nothing and does not pretend to. It is a REFUSAL rather than a spelling, and ' +
        'the companions it owes are below: the bit PINNED PER SIDE (a differential over it ' +
        'could only ever be red, because exactly one side emits) and the same block with the ' +
        'update line removed, compared unruled. Until J62-10 this row was held by a sentence ' +
        'and by a hand probe; the row said so and named the owner as whichever unit next ' +
        'touched this file.',
    });
    // The half the ruling does NOT license: everything else in the injected block is the same
    // on both sides. A port that also reworded the session header would redden here while the
    // ruling stayed green.
    cases.push({
      name: 'stale-install: everything the ruling does NOT license — the same block with the update line taken out',
      kind: 'string',
      expected: withoutUpdate(pyCtx),
      actual: withoutUpdate(ndCtx),
    });
    // THE BIT, PER SIDE. `updateBytes` is deliberately NOT pinned: it counts a line carrying
    // an absolute path, so it is a function of where the scratch directory landed.
    cases.push({
      name: 'stale-install: the bit, PINNED PER SIDE — the reference',
      kind: 'json',
      expected: { updateState: null, updateProbe: 'node-only', emitsUpdateLine: false, updateBytes: 0 },
      actual: {
        updateState: py.last['updateState'] ?? null,
        updateProbe: py.last['updateProbe'] ?? null,
        emitsUpdateLine: pyCtx !== withoutUpdate(pyCtx),
        updateBytes: py.last['updateBytes'] ?? null,
      },
    });
    cases.push({
      name: 'stale-install: the bit, PINNED PER SIDE — the port',
      kind: 'json',
      expected: { updateState: 'available', updateProbe: 'fresh', emitsUpdateLine: true, spawnedNothing: true },
      actual: {
        updateState: nd.last['updateState'] ?? null,
        updateProbe: nd.last['updateProbe'] ?? null,
        emitsUpdateLine: ndCtx !== withoutUpdate(ndCtx),
        spawnedNothing: nd.last['updateProbe'] !== 'spawned',
      },
    });
  }

  // ============================== promptFingerprint.chars — the third code-unit/code-point cut
  //
  // ADDED BY J62-10 (review). `docs/porting.md`'s prose paragraph on this divergence said it
  // could not be gated "without the suite reading a hook log field nothing else reads". The
  // suite already reads hook log records — `runHook` returns them — so the reason was wrong,
  // and an ungated defect in the same class as row 7 is exactly the thing this job set out to
  // stop being held by a sentence. The paragraph is amended to point here.
  //
  // `UserPromptSubmit` only logs the fingerprint on the INJECT branch, so the bed needs a
  // store whose fact actually answers the prompt; the precondition case below is what says it
  // did, rather than letting a `skip` record pass as agreement.
  {
    const id = 'prompt-fingerprint';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    seedStore(ctx, join(cwd, '.bantamkit', 'memory'), [
      {
        type: 'project',
        name: 'deployment-rollback',
        description: 'the deployment path rollback procedure for the staging cluster',
      },
    ]);
    // Three astral characters, so the two counts part company by exactly three.
    const PROMPT = 'deployment path rollback procedure 😀🎉🚀 for the staging cluster';
    b.snapshot();
    const payload = { hook_event_name: 'UserPromptSubmit', prompt: PROMPT, cwd, session_id: id };
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    b.restore();
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });

    // PRECONDITION. A `skip` or a `none` record carries no fingerprint at all, and two absent
    // fingerprints compare equal — the shape `tests-that-pick-the-input-that-cannot-fail`
    // warns about. This stops the suite instead.
    if (py.last['action'] !== 'inject' || nd.last['action'] !== 'inject') {
      throw new Error(
        `hooks: prompt-fingerprint needs the INJECT branch on both sides and got ` +
          `py=${py.last['action']} node=${nd.last['action']}; the bed's store no longer ` +
          'answers the prompt, so nothing below would be comparing a fingerprint.',
      );
    }
    cases.push(
      ...literalCases(
        { astral: astralCount(PROMPT), codePoints: codePoints(PROMPT) },
        { astral: astralCount(PROMPT), codePoints: codePoints(PROMPT) },
        'prompt-fingerprint: precondition — three astral characters in the prompt, and both sides injected',
        { astral: 3, codePoints: 62 },
      ),
    );
    cases.push({
      name: 'prompt-fingerprint: chars — code points against UTF-16 code units',
      kind: 'json',
      expected: { chars: py.last['prompt']['chars'] },
      actual: { chars: nd.last['prompt']['chars'] },
      ruling:
        'RULED DIFFERENT AND IT IS A BUG, recorded rather than endorsed — `docs/porting.md`, ' +
        'the `promptFingerprint.chars` paragraph under the divergence table. The ' +
        '`UserPromptSubmit` arm logs `{sha256, chars, bytes}` for the prompt it answered; ' +
        '`chars` is `String.prototype.length` on the port and `len(str)` on the reference, ' +
        'so the two agree below U+10000 and part company by one per astral character. It is ' +
        'the same class as row 7 and the same one-line repair closes both. Until J62-10 this ' +
        'was named in prose and gated by nothing, on the stated grounds that a case would ' +
        'have to read a hook log field nothing else reads — which this suite already does. ' +
        'When the repair lands this ruling goes stale and reddens, and the per-side literals ' +
        'below redden with it; that pair of failures is the whole reason it is a case.',
    });
    // The half the ruling does not license: the digest and the byte count are the same
    // function on both sides, and a port that started hashing something else would redden
    // here while the ruling stayed green.
    cases.push({
      name: 'prompt-fingerprint: everything the ruling does NOT license — sha256 and bytes',
      kind: 'json',
      expected: { sha256: py.last['prompt']['sha256'], bytes: py.last['prompt']['bytes'] },
      actual: { sha256: nd.last['prompt']['sha256'], bytes: nd.last['prompt']['bytes'] },
    });
    // PER SIDE, because a repair landing on BOTH leaves the ruling stale but the differential
    // green — the symmetric-regression shape.
    cases.push(
      ...literalCases(
        py.last['prompt']['chars'],
        nd.last['prompt']['chars'],
        'prompt-fingerprint: PINNED PER SIDE: 62 code points on the reference, 65 UTF-16 units on the port',
        undefined,
        'json',
      ).map((c, i) => ({ ...c, expected: i === 0 ? 62 : 65 })),
    );
  }

  // ================================ an injection is not a recall (job64, J64-1)
  //
  // THE PROPERTY: a `UserPromptSubmit` that INJECTS leaves every fact file in the store it
  // read byte-identical, contents AND mtime, on both sides — and the injection itself is
  // unchanged: the same block on stdout, the same `inject` record. Until this job the arm
  // went down `Memory.recallOutcome(prompt, 3)` with the component's default `stamp`, so
  // every automatic injection dated up to three facts as "recalled today" and moved their
  // mtime; J64-0 measured 25 of 42 facts in one real store carrying that day's date, and
  // every rule keyed on `last_recalled` (compaction's stalest-first, the SessionStart drop
  // rule, the Stop dream's `size + mtimeMs` fingerprint) was reading this arm's traffic.
  //
  // NOTHING PINNED IT. J64-0 Q2 found no unit test on either side and no case in this suite
  // that read a fact file after a `UserPromptSubmit`; the one Node test that needs a stamped
  // fact seeds it through `Memory.recall`, not the hook. So this block is the first, and it is
  // PER SIDE against a typed constant, because the regression it guards lands symmetrically
  // (one default flipped in one shared component) and a differential would stay green.
  //
  // THE BED HAS A CONTROL BUILT IN. Three facts share tokens with the prompt and two share
  // none, so `hits: 3` is pinned first as the precondition — an arm that skipped the store
  // altogether would leave the files alone for the wrong reason, and `hits: 0` would say so.
  // The "explicit recall still stamps" half of the property is pinned where that surface
  // lives: `tools/conformance/suites/wire.mjs` (`memory_recall` over MCP, per side) and
  // `store.mjs` (`MemoryStore.recall` with `stamp=true`, the whole tree diffed).
  //
  // RED-THEN-GREEN, measured 2026-09-25: with the hook's `stamp=False` / `false` put back to
  // the default on BOTH sides, the four per-side property literals below go red (the
  // `rewritten` / `mtimeMoved` / `stamped` lists each name the three hit files, and the
  // field-for-field snapshot moves on the same three) while the precondition literals, the
  // record differential and the stdout differential all stay green — the symmetric-regression
  // shape, and the reason the record and stdout comparisons alone could never have held this
  // (117 cases, 4 failures). Put back on the port alone: the port's two go red, the reference's
  // two and every differential stay green (117 cases, 2 failures). Counts and commands in
  // `.shiftwork/notes-job64/J64-1.md`.
  {
    const id = 'inject-no-stamp';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const factsDir = join(cwd, '.bantamkit', 'memory', 'facts');
    // Pairwise Jaccard over `tokens(name + description)` stays under the store's 0.5
    // duplicate threshold, or `seedStore` refuses the bed; each hit shares three or more
    // prompt tokens, each miss shares none.
    seedStore(ctx, join(cwd, '.bantamkit', 'memory'), [
      {
        type: 'project',
        name: 'deployment-rollback',
        description: 'the deployment path rollback procedure for the staging cluster',
      },
      { type: 'project', name: 'staging-cluster-notes', description: 'wiring notes kept about the staging cluster nodes' },
      { type: 'project', name: 'rollback-runbook', description: 'runbook steps when a rollback of the deployment is needed' },
      { type: 'reference', name: 'unrelated-alpha', description: 'nothing shared here at all' },
      { type: 'reference', name: 'unrelated-beta', description: 'still nothing in common with anything' },
    ]);
    const PROMPT = 'deployment path rollback procedure for the staging cluster';
    const payload = { hook_event_name: 'UserPromptSubmit', prompt: PROMPT, cwd, session_id: id };
    b.snapshot();
    // Snapshotted PER SIDE and AFTER the restore: `cpSync` does not preserve timestamps, so
    // the port's bed carries the copy's mtimes and a snapshot taken before the restore would
    // fail the port for the harness's own copy.
    const pyBefore = factsState(factsDir);
    const py = runHook(ctx, 'py', { payload, cwd, home: home(id, 'py') });
    const pyAfter = factsState(factsDir);
    b.restore();
    const ndBefore = factsState(factsDir);
    const nd = runHook(ctx, 'node', { payload, cwd, home: home(id, 'node') });
    const ndAfter = factsState(factsDir);

    // PRECONDITION: the inject branch, with three hits, on both sides. A `skip` or `none`
    // record leaves the files alone for a reason this block is not about.
    if (py.last['action'] !== 'inject' || nd.last['action'] !== 'inject') {
      throw new Error(
        `hooks: inject-no-stamp needs the INJECT branch on both sides and got ` +
          `py=${py.last['action']} node=${nd.last['action']}; the bed's store no longer ` +
          'answers the prompt, so nothing below would be measuring an injection.',
      );
    }
    const recordOf = (r) => ({ action: r.last['action'], hits: r.last['hits'], dropped: r.last['dropped'] });
    cases.push(
      ...literalCases(
        recordOf(py),
        recordOf(nd),
        'inject-no-stamp: precondition — the arm read the store and injected three of five',
        { action: 'inject', hits: 3, dropped: 0 },
      ),
    );
    // Both sides seeded the same five facts, all undated: the state the property is measured
    // against, pinned so a bed that arrived pre-stamped cannot make the cases below vacuous.
    cases.push(
      ...literalCases(
        Object.fromEntries(Object.entries(pyBefore).map(([n, s]) => [n, s.lastRecalled])),
        Object.fromEntries(Object.entries(ndBefore).map(([n, s]) => [n, s.lastRecalled])),
        'inject-no-stamp: precondition — five facts on disk, none of them dated',
        {
          'deployment-rollback.md': 'null',
          'rollback-runbook.md': 'null',
          'staging-cluster-notes.md': 'null',
          'unrelated-alpha.md': 'null',
          'unrelated-beta.md': 'null',
        },
      ),
    );
    // THE PROPERTY, PER SIDE: not one file rewritten, not one mtime moved, not one stamp.
    cases.push(
      ...literalCases(
        factsDiff(pyBefore, pyAfter),
        factsDiff(ndBefore, ndAfter),
        'inject-no-stamp: PINNED PER SIDE: the injection left every fact file byte- and mtime-identical',
        { rewritten: [], mtimeMoved: [], stamped: [] },
      ),
    );
    cases.push(
      ...literalCases(
        pyAfter,
        ndAfter,
        'inject-no-stamp: the five files after the injection are the five files before it, field for field',
        undefined,
      ).map((c, i) => ({ ...c, expected: i === 0 ? pyBefore : ndBefore })),
    );
    // WHAT DID NOT CHANGE: the injected block and the record are the same on both sides,
    // and the same as before this job — the stamp was the only thing taken away.
    cases.push({
      name: 'inject-no-stamp: the injected block on stdout, byte for byte',
      kind: 'bytes',
      expected: py.stdout,
      actual: nd.stdout,
    });
    const injectFields = (r) =>
      Object.fromEntries(Object.entries(r.last).filter(([k]) => !['ts', 'ms'].includes(k)));
    cases.push({
      name: 'inject-no-stamp: the inject record, with only `ts` and `ms` masked',
      kind: 'json',
      expected: injectFields(py),
      actual: injectFields(nd),
    });
    cases.push(
      ...literalCases(
        { bytes: py.last['bytes'], injected: py.last['injected'].map((x) => x.name) },
        { bytes: nd.last['bytes'], injected: nd.last['injected'].map((x) => x.name) },
        'inject-no-stamp: PINNED PER SIDE: the three names injected, in score order, and the block size',
        // 423 is MEASURED off both sides on this bed (2026-09-25), not derived: the header
        // line plus three `[project] [name] (type) description` headers, under the cap.
        { bytes: 423, injected: ['deployment-rollback', 'rollback-runbook', 'staging-cluster-notes'] },
      ),
    );
  }

  // ============================ inject-dedupe: what a context was shown is not shown again
  //
  // job64 / J64-2. Measured 2026-09-25 over a week of the real log: 333 of 598 injections
  // repeated a name already injected earlier in the SAME session, because the arm never
  // consulted the per-session ledger. Now it does: the seen-set lives in
  // `ledger-<session>.json` under `injected[<transcript>]`, so it is forgotten exactly when
  // the window is (PostCompact, SessionStart `compact`, and now SessionStart `clear`). The
  // seen headers are DROPPED, never refilled from rank 4 — what leaves is a subset of what
  // the un-deduped arm sent. Six properties from the unit brief, each pinned PER SIDE against
  // a literal and then the whole sequence compared across sides, on the `inject-no-stamp` bed
  // and one sequence of payloads per side under its own throwaway home:
  //   (a) the same prompt twice in one context: the second emits nothing, `action: suppress`;
  //   (b) another session is not suppressed by the first's injection;
  //   (c) after PostCompact the same context is injected again;
  //   (d) a prompt whose top 3 mixes seen and unseen names emits only the unseen;
  //   (e) SessionStart `clear` forgets, `startup` does not (the control);
  //   (f) a subagent (same session_id, own transcript_path) is not suppressed by the parent,
  //       and the parent is still suppressed afterwards.
  // MUTATION EVIDENCE (2026-09-25) — the seen-set forced empty on BOTH sides (`seen = {}` /
  // `const seen = {}`): (a), (d), (e), (f) and the identity literal go red per side, 10 of
  // 140, while the precondition, (b), (c), the s5 ledger shape and EVERY differential stay
  // green — the symmetric-regression shape, and why the sequence differential alone could
  // never hold this. (b) and (c) pin the "still injected" halves and are green either way;
  // the s5 ledger is still written by the mutant, so its shape is not what catches it; the
  // identity literal is 9 long because exactly 9 of the 12 prompts inject, and the mutant
  // injects 12. On the port alone the port's five literals, the (d) stdout-bytes
  // differential and the sequence differential go red, 7 of 140. Two narrower mutations,
  // (e)'s `clear` reset removed and the seen-set keyed by session instead of transcript, are
  // counted in `.shiftwork/notes-job64/J64-2.md` with the commands.
  {
    const id = 'inject-dedupe';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    seedStore(ctx, join(cwd, '.bantamkit', 'memory'), [
      {
        type: 'project',
        name: 'deployment-rollback',
        description: 'the deployment path rollback procedure for the staging cluster',
      },
      { type: 'project', name: 'staging-cluster-notes', description: 'wiring notes kept about the staging cluster nodes' },
      { type: 'project', name: 'rollback-runbook', description: 'runbook steps when a rollback of the deployment is needed' },
      { type: 'reference', name: 'unrelated-alpha', description: 'nothing shared here at all' },
      { type: 'reference', name: 'unrelated-beta', description: 'still nothing in common with anything' },
    ]);
    // A hits the three deployment/rollback/staging facts (scores 8, 3, 3); C hits
    // `unrelated-alpha` and then two of A's three — measured through `Memory.layered` on this
    // bed, so after A it is the mixed case.
    const A = 'deployment path rollback procedure for the staging cluster';
    const C = 'nothing shared here at all about the staging cluster';
    const A_NAMES = ['deployment-rollback', 'rollback-runbook', 'staging-cluster-notes'];
    b.snapshot();

    const maskStamps = (ledger) => ({
      ...ledger,
      injected: Object.fromEntries(
        Object.entries(ledger.injected ?? {}).map(([t, names]) => [
          t,
          Object.fromEntries(Object.keys(names).map((n) => [n, '<ts>'])),
        ]),
      ),
    });
    const sequence = (side) => {
      const h = home(id, side);
      const seq = [];
      const up = (session, transcript, text) => {
        const r = runHook(ctx, side, {
          payload: { hook_event_name: 'UserPromptSubmit', prompt: text, cwd, session_id: session, transcript_path: transcript },
          cwd,
          home: h,
        });
        seq.push({
          action: r.last['action'],
          hits: r.last['hits'],
          injected: (r.last['injected'] ?? []).map((x) => x.name),
          suppressed: r.last['suppressed'],
          dropped: r.last['dropped'] ?? null,
          bytes: r.last['bytes'] ?? null,
          stdout: dec(r.stdout),
        });
        return r;
      };
      const ev = (payload) => runHook(ctx, side, { payload: { ...payload, cwd }, cwd, home: h });
      up('s1', '/t/s1.jsonl', A); // 0  precondition
      up('s1', '/t/s1.jsonl', A); // 1  (a)
      up('s2', '/t/s2.jsonl', A); // 2  (b)
      ev({ hook_event_name: 'PostCompact', session_id: 's1' });
      up('s1', '/t/s1.jsonl', A); // 3  (c)
      up('s3', '/t/s3.jsonl', A); // 4
      up('s3', '/t/s3.jsonl', C); // 5  (d)
      up('s4', '/t/s4.jsonl', A); // 6
      ev({ hook_event_name: 'SessionStart', source: 'startup', session_id: 's4' });
      up('s4', '/t/s4.jsonl', A); // 7  (e) control
      ev({ hook_event_name: 'SessionStart', source: 'clear', session_id: 's4' });
      up('s4', '/t/s4.jsonl', A); // 8  (e)
      up('s5', '/t/parent.jsonl', A); // 9
      up('s5', '/t/child.jsonl', A); // 10 (f)
      up('s5', '/t/parent.jsonl', A); // 11 (f)
      ev({ hook_event_name: 'SessionStart', source: 'clear', session_id: 's9' });
      const ledgerS5 = JSON.parse(readFileSync(join(h, '.bantamkit', 'hooks', 'ledger-s5.json'), 'utf8'));
      return {
        seq,
        ledgerS5: maskStamps(ledgerS5),
        s9Exists: existsSync(join(h, '.bantamkit', 'hooks', 'ledger-s9.json')),
      };
    };
    const py = sequence('py');
    b.restore();
    const nd = sequence('node');

    // PRECONDITION: the first prompt of a fresh context injects all three on both sides. A
    // `skip` or `none` there would make every "suppress" below vacuous.
    if (py.seq[0].action !== 'inject' || nd.seq[0].action !== 'inject') {
      throw new Error(
        `hooks: inject-dedupe needs the INJECT branch first on both sides and got ` +
          `py=${py.seq[0].action} node=${nd.seq[0].action}; the bed's store no longer answers ` +
          'the prompt, so nothing below would be measuring a suppression.',
      );
    }
    const pick = (s, i, fields) => Object.fromEntries(fields.map((f) => [f, s.seq[i][f]]));
    const RECORD = ['action', 'hits', 'injected', 'suppressed', 'dropped'];
    cases.push(
      ...literalCases(
        pick(py, 0, RECORD),
        pick(nd, 0, RECORD),
        'inject-dedupe: precondition — a fresh context is injected all three, nothing suppressed',
        { action: 'inject', hits: 3, injected: A_NAMES, suppressed: [], dropped: 0 },
      ),
    );
    // (a) THE PROPERTY, PER SIDE: the same prompt again in the same context emits NOTHING,
    // and the record names what was withheld rather than saying `none`.
    cases.push(
      ...literalCases(
        pick(py, 1, [...RECORD, 'stdout']),
        pick(nd, 1, [...RECORD, 'stdout']),
        'inject-dedupe: PINNED PER SIDE (a): the second identical prompt emits nothing and logs `suppress` with the names',
        { action: 'suppress', hits: 3, injected: [], suppressed: A_NAMES, dropped: null, stdout: '' },
      ),
    );
    // (b) another session, unaffected.
    cases.push(
      ...literalCases(
        pick(py, 2, RECORD),
        pick(nd, 2, RECORD),
        'inject-dedupe: PINNED PER SIDE (b): a different session is injected in full',
        { action: 'inject', hits: 3, injected: A_NAMES, suppressed: [], dropped: 0 },
      ),
    );
    // (c) after PostCompact, the same context again.
    cases.push(
      ...literalCases(
        pick(py, 3, RECORD),
        pick(nd, 3, RECORD),
        'inject-dedupe: PINNED PER SIDE (c): after PostCompact the same context is injected again',
        { action: 'inject', hits: 3, injected: A_NAMES, suppressed: [], dropped: 0 },
      ),
    );
    // (d) the mixed case: only the unseen header leaves; the seen two are withheld, not
    // refilled; and `hits == injected + dropped + suppressed`. 194 is MEASURED on both sides
    // (2026-09-25): the header line plus the one `[project] [unrelated-alpha] (reference) …`.
    cases.push(
      ...literalCases(
        pick(py, 5, [...RECORD, 'bytes']),
        pick(nd, 5, [...RECORD, 'bytes']),
        'inject-dedupe: PINNED PER SIDE (d): a mixed pick emits only the unseen header, and withholds the seen two',
        {
          action: 'inject',
          hits: 3,
          injected: ['unrelated-alpha'],
          suppressed: ['staging-cluster-notes', 'deployment-rollback'],
          dropped: 0,
          bytes: 194,
        },
      ),
    );
    cases.push({
      name: 'inject-dedupe (d): the mixed block on stdout, byte for byte',
      kind: 'bytes',
      expected: Buffer.from(py.seq[5].stdout, 'utf8'),
      actual: Buffer.from(nd.seq[5].stdout, 'utf8'),
    });
    // (e) `clear` forgets; `startup` between two identical prompts is the CONTROL — without
    // it a SessionStart that always reset would pass the `clear` half alone.
    const actions = (s, ...i) => i.map((k) => s.seq[k].action);
    cases.push(
      ...literalCases(
        actions(py, 6, 7, 8),
        actions(nd, 6, 7, 8),
        'inject-dedupe: PINNED PER SIDE (e): inject, then suppressed across `startup`, then injected again after `clear`',
        ['inject', 'suppress', 'inject'],
      ),
    );
    // (f) parent, subagent, parent: the subagent is not suppressed by the parent's injection
    // and the parent still is by its own.
    cases.push(
      ...literalCases(
        actions(py, 9, 10, 11),
        actions(nd, 9, 10, 11),
        'inject-dedupe: PINNED PER SIDE (f): a subagent transcript is injected; the parent is still suppressed after it',
        ['inject', 'inject', 'suppress'],
      ),
    );
    const s5 = {
      reads: {},
      injected: {
        '/t/parent.jsonl': Object.fromEntries(A_NAMES.map((n) => [n, '<ts>'])),
        '/t/child.jsonl': Object.fromEntries(A_NAMES.map((n) => [n, '<ts>'])),
      },
    };
    cases.push(
      ...literalCases(
        py.ledgerS5,
        nd.ledgerS5,
        'inject-dedupe: PINNED PER SIDE (f): one ledger file for the session, one seen-set per transcript, stamps masked',
        s5,
      ),
    );
    // The record arithmetic closes on every inject record of the sequence.
    const identity = (s) =>
      s.seq.filter((r) => r.action === 'inject').map((r) => r.hits === r.injected.length + r.dropped + r.suppressed.length);
    cases.push(
      ...literalCases(
        identity(py),
        identity(nd),
        'inject-dedupe: PINNED PER SIDE: hits == injected + dropped + suppressed on every inject record',
        Array(9).fill(true),
      ),
    );
    cases.push(
      ...literalCases(
        py.s9Exists,
        nd.s9Exists,
        'inject-dedupe: a `clear` with no ledger under the session creates none',
        false,
      ),
    );
    // And the two sides ran the identical sequence: every record field and every byte of
    // stdout, twelve prompts long.
    cases.push({
      name: 'inject-dedupe: the twelve-prompt sequence, record by record and byte by byte, is the same on both sides',
      kind: 'json',
      expected: py.seq,
      actual: nd.seq,
    });
    cases.push({
      name: 'inject-dedupe: the s5 ledger, stamps masked, is the same file on both sides',
      kind: 'json',
      expected: py.ledgerS5,
      actual: nd.ledgerS5,
    });
  }

  // ======================= dream-fingerprint: a re-dated fact does not re-arm the preview
  //
  // job64 / J64-3. The Stop arm previews the cross-layer dream once per change to either
  // layer, gated by a fingerprint of `facts/*.md` in `dream-state.json`. Until this unit that
  // fingerprint was `name + size + mtimeMs`, and every recall rewrites one frontmatter line
  // (`last_recalled:`) and the mtime — so a session of recalls re-armed the preview on every
  // Stop (measured 2026-09-25 over a week of the real log: 103 of 236 previews reported the
  // identical `wouldMerge 14 / wouldConsume 14`). Size is no signal either: J64-0 measured a
  // same-day re-stamp moving the mtime ALONE. The fingerprint is now a sha256 over each fact's
  // name and its bytes with that one line dropped, identical on both sides.
  //
  // Six Stops per side on one three-fact project store (restored between sides) and a
  // one-fact profile store per side, with a change between each pair:
  //   S1 first look                       -> dream-preview
  //   (a1) an explicit recall through the reference store (null -> today, bytes + mtime move)
  //   S2                                  -> dream-skip unchanged, same fingerprint
  //   (a2) the `last_recalled:` line re-dated to another day
  //   S3                                  -> dream-skip unchanged, same fingerprint
  //   (a3) the mtime alone (utimes)
  //   S4                                  -> dream-skip unchanged, same fingerprint
  //   (b)  the body edited
  //   S5                                  -> dream-preview, fingerprint moved
  //   (c)  a fact added
  //   S6                                  -> dream-preview, fingerprint moved again
  // The (a1) diff is pinned as a precondition so the three skips cannot be vacuous: the
  // recall really rewrote the file. MUTATION EVIDENCE (2026-09-25) — the stat fields put back
  // on both sides (`size + mtimeMs` instead of the content digest): the two PINNED PER SIDE
  // literals go red per side, 4 cases, while the precondition and the sequence differential
  // stay green — the symmetric-regression shape, and why the differential alone could never
  // hold this. Counts and commands in `.shiftwork/notes-job64/J64-3.md`.
  {
    const id = 'dream-fingerprint';
    const b = bed(join(root, id));
    const cwd = join(b.root, 'cwd');
    mkdirSync(cwd, { recursive: true });
    const store = join(cwd, '.bantamkit', 'memory');
    const factsDir = join(store, 'facts');
    seedStore(ctx, store, [
      { type: 'project', name: 'shared-ruling', description: 'a ruling both layers carry a copy of' },
      { type: 'project', name: 'recalled-often', description: 'the fact the operator recalls every turn' },
      { type: 'reference', name: 'left-alone', description: 'nothing here answers any query' },
    ]);
    const transcript = join(cwd, 'transcript.jsonl');
    writeFileSync(transcript, '');
    b.snapshot();
    const fact = join(factsDir, 'recalled-often.md');
    const REDATED = "last_recalled: '2020-01-01'";

    const sequence = (side) => {
      const h = home(id, side);
      // The profile layer is under the per-side home: one shared name, so the preview has
      // something to report and the child's status is `previewed` on every preview.
      seedStore(ctx, join(h, '.bantamkit', 'memory'), [
        { type: 'project', name: 'shared-ruling', description: 'the profile copy of the ruling' },
      ]);
      const payload = { hook_event_name: 'Stop', cwd, session_id: id, transcript_path: transcript };
      const state = join(h, '.bantamkit', 'hooks', 'dream-state.json');
      const fingerprintOf = () => (existsSync(state) ? JSON.parse(readFileSync(state, 'utf8'))['fingerprint'] : null);
      const steps = [];
      const stop = (label) => {
        const r = runHook(ctx, side, { payload, cwd, home: h });
        const rec = r.records.filter((x) => String(x['action']).startsWith('dream')).pop() ?? {};
        steps.push({ label, action: rec['action'], reason: rec['reason'] ?? null, fingerprint: fingerprintOf() });
      };
      stop('S1 first look');
      const a1Before = factsState(factsDir);
      recallStore(ctx, store, 'the operator recalls every turn', 'recalled-often');
      const a1 = factsDiff(a1Before, factsState(factsDir));
      stop('S2 after an explicit recall');
      writeFileSync(fact, readFileSync(fact, 'utf8').replace(/^last_recalled: .*$/m, REDATED));
      stop('S3 after re-dating last_recalled');
      const later = new Date(statSync(fact).mtimeMs + 1000);
      utimesSync(fact, later, later);
      stop('S4 after a touch');
      writeFileSync(fact, readFileSync(fact, 'utf8').replace(/\nbody\n$/, '\na new body\n'));
      stop('S5 after a body edit');
      seedStore(ctx, store, [{ type: 'reference', name: 'brand-new', description: 'written after the last look' }]);
      stop('S6 after a fact was added');
      const fp = steps.map((s) => s.fingerprint);
      return {
        steps,
        a1,
        bodyEdited: /a new body/.test(readFileSync(fact, 'utf8')),
        movement: {
          sameAfterRecall: fp[1] === fp[0],
          sameAfterRedate: fp[2] === fp[0],
          sameAfterTouch: fp[3] === fp[0],
          movedOnBodyEdit: fp[4] !== fp[0],
          movedOnAdd: fp[5] !== fp[4],
        },
      };
    };
    const py = sequence('py');
    b.restore();
    const nd = sequence('node');

    // PRECONDITION: the first look previewed on both sides, the recall really rewrote the
    // fact (bytes, mtime and the date all moved), and the body edit landed.
    const pre = (s) => ({ first: s.steps[0].action, a1: s.a1, bodyEdited: s.bodyEdited });
    cases.push(
      ...literalCases(pre(py), pre(nd), 'dream-fingerprint: precondition — S1 previewed, the recall re-dated the file, the body edit landed', {
        first: 'dream-preview',
        a1: { rewritten: ['recalled-often.md'], mtimeMoved: ['recalled-often.md'], stamped: ['recalled-often.md'] },
        bodyEdited: true,
      }),
    );
    // THE PROPERTY, PER SIDE: three re-datings are three skips, and the two content changes
    // are two previews.
    const actionsOf = (s) => s.steps.map((x) => x.action + (x.reason ? `/${x.reason}` : ''));
    cases.push(
      ...literalCases(
        actionsOf(py),
        actionsOf(nd),
        'dream-fingerprint: PINNED PER SIDE: a recall, a re-date and a touch each skip; a body edit and a new fact each preview',
        [
          'dream-preview',
          'dream-skip/unchanged',
          'dream-skip/unchanged',
          'dream-skip/unchanged',
          'dream-preview',
          'dream-preview',
        ],
      ),
    );
    cases.push(
      ...literalCases(
        py.movement,
        nd.movement,
        'dream-fingerprint: PINNED PER SIDE: the stored fingerprint is unmoved by re-dating and moved by content',
        { sameAfterRecall: true, sameAfterRedate: true, sameAfterTouch: true, movedOnBodyEdit: true, movedOnAdd: true },
      ),
    );
    // The whole sequence, side to side, with the hex masked: the profile root's path is in
    // the hash and the two homes differ, so the hexes are not comparable across sides.
    const masked = (s) => s.steps.map(({ label, action, reason }) => ({ label, action, reason }));
    cases.push({
      name: 'dream-fingerprint: the six-Stop sequence is the same on both sides',
      kind: 'json',
      expected: masked(py),
      actual: masked(nd),
    });
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
