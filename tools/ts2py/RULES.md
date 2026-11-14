# ts2py rule ledger

Every lowering rule ts2py applies, the job that introduced it, and what each later job did to
it. `SUBSET.md` is the contract (each rule with the JS semantic it preserves); this file is the
count, the input to #315's "new versus reused compiler rules" and to the rollout estimate.

- **J85**: the #314 pilot, input `runtime-ts/src/workplan.ts`.
- **J86**: #315, input the fact-file codec (`runtime-ts/src/memory/pyyaml.ts` and
  `runtime-ts/src/memory/factfile.ts`).

Status: **reused** (J86 compiled the codec with the J85 rule as it was), **extended** (J86 changed
or widened it; the J86 column says how), **new** (J86 added it).

## Summary (J86)

| | count |
|---|---|
| J85 rules | 59 |
| reused unchanged by J86 | 32 |
| extended by J86 | 27 |
| new in J86 | 44 |
| adapter entries (J86) | 4: 2 functions (`pyFloatRepr`, `pyStrip`), 2 classes (`TextDecoder.decode`, `Date` with 3 getters) |
| runtime support module-level names | J85 64, J86 139 (75 added; 14 J85 helpers changed, each only for value kinds J85 never produced or toward JS where J85 differed) |

Counted from the tables below. The runtime names were counted with
`grep -oE "^(def|class) [A-Za-z_0-9]+|^_JS[A-Z_0-9]* =" src/runtime.py` against the J85 file.

The workplan module J85 generated is byte-identical when compiled by J86's ts2py
(`runtime-py/src/bantamkit/_generated/workplan.py`); `_ts2py_runtime.py` was regenerated, and
`node tools/conformance/run.mjs --suite ts2py` (448 cases) and `--suite workplan` (294 cases)
pass with it.

## J85 rules

| # | Rule | J86 |
|---|---|---|
| 1 | `function f` -> `def _f` (private) | extended: default parameters; a body that can run off its end returns `undefined` |
| 2 | `export function f` -> `__all__` | reused |
| 3 | module-level `const f = () =>` -> `def` | extended: as rule 1 |
| 4 | module-level `const X = e` | reused |
| 5 | type-only syntax erased | reused |
| 6 | `const` / `let` declaration | reused |
| 7 | `x = e` statement | extended: `x` must be a local; one an enclosing function owns is `nonlocal` in a closure |
| 8 | `o.k = e` -> `_js_put` | extended: `o[k] = e`; class instances (attributes, frozen); `__proto__` refused at run time |
| 9 | `if / else if / else` | reused |
| 10 | `while` | reused |
| 11 | `for (const x of xs)` | reused |
| 12 | `for (const [i, x] of xs.entries())` | reused |
| 13 | `for (const [a, b] of xs)` | reused |
| 14 | unlabelled `break` / `continue` | extended: a `break` inside a switch case is accepted only as its last statement |
| 15 | `return` / bare `return` | reused |
| 16 | expression statement | reused |
| 17 | number literal | reused |
| 18 | string literal | extended: its edge units are tracked (for rules 19 and 35) |
| 19 | template literal | extended: a junction where two surrogate halves may meet is `_js_cat`; `String()` of a BigInt and of an instance (`toString`) |
| 20 | `true` / `false` / `null` / `undefined` | reused |
| 21 | array literal, spread | reused |
| 22 | object literal (static keys) | extended: object spread `{...x}` |
| 23 | `o.k` / `o[k]` -> `_js_get` | extended: a string indexed by UTF-16 unit; class instances; a match array's `index` / `input`; an inherited `Object.prototype` name raises |
| 24 | `.length` | reused |
| 25 | `.size` | reused |
| 26 | `typeof` | extended: `bigint` |
| 27 | `===` / `!==` | extended: BigInts by value; reused by `switch` with a lowered discriminant |
| 28 | `== null` / `!= null` | reused |
| 29 | `??` | reused |
| 30 | `\|\|` / `&&` | reused |
| 31 | `!` and conditions (ToBoolean) | extended: `0n` is falsy |
| 32 | `c ? a : b` | reused |
| 33 | `<` `<=` `>` `>=` | extended: a BigInt against a BigInt or a number, by exact value |
| 34 | `a - b`, unary `-` | extended: unary `-` of anything but a non-zero literal is `_js_neg` (`-0`, BigInt); `-` on two BigInts exact |
| 35 | `a + b` | extended: two BigInts exact; string junction rule (`_js_cat`) |
| 36 | call of a module function or local | extended: calling a class without `new` refused |
| 37 | `new Map` / `new Set` | extended: `new` of compiled classes, `Error`, `TypeError`, adapter classes, `RegExp` (new rules 3, 11, 13, 44) |
| 38 | regex literal (no flags) | extended: the `g` flag; `\xHH` / `\uHHHH`; fixed-width lookbehind |
| 39 | inline arrow callback -> `lambda` | extended: an array-pattern parameter |
| 40 | `as` / `!` / generics / `p?:` erased | reused |
| 41 | `Array.isArray` | reused |
| 42 | `Number.isInteger` | reused |
| 43 | `JSON.stringify` | reused |
| 44 | `Map` `has` / `get` / `set` | reused |
| 45 | `Set` `has` / `add` | reused |
| 46 | `.every` / `.some` | reused |
| 47 | `.find` | reused |
| 48 | `.map` | reused |
| 49 | `.push` | extended: a spread argument |
| 50 | `.slice` | extended: strings, by UTF-16 unit |
| 51 | `.join` | extended: two halves that meet form one character |
| 52 | `.sort` | reused |
| 53 | `.entries` | reused |
| 54 | `.includes` | extended: strings by UTF-16 unit |
| 55 | `.startsWith` | extended: by UTF-16 unit |
| 56 | `.split` | extended: by UTF-16 unit (`""` gives code units) |
| 57 | `re.test` | reused (a `g` regex raises: rule 38) |
| 58 | names (snake_case, keywords, builtin guard, collisions, reserved `_js`) | extended: classes keep their name; members their JS spelling; the builtin guard lists the names the J86 runtime calls |
| 59 | output (header, determinism, runtime inline or imported) | extended: imports from other compiled modules and the adapter module; several modules per run (`--out-dir`) |

## J86 rules (new)

| # | Rule | Pinned by |
|---|---|---|
| 1 | value import from a module compiled in the same run -> `from .m import a` | `codec.rs` imports test, codec round trip |
| 2 | import through the adapter seam; any other import a compile error naming it | `codec.rs` imports test |
| 3 | `new` of a global adapter class (`TextDecoder`, `Date`) | codec round trip (`TextDecoder`) |
| 4 | `export { a }` | codec round trip (`export { pyStrip }`) |
| 5 | `class C` -> `class C(_JsObject)` with `_js_own` / `_js_own_methods` | probe |
| 6 | class fields, initialised first, in order | probe |
| 7 | constructor -> `__init__` (extra arguments ignored) | probe |
| 8 | methods -> `def m(self, ...)` | probe |
| 9 | getters -> `@property` | probe (`size`) |
| 10 | `extends Error` -> `_JsError` (`message`, inherited `name`, `toString`) | probe, `throw_boom` |
| 11 | `new Error` / `new TypeError` | probe, probe2 |
| 12 | `this` / `this.x` / `this.m()` (declared members only) | probe; refusals |
| 13 | `new C(...)` of a compiled class | probe |
| 14 | `instanceof` | probe |
| 15 | method of a compiled class on another receiver -> `_js_invoke` | probe2 (`twice`), codec |
| 16 | a name a class shares with a builtin -> `_js_dispatch` | probe (`push`, `add`) |
| 17 | `Object.freeze(this)` | `frozen_write` |
| 18 | `throw` | `throw_boom`, codec errors |
| 19 | `switch` -> if-chain over `===` | probe (`kind`); refusals |
| 20 | `for (;;)` | probe (`scan`) |
| 21 | `+=` / `-=` / `*=` on a local or `this.x` | probe |
| 22 | `a = b = e` | probe |
| 23 | `const f = () => ...` in a function -> nested `def` + `nonlocal` | probe (`skip`); refusal inside a loop |
| 24 | default parameters | probe (`start = 10`, `times = 1`) |
| 25 | `const [a, , b] = e` | probe |
| 26 | `[a, b] = e` | probe |
| 27 | `const { a } = e` | probe |
| 28 | `*`, `/`, `%` as JS (`-0`, Infinity, NaN, sign of `%`) | probe |
| 29 | BigInt: literal, `BigInt()`, arithmetic, comparison | probe, `mix_big_int`, `bigint_differences_compose_like_node` |
| 30 | `Infinity`, `NaN` | probe2 |
| 31 | `in` | probe |
| 32 | `Object.prototype`, `Object.getPrototypeOf` | probe |
| 33 | `Object.keys`, `Object.entries` | probe, probe2 |
| 34 | `Math.floor` / `abs` / `max` / `min` | probe, probe2 |
| 35 | `Number()`, `Number.isNaN`, `String()`, `parseInt` | probe |
| 36 | `String.fromCodePoint`, `.codePointAt` (UTF-16) | probe |
| 37 | `.indexOf`, `.lastIndexOf` (UTF-16) | probe |
| 38 | `.padStart`, `.padEnd`, `.repeat` | probe |
| 39 | `.toLowerCase`, `.toUpperCase` (ASCII; non-ASCII raises) | probe |
| 40 | `.replace` (string, regex, `g`) | probe |
| 41 | `.exec` (match array) | probe |
| 42 | `.toString(radix)` | probe |
| 43 | `.reverse`, `.pop`, `.filter` | probe2 |
| 44 | `new RegExp(`...${n}...`)` with whole-count substitutions | probe; refusal |

"probe" and "probe2" are `tests/fixtures/j86_probe.ts`, run by `tests/codec.rs`
(`j86_semantics_match_node`); every expected value there is Node's output for the same file.
"codec round trip" is `codec_compiles_and_round_trips_like_node`, which compiles the real
`pyyaml.ts` and `factfile.ts`. Two runtime mutations were checked to turn the probe test red
(Python's `%` in `_js_mod`; code-point indexing in `_js_get`).

## Adapters (J86)

Declared in `src/adapters.rs`, written in `src/adapters.py`. Measured against Node's own
implementation (runtime-ts `dist/`) on 2026-11-15:

| TypeScript | Python | Why it is the same function | Measurement |
|---|---|---|---|
| `pyFloatRepr` (`runtime-ts/src/memory/pyfs.ts`) | `py_float_repr(x)` = `repr(float(x))` | Python is the reference: the TypeScript ports CPython's `repr(float)` | 120,019 doubles (100,000 random bit patterns, 20,000 short decimals, 19 edge values incl. ±0, NaN, ±Infinity, 5e-324, 1e16, 1e17): 0 disagreements |
| `pyStrip` (`runtime-ts/src/pysem.ts`) | `py_strip(s)` = `s.strip()` | Python is the reference: the TypeScript ports `str.strip()`; it builds its regex at run time with a `$&` replacement, which ts2py refuses | all 1,114,112 codepoints: the stripped sets are the same 29 (symmetric difference 0), and none is stripped from inside a string; 20,000 random strings over whitespace, astral and lone-surrogate characters: 0 disagreements |
| `TextDecoder` (Node global) | `TextDecoder('utf-8').decode(b)` = `bytes(b).decode('utf-8', 'replace')` minus one leading U+FEFF | WHATWG UTF-8 decode replaces each maximal invalid subpart with one U+FFFD and drops a BOM; CPython's `replace` handler substitutes the same subparts | 30,000 random byte strings biased to UTF-8 edge bytes (10% with a BOM): 0 disagreements |
| `Date` (Node global) | `new Date()` (no argument) with `getFullYear` / `getMonth` / `getDate` from `datetime.datetime.now()` | Python is the reference: the one use, `todayLocal`, is defined by its doc comment as `date.today().isoformat()` (local) | not measured (time-dependent); a `Date` with an argument raises |

`pysem.ts` is therefore not compiled: the codec reaches only `pyStrip` from it.
