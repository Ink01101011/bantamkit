/**
 * `pattern`, top-level scalars and clipped feedback (job65 J65-7: #131, #132, #152, #153) —
 * the in-runtime half.
 *
 * `tools/conformance/suites/validate.mjs` (`pattern/`) compares every answer here against the
 * CPython reference; this file says WHICH answer the port gives with no Python on PATH:
 *
 *   - #131: the dialect is `re`'s. `\d`/`\w` are Unicode, `$` matches before a final newline,
 *     `\Z` is end of string, `(?P<x>…)` is a group; inline flags, look-behind, backreferences,
 *     atomic groups, possessive quantifiers, conditional groups and `\N{…}` are ANSWERED with
 *     one sentence, eagerly, never raised and never judged differently.
 *   - #132: a document's patterns share a 500 ms budget; past it the answer is one sentence,
 *     and a `ping` sent behind the validation is answered within a second.
 *   - #152: `"x"`, `1.0` and `null` are JSON documents.
 *   - #153: an offending value is quoted at most 200 codepoints, a sentence at most 1000.
 */
import './_sandbox.mjs';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const dist = new URL('../dist/', import.meta.url);
const contract = await import(new URL('contract.js', dist));
const pyjson = await import(new URL('pyjson.js', dist));
const pyjsonschema = await import(new URL('pyjsonschema.js', dist));

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const CLI = join(packageRoot, 'dist', 'cli.js');
const ASSETS = join(dirname(packageRoot), 'assets');

const se = (output, schema) => contract.schemaError(output, pyjson.parseJson(JSON.stringify(schema)));
const sOf = (pattern) => ({ properties: { s: { pattern } } });
const REFUSED =
  ' is not supported: this validator refuses inline flags, look-behind, backreferences, atomic ' +
  'groups, possessive quantifiers, conditional groups and \\N{...} escapes';

test("#131: the issue's five probes give the reference's verdicts", () => {
  assert.equal(se(JSON.stringify({ s: '๑๒๓' }), sOf('^\\d+$')), null);
  assert.equal(se(JSON.stringify({ s: 'ไทย' }), sOf('^\\w+$')), null);
  assert.equal(se(JSON.stringify({ s: 'a\n' }), sOf('^a$')), null);
  assert.equal(
    se(JSON.stringify({ s: 'abcZ' }), sOf('c\\Z')),
    "JSON does not match schema at 's': 'abcZ' does not match 'c\\\\Z'",
  );
  assert.equal(se(JSON.stringify({ s: 'a' }), sOf('(?P<x>a)')), null);
});

test('#131: re classes, anchors and literals are translated, not borrowed from RegExp', () => {
  const t = (pattern, text) => new RegExp(pyjsonschema.translatePyPattern(pattern).source, 'v').test(text);
  assert.equal(t('^\\s$', '\x1c'), true); // str.isspace() — JS \s says no
  assert.equal(t('^\\s$', '﻿'), false); // JS \s says yes
  assert.equal(t('^.$', '\r'), true); // `.` stops only at \n in re
  assert.equal(t('\\bไทย\\b', 'ภาษา ไทย'), true); // a Unicode word boundary
  assert.equal(t('\\B', ''), false); // SRE_AT_UNI_NON_BOUNDARY never matches the empty string
  assert.equal(t('^a{,2}$', 'aa'), true);
  assert.equal(t('^a{$', 'a{'), true); // a `{` that is not a repeat is a literal
  assert.equal(t('^[]a]+$', ']a'), true); // `]` first in a class is a member
  assert.equal(t('^\\Aa\\Z', 'a\n'), false);
});

test('#131: a pattern re refuses raises; one outside the shared dialect is answered, eagerly', () => {
  assert.throws(() => pyjsonschema.translatePyPattern('('), { name: 'PyReError' });
  assert.throws(() => pyjsonschema.translatePyPattern('a**'), { name: 'PyReError' });
  assert.throws(() => pyjsonschema.translatePyPattern('\\q'), { name: 'PyReError' });
  for (const p of ['(?i)a', '(?<=a)b', '(a)\\1', '(?>a)', 'a*+', '(a)?(?(1)b|c)', '\\N{DIGIT ONE}', '\\N{NOPE}']) {
    assert.equal(pyjsonschema.translatePyPattern(p).source, null, p);
    // `{"n": 1}` never reaches `s`: the refusal is the schema's, like check_schema's compile.
    assert.equal(se('{"n": 1}', sOf(p)), `the pattern ${pyjson.reprValue({ t: 'str', v: p })}${REFUSED}`);
  }
  assert.notEqual(pyjsonschema.translatePyPattern('(?u)a').source, null); // the default flag
});

test('#132: a catastrophic pattern is refused at the budget, not run to the end', () => {
  const started = Date.now();
  const answer = se(JSON.stringify({ s: 'a'.repeat(40) + '!' }), sOf('^(a+)+$'));
  const took = Date.now() - started;
  assert.equal(
    answer,
    "the pattern '^(a+)+$' did not finish within the 500 ms this validator allows a document's " +
      'patterns; rewrite it so it cannot backtrack catastrophically, as (a+)+$ does',
  );
  assert.ok(took < 2000, `took ${took} ms`);
  // The clock is per validation: the next call starts from zero.
  assert.equal(se(JSON.stringify({ s: 'aaa' }), sOf('^(a+)+$')), null);
});

const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'bk-patterns-')));
after(() => rmSync(scratch, { recursive: true, force: true }));

test('#132: a ping sent behind a catastrophic validate_json is answered within a second', async () => {
  const home = join(scratch, 'home');
  const store = join(scratch, 'store');
  mkdirSync(home, { recursive: true });
  mkdirSync(store, { recursive: true });
  const child = spawn(process.execPath, [CLI, '--store', store], {
    cwd: scratch,
    env: { ...process.env, HOME: home, USERPROFILE: home, BANTAMKIT_ASSETS: ASSETS },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const answered = new Map();
  let out = '';
  child.stdout.on('data', (chunk) => {
    out += chunk.toString('utf8');
    let at;
    while ((at = out.indexOf('\n')) !== -1) {
      const frame = JSON.parse(out.slice(0, at));
      out = out.slice(at + 1);
      answered.get(frame.id)?.(frame);
    }
  });
  const send = (frame) => child.stdin.write(`${JSON.stringify(frame)}\n`);
  const reply = (id) => new Promise((resolve) => answered.set(id, resolve));
  try {
    const init = reply(1);
    send({
      jsonrpc: '2.0',
      id: 1,
      method: 'initialize',
      params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } },
    });
    await init;
    send({ jsonrpc: '2.0', method: 'notifications/initialized' });
    const t0 = Date.now();
    const validated = reply(2).then((f) => ({ f, at: Date.now() - t0 }));
    send({
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: {
        name: 'validate_json',
        arguments: { output: JSON.stringify({ x: 'a'.repeat(40) + '!' }), schema: { properties: { x: { pattern: '^(a+)+$' } } } },
      },
    });
    await new Promise((r) => setTimeout(r, 20));
    const pinged = reply(3).then(() => Date.now() - t0);
    send({ jsonrpc: '2.0', id: 3, method: 'ping' });
    const pingAt = await pinged;
    const { f } = await validated;
    assert.ok(pingAt < 1000, `ping answered at ${pingAt} ms`);
    const body = JSON.parse(f.result.content[0].text);
    assert.equal(body.valid, false);
    assert.match(body.feedback, /did not finish within the 500 ms/);
  } finally {
    child.kill();
  }
});

test('#152: a top-level scalar is a JSON document', () => {
  assert.equal(se('"just a string"', { type: 'string' }), null);
  assert.equal(se('1.0', { type: 'number' }), null);
  assert.equal(se('null', { type: 'null' }), null);
  assert.equal(se('"x"', { type: 'integer' }), "JSON does not match schema at 'root': 'x' is not of type 'integer'");
  assert.equal(se('42 is the answer', {}), 'output was not parseable JSON: no JSON object found in output');
});

test('#153: the offending value is clipped at 200 codepoints, the sentence at 1000', () => {
  const big = se(JSON.stringify({ x: 'y'.repeat(1 << 20) }), { properties: { x: { maxLength: 10 } } });
  assert.equal(big, `JSON does not match schema at 'x': '${'y'.repeat(199)}…(1048378 more) is too long`);
  const key = se(JSON.stringify({ ['k'.repeat(5000)]: 1 }), { additionalProperties: false });
  assert.ok([...key].length < 1100, `${[...key].length}`);
  assert.match(key, /…\(\d+ more\)$/);
  // codepoints, not UTF-16 units: 300 astral characters clip after 199 of them, not 99.
  const astral = se(JSON.stringify({ x: '😀'.repeat(300) }), { properties: { x: { maxLength: 1 } } });
  assert.equal(astral, `JSON does not match schema at 'x': '${'😀'.repeat(199)}…(102 more) is too long`);
  assert.equal(pyjsonschema.clipText('abc', 2), 'ab…(1 more)');
});
