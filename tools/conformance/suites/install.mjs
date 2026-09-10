/**
 * install — which install shape is running, over fixtures BOTH runtimes are handed.
 *
 * WHY THIS SUITE EXISTS, AND WHAT IT REPLACED. `build_identity` reports `install_shape`,
 * `install_source` and `install_source_exists`, and the obvious way to compare them is to
 * ask two live servers. That comparison is worthless, and it was measured to be worthless:
 * at `c9372ca` the harness's reference ran from an editable install of `runtime-py`
 * (`linked`, an origin that exists, `unavailable == ["git_commit"]`) and its port ran from
 * the checkout (`checkout`, no origin at all, three names in `unavailable`). Same code, two
 * ENVIRONMENTS, and a red run that looked exactly like a code difference. Worse, it would
 * have looked different again on a colleague's machine, and identical on a machine where
 * both were `pip install`ed and `npm i`ed — a case whose colour is decided by how the
 * developer set their laptop up is not an instrument.
 *
 * So the shape is not read off the machine here. Every scenario below builds BOTH halves of
 * a matched install — a real `.dist-info` with a real `direct_url.json` for the reference, a
 * real `node_modules` with npm's real hidden lockfile for the port — and hands each side its
 * own half of the SAME shape. A difference in the answer is then a difference in the code,
 * which is the only kind this repository can act on.
 *
 * THE ORIGINS ARE SHARED ON PURPOSE. Both halves of a scenario record the same absolute
 * path, taken from one `origins/` directory beside the fixtures. That buys the strongest
 * comparison available: `install_source` and the whole `install-source-missing` sentence are
 * compared BYTE FOR BYTE, path included, rather than relativised into agreement. A suite
 * that scrubbed the path would be green for a runtime that printed the wrong one.
 *
 * WHAT IS RULED, AND WHY EACH RULING HAS A COMPANION. Four differences are deliberate and
 * carried in `docs/porting.md`. Three of them are a REFUSAL on one side, and a `ruling:` case
 * only ever proves the two sides still DIFFER — never that either still refuses. So each
 * refusal-shaped ruling is accompanied by a non-ruled case that compares the refusal BIT, and
 * by per-side literals, because a differential over a bit is blind to both sides losing it at
 * once.
 *
 * NOTHING HERE READS THE MACHINE'S OWN INSTALL. Not once. The only fact about this laptop
 * that reaches a case is the scratch directory the fixtures were built in, and that is
 * identical on both sides by construction.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'install';
export const summary = 'install-shape self-diagnosis (AS-7a), over matched constructed installs';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'install_ref.py');

/** The five words, spelled and ordered as both runtimes declare them. */
const VOCABULARY = ['registry', 'local-file', 'linked', 'checkout', 'ephemeral'];

const writeFile = (path, text) => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, 'utf8');
};
const writeJson = (path, value) => writeFile(path, `${JSON.stringify(value, null, 2)}\n`);

/** npm records a `file:` origin as a RAW path relative to the project, POSIX-separated. */
const fileSpec = (project, target) => `file:${relative(project, target).split(sep).join('/')}`;
const bareSpec = (project, target) => relative(project, target).split(sep).join('/');

// ------------------------------------------------------------------ the two fixture halves

/**
 * The reference half: one real `.dist-info` beside the tree it claims to own.
 *
 * `METADATA` and `RECORD` are written because `importlib.metadata` reads them and a
 * dist-info without them is discovered as a distribution with no name — a case the resolver
 * handles, and not the case any scenario here is about. `directUrl: null` writes no
 * `direct_url.json` at all, which is PEP 610's signal for "came from an index".
 */
function pythonInstalled(root, { directUrl = null, running = null } = {}) {
  const site = join(root, 'site-packages');
  const distInfo = join(site, 'bantamkit-0.25.0.dist-info');
  writeFile(join(distInfo, 'METADATA'), 'Metadata-Version: 2.1\nName: bantamkit\nVersion: 0.25.0\n');
  writeFile(join(distInfo, 'RECORD'), 'bantamkit/__init__.py,,\n');
  writeFile(join(distInfo, 'INSTALLER'), 'pip\n');
  if (directUrl !== null) writeFile(join(distInfo, 'direct_url.json'), JSON.stringify(directUrl));
  const importable = running ?? join(site, 'bantamkit', '__init__.py');
  writeFile(importable, '__version__ = "0.25.0"\n');
  return { site, running: importable };
}

/** The reference half with no installer record anywhere: a tree on the import path. */
function pythonCheckout(root) {
  const site = join(root, 'site-packages');
  mkdirSync(site, { recursive: true });
  const running = join(root, 'tree', 'bantamkit', '__init__.py');
  writeFile(running, '__version__ = "0.25.0"\n');
  return { site, running };
}

/**
 * The port half: `<project>/node_modules/bantamkit-mcp`, with npm's hidden lockfile.
 *
 * `entry: null` writes NO `.package-lock.json` at all — the global-install shape, where the
 * ABSENCE is the evidence. `npx: true` adds the `_npx` marker npm writes into the cache
 * project's own `package.json`, which is a record and not a directory name.
 */
function nodeInstalled(project, { entry = null, npx = false } = {}) {
  const packageRoot = join(project, 'node_modules', 'bantamkit-mcp');
  writeJson(join(packageRoot, 'package.json'), { name: 'bantamkit-mcp', version: '0.25.0' });
  const running = join(packageRoot, 'dist', 'mcp', 'identity.js');
  writeFile(running, '// the file that is running\n');
  if (entry !== null) {
    writeJson(join(project, 'node_modules', '.package-lock.json'), {
      name: 'proj',
      lockfileVersion: 3,
      requires: true,
      packages: { 'node_modules/bantamkit-mcp': entry },
    });
  }
  writeJson(
    join(project, 'package.json'),
    npx
      ? { dependencies: { 'bantamkit-mcp': 'file:../x.tgz' }, _npx: { packages: ['./x.tgz'] } }
      : { name: 'proj', version: '1.0.0' },
  );
  return { running, entry: null };
}

/** The port half with no installer record: a package tree nobody put in a `node_modules`. */
function nodeCheckout(root) {
  writeJson(join(root, 'package.json'), { name: 'bantamkit-mcp', version: '0.25.0' });
  const running = join(root, 'dist', 'mcp', 'identity.js');
  writeFile(running, '// the file that is running\n');
  return { running, entry: null };
}

/** The port half with no `package.json` above the running file at all. */
function nodeUnowned(root) {
  const running = join(root, 'nowhere', 'identity.js');
  writeFile(running, '// the file that is running\n');
  return { running, entry: null };
}

// ------------------------------------------------------------------------- the scenarios

/**
 * Build every matched fixture under one root and return the manifest both sides read.
 *
 * The origins live in one directory shared by the two halves, so a scenario's recorded path
 * is the SAME STRING on both sides and every sentence carrying it is byte-comparable.
 */
function buildScenarios(root) {
  const origins = join(root, 'origins');
  const liveArchive = join(origins, 'bantamkit-0.25.0.tar.gz');
  writeFile(liveArchive, 'not really an archive, and nothing here opens it\n');
  const liveTree = join(origins, 'src-tree');
  writeFile(join(liveTree, 'marker.txt'), 'the tree a linked install still reads\n');
  // Never created. This is AS-7's measured incident: a tarball under a scratch directory
  // that no longer exists, recorded by an installer that will never look at it again.
  const goneArchive = join(origins, 'gone', 'bantamkit-mcp-0.25.0.tgz');
  // A regular file with a path underneath it: the origin is not merely absent, the lookup
  // hits ENOTDIR. Both runtimes must still call that "not there" rather than "could not look".
  const notADirectory = join(origins, 'a-file');
  writeFile(notADirectory, 'a regular file\n');
  const underAFile = join(notADirectory, 'bantamkit-0.25.0.tgz');

  const scenarios = [];
  const add = (id, py, node) => scenarios.push({ id, py, node });
  const py = (id, options) => pythonInstalled(join(root, 'py', id), options);
  const nd = (id, options) => nodeInstalled(join(root, 'node', id), options);
  const project = (id) => join(root, 'node', id);
  const url = (path) => pathToFileURL(path).href;

  // --------------------------------------------------------------- the five shapes agree

  // No `direct_url.json` on one side, no lockfile record on the other. Both absences are
  // positive evidence, and both resolve to the one shape with a registry to reinstall from.
  add('registry', py('registry'), nd('registry', { entry: null }));

  add(
    'local-file-present',
    py('local-file-present', { directUrl: { url: url(liveArchive), archive_info: {} } }),
    nd('local-file-present', { entry: { version: '0.25.0', resolved: fileSpec(project('local-file-present'), liveArchive) } }),
  );

  // THE MEASURED INCIDENT, on both sides at once.
  add(
    'local-file-gone',
    py('local-file-gone', { directUrl: { url: url(goneArchive), archive_info: {} } }),
    nd('local-file-gone', { entry: { version: '0.25.0', resolved: fileSpec(project('local-file-gone'), goneArchive) } }),
  );

  // The same finding reached through a different errno.
  add(
    'local-file-under-a-file',
    py('local-file-under-a-file', { directUrl: { url: url(underAFile), archive_info: {} } }),
    nd('local-file-under-a-file', { entry: { version: '0.25.0', resolved: fileSpec(project('local-file-under-a-file'), underAFile) } }),
  );

  // An editable install here, a `link: true` lockfile entry there. The reference's editable
  // branch is ownership by CONTAINMENT, so the running file has to sit inside the tree.
  add(
    'linked',
    py('linked', {
      directUrl: { url: url(liveTree), dir_info: { editable: true } },
      running: join(liveTree, 'bantamkit', '__init__.py'),
    }),
    nd('linked', { entry: { resolved: bareSpec(project('linked'), liveTree), link: true } }),
  );

  add('checkout', pythonCheckout(join(root, 'py', 'checkout')), nodeCheckout(join(root, 'node', 'checkout', 'tree')));

  // A `git+https:` origin is neither an index nor a path on EITHER side, and both refuse
  // with the same sentence. This is the refusal-bit companion the invariant demands: it is
  // the case that goes red if one side quietly stops refusing, which no `ruling:` can see.
  const gitOrigin = 'git+https://github.com/example/bantamkit.git@abc123def456';
  add(
    'git-origin',
    py('git-origin', { directUrl: { url: gitOrigin, vcs_info: { vcs: 'git', commit_id: 'abc123def456' } } }),
    nd('git-origin', { entry: { version: '0.25.0', resolved: gitOrigin } }),
  );

  // ------------------------------------------------------- the three deliberate divergences

  // D2: an `http(s)` origin. The reference refuses it; on the port the registry IS an https
  // URL, so the same record is `registry`.
  const httpOrigin = 'https://registry.npmjs.org/bantamkit-mcp/-/bantamkit-mcp-0.25.0.tgz';
  add(
    'http-origin',
    py('http-origin', { directUrl: { url: httpOrigin, archive_info: {} } }),
    nd('http-origin', { entry: { version: '0.25.0', resolved: httpOrigin } }),
  );

  // D1: an `npx` cache filled from a tarball that is gone. Shape is the ENVIRONMENT and the
  // origin is the ORIGIN, and the measured incident is both at once — so the port answers
  // `ephemeral` while the origin survives in `install_source` and the condition still fires.
  // The reference has no such record to read and answers `local-file` for the same origin.
  add(
    'npx-cache-gone',
    py('npx-cache-gone', { directUrl: { url: url(goneArchive), archive_info: {} } }),
    nd('npx-cache-gone', {
      entry: { version: '0.25.0', resolved: fileSpec(project('npx-cache-gone'), goneArchive) },
      npx: true,
    }),
  );

  // D3: no `package.json` anywhere above the running file. The reference does not need one
  // and falls through to `checkout`; the port cannot identify the package at all and refuses.
  add('unowned-file', pythonCheckout(join(root, 'py', 'unowned-file')), nodeUnowned(join(root, 'node', 'unowned-file')));

  return { scenarios, origins: { liveArchive, liveTree, goneArchive, underAFile } };
}

// ------------------------------------------------------------------------------ comparison

/** Compare each side to a typed constant — the only shape a symmetric regression reddens. */
function literalCases(pySide, nodeSide, label, expected, kind = 'json') {
  return [
    { name: `${label} — the reference`, kind, expected, actual: pySide },
    { name: `${label} — the port`, kind, expected, actual: nodeSide },
  ];
}

export async function run(ctx) {
  const identity = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'mcp', 'identity.js')).href);
  const status = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'mcp', 'status.js')).href);

  const root = join(ctx.scratch, 'install');
  const { scenarios, origins } = buildScenarios(root);

  const nodeAnswers = {};
  for (const scenario of scenarios) {
    try {
      const install = identity.deriveInstall(scenario.node.running, scenario.node.entry);
      const condition = status.installSourceCondition(install);
      const stat = install.source === null ? null : identity.originStat(install.source);
      nodeAnswers[scenario.id] = {
        refused: false,
        shape: install.shape,
        source: install.source,
        source_reason: install.sourceReason,
        source_exists: stat === null ? null : stat.present,
        condition: condition === null ? null : { key: condition.key, sentence: condition.sentence },
      };
    } catch (error) {
      if (!(error instanceof identity.Undetermined)) throw error;
      nodeAnswers[scenario.id] = { refused: true, refusal: error.message };
    }
  }

  const reference = ctx.runPython(REF, { scenarios });
  const pyAnswers = reference.answers;

  const cases = [];
  const notes = [];
  const pair = (id) => [pyAnswers[id], nodeAnswers[id]];

  // ------------------------------------------------------------------ the closed vocabulary

  cases.push({
    name: 'install: the five words are the five words, in the same order',
    kind: 'json',
    expected: reference.shapes,
    actual: [...identity.INSTALL_SHAPES],
  });
  // The vocabulary is spelled out twice, once per runtime, so a word changed on both sides at
  // once leaves the case above green. These two are what see that.
  cases.push(...literalCases(reference.shapes, [...identity.INSTALL_SHAPES], 'install: the vocabulary against a literal', VOCABULARY));

  // --------------------------------------------- everything the two runtimes must agree on

  const AGREE = [
    'registry',
    'local-file-present',
    'local-file-gone',
    'local-file-under-a-file',
    'linked',
    'checkout',
    'git-origin',
  ];
  for (const id of AGREE) {
    const [py, nd] = pair(id);
    // The whole answer, field for field, path included — not a summary of it. ONE
    // substitution, on ONE scenario: `registry`'s `source_reason` is `docs/porting.md`'s row
    // D4, so both sides' copies are replaced by the same marker here and the sentences
    // themselves are compared — ruled, and then unruled on the halves the ruling does not
    // license — in the divergence block below. Every other field of every other scenario
    // reaches this comparison as the runtime produced it.
    const compared = (answer) => (id === 'registry' ? { ...answer, source_reason: '<compared in the D4 block>' } : answer);
    cases.push({
      name: `install: ${id} — the same shape, origin, reason and condition on both sides`,
      kind: 'json',
      expected: compared(py),
      actual: compared(nd),
    });
  }

  // The condition's KEY, pinned per side, because both sides carry the token as a literal and
  // a differential cannot see it renamed on both at once.
  cases.push(
    ...literalCases(
      pyAnswers['local-file-gone'].condition?.key ?? null,
      nodeAnswers['local-file-gone'].condition?.key ?? null,
      'install: the condition key against a literal',
      'install-source-missing',
      'string',
    ),
  );

  // THE MEASURED INCIDENT, asserted as a property rather than as a repeat of the diff above:
  // the sentence names the path that is gone. A condition that fired but said "an origin is
  // missing" would satisfy every comparison in this file and be worthless to the operator.
  cases.push(
    ...literalCases(
      `${pyAnswers['local-file-gone'].condition?.sentence?.includes(origins.goneArchive)}`,
      `${nodeAnswers['local-file-gone'].condition?.sentence?.includes(origins.goneArchive)}`,
      'install: the dangling-origin sentence names the path that is gone',
      'true',
      'string',
    ),
  );
  // And the remedy is a reinstall BY NAME rather than an update run — the J46-4 shape, which
  // exits 0 having changed nothing where a dangling `file:` install lives.
  cases.push(
    ...literalCases(
      `${/reinstall bantamkit by name from a package registry/.test(pyAnswers['local-file-gone'].condition?.sentence ?? '')}`,
      `${/reinstall bantamkit by name from a package registry/.test(nodeAnswers['local-file-gone'].condition?.sentence ?? '')}`,
      'install: the remedy is a reinstall by name, never an update in place',
      'true',
      'string',
    ),
  );

  // A live origin is not a finding, on either side. The pair is what proves the condition is
  // conditional; the case above alone would be satisfied by a condition that always fires.
  cases.push(
    ...literalCases(
      `${pyAnswers['local-file-present'].condition}`,
      `${nodeAnswers['local-file-present'].condition}`,
      'install: a live origin fires nothing',
      'null',
      'string',
    ),
  );

  // -------------------------------------------------------- the refusal BIT, before any word

  // A ruling proves the two sides still DIFFER. It cannot prove either still refuses, and
  // three of the four rows in `docs/porting.md` are a refusal on one side. This is the bit.
  //
  // Two cases, and the split is deliberate. The differential covers every scenario the two
  // runtimes are supposed to answer the same way about — including `git-origin`, where both
  // refuse — and it is NOT narrowed around the ruled pair: `http-origin` and `unowned-file`
  // are held out because they are the divergence itself, and they are pinned per side just
  // below, against a literal, where a differential could never see them at all.
  const RULED_REFUSALS = new Set(['http-origin', 'unowned-file']);
  const refusalBits = (answers) =>
    Object.fromEntries(scenarios.filter((s) => !RULED_REFUSALS.has(s.id)).map((s) => [s.id, answers[s.id].refused === true]));
  cases.push({
    name: 'install: which scenarios refuse — the bit, not the sentence',
    kind: 'json',
    expected: refusalBits(pyAnswers),
    actual: refusalBits(nodeAnswers),
  });
  const bitsOf = (answers) => ({
    'git-origin': answers['git-origin'].refused,
    'http-origin': answers['http-origin'].refused,
    'unowned-file': answers['unowned-file'].refused,
  });
  cases.push({
    name: 'install: the three refusal bits against a literal — the reference',
    kind: 'json',
    expected: { 'git-origin': true, 'http-origin': true, 'unowned-file': false },
    actual: bitsOf(pyAnswers),
  });
  cases.push({
    name: 'install: the three refusal bits against a literal — the port',
    kind: 'json',
    expected: { 'git-origin': true, 'http-origin': false, 'unowned-file': true },
    actual: bitsOf(nodeAnswers),
  });

  // ------------------------------------------------------------- the four ruled divergences

  // D1 — the environment word.
  cases.push({
    name: 'install: an npx cache filled from a tarball is `ephemeral` on the port and `local-file` on the reference',
    kind: 'string',
    expected: pyAnswers['npx-cache-gone'].shape,
    actual: nodeAnswers['npx-cache-gone'].shape,
    ruling:
      'RULED DIFFERENT, and carried in `docs/porting.md`. npm writes an `_npx` marker into ' +
      "the cache project's own `package.json`, so an ephemeral environment is a RECORD the " +
      'port can read. `pipx run` and `uvx` leave no equivalent — telling one of their ' +
      'environments from an ordinary venv would mean pattern-matching cache directory names, ' +
      'which is a guess, and this surface does not guess. The word is declared in BOTH ' +
      'vocabularies so a consumer handles one set of five. Note what does NOT differ: the ' +
      'origin survives the environment word, so `install_source`, `install_source_exists` and ' +
      'the whole condition sentence are compared unruled in the case below.',
  });
  // The companion, and it is the half that matters: the environment word did not eat the
  // finding. The measured incident is BOTH at once — an npx cache filled from a tarball that
  // is gone — so the condition must still fire and still name the path on both sides.
  cases.push({
    name: 'install: the npx cache keeps the origin the environment word did not replace',
    kind: 'json',
    expected: {
      source: pyAnswers['npx-cache-gone'].source,
      source_exists: pyAnswers['npx-cache-gone'].source_exists,
      condition: pyAnswers['npx-cache-gone'].condition,
    },
    actual: {
      source: nodeAnswers['npx-cache-gone'].source,
      source_exists: nodeAnswers['npx-cache-gone'].source_exists,
      condition: nodeAnswers['npx-cache-gone'].condition,
    },
  });

  // D2 — an http(s) origin: a refusal on one side, a shape on the other.
  cases.push({
    name: 'install: an http(s) origin is refused by the reference and is `registry` on the port',
    kind: 'string',
    expected: pyAnswers['http-origin'].refusal,
    actual: nodeAnswers['http-origin'].shape,
    ruling:
      'RULED DIFFERENT, and carried in `docs/porting.md`. PEP 610 records an http archive as ' +
      'a direct URL that is not a path, and the reference will not round it to a word. On the ' +
      'port the npm registry IS an https URL, and telling a published tarball URL from the ' +
      'configured index would mean knowing which index was configured — a guess. Either way ' +
      'the origin is REMOTE, so it can never be the dangling-local-path defect this surface ' +
      'exists for, and both routes out are a reinstall from a name or from that same URL. ' +
      'The refusal BIT is compared unruled above, because this case would stay green if the ' +
      'reference stopped refusing and started answering some other word.',
  });

  // D3 — no `package.json` above the running file.
  cases.push({
    name: 'install: a running file no package.json owns is `checkout` on the reference and refused by the port',
    kind: 'string',
    expected: pyAnswers['unowned-file'].shape,
    actual: nodeAnswers['unowned-file'].refusal,
    ruling:
      'RULED DIFFERENT, and carried in `docs/porting.md`. The reference identifies the package ' +
      'from the DISTRIBUTIONS on `sys.path` and needs no manifest beside the running file, so ' +
      'the absence of any installer record is positive evidence of a checkout. The port has no ' +
      'equivalent index: without a `package.json` above the running file it cannot name the ' +
      'package at all, and a `checkout` answered there would be a guess about which package ' +
      'this even is. The refusal BIT is compared unruled above.',
  });

  // D4 — the `registry` reason, one clause apart.
  cases.push({
    name: 'install: the registry reason names PEP 610 on the reference and npm on the port',
    kind: 'string',
    expected: pyAnswers['registry'].source_reason,
    actual: nodeAnswers['registry'].source_reason,
    ruling:
      'RULED DIFFERENT, one clause, and carried in `docs/porting.md`. The first clause and the ' +
      'closing sentence are byte-identical; the middle names the MECHANISM that makes an ' +
      'absence evidence, and the two mechanisms are different files written by different ' +
      'installers. Copying the reference sentence verbatim would have a Node server citing ' +
      'PEP 610, which is how `git_commit` diverged on a noun. The two halves that must NOT ' +
      'drift are compared unruled below.',
  });
  // The halves the ruling does not license: same first clause, same closing sentence.
  const clauses = (reason) => [reason.split(':')[0], reason.split('. ').slice(-1)[0]];
  cases.push({
    name: 'install: the registry reason opens and closes identically on both sides',
    kind: 'json',
    expected: clauses(pyAnswers['registry'].source_reason),
    actual: clauses(nodeAnswers['registry'].source_reason),
  });

  // ------------------------------------------------------------------------------- notes

  notes.push(
    `${scenarios.length} matched installs built under ${root}; every origin path is shared by the two halves, so every sentence is compared with its path in it`,
  );
  notes.push(
    "the machine's OWN install is not read by any case here, deliberately: the harness does " +
      'not install its two sides alike, so a live `build_identity` comparison of these three ' +
      'fields compares environments and not code — see the header, and `wire`’s own note',
  );
  notes.push(`the incident sentence (the port): ${JSON.stringify(nodeAnswers['local-file-gone'].condition?.sentence ?? null)}`);
  notes.push(
    `shapes answered — reference ${JSON.stringify(
      Object.fromEntries(scenarios.map((s) => [s.id, pyAnswers[s.id].refused ? 'REFUSED' : pyAnswers[s.id].shape])),
    )}`,
  );
  notes.push(
    `shapes answered — port      ${JSON.stringify(
      Object.fromEntries(scenarios.map((s) => [s.id, nodeAnswers[s.id].refused ? 'REFUSED' : nodeAnswers[s.id].shape])),
    )}`,
  );

  return { cases, notes };
}
