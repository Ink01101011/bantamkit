/**
 * skillreport (#205 Task 3): the same nodes as runtime-py/tests/test_skillreport.py.
 * `tools/conformance/suites/skill-host.mjs` compares the two runtimes. Every path is under a
 * fresh temp directory: nothing here reads a real home.
 */
import './_sandbox.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const R = await import('../dist/skillreport.js');
const { Gathered, UsageScan } = await import('../dist/skillhost.js');
const { scanRoots } = await import('../dist/skillaudit.js');

const NOW = '2026-10-16T00:00:00.000Z';
const SETTINGS = '{\n  "enabledPlugins": {\n    "alpha@mk": true,\n    "beta@mk": true\n  }\n}\n';

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'skillreport-')));
const sha = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');

function skill(base, rel, description) {
  const p = path.join(base, rel, 'SKILL.md');
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `---\nname: ${path.basename(path.dirname(p))}\ndescription: ${description}\n---\n`);
}

function bed(counts, span, settingsText = SETTINGS) {
  const dir = tmp();
  const cache = path.join(dir, 'cache');
  skill(cache, 'mk/alpha/1.0.0/skills/a1', 'a one');
  skill(cache, 'mk/alpha/1.0.0/skills/a2', 'a two');
  skill(cache, 'mk/beta/1.0.0/skills/b1', 'b one');
  const settings = path.join(dir, 'settings.json');
  fs.writeFileSync(settings, settingsText);
  const usage = counts === null ? null : new UsageScan(new Map(Object.entries(counts)), span, 3, 0, 0);
  const src = { 'alpha@mk': settings, 'beta@mk': settings };
  return { g: new Gathered('claude-code', [['plugins', cache]], ['alpha@mk', 'beta@mk'], null, src, usage), settings, dir };
}

test('a plugin with every skill at zero over 30 days is proposed', () => {
  const { g, settings } = bed({ 'beta:b1': 4 }, 30);
  const rec = R.buildRecord(g, NOW);
  assert.deepEqual(rec.proposals, [
    {
      plugin: 'alpha@mk',
      file: settings,
      line: 3,
      before: '    "alpha@mk": true,',
      after: '    "alpha@mk": false,',
      skills: ['alpha:a1', 'alpha:a2'],
    },
  ]);
  assert.equal(rec.version, R.STATE_VERSION);
  assert.deepEqual(rec.surfaced, []);
});

test('no proposal without usage', () => {
  const { g } = bed(null, 0);
  assert.deepEqual(R.buildRecord(g, NOW).proposals, []);
});

test('propose refuses a missing measurement even at 30 days', () => {
  const { g } = bed(null, 0);
  const found = scanRoots(g.roots.map(([label, p]) => ({ label, path: p })), [...g.enabled], null);
  assert.deepEqual(R.propose(found, null, 30, g.sources), []);
  assert.deepEqual(R.propose(found, new Map(), 30, g.sources).map((p) => p.plugin), ['alpha@mk', 'beta@mk']);
});

test('no proposal under 30 days', () => {
  const { g } = bed({ 'beta:b1': 4 }, 29);
  assert.deepEqual(R.buildRecord(g, NOW).proposals, []);
});

test('one called skill keeps its plugin', () => {
  const { g } = bed({ 'alpha:a2': 1, 'beta:b1': 4 }, 30);
  assert.deepEqual(R.buildRecord(g, NOW).proposals, []);
});

test('personal skills never get a diff', () => {
  const dir = tmp();
  const user = path.join(dir, 'user');
  skill(user, 'solo', 's');
  const settings = path.join(dir, 'settings.json');
  fs.writeFileSync(settings, '{\n  "enabledPlugins": {\n    "@": true\n  }\n}\n');
  const g = new Gathered('claude-code', [['user', user]], ['@'], null, { '@': settings }, new UsageScan(new Map(), 30, 1, 0, 0));
  const rec = R.buildRecord(g, NOW);
  assert.deepEqual(rec.proposals, []);
  assert.equal(rec.findings[0].kind, 'never-invoked');
  assert.deepEqual(rec.findings[0].skills, ['solo']);
});

test('render shows the diff and never claims it was applied', () => {
  const { g, settings } = bed({ 'beta:b1': 4 }, 30);
  const before = sha(settings);
  const text = R.renderReport(R.buildRecord(g, NOW));
  assert.ok(text.includes(`--- ${settings}\n+++ ${settings}\n@@ -3 +3 @@\n-    "alpha@mk": true,\n+    "alpha@mk": false,`));
  assert.ok(text.includes('NOT applied; bantamkit never edits settings.json'));
  assert.equal(sha(settings), before);
});

test('minified settings is not located and says so', () => {
  const { g, settings } = bed({ 'beta:b1': 4 }, 30, '{"enabledPlugins":{"alpha@mk":true,"beta@mk":true}}');
  const before = sha(settings);
  const rec = R.buildRecord(g, NOW);
  assert.deepEqual(rec.proposals.map((p) => [p.line, p.before, p.after]), [[null, null, null]]);
  const text = R.renderReport(rec);
  assert.ok(text.includes(`set enabledPlugins["alpha@mk"] to false in ${settings} (the line could not be located)`));
  assert.ok(!text.includes('--- '));
  assert.equal(sha(settings), before);
});

test('only a line inside enabledPlugins is located', () => {
  const text =
    '{\r\n  "other": {\r\n    "alpha@mk": true\r\n  },\r\n' +
    '  "enabledPlugins": {\r\n    "alpha@mk" : true ,\r\n    "beta@mk": true\r\n  }\r\n}\r\n';
  const { g } = bed({ 'beta:b1': 4 }, 30, text);
  const [p, ...rest] = R.buildRecord(g, NOW).proposals;
  assert.equal(rest.length, 0);
  assert.deepEqual([p.line, p.before, p.after], [6, '    "alpha@mk" : true ,', '    "alpha@mk" : false ,']);
});

test('young render ends with the span sentence', () => {
  const { g } = bed({ 'beta:b1': 4 }, 12);
  const text = R.renderReport(R.buildRecord(g, NOW));
  assert.ok(text.endsWith('proposed change: none — the transcripts span 12 days; a change needs 30'));
});

test('null host report', () => {
  const rec = R.buildRecord(new Gathered('none'), NOW);
  assert.deepEqual(rec, { version: 1, ts: NOW, host: 'none', error: 'no skill directory was found for this host', surfaced: [] });
  assert.ok(R.renderReport(rec).startsWith('skill audit — could not run: no skill directory was found for this host.'));
});

test('runLive never throws', () => {
  const saved = R.skillreportDeps.selectAdapter;
  R.skillreportDeps.selectAdapter = () => {
    throw new Error('x');
  };
  try {
    const rec = R.runLive(tmp(), null, NOW);
    assert.equal(rec.error, 'the gather failed');
    assert.equal(rec.host, 'none');
  } finally {
    R.skillreportDeps.selectAdapter = saved;
  }
});

test('runLive over a home with no .claude is the null report', () => {
  const rec = R.runLive(tmp(), null, NOW);
  assert.equal(rec.host, 'none');
  assert.equal(rec.error, R.NO_ROOTS);
});
