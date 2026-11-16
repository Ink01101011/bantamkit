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

## J88-2 rules (#316 G2: `eventlog`, `tokenledger`, `storage/logsegment`)

Census estimate for the three modules (J88-1, `node tools/ts2py/census.mjs` restricted to them):
1,208 lines, 2 new syntax kinds, 11 new builtin calls, 22 Node adapters, 11-14 rules. Actual:
**16 new rules, 9 extended; 37 new adapter rows, 3 extended.** The census undercounts for the
reason J87-3 gave (an import of an uncompiled `src` module, here `pyfs`, `store` and `lock`, reads
as user code: 15 of the 37 rows) and because it counts a construct once where the lowering needed
a value model (Buffers) or a statement form (`finally`, an arrow as a value) behind it.

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G2-1 | `import * as fs from 'node:fs'`: `fs.name(...)` is that module's adapter row; a name with none, or a namespace import of anything else, refused | new | `g2.rs` (fs probe, real modules); `refusals.rs` (`fs.watch`, `* as m`) |
| G2-2 | an adapter may be a constant, read by name (`LOCK_STALE_MS`, `LOCK_POLL_MS`) | new | `g2.rs` real modules |
| G2-3 | `try` / `finally` (with or without a `catch`) -> Python `try:` / `finally:` | new | `g2.rs` probe (`finallies`: a return through a finally, a throw through two) |
| G2-4 | a `catch` binding read as a value; `_js_get` of a Python exception answers `code` (an `OSError`'s errno name, else `undefined`) and refuses every other property | extended (G1-5) | `g2.rs` probe (`reflection`: `e.code` of a JS Error); fs probe (`code` of every fs failure); `refusals.rs` comment |
| G2-5 | an arrow used as a value (an argument, a `let`) -> a loose nested `def` before the statement (every parameter defaults to `undefined`, extra arguments swallowed, `nonlocal` for what it assigns); refused in a loop and inside a callback lambda | new (J86 rule `nested def` reused) | `g2.rs` probe (`closures`: two closures assigning one local, a call with no arguments); `refusals.rs` (an arrow inside a callback) |
| G2-6 | a block-bodied callback -> the same hoisted `def` | extended (J85 callbacks) | `g2.rs` probe (`doubled`) |
| G2-7 | a module function named as a callback (`rows.map(dumpsLine)`) -> a lambda passing the first N arguments | extended (J85 callbacks) | `g2.rs` probe (`['x','yy'].map(trimmed)`) |
| G2-8 | `o.k op= v` / `o[k] op= v` on a local object, key a local or literal | extended (J86 compound assignment) | `g2.rs` probe (`row.requests += 2`, `row[key] -= 1`); `refusals.rs` (`o.a.n += 1`) |
| G2-9 | `a << b`: folded for small literals, else `_js_shl` (ToInt32, count mod 32) | new | `g2.rs` probe (`1 << 20`); `refusals.rs` (`>>`) |
| G2-10 | `new RangeError(m)`, `instanceof RangeError` | extended (J86 errors) | `g2.rs` probe (`stringify`, `dates`) |
| G2-11 | `static m(...)` -> `@staticmethod`; `C.m(...)` on a compiled class | new | `g2.rs` probe (`Clocked.make()`) |
| G2-12 | `this.f(...)` of a field holding a function -> `self.f(...)` | new | `g2.rs` probe (`Clocked.now`) |
| G2-13 | `x.constructor` (for its `name`) -> `_js_constructor_of` | new | `g2.rs` probe (`names`: Object, Array, a compiled Error, TypeError, Error) |
| G2-14 | `process.pid`, `process.env` as a value | extended (G1-16) | `g2.rs` real modules; `--suite eventlog` (`from_env` with no env) |
| G2-15 | `JSON.stringify(x, replacer, space)` -> `_js_json_stringify_with` | new | `g2.rs` probe (`stringify`: indent 2, a string space, empty containers, a replacer that throws RangeError, `undefined` members, a lone surrogate) |
| G2-16 | `JSON.parse` past CPython's recursion limit -> `_js_json_parse_deep` | extended (G1-7) | `g2.rs` probe (`deepParse`: 50,000-deep array and its malformed twin, 30,000-deep object); J88-2: 20,017 texts, the deep parser and `json.loads` agree on every one |
| G2-17 | `new Date(ms).toISOString()` -> `_js_date_to_iso` | new | `g2.rs` probe (`dates`: toward zero, year 0, -1, 10000, both TimeClip ends, three RangeErrors) |
| G2-18 | `Date.now()` -> `_js_now` | new | `--suite eventlog` beds |
| G2-19 | `.trim()`, `.endsWith()` | new | `g2.rs` probe (`strings`: U+FEFF trimmed, U+001C / U+0085 kept, a lone trail surrogate suffix) |
| G2-20 | `.toLowerCase()` of a non-ASCII string, outside 55 code points and U+03A3 | extended (J86) | `g2.rs` probe (`ÀÉÎ İ ẞ`); J88-2: the 1,462 non-ASCII code points with a lowercase, 55 differ (all assigned after Unicode 15.0); J89-7: the 55 mapped to Node's answer, U+03A3 refused only next to a `Cn` code point or U+0295 / U+1171E (0 wrong against Node 26.13 over every code point alone and in five sigma contexts, on CPython 3.11-3.14); J89-7b: U+03A3 never refused, its Final_Sigma walk run over Node's class for the 307 code points the tables classify apart (0 wrong and 0 refused over every code point in eleven sigma contexts, 402,145 fuzzed strings and 407,044 pairs of the 307, on CPython 3.11-3.14) |
| G2-21 | `m.values()` | new | `g2.rs` probe (`[...m.values()]`) |
| G2-22 | `Object.assign(target, ...sources)` | new | `g2.rs` probe (`Object.assign(new Error, {code})`) |
| G2-23 | `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)` -> `_js_sleep_ms`; any other `Atomics.wait` refused | new | `refusals.rs`; `--suite storage-log` (the #208 drain) |
| G2-24 | Buffers: `bytes` / `bytearray` / `memoryview`, `.length`, `[i]`, `.toString('utf8' / 'hex')`, `.subarray` | new | `g2.rs` probe (`buffers`) and fs probe |
| G2-25 | an adapter function called with `...xs` of a value proven a list | extended (G1-12) | `g2.rs` real modules (`pyJoin(root, ...DEFAULT_RELATIVE_PATH)`) |

Runtime names added (26): `_js_buffer_to_string`, `_js_m_subarray`, `_js_m_endsWith`, `_js_m_trim`,
`_js_m_values`, `_js_to_int32`, `_js_shl`, `_js_now`, `_js_sleep_ms`, `_js_civil`,
`_js_date_to_iso`, `_js_object_assign`, `_js_constructor_of`, `_js_json_gap`, `_js_json_full`,
`_js_json_stringify_with`, `_js_json_parse_deep` and its two patterns, `_JS_BYTES`,
`_JS_LOWER_DIFFERS`, and the `errno` / `time` imports. Changed: `_js_get` (a Buffer's `length` and
index; a Python exception's `code`, any other property refused), `_js_len` (a Buffer),
`_js_m_toString` (a Buffer), `_js_json_parse` (the deep fallback), `_js_m_toLowerCase` (non-ASCII).
Every other generated module (`workplan`, `pyyaml`, `factfile`, `pricing`, `jobbudget`) recompiles
byte for byte unchanged but for the `# ruff: noqa` header, which gains E741 (a TypeScript name
`l` is kept as spelled). Generated: `logsegment.py` 554 lines, `eventlog.py` 225, `tokenledger.py`
468 (1,247, against the census's 1,208 TypeScript lines: typed bodies write 19 functions twice).

## J89-2 rules (#316 G3 U1: `memory/usage`; `memory/retrieval` lowered, then kept hand-written)

Census (J89-1, `node tools/ts2py/census.mjs` over the two modules): retrieval 5 new kinds and 13
calls, usage 5 calls, among them `>>`, postfix `++`/`--`, `.charCodeAt`, `.match`, `.normalize`,
`Math.round`, `Math.log1p`, `Object.is`, `Float64Array`, `DataView`. Actual: **8 new rules, 3
extended, 1 compiler defect fixed, 6 exact runtime fast paths; 5 new adapter rows** (usage's).

**`memory/retrieval.ts` compiled and answered every conformance case, and was NOT shipped
generated by J89-2** (J89-3 shipped it, below; docs/porting.md, *The usage ledger*, has J89-2's
numbers): its BM25 and ranking loops are
per-element arithmetic over arrays and Map values, which the fact system cannot prove numeric, so
each `+`, `/` and index is a JS-semantics call; a 5,000-fact recall went from 6.1 ms to 78 ms
against `test_storage_bar.py`'s declared 15 ms bar, and `bm25_segments`, `rank_columns` and
`weight_of` ran 23x, 23x and 40x slower. What it needs is recorded there. The rules below that
only retrieval used (G3-3, G3-4, G3-7) are kept and pinned by the probe for that later unit.
Refactors made for it were reverted with it; those kept for usage are pure: `new Date` +
`setUTC*` became Hinnant's `days_from_civil` (`usage.test.mjs` holds the two equal on every day of
years 1..9999), `export { reduce as reduceUsage }` the function's own name, `Math.pow` the
`pysem.pyPow` adapter, the newline count a `latin1` split.

What is still refused, and why: `Math.log`, `Math.log1p` and `Math.pow`. V8's transcendental bits
are not one function of the input across platforms (a straight Python port of its fdlibm `log`
differs from Node on 86 of 40,021 doubles on arm64, where the C compiler fuses multiply-adds), so
no runtime helper reproduces "Node's" answer; a TypeScript port of CPython arithmetic calls a
`pysem.ts` function whose adapter is the CPython operator it ports (`pyPow`).

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G3-1 | a module-level `let` (a module global; a module function assigning it declares `global`); no initializer, an assignment from a closure, and an import by another compiled module refused | new | `g3.rs` probe (`bump`, `readCounter`), `g3_a_module_let_is_not_importable`; `refusals.rs` `g3_refusals`; usage's `PARSED` memo |
| G3-2 | `i++` / `++i` / `i--` / `--i` as a C-style `for` update on a local -> `_js_inc` / `_js_dec` (ToNumeric, then plus or minus one), `_js_num(i + 1)` when proven a number | new | `g3.rs` probe (`loops`); `refusals.rs` (`o.n++`) |
| G3-3 | `s.charCodeAt(i)` -> `_js_m_charCodeAt` | new | `g3.rs` probe (`codes`: ASCII, BMP, both halves of a pair, a lone surrogate, -1, the length, NaN, 1.9, Infinity, no argument) |
| G3-4 | `s.match(re)` -> `_js_m_match` (a `g` literal: every match over code units, `null` for none; else `exec`) | new | `g3.rs` probe (`matches`: words, none, empty matches, astral text, a non-`g` group match) |
| G3-5 | `x.toFixed(f)` -> `_js_m_toFixed` (exact decimal of the double, ties to the larger) | new | `g3.rs` probe (`fixed`: ties, `-0`, 1e21 and past, NaN, the infinities, 5e-324, 20 and 100 digits; `errors`: 101 and -1 are RangeError); `g3_to_fixed_fuzz_like_node` (40,000 seeded doubles x 0..20 digits against Node's digest) |
| G3-6 | `xs[i] = e` on an array (`_js_put`): an index in range, or the length (an append) | new | `g3.rs` probe (`writes`) |
| G3-7 | `k in m` for a Map or Set (`_js_in`): the prototype's names | new | `g3.rs` probe (`membership`) |
| G3-8 | `buf.indexOf(byte, offset)` on a Buffer (`_js_m_indexOf`), `buf.toString('latin1')` | extended (J86 `indexOf`, G2-24) | `g3.rs` probe (`buffers`: offsets 2, -1, 1.9, 100, NaN; bytes 266 and 99; a non-ASCII latin1 text and its split) |
| G3-9 | a method a declared adapter class names (`Hash.update` / `digest`) | extended (J86 `_js_invoke`) | `g3.rs` probe (`hashes`); `g3_modules_compile_together` |
| G3-10 | the builtin guard for EVERY name, not only module-level ones (`type` -> `type_`): a guarded entry's own `type(x) is str` called the string | defect fixed | `g3.rs` probe (`named(type, len)`); `pyfmt.rs` `names`; it renamed locals in `workplan.py` (`id`), `pyyaml.py` (`ord`, `abs`) and `eventlog.py` (`sorted`) with no change of behaviour |
| G3-11 | exact fast paths at the top of `_js_add`, `_js_mul`, `_js_div`, `_js_mod`, `_js_floor`, `_js_number`, `_js_max` / `_js_min` (two operands), `_js_typeof`, `_js_double_out`, `_js_m_split` (no surrogate: no per-part pass) | new | `g3_numeric_fast_paths_answer_as_the_general_path`: 40,000 random operand pairs, each helper against its own general path (an operand of a `float` / `int` / `str` / `dict` subclass takes it), 373,369 calls, 0 differences |

Runtime names added (12): `_js_inc`, `_js_dec`, `_js_m_charCodeAt`, `_js_m_match`, `_js_m_toFixed`,
`_JS_EXACT` (a 1,200-digit `decimal` context), `_js_buffer_index_of`, `_JS_MAP_PROTO_NAMES`,
`_JS_SET_PROTO_NAMES`, `_js_number_pair`, and the `decimal` import. Changed: `_js_put` (an array
element), `_js_in` (a Map or Set), `_js_m_indexOf` (a Buffer), `_js_buffer_to_string` (`latin1`),
and the fast paths of G3-11. Generated: `usage.py` 495 lines (against 388 TypeScript lines: typed
bodies write most functions twice). G1 and G2's modules recompile byte for byte but for G3-10's
renames.

## J89-3 rules (#316 G3: numeric lowering; `memory/retrieval` generated)

J89-2's retrieval answered every case and ran a 5,000-fact recall in 78 ms against the #204 bar of
15 ms: its BM25 and ranking loops did arithmetic on array elements no fact proved numbers. J89-3
gives the compiler what that code needs, and only where the TypeScript proves it: `Float64Array`
(whose elements a write converts to doubles, so they are proven floats), a proven-float fact with
native IEEE arithmetic, counted loops whose array bounds and element numbers are checked once before
they run, and the key sort `(a, b) => t[b] - t[a] || a - b`. With them `memory/retrieval.ts` is
generated (`_generated/retrieval.py`, 888 lines, in the G1/G2/G3 ts2py call) and the bar is 7.0 ms
(docs/porting.md, *Retrieval*). **5 new rules, 1 extended; 26 runtime names; 6 adapter rows (5
re-added from J89-2's attempt, 1 class), 1 changed.**

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G3-12 | a proven-float fact (`types::Fact::f64`, `type(v) is float`): a literal Python spells as a float, a Float64Array element read in a proven copy (G3-14), and `+ - * /` of two proven numbers at least one of which is a float. `+ - *` are the native operators (an int within 2**53 converts exactly, so this is IEEE-754's answer); `/` is native with a zero divisor sent to `_js_div` (inline `x / y if y else _js_div(x, y)` for a name or literal divisor, `_js_fdiv(x, e)` otherwise). The result is a float even where the general helpers spell an integral product as an int (the same JS value) | new | `g3_numeric.rs` probe (`arithmetic`: 196 pairs of 0, -0, ±1, 0.5, -2.5, 3, ±1e300, 5e-324, 2**53, ±Infinity, NaN through `+ - * /`, an int operand, a compound divisor) and fuzz |
| G3-13 | `const t = new Float64Array(n)` -> `_js_f64_new(n)` (ToIndex: a fraction truncates, NaN is 0; a negative or past-2**53-1 length is Node's RangeError naming the value; a BigInt is Node's TypeError; an object argument, and a length past 2**26, are refused at run time). `t` may only be indexed (`_js_ta_get`: the float, or `undefined` for a numeric key that is no valid index; -0 is index 0, the string `"-0"` is not), written by index (`_js_ta_put`: ToNumber first, then a float stored at a valid index, nothing otherwise) and measured (`len(t)`); a key that is not numeric is refused at run time. Any other use (as a value: returned, passed, aliased, iterated, spread, a method; bound by `let`; built anywhere but a `const` initializer; `t[i] op= v`) is refused at compile time | new | probe (`lengths`, `reads`, `writes`: 15 lengths, 13 keys, 13 writes against Node); `g3_numeric.rs` `j89_3_a_float64array_that_escapes_is_refused` |
| G3-14 | a counted loop `for (let i = a; i < b; i += 1)` (or `i++`, `++i`, `i = i + 1`) gets a **proven copy**: `if <guard>: for i in range(i, b): <body>` `else:` the general loop. The guard: `i` an int, `0 <= i`, `b` an int (a name the body does not assign, a literal, or a Float64Array's length) no larger than each Float64Array or fresh array the body indexes by `i`; each plain array the body reads at `i` a list that long whose elements over `[i, b)` are proven numbers (`_js_doubles`); each `const` or parameter the body uses as an operand a proven number (`_js_is_double`, unless already proven); each outer `let` the body assigns and uses as an operand ("carried") a proven number, kept only when every assignment in the copy assigns one (else the copy is lowered again without it). The body may hold only expression statements, `if`, `const` / `let`, `return` and an unlabelled `break`; assign only locals, Float64Array elements at `i` and fresh-array elements at `i` (a fresh array: a `const` of an array literal or of `.slice(...)`); push only onto fresh arrays; call only adapters and `Math.max/min/abs/floor/ceil/trunc/round/sign/sqrt`; read members only as `x[i]` and a Float64Array's `.length`; no closure, no loop, no template. So nothing that runs during the loop can change what the guard checked. In the copy `i` is a proven number, `t[i]` / `x[i]` / `fresh[i] = v` are native, and the facts above hold; the copy's own bindings are keyed apart from the general loop's (`Key::Var::ver`) | new | probe (`loops`: `spread` over proven and unproven elements, a `-0` / `1.0` / fractional start or bound, a string `w`; `best` (a carried `let`); `joined` (one that is not)); `j89_3_a_loop_that_could_break_its_guard_has_no_proven_copy` (11 bodies that get no copy, 1 that does) |
| G3-15 | `xs.sort((a, b) => t[b] - t[a] \|\| a - b)` (or `t[a] - t[b]`), `t` a Float64Array -> `_js_sort_by_f64(xs, t, descending, <the comparator>)`: when every item is an int index into `t` and no key it names is NaN, the comparator is a total order, so `xs.sort(); xs.sort(key=t.__getitem__, reverse=descending)` (both stable) is V8's order; otherwise (a NaN key makes the comparator inconsistent, or the items are not such indexes) V8's own sort runs with the comparator (G3-16). Any other comparator is the general `.sort` | new | probe (`sorts`: ties, -0 / 0, two Infinities, NaN keys both ways, duplicated items, empty); `j89_3_only_the_exact_key_comparator_is_a_key_sort` (7 near misses stay `_js_m_sort`) |
| G3-16 | `_js_v8_sort`: V8's `Array.prototype.sort` step for step (binary insertion alone for 7 or fewer elements, else CPython's pre-3.11 TimSort with V8's run, gallop and merge rules), `undefined` last | new (runtime) | the fuzz below: 20,000 rounds whose key sorts hold NaN keys on arrays up to 2,000 long; J89-3 also checked it on 30,000 seeded sorts against Node with identical comparator call counts, where CPython's `list.sort` differed on 561 |
| G3-11 | `_js_mul` of two floats returns a non-integral product directly (`_js_double_out` returned it unchanged) | extended | `g3_numeric_fast_paths_answer_as_the_general_path` (`g3.rs`, unchanged, still 0 differences) |

**The fuzz** (`g3_numeric.rs` `j89_3_numeric_fuzz_like_node`): 20,000 rounds of the probe's
generator (Park-Miller, every product below 2**53, the same in both runtimes): a key sort both
ways of a shuffled, sometimes duplicated index list whose keys hold NaN, ±0, ±Infinity and ties (24,
300 or 2,000 items); the float arithmetic over four random pairs; and `spread` / `best` over arrays
some of whose elements are strings. 60,000 answers, hashed in the compiled code: the digest equals
Node's. Two runtime mutants turn it red (the key sort's fallback as CPython's sort; `_js_fdiv`'s
zero divisor as Infinity).

Runtime names added (26): `_js_f64_new`, `_js_f64_index`, `_js_ta_get`, `_js_ta_put`, `_js_to_f64`,
`_js_fdiv`, `_js_doubles`, `_js_sort_by_f64`, `_js_v8_sort`, `_js_v8_timsort` and its 11 steps
(`_js_v8_lt`, `_min_run`, `_binary_insertion`, `_count_run`, `_merge_collapse`,
`_merge_force_collapse`, `_merge_at`, `_gallop_left`, `_gallop_right`, `_merge_low`, `_merge_high`
with that prefix), `_JS_F64_MAX`, `_JS_FLOAT_KINDS`, `_JS_NUMBER_KINDS`, `_JS_INT_KINDS`,
`_JS_V8_MIN_GALLOP`. Changed: `_js_mul` (G3-11). G1, G2 and usage recompile byte for byte.

**Found, not fixed (for the orchestrator):** the general `.sort(compare)` (`_js_m_sort`, every
compiled module's) is CPython's `list.sort`, which on an INCONSISTENT comparator orders differently
from V8 (561 of 30,000 seeded sorts with NaN keys). Every comparator the compiled modules pass today
is consistent on the values they sort; `_js_v8_sort` (G3-16) is the drop-in fix if one is wanted.

## J89-4a rules (#316 G3 U2: the constructs `memory/store.ts` needs)

J89-4 (9e44aa5c) ran ts2py over `memory/store.ts` with the G1/G2/G3 call and counted **86
refusals**: 34 imports with no adapter, 51 constructs, and one clash in `tokenledger.ts`
(`message.usage` refused because `MemoryStore` declared a method `usage`). J89-4a leaves **0**:
`tests/g3_store.rs` `j89_4a_store_compiles_with_the_committed_modules` compiles store.ts with the
seven modules of that call (generating it is J89-4b's). Of the 51 constructs, 18 are lowered by the
rules below; 25 were adapter calls the new rows resolve (16 `HotIndex` / `ColdIndex` method calls,
the two `new`s, 5 `instanceof`, 2 `Buffer.byteLength`); 8 went with a TypeScript change whose Node
answers are unchanged (docs/porting.md, *The store's constructs*): `Date.UTC`, three `getUTC*` and
`Math.round` with D1's fix (the day is `parseTs`'s), the run-time `new RegExp(..., 'u')` moved to
`pysem.pySearchWord` (an adapter), `memo ??= usage()` written as an `if`, `.filter(matchesMd)` as
`.filter((name) => matchesMd(name))`. The clash went with store.ts's private `usage()` renamed
`usageLedger()`: a receiver's type is never a proven fact (types.rs), so ts2py cannot tell
`message.usage` (a plain object's property) from the method, and the refusal stays
(`j89_4a_a_method_name_still_refuses_a_property_read_of_that_name`). One more construct the census
could not see was found by running the compiled store: `NOT_ONE_LINE.lastIndex = 0` around an
`exec` on a `g` regex (accepted, then refused at run time); store.ts now uses a non-`g` twin, and
the write is refused at compile time (G3-26). **10 new rules (one a refusal), 2 extended; 4 runtime names; 34
adapter rows (a new kind, `ImportedClass`), 1 adapter extended.**

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G3-17 | `a >> b` -> `_js_sar` (ToInt32 of the left, the count's low five bits, Python's arithmetic `>>`) | new | `g3_store.rs` probe (`shifts`: 29 left values incl. ±0, Int32 edges, 1e21, 2**53+1, NaN, ±Infinity, strings, booleans, null, undefined × 13 counts incl. 32, 33, -1, 1.9, NaN, `'3'`, 2**32+1; the bisect `(lo + hi) >> 1`) and the fuzz below |
| G3-18 | `a.forEach(cb)` (an array) -> `_js_m_forEach`: `cb(item, index, a)` for each index below the length read at the start that is still present; answers `undefined` | new | probe (`eaches`: a callback that pushes, one that pops, the third argument) |
| G3-19 | `m.keys()` -> `_js_m_keys`: a Map's keys, a Set's items, an array's indexes, as a fresh list (the Map snapshot of SUBSET.md's known limits, as `values`) | new | probe (`keyed`: Map, Set, array, spread, empty) |
| G3-20 | `a.copyWithin(t, s, e?)` -> `_js_m_copyWithin`: ECMA-262's bounds (ToIntegerOrInfinity, negative from the end, clamped), the overlap copied as through a temporary | new | probe (`copies`: 20 argument lists incl. negatives, NaN, ±Infinity, fractions, strings, overlap both ways; `binarysort`'s shift) |
| G3-21 | `continue` in a C-style `for` (with any update): `first = True` / `while True:` / `if first: first = False` / `else: <update>` / `if not (<test>): break` / the body, so a Python `continue` reaches the update, then the test, as JS's does | extended (G1's refusal) | probe (`continues`: `+=` and `--` updates, nested loops with `continue` and `break`, a test with a side effect counted, store.ts's `old < start + count`) |
| G3-22 | a module `function*` -> a Python generator function: `yield <v>;` as a statement (not inside a `try`: a JS `break` closes the generator at once, Python when it is collected), `return;` only; one body, untyped; a body with no `yield` still a generator. Its call is allowed only as a for-of's iterable or an array spread's argument (also across modules, `ModuleExports::generators`), so its object is never held and iterated again after a `break` | new | probe (`generators`: early `return`, a consumer that breaks, a second call after one was abandoned, `[...g()]`, a generator with no `yield`); `j89_4a_refusals` (held in a const, passed as a callback, `yield*`, a read `yield`, `return 2`, a `yield` in a `try`, a generator method) |
| G3-23 | a hole in a for-of array pattern (`for (const [, p] of xs)`) binds nothing | new | probe (`holes`) |
| G3-24 | a spread argument to `.splice` (`a.splice(i, n, ...xs)`), `xs` proven a list | extended (J86 `.push(...xs)`) | probe (`splices`); `j89_4a_refusals` (a string spread) |
| G3-25 | `\s` / `\S` outside a class -> JS's set spelled out (U+0009-U+000D, U+0020, U+00A0, U+1680, U+2000-U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF; Python's `\s` differs on U+001C-U+001F, U+0085, U+FEFF); inside a class still refused | new | probe (`spaces`: every code unit 0..0xFFFF `/\s/` matches, Node's list; store.ts's `/:(\s|$)/` on 11 heads; `\S`); `lower.rs` `regex_translation` |
| G3-26 | `re.lastIndex = n` refused at compile time (the subset models no `lastIndex`) | new (refusal) | `j89_4a_refusals` |
| G3-27 | `new Date().toISOString()` -> `_js_date_to_iso(_js_now())` | new | probe (`clock`: the shape and length) |
| G3-28 | an `ImportedClass` adapter (below): `new C(...)`, `instanceof C`, and its methods dispatched (`_js_invoke` / `_js_dispatch`) in a module that imports it and nowhere else; a property of one of those names on anything else reads (`pool.names`), and on an instance the runtime refuses it as a value | new | `j89_4a_imported_class_methods_stay_in_their_module` |

**The fuzz** (`g3_store.rs`, the probe's `fuzz(20000)`): 20,000 seeded `a >> b` (Park-Miller) over
Int32 edges, fractions and magnitudes past 2**32 with counts -5..64, folded into one number: Node
printed 302436588 and the compiled Python prints it. Two runtime mutants turn it red (the count
taken mod 32 with a negative count as 0: 795140807; the left truncated without ToInt32's wrap:
-547775272).

**The day** (D1, `candidatesDone`'s `ordinal`): 30,000 seeded strings (16,744 of them real days of
the years 1..9999, the rest out-of-range months and days, year 0000, Feb 29 of every kind of year,
mutated characters, trailing text): Node's new ordinal agrees with CPython's `date.fromisoformat`
behind store.py's `_ISO_DAY_RE`, and with the generated `usage.parse_ts` the compiled store calls,
on all 30,000; the old `Date.UTC` ordinal disagreed on 3,908.

Runtime names added (4): `_js_sar`, `_js_m_forEach`, `_js_m_keys`, `_js_m_copyWithin`. G1, G2, G3
U1 and the codec recompile byte for byte.

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

### Adapters (J88-2, #316 G2)

Measured against Node v26.13.0 on 2026-11-15. Node builtins are pinned by `tests/g2.rs`'s fs
probe, which runs the same calls on the same directory under Node and under the generated Python
and compares every answer (a file, a directory, a symlink to one, invalid UTF-8, a NUL path).

| TypeScript | Python | Why it is the same function | Measurement |
|---|---|---|---|
| `statSync`, `lstatSync`, `fstatSync`, `Stats` (`node:fs`) | `os.stat` / `os.lstat` / `os.fstat` as a `Stats` (`size`, `mtimeMs` = `sec * 1e3 + nsec / 1e6`, `isDirectory` / `isFile` / `isSymbolicLink` from `st_mode`; a Windows junction is a link) | libuv's stat fields as Node combines them | fs probe: sizes, types, a symlink both ways, ENOENT / ENOTDIR / ERR_INVALID_ARG_VALUE codes |
| `readdirSync` | `os.listdir` of the path as `os.fsencode` encodes it, names decoded with U+FFFD | Node decodes entry names as UTF-8 with replacement; directory order either way | fs probe |
| `mkdirSync(p, {recursive: true})` | `os.makedirs(exist_ok=True)` | EEXIST for a file in the way, ENOTDIR for a file on the path | fs probe |
| `renameSync`, `linkSync` | `os.replace`, `os.link` | rename(2) replacing the target; link(2) | fs probe (EEXIST for a second link) |
| `rmSync(p, {force: true})` | unlink, ENOENT ignored, a directory refused | Node's `rm` of a file without `recursive` | fs probe |
| `openSync`, `closeSync`, `writeSync`, `readSync`, `appendFileSync` | `os.open` with `stringToFlags`'s bits, mode 0o666, O_BINARY on Windows; one `os.write`; `os.pread`; an `a`-mode loop | the syscalls Node's binding makes | fs probe (EEXIST for `wx` twice, a pread at 4 and past EOF); `test_write_over_and_rotate_write_temp_then_rename` and its Node twin (the order and mode of a crash-safe write); J88-RF F1: `writeSync` answers a short count as write(2) does, and `logsegment.ts`'s `writeAll` loops on it, so a short write is never renamed into place (`test_a_short_write_renames_nothing_over_the_log` and its Node twin) |
| `readFileSync(p)` with no encoding | the bytes (`open(p, 'rb')`) | a Buffer | fs probe (EISDIR for a directory) |
| `dirname`, `basename` (`node:path`) | lib/path.js `posix` / `win32` ported | the same statements | 60,000 random paths over separators, dots, drive letters, colons and non-ASCII: 0 disagreements on each of the four functions |
| `gzipSync`, `gunzipSync` (`node:zlib`) | `gzip.compress(mtime=0)`; `gzip.decompress` with Node's refusals | RULED for the compressed bytes (Chromium zlib's deflate stream: 300 of 300 inputs differ from CPython's zlib at level 6 too); decompression equal | nine shapes (empty, one and two members, zero padding, trailing garbage, truncated, a bad CRC, plain text, two magic bytes): CPython returned `b""` for the empty input where Node throws Z_BUF_ERROR, and the adapter throws. J88-RF F5: two more shapes differ and are left as they are (a member, a zero, a non-zero byte; a member, a zero, a member: Node ends the input at the zero), named in `docs/porting.md`; neither runtime writes them |
| `randomBytes` (`node:crypto`) | `os.urandom` | the OS CSPRNG | only the count and use are compared |
| `TextDecoder` (`fatal`, `ignoreBOM`) | strict `bytes.decode('utf-8')` raising Node's TypeError (code ERR_ENCODING_INVALID_ENCODED_DATA); the BOM kept with `ignoreBOM` | WHATWG's well-formed UTF-8 and CPython's strict codec accept the same byte strings | 40,000 random byte strings biased to UTF-8 edge bytes, 33,013 refused by Node: 0 disagreements |
| `Buffer.from(s, 'utf8')`, `Buffer.concat`, `Buffer.alloc` | `s.encode` with each lone surrogate as U+FFFD, a bytes join, `bytearray(n)` | Node's UTF-8 encoder writes EF BF BD for a lone surrogate | `g2.rs` probe |
| `process.pid`, `process.env` (a value) | `os.getpid()`, `dict(os.environ)` | each runtime its own process | `--suite eventlog` |
| `cmpCodepoint`, `pyExists`, `pyIsDir`, `pyJoin`, `pyParent`, `pyName`, `osErrorClassName`, `PyOSError` (`memory/pyfs.ts`) | the CPython call each ports (`Path.exists`, `Path.is_dir`, `str(PurePath(...))`, `.parent`, `.name`, the errnomap table, `OSError`) | Python is the reference (`pyfs.ts` is the CPython OS seam) | `--suite eventlog` (beds: a never-saved store, a parent that is a file, the errno names), `--suite store` |
| `bantamkitDirFor`, `ensureBantamkitGitignore` (`memory/store.ts`) | `bantamkit.memory.store`'s functions (since J89-4b the shim over the generated ones) | reached only by a call that compiles the event log WITHOUT store.ts (ts2py's G2 tests); the committed event log imports the compiled store (`from .store import ...`, J89-4b) | `--suite eventlog` (`.gitignore` beds), `--suite store` |
| `exclusive`, `LOCK_STALE_MS`, `LOCK_POLL_MS` (`storage/lock.ts`) | `bantamkit.storage.lock` (the context manager around `body(held)`) | Python is the reference; #316 G4 is not generated yet | `--suite storage-lock`, `--suite storage-log` (#208 beds) |

`existsSync` changed with them: a NUL in the path answers `false` (Node validates inside its
`try`), and a lone surrogate is looked up as the U+FFFD Node's encoding writes, where J87-3 refused
both.

J88-RF (F4a, F4b): every G2 fs adapter and the `exclusive` lock adapter hand a path to the OS as
Python's own `os` functions encode it (`os.fsencode`): a POSIX surrogateescape code point
(U+DC80..U+DCFF, an undecodable byte of a real name) is that byte, and only a lone surrogate no
encoding takes becomes the U+FFFD Node writes. The lock is named from the same path as the data
(it raised `UnicodeEncodeError` on a lone surrogate before). The target-specific row is in
`docs/porting.md`.

### Adapters (J89-2, #316 G3 U1)

Measured against Node v26.13.0 on macOS arm64, 2026-11-15.

| TypeScript | Python | Why it is the same function | Measurement |
|---|---|---|---|
| `pyPow` (`pysem.ts`) | `float ** float` (a negative base refused: Python answers a complex); since J89-3 Infinity where `**` overflows | Python is the reference: usage.py's `0.5 ** (age / half)`; where CPython raises OverflowError, Node's `Math.pow` answer (Infinity) | Node's `Math.pow(0.5, y)` and CPython agree on 30,000 of 30,000 doubles (`Math.pow(x, 0.37)` differs on 131); `--suite recall-usage` (`future:`, agreeing since J89-3) |
| `pyRealpath` (`memory/pyfs.ts`) | `os.path.realpath(_os_text(p))` | Python is the reference: J89-1F's port of `os.path.realpath(strict=False)`, under the G2 path policy (`_os_char`) | `--suite recall-usage` (`storeId` of a dangling symlink, a path below one, a lone surrogate, the ruled U+DC80) and `--suite skill-layer` |
| `createHash`, `Hash` (`node:crypto`) | `hashlib.sha256` over the string's UTF-8, a lone surrogate as U+FFFD, a POSIX U+DC80..U+DCFF as its real byte (the G2 path policy: the one caller hashes a path) | Node's UTF-8 encoder writes EF BF BD for a lone surrogate | `g3.rs` probe (`hashes`: empty, `héllo`, an astral character, a lone U+D800); `--suite recall-usage` `storeId` cases |

### Adapters (J89-3, #316 G3)

The rows J89-2's retrieval attempt used, re-added with it (`pysem.ts` holds each function, moved
from `retrieval.ts` unchanged; `adapters.rs` says why each is faithful). Measured against Node
v26.13.0 on macOS arm64.

| TypeScript | Python | Why it is the same function | Measurement |
|---|---|---|---|
| `pyRoundFloat9` (`pysem.ts`; was `retrieval.ts`'s `pyRound9` body) | `round(x, 9)` | Python is the reference: CPython's `double_round` (half to even on the exact binary value) | `--suite recall-retrieval` (`pyRound9` against `round(x, 9)`, 1,000 seeded doubles, bits) |
| `pyLog`, `pyLog1p` | `math.log`, `math.log1p` | Python is the reference: retrieval.py's idf and usage weight; Node's last bit differs (J89-2: 549 and 561 of 30,000), absorbed by the nine-decimal rounding every score takes | `--suite recall-retrieval`, `recall-gate` |
| `pyNfkcLower` | `unicodedata.normalize('NFKC', s).lower()` | Python is the reference: retrieval.py's tokenizer | `--suite recall-retrieval`, `recall-strings` |
| `pyWordchar` (and `WORDCHAR`, moved to `pysem.ts`) | `unicodedata.category(ch)[0] in 'LNM'` | Python is the reference: retrieval.py's `_wordchar` | `--suite recall-retrieval` (`stale`, the tokenizer) |
| `CountsView` (`memory/queries.ts`, class, `scan` only) | a class no Python code builds | declared for `bm25Rows`'s `row.scan(...)`; Python's rows are Maps, and `'scan' in` a Map is false | `--suite recall-queries` |


### Adapters (J89-4a, #316 G3 U2)

Every import of `memory/store.ts` that is not compiled. `ImportedClass` (new): a class whose
methods dispatch only in a module that imports it (`adapters.rs`), so `HotIndex.names` and
`ColdIndex.add` do not turn every `Set.add` of the call into a dispatch, and `pool.names` (a plain
object's field) still reads. Exercised end to end by running the compiled store (a scratch compile,
J89-4b's to ship) and Node's over the same saves, recall, lookup, `candidatesDone` and archived
recall: identical answers, identical store trees and index file lists.

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `homedir` (`node:os`) | `str(Path.home())` | Python is the reference: store.py passes `Path.home()` in each place store.ts calls `homedir()`; the two differ only for a set but empty `HOME` |
| `pySearchWord` (`pysem.ts`, new: store.ts's `DONE_WORD_RE` moved there) | group 1 of `re.compile(r'\b(' + alternatives + r')\b', re.IGNORECASE).search(text)` | Python is the reference: store.py's `_DONE_WORD_RE`; J89-1F and J89-2 swept the Node regex against it (`--suite store`) |
| `HotIndex`, `INDEX_DIR_ENV` (`storage/hotindex.ts`) | `bantamkit.storage.hotindex`, imported when the first index is built; `names()` / `segments()` / `skipped` as read-only Maps over its dicts (`_JsReadMap`), `parseFile` answering the doc or the reason, a native `BantamError` restated as the adapter's | Python is the reference: hotindex.ts ports it (#316 G4 later) |
| `ColdIndex`, `ColdIndexError` (`storage/coldindex.ts`) | `bantamkit.storage.coldindex`, `add` taking a Map, `query` answering lists; its `ColdIndexError` restated as a JS Error | Python is the reference: coldindex.ts ports it |
| `PyScalar` (`memory/pyyaml.ts`); `extraOf`, `formatFact`, `lifecycleOf`, `parseFrontmatter`, `pyList`, `pySplit`, `pyTruthy`, `todayLocal`, `VALID_OUTCOMES` (`memory/factfile.ts`); `pyStrip` (re-exported from `pysem.ts`) | the class, functions and constant ts2py compiled from the same TypeScript (`_generated/pyyaml.py`, `_generated/factfile.py`, the #315 call kept apart), imported lazily | the same TypeScript, compiled; J89-4b decides `parseFrontmatter` / `formatFact`'s Python boundary (factcodec's PyYAML fallback, #315's owner ruling) |
| `asPyOSError`, `matchesMd`, `pyLexists`, `pyMkdirParents`, `pyMtimeDate`, `pyParents`, `pyReadText`, `pyReplace`, `pyScandirNames`, `pyScandirProbe`, `pySuffix`, `pyUnlink`, `pyWriteText`, `pyWriteTextAtomic`, `sortedPathNames`, `PyUnicodeDecodeError` (`memory/pyfs.ts`) | the CPython call each ports (its doc comment): `OSError` passed through, `fnmatch(name, '*.md')`, `os.path.lexists`, `Path.mkdir(parents=True, exist_ok=True)`, `date.fromtimestamp(st_mtime)`, `PurePath.parents`, `Path.read_text` (a `UnicodeDecodeError` as `PyUnicodeDecodeError`, a JS Error with CPython's message), `os.replace`, `os.scandir` names / probe, `PurePath.suffix`, `Path.unlink`, `Path.write_text`, store.py's `_write_text_atomic` carried statement for statement, a stable sort by `os.path.normcase` | Python is the reference: pyfs.ts is the CPython OS seam |
| `Buffer.byteLength(s, 'utf8')` (Node global) | `len(s.encode('utf-8', 'surrogatepass'))` | a lone surrogate is three bytes either way (U+FFFD's, as `Buffer.from` writes it); `g3_store.rs` holds it to `len(buffer_from(s))` over 20,000 seeded strings and the probe to Node over 9 |
| `statSync(p, {bigint: true})` (extended) | `BigIntStats`: `size`, `mtimeNs` (`st_mtime_ns`, exact) and `mtimeMs` as BigInts | libuv's `sec * 1e9 + nsec`, which `st_mtime_ns` is |

### Adapters (J89-4b, #316 G3 U2: the store generated)

`store.ts` is compiled into `_generated/store.py` and shipped (the shim is `bantamkit.memory.store`).
What the J89-4a rows needed to be faithful once a real store runs through them, each held by
`--suite store` (0 failures; the two `G3 as Node` store-root rulings went STALE by design and are
agreeing cases) and by `g3_store.rs` `j89_4b_store_os_seam_answers_like_node` (red against any
other spelling of the lines Node printed):

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `pyOSErrorText`, `pyOSErrorStrerror` (`memory/pyfs.ts`, new) | `str(e)` and `str(e.strerror)` of the CPython `OSError` | Python is the reference: a `PyOSError` ports CPython's `OSError` (its constructor builds `message` as `OSError.__str__`). A compiled `e.message` / `e.strerror` read of a Python exception stays refused (Node's own fs errors spell both differently), so store.ts asks these two functions where it holds a `PyOSError`: the `skipped` reason, `unwritable` and `unreadable` |
| the J89-4a `pyfs.ts` rows that take a path (`pyLexists`, `pyMkdirParents`, `pyMtimeDate`, `pyReadText`, `pyReplace`, `pyScandirNames`, `pyScandirProbe`, `pyUnlink`, `pyWriteText`, `pyWriteTextAtomic`) and the `HotIndex` adapter's source path | the same CPython calls, of the path as Node's fs receives it (`_store_path`): the G2 path policy (`_node_path`: a lone surrogate CPython cannot encode is U+FFFD, a POSIX surrogateescape code point the real byte), and a NUL the `OSError` `asPyOSError` makes of Node's `ERR_INVALID_ARG_VALUE` (errno 0, strerror `ERR_INVALID_ARG_VALUE: <Node's message>`, the inspected path cut at 128 UTF-16 units); `pyLexists` of a NUL is false (the port's bare catch) | the store's root is the caller's string, and Node's answer for one no encoding takes is the G2 policy's (`docs/porting.md`, the `G3 as Node` store-root rows, now closed) |
| `parseFrontmatter`, `formatFact` (`memory/factfile.ts`) | inside bantamkit: `factcodec.held_frontmatter` (`load_frontmatter`: the compiled codec, then PyYAML where it refuses; a PyYAML refusal a JS Error carrying `str(e)`; a non-mapping `frontmatter is not a mapping`) and `factcodec.held_fact_text` (`fact_text` over the Python values the fact stands for); outside it (ts2py's tests) the compiled codec alone | #315's owner ruling: generated + PyYAML fallback. A value the codec's shape cannot hold as Python holds it is carried opaque (`factcodec._Opaque`, a `PyScalar` whose `text` is `str()` of the value), so the #120 rulings and the malformed-message rulings hold unchanged |
| `bantamkitDirFor`, `ensureBantamkitGitignore` | (the rows above, kept) | the committed event log now imports the compiled store's; the rows serve only a call that compiles the event log without store.ts |



## J89-5 rules (#316 G3 U3: `memory/native.ts` generated)

`native.ts` joins the G1/G2/G3 call and is shipped as `_generated/native.py` (the shim is
`bantamkit.memory.native`). Two constructs and two adapter rows; J89-4a's method-name clash ruling
stands (a member named like a method a compiled or adapter class declares is refused unless a
DECLARED TYPE makes it a data field), and both constructs only widen where a declared type exists:

| Construct | Lowering | Why it is the same | Measurement |
|---|---|---|---|
| `import { type Pool }` / `import type { Pool }` from a compiled module of the call | the type's data fields (`TypeDecls::fields` of the declaring module) declared under the local name, so `pool.facts` reads the field (`_js_get`) as it does in store.ts | a type annotation changes nothing at run time in Node; the read is the same `_js_get` an undeclared non-method name gets, and on a compiled-class instance `_js_object_get` still refuses a method read at run time | `g3_store.rs` `j89_5_an_imported_type_declares_its_data_fields` (Node: `[[1,2],null]`; the same read through an undeclared object stays refused) |
| an annotated arrow parameter (`(o: Omission) => o.count`) | the annotation's data fields declared for the parameter, as `bind_params` does for a function's | as above; tokenledger.ts annotates its one omission callback, which `NativeStore.count()` (a class method of the call now) would otherwise refuse | `g3_store.rs` `j89_5_an_annotated_callback_parameter_declares_its_fields` (Node: `[2,5]`; unannotated stays refused) |

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `DUPLICATE` (`storage/hotindex.ts`) | `bantamkit.storage.hotindex.DUPLICATE`, imported lazily | Python is the reference: the same `duplicate name` sentence head the port declares |
| `parseNative` (`storage/hotindex.ts`) | `divergence.parse_fact`, answering `{name, description, type, body}` (`meta` is read by no compiled caller and not carried), its `MemoryValidationError` restated as the adapter's `BantamError` with the same message | Python is the reference: `parseNative` is `divergence.parse_fact` for the native shape (its doc comment). The layer reads every file through exactly the function the hand-written layer called, so `--suite recall-strings` (the native pool), `skill-layer` and `hooks` compare the same reads |

TS refactors (Node's answers unchanged; types and a guard only): native.ts's two `skipped?.push(...)`
are `if (skipped != null) skipped.push(...)` (optional chaining on a call is outside the subset; `!=
null` short-circuits on exactly the two values `?.` does); tokenledger.ts's omission callback is
annotated `(o: Omission)`.

Runtime and adapter changes, each answering what it replaces (`g3_store.rs`
`j89_5_codepoint_sort_and_join_memo_answer_as_the_paths_they_replace`, 20,000 seeded inputs, 0
differences; red under a UTF-16-order mutation of the sort, 8,704 differences):

| Where | Change | Why it is the same |
|---|---|---|
| `_js_m_sort` (runtime) | a comparator marked `_js_codepoint_order` (only `cmp_codepoint`'s adapter) over a list of strings sorts with Python's own `str` order, the comparator never called | Python compares `str` by code point, which is `cmpCodepoint`'s order; both sorts are stable and the strings it ties are equal |
| `py_join` (adapter) | `str(PurePath(*parts))` memoised (8,192 entries) for string parts | `PurePath` reads no filesystem: the same parts give the same string on one OS |
| `_native_bantam_error` (adapter) | restates into the `BantamError` class already built (`globals()`) | a FIX: a direct `__getattr__` call built a second class, so a module that had imported `BantamError` saw `instanceof BantamError` false for a restated error. Found by the native layer (`candidates` raised on a malformed file); `--suite recall-strings` `native candidates past a malformed file and a duplicate name` is red without it |

## J89-5a rules (#316 G3 U3: `memory/queries.ts` generated)

`queries.ts` joins the G1/G2/G3 call and is shipped as `_generated/queries.py` (the shim is
`bantamkit.memory.queries`). One compile rule, six adapter rows and a widened one, and TS
refactors for the rest of J89-5's census; no runtime helper was added.

| Construct | Lowering | Why it is the same | Measurement |
|---|---|---|---|
| a method of a class no export names (`CountsView`: `has`, `get`, `keys`, `scan`, `at`) | a method name in its own module only (`scan_module` answers it apart; `lib.rs` adds it to that module's `class_methods`), as J89-4a's `ImportedClass` rows are; an exported class's names still reach every module | the class reaches another module only as a value a function returned; there `m.get(k)` is `_js_m_get`, which refuses an instance at run time (`_js_outside`), and a read of the name is `_js_get` -> `_js_object_get`, which refuses a method read: the other modules answer as Node or refuse, never differently. Without it every `.get` / `.has` / `.keys` of the eleven modules of the call would dispatch at run time (J89-5a measured the diff: eventlog, native, retrieval, store, tokenledger and usage each gained `_js_dispatch`), and the codec call's `factfile.py` loses the `push` dispatches pyyaml.ts's private `Emitter` gave it | `g3_store.rs` `j89_5a_a_private_class_keeps_its_method_names_in_its_module` (Node: `[[1,true],[null,false],[5,true],5,1,[...]]`; Python the same with the cross-module call refused); red when the private names are put back into the call's set |

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `parseJson` (`pyjson.ts`) | `parse_json`: `json.loads`, the value tagged as `PyValue` (`{t, v}`, an int a BigInt, a dict a Map in the dict's order), a refusal `PyJSONDecodeError` (a JS Error) with CPython's message; a text nested past 512 (`_PARSE_JSON_DEPTH`, counted as `JSON.parse` nests, found without recursing) the RangeError `Maximum call stack size exceeded` (J89-5e), and `json.loads`'s `RecursionError` the same RangeError as the backstop (J89-5d) | Python is the reference: pyjson.ts is the port of CPython's json module. The RangeError is what the recursive `parseJson` throws past its stack, so a compiled `catch` sees it as it sees Node's (J89-5d, ruled: a crash is a bug). The depth is Python's own because CPython's moves with the version (3.11: the recursion limit less the caller's frames, ~980; 3.12 and 3.13: ~9,994; 3.14: none) (J89-5e, ruled: the answer must not depend on it); between 512 and Node's stack the two differ by ruling (docs/porting.md). Checked against 3.11's `json.loads` with the recursion limit set to read exactly 512: 20,000 seeded texts, 0 differences in outcome but the 31 where 3.11 itself raised `RecursionError` building a decode error within two frames of its limit (the texts are malformed no deeper than 512, and `parse_json` refuses them with `json.loads`'s message) |
| `dumpJson` (`pyjson.ts`) | `dump_json`: `json.dumps` of the untagged value with `indent`, `sort_keys`, `ensure_ascii`, `separators`; any other option refused | Python is the reference, as above; the hand-written queries module wrote the sidecar with `hotindex.dumps`, which is this call |
| `encodeBasestringAscii` (`pyjson.ts`) | `json.encoder.encode_basestring_ascii` | Python is the reference: its doc comment names `py_encode_basestring_ascii` |
| `sha16` (`storage/hotindex.ts`) | `bantamkit.storage.hotindex.sha16` | Python is the reference (#204), the key the hand-written module used |
| `pyDecodeUtf8` (`memory/pyfs.ts`) | `bytes.decode('utf-8')`, strict, BOM kept; a refusal `PyUnicodeDecodeError` with CPython's message | Python is the reference: its doc comment, measured over 64,028,929 sequences |
| `fs.writeFileSync(path, string, 'utf8')` | opened `w` (O_TRUNC, O_CREAT, O_WRONLY, mode 0o666, binary), every byte of Node's UTF-8 (a lone surrogate U+FFFD) written, closed; a Buffer, another encoding or an options object refused | Node builtin; the flags and mode `Path.write_text` opened with |
| `createHash('sha1')`, `hash.update(buffer)` (the `createHash` / `Hash` rows, widened) | `hashlib.sha1`; a Buffer's bytes hashed as they are | Node builtin |

Measured against Node v26.13.0 (runtime-ts's own `dist/pyjson.js`): a seeded fuzz of 20,000 JSON
texts (repeated keys, code-point key order, ints past 2^64, `-0`, `1e400`, `NaN`, escaped lone
surrogates, a BOM, 15% mutated so 6,262 of them refuse) through `parseJson` and `dumpJson` under
four option sets, and 20,000 strings through `encodeBasestringAscii`: 0 differences, the refusal
messages included. Red under a mutation that reads an integral float as an int (1,180
differences). The adapters' pinned answers are `g3_store.rs`
`j89_5a_queries_adapters_answer_like_node`, with each refusal above.

TS refactors (Node's answers unchanged, `npm test` green; each only on a path Node's speed does not
measure apart from the save it sits in):
- `SidecarWriteError` names itself with a class field, `override name = 'SidecarWriteError'`, not
  a constructor: the same own, writable, enumerable `name` (property descriptors compared in Node).
- `CountsView`'s parameter property is a declared field assigned in the constructor.
- `doc['facts']` (twice) is read through `const top: JsonTop = doc as JsonTop`, a type whose
  `facts` is JSON data, so the read is a field read, not `MemoryStore.facts` (J89-4a's clash ruling).
- `[n, [dl, c]]` (a for-of head and an arrow parameter) is `[n, row]` with `row[0]` / `row[1]`;
  `dumpTermsSlow`'s `.flatMap` (outside the subset, met once the pattern compiled) is a loop.
- `writeEntries` builds the merged `facts` Map anew instead of `Map.delete`: the sidecar is written
  with sorted keys, so the order the names are held in never reaches its bytes.
- `writeEntries`'s `String((e as Error).message)` is `pyOSErrorText(...)` of the `PyOSError` the
  failure is (`asPyOSError`), so the message is CPython's `str(e)` on both sides. No caller reads
  it: Node's component answers `WRITE_FAILED`, and the Python shim restates the error as the
  `OSError` component.py catches.

## J89-5b rules (#316 G3 U3: `memory/layers.ts` generated, the config read kept on PyYAML)

`layers.ts` joins the G1/G2/G3 call and is shipped as `_generated/layers.py` (the shim is
`bantamkit.memory.layers`). No construct and no runtime helper was added: nine adapter rows and
three TS refactors.

**The config reader is not compiled, by ruling.** J89-5 stopped on it: layers.ts read `config.yaml`
with its own reduction of `yaml.safe_load`, so compiling it would have moved Python off PyYAML. The
orchestrator ruled option (b): Python keeps PyYAML for the config, as #315's owner ruling kept it
for fact files. The reader (`firstTokenTab`, `parseConfigDocument` and their helpers) moved, byte
for byte, into `runtime-ts/src/memory/grantconfig.ts`, which is not in the call; layers.ts imports
the two functions, and those imports are adapter rows onto PyYAML. Where the two readers answer a
document differently the difference is ruled (`docs/porting.md`, `RULED: config outside the
reader's language — ...` in `--suite recall-strings`).

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `firstTokenTab` (`memory/grantconfig.ts`) | `yaml.safe_load(text)` (one load per text, shared with the next row); the 1-based `[line, column]` of the mark of a `ScannerError` whose problem is exactly `found character '\t' that cannot start any token`, else null; since J89-5d a `ValueError` (a scalar PyYAML resolves but cannot construct) or `RecursionError` from the load is held for the next row, not raised | Python is the reference (the ruling): it is the reference's `_token_tab`. Until J89-5d a non-YAML error left `loadGrants` raw from here, as it left `load_grants`; J89-5d ruled that a crash is a bug, so it is refused by name instead |
| `parseConfigDocument` (`memory/grantconfig.ts`) | `yaml.safe_load(text)` converted: `None` `{kind: 'null'}`; a dict `{kind: 'mapping', entries}`, a Map of its `str` keys only (`data.get('extra_stores')` matches no other); a list entry `{kind: 'seq', items}`, each `str` item `{kind: 'str', value}` and any other `{kind: 'other', value: null}`; any other entry or document `{kind: 'other'...}`; a `yaml.YAMLError` a `_JsError` with `str(e)`; since J89-5d a held `ValueError` a `_JsError` with `str(e)`, a held `RecursionError` one with `the document is nested too deeply to read`, and a `str` item holding NUL `{kind: 'other'}` (a NUL names no path, so the list is not of paths) | Python is the reference: the compiled validator asks exactly the reference's questions (`is None`, `isinstance(dict)`, `isinstance(list)`, `all(isinstance(p, str))`) of the converted value, and interpolates `str(e)` as `{e}` |
| `pyIsFile`, `pyResolve`, `pyStatIsDir`, `pyCwd`, `pyExpanduser`, `pyIsAbsolute` (`memory/pyfs.ts`) | `Path.is_file()`, `str(Path.resolve())`, `S_ISDIR(os.stat().st_mode)`, `str(Path.cwd())`, `str(Path.expanduser())`, `PurePath.is_absolute()`, of the path as given (no `_store_path`: the reference called pathlib on it directly, so a NUL in a granted path is still CPython's `ValueError` from `resolve`) | Python is the reference: each is the pathlib call its doc comment names |
| `pyRepr` (`memory/pyfs.ts`) | `py_repr` (the J87-3 row) | pyfs.ts re-exports pysem.ts's `pyRepr` |

Measured: `g3_store.rs` `j89_5b_layers_adapters_answer_like_the_reference` (the #158 tab positions
equal to Node's `firstTokenTab`; the document shapes; the `ValueError`; the pyfs rows equal to
Node's `pyfs.ts` over one bed; a non-string refused). A 59-document battery of YAML features
(anchors, aliases, merge keys, tags, directives, multi-document streams, block and folded scalars,
flow mappings, escapes, a BOM, a NUL, an impossible timestamp, deep nesting) gave byte-identical
`load_grants` answers on the generated Python and on the hand-written module of `32831cff`.

TS refactors (Node's answers unchanged, `npm test` green):
- the reader moved to `grantconfig.ts` (above);
- `data.entries` is read through `const mapping: ConfigMapping = data`, a local interface whose
  `entries` is a data field (J87-12), not `Map.prototype.entries`;
- `e.strerror` (twice) is `pyOSErrorStrerror(e)` and the read failure's `e.message` is
  `pyOSErrorText(e)` for a `PyOSError` (J89-4b): CPython's `strerror` and `str(e)` on both sides.

## J89-5c rules (#316 G3 U3: `memory/dream.ts` generated)

`dream.ts` joins the G1/G2/G3 call and is shipped as `_generated/dream.py` (the shim is
`bantamkit.memory.dream`). J89-5's census counted **25 refusals**; J89-5c leaves **0**: one runtime
extension (G3-29, a construct the compiler accepted and the runtime refused, found by running the
compiled dream), six adapter rows, and TS refactors whose Node answers are unchanged.

| # | Rule | Status | Pinned by (`tests/`) |
|---|---|---|---|
| G3-29 | `s.split(re)` -> `_js_split_regex`: ECMA-262's `RegExp.prototype[@@split]` with no limit over UTF-16 code units (an empty match where the last piece ended moves on one unit; a match starting at the end is not taken; captures join the result, `undefined` when they took no part; `''` is `[]` when the splitter matches it; a `g` flag changes nothing). A limit stays refused at compile time; a receiver that is not a string is refused at run time | extended (the string-separator row) | `g3_store.rs` `j89_5c_split_by_a_regex_answers_like_node` (`tests/fixtures/j89_5c_probe.ts`: 13 splitters incl. an empty-matching one, captures, `^`, `$`, a lookbehind, `\b`, lone surrogate halves, a `g` regex, x 18 subjects incl. `''`, astral and lone halves; and `fuzz(20000)`, 20,000 seeded strings, digest 545608662 as Node printed it); `j89_5c_split_with_a_limit_is_refused`. Four runtime mutants each turn it red (an empty match moving two units, captures dropped, a match at the end taken, `''` always `['']`) |

**The 25 refusals, and where each went.**
- The 4 `pysem` imports (`pyCaseless`, `PY_WORD_CLASS`, `PY_WS`, `PY_WS_CLASS`), the 6 `new RegExp(..., 'u'|'gu')`,
  `matchAll` (2), `match.index`, and `groups['count']` (the name clash with `NativeStore.count()`):
  every pattern dream.ts built at run time from CPython's classes moved, byte for byte, into
  `runtime-ts/src/memory/dreamre.ts`, which is not in the call (as `pySearchWord` moved to pysem in
  J89-4a and the config reader to `grantconfig.ts` in J89-5b). dream.ts imports four scans from it,
  each a port of a `dream.py` pattern, so each is an adapter onto that CPython pattern (below). The
  relative scan hands back each match's `lead` (the body from the previous match's end to its own)
  and a `tail`, so no string position crosses the seam (a UTF-16 unit in Node, a code point in
  CPython), and the count group is a field named `digits`: the clash is gone without a rename.
- `/\p{Nd}/u` (`pyIntDigits`) and the 8 constructs of `formatFixed3` (`Object.is(x, -0)`,
  `DataView`, `setFloat64`, `getBigUint64`, BigInt `&` x2, `|`, `<<=`): both functions moved to
  `dreamre.ts` and are adapters; dream.ts re-exports them (`import` + `export { ... }`), so Node's
  public surface (`index.ts`, `dream.test.mjs`) is unchanged. The compiled dream never calls
  `formatFixed3` (component.ts prints with it).
- `/^[A-Za-z][A-Za-z0-9 ._'()\[\]-]*$/u` (`SUBJECT_OK`): the `u` flag dropped. Every atom is one ASCII
  character and nothing reads a surrogate, so the flag changed nothing; it now lowers as any literal.
- `.flatMap` (`superseded`): a loop pushing each merge's records. `consumed.map(pyHashKey)`: an
  inline arrow.

**Found by running the compiled dream, not by the census.** `store.internals()` answers an object
of arrow functions; `projectInner.facts()` lowered to `_js_invoke` (a compiled class declares
`facts`, `factPath`, `indexLine`, `writeFact`, `rebuildIndex`, `afterWrite`), which refuses a dict
at run time. dream.ts now destructures `internals()` into locals and calls each as a function (arrow
functions have no `this`, so Node's answers are unchanged). And `normalised.split(BLOCK_SPLIT)`
compiled and was refused at run time (G3-29 above).

### Adapters (J89-5c, #316 G3 U3: the dream)

| TypeScript (`memory/dreamre.ts`) | Python | Why it is the same function |
|---|---|---|
| `pyRelativeScan` | `dream.py`'s `_RELATIVE.finditer(body)` (`re.IGNORECASE`), with `_STAMPED.match(body, end)` per match; `{lead, term, stamped, simple, now, digits, unit}` per match and the rest as `tail` | Python is the reference: the TypeScript is a port of those two patterns (dream.ts's header measured `\s`, `\d`, `\b`, `.` and the case folding) |
| `pyUnresolvedTerms` | `[m.group(0) for m in _UNRESOLVED.finditer(body)]` | the port of `_UNRESOLVED` |
| `pySlotGroups` | `_SLOT.match(_BULLET.sub('', text))` as `[subject, value]` or `null` | the port of `_SLOT` and `_BULLET` |
| `pySubSpaces` | `re.sub(r'\s+', ' ', text)` | the call `collapse` made |
| `pyIntDigits` | `int(text)` as a double (infinity past the largest); since J89-5d a run of decimal digits past CPython's 4,300-digit limit is read without it (leading zeros dropped, more than 400 digits left infinity), the limit itself untouched | the call `_resolve` made; the limit case takes Node's answer (J89-5d, ruled: a crash is a bug) |
| `formatFixed3` | `format(x, '.3f')`, no sign on a value that rounds to zero; `inf`, `-inf`, `nan` | `f"{x:.3f}"`, round half to even on the exact binary value |

The patterns are `dream.py`'s own: compared with the hand-written module's compiled `_RELATIVE`,
`_UNRESOLVED`, `_STAMPED`, `_BULLET` and `_SLOT`, `pattern` and `flags` equal on all five.

**Measured against Node v26.13.0 (Unicode 17.0) on CPython 3.12.13 (UCD 15.0.0), 2026-11-16.** A seeded
corpus (the dream suite's alphabet: the relative-date words, CPython's 29 `\s` codepoints and U+FEFF,
`ı`, `İ`, `ſ`, `K`, U+0345, astral and lone-surrogate characters, Nd digits of seven scripts incl.
the mathematical digits, stamps): 20,000 bodies through `pyRelativeScan`, `pyUnresolvedTerms` and
`pySubSpaces`, 20,000 lines through `pySlotGroups`, 20,000 Nd runs through `pyIntDigits`, 20,014
doubles through `formatFixed3` (random bit patterns, sixteenths, short decimals, ±0, subnormal,
±1e300, ±Infinity, NaN): **0 differences** on every scan and on `formatFixed3`; `pyIntDigits` 13,384
of 20,000, every one a run holding a digit of U+1D7D8..U+1D7FF and none without (node's walk back to
a block's zero reads those as 9: pinned `ruling: UNRULED DIVERGENCE` in `--suite dream`, unchanged by
generation). The same corpus with three Unicode 16 assignments added (U+10D40, U+10D49, U+1C89):
87 scan and 12 unresolved differences, every one in a body holding one of them (UCD skew, the
`docs/porting.md` class), 0 otherwise. The compiled functions over the Unicode 15 corpus
(`absolutise`, `collapse`, `blockKey`, `splitBlocks`, `mergeBodies`, `mergeDescriptions`,
`claimSlot`, 20,000 each, against Node): 0 differences.

TS refactors (Node's answers unchanged): Node's `dream.js` of 053569d5 and of this tree over the
same corpus (`absolutise`, `claimSlot`, `collapse`, `blockKey`, `splitBlocks`, `mergeBodies`,
`mergeDescriptions`, `pyIntDigits`, `formatFixed3`; 180,014 calls): 0 differences; `npm test`
2,460 pass, 0 fail, 47 skipped.

Runtime names added (1): `_js_split_regex`. G1, G2 and every G3 module recompile byte for byte.

## J89-6 rules (#316 G3 U4: `memory/component.ts` generated)

`component.ts` joins the G1/G2/G3 call and is shipped as `_generated/component.py` (the shim is
`bantamkit.memory.component`). The census (this unit's first compile) counted **82 refusals**, 81
in component.ts and one in tokenledger.ts that component.ts caused; J89-6 leaves **0**. No lowering
was added or changed: every refusal went to an adapter row or a TS refactor whose Node answers are
unchanged, and every module the call already compiled recompiles byte for byte.

**The 82 refusals, and where each went.**
- 26 imports of modules the call does not compile. `pyHome` (pyfs), `SKILL_LAYER`, `SkillStore`,
  `skillRoots`, `triggersEnabled` (skills), `loadSkill` (assets), `viaEnabled`, `viaLabel`,
  `viaPick` (touch/context), `resolve` (node:path): adapter rows onto the hand-written module each
  ports (below). `frame` (replynative) and `tokenizeLabel` (skilllabel): their one caller, `fire`,
  now calls skills.ts's `fireOn`, which makes the same three calls; one adapter row. `TouchGraph`,
  `TouchLog`, `FileSet`, `shortestSuffix`, `findRepo`, `lsFiles` and the `* as recallFileMod`
  namespace (its 9 member calls and `process.cwd()`): the repository half of `recallFile` moved
  statement for statement into recallfile.ts's `fileLinks`, which is not compiled; one adapter row,
  and two constant rows for the sentences component.ts still says (`QUERY_IGNORED`,
  `RECALL_NEEDS_QUERY_OR_FILE`). The `* as queriesMod` namespace (12 member reads): named imports
  of the compiled queries module. `dream as runDream`: the plain import (a module function and a
  method of one name do not meet in Python). `formatFixed3` from dream.js (a re-export ts2py does
  not follow): imported from dreamre.ts, its existing adapter row.
- `instanceof SkillStore` (3) and `isReadOnly`'s: skills.ts's `isSkillStore`, one adapter row
  (`isinstance` of the `SkillStore` adapter). `instanceof queriesMod.SidecarWriteError` (2): the
  compiled class, named.
- `...PROJECT_STORE` (2, an imported array ts2py cannot prove one): `STORE_PARTS`, its copy by
  `map`.
- `.findIndex` (2): a private `layerAt` loop. `.split(':', 1)[0]` (3): `layerKind`, `split(':')[0]`
  (the first piece is the same with or without a limit). Destructured arrow parameters in
  `forEach` (2, `[label]`, `[label, store, writable]`): counted loops.
- `Array.from(text)` (1): `[...text]` (both iterate code points).
- A property read of a name a compiled class declares as a method: `this.store.now()` (4,
  `now` is a field), `result.archived` (4, `MemoryStore.archived()`), `context?.weights` (1,
  `UsageLedger.weights()`): each read off a destructure, as J89-5c read `internals()`. The private
  `usage()` is `ledger()`: its name made tokenledger.ts's `message.usage` read as a method value
  (the 82nd refusal).
- `.toLowerCase()` of a name (`normalizeName`): not refused at compile time, but ts2py's lowering
  refused U+03A3 and the 55 code points CPython's and ICU's tables map apart at run time (J89-7
  narrowed that to a U+03A3 next to a code point the tables classify apart; J89-7b refuses none),
  and `ΣΟΦΟΣ` is a case the store suite pins. pysem.ts's `pyLower` (Node: `toLowerCase()`), an
  adapter onto `str.lower()`, the call `normalize_name` made, and since J89-7b onto the runtime's
  `_js_m_toLowerCase`: CPython 3.11-3.13's `str.lower()` keeps U+1C89 where Node lowers it.

### Adapters (J89-6, #316 G3 U4: the component)

| TypeScript | Python | Why it is the same function |
|---|---|---|
| `path.resolve` (node:path) | `path.posix.resolve` ported over `_normalize_string` (path_join's port); win32 only a drive-absolute path | Node builtin, reproduced; `sameDirectory`'s fallback is its one caller |
| `pyHome` (pyfs.ts) | `str(Path.home())` | its doc comment |
| `pyLower` (pysem.ts) | `_js_m_toLowerCase` (J89-7b; `str.lower()` until then) | `normalize_name`'s call, as Node answers it on every CPython (`str.lower()` keeps U+1C89 on 3.11-3.13) |
| `SKILL_LAYER`, `SkillStore`, `skillRoots`, `triggersEnabled` (skills.ts) | `bantamkit.memory.skills`' own, `SkillStore` with the TypeScript spelling of the seven methods called (`pool`, `candidates`, `lookup`, `count`, `archivedRecall`, `offer`, `resolve`) and `root`; facts and pools as the generated store's shapes | skills.ts is the port (`--suite skill-layer`) |
| `isSkillStore` (skills.ts) | `isinstance(store, SkillStore)` (the adapter) | `instanceof SkillStore` |
| `fireOn` (skills.ts) | `SkillStore.fire(tokenize_label(frame(query)), shown, offer)` | the three calls `_fire` made |
| `loadSkill` (assets.ts) | `bantamkit.assets.load_skill` | assets.ts mirrors it |
| `viaEnabled`, `viaPick`, `viaLabel` (touch/context.ts) | `touch.context`'s three, a `Set` as a set, `(fact, path)` as an array | context.ts is the port |
| `fileLinks` (touch/recallfile.ts) | `current_cwd`, `find_repo`, `TouchGraph.load` over the Python layers, `ls_files`, `FileSet`, `recallfile`'s sentences, `shortest_suffix`, `history_line`, `linked_names`, in `recall_file`'s order | the repository half of `recall_file`, moved out of component.ts statement for statement |
| `QUERY_IGNORED`, `RECALL_NEEDS_QUERY_OR_FILE` (touch/recallfile.ts) | `touch.recallfile`'s | the same sentences |

**Measured against Node v26.13.0 on CPython 3.12.13, 2026-11-16.** `path_resolve` over 20,000
seeded argument lists (one to three paths of `a`, `b`, `.`, `..`, `...`, `.x`, `é`, an astral
character, a space, joined by `/`, `//` or nothing, half absolute) from one working directory:
**0 differences**. `normalize_name` (generated, through `pyLower`) over 20,000 seeded names from a
case-folding alphabet (`Σ`, `σ`, `ς` in every context, `İ`, `ß`, `ẞ`, `ǅ`, `Ǆ`, `K`, `Å`, `ﬃ`, a
Deseret capital, CPython's whitespace, a lone surrogate): **0 differences**; UCD-skew code points
were left out of the alphabet and keep the `docs/porting.md` class. `g3_store.rs`
`j89_6_component_adapters_answer_like_node` pins 19 `path.resolve` answers and five lowercases to
what Node printed, and the refusal of each on a non-string; `j89_6_component_compiles_with_the_g3_call`
the zero-refusal compile.

TS refactors (Node's answers unchanged): Node's `component.js` of 25a9fadc and of this tree over the
same seeded corpus (20,000 `normalizeName`, 200 `layerLabel`, 1,500 scenarios of 5 to 19 calls each
over `layered` / `layeredForEval` with and without a skill, a native directory and the trigger
switch — save, recall, recall-by-name, `includeArchived`, the outcome filter, queries, compact,
dream, inject, rank, accounting — and the store tree after each, then `recallFile` over a git bed
and a via admission; 41,166 records): **0 differences** once the three wall-clock fields that also
differ between two runs of one dist are masked (the hot index's meta file, a `layeredForEval`
ledger, a commit sha).

Runtime names added: 0. Adapter names added: 15.
