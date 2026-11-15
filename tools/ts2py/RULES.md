# ts2py rule ledger

Every lowering rule ts2py applies, the job that introduced it, and what each later job did to
it. `SUBSET.md` is the contract (each rule with the JS semantic it preserves); this file is the
count, the input to #315's "new versus reused compiler rules" and to the rollout estimate.

- **J85**: the #314 pilot, input `runtime-ts/src/workplan.ts`.
- **J86**: #315, input the fact-file codec (`runtime-ts/src/memory/pyyaml.ts` and
  `runtime-ts/src/memory/factfile.ts`).
- **J87-3**: #316 G1, input `runtime-ts/src/pricing.ts` and `runtime-ts/src/jobbudget.ts` (J87 rules
  below).

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

## J87 rules (#316: type-directed lowering)

No J85 or J86 rule changed what it answers; J87 adds proofs and, under them, cheaper lowerings of
existing rules (SUBSET.md, *Types*). `tests/types.rs` pins each one taken and not taken, against
Node. The 14 runtime names added (`_js_is_double`, `_js_str_len`, `_js_str_at`, `_js_list_at`,
`_js_units_at`, `_js_units_index_of`, `_js_units_slice`, `_js_str_includes`,
`_js_str_starts_with`, `_js_str_index_of`, `_js_str_slice`, `_js_list_join`, `_js_re_exec`,
`_js_re_replace`) each return what the general helper returns for a proven receiver; no existing
helper changed.

| # | Rule | Where |
|---|---|---|
| J87-1 | facts by greatest fixpoint: re-lower until a round observes what it assumed (64-round cap) | `lib.rs`, `types.rs` |
| J87-2 | a binding's facts: the meet of every value bound to it, flags only | `lower.rs` `bind` |
| J87-3 | a function's return facts: the meet of its returns (falling off the end counts unless the end is unreachable) | `function_body`, `types::completes` |
| J87-4 | typed body for guardable parameter annotations; guarded entry when exported, read as a value or called unproven | `module_function`, `module_call` |
| J87-5 | fresh tuples: an array literal, or a return every path of which is one; a literal index of one | `array`, `computed member` |
| J87-6 | frozen module constants (array: destructuring `for-of` only; object: member reads only) | `global_read`, `member_object`, `for_of` |
| J87-7 | held `const`: read only by a literal index, a nullish or a truthiness test (`peek`) | `resolve`, `peek` |
| J87-8 | nullability ("X or undefined", `null`, `undefined`, match arrays) and narrowing of `const` bindings | `narrowings`, `block`, `if` |
| J87-9 | hoisted UTF-16 view of a never-reassigned `str` binding | `units_of`, `hoist_line` |
| J87-10 | proven-receiver fast paths: `===` of two bools, `.length`, index, `push`, `includes`, `startsWith`, `indexOf`, `slice`, `join`, `test`, `exec`, `replace`, truthiness | `fast_method`, member arms, `truthy` |
| J87-11 | direct unpack of a fresh tuple / a frozen row of exactly the pattern's length | `destructured`, `for_of` |
| J87-12 | a data field named like a method is read as data where the declared type says so (J86-R finding 3 carried) | `declared_data`, `types::TypeDecls` |
| J87-13 | a refusal in a function lowered twice (typed and untyped) is reported once | `lib.rs` |

## J87-3 rules (#316 G1: `pricing`, `jobbudget`)

Census estimate for G1 (`node tools/ts2py/census.mjs`, `docs/roadmap-1.0.0.md`, #315): 5 new
syntax kinds, 5 new builtin calls, 3 Node adapters, 9-11 rules. Rerun on the sources J87-3
compiled (`jobbudget.ts` grew in J87-1F): 560 lines, 5 kinds, 6 calls, 3 adapters, 10-12 rules.
Actual: **11 new rules, 6 extended, the rest reused unchanged; 9 adapter rows** (the census counts
only Node builtins: it reads an import of an uncompiled `src` module as user code, and four were).

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G1-1 | `a ** b` of two non-negative integer literals with an exact result at most 2^53, folded; any other `**` refused | new | `g1.rs` probe; `refusals.rs` (`a ** 2`, `2 ** 54`, `4 ** 0.5`) |
| G1-2 | `Number.MAX_SAFE_INTEGER` -> `9007199254740991` | new | `g1.rs` probe |
| G1-3 | `o?.k` / `o?.[k]`, one optional member read -> `_js_opt_get` | new | `g1.rs` probe; `refusals.rs` (`a?.b.c`, `a?.b?.c`, `a?.()`) |
| G1-4 | `try` / `catch` -> `except Exception` + `_js_catch` (what JS could throw only), handler after the statement | new | `g1.rs` probe and fs-error test; `refusals.rs` (`finally`) |
| G1-5 | a `catch` binding: rethrow only (`throw e` -> `raise` of the caught object) | new | `g1.rs` (`caught`); `refusals.rs` (`String(e)`) |
| G1-6 | C-style `for (let ...; test; assignment)` -> init / `while` / body / update; `continue` refused | extended (J86 rule 20, `for (;;)`) | `g1.rs` probe (`countDown`); `refusals.rs` (`continue`, a non-`let` init) |
| G1-7 | `JSON.parse(text)` -> `_js_json_parse` | new | `g1.rs` probe (numbers, a repeated key, `__proto__`, seven malformed texts) |
| G1-8 | `Number.isFinite` -> `_js_number_is_finite` | new | `g1.rs` probe |
| G1-9 | `Math.trunc` -> `_js_trunc` | new | `g1.rs` probe (`-0`, NaN, a string) |
| G1-10 | `.splice` -> `_js_m_splice` | new | `g1.rs` probe (four shapes) |
| G1-11 | `.reduce` -> `_js_m_reduce` | new | `g1.rs` probe (with and without an initial value; the empty TypeError caught) |
| G1-12 | `Math.max` / `Math.min` with a spread argument proven a list | extended (J86 rule 34) | `g1.rs` probe; `refusals.rs` (`...x` of `any`) |
| G1-13 | `.sort(<adapter function>)` | extended (J85 rule 52) | `g1.rs` real modules (`sortedByCodePoint`, the astral offender) |
| G1-14 | `class E extends <adapter Error class>` (and a class declared above extending one) | extended (J86 rule 10) | `g1.rs` real modules (`PriceTableError`); `refusals.rs` (`extends A`) |
| G1-15 | `node:` specifiers looked up in the adapter table | extended (J86 rule 2) | `g1.rs` (fs errors, real modules) |
| G1-16 | `process.env[k]` / `process.env.K`, a read -> the `process_env` adapter | new | `g1.rs` real modules; `refusals.rs` (`process.argv`) |
| G1-17 | a call proves what its body's returns prove; the J85 `: boolean` annotation rule (`bool_fns`) dropped | extended (J85 rule 36) | `types.rs` (`a_boolean_return_annotation_is_not_proof`) |
| G1-18 | `Object.hasOwn(o, k)` -> `_js_object_has_own`, `Object.fromEntries(entries)` -> `_js_object_from_entries` (J87-3F: `pricing.ts`'s own-key model lookup and rates build) | new | `g1.rs` (`own_key_builtins_answer_like_node`: `__proto__` own, five inherited names not, arrays / strings / a number, `null` thrown, a repeated key, an integer-like key, a missing value) |

Every other construct the two modules use was lowered by an earlier rule unchanged (template
literals with and without substitutions, BigInt arithmetic and `BigInt()`, `in`, object spread,
`Object.keys`, `.filter` / `.map` / `.some` / `.includes` / `.padStart` / `.slice` / `.join`,
`throw` of a compiled Error class, typed bodies and guarded entries). Runtime names added (11):
`_js_number_is_finite`, `_js_trunc`, `_js_m_splice`, `_js_m_reduce`, `_js_opt_get`,
`_js_json_number`, `_JsJsonParseError`, `_js_json_reject_constant`, `_js_json_parse`, `_js_catch`,
`_js_py_value` (the last is for shims, not generated code: Node's `fromJs` lift). No existing
helper changed. Generated: `pricing.py` 340 lines, `jobbudget.py` 179 (519, against the census's
320-386: J87-2's typed bodies and guarded entries write five functions twice).

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

### Adapters (J87-3, #316 G1)

Measured against Node v26.13.0 (`runtime-ts` `dist/` and Node's own builtins) on 2026-11-15:

| TypeScript | Python | Why it is the same function | Measurement |
|---|---|---|---|
| `pyRepr` (`pysem.ts`) | `py_repr(s)` = `repr(s)` | Python is the reference: the TypeScript ports `repr(str)` | the hand-written pricing module used `!r`; `--suite pricing` (astral, quote and newline model names) |
| `cmpCodepoint` (`pysem.ts`) | `cmp_codepoint(a, b)` | Python is the reference: it exists to order as `sorted()` does, by code point; same return values (-1, 1, the length difference) | `--suite pricing` (`astral model names`, `astral unknown top keys`) |
| `assetsRoot` (`assets.ts`) | `assets_root()` = `str(bantamkit.assets.assets_root())` | Python is the reference: `assets.ts` mirrors it arm for arm; each runtime resolves its own pack | `--suite pricing` (`load: the shipped table`) |
| `BantamError` (`errors.ts`) | `BantamError`: `bantamkit.client.BantamError` with `_JsError`'s face; own `name` = the constructing class's JS name | Python is the reference: `errors.ts` says it is the Python base; built lazily (PEP 562) so a module that never uses it does not import `bantamkit.client` | `g1.rs` (`PriceTableError: ...` by `name` and message); `test_pricing.py` (`except BantamError`) |
| `existsSync` (`node:fs`) | `exists_sync(p)` = `os.path.exists(p)`; a non-string argument is false | stat succeeds (symlinks followed), false on any error, as Node | 18 paths (a file, a directory, each with a trailing slash, missing, a dangling symlink, a symlink loop, a symlink to a file, `''`, `.`, `/`, a mode-000 directory, with a trailing slash, and a file inside it, `x//f`, `x/./f`, `x/d/../f`, a missing non-ASCII name): 0 disagreements |
| `readFileSync(p, 'utf8')` (`node:fs`) | `read_file_sync`: `open(p, 'rb').read().decode('utf-8', 'replace')` | Node's UTF-8 decode replaces each maximal invalid subpart with one U+FFFD and keeps a BOM; so does CPython's `replace` handler. A failure is CPython's `OSError` from `open()` | 30,000 random byte strings biased to UTF-8 edge bytes (10% with a BOM) against `Buffer#toString('utf8')`, and 2,000 of them written to files and read back with `readFileSync`: 0 disagreements |
| `join` (`node:path`) | `path_join(*parts)`: `lib/path.js`'s `posix.join` + `normalizeString` (from `path.posix.join.toString()` of Node 26.13), `win32.join` on Windows | the same statements over the same UTF-16-free inputs; on win32, a colon other than a drive's and a path whose last character dropped leaves a reserved device name are refused (Node's newer reserved-name rules there are not ported) | 60,000 random joins of 1-4 parts over separators, dots, drive and UNC prefixes, device names and non-ASCII: 0 disagreements with `path.posix.join`; 41,055 with `path.win32.join` (18,945 refused): 0 disagreements |
| `process.env` (Node global) | `process_env(k)` = `os.environ.get(k, undefined)` | each runtime reads its own process environment; the hand-written module read `os.environ` | `test_pricing.py` (`BANTAMKIT_PRICES`) |

A path holding a NUL or a lone surrogate is refused by both fs adapters (Node throws its own
TypeError for a NUL and writes a lone surrogate as U+FFFD; CPython raises `ValueError` and maps some
lone surrogates to bytes).
