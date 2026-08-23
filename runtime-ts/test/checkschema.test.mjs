/**
 * `check_schema` — the caller schema that is not a schema, and the two decoders that were
 * one question with two answers.
 *
 * WHY THIS FILE EXISTS. `jsonschema.validate` runs `cls.check_schema(schema)` BEFORE it
 * looks at the instance. This port did not, and the consequence was not a different sentence
 * but a WRONG ANSWER: the keywords in `pyjsonschema.ts` are written to SKIP a schema value
 * they do not recognise, which is correct inside `iter_errors` and is `{"valid": true}` at a
 * tool boundary. N8 measured five on the wire; the fix is `checkSchema`, and 53 shapes are
 * compared against the reference in `tools/conformance/suites/validate.mjs`. This file is
 * the in-runtime half — it says WHICH ANSWER changed, without a Python on PATH.
 *
 * The UTF-8 BOM cases are here for the same reason one directory over: `pyDecodeUtf8`'s own
 * validator accepted `EF BB BF` as three ordinary bytes while the `TextDecoder` behind it
 * silently dropped them, so the module checked one string and returned another.
 */
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const dist = new URL('../dist/', import.meta.url);
const contract = await import(new URL('contract.js', dist));
const pyjson = await import(new URL('pyjson.js', dist));
const pyjsonschema = await import(new URL('pyjsonschema.js', dist));
const pyfs = await import(new URL('memory/pyfs.js', dist));
const assets = await import(new URL('assets.js', dist));

/** The five N8 measured on the wire, each with the answer this port used to give. */
const N8_FIVE = [
  ['{"required": "a"}', '{"valid": true}'],
  ['{"required": 3}', '{"valid": true}'],
  ['{"properties": ["a"]}', '{"valid": true}'],
  ['{"additionalProperties": [1]}', '{"valid": true}'],
  ['{"type": 3}', '{"valid": false, "feedback": "… is not of type 3"}'],
];

test('the five N8 measured now REFUSE instead of answering', () => {
  for (const [schema, was] of N8_FIVE) {
    assert.throws(
      () => contract.schemaError('{"a": 1}', pyjson.parseJson(schema)),
      (e) => e instanceof pyjsonschema.PyJsonSchemaUnsupported,
      `${schema} used to answer ${was}`,
    );
  }
});

test('the shape table, one refusal per keyword family', () => {
  const bad = [
    '{"required": [3]}',
    '{"required": ["a", "a"]}',
    '{"properties": {"a": 3}}',
    '{"additionalProperties": 1}',
    '{"type": "nosuch"}',
    '{"type": ["string", 3]}',
    '{"type": ["string", "string"]}',
    '{"type": []}',
    '{"enum": "a"}',
    '{"multipleOf": "a"}',
    '{"multipleOf": 0}',
    '{"multipleOf": -1}',
    '{"minimum": "a"}',
    '{"maxLength": "a"}',
    '{"maxLength": -1}',
    '{"maxLength": 1.5}',
    '{"uniqueItems": "yes"}',
    '{"pattern": 3}',
    '{"pattern": "("}',
    '{"format": 3}',
    '{"allOf": {"a": 1}}',
    '{"allOf": []}',
    '{"allOf": [3]}',
    '{"anyOf": {}}',
    '{"oneOf": "x"}',
    '{"prefixItems": {}}',
    '{"items": 3}',
    '{"contains": 3}',
    '{"not": 3}',
    '{"if": 3}',
    '{"propertyNames": 3}',
    '{"patternProperties": []}',
    '{"patternProperties": {"^a": 3}}',
    '{"dependentRequired": "a"}',
    '{"dependentRequired": {"a": "b"}}',
    '{"dependentSchemas": []}',
    '{"dependentSchemas": {"a": 3}}',
    '{"minContains": "a"}',
    '[1]',
    '3',
    '"x"',
    // Recursive, and the last one is the loudest: `$defs` is never descended into by any
    // keyword this port implements, and the reference refuses it all the same.
    '{"properties": {"a": {"required": "b"}}}',
    '{"items": {"type": 3}}',
    '{"anyOf": [{"properties": {"a": {"maxLength": "x"}}}]}',
    '{"$defs": {"x": {"type": 3}}}',
  ];
  for (const schema of bad) {
    assert.throws(
      () => contract.schemaError('{"a": 1}', pyjson.parseJson(schema)),
      (e) => e instanceof pyjsonschema.PyJsonSchemaUnsupported,
      schema,
    );
  }
});

test('a schema that IS a schema still answers, and the answer is unchanged', () => {
  // The shapes next door to a refusal, so the check cannot be passing by refusing everything.
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"required": ["a"]}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"type": ["object", "array"]}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"enum": []}')) !== null, true);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"maxLength": 2.0}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"multipleOf": 0.5}')), null);
  assert.equal(contract.schemaError('{"a": 1}', pyjson.parseJson('{"additionalProperties": false}')) !== null, true);
  assert.equal(
    contract.schemaError('{"a": "x"}', pyjson.parseJson('{"properties": {"a": {"type": "integer"}}}')),
    "JSON does not match schema at 'a': 'x' is not of type 'integer'",
  );
  // Every tool asset ships its own parameter block through this path on every call.
  for (const tool of ['memory_save', 'memory_recall', 'shiftwork_clock_out', 'validate_json']) {
    const parameters = assets.loadToolAsset(tool)['parameters'];
    assert.doesNotThrow(() => pyjsonschema.checkSchema(pyjson.fromJs(parameters)));
  }
});

test('pyDecodeUtf8 KEEPS a BOM, because bytes.decode("utf-8") does', () => {
  const dec = (bytes) => pyfs.pyDecodeUtf8(Uint8Array.from(bytes));
  assert.equal(dec([0xef, 0xbb, 0xbf]), '﻿');
  assert.equal(dec([0xef, 0xbb, 0xbf, 0x61]), '﻿a');
  assert.equal(dec([0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf]), '﻿﻿');
  assert.equal(dec([0x61, 0xef, 0xbb, 0xbf]), 'a﻿');
});

test('json.loads refuses a BOM and raw_decode does not — the check lives in loads', () => {
  assert.throws(
    () => pyjson.parseJson('﻿{"a": 1}'),
    (e) => String(e.message) === 'Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)',
  );
  // `contract.extract_json` goes through `raw_decode`, which has no BOM test at all: it just
  // fails to find a value there.
  assert.throws(
    () => pyjson.rawDecode('﻿{"a": 1}'),
    (e) => String(e.message) === 'Expecting value: line 1 column 1 (char 0)',
  );
});

test('asPyOSError prints CPython\'s errno, not libuv\'s status number', () => {
  // CONSTRUCTIBLE ON EVERY PLATFORM, which is the point. libuv reuses the platform errno on
  // POSIX and has its own space on Windows — ENOENT arrives as -4058 there, EISDIR as -4068
  // — so `Math.abs(err.errno)` is right by accident here and wrong where it matters.
  // MEASURED on windows-latest, run 32644269451: five nodes reported
  // `[Errno 4058] No such file or directory` for what CPython prints as `[Errno 2]`.
  // Feeding the Windows-shaped error object in by hand means the fix has a node that goes
  // red on this laptop, instead of one only a Windows runner could ever have failed.
  const win = (code, errno, path) => Object.assign(new Error('x'), { code, errno, path, syscall: 'open' });
  // The ORIGIN has to be named now: on Windows, `os.*` carries a winerror and prints
  // `[WinError %d]`, and only the C-runtime arm keeps the `[Errno %d]` form on every
  // platform. Leaving it defaulted made this node assert the Win32 sentence was the CRT
  // one — MEASURED, run 32649940727, and it was this test that was wrong.
  const crt = (code, errno, path) => pyfs.asPyOSError(win(code, errno, path), undefined, undefined, 'crt');
  assert.equal(crt('ENOENT', -4058, '/a/x.md').message, "[Errno 2] No such file or directory: '/a/x.md'");
  assert.equal(crt('ENOENT', -4058, '/a/x.md').errno, 2);
  assert.equal(crt('EACCES', -4092, '/a/d').errno, 13);
  // The libuv magnitude is wrong on Windows for EVERY code, so the errno is checked on the
  // Win32 arm too — where the sentence differs but the number must not.
  assert.equal(pyfs.asPyOSError(win('EISDIR', -4068, '/a/d')).errno, 21);
  assert.equal(pyfs.asPyOSError(win('ENOENT', -4058, '/a/x.md')).errno, 2);
  // The POSIX shape keeps answering the same, so the fix is not a platform switch.
  assert.equal(crt('ENOENT', -2, '/a/x.md').errno, 2);
  // A code the table does not carry keeps the magnitude rather than losing the number.
  assert.equal(pyfs.asPyOSError(win('EWHAT', -4321, '/a/x.md')).errno, 4321);
});

test('OSError and the symlink-loop RuntimeError print the path with %r', () => {
  const err = (filename, filename2 = null) =>
    new pyfs.PyOSError(2, 'ENOENT', 'No such file or directory', filename, filename2).message;
  assert.equal(err('/a/plain.md'), "[Errno 2] No such file or directory: '/a/plain.md'");
  // An apostrophe flips the quote, exactly as `repr` does; the old spelling emitted
  // `: '/a/it's.md'`, which is not a string CPython ever prints.
  assert.equal(err("/a/it's.md"), `[Errno 2] No such file or directory: "/a/it's.md"`);
  assert.equal(err('/a/two\nlines.md'), "[Errno 2] No such file or directory: '/a/two\\nlines.md'");
  assert.equal(err('/a/tab\there.md'), "[Errno 2] No such file or directory: '/a/tab\\there.md'");
  assert.equal(
    err("/a/x'.md", '/b/y\n.md'),
    `[Errno 2] No such file or directory: "/a/x'.md" -> '/b/y\\n.md'`,
  );
});

test("pathlib's symlink-loop RuntimeError uses %r too", () => {
  // `realpathSync`: `os.tmpdir()` is not canonical — a `/var` symlink on macOS, the 8.3
  // short name on Windows CI. See the note in test/store.test.mjs.
  const bed = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-loop-')));
  try {
    const link = join(bed, "loop's-link");
    symlinkSync(link, link);
    // The path in the message is the RESOLVED one (`/var` is a symlink to `/private/var`
    // here), so what is pinned is the quoting: `%r` picks `"` because the name holds a `'`.
    //
    // THE PREFIX IS PLATFORM-SHAPED AND THE OLD REGEX WAS NOT. `^Symlink loop from "/` can
    // never match `"D:\\a\\..."`, so on a Windows cell this node could only ever fail —
    // and it did, run 32646521489, for TWO reasons at once: that, and `resolveWindows`
    // swallowing the error and raising nothing at all. Both are fixed; the assertion is
    // written so that the RAISE is required on every platform and only the spelling of the
    // path is allowed to differ.
    const anchor = process.platform === 'win32' ? '[A-Za-z]:\\\\\\\\' : '\\/';
    assert.throws(
      () => pyfs.pyResolve(link),
      (e) => new RegExp(`^Symlink loop from "${anchor}.*loop's-link"$`).test(e.message),
    );
  } finally {
    rmSync(bed, { recursive: true, force: true });
  }
});

test('an asset that is not UTF-8 raises CPython\'s decode message, not U+FFFD', () => {
  // `assets.ts` used to carry its OWN decoder — `readFileSync(p, "utf8")`, which substitutes
  // U+FFFD for a bad byte and hands a model a description with a replacement character in
  // it. `Path.read_text(encoding="utf-8")` raises. One decoder for the package means this
  // arm inherits `pyDecodeUtf8`'s strictness along with its BOM handling.
  const bed = realpathSync.native(mkdtempSync(join(tmpdir(), 'bk-assets-')));
  const saved = process.env.BANTAMKIT_ASSETS;
  try {
    mkdirSync(join(bed, 'skills'), { recursive: true });
    writeFileSync(join(bed, 'skills', 'broken.md'), Buffer.from([0x61, 0xff, 0x62]));
    writeFileSync(join(bed, 'skills', 'bommed.md'), Buffer.from([0xef, 0xbb, 0xbf, 0x61]));
    process.env.BANTAMKIT_ASSETS = bed;
    assert.throws(
      () => assets.loadSkill('broken'),
      (e) =>
        e.name === 'UnicodeDecodeError' &&
        e.message === "'utf-8' codec can't decode byte 0xff in position 1: invalid start byte",
    );
    // …and the BOM is content, here as everywhere else.
    assert.equal(assets.loadSkill('bommed'), '\ufeffa');
  } finally {
    if (saved === undefined) delete process.env.BANTAMKIT_ASSETS;
    else process.env.BANTAMKIT_ASSETS = saved;
    rmSync(bed, { recursive: true, force: true });
  }
});

// ------------------------------------------------------- what Windows answers, from here
//
// Every node below runs on EVERY platform, and that is the whole design. The port's Windows
// arms were previously only reachable on a runner, so the loop for correcting them was
// commit -> push -> seven minutes -> read a log. `ntpath` and `PureWindowsPath` are pure
// path algebra that CPython computes identically everywhere, and the errno/winerror question
// is a decision over an error object that can be built by hand — so both become laptop
// measurements. The differential half (these same functions against a running CPython) is
// `tools/conformance/suites/store.mjs`, case `ntpath.splitroot and PureWindowsPath parsing`.

test('ntpath.splitroot: a UNC share is a DRIVE, and three slashes are not two', () => {
  // `//a/b` is `\\server\share`: the whole text is the drive, the root is a separator that
  // splitroot itself does not return, and there is nothing left to walk. Reading it as a
  // POSIX-style double-slash root is what made `pyParents('//a/b')` answer a two-element
  // walk over directories that cannot exist (run 32646521489).
  assert.deepEqual(pyfs.ntSplitRoot('//a/b'), ['//a/b', '', '']);
  assert.deepEqual(pyfs.ntSplitRoot('//a/b/c'), ['//a/b', '/', 'c']);
  assert.deepEqual(pyfs.ntSplitRoot('//a'), ['//a', '', '']);
  assert.deepEqual(pyfs.ntSplitRoot('///a'), ['///a', '', '']);
  assert.deepEqual(pyfs.ntSplitRoot('////a/b'), ['///', '/', 'a/b']);
  assert.deepEqual(pyfs.ntSplitRoot('/a'), ['', '/', 'a']);
  assert.deepEqual(pyfs.ntSplitRoot('a'), ['', '', 'a']);
  assert.deepEqual(pyfs.ntSplitRoot('C:x'), ['C:', '', 'x']);
  assert.deepEqual(pyfs.ntSplitRoot('C:/x'), ['C:', '/', 'x']);
  assert.deepEqual(pyfs.ntSplitRoot('//?/C:/x'), ['//?/C:', '/', 'x']);
  assert.deepEqual(pyfs.ntSplitRoot('//?/UNC/srv/share/x'), ['//?/UNC/srv/share', '/', 'x']);
  // The slices come back in the CALLER's separators, which is how `ntpath` returns them.
  assert.deepEqual(pyfs.ntSplitRoot('\\\\srv\\share\\x'), ['\\\\srv\\share', '\\', 'x']);
});

test("PureWindowsPath: `//a/b` has a root and `///a` does not — the empty-substring rule", () => {
  // pathlib puts a root back on a bare `\\server\share` when the drive splits into FOUR
  // pieces whose third is not `?` or `.`. That test is `drv_parts[2] not in '?.'`, a
  // SUBSTRING test, and `'' in '?.'` is True — so `///a`, whose third piece is empty, keeps
  // an empty root and stays RELATIVE. Spelled as two character comparisons it came out
  // absolute, and the conformance case caught it on this laptop before a CI cycle was spent.
  assert.deepEqual(pyfs.parseWindowsPath('//a/b'), { drive: '\\\\a\\b', root: '\\', tail: [] });
  assert.deepEqual(pyfs.parseWindowsPath('///a'), { drive: '\\\\\\a', root: '', tail: [] });
  assert.equal(pyfs.winIsAbsolute('///a'), false);
  assert.equal(pyfs.winIsAbsolute('//a'), false);
  assert.equal(pyfs.winIsAbsolute('//a/b'), true);
  assert.equal(pyfs.winIsAbsolute('/a'), false);
  assert.equal(pyfs.winIsAbsolute('C:/a'), true);
  assert.equal(pyfs.winIsAbsolute('C:a'), false);
  assert.deepEqual(pyfs.winParents('//a/b'), []);
  assert.deepEqual(pyfs.winParents('/a/b/c'), ['\\a\\b', '\\a', '\\']);
  assert.deepEqual(pyfs.winParents('a/b'), ['a', '.']);
  assert.deepEqual(pyfs.winParents('/a/b/../c'), ['\\a\\b\\..', '\\a\\b', '\\a', '\\']);
  // `_format_parsed_parts`' third arm: an anchorless path whose FIRST component would parse
  // as a drive gets a `.` in front, so it cannot be re-read as drive-relative.
  assert.equal(pyfs.winFormat('', '', ['C:x', 'y']), '.\\C:x\\y');
  assert.equal(pyfs.winFormat('', '', ['a', 'C:x']), 'a\\C:x');
  assert.equal(pyfs.winStr(''), '.');
  assert.equal(pyfs.winStr('//a/b'), '\\\\a\\b\\');
  assert.equal(pyfs.winStr('/a/./b'), '\\a\\b');
});

test('ntpath.isabs is not PureWindowsPath.is_absolute, and realpath needs the first one', () => {
  // CPython's own source labels the difference a LEGACY BUG and keeps it: `isabs` looks at
  // three characters and calls any leading separator absolute. `realpath` prepends the cwd
  // on `not isabs(path)`, so using pathlib's stricter reading there joins the cwd onto a
  // path Windows already resolves from the drive root.
  assert.equal(pyfs.ntIsAbs('/a'), true);
  assert.equal(pyfs.winIsAbsolute('/a'), false);
  assert.equal(pyfs.ntIsAbs('//a'), true);
  assert.equal(pyfs.ntIsAbs('///a'), true);
  assert.equal(pyfs.ntIsAbs('C:/a'), true);
  assert.equal(pyfs.ntIsAbs('C:a'), false);
  assert.equal(pyfs.ntIsAbs('C:'), false);
  assert.equal(pyfs.ntIsAbs('a'), false);
  assert.equal(pyfs.ntIsAbs(''), false);
  // `ntpath.split` at 3.12 has NO fallback to the unstripped head.
  assert.deepEqual(pyfs.ntSplit('//a/b/c'), ['//a/b/', 'c']);
  assert.deepEqual(pyfs.ntSplit('////a/b'), ['////a', 'b']);
  assert.deepEqual(pyfs.ntSplit('C:'), ['C:', '']);
  assert.deepEqual(pyfs.ntSplit('\\a\\b'), ['\\a', 'b']);
  assert.deepEqual(pyfs.ntSplit('a'), ['', 'a']);
});

test('ntpath.join: a bare UNC share gains a separator the POSIX join never adds', () => {
  assert.equal(pyfs.ntJoin('//a', 'facts'), '//a\\facts');
  assert.equal(pyfs.winStr(pyfs.ntJoin('//a', 'facts')), '\\\\a\\facts\\');
  assert.equal(pyfs.winStr(pyfs.ntJoin('///a', 'facts')), '\\\\\\a\\facts');
  assert.equal(pyfs.winStr(pyfs.ntJoin('/a/b/..', 'facts')), '\\a\\b\\..\\facts');
  // A later part with its own root replaces what came before; a DIFFERENT drive replaces
  // even the drive.
  assert.equal(pyfs.ntJoin('/a', '/b'), '/b');
  assert.equal(pyfs.ntJoin('C:/a', 'D:/b'), 'D:/b');
  assert.equal(pyfs.ntJoin('C:/a', 'C:b'), 'C:/a\\b');
});

test('with_suffix rebuilds the path in the flavour, so the separators change too', () => {
  // Slicing the input string kept `/f/a.md.tmp`; `PureWindowsPath` prints `\f\a.md.tmp`.
  assert.equal(pyfs.winWithSuffix('/f/a.md', '.md.tmp'), '\\f\\a.md.tmp');
  assert.equal(pyfs.winWithSuffix('/f/.md', '.md.tmp'), '\\f\\.md.md.tmp');
  assert.equal(pyfs.winWithSuffix('/f/a.', '.md.tmp'), '\\f\\a..md.tmp');
  assert.equal(pyfs.winName('/f/a.md'), 'a.md');
  assert.equal(pyfs.winName('//a/b'), '');
});

test('OSError.__str__ prints the WinError when there is one, and the errno when there is not', () => {
  // CPython carries BOTH numbers for a Win32 call and `__str__` shows only the Win32 one.
  // MEASURED, run 32646521489: `[WinError 3] The system cannot find the path specified`
  // where this port printed `[Errno 2] No such file or directory` for the same `os.replace`.
  const win = new pyfs.PyOSError(2, 'ENOENT', 'The system cannot find the path specified',
    'C:\\a\\x.tmp', 'C:\\a\\missing\\y.json', 3);
  assert.equal(
    win.message,
    "[WinError 3] The system cannot find the path specified: 'C:\\\\a\\\\x.tmp' -> 'C:\\\\a\\\\missing\\\\y.json'",
  );
  // The errno is still THERE, it is just not what gets printed; `except FileNotFoundError`
  // still catches, which is why the subclass comes off the code and not off the winerror.
  assert.equal(win.errno, 2);
  assert.equal(win.winerror, 3);
  assert.equal(win.name, 'FileNotFoundError');
  const posix = new pyfs.PyOSError(2, 'ENOENT', 'No such file or directory', '/a/x.md');
  assert.equal(posix.message, "[Errno 2] No such file or directory: '/a/x.md'");
  assert.equal(posix.winerror, null);
});

test('winerrorFor re-derives the distinction libuv threw away', () => {
  // ENOENT is the whole problem: `ERROR_FILE_NOT_FOUND` (2) and `ERROR_PATH_NOT_FOUND` (3)
  // both arrive as one code, so which one Win32 raised has to be worked out from which
  // component is missing. `exists` is injected, so this is a pure function with a node that
  // can go red on a laptop instead of only on a runner.
  // The injected `exists` is asked about a PARENT, and `pyParent` renders in the running
  // platform's flavour — so a POSIX-spelled set never matches on Windows and every ENOENT
  // came back 3. MEASURED, run 32649940727: this test was wrong, not the derivation.
  const present = (set) => (p) => set.includes(p.replace(/\\/g, '/'));
  const here = present(['/a', '/a/there']);
  // A one-name call: the leaf is missing beside an existing parent -> 2.
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', '/a/gone', null, here), 2);
  // ...and a missing DIRECTORY component -> 3.
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', '/a/nope/gone', null, here), 3);
  // A two-name call opens the SOURCE first, so a missing source is 2 even when the
  // destination's directory is missing too. Both arms measured on run 32646521489.
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', '/a/there', '/a/nope/b', here), 3);
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', '/a/gone', '/a/b', here), 2);
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', '/a/gone', '/a/nope/b', here), 2);
  // A directory listing uses the NAMED path as a directory, so a missing one is already a
  // missing directory component.
  assert.equal(pyfs.winerrorFor('ENOENT', 'scandir', '/a/gone', null, here), 3);
  assert.equal(pyfs.winerrorFor('ENOENT', 'scandir', '/a/there', null, here), 2);
  // The one-to-one arms.
  assert.equal(pyfs.winerrorFor('ENOTDIR', 'win32', '/a', null, here), 267);
  assert.equal(pyfs.winerrorFor('EEXIST', 'win32', '/a', null, here), 183);
  assert.equal(pyfs.winerrorFor('EACCES', 'win32', '/a', null, here), 5);
  assert.equal(pyfs.winerrorFor('ELOOP', 'win32', '/a', null, here), 1921);
  // WIN32 VALIDATES THE NAME BEFORE IT LOOKS AT THE DISK, so a component holding a
  // forbidden character is ERROR_INVALID_NAME and never a not-found — libuv folds it into
  // ENOENT and the port said "The system cannot find the file specified" for a name Windows
  // had refused to parse. MEASURED, run 32649940727.
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\two\nlines.md'), true);
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\tab\there.md'), true);
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\quote"both.md'), true);
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\ret\rurn.md'), true);
  // The drive's colon is part of the ANCHOR, and a backslash SPLITS a name rather than
  // sitting in one — neither makes the path invalid.
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\back\\slash.md'), false);
  assert.equal(pyfs.ntNameIsInvalid('C:\\a\\thai-ความจำ.md'), false);
  assert.equal(pyfs.ntNameIsInvalid(null), false);
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', 'C:\\a\\two\nlines.md', null, here), 123);
  assert.equal(pyfs.winerrorFor('ENOENT', 'win32', 'C:\\a\\ok.md', 'C:\\a\\two\nlines.md', here), 123);
  // ...and through the other door, `open()` on such a name is EINVAL, not a not-found.
  assert.equal(pyfs.crtCode('ENOENT', 'C:\\a\\two\nlines.md'), 'EINVAL');
  assert.equal(pyfs.crtCode('ENOENT', 'C:\\a\\ok.md'), 'ENOENT');
  // An unmapped code makes NO claim: a visible `[Errno n]` beats a plausible wrong sentence.
  assert.equal(pyfs.winerrorFor('EWHAT', 'win32', '/a', null, here), null);
  // And `open()` never carries one at all, on any code.
  assert.equal(pyfs.winerrorFor('ENOENT', 'crt', '/a/gone', null, here), null);
  assert.equal(pyfs.winerrorFor('EISDIR', 'crt', '/a', null, here), null);
  // Every wording the derivation can name is one this port can print.
  for (const n of pyfs.WINERROR_NUMBERS) assert.equal(typeof pyfs.pyWinStrerror(n), 'string');
  for (const code of ['ENOENT', 'ENOTDIR', 'EEXIST', 'EACCES', 'EPERM', 'ENOTEMPTY', 'ELOOP',
    'EINVAL', 'ENAMETOOLONG', 'EBUSY']) {
    const n = pyfs.winerrorFor(code, 'win32', '/a/gone', null, here);
    assert.ok(pyfs.WINERROR_NUMBERS.includes(n), `${code} -> ${n} has no wording`);
  }
});

test('the CRT and the Win32 API are two error paths, and open() takes the second one', () => {
  // `open()` on Windows goes through `_wopen`, which sets errno alone; opening a DIRECTORY
  // there is EACCES, not EISDIR, so CPython prints `[Errno 13] Permission denied` for the
  // `.tmp` a clock-out could not write. MEASURED, run 32646521489, six consecutive cases.
  assert.equal(pyfs.crtCode('EISDIR'), 'EACCES');
  // Nothing else moves: these already agree with libuv in both number and wording.
  for (const code of ['ENOENT', 'EACCES', 'EEXIST', 'EINVAL', 'ENOTDIR']) {
    assert.equal(pyfs.crtCode(code), code);
  }
  // And the scandir shape, which is a different syscall rather than a different sentence:
  // `FindFirstFileW(p + "\\*")` uses `p` as a directory component, so a dangling FILE
  // symlink there is ERROR_DIRECTORY and CPython raises NotADirectoryError where libuv
  // reported ENOENT and `count_facts` answered 0.
  assert.equal(pyfs.scandirIsNotADirectory('ENOENT', () => true), true);
  assert.equal(pyfs.scandirIsNotADirectory('ENOENT', () => false), false);
  assert.equal(pyfs.scandirIsNotADirectory('ENOTDIR', () => true), false);
  assert.equal(pyfs.scandirIsNotADirectory('EACCES', () => true), false);
});
