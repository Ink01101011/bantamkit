/**
 * J90-P5 (#316 G4): every member the compiled TypeScript reads off an object an ADAPTER makes.
 *
 * WHY. A read of a member an adapter object does not provide answers `undefined` in the generated
 * Python, silently: `_js_object_get` falls through to `undefined` for a name the class does not
 * list, and a dict an adapter returns answers `undefined` for a key it lacks. That is how J90-P4's
 * `Stats.ino` divergence hid (the hot index keyed its held head on `undefined`). Node's object has
 * every member its type declares, so the TypeScript checker, not a grep, is the list of what the
 * compiled modules read: this walks every property read in the compiled sources with the
 * program's own checker, keeps the ones whose member is declared OUTSIDE the compiled sources, and
 * sorts each into a provider row. A read no row claims is red (`adapter/unclassified`), so a new
 * adapter type cannot be read without a row; a row's provider is then asked (`ref/ts2py_ref.py`,
 * `adapters`) what it really provides, and a member it lacks is red.
 */
import { createRequire } from 'node:module';
import { join, relative, sep } from 'node:path';

/**
 * Receiver type name -> the adapter class (`_ts2py_adapters.<cls>`) whose `_js_own` must list the
 * member. Keyed by the declaring file too, so a compiled class of the same name is not caught.
 */
const CLASSES = [
  { file: 'node_modules/@types/node/fs.d.ts', type: 'Stats', cls: 'Stats' },
  { file: 'node_modules/@types/node/fs.d.ts', type: 'BigIntStats', cls: 'BigIntStats' },
  { file: 'node_modules/@types/node/crypto.d.ts', type: 'Hash', cls: 'Hash' },
  { file: 'node_modules/@types/node/util.d.ts', type: 'TextDecoder', cls: 'TextDecoder' },
  { file: 'node_modules/typescript/lib/lib.es5.d.ts', type: 'Date', cls: 'Date' },
  { file: 'src/memory/skills.ts', type: 'SkillStore', cls: 'SkillStore' },
  { file: 'src/storage/coldfs.ts', type: null, cls: '_ColdFs' },
  { file: 'src/storage/retentionfs.ts', type: null, cls: '_RetentionFs' },
];

/** Declaring file -> the adapter (or shim) that builds that object as a plain dict. */
const DICTS = [
  { file: 'src/storage/nativefact.ts', provider: 'parse_native' },
  { file: 'src/memory/dreamre.ts', provider: 'py_relative_scan' },
  { file: 'src/memory/grantconfig.ts', provider: 'parse_config_document' },
  { file: 'src/pyjson.ts', provider: 'parse_json' },
  { file: 'src/touch/recallfile.ts', provider: 'file_links' },
  { file: 'src/touch/context.ts', provider: 'component._context_in' },
];

/**
 * Reads the generated Python never answers through an adapter object's member list, each with why
 * an unprovided member cannot hide there.
 */
function runtimeRow(file, type, member) {
  if (/node_modules\/typescript\/lib\/lib\./.test(file)) {
    return 'a JS builtin the runtime implements (a list, str, Map, Set, Error, Math, JSON...): not an adapter object';
  }
  if (file.startsWith('node_modules/@types/node/')) {
    if (type.startsWith('typeof import(') || ['PlatformPath', 'Process', 'Performance', 'BufferConstructor'].includes(type)) {
      return 'a module name ts2py resolves at compile time (an unlisted name is a compile error, adapters.rs)';
    }
    if (/^(Buffer|NonSharedBuffer)\b/.test(type)) {
      return 'a Buffer method the runtime implements (`_js_m_*`; any other is refused)';
    }
    if (type === 'ErrnoException' && member === 'code') {
      return "an exception's `code` (`_js_get`'s exception branch; any other member is refused)";
    }
  }
  if (file === 'src/memory/pyfs.ts' && type === 'PyOSError' && member === 'code') {
    return "an exception's `code` (`_js_get`'s exception branch; any other member is refused)";
  }
  return null;
}

/**
 * Every property read in `sources` whose member is declared outside them, each sorted into a row.
 * Returns `{ classes, dicts, runtime, unclassified, count }`: `classes[cls]` the members read off
 * that class; `dicts[provider]` one entry per object shape read (`literals`: its string-literal
 * members, a discriminant such as `kind: 'str'`; `members`: what is read off it).
 */
export function adapterReads(repoRoot, sources) {
  const runtimeTs = join(repoRoot, 'runtime-ts');
  const require = createRequire(join(runtimeTs, 'package.json'));
  const ts = require('typescript');
  const config = ts.getParsedCommandLineOfConfigFile(join(runtimeTs, 'tsconfig.json'), {}, {
    ...ts.sys,
    onUnRecoverableConfigFileDiagnostic(d) {
      throw new Error(ts.flattenDiagnosticMessageText(d.messageText, '\n'));
    },
  });
  const files = sources.map((s) => join(repoRoot, s));
  const program = ts.createProgram(files, config.options);
  const checker = program.getTypeChecker();
  const compiled = new Set(files.map((f) => f.split(sep).join('/')));
  // A declaration under node_modules is named from there on (a worktree may link node_modules
  // from another checkout); anything else relative to runtime-ts.
  const rel = (f) => {
    const p = f.split(sep).join('/');
    const at = p.lastIndexOf('/node_modules/');
    return at >= 0 ? p.slice(at + 1) : relative(runtimeTs, f).split(sep).join('/');
  };
  const classes = {};
  const dicts = {};
  const runtime = {};
  const unclassified = new Set();
  let count = 0;
  for (const file of files) {
    const sf = program.getSourceFile(file);
    if (!sf) throw new Error(`adapter audit: ${file} is not in the program`);
    const visit = (node) => {
      let member = null;
      let receiver = null;
      if (ts.isPropertyAccessExpression(node)) {
        member = node.name.text;
        receiver = node.expression;
      } else if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
        member = node.argumentExpression.text;
        receiver = node.expression;
      }
      if (member !== null) {
        const type = checker.getTypeAtLocation(receiver);
        for (const part of type.isUnion() ? type.types : [type]) {
          const prop = checker.getPropertyOfType(checker.getApparentType(part), member);
          const decls = (prop && prop.declarations) || [];
          // No declaration: an index signature (`Record<string, unknown>`, JSON data), not an
          // object anything builds with a fixed member list.
          if (decls.length === 0) continue;
          const where = decls.map((d) => d.getSourceFile().fileName.split(sep).join('/'));
          if (where.some((f) => compiled.has(f))) continue;
          count += 1;
          const declFile = rel(where[0]);
          const name = checker.typeToString(part);
          const site = `${relative(repoRoot, file).split(sep).join('/')}:${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
          // `new Date(...).toISOString()` is lowered at compile time (lower.rs, J88-2 / J89-4a),
          // never read off the adapter's `Date`.
          if (member === 'toISOString' && name === 'Date' && ts.isNewExpression(receiver)) {
            (runtime['`new Date(...).toISOString()`, which lower.rs lowers to the runtime\'s ISO formatter'] ??= new Set()).add(`${name}.${member}`);
            continue;
          }
          const cls = CLASSES.find((c) => c.file === declFile && (c.type === null || c.type === name));
          if (cls) {
            (classes[cls.cls] ??= new Set()).add(member);
            continue;
          }
          const dict = DICTS.find((d) => d.file === declFile);
          if (dict) {
            const literals = {};
            const declared = [];
            for (const p of checker.getPropertiesOfType(part)) {
              declared.push(p.name);
              const t = checker.getTypeOfSymbol(p);
              if (t.isStringLiteral()) literals[p.name] = t.value;
            }
            const key = `${dict.provider} ${JSON.stringify(declared.sort())} ${JSON.stringify(literals)}`;
            const row = ((dicts[dict.provider] ??= {})[key] ??= { literals, members: new Set() });
            row.members.add(member);
            continue;
          }
          const why = runtimeRow(declFile, name, member);
          if (why) {
            (runtime[why] ??= new Set()).add(`${name}.${member}`);
            continue;
          }
          unclassified.add(`${declFile} ${name}.${member} (${site})`);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return {
    count,
    classes: Object.fromEntries(Object.entries(classes).map(([k, v]) => [k, [...v].sort()])),
    dicts: Object.fromEntries(
      Object.entries(dicts).map(([k, rows]) => [
        k,
        Object.values(rows).map((r) => ({ literals: r.literals, members: [...r.members].sort() })),
      ]),
    ),
    runtime: Object.fromEntries(Object.entries(runtime).map(([k, v]) => [k, [...v].sort()])),
    unclassified: [...unclassified].sort(),
  };
}
