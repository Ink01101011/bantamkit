import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { loadLang } from '../dist/assets.js';
import * as rn from '../dist/replynative.js';

const on = (lang) => (lang === undefined ? { BANTAMKIT_REPLY_NATIVE: 'on' } : { BANTAMKIT_REPLY_NATIVE: 'on', BANTAMKIT_REPLY_LANG: lang });

test('mode', () => {
  const rows = [
    [{}, ['off', null, null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: ' ON ' }, ['latest', null, null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: '1', BANTAMKIT_REPLY_LANG: ' TH ' }, ['fixed', 'th', null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: 'yes', BANTAMKIT_REPLY_LANG: 'ko' }, ['fixed', 'ko', null, null]],
    [{ BANTAMKIT_REPLY_NATIVE: 'true', BANTAMKIT_REPLY_LANG: '' }, ['latest', null, null, null]],
    [on('th-TH'), ['latest', null, 'th-TH', 'invalid-lang']],
    [on('thai'), ['latest', null, 'thai', 'invalid-lang']],
    [{ BANTAMKIT_REPLY_NATIVE: 'garbage', BANTAMKIT_REPLY_LANG: 'th' }, ['off', null, null, null]],
  ];
  for (const [env, want] of rows) {
    const m = rn.mode(env);
    assert.deepEqual([m.kind, m.lang, m.rawLang, m.reason], want, JSON.stringify(env));
  }
  assert.equal(rn.mode(on('😀'.repeat(40))).rawLang, '😀'.repeat(32));
});

test('classify', () => {
  const rows = [
    ['What is this "สวัสดี"?', null],
    ['What is this สวัสดี?', 'th'],
    ['merge main เข้า feat/207', 'th'],
    ['ทำต่อ', 'th'],
    ['fix the login bug', null],
    ['check C:\\Users\\สมชาย\\app.log', null],
    ['check /Users/สมชาย/app.log', null],
    ['see https://example.com/สวัสดี now', null],
    ['run `echo สวัสดี` please', null],
    ['```\nสวัสดี\n```\nwhy does this fail', null],
    ['<pasted_content id="a">ข้อความ</pasted_content> explain this', null],
    ['รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', 'th'],
    ['"ship เลย"', 'th'],
    ['これはなぜ壊れていますか', 'ja'],
    ['漢字だけ', 'ja'],
    ['漢字', null],
    ['「こんにちは」 means what', null],
    ['', null],
  ];
  for (const [prompt, want] of rows) assert.equal(rn.classify(prompt), want, prompt);
  assert.equal(rn.frame('"ship เลย"'), '"ship เลย"');
});

test('loadLang', () => {
  const t = loadLang('th');
  assert.ok(t.startsWith('[reply-native th]') && !t.endsWith('\n'));
  assert.throws(() => loadLang('zz'), /lang asset not found/);
});

test('plan', () => {
  const p = rn.plan(rn.mode(on()), 'th', []);
  assert.deepEqual(p.parts, ['core', 'th']);
  assert.equal(p.text, `${loadLang('core-latest')}\n${loadLang('th')}`);
  assert.equal(Buffer.byteLength(p.text), 885);
  assert.equal(p.reason, null);
  assert.deepEqual(rn.plan(rn.mode(on()), 'th', ['core', 'th']).parts, []);
  const ja = rn.plan(rn.mode(on()), 'ja', new Set(['core', 'th']));
  assert.deepEqual([ja.parts, ja.text], [['ja'], loadLang('ja')]);
  assert.deepEqual(rn.plan(rn.mode(on()), null, []), { parts: [], text: '', reason: null });
  const th = rn.plan(rn.mode(on('th')), 'th', []);
  assert.ok(th.text.includes('ISO 639-1 code is th,') && !th.text.includes('{lang}'));
  assert.equal(Buffer.byteLength(th.text), 898);
  const ko = rn.plan(rn.mode(on('ko')), 'ko', []);
  assert.deepEqual([ko.parts, Buffer.byteLength(ko.text)], [['core'], 508]);
  assert.deepEqual(rn.plan(rn.mode(on('en')), 'en', []), { parts: [], text: '', reason: 'english' });
});

test('plan over budget and missing asset', () => {
  const root = mkdtempSync(join(tmpdir(), 'rn-'));
  mkdirSync(join(root, 'langs'));
  writeFileSync(join(root, 'langs', 'core-latest.md'), `${'x'.repeat(601)}\n`);
  writeFileSync(join(root, 'langs', 'th.md'), 'y\n');
  const saved = process.env.BANTAMKIT_ASSETS;
  process.env.BANTAMKIT_ASSETS = root;
  try {
    assert.equal(rn.plan(rn.mode(on()), 'th', []).reason, 'over-budget');
    unlinkSync(join(root, 'langs', 'core-latest.md'));
    assert.deepEqual(rn.plan(rn.mode(on()), 'th', []), { parts: [], text: '', reason: 'asset-missing' });
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
  }
});

test('statusLine', () => {
  const home = mkdtempSync(join(tmpdir(), 'rn-home-'));
  assert.equal(rn.statusLine(home), 'reply-native: off');
  const dir = join(home, '.bantamkit', 'hooks');
  mkdirSync(dir, { recursive: true });
  const state = join(dir, rn.STATE_FILE);
  writeFileSync(state, '{not json');
  assert.equal(rn.statusLine(home), 'reply-native: the last record is unreadable');
  writeFileSync(state, JSON.stringify({ ts: '2026-11-07T00:00:00.000Z', event: 'UserPromptSubmit', mode: 'latest', lang: 'th', parts: ['core', 'th'], bytes: 885 }));
  assert.equal(rn.statusLine(home), 'reply-native: latest; last UserPromptSubmit at 2026-11-07T00:00:00.000Z: injected core+th (885 bytes)');
  writeFileSync(state, JSON.stringify({ ts: 'T', event: 'SessionStart', mode: 'fixed', lang: 'en', parts: [], bytes: 0, reason: 'english' }));
  assert.equal(rn.statusLine(home), 'reply-native: fixed en; last SessionStart at T: nothing injected (english)');
  writeFileSync(state, JSON.stringify({ ts: 'T', event: 'UserPromptSubmit', mode: 'latest', lang: 'th', parts: [], bytes: 0, reason: 'invalid-lang', rawLang: 'th-TH' }));
  assert.equal(
    rn.statusLine(home),
    'reply-native: latest; last UserPromptSubmit at T: nothing injected (invalid-lang); BANTAMKIT_REPLY_LANG=th-TH invalid, fell back to latest',
  );
});

test('classify is linear on hostile input (0.39.0 gate g1)', () => {
  // These were quadratic: 256 KB took 13 s through the hook, past its 10 s timeout.
  const cases = [
    ['long token', 'สวัสดี ' + '9f'.repeat(1 << 19)],
    ['opening curly quotes', '“'.repeat(1 << 20)],
    ['opening corner quotes', '「'.repeat(1 << 20)],
    ['unclosed tags', '<pasted_content'.repeat(Math.floor((1 << 20) / 15))],
  ];
  for (const [name, text] of cases) {
    const t = performance.now();
    rn.classify(text);
    assert.ok(performance.now() - t < 3000, name);
  }
});
