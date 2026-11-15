#!/usr/bin/env node
// The #316 census (docs/roadmap-1.0.0.md, "Estimate for #316, by dependency group"): per
// `runtime-ts/src` module, the executable syntax kinds, builtin call names and Node-builtin calls it
// uses, against what ts2py already lowers (the modules it compiles), then the estimate by #313's
// dependency groups. Committed by J86-6 (J86-R finding 5b) from the J86-3 scratch scripts, unchanged
// in what they count.
//
//   node tools/ts2py/census.mjs [--src <runtime-ts/src>] [--json <out.json>]
//
// It parses with the TypeScript compiler API (`ts.createSourceFile`, no type checker), loaded from
// `runtime-ts/node_modules` (`cd runtime-ts && npm ci`). The builtin names come from the RUNNING
// Node's own prototypes and globals, so a different Node major can move a call-name count.
// Prints one JSON row per group, then the totals row the roadmap's table ends with.
import { createRequire } from 'node:module';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i === -1 ? dflt : args[i + 1];
};
const SRC = resolve(opt('--src', join(repo, 'runtime-ts', 'src')));
const ts = createRequire(join(repo, 'runtime-ts', 'package.json'))('typescript');

// ------------------------------------------------------------------------------- the census

const files = [];
(function walk(d) {
  for (const f of readdirSync(d).sort()) {
    const p = join(d, f);
    if (statSync(p).isDirectory()) walk(p);
    else if (f.endsWith('.ts')) files.push(p);
  }
})(SRC);
const mod = (p) => relative(SRC, p).replace(/\.ts$/, '');
// Pure-type and trivia kinds lower to nothing.
const SKIP = new Set(['SourceFile', 'EndOfFileToken', 'Identifier', 'TypeReference', 'StringKeyword', 'NumberKeyword', 'BooleanKeyword', 'AnyKeyword', 'UnknownKeyword', 'VoidKeyword', 'NeverKeyword', 'UndefinedKeyword', 'ObjectKeyword', 'BigIntKeyword', 'SymbolKeyword', 'TypeAliasDeclaration', 'InterfaceDeclaration', 'PropertySignature', 'MethodSignature', 'UnionType', 'IntersectionType', 'ArrayType', 'TupleType', 'LiteralType', 'TypeLiteral', 'FunctionType', 'TypeOperator', 'IndexedAccessType', 'TypeQuery', 'TypeParameter', 'TypePredicate', 'ParenthesizedType', 'ExpressionWithTypeArguments', 'QualifiedName', 'JSDoc', 'JSDocText', 'ImportSpecifier', 'NamedImports', 'ImportClause', 'ExportSpecifier', 'NamedExports', 'ReadonlyKeyword', 'ExportKeyword', 'DeclareKeyword', 'ConstKeyword', 'PrivateKeyword', 'PublicKeyword', 'ProtectedKeyword', 'StaticKeyword', 'AbstractKeyword', 'AsyncKeyword', 'AsExpression', 'NonNullExpression', 'SatisfiesExpression', 'TypeAssertionExpression', 'IndexSignature', 'MappedType', 'ConditionalType', 'InferType', 'TemplateLiteralType', 'TemplateLiteralTypeSpan', 'RestType', 'OptionalType', 'NamedTupleMember', 'ThisType', 'ImportType', 'LastTypeNode', 'ColonToken', 'QuestionToken', 'DotDotDotToken', 'ExclamationToken', 'EqualsGreaterThanToken', 'HeritageClause', 'Parameter', 'VariableDeclarationList', 'Block', 'ExpressionStatement', 'CaseBlock', 'SyntaxList']);
const KIND = (k) => ts.SyntaxKind[k];
const PROTO = new Set();
for (const P of [Array, String, Map, Set, RegExp, Number, Promise, Date, Uint8Array, Buffer, Object, Error, BigInt, WeakMap, Function]) {
  for (const k of Object.getOwnPropertyNames(P.prototype)) if (k !== 'constructor') PROTO.add(k);
}

function census(p) {
  const text = readFileSync(p, 'utf8');
  const sf = ts.createSourceFile(p, text, ts.ScriptTarget.Latest, true);
  const kinds = {};
  const methods = {};
  const builtins = new Set();
  const internal = new Set();
  // Names this module declares or imports from an internal module: calls to them are user code,
  // not a compiler rule. Names imported from a Node builtin are adapter calls, keyed by module.
  const local = new Set();
  const nodeName = new Map();
  (function d(n) {
    if ((ts.isFunctionDeclaration(n) || ts.isClassDeclaration(n) || ts.isVariableDeclaration(n) || ts.isParameter(n)) && n.name && ts.isIdentifier(n.name)) local.add(n.name.text);
    if (ts.isBindingElement(n) && ts.isIdentifier(n.name)) local.add(n.name.text);
    if (ts.isImportDeclaration(n)) {
      const s = n.moduleSpecifier.text;
      const c = n.importClause;
      const names = [];
      if (c && c.name) names.push(c.name.text);
      if (c && c.namedBindings) {
        if (ts.isNamespaceImport(c.namedBindings)) names.push(c.namedBindings.name.text);
        else for (const e of c.namedBindings.elements) names.push(e.name.text);
      }
      for (const x of names) {
        if (s.startsWith('.')) local.add(x);
        else nodeName.set(x, s);
      }
    }
    ts.forEachChild(n, d);
  })(sf);
  const add = (o, k) => (o[k] = (o[k] || 0) + 1);
  (function v(n) {
    const k = KIND(n.kind);
    // a declaration-only `declare` / type position contributes nothing executable
    if (ts.isTypeNode(n) && !ts.isExpressionWithTypeArguments(n)) return;
    if (ts.isInterfaceDeclaration(n) || ts.isTypeAliasDeclaration(n)) return;
    if (!SKIP.has(k)) add(kinds, k);
    if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) {
      const s = n.moduleSpecifier && n.moduleSpecifier.text;
      if (s) {
        if (s.startsWith('.')) internal.add(relative(SRC, resolve(dirname(p), s)).replace(/\.js$/, ''));
        else builtins.add(s);
      }
    }
    if ((ts.isCallExpression(n) || ts.isNewExpression(n)) && n.expression) {
      const e = n.expression;
      if (ts.isIdentifier(e)) {
        if (nodeName.has(e.text)) add(methods, `${nodeName.get(e.text)}:${e.text}`);
        else if (!local.has(e.text) && globalThis[e.text] !== undefined) add(methods, `${ts.isNewExpression(n) ? 'new ' : ''}${e.text}()`);
      } else if (ts.isPropertyAccessExpression(e)) {
        const r = e.expression;
        const m = e.name.text;
        if (ts.isIdentifier(r) && nodeName.has(r.text)) add(methods, `${nodeName.get(r.text)}:${m}`);
        else if (ts.isIdentifier(r) && !local.has(r.text) && globalThis[r.text] !== undefined) add(methods, `${r.text}.${m}`);
        else if (PROTO.has(m)) add(methods, `.${m}`);
      }
    }
    ts.forEachChild(n, v);
  })(sf);
  return {
    mod: mod(p),
    lines: text.split('\n').length - (text.endsWith('\n') ? 1 : 0),
    kinds,
    methods,
    builtins: [...builtins].sort(),
    internal: [...internal].sort(),
  };
}

const all = files.map(census);
if (opt('--json')) writeFileSync(opt('--json'), JSON.stringify(all));

// ------------------------------------------------------------------------------ the estimate

const by = Object.fromEntries(all.map((m) => [m.mod, m]));
const mods = all.map((m) => m.mod);
// #313's dependency groups.
const G = {
  G1: ['workplan', 'pricing', 'jobbudget'],
  G2: ['pyjson', 'pyjsonschema', 'memory/factfile', 'memory/pyyaml', 'eventlog', 'tokenledger', 'storage/logsegment', 'pysem'],
  G3: ['memory/store', 'memory/retrieval', 'memory/dream', 'memory/layers', 'memory/queries', 'memory/usage', 'memory/cli', 'memory/native', 'memory/component'],
  G4: ['storage/hotindex', 'storage/coldindex', 'storage/tiers', 'storage/retention', 'storage/retention-child', 'storage/lock', 'storage/index'],
  G5: ['shiftwork'],
  G6: ['skillaudit', 'skillmine', 'skilldraft', 'skillfile', 'skillhost', 'skillinstall', 'memory/skills', 'skillpromote', 'skillpropose', 'skillreport', 'skilllabel'],
  G7: ['hookadapter', 'replynative', 'statusline', ...mods.filter((m) => m.startsWith('touch/'))],
  G8: ['docread', 'charsets', 'repomap', 'htmlentities'],
  G9: ['hostinstall', 'selfupdate', 'updatecheck', 'mcpreport', 'npminstall'],
  G10: ['cli', 'pyargparse', 'memory/pyfs', ...mods.filter((m) => m.startsWith('mcp/'))],
  G11: ['client'],
};
const assigned = new Set(Object.values(G).flat());
G['not in #313 table'] = mods.filter((m) => !assigned.has(m));
// What ts2py compiles today.
const DONE = new Set(['workplan', 'memory/factfile', 'memory/pyyaml']);
const union = (ms, f) => {
  const s = new Set();
  for (const m of ms) for (const k of Object.keys(by[m][f])) s.add(k);
  return s;
};
const J85 = { k: union(['workplan'], 'kinds'), m: union(['workplan'], 'methods') };
const NOW = { k: union([...DONE], 'kinds'), m: union([...DONE], 'methods') };

// The two calibration points: J85 (workplan, 59 rules) and J86 (the codec over workplan, 44 new
// and 27 extended rules, RULES.md).
const codec = ['memory/factfile', 'memory/pyyaml'];
const newK = [...union(codec, 'kinds')].filter((k) => !J85.k.has(k));
const newM = [...union(codec, 'methods')].filter((k) => !J85.m.has(k));
const RULES_J86 = 44 + 27;
const wp = by.workplan;
const wpItems = Object.keys(wp.kinds).length + Object.keys(wp.methods).length;
const perJ85 = 59 / wpItems;
const perJ86 = RULES_J86 / (newK.length + newM.length);
const rLo = Math.min(perJ85, perJ86);
const rHi = Math.max(perJ85, perJ86);
console.log(JSON.stringify({
  typescript: ts.version,
  node: process.version,
  calibration: {
    j85: { lines: wp.lines, kinds: Object.keys(wp.kinds).length, calls: Object.keys(wp.methods).length, items: wpItems, rules: 59, perItem: +perJ85.toFixed(2) },
    j86: { newKinds: newK.length, newCalls: newM.length, rules: RULES_J86, perItem: +perJ86.toFixed(2) },
    lowered: { kinds: NOW.k.size, calls: NOW.m.size },
  },
}));

const isAdapter = (c) =>
  c.startsWith('node:') ||
  /^(Buffer|process|Date|setTimeout|setInterval|clearTimeout|URL|TextDecoder|TextEncoder|structuredClone|queueMicrotask|new URL|new TextDecoder|new TextEncoder|new Date)[.(]/.test(c) ||
  /^new (URL|TextDecoder|TextEncoder|Date|Promise)\(/.test(c) ||
  /^(setTimeout|setInterval)\(/.test(c);
// Cumulative in #313's order: each group's items count as lowered for every later group; G10
// stays per runtime, so it is reported and never added.
const haveK = new Set(NOW.k);
const haveM = new Set(NOW.m);
const total = { lines: 0, newKinds: 0, newCalls: 0, adapters: 0, rules: [0, 0], units: [0, 0], py: [0, 0] };
for (const g of ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9', 'G11', 'G10', 'not in #313 table']) {
  const ms = G[g].filter((m) => !DONE.has(m) && by[m]);
  if (!ms.length) continue;
  const lines = ms.reduce((a, m) => a + by[m].lines, 0);
  const k = union(ms, 'kinds');
  const m = union(ms, 'methods');
  const nk = [...k].filter((x) => !haveK.has(x));
  const nm = [...m].filter((x) => !haveM.has(x));
  const adapters = nm.filter(isAdapter);
  const calls = nm.filter((x) => !isAdapter(x));
  const items = nk.length + calls.length;
  const rules = [Math.round(items * rLo), Math.round(items * rHi)];
  const units = [Math.ceil(rules[0] / 71) + 3, Math.ceil(rules[1] / 59) + 3 + Math.ceil(lines / 2003)];
  const py = [Math.round(lines * 0.58), Math.round(lines * 0.7)];
  console.log(JSON.stringify({ g, mods: ms.length, lines, newKinds: nk.length, kinds: nk.join(' '), newCalls: calls.length, adapters: adapters.length, adapterList: adapters.slice(0, 12).join(' '), rules, units, py }));
  if (g !== 'G10') {
    for (const x of k) haveK.add(x);
    for (const x of m) haveM.add(x);
    total.lines += lines;
    total.newKinds += nk.length;
    total.newCalls += calls.length;
    total.adapters += adapters.length;
    for (const i of [0, 1]) {
      total.rules[i] += rules[i];
      total.units[i] += units[i];
      total.py[i] += py[i];
    }
  }
}
console.log(JSON.stringify({ g: 'G1-G9, G11 and the unassigned', ...total }));
