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

// ------------------------------------------------------------- Task 4: the daily run

const retention = await import('../dist/storage/retention.js');

function homeWithClaude() {
  const dir = tmp();
  const home = path.join(dir, 'home');
  fs.mkdirSync(path.join(home, '.bantamkit'), { recursive: true });
  const p = path.join(home, '.claude', 'skills', 'solo', 'SKILL.md');
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, '---\ndescription: Use "x" now\n---\n');
  return { dir, home };
}

/** Set (or delete, with undefined) env vars until `t` ends. */
function env(t, vars) {
  for (const [k, v] of Object.entries(vars)) {
    const saved = process.env[k];
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
    t.after(() => (saved === undefined ? delete process.env[k] : (process.env[k] = saved)));
  }
}

test('daily writes the record and keeps surfaced that still apply', () => {
  const { home } = homeWithClaude();
  R.daily(home, null, NOW);
  const raw = fs.readFileSync(R.statePath(home), 'utf8');
  assert.ok(raw.endsWith('}\n') && !raw.includes('\r'));
  const rec = R.readState(home);
  assert.equal(rec.host, 'claude-code');
  assert.deepEqual(rec.surfaced, []);
  assert.equal(rec.ts, NOW);
  const key = R.surfaceKey(rec.findings[0]);
  assert.equal(key, 'never-invoked\tsolo\t0 calls');
  rec.surfaced = ['gone\t\t', key];
  fs.writeFileSync(R.statePath(home), JSON.stringify(rec));
  R.daily(home, null, '2026-10-17T00:00:00.000Z');
  assert.deepEqual(R.readState(home).surfaced, [key]);
  assert.deepEqual(fs.readdirSync(path.join(home, '.bantamkit')).filter((n) => n.endsWith('.tmp') || n.endsWith('.lock')), []);
});

test('corrupt or wrong version is recomputed', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined });
  const { home } = homeWithClaude();
  for (const bad of [
    '{"version": 9}',
    'not json',
    '﻿{"version": 1}',
    '{"version": true, "ts": "t", "host": "h", "surfaced": [], "error": "e"}',
    '{"version": 1, "ts": "t", "host": "h", "surfaced": [1], "error": "e"}',
    '{"version": 1, "ts": "t", "host": "h", "surfaced": [], "skills": 1.5}',
  ]) {
    fs.writeFileSync(R.statePath(home), bad);
    assert.equal(R.readState(home), null, bad);
    assert.equal(R.statusLine(home), 'skill audit: the last record is unreadable; the next run recomputes it');
  }
  R.daily(home, null, NOW);
  assert.equal(R.readState(home).version, 1);
});

test('a whole float reads as the integer JSON.parse makes it', () => {
  const { home } = homeWithClaude();
  fs.writeFileSync(R.statePath(home), '{"version": 1.0, "ts": "t", "host": "h", "surfaced": [], "error": "e"}');
  assert.equal(R.readState(home).version, 1);
});

test('status lines', (t) => {
  const bare = tmp();
  env(t, { BANTAMKIT_SKILL_AUDIT: 'off', BANTAMKIT_RETENTION: undefined });
  assert.equal(R.statusLine(bare), 'skill audit: off; never ran; usage adapter none');
  // Amendment A3: the prefix reads the AUDIT switch, never retention's.
  delete process.env.BANTAMKIT_SKILL_AUDIT;
  process.env.BANTAMKIT_RETENTION = 'off';
  assert.equal(R.statusLine(bare), 'skill audit: never ran; usage adapter none');
  const { home } = homeWithClaude();
  assert.equal(R.statusLine(home), 'skill audit: never ran; usage adapter claude-code');
  R.daily(home, null, NOW);
  assert.equal(
    R.statusLine(home),
    'skill audit: last ran 2026-10-16T00:00:00.000Z on claude-code; 1 skill, 11 catalogue bytes; findings 0 high, 0 medium, 1 low; usage over 0 days (a proposed change needs 30)',
  );
  fs.writeFileSync(R.statePath(home), JSON.stringify({ version: 1, ts: NOW, host: 'none', error: 'boom', surfaced: [] }));
  assert.equal(R.statusLine(home), 'skill audit: last ran 2026-10-16T00:00:00.000Z; no report — boom');
});

test('the retention child runs the audit under the claimed day', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined, BANTAMKIT_RETENTION: 'off' });
  const { dir, home } = homeWithClaude();
  assert.equal(retention.childMain([dir, home], NOW), 0);
  assert.equal(R.readState(home).ts, NOW);
  assert.deepEqual(JSON.parse(fs.readFileSync(retention.statePath(home), 'utf8')), { ran_at: NOW });
  // The claimed day holds: a second child the same day neither sweeps nor audits again.
  fs.unlinkSync(R.statePath(home));
  assert.equal(retention.childMain([dir, home], '2026-10-16T12:00:00.000Z'), 0);
  assert.equal(fs.existsSync(R.statePath(home)), false);
});

test('BANTAMKIT_SKILL_AUDIT=off stops the daily run', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: 'off', BANTAMKIT_RETENTION: undefined, BANTAMKIT_INDEX_DIR: path.join(tmp(), 'idx') });
  const { dir, home } = homeWithClaude();
  retention.childMain([dir, home], NOW);
  assert.equal(fs.existsSync(R.statePath(home)), false);
  assert.ok('report' in JSON.parse(fs.readFileSync(retention.statePath(home), 'utf8')));
});

test('daily never throws', () => {
  const home = path.join(tmp(), 'home');
  fs.mkdirSync(path.join(home, '.claude', 'skills'), { recursive: true });
  R.daily(home, null, NOW);
  assert.equal(fs.existsSync(path.join(home, '.bantamkit')), false);
});

// --- Task 5: the SessionStart line ---------------------------------------------------------

const { FULL, HIGH, LINE, never, put, rec } = await import('./_skillline.mjs');
const one = (body) => `[bantamkit] skill audit: 1 new — ${body} — /mcp__bantamkit__skill_audit has the report.`;

test('the line is capped and then silent', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec(FULL));
  const line = R.sessionLine(home);
  assert.equal(line, LINE);
  assert.equal(Buffer.byteLength(line), 199);
  assert.ok(Buffer.byteLength(line) <= R.LINE_MAX_BYTES);
  assert.equal(R.sessionLine(home), null);
  const keys = FULL.map((f) => R.surfaceKey(f)).sort();
  assert.deepEqual(R.readState(home).surfaced, keys);
});

test('nothing new is null and writes nothing', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec(FULL, 30, FULL.map((f) => R.surfaceKey(f))));
  const before = fs.readFileSync(R.statePath(home));
  assert.equal(R.sessionLine(home), null);
  assert.deepEqual(fs.readFileSync(R.statePath(home)), before);
});

test('never-invoked waits for 30 days', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec([never('x')], 29));
  assert.equal(R.sessionLine(home), null);
  put(home, rec([never('x')], 30));
  assert.equal(R.sessionLine(home), one('x 30 days without a call'));
});

test('one long item is clipped on a code point', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec([{ ...HIGH, skills: ['ก'.repeat(80)] }]));
  const line = R.sessionLine(home);
  const raw = Buffer.from(line, 'utf8');
  assert.ok(raw.length <= 200 && line.includes('…'));
  assert.equal(new TextDecoder('utf-8', { fatal: true }).decode(raw), line);
});

test('a finding shown once is never shown again, but a new one is', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec([HIGH]));
  assert.notEqual(R.sessionLine(home), null);
  const stored = R.readState(home);
  stored.findings.push(never('late'));
  put(home, stored);
  assert.equal(R.sessionLine(home), one('late 30 days without a call'));
  assert.equal(R.sessionLine(home), null);
});

test('no record, an error record or a corrupt file is silent', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  assert.equal(R.sessionLine(home), null);
  assert.equal(fs.existsSync(R.statePath(home)), false);
  put(home, { version: 1, ts: 't', host: 'none', error: 'x', surfaced: [] });
  assert.equal(R.sessionLine(home), null);
  fs.writeFileSync(R.statePath(home), '{not json');
  assert.equal(R.sessionLine(home), null);
  assert.equal(fs.readFileSync(R.statePath(home), 'utf8'), '{not json');
});

test('a malformed finding is skipped, not fatal', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: undefined }); // the sandbox pins it off, and off silences the line (job73 A6)
  const home = tmp();
  put(home, rec([{ kind: 'x', severity: 'high', skills: 'alpha', detail: 'd' }, HIGH]));
  assert.equal(R.sessionLine(home), one('shared-trigger-phrase: alpha:a1, beta:b2'));
});

test('the audit switch off silences the line and writes nothing (job73 A6 ruling)', (t) => {
  env(t, { BANTAMKIT_SKILL_AUDIT: 'off' });
  const home = tmp();
  put(home, rec(FULL));
  const before = fs.readFileSync(R.statePath(home));
  assert.equal(R.sessionLine(home), null);
  assert.deepEqual(fs.readFileSync(R.statePath(home)), before);
  delete process.env.BANTAMKIT_SKILL_AUDIT;
  assert.equal(R.sessionLine(home), LINE);
});

test('renderLine never overflows', () => {
  for (let n = 0; n < 40; n++) {
    const items = Array.from({ length: n }, (_, i) => `item-${i} ` + 'x'.repeat((i * 7) % 90));
    assert.ok(Buffer.byteLength(R.renderLine(items)) <= R.LINE_MAX_BYTES);
  }
});
