/**
 * The npm README and the PyPI README do not hand a reader the other package's commands.
 *
 * THE NODE HALF of `runtime-py/tests/test_readme_separation.py`. That file carries the full
 * reasoning — what ships where, the measured leak table, RULING S3.1 (key on RUNNABILITY, not
 * on mention), RULING S3.2 (a table cell is an instruction too) and what is deliberately left
 * legal. Read it before changing either. This file holds the same property over the same two
 * files with the same forbidden sets.
 *
 * WHY IT EXISTS SEPARATELY. `runtime-ts/README.md` IS the npm landing page — npm always
 * includes `README.md` from the package root regardless of `files`, the same rule
 * `packaging.test.mjs` records for `package.json` — and the npm release gate is `npm test`,
 * which does not run pytest. A gate for this page that only ran on the Python side would let
 * `npm publish` ship a page that hands an `npx` reader three `pip` commands, which is exactly
 * what 0.35.3 did. So the gate lands on both sides, per RULING S3.3, and there is no
 * `docs/porting.md` divergence row to write.
 *
 * It reads tracked markdown rather than a runtime surface, so it has no conformance case: the
 * two sides are held equal by being the same assertions over the same bytes, and either one
 * going red is the same red.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const NPM_README = join(REPO_ROOT, 'runtime-ts', 'README.md');
const PYPI_README = join(REPO_ROOT, 'runtime-py', 'README.md');
const ROOT_README = join(REPO_ROOT, 'README.md');

// Same fence handling as the Python side and as test_doc_commands_gate.py.
const FENCE = /^(`{3,})\s*([^\s`]*)/;
const SHELL_INFO = new Set(['bash', 'sh', 'shell', 'console', 'zsh']);
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|[\s:|-]+\|\s*$/;
const CODE_SPAN = /`([^`\n]+)`/g;

/** Commands that install, upgrade or launch the PYTHON package. Forbidden on the npm page. */
const PYTHON_PACKAGE_COMMANDS = [
  [/\bpipx\b/, 'pipx'],
  [/\bpip3?\s+(install|download|wheel|uninstall)\b/, 'pip install/download/wheel'],
  [/\bpython3?\s+-m\s+pip\b/, 'python -m pip'],
  [/\bpython3?\s+-m\s+venv\b/, 'python -m venv'],
  [/\bpython3?\s+-m\s+bantamkit\b/, 'python -m bantamkit...'],
  [/\buv\s+(tool|pip)\b/, 'uv tool/uv pip'],
  [/\/bin\/bantamkit-mcp\b/, "a venv's bin/bantamkit-mcp"],
];

/**
 * Commands that install, upgrade or launch the NODE package. Forbidden on the PyPI page.
 * `node tools/...` is deliberately absent: both pages carry a Development section whose
 * reader has cloned the repository, and the cross-runtime gate really does need Node.
 */
const NODE_PACKAGE_COMMANDS = [
  [/\bnpx\b/, 'npx'],
  [/\bnpm\s+(i|install|ci|exec)\b/, 'npm install/ci/exec'],
  [/\bbantamkit-memory\b/, 'the Node operator CLI bantamkit-memory'],
  [/\bdist\/cli\.js\b/, 'dist/cli.js'],
];

/**
 * `[lineNumber, kind, text]` for every place a page instructs a reader.
 *
 * `shell` is a line inside a fence whose info string names a shell; `cell` is one inline code
 * span inside a table row. Prose, links, unmarked fences and `python`/`json`/`ts` fences are
 * not instructions and are not returned.
 */
export function instructionSites(markdown) {
  const sites = [];
  let fence = null;
  let inShellBlock = false;
  const lines = markdown.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const lineno = i + 1;
    const match = FENCE.exec(line);
    if (match !== null) {
      const ticks = match[1];
      const info = match[2].toLowerCase();
      if (fence === null) {
        fence = ticks;
        inShellBlock = SHELL_INFO.has(info);
      } else if (ticks.length >= fence.length) {
        fence = null;
        inShellBlock = false;
      }
      continue;
    }
    if (fence !== null) {
      if (inShellBlock && line.trim()) sites.push([lineno, 'shell', line.trim()]);
      continue;
    }
    if (TABLE_ROW.test(line) && !TABLE_RULE.test(line)) {
      for (const span of line.matchAll(CODE_SPAN)) sites.push([lineno, 'cell', span[1]]);
    }
  }
  return sites;
}

function foreignInstructions(path, rel, forbidden) {
  const hits = [];
  for (const [lineno, kind, body] of instructionSites(readFileSync(path, 'utf8'))) {
    for (const [pattern, name] of forbidden) {
      if (pattern.test(body)) {
        hits.push(`${rel}:${lineno} (${kind}) runs ${name}: ${body}`);
        break;
      }
    }
  }
  return hits;
}

test('the scan reaches both landing pages', () => {
  // Without this, a broken fence or table parser makes the two gates below green. No count is
  // asserted — that is a function of how much documentation each page carries.
  for (const path of [NPM_README, PYPI_README]) {
    assert.ok(instructionSites(readFileSync(path, 'utf8')).length > 0, `${path} yielded nothing`);
  }
});

test('the npm page never runs the Python package', () => {
  const hits = foreignInstructions(NPM_README, 'runtime-ts/README.md', PYTHON_PACKAGE_COMMANDS);
  assert.deepEqual(hits, [], `the npm landing page runs the PyPI package:\n${hits.join('\n')}`);
});

test('the PyPI page never runs the npm package', () => {
  const hits = foreignInstructions(PYPI_README, 'runtime-py/README.md', NODE_PACKAGE_COMMANDS);
  assert.deepEqual(hits, [], `the PyPI landing page runs the npm package:\n${hits.join('\n')}`);
});

test('each page still points at its sibling', () => {
  // Separation is not silence: the two share one store on disk, so a reader who landed on the
  // wrong package must be able to find the right one. Otherwise the gate above is satisfiable
  // by deleting the cross-reference.
  assert.match(readFileSync(NPM_README, 'utf8'), /https:\/\/pypi\.org\/project\/bantamkit\//);
  assert.match(readFileSync(PYPI_README, 'utf8'), /https:\/\/www\.npmjs\.com\/package\/bantamkit-mcp/);
});

test('the repo-root README is exempt and offers both installs', () => {
  const sites = instructionSites(readFileSync(ROOT_README, 'utf8'));
  const matches = (forbidden) =>
    sites.some(([, , body]) => forbidden.some(([pattern]) => pattern.test(body)));
  assert.ok(matches(NODE_PACKAGE_COMMANDS), 'the root README stopped offering the npm install');
  assert.ok(matches(PYTHON_PACKAGE_COMMANDS), 'the root README stopped offering the PyPI install');
});

test('a claim about the other runtime is not an instruction', () => {
  // The three shapes the two pages really use to describe each other. If any counted, closing
  // the gate would mean deleting the record of a deliberate divergence.
  for (const markdown of [
    'every later launch starts offline. No Python, `pip`, `uv`, `pipx` or venv.\n',
    "`bantamkit-mcp`'s help is byte-compared with `python -m bantamkit.mcpserver -h`.\n",
    'there the same CLI is `python -m bantamkit.memory`, identical bytes apart.\n',
    'The same server in pure Node is on npm as [`bantamkit-mcp`](https://npm/x).\n',
  ]) {
    assert.deepEqual(instructionSites(markdown), [], markdown);
  }
});

test('shapes that are not instructions', () => {
  for (const markdown of [
    '```\npip install bantamkit\n```\n',
    '```python\nimport bantamkit\n```\n',
    '```json\n{"command": "npx"}\n```\n',
    '|---|---|\n',
  ]) {
    assert.deepEqual(instructionSites(markdown), [], markdown);
  }
});

test('the extractor fires on a fenced command', () => {
  assert.deepEqual(instructionSites('```bash\npip install -U "bantamkit[mcp]"\n```\n'), [
    [2, 'shell', 'pip install -U "bantamkit[mcp]"'],
  ]);
});

test('the extractor fires on a table cell', () => {
  // RULING S3.2's widening, pinned on the row that was actually in the shipped npm README.
  const markdown =
    '| How it was installed | How to update |\n' +
    '|---|---|\n' +
    '| PyPI (`pip install "bantamkit[mcp]"`) | `pipx upgrade bantamkit` |\n';
  assert.deepEqual(instructionSites(markdown), [
    [3, 'cell', 'pip install "bantamkit[mcp]"'],
    [3, 'cell', 'pipx upgrade bantamkit'],
  ]);
});

test('every forbidden pattern fires on a real command', () => {
  // A pattern that never matches anything is a gate with a dead branch. Each string was copied
  // out of a page that really carried it.
  const cases = [
    ['pip install "bantamkit[mcp]"', PYTHON_PACKAGE_COMMANDS],
    ['pipx upgrade bantamkit', PYTHON_PACKAGE_COMMANDS],
    ['uv tool upgrade bantamkit', PYTHON_PACKAGE_COMMANDS],
    ['python -m bantamkit.memory status', PYTHON_PACKAGE_COMMANDS],
    ['python -m venv <env>', PYTHON_PACKAGE_COMMANDS],
    ['/absolute/path/to/env/bin/bantamkit-mcp', PYTHON_PACKAGE_COMMANDS],
    ['npx -y bantamkit-mcp@latest --update', NODE_PACKAGE_COMMANDS],
    ['npm i -g bantamkit-mcp@latest', NODE_PACKAGE_COMMANDS],
    ['npx -y -p bantamkit-mcp bantamkit-memory status', NODE_PACKAGE_COMMANDS],
    ['node ~/.bantamkit/mcp/node_modules/bantamkit-mcp/dist/cli.js', NODE_PACKAGE_COMMANDS],
  ];
  for (const [body, forbidden] of cases) {
    assert.ok(forbidden.some(([pattern]) => pattern.test(body)), body);
  }
});

test('the Development-section command that must stay legal', () => {
  // If this goes red, the forbidden set has been widened to the bare word `node` and the PyPI
  // page's Development section is about to lose the cross-runtime gate.
  const body = 'node tools/conformance/run.mjs --all';
  assert.ok(!NODE_PACKAGE_COMMANDS.some(([pattern]) => pattern.test(body)));
});
