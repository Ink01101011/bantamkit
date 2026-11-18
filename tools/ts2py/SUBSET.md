# ts2py: the accepted TypeScript subset

`ts2py <input.ts> -o <output.py>` compiles one TypeScript module into one Python module (#314).
`ts2py <a.ts> <b.ts> ... --out-dir <dir> --runtime-module ._ts2py_runtime` compiles several
together, one Python module per input named after its stem (J86, #315; see Modules below).
The parser is `oxc_parser` (exact-pinned in `Cargo.toml`); this crate only lowers its AST.
`RULES.md` is the ledger: every lowering rule, the job that introduced it, and what J86 reused,
extended or added.

This file is the contract. A construct that is not listed below is **refused at compile time**:
one line per offence on stderr, exit status 1, no output written.

```
<path>:<line>:<col>: unsupported <construct>: <snippet>
```

`<path>` is the input path relative to the enclosing git checkout, `<line>` and `<col>` are
1-based (the column counts characters), and `<snippet>` is the first line of the offending
source, cut at 80 characters. A syntax error is reported the same way as `syntax error: <message>`.

## Values

| JS value | Python value |
|---|---|
| `undefined` | `_JS_UNDEFINED`, a falsy singleton distinct from `None` |
| `null` | `None` |
| boolean | `bool` |
| number | `int` or `float` (a Python `bool` is never a number, see `typeof`); see Numbers below |
| string | `str` |
| array | `list` (only a `list`; a tuple is not an array) |
| plain object | `dict` with `str` keys |
| `Map` / `Set` | `_JsMap` / `_JsSet` (runtime support) |
| regex literal | a compiled `re.Pattern`, hoisted to a module constant `_JS_RE_<n>`; with the `g` flag, `_JsGlobalRegExp(<pattern>)` (J86) |
| BigInt (J86) | `_JsBigInt`: exact, `typeof` is `bigint`, never equal to a number (`1n !== 1`, distinct `Map` keys) |
| `-0` (J86) | the float `-0.0` (an `int` has no negative zero) |
| class instance (J86) | an instance of the generated class, a subclass of `_JsObject`; fields are attributes spelled as in JS |
| `Error` and subclasses (J86) | `_JsError` (a Python `Exception`); `TypeError` is `_JsTypeError` (also a Python `TypeError`) |

## Numbers

A JS number is an IEEE-754 double; a Python `int` is exact. The generated code keeps the JS
model without giving up `int`:

- An `int` within +-2^53 is exactly a double, so it stays an `int` and prints as JS prints it
  (`3`, never `3.0`).
- Wherever the lowering does arithmetic or compares numbers (`-`, `+`, unary `-`, `<`, `<=`, `>`,
  `>=`, `===` / `!==`, so also a sort comparator's result), and wherever a number is stringified
  (`JSON.stringify`, template literals, `.join`, a `Map` / `Set` key), an `int` beyond +-2^53 is
  first rounded to the nearest double (ties to even, as `JSON.parse` rounds it; past the double
  range it is +-Infinity) by the runtime helper `_js_num`. The result of `+` / `-` is rounded the
  same way.
- So `9007199254740993 - 9007199254740992` is `0`, `9007199254740992 + 1 === 9007199254740992`,
  and `JSON.stringify(12345678901234567890)` is `12345678901234567000`, as in Node.
- `Number.isInteger` reads its argument as that double too, so an int past the double range (the
  309-digit integer spelling, which `JSON.parse` reads as Infinity) is not an integer, as in JS.
- J86: `*`, `/` and `%` go through `_js_mul` / `_js_div` / `_js_mod`, which compute on the two
  doubles: `/` is IEEE division (`1 / 0` is `Infinity`, `0 / 0` is `NaN`, `1 / -0` is
  `-Infinity`), `%` takes the sign of the dividend (`-7 % 3` is `-1`, `-4 % 2` is `-0`) and is
  `NaN` for a zero divisor or an infinite dividend, `*` keeps the sign of a zero (`0 * -5` is `-0`).
  An integral finite result within 2^53 comes back as an `int` (except `-0`), so it still prints
  as JS prints it. Unary `-` of anything but a non-zero literal is `_js_neg`, so `-x` of `0` is
  `-0`. A result of `*`, `/`, `%` is a known number only when both operands are.
- J86: a BigInt is `_JsBigInt` (literal `5n`, or `BigInt(x)`: an integral number, a boolean, or a
  string in StringToBigInt's grammar, else the RangeError / SyntaxError JS raises). `+`, `-`, `*`,
  `/` (truncating) and `%` (sign of the dividend) on two BigInts are exact; a BigInt divisor of
  `0n` is a RangeError; a BigInt mixed with a number in arithmetic is the TypeError JS raises
  (`Cannot mix BigInt and other types, use explicit conversions`). `<` and friends compare a BigInt
  with a BigInt or a number by exact value. `0n` is falsy. `String(n)` / `n.toString(radix)` print
  it exactly.
- Otherwise a value only read, stored or passed along is not rounded: rounding happens where JS
  would make the difference observable through one of the operations above or a check that
  depends on the double (`Number.isInteger`).

## Strings are compared as UTF-16 code units

A JS string is a sequence of UTF-16 code units; a Python `str` is a sequence of code points. The
two orders agree except where an astral character (U+10000 and up, one surrogate pair in JS)
meets U+E000..U+FFFF: JS puts the astral character first (its lead unit is 0xD800..0xDBFF), Python
last. ts2py lowers every construct that could tell the two apart faithfully rather than refusing
it (J85-R F2, F3):

- `<`, `<=`, `>`, `>=` on anything but two known numbers lower to `_js_lt` / `_js_le` / `_js_gt` /
  `_js_ge`, JS's Abstract Relational Comparison: two strings compare by UTF-16 code unit, so
  `'\uffff' < '😀'` is `false` and `['😀', '\uffff', 'a']` sorted by `(x, y) => x < y ? -1 : ...`
  is `a,😀,\uffff`, as in Node. Any other pair goes through ToPrimitive (an array or object is its
  `String()`) and ToNumber (JS's string-to-number grammar: trimmed JS whitespace, `0x` / `0o` /
  `0b`, `Infinity`, empty is `0`, anything else `NaN`), so `'10' < 9` is `false`, `null < 1` is
  `true`, and a comparison with `NaN` or `undefined` is `false` both ways. Two known numbers (a
  literal, the `.length` of a known string, an arithmetic result) keep the plain Python operator.
- `.length` and `.size` are known numbers only on a receiver known to be a string (a string
  literal, a template, a concatenation of strings; J87: any proven `str`, and `.length` of a proven
  list, Types below). On anything else they are whatever the
  receiver holds: an array's length or a `Map`'s size, but a plain object's own `length` or `size`
  key when it has one, which may be a string or `true`. So they are compared, added and equated
  through the runtime as any unknown value is: `{length: '\uffff'}.length < {length: '😀'}.length`
  is `false` (UTF-16 order), `{length: true}.length === 1` is `false`, and
  `{size: '2'}.size + 1` is `'21'`, as in Node (J85-R2 L1).
- A regex (no flags, or `g`) matches UTF-16 code units: ts2py writes an astral literal in the
  pattern as its two surrogates (in a class, two members), and `re.test` / `re.exec` /
  `s.replace` split each astral character of the subject into its surrogates before matching. So
  `.` and a class like `[^x]` match one code unit, and `/^a.b$/.test('a😀b')` is `false` while
  `/^a..b$/.test('a😀b')` is `true`, as in Node.
- J86: every string POSITION is a UTF-16 code unit. `s[i]` reads one unit (an astral character's
  lead or trail surrogate, as in JS), and `.slice`, `.indexOf`, `.lastIndexOf`, `.padStart`,
  `.padEnd`, `.codePointAt`, `.includes`, `.startsWith` and `.split` count and search in units, so
  a separator or needle that is half of a pair is found inside one, and `''.split` gives units.
  A Python `str` holds the canonical spelling of the JS string (every lead+trail pair joined into
  its astral character, lone surrogates kept); every operation that can make two halves meet
  re-canonicalises (`_js_from_units`), so `'a😀b'.slice(0, 2) + 'a😀b'.slice(2) === 'a😀b'`.
  A literal `+` or template junction where a lead surrogate may meet a trail surrogate (neither
  side a literal whose edge is known) is `_js_cat`; every other junction stays a plain `+`.
  Iteration (`for of`, `[...s]`, array destructuring of a string) is by code point, as JS's string
  iterator is.
- `.sort()` without a comparator already ordered by code unit, and `===` is unaffected (equality
  is the same in both models). What remains is searching for half of a surrogate pair (Known
  limits).

## Accepted constructs

One line per construct: TypeScript, its Python lowering, and the JS semantic that is preserved.

### Module level

| Construct | Lowering | Preserved |
|---|---|---|
| `function f(...) {...}` | `def _f(...):` | non-exported names get a leading `_` |
| `export function f(...)` | `def f(...):`, listed in `__all__` | export set = `__all__` (sorted) |
| `export { a, b }` (J86) | `a`, `b` added to `__all__` | a module-level or imported name, exported as itself (renaming refused) |
| `import { a } from './m.js'` (J86) | `from .m import a` when `m.ts` is compiled in the same run; `from ._ts2py_adapters import a` when `adapters.rs` declares it; else refused, naming the import | Modules below |
| `class C { ... }` / `class E extends Error {}` (J86) | `class C(_JsObject)` / `class E(_JsError)` | Classes below |
| `const f = (...) => ...` (module level) | `def _f(...):` (`return <expr>` for an expression body) | same as a function |
| `const X = <expr>` (module level) | `X = <expr>` | evaluated once, in source order |
| `let X = <expr>` / `export let X = <expr>` (module level, J89-2) | `X = <expr>`, a module global; a module function that assigns it declares `global X` | every function reads it when it runs, as JS reads the live binding; it holds no type facts; a closure may read it but not assign it, it needs an initializer, and another compiled module may not import it (`from .m import X` would copy the binding once: refused as a name the module does not export) |
| `interface`, `type` alias, `import type`, `export type` | erased | type-only |

### Statements (inside a function)

| Construct | Lowering | Preserved |
|---|---|---|
| `const x = e` / `let x = e` / `let x;` | `x = e` / `x = _JS_UNDEFINED` | uninitialised `let` reads as `undefined` |
| `const [a, , b] = e` (J86) | `a, _, b = _js_destructure(e, 3)` | through the iterator: a string gives code points, a short array `undefined`, `null` a TypeError |
| `const { a, b: c } = e` (J86) | `a = _js_get(e, "a")` ... (`e` evaluated once) | a missing key is `undefined`; `null` / `undefined` a TypeError |
| `const f = (...) => ...` inside a function (J86) | a nested `def f(...)`, with `nonlocal` for every enclosing local it assigns | the closure shares the enclosing bindings, as the arrow does; refused inside a loop (JS binds per iteration) |
| `x = e` (statement) | `x = e` | `x` must be a local (a module-level binding is a const or an import) |
| `a = b = e` (J86) | `a = b = e` | one value, every target bound to it |
| `x += e`, `x -= e`, `x *= e` (J86; `x` a local or `this.x`) | `x = <x + e>` as the binary operator lowers | `x` read before `e` is evaluated |
| `o.k += e`, `o[k] -= e` (J88-2; `o` a local, `k` a local or a literal) | `_js_put(o, "k", <_js_get(o, "k") + e>)` | the property read before `e` is evaluated, then written back; anything else as the object (`o.a.k += 1`) is refused, since it would be evaluated twice |
| `[a, b] = e` (J86) | `a, b = _js_destructure(e, 2)` | as the declaration |
| `o.k = e`, `o[k] = e` (statement) | `_js_put(o, "k", e)` | sets a key on a plain object (`__proto__` is refused at run time: JS would set the prototype); on a class instance (J86) the attribute, a TypeError on a frozen one |
| `xs[i] = e` on an array (J89-2) | `_js_put(xs, i, e)` | an index inside the array, or exactly its length (an append); a write past the end (a hole) or a non-index key on an array is outside the subset at run time |
| `this.x = e` (J86) | `self.x = e` | a declared member; a TypeError once `Object.freeze(this)` ran |
| `if / else if / else` | `if / elif / else` | condition through ToBoolean (below) |
| `while (c)` | `while c:` | condition through ToBoolean |
| `for (;;)` (J86) | `while True:` | |
| `for (let i = a; test; i++) body` (J89-2: `i++`, `++i`, `i--`, `--i`, `i` a local) | as below, the update `i = _js_inc(i)` / `_js_dec(i)` (`_js_num(i + 1)` when `i` is proven a number) | ToNumeric then plus or minus one: a string `"1"` becomes 2, never `"11"`; an update of anything but a local name is refused |
| `for (let i = a; test; i -= 1) body` (J87-3) | `i = a`, `while test:`, the body, then the update as the body's last statement | the init must be a `let` declaration (or absent), the update an assignment (or absent); closures in the body are refused as in any loop |
| the same loop whose body `continue`s it (J89-4a) | `i = a`, `_js_firstN = True`, `while True:`, `if _js_firstN: _js_firstN = False` / `else:` the update, `if not (test): break`, the body | JS's order: a `continue` runs the update, then the test (a Python `continue` reaches the update at the top of the next iteration); the first iteration runs no update |
| `try { ... } finally { ... }`, `try { ... } catch { ... } finally { ... }` (J88-2) | `try:` holding the try (and its catch, as below) / `finally:` the finalizer | Python's `finally` runs where JS's does: a normal end, a `return`, a `break` and a throw; a `return` inside the finalizer replaces the completion in both |
| `try { ... } catch (e?) { ... }` (J87-3) | `_js_caughtN = None` / `try:` / `except Exception as _js_errorN: _js_caughtN = _js_catch(_js_errorN)` / `if _js_caughtN is not None:` the handler | a `catch` sees only what JS could have thrown (`_js_catch`): a JS Error (`_JsError`), an `OSError` an fs adapter raised where Node throws an fs Error, or the runtime's JS-worded `TypeError` (`Cannot read properties of null ...`); a subset refusal (`ts2py: ...`), a `RecursionError` and any other Python exception propagate. The handler runs after the `try` statement, so nothing it raises is chained to what was caught (a JS throw carries no implicit cause). `throw e` is `raise` of the caught object, unchanged; J88-2: `e` may be read as a value (passed on, `e.code`, `typeof e`), and the runtime answers only what JS would read of it: a Python exception's `code` is the errno name of an `OSError` (libuv's spelling) or `undefined`, and any other property of a Python exception (`message`, `errno`, ...) is outside the subset at run time |
| `switch (x) { case a: ... }` (J86) | `x` once into `_js_switchN`, then `if _js_strict_eq(...) / elif / else` | `===` per case, in order; empty cases group (`case a: case b:`); each case group must end in `return` / `throw` or a trailing `break` (dropped); fallthrough, a `break` elsewhere in a case, and a `default` that is not last are refused |
| `throw e` (J86) | `raise e` for `new <class or Error>(...)`, else `raise _js_throw(e)`; J87-3: `throw e` of a `catch` binding is `raise` of what was caught | throwing a value that is not an Error raises a TypeError instead |
| `for (const x of xs)` | `for x in xs:` | iterates a list, a `Map` (as `[key, value]` pairs), a `Set`, a string |
| `for (const [i, x] of xs.entries())` | `for i, x in _js_m_entries(xs):` | pairs are exact, so a plain unpack |
| `for (const [a, b] of xs)` (other iterables) | `for _js_itemN in xs:` + `a = _js_get(_js_itemN, 0)` ... | a short element reads `undefined`, not an unpack error; J89-4a: a hole (`[, b]`) binds nothing |
| `function* g(...) { ... yield v; ... }` (module level, J89-4a) | a Python generator function: `yield v` as a statement, `return;` as `return`; a body with no `yield` ends `yield` (still a generator) | lazy, as a JS generator: the body runs as the consumer pulls. Its call is allowed only as a for-of's iterable or an array spread's argument (in its own module and in any module of the call that imports it), so the object is never held: a JS `break` closes the generator, a Python `break` leaves it open, and no compiled code can iterate it again. A `yield` inside a `try` (JS closes at the `break`, Python at collection, with a GeneratorExit at the `yield`), a `yield` whose value is read, `yield*`, `return v`, a generator method or arrow, and a typed body are refused |
| `break` / `continue` (unlabelled) | `break` / `continue` | |
| `return e` / `return` | `return e` / `return _JS_UNDEFINED` | a bare return yields `undefined`; J86: a body that can run off its end gets a final `return _JS_UNDEFINED` (Python would return `None`, which is `null`) |
| parameter default `p = d` (J86) | `p=_JS_UNDEFINED`, then `if p is _JS_UNDEFINED: p = d` | applied when the argument is missing or `undefined`, evaluated at call time |
| expression statement (a call) | the call | |

### Expressions

| Construct | Lowering | Preserved |
|---|---|---|
| number literal | `int` when integral and below 2^53, else float literal | |
| string literal | double-quoted `str`; lone surrogates as `\udxxx` | |
| template literal `` `a${x}b` `` | `"a" + _js_str(x) + "b"` | substitutions stringify as JS `String()`: `3.0` is `3`, `1e21` is `1e+21`, `null` is `null` |
| `true` / `false` / `null` / `undefined` | `True` / `False` / `None` / `_JS_UNDEFINED` | |
| `[a, ...b]` | `[a, *b]` | spread of any iterable above |
| `{ k: v, s }` (static keys, shorthand) | `{"k": v, "s": s}` | insertion order |
| `{ ...x, k: v }` (J86) | `{**_js_spread(x), "k": v}` | x's own enumerable properties; `null`, `undefined` and primitives add none; a later key keeps the first one's position |
| BigInt literal `5n` (J86) | `_JsBigInt(5)` | Numbers above |
| `Infinity`, `NaN` (J86) | `_JS_INFINITY`, `_JS_NAN` | |
| `Number.MAX_SAFE_INTEGER` (J87-3) | `9007199254740991` | a known number |
| `a ** b` (J87-3), both non-negative integer literals | the exact power, folded (`2 ** 53` is `9007199254740992`) | only when the result is an integer of at most 2^53; any other `**` is refused (V8's `**` and CPython's `pow` part in the last bit for some operands, and a negative base or a fraction has JS-only rules) |
| `o?.k`, `o?.[k]` (J87-3) | `_js_opt_get(o, k)` | `undefined` when `o` is `null` / `undefined`, else the read `_js_get` makes; one optional member read only: an optional call, a link after it (`o?.k.j`) and two optional links are refused |
| `process.env[k]`, `process.env.K` (J87-3, a read) | `process_env(k)` from the adapter module | the process environment; `undefined` when unset (`adapters.rs`) |
| `this` (J86, in a class) | `self` | refused outside a class body |
| `this.x`, `this.m(...)` (J86) | `self.x`, `self.m(...)` | refused unless the class (or Error) declares the member; J88-2: `this.f(...)` of a FIELD holding a function (a clock the constructor was given) calls it without `this` (a field value ts2py compiles never reads `this`) |
| `C.m(...)` (J88-2) | `C.m(...)`, a `@staticmethod` the class declares | a static method's body has no `this` |
| `x.constructor` (J88-2, read for its `name`) | `_js_constructor_of(x)`, an object whose `name` is the JS constructor's name (`Object`, `Array`, a compiled class's, `TypeError`), or a Python exception's class name | the function itself is never handed out |
| `process.pid`, `process.env` as a value (J88-2) | `process_pid()`, `process_env_all()` (a snapshot of the environment, only ever read) | each runtime its own process |
| `a << b` (J88-2) | folded for two small non-negative integer literals (`1 << 20` is `1048576`), else `_js_shl(a, b)` | ToInt32 of the left, the count mod 32, the result wrapped to Int32; `>>>` stays refused |
| `a >> b` (J89-4a) | `_js_sar(a, b)` | ToInt32 of the left, the count's low five bits, the sign-propagating shift (Python's `>>` of an Int32 int); a BigInt operand is outside the subset at run time |
| `new Date().toISOString()` (J89-4a) | `_js_date_to_iso(_js_now())` | `new Date(Date.now())`'s spelling, as `new Date(ms).toISOString()` (J88-2) |
| `new C(...)` (J86) | `C(...)` for a compiled class; `_JsError(...)` / `_JsTypeError(...)` / `_JsRangeError(...)` (J88-2) for `Error` / `TypeError` / `RangeError`; an adapter class (`new TextDecoder(...)`, `new Date()`) from the adapter module | extra arguments ignored, as JS ignores them |
| `new RegExp(`...${n}...`)` (J86) | `_js_regexp_dynamic("<pattern>", n, ...)` | the template is checked against the whitelist grammar at compile time with each substitution as a whole `{n}` repeat count, and `n` must be an integer in 0..65535 at run time; a substitution anywhere else is refused |
| `x instanceof C` (J86) | `isinstance(x, C)` | `C` a compiled class or `Error` / `TypeError`; a primitive is never an instance |
| `k in o` (J86) | `_js_in(k, o)` | own keys, plus the names `Object.prototype` gives a plain object or instance (`'toString' in {}` is true); an array index; a TypeError on a primitive |
| `Object.prototype` (J86) | `_JS_OBJECT_PROTOTYPE` | compared by identity with `Object.getPrototypeOf` |
| `o.k`, `o[k]` | `_js_get(o, "k")`, `_js_get(o, k)` | missing key / out-of-range index reads `undefined`; reading a property of `null`/`undefined` raises `TypeError` |
| `x.length` | `_js_len(x)` | string length in UTF-16 code units, array length, else the receiver's own `length` value; a known number only when `x` is a known string |
| `x.size` | `_js_size(x)` | `Map` / `Set` size, else the receiver's own `size` value; never a known number |
| `typeof x` | `_js_typeof(x)` | `typeof true === 'boolean'`, never `'number'`; `typeof null === 'object'` |
| `a === b` / `a !== b` | `_js_strict_eq(a, b)`; `a is None` / `a is _JS_UNDEFINED` against a `null`/`undefined` literal; plain `==` when one side is a string or both are known numbers | `true !== 1`; numbers by value as doubles, objects by identity; `null !== undefined` |
| `x == null` / `x != null` (either side `null` or `undefined`) | `_js_is_nullish(x)` / `not _js_is_nullish(x)` | a missing key (`undefined`) and `None` alike |
| `a ?? b` | `_js_coalesce(a, lambda: b)`, or `_js_coalesce_value(a, b)` when `b` is side-effect free | `b` only when `a` is `null`/`undefined`; `0`, `""`, `false` kept |
| `a \|\| b`, `a && b` | `a or b` / `a and b` when both are known booleans; else `_js_or` / `_js_and` (lazy like `??`) | JS truthiness, and the operand value (not a bool) is returned |
| `!x` | `not x` (known boolean) or `not _js_truthy(x)` | ToBoolean: `[]` and `{}` are truthy, `0`/`NaN`/`""` falsy |
| `c ? a : b` | `a if c else b` | condition through ToBoolean |
| `a < b`, `<=`, `>`, `>=` | two known numbers: same operator, each operand through `_js_num` unless it is a literal, a known string's length or already rounded; anything else: `_js_lt` / `_js_le` / `_js_gt` / `_js_ge` | numbers as doubles (Numbers above); strings by UTF-16 code unit; mixed operands through ToPrimitive and ToNumber (Strings above) |
| `a - b`, unary `-a` | `_js_num(_js_num(a) - _js_num(b))`; `-<non-zero literal>`, else `_js_neg(a)` (J86) | numbers as doubles; `-0`; BigInts exactly (Numbers above) |
| `a * b`, `a / b`, `a % b` (J86) | `_js_mul(a, b)`, `_js_div(a, b)`, `_js_mod(a, b)` | Numbers above |
| `a + b` | `_js_num(...)` of `a + b` when both are known numbers, `a + b` when both known strings (`_js_cat(a, b)` when neither edge is a known-safe literal, J86), else `_js_add(a, b)` | string concatenation via `String()` when either side is a string (two surrogate halves meeting form one character); numbers as doubles; two BigInts exactly |
| `f(args)` (a module function or a local) | `f(args)` | |
| `new Map(entries?)`, `new Set(items?)` | `_JsMap(...)`, `_JsSet(...)` | insertion order; SameValueZero keys, so `true` and `1` are different keys and `1.0` and `1` the same; a `-0` key or item is stored as `0`, as JS stores `+0` (J90-RF2) |
| `/pattern/` (no flags, or `g`, J86) | `_JS_RE_<n> = re.compile(<translated>, re.ASCII)`; with `g`, wrapped in `_JsGlobalRegExp` (only `.replace` accepts it: `.test` / `.exec` on a `g` regex read `lastIndex`, which is not modelled, and raise) | `\d`, `\w`, `\b` are ASCII; `$` is end of input (`\Z`); `.` excludes `\n`, `\r`, U+2028, U+2029; an astral literal is written as its two surrogates (Strings above). The pattern is parsed against a whitelist grammar, so every accepted pattern is valid JS and compiles under `re`; anything else is refused at compile time with its reason, never an `re.error` at import (Refused below). J86 adds `\xHH` and `\uHHHH` (one code unit each, in and out of a class) and a lookbehind `(?<=...)` / `(?<!...)` holding only single-unit atoms, so its width is fixed (as `re` requires) and reading it backwards (JS) or forwards (`re`) is the same |
| an arrow used as a value (J88-2): passed to a function or method (`exclusive(p, (held) => {...})`), a block-bodied callback, or bound by `let` | a nested `def _js_fnN(p=_JS_UNDEFINED, ..., *_)` emitted just before the statement, closing over the enclosing locals (`nonlocal` for each it assigns) | a JS function called with fewer arguments sees `undefined`, with more ignores them; refused inside a loop (as any closure) and inside a callback lambda (the `def` could not see the lambda's parameters) |
| a module function named as a callback (J88-2, `rows.map(dumpsLine)`) | `lambda _js_a0=_JS_UNDEFINED, ..., *_: f(_js_a0, ...)` with as many arguments as `f` declares | JS binds the first N of `(item, index, array)` to a function of N parameters |
| `(params) => expr` **as a callback argument** of the methods below | `lambda params, *_: expr` | JS passes `(item, index, array)`; extra arguments are absorbed. J86: a parameter may be an array pattern of names, `([k]) => e` is `lambda _js_argN, *_: (lambda k: e)(*_js_destructure(_js_argN, 1))` |
| `as T`, `x!`, `satisfies T`, `<T>x`, `f<T>(...)`, generics, `readonly`, parameter and return annotations, `p?:` | erased (`p?:` becomes `p=_JS_UNDEFINED`); J87: a parameter annotation may give its function a typed body behind a guard (Types below) | a missing optional argument is `undefined` |

### Builtins

| Call | Lowering | Preserved |
|---|---|---|
| `Array.isArray(x)` | `_js_is_array(x)` | a `list` only |
| `Number.isNaN(x)` (J86) | `_js_number_is_nan(x)` | a number that is NaN; no coercion |
| `Number(x)`, `String(x)`, `BigInt(x)`, `parseInt(s, radix?)` (J86) | `_js_number`, `_js_str`, `_js_bigint`, `_js_parse_int` | ToNumeric / `String()` / StringToBigInt / parseInt's prefix grammar (JS whitespace, sign, `0x`); a parseInt past 2^53 in a radix V8 rounds approximately is outside the subset |
| `Math.floor`, `Math.abs`, `Math.max(...)`, `Math.min(...)` (J86) | `_js_floor`, `_js_abs`, `_js_max`, `_js_min` | NaN, the infinities and `-0` kept; any NaN argument makes max/min NaN; +0 beats -0 for max; no argument is -Infinity / Infinity; J87-3: a spread argument (`Math.min(...xs)`) only of a value proven a list |
| `Math.trunc(x)`, `Number.isFinite(x)` (J87-3) | `_js_trunc`, `_js_number_is_finite` | ToNumber then toward zero, NaN / the infinities / the sign of a zero kept (`Math.trunc(-0.5)` is `-0`); a number that is not NaN or an infinity, no coercion |
| `JSON.parse(text)` (J87-3, one argument) | `_js_json_parse` | the JSON grammar exactly (CPython's strict decoder, the bare `NaN` / `Infinity` it accepts refused); numbers as JS numbers (`3000000.0` is the int `3000000`, a long integer rounds to the double, past the range is Infinity); a repeated key keeps its first position and its last value; `__proto__` an ordinary own key; a malformed text is a SyntaxError whose `message` is outside the subset (V8's wording is not reproduced) and whose Python text is CPython's decoder message; J88-2: a text nested past CPython's recursion limit is read by an iterative parser over the same grammar (`_js_json_parse_deep`, strings by `json.decoder.scanstring`), as V8 reads any depth |
| `Object.keys(o)`, `Object.entries(o)` (J86) | `_js_object_keys`, `_js_object_entries` | own enumerable keys in JS order (array indices ascending first); an instance's fields in definition order |
| `Object.hasOwn(o, k)`, `Object.fromEntries(entries)` (J87-3F) | `_js_object_has_own`, `_js_object_from_entries` | an OWN property only, never what `Object.prototype` gives (`__proto__` is own when the object holds it; an array or a string owns its indices in range and `length`; a number, boolean or BigInt owns nothing; `null` / `undefined` throw TypeError); `fromEntries` of an array of `[key, value]` arrays, each key an own data property (CreateDataProperty, so `__proto__` is a key), a repeated key keeping its first position and its last value, a missing value `undefined`; any other receiver, iterable, entry or a non-primitive key is outside the subset |
| `Object.freeze(this)` (J86) | `_js_freeze(self)` | later writes raise JS's TypeError; freezing a plain object or array is outside the subset |
| `Object.getPrototypeOf(o)` (J86) | `_js_get_prototype_of(o)` | `Object.prototype` for a plain object, the class for an instance, a distinct stand-in for anything else |
| `String.fromCodePoint(...cps)` (J86) | `_js_from_code_point` | each an integer in 0..0x10FFFF, else RangeError; two halves passed separately form one character |
| `s.codePointAt(i)` (J86) | `_js_m_codePointAt` | UTF-16 position; a lead surrogate followed by a trail gives the astral code point, otherwise the unit; out of range is `undefined` |
| `s.indexOf(x, from?)`, `s.lastIndexOf(x, from?)` (J86) | `_js_m_indexOf`, `_js_m_lastIndexOf` | UTF-16 positions, `from` clamped as JS clamps it (a NaN `from` of lastIndexOf is +Infinity); strings only |
| `s.padStart(n, f?)`, `s.padEnd(n, f?)`, `s.repeat(n)` (J86) | `_js_m_padStart`, `_js_m_padEnd`, `_js_m_repeat` | length in UTF-16 units; the filler cut to fit; a negative or infinite count is RangeError |
| `s.toLowerCase()`, `s.toUpperCase()` (J86) | `_js_m_toLowerCase`, `_js_m_toUpperCase` | ASCII exactly; a non-ASCII string raises (CPython and V8 follow different Unicode versions); J88-2: `toLowerCase` of a non-ASCII string is `str.lower()` unless it holds one of the 55 code points whose mapping the two tables differ on, or U+03A3 (final sigma is contextual), which raise; J89-7: the 55 are mapped to Node 26.13's answer before `str.lower()`, and a U+03A3 raises only when its Final_Sigma walk (over CPython's Case_Ignorable) reaches a code point CPython has as `Cn`, or U+0295 / U+1171E, the only places the two tables classify a sigma context apart; J89-7b: nothing raises: a U+03A3 is lowered by the Final_Sigma walk itself, over Node's Case_Ignorable / Cased for the 307 code points CPython 3.11's table classifies apart (fewer on later versions) and CPython's own elsewhere, and the 55 are translated only when a precompiled class finds one |
| `s.trim()`, `s.endsWith(x)` (J88-2) | `_js_m_trim`, `_js_m_endsWith` | JS's WhiteSpace and LineTerminator (U+FEFF trimmed, U+001C-U+001F and U+0085 not: not `str.strip()`); by UTF-16 unit |
| `m.values()` (J88-2) | `_js_m_values` | a Map's values, a Set's items or an array's elements, as a fresh list (only spread or iterated at once) |
| `m.keys()` (J89-4a) | `_js_m_keys` | a Map's keys, a Set's items or an array's indexes, as a fresh list (the same snapshot as `values`) |
| `a.forEach(cb)` (J89-4a) | `_js_m_forEach` | an array: `cb(item, index, a)` for each index below the length read at the start that is still present when reached (a pushed element is not visited, a popped one is skipped); answers `undefined`; a `thisArg` is refused (arity) and a Map's or Set's `forEach` raises at run time |
| `a.copyWithin(t, s, e?)` (J89-4a) | `_js_m_copyWithin` | an array: each bound ToIntegerOrInfinity, a negative one from the end, clamped; the count the smaller of the source's and the target's room; an overlap copied as through a temporary; answers the array |
| `a.splice(i, n, ...xs)` (J89-4a) | `_js_m_splice(a, i, n, *xs)` | a spread argument proven a list (a string, a Map or anything unproven is refused) |
| `new Date(ms).toISOString()` (J88-2) | `_js_date_to_iso(ms)` | TimeClip then toward zero; `+YYYYYY` / `-YYYYYY` outside years 0-9999; a value past 8.64e15 or not finite is the RangeError `Invalid time value`; a string is outside the subset |
| `Date.now()` (J88-2) | `_js_now()` | whole milliseconds, `time.time_ns() // 1_000_000` |
| `Object.assign(target, ...sources)` (J88-2) | `_js_object_assign` | each source's own enumerable keys [[Set]] on a plain object or an instance (an Error given a `code`); a source that is not a plain object is outside the subset |
| `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)` (J88-2) | `_js_sleep_ms(ms)` | the one spelling of a synchronous sleep (nothing can notify a fresh buffer); a wait that never ends is outside the subset; any other `Atomics.wait` is refused |
| Buffers (J88-2) | `bytes` / `bytearray` (`Buffer.alloc`) / `memoryview` (`subarray`, sharing the bytes as Node's does) | `buf.length`, `buf[i]` (`undefined` out of range), `buf.toString('utf8' / 'hex')`; `Buffer.from(s, 'utf8')`, `Buffer.concat`, `Buffer.alloc` through the adapter seam |
| `s.charCodeAt(i)` (J89-2) | `_js_m_charCodeAt` | the UTF-16 code unit at `i` (half of an astral pair), NaN outside the string; `i` ToIntegerOrInfinity (missing or NaN is 0) |
| `s.match(re)` (J89-2, a regex literal) | `_js_m_match` | with `g`: every match's text over UTF-16 code units, an empty match stepping one unit, `null` when none; without `g`: what `re.exec(s)` answers |
| `x.toFixed(f)` (J89-2) | `_js_m_toFixed` | Number.prototype.toFixed: the integer nearest `x * 10**f` on x's EXACT binary value, the larger on a tie (so a tie rounds away from zero: `(0.0009765625).toFixed(9)` is `0.000976563`, where Python's `format` rounds half to even); `-0` is `0`; NaN, the infinities and `|x| >= 1e21` are the number's `String()`; `f` outside 0..100 is RangeError; a receiver that is not a number is TypeError |
| `buf.indexOf(byte, offset?)` (J89-2, a Buffer, `byte` a number) | `_js_m_indexOf` | `byte >>> 0` truncated to eight bits; the offset ToNumber (NaN or missing is 0), negative from the end, truncated toward zero |
| `k in m` (J89-2, `m` a Map or Set) | `_js_in` | false for every key but what `Map.prototype` / `Set.prototype` / `Object.prototype` hold (`'get' in m`, `'size' in m`), as JS's prototype chain answers |
| `s.replace(p, r)` (J86) | `_js_m_replace` | a string `p` replaces its first occurrence, a regex its first match, a `g` regex every match (empty matches as JS steps over them); `r` must be a string without `$` (JS's substitution patterns are outside the subset) |
| `re.exec(s)` (J86) | `_js_m_exec` | `null` on no match; else an array of the match and groups (`undefined` for a group that did not take part) with `index` and `input` |
| `x.toString(radix?)` (J86) | `_js_m_toString` | an instance's own `toString`; `Error.prototype.toString` (`name: message`); a number or BigInt in radix 2..36 (a fraction only in radix 10) |
| `a.reverse()`, `a.pop()`, `a.filter(cb)` (J86) | `_js_m_reverse`, `_js_m_pop`, `_js_m_filter` | in place / `undefined` when empty / callback through ToBoolean |
| `a.splice(start, count?, ...items)`, `a.reduce(cb, init?)` (J87-3) | `_js_m_splice`, `_js_m_reduce` | in place, the removed elements returned, `start` / `count` clamped as JS clamps them; left to right over the length read at the start, JS's TypeError for an empty array with no initial value |
| `x.m(...)` for a method a compiled class declares (J86) | `_js_invoke(x, "m", ...)`; when a builtin above has the same name, `_js_dispatch(x, "m", _js_m_m, ...)` | the receiver decides, as JS's prototype lookup does: an instance runs its own method, anything else the builtin |
| `Number.isInteger(x)` | `_js_number_is_integer(x)` | `3.0` is an integer; `True` is not (not a number); an int past the double range is not (it is Infinity in JS) |
| `JSON.stringify(x, replacer, space)` (J88-2) | `_js_json_stringify_with(x, replacer, space)` | SerializeJSONProperty in ECMA-262 order: a function replacer called `(key, value)` on every value, the root under `""`, before the type is read; `space` a count (at most 10) or a string (its first 10 units); `"key": value` and one value per line when indented, `[]` / `{}` when empty; a cycle is JS's TypeError; an array-of-keys replacer and nesting past the recursion limit are outside the subset |
| `JSON.stringify(x)` (one argument) | `_js_json_stringify(x)` | byte for byte: compact, non-ASCII unescaped, lone surrogates and control characters `\u00xx`, integral floats as `3`, `1e21` as `1e+21`, an int beyond 2^53 as the double it rounds to, non-finite as `null`, `undefined` members skipped (`null` in arrays), object keys in JS own-property order (array-index keys ascending first, then insertion order) |
| `m.has(k)`, `m.get(k)`, `m.set(k, v)` | `_js_m_has` / `_js_m_get` / `_js_m_set` | `Map`; `get` of a missing key is `undefined`; `set` keeps the original position |
| `buf.equals(other)` (J90-3) | `_js_m_equals` | two Buffers (`bytes`, `bytearray`, a `memoryview`): whether they hold the same bytes; a second argument that is not one is outside the subset; `equals` joins `JS_METHOD_NAMES` (read as a value it is refused) |
| `buf.toString('base64')` (J90-3) | `_js_buffer_to_string` | RFC 4648 with `=` padding, Node's `base64` encoder; `utf8`, `latin1` and `hex` as before |
| `m.delete(k)` (J90-2) | `_js_m_delete` | a `Map` or a `Set`: whether the key was there; a later `set` of it appends at the end; anything else raises at run time (`.delete() on <type> is outside the subset`). An iteration of the same Map or Set skips an entry deleted before it is reached (Known limits) |
| `s.has(x)`, `s.add(x)` | `_js_m_has` / `_js_m_add` | `Set` |
| `a.every(cb)`, `a.some(cb)` | `_js_m_every` / `_js_m_some` | callback result through ToBoolean |
| `a.find(cb)` | `_js_m_find` | no match is `undefined`, never `None` |
| `a.map(cb)` | `_js_m_map` | |
| `a.push(...xs)` | `_js_m_push` | returns the new length; J86: a spread argument (`a.push(...b)`) iterates `b` |
| `a.slice(start?, end?)` | `_js_m_slice` | negative and out-of-range bounds clamp as in JS; J86: on a string, by UTF-16 unit |
| `a.join(sep?)` | `_js_m_join` | default `,`; `null`/`undefined` elements join as empty; J86: two surrogate halves that meet form one character |
| `a.sort(cmp?)` | `_js_m_sort` | in place, returns the array, **stable**; with a comparator, the comparator's sign orders (NaN is 0); without one, by `String()` in UTF-16 code-unit order; `undefined` last; J87-3: the comparator may be an adapter function named directly (`names.sort(cmpCodepoint)`), which `_js_m_sort` calls with the two values JS passes |
| `a.entries()` | `_js_m_entries` | `[index, item]` pairs (a `Map` gives `[key, value]`) |
| `s.includes(x)`, `a.includes(x)` | `_js_m_includes` | substring (J86: by UTF-16 unit); array membership by SameValueZero |
| `s.startsWith(p)` | `_js_m_startsWith` | J86: by UTF-16 unit |
| `s.split(sep)` (string separator) | `_js_m_split` | J86: by UTF-16 unit, so `""` splits into code units |
| `s.split(re)` (a regex, J89-5c) | `_js_m_split` -> `_js_split_regex` | ECMA-262's `RegExp.prototype[@@split]` with no limit, over UTF-16 code units: the splitter tried at each position from the end of the last piece; an empty match where the last piece ended moves on one unit, a match starting at the end is never taken; each capture group joins the result after its piece (`undefined` when it took no part); `''` is `[]` when the splitter matches it, else `['']`; a `g` flag changes nothing. A limit (a second argument) is refused at compile time |
| `re.test(s)` | `_js_m_test` | `re.search` on `String(s)` with each astral character split into its surrogates, so the pattern sees UTF-16 code units |

A method above called on a receiver of the wrong runtime type raises
`TypeError("ts2py: .<method>() on <type> is outside the subset")` instead of guessing.

## Types: proven facts and the fast paths they take (J87, #316)

ts2py uses the types the TypeScript declares only where the compiler can PROVE what the Python
value is, and lowers a construct to cheaper exact Python only under that proof; anywhere the proof
fails, the J85/J86 lowering above (the JS-semantics helper) is what runs. Every fast path below is
pinned twice in `tests/types.rs` (taken where proven, not taken where the proof fails), and the
probe runs under Python against Node's output for the same source.

**Mechanism.** oxc (exact-pinned) parses and gives the AST; it has no type checker, and its
semantic crate would only give scopes and symbols, which `src/lower.rs` already computes. `tsc`'s
checker would give declared types, but they are not proofs of a Python value (`any`, `as`, `!`,
`JSON.parse`, bivariant parameters, adapters) and would put Node into every compile. So ts2py
infers locally (`src/types.rs`): facts come from what the compiler itself controls, and are found
by a **greatest fixpoint** over the module. `lib.rs` lowers the module, collects what each round
observed (every binding's value, every function's returns, every call site, every use of a frozen
constant), and lowers again under those facts until a round observes exactly what it assumed.
The first round assumes everything ("optimistic"); every later round can only take a fact away or
add a guarded entry or an escape, so it ends (it is refused after 64 rounds). At the fixpoint every
fact was re-proved by every assignment, return and call site of the final lowering. An optimistic
fact still standing there belongs to a value no code ever produces (a function that never
returns), so nothing reads it.

**What is a fact.** A fact is a property of the Python value:

| Fact | The value | Proved by |
|---|---|---|
| `str` | `type(v) is str` | a string literal or template; `+` of two strings; `typeof`; a method whose result is always a string (`join`, `slice` of a string, ...); a `string` parameter in a typed body; a narrowing |
| `num` | a plain `int` within +-2^53, or a `float` (what `_js_num` leaves unchanged) | a number literal; `+ - * / %` of two numbers (rounded by `_js_num`); `.length` of a proven string or list; `indexOf`; `Math.*`; a `number` parameter in a typed body |
| `f64` (J89-3) | `type(v) is float` (so also `num`) | a literal Python spells as a float (`0.75`, `1e+21`, `-0.0`); a Float64Array element read in a proven loop copy; `+ - * /` of two proven numbers one of which is a float |
| `bool` | `type(v) is bool` | a comparison, `!`, a method or builtin that always returns a boolean; a `boolean` parameter in a typed body |
| `list` | a Python `list` | an array literal; `split`, `map`, `filter`, `sort`, `reverse`, `entries`; an array or tuple parameter in a typed body |
| `regex` | a compiled `re.Pattern` without `g` | a regex literal |
| `match` | `None` or a match array (element 0 the matched `str`) | `.exec` |
| tuple | a FRESH array of exactly n items with these facts | an array literal; a function every return of which is one; a `const` whose every read is a literal index or a nullish or truthiness test (so nothing else can hold, and mutate, it) |
| elements | what every element (or property value) is | a non-exported module `const` bound to an array or object literal whose every use is a destructuring `for-of` (arrays) or a member read (objects): a **frozen** constant; any other use escapes it |
| "X or undefined" | X whenever not nullish | an index into a proven string (`str` or `undefined`); a property of a frozen object |

A binding (a `const`, `let`, parameter, loop or destructured name) holds the meet of every value
any assignment gives it, met over the whole function (flow-insensitive), and keeps only the flags:
an array it holds may be mutated later, so no tuple or element fact survives a binding (except the
two `const` cases above). **Narrowing** is the one flow-sensitive rule, and only on a `const`
(local or module, never reassigned): after `if (<test>) <exits>` for the rest of the block, inside
`if (<test>)` for the consequent and in a plain `else`, a test that rules out `null` and
`undefined` (`x === undefined` when `x` is never `null`, `x == null`, `!x`, `x`), that compares
`x === '<string literal>'`, or `typeof x === 'string'` / `'boolean'` (and `&&` / `||` of such
tests) narrows `x` to what it is there. A number literal does not narrow: `===` compares numbers as
doubles, so an int past 2^53 can equal one.

**Typed bodies and the guarded entry.** A module function whose parameters carry an annotation
the guard can check (`string` and string-literal unions, `number` and numeric literals,
`boolean`, arrays and tuples, `readonly` of those, aliases of these) gets a typed body in which
those parameters hold their facts. A call whose arguments prove them calls the typed body. When
anything else can reach the function (it is exported, read as a value, or called with an argument
a call site cannot prove), the function's own name is a guarded entry:

```python
def _scan_quoted(front, pos, quote):
    if type(front) is str and _js_is_double(pos) and type(quote) is str:
        return _scan_quoted__typed(front, pos, quote)
    <the untyped body: the J86 lowering>
```

so a Python caller, an adapter or `JSON.parse` data with any value runs the untyped body and gets
JS's answer for it (`tests/types.rs` calls an exported function with an array where its
annotation says `string`). Optional and defaulted parameters are not guarded. Class methods,
constructors and closures have untyped bodies only. A call into another compiled module goes
through that module's guarded entry, and its result proves nothing. The typed body's name is
`_<name>__typed`; a collision with a source name is refused like any other.

**Not proof**, anywhere: `any`, `unknown`, `as`, `!`, `satisfies`, a return-type annotation, a
union the path does not cover, and any value from `JSON.parse`, an adapter or another module.
J87-3 dropped the J85 rule that a call of a function annotated `: boolean` is a known bool: what a
call proves is what every `return` of the body proved (the fixpoint's return facts), so
`function isIt(x: any): boolean { return x; }` is tested with JS truthiness (`tests/types.rs`,
`a_boolean_return_annotation_is_not_proof`; it changed one line of the committed `factfile.py`,
where `value.truthy` had been trusted).

**The fast paths.** Each is exact for the receiver and argument facts it requires and takes the
general helper otherwise; each helper in `src/runtime.py` returns exactly what the general helper
returns for that receiver and falls back to it for any argument its own fast case does not cover
(`proven_receiver_helpers_answer_as_the_general_helpers` fuzzes every pair; a helper mutant turns
it red).

| Construct | Proven | Lowering | Otherwise |
|---|---|---|---|
| `a === b` | both `str` (or one), both `num`, both `bool` | `a == b` | `_js_strict_eq` |
| `a + b`, `a - b`, `<` ... | both `num` | `_js_num(a + b)`, `a < b` (J85 rule, now reached through facts) | `_js_add`, `_js_lt` ... |
| `x.length` | `str` / `list` | `_js_str_len(x)` / `len(x)` | `_js_len` |
| `x[i]` | `str` / `list` | `_js_str_at(x, i)` / `_js_list_at(x, i)` | `_js_get` |
| `x[k]`, `k` a literal | a fresh tuple of more than `k` items | `x[k]` | as above |
| `xs.push(v)` | `list` | `xs.append(v)` as a statement, else `_js_m_push(xs, v)` | `_js_dispatch(...)` / `_js_m_push` |
| `xs.includes(s)` | `list` and `str`, one side pure | `s in xs` (no runtime value but a `str` equals one) | `_js_m_includes` |
| `s.includes(t)`, `s.startsWith(t)` | both `str` | `_js_str_includes`, `_js_str_starts_with` | `_js_m_*` |
| `s.indexOf(t, p?)` | `str`, `t` a `str` | `_js_str_index_of` | `_js_m_indexOf` |
| `s.slice(a?, b?)` | `str` | `_js_str_slice` | `_js_m_slice` |
| `xs.join(sep?)` | `list`, `sep` a `str` | `_js_list_join` (`str.join`, which refuses all but `str` elements, then the general join) | `_js_m_join` |
| `re.test(s)` | `regex` and `str` | `re.search(_js_code_units(s)) is not None` | `_js_m_test` |
| `re.exec(s)` | `regex` and `str` | `_js_re_exec` | `_js_m_exec` |
| `s.replace(re, 'lit')` | `str`, `regex`, a literal without `$` or `\` | `_js_re_replace` (`re.sub` with the literal) | `_js_m_replace` |
| truthiness, `!s` | `str` | `s != ""` | `_js_truthy` |
| `const [a, b] = e` | `e` a fresh tuple of exactly that length | `a, b = e` | `_js_destructure` |
| `for (const [a, b] of T)` | `T` frozen, rows of exactly that length | `for a, b in T:` | `_js_get(row, i)` |
| `a + b`, `a - b`, `a * b` (J89-3) | both `num`, one `f64` | the native operator (IEEE-754; an int within 2^53 converts exactly), a `float` | `_js_num(a + b)`, `_js_mul` ... |
| `a / b` (J89-3) | both `num`, one `f64` | `a / b if b else _js_div(a, b)` (a name or literal `b`), else `_js_fdiv(a, b)`: Python's `/` but a zero divisor's JS answer | `_js_div` |
| a `str` binding indexed or `.length`-ed | a parameter or declared local never assigned again | its UTF-16 view `_jsu_<name> = _js_code_units(<name>)` beside the binding; `len(_jsu_s)`, `_jsu_s[i] if type(i) is int and 0 <= i < len(_jsu_s) else _js_str_at(s, i)`, `_js_units_at` / `_js_units_index_of` / `_js_units_slice` | the `_js_str_*` helpers |

Known limits: a binding's facts are met over the whole function, so one unproven assignment
(`i += used` where `used` is unproven) makes every read of it unproven; narrowing applies to
`const` bindings only and never across a loop's back edge; methods and closures are untyped.

## Typed arrays and counted loops (J89-3, #316 G3)

**`Float64Array`.** `const t = new Float64Array(n)` is a Python `list` of `float`s
(`_js_f64_new`: ToIndex of `n`, so `2.7` is 2 and NaN is 0; a negative length, or one past
2^53 - 1, is the RangeError Node throws with the value in its message; a BigInt is Node's TypeError;
an object argument, which Node would copy, and a length past 2^26 are refused at run time). A write
converts its value (ToNumber, then a float), so every element is always a float: that is the proof
the lowerings below use. The binding may only be

- indexed, `t[k]` (`_js_ta_get`): the element, or `undefined` for a numeric key that is not a valid
  index (out of range, a fraction, NaN, an infinity, the string `"-0"`); the number `-0` names
  element 0, as its key is `"0"`;
- written by index, `t[k] = v` (`_js_ta_put`): ToNumber of `v` first, then the float stored at a
  valid index and nothing stored otherwise;
- measured, `t.length` (`len(t)`, fixed when it is made);
- the keys of the key sort below.

A key that is not a number or a canonical numeric string is refused at run time (JS would read or
make an ordinary property). Anything else is refused at compile time: the array as a value
(returned, passed, aliased, iterated, spread, a method called on it), `let t = new Float64Array`,
`new Float64Array` anywhere but a `const`'s initializer, `t[k] op= v`.

**Counted loops proven once.** `for (let i = a; i < b; i += 1)` (or `i++`, `++i`, `i = i + 1`)
whose body indexes arrays by `i` itself is lowered twice: a proven copy under a guard, and the
general loop as before:

```python
i = <a>
if type(i) is int and 0 <= i and type(b) is int and b <= len(t) and type(xs) is list and b <= len(xs) and _js_doubles(xs, i, b) and _js_is_double(w):
    for i in range(i, b):  # noqa: B020
        t[i] = t[i] + xs[i] * w        # floats and proven numbers, native
else:
    while ...:                         # the general loop
```

The guard checks, once: `i` an int at least 0; `b` an int (a name the body does not assign, a
literal, or a Float64Array's length) no larger than the length of every Float64Array and every fresh
array the body indexes at `i`; every plain array the body reads at `i` a list that long whose
elements over `[i, b)` are proven numbers (`_js_doubles`: floats, and ints within 2^53, nothing
else); every `const` or parameter the body uses as an operand of arithmetic or a comparison a proven
number; and every outer `let` the body assigns and uses as an operand, when each assignment the copy
makes to it is a proven number (else the copy is made without it). It holds for the whole loop
because the body cannot change any of it: the body holds expression statements, `if`, `const` /
`let`, `return` and an unlabelled `break` only; it assigns locals, Float64Array elements at `i`
and fresh-array elements at `i` (a fresh array is a `const` bound to an array literal or to
`.slice(...)`, which no parameter can alias), pushes onto fresh arrays only, and calls adapters and
`Math.max/min/abs/floor/ceil/trunc/round/sign/sqrt` only, so no compiled code and no caller's code
runs while it loops; it reads no member but `x[i]` and a Float64Array's `.length`; it holds no
closure, no nested loop, no template. In the copy, `i` is a proven number, `t[i]` is a proven float,
`xs[i]` a proven number, and `t[i] = v` / `fresh[i] = v` are the stores themselves.

**The key sort.** `xs.sort((a, b) => t[b] - t[a] || a - b)` (or `t[a] - t[b] || a - b`) with `t` a
Float64Array is `_js_sort_by_f64`: when every item is an int index into `t` and no key it names is
NaN, the comparator is a total order (key, then index), so two stable sorts (by index, then by key)
are V8's order at C speed; otherwise V8's own sort runs with the comparator (`_js_v8_sort`, V8's
`Array.prototype.sort` step for step, so even a NaN key's inconsistent comparator leaves V8's
order). Any other comparator is the general `.sort`.

## Storage speed (J90-P, #316 G4)

Each lowering below is pinned TAKEN and answering as Node does in `tests/j90p.rs` (the probe and a
30,000-input digest of `tests/fixtures/j90p_probe.ts`); each runtime fast path is held to the
general path it shortcuts by that file's seeded fuzz.

| Construct | Lowering | Otherwise |
|---|---|---|
| `Array.isArray(x)` true, `x` a `const`, a callback parameter, or a parameter or local no assignment rebinds | narrows `x` to a list (in an `if`, the right side of `&&` / `\|\|`, a `?:` branch) | no narrowing |
| `typeof x === 'string'` / `'boolean'` / `'number'` / `'undefined'` (or `!==`) | `isinstance(x, str)` / `isinstance(x, bool)` / `_js_is_number(x)` / `x is _JS_UNDEFINED`: the one test `_js_typeof` answers that name for | `_js_typeof(x) == ...` |
| `xs.sort((a, b) => k(a) - k(b))` or `k(b) - k(a)`, `k` reads only its parameter, other bindings, members and `.get()` (no compiled class declares `get`), never a Float64Array | `_js_sort_keyed`: a stable sort by the keys when every key is a number JS holds exactly and none is NaN | the general `.sort` with the comparator |
| `new Map(Object.entries(x))`, or through a module `const` arrow `(v) => Object.entries(v)` | `_js_map_entries(x)`: a plain object's entries copied at once; when a key may be an array index, the order is settled at the first walk or write | `_JsMap(_js_object_entries(x))` |
| `for (const [a, b, , d] of xs)` (rows not proven) | `for a, b, _js_hole, d in _js_rows(xs, 4, (0, 1, 3))`: a list that long sliced at once, anything else `_js_get` of each named index | — |
| a counted loop that reads another array's `.length` (and is proven for another reason) | that array checked a list in the guard; `len(x)` in the proven copy | the general loop |

A `Map` keeps each key's `_js_key` tag mapped to its value; a key that is not its own tag (a bool,
NaN, an object, an int past 2^53) is kept beside it in `_keys`.

## Storage speed and size (J90-P2, #316 G4)

Each lowering below is pinned TAKEN and answering as Node does in `tests/j90p2.rs` (the probe and
a 3,000-input digest of `tests/fixtures/j90p2_probe.ts`, compiled as `runtime-ts/src/j90p2_probe.ts`
so `./pysem.js` is the `cmpCodepoint` adapter); each runtime fast path is held to the general path
by that file's seeded fuzz.

| Construct | Lowering | Otherwise |
|---|---|---|
| `xs.sort(compare)`, any comparator the rows below do not take | `_js_m_sort`, which runs V8's own sort (`_js_v8_timsort`): V8's order for an inconsistent comparator (a NaN key, a parity comparator) and V8's comparator calls, pair for pair | — (until J90-P2: CPython's `list.sort`, whose order differs on CPython 3.13+ and whose calls differ on every version) |
| `xs.sort((a, b) => c1 \|\| c2 \|\| ...)`, each `ci` a key difference `k(a) - k(b)` / `k(b) - k(a)` or `cmpCodepoint(k(a), k(b))` / `cmpCodepoint(k(b), k(a))` (the adapter, not a local), two parts or more, or one `cmpCodepoint` part; every `k` pure as for `_js_sort_keyed` | `_js_sort_lex`: stable sorts by each key, the last first, when every number key is a number JS holds exactly and none is NaN and every code-point key is a `str` | the general `.sort` with the comparator |
| `createHash('sha256' \| 'sha1').update(x, 'utf8').digest('hex')`, `createHash` the node:crypto adapter | `hash_hex(alg, x)`: an ASCII `str` hashed as its bytes at once, anything else the three calls with their refusals | the three calls |
| `xs.every((x) => e)` / `.some` / `.map` / `.filter`, one plain parameter, an expression body with no function (`=>`, `function`, `class`) in it | `all(e for x in xs)` / `any(...)` / `[e for x in xs]` / `[x for x in xs if e]` (a receiver not proven a list through `_js_array`), the comprehension the helper runs, `e` inline | the helper with a lambda |
| `x.length === N` (N a literal 0..16) on the left of `&&`, `x` proven a list and a `const` / stable binding, the right side `pure_test` (names, literals, member reads, `typeof`, `!`, `-`, comparisons, arithmetic, `&&` / `\|\|` / `??`, `?:`, `Number.isInteger` / `Number.isNaN` / `Array.isArray`) | the right side reads `x[k]` (k < N) as `x[k]` | `_js_list_at(x, k)` |
| a wrapped function whose guarded entry's body is the typed body line for line | one body under the function's name, the typed name bound to it (`_f__typed = f`) | both bodies |

`Number.isInteger` answers a plain int within 2^53 at once (`_js_number_is_integer`).

**The shipped support modules.** `--emit-runtime` and `--emit-adapters` write the support modules
in their SHIPPED form (`ts2py::shipped`): the leading comment block and one note line, then every
line but the full-line comments and the docstring of each function or class whose body goes on
after it; nothing inside a triple-quoted string is touched. `tests/shipped.rs` holds the shipped
runtime, and the host's `tests/shipped_adapters.rs` (bantamkit's, under `tools/ts2py-bantamkit/`)
the shipped adapters, to the source's `ast.dump` (docstrings aside), and
`runtime-py/tests/test_ts2py_fresh.py` spells the same rule. The documentation stays in the
sources, the only copies anyone edits: `tools/ts2py/python/ts2py/runtime.py` for the runtime and
the host's adapter module (bantamkit's `tools/ts2py-bantamkit/adapters.py`) for the adapters
(J90-PKG).

## Proven shapes for JSON-derived arrays (J90-P3, #316 G4)

A value read from JSON proves nothing (SUBSET.md, *Not proof*), and a TypeScript check on it
(`Array.isArray`, `every(Number.isInteger)`, a length test) proves less than a lowering needs
(`Number.isInteger` admits an int past 2^53, which `<` and `+` must round). So the shape is proven
the way the counted loop proves it (J89-3): by a guard made once, at run time, before the loop,
that checks the STRONGER property the direct reads need; a value that fails it (a string, `null`,
`-0`, a float, an int past 2^53, a length that is no multiple of the stride) takes the general
loop, which answers what JS answers. Every rule below is pinned TAKEN and answering as Node does in
`tests/j90p3.rs` (`probe()` and a 3,000-input digest over seeded malformed segment arrays read from
JSON text, `tests/fixtures/j90p3_probe.ts`), with a mutation of each shown red.

| Construct | Proven copy | Guard (once, before the loop) |
|---|---|---|
| `for (let j = a; j < b; j += S)`, `S` a whole-number literal from 1 to 1024 or a module `const` bound to one | `for j in range(j, b, S)` | as J89-3 |
| `x[j + c]`, `c` a whole-number literal or such a `const` | `x[j + c]` | `x` a list; `b <= j or j + (b - 1 - j) // S * S + c < len(x)` (the last group's read in range); with `S == 1`, `b + c <= len(x)` |
| an array some read of which (or a `const` read from it) is an operand of arithmetic, a comparison, `===`, an index, a return, or anything but a sink | its reads proven numbers | `_js_doubles(x, j, len(x))` (`_js_doubles(x, j, b)` for `x[j]` at stride 1, as before) |
| an array every read of which lands only in a SINK: a `const`'s initializer whose name then lands only in sinks, an array literal's element, `push`'s argument, a bare name tested by `if` | its reads `x[j + c]` as they are, proving nothing | bounds alone (no element check: a string array is read directly) |
| a counted loop nested in the body (`for (let k = s; k < e; k += S2)`) | lowered with its own guard and copy, per entry, inside the copy; the outer copy's proven bindings stay proven in it | the outer guard checks every array the inner loop reads by `k` is a list |
| `throw new Error('literal')`, array literals, `push` of an array literal onto a fresh array | in the copy (no compiled code runs) | — |

The general loop of a copy (what a failed guard runs) holds no copy of a nested loop of its own:
it is the rare path, lowered once. Two smaller rules ride with these: `Array.isArray(x)` is
`isinstance(x, list)` inline (`_js_is_array`'s own test; a match array is a list subclass), and a
proven number named once is tested `x != 0 and x == x` (falsy for `0`, `-0` and NaN) instead of
`_js_truthy(x)`.

**One body up to temporaries.** J90-P2's one body for a wrapped function whose guarded entry is
its typed body line for line now compares the two bodies up to the compiler's own temporaries
(`_js_caught`, `_js_error`, `_js_fn`, `_js_arg`, `_js_t`, `_js_first`, `_js_obj`, `_js_switch`,
`_js_item` followed by digits, renumbered in order of first appearance): each is local to its
body, so two bodies that differ only in those numbers are one function. It removed about 25 KB of
committed `_generated` source (a typed body with a `try` differed only there).

`decodeSegments` (storage/hotindex.ts) is written for the strided copy: a segment's five numbers
read once at `j + 0..4`, the run one nested counted loop, `names` read only as values
(`ArrayLike<string>`, so it has one body); Node's answers before and after are equal over 20,000
seeded inputs, malformed ones included.

## Classes (J86)

| Construct | Lowering | Preserved |
|---|---|---|
| `class C { ... }` | `class C(_JsObject):` (exported: as written; else `_C`), with `_js_name`, `_js_own` (fields, methods, getters) and `_js_own_methods` | a reflective read (`_js_get(x, "k")`, `k in x`, `Object.keys(x)`) sees exactly the members JS would, nothing Python adds |
| field `x = e;` / `x: T;` | `self.x = e` / `self.x = _JS_UNDEFINED` at the start of `__init__`, in declaration order | ES2022 class fields (`target: ES2022`): own properties, initialised before the constructor body runs |
| `constructor(p) { ... }` | `def __init__(self, p, *_):` (fields first, then the body) | extra `new` arguments ignored |
| method `m(p) { ... }` | `def m(self, p):` | a body that can run off its end returns `undefined` |
| getter `get g() { ... }` | `@property def g(self):` | |
| `class E extends Error {}` (J87-3: or `extends` an adapter Error class such as `BantamError`, or a class declared above that extends one) | `class E(_JsError):` (`class E(BantamError):`) | `e.message` is the argument (as `String()`), `e.name` is `"Error"` (inherited, as JS gives every subclass that does not set its own), `String(e)` is `name: message`; `e.name = "X"` makes an own `name`, and so does a class field `override name = 'X'` (J89-5a: set after the base constructor, as JS defines a field once `super` returns); a `_JsError` is a Python exception, `_JsTypeError` also a Python `TypeError` |
| `Object.freeze(this)` | `_js_freeze(self)` | a later write raises JS's TypeError (`Cannot assign to read only property 'v' of object '#<C>'`) |

Refused in a class: `static` members, computed or `#private` keys, setters, accessor properties,
decorators, `abstract`, `extends` anything but an Error class (`Error`, an adapter `ErrorClass`, or a
class declared above extending one), a constructor in a class that extends
`Error` (it would need `super`), a member whose name is a Python keyword or starts with `_` (the
runtime's own attributes do), and on an Error subclass a member named `args`, `with_traceback` or
`add_note` (Python's exceptions carry those).

## Modules and the adapter seam (J86)

J88-2: `import * as fs from 'node:fs'` (a namespace import of a `node:` builtin) is accepted, and
`fs.name(...)` is that module's adapter row (the host's table); a name with no row is refused at
compile time, and a namespace import of anything else stays refused. An adapter may be a
constant (`LOCK_STALE_MS`), read by name. An adapter function may be called with `...xs` of an
array proven a list.

- Several modules compiled in one run (`--out-dir`) import each other: `import { a } from
  './m.js'` in a module whose path is `runtime-ts/src/memory/x.ts` resolves to
  `runtime-ts/src/memory/m.ts`; if that is one of the inputs, the import is
  `from .m import <a's Python name>` (classes keep their name). The modules form a package, so
  `--runtime-module` (and the adapter module) must be importable from it.
- J90-2: two (or more) modules of one run may import each other (an import cycle: `hotindex.ts`
  and `memory/store.ts`). An import whose module imports this one back, directly or not (value
  imports only), is written at the END of the Python module (`from .m import a  # noqa: E402`), on
  every side of the cycle, so Python can import the cycle from either side with no name unbound. A
  name of the cycle may not be read while a module is executed (a module-level `const` / `let`
  initializer): refused, `module-level use of <name>, imported in an import cycle`.
- J90-3: a RE-EXPORT, `export { a, type T } from './m.js'` (`storage/index.ts`), binds each value
  name as `import { a } from './m.js'` would (a compiled module of the run, at the end of the module
  when it is in a cycle, or an adapter row) and exports it; a type is dropped. A renamed re-export,
  `export *`, and a name neither a compiled module nor an adapter row provides are refused. Another
  compiled module cannot import a name THROUGH the re-export (the re-exporting module's export table
  lists only what it declares): such an import is refused as one the module does not export.
- J90-3: a CONSTANT of a namespace-imported Node module (`path.sep` under `import * as path from
  'node:path'`) is its adapter row of kind `Constant`, read by name; any other member read of the
  namespace stays refused.
- Any other import resolves only through the HOST's adapter table (#337): the `[[adapter]]` rows
  of the file `--config` names (`src/host.rs`; the compiler declares no row of its own). A row
  names the TypeScript module (or a Node global such as `TextDecoder`), the name, the Python name
  in the host's `adapter_source` (`--emit-adapters <file>` writes it, importing the runtime from
  `--runtime-module`), and the reason the hand-written Python is the same function; a row with no
  reason is refused when the file is read. bantamkit's rows and their measurements:
  `tools/ts2py-bantamkit/ts2py.toml` and `RULES.md`, Adapters.
- J87-3: a Node builtin module (`import { join } from 'node:path'`) is looked up in the same table
  under its specifier (`node:fs`, `node:path`); `process.env` is a global row.
- An import with no compiled module and no row is a compile error naming it:
  `<path>:<line>:<col>: unsupported import of pyRepr from ./pyfs.js: no compiled module and no declared adapter: pyRepr`.
- Renamed imports and exports, default and namespace imports, and side-effect imports are refused.
- J89-4a: an `ImportedClass` row (`HotIndex`, `ColdIndex`) is a class whose methods dispatch
  (`_js_invoke`, or `_js_dispatch` where a builtin shares the name) only in a module that imports
  it, so its method names do not turn every `Set.add` of the call into a dispatch; naming one of
  them as a value is not refused at compile time (`pool.names` of a plain object reads the
  field), and on an instance the runtime refuses it (`_js_object_get`). `Buffer.byteLength(s,
  'utf8')` is a global row; `statSync(p, {bigint: true})` answers `BigIntStats`.

## Names

- A module-level **exported** name is `snake_case(name)`: `touchesRefusal` -> `touches_refusal`,
  `plan` -> `plan`. An acronym run is one word (`parseJSONValue` -> `parse_json_value`); an
  all-caps name (`MAX_WIDTH`) is kept.
- A module-level **non-exported** name is `_` + `snake_case(name)`: `readNodes` -> `_read_nodes`.
- J86: a class keeps its name (`PyScalar`), with `_` when it is not exported (`_Emitter`); its
  members keep their JS spelling (`self.bestWidth`, `def writeIndent(self)`), because a
  reflective read looks them up by that spelling.
- A local or parameter is `snake_case(name)`: `nodeId` -> `node_id`.
- A Python keyword gets a trailing `_` (`lambda` -> `lambda_`); so does any name (J89-2: a
  local or parameter too, not only a module-level name) that would shadow a builtin the runtime
  support or a generated body calls (`len` -> `len_`, `type` -> `type_`): since J87 a function
  body itself spells `type(x) is str` in its guarded entry, so a parameter named `type` made the
  guard call the string.
- Two different source names that fold to one Python name are refused (`name collision`).
- Identifiers starting `_js`, `_Js` or `_JS` are reserved for the runtime support and refused.

## Output

- Line 1: `# Generated by tools/ts2py from <path>. DO NOT EDIT: ...`; line 2:
  `# source-sha256: <sha256 of the source bytes>`; line 3: `# ruff: noqa: E501, B023`.
  E501 because generated lines are not wrapped; B023 because the only lambdas are callbacks a
  helper calls before the enclosing statement finishes, so a loop variable they read is never
  stale.
- Deterministic: the same source bytes give byte-identical output, from any working directory.
- By default the runtime support (`src/runtime.py`, pure standard library) is inlined, so the
  module stands alone. `--runtime-module <module>` imports the helpers the module uses from
  `<module>` instead, and `--emit-runtime <file>` writes the support module to `<file>`.
- J86: with `--out-dir <dir>`, every input becomes `<dir>/<stem>.py`; imports between them and
  from the adapter module (`--adapter-module`, default `._ts2py_adapters`) follow the runtime
  import. `--emit-adapters <file>` writes `src/adapters.py`, importing the runtime from
  `--runtime-module` (default `._ts2py_runtime`). Adapter classes subclass the runtime's
  `_JsObject`, so modules that use them import the runtime rather than inline it.

## Refused (not exhaustive: anything unlisted above is refused)

Generator methods and arrows, `yield*`, a `yield` used as a value or inside a `try`, a generator
call anywhere but a for-of's iterable or an array spread (J89-4a lowers the rest), `async`
functions and `await`, `this` outside a class body,
labelled statements / `break label` / `continue label`, any builtin or method not in the tables
above (`Object.create`, `Math.round`, `Math.log`, `Math.pow`, `s.trimEnd()`, `s.normalize()`,
`String.fromCharCode()`, ...; J89-2: `Math.log`, `Math.log1p` and `Math.pow` stay refused because
V8's last bit is not a function of the input across platforms, so a port of CPython's arithmetic
calls `pysem`'s adapters instead), `var`, nested `function` declarations, function expressions, an arrow inside a loop, an
arrow inside a callback lambda (J88-2 accepts one anywhere else), a callback that is neither an
inline arrow nor a module function or adapter named directly,
destructuring with defaults, rest elements, nesting or computed keys, rest parameters, optional
chaining other than one member read (J87-3), loose equality `==` other than against
`null`/`undefined`, `**` other than of two integer literals with an exact result (J87-3), the
bitwise operators but `<<` (J88-2) and `>>` (J89-4a), `void`, `delete`, unary `+`, `++`/`--` anywhere but a C-style
`for` update on a local name (J89-2), typed arrays (`Float64Array`, `DataView`), compound assignment
other than `+=` `-=` `*=` on a local, `this.x` or a property of a local (J88-2), assignment inside an expression (other than a chain of `=`
between locals), assignment to a module-level name other than a module `let` from a module
function (J89-2), a module-level `let` without an initializer, the comma operator, `switch` fallthrough between non-empty cases, a
`break` that does not end its case, a `default` that is not the last case, `do-while`, a C-style
`for` whose init is not a `let` declaration or whose update is not an assignment (J87-3; J89-4a
lowers a `continue`), `for-in`, `for await`, a write to a regex's `lastIndex` (J89-4a: the subset
models none),
computed or integer-like object keys, getters/setters and methods in object literals, tagged
templates, non-finite number literals, regex flags other than `g`, regex syntax whose meaning
differs between the engines (`\s` inside a class (J89-4a spells it out elsewhere), `\B`, named groups, backreferences, a lookbehind holding
anything but single-unit atoms, Annex B leniencies such as a bare `{`, `}` or `]` or an `\x`
/ `\u` without its digits, a quantified lookaround, a class escape as a range endpoint), regexes
JS itself rejects (a range out of order in UTF-16 code units such as `[😀-😂]`, `{3,2}`, a
quantifier with nothing to repeat, unbalanced parentheses), regexes `re` cannot compile (a
repeat count above 65535, groups nested deeper than 64), `new RegExp` of anything but a
template literal whose substitutions are whole `{n}` repeat counts, the class members listed
under Classes, `enum`, `namespace`, imports that resolve to no compiled module and no adapter,
renamed imports and exports, a block binding that shadows an enclosing one, a local that
shadows a module-level name, and any global identifier other than `undefined`, `Infinity`,
`NaN` and the builtins in the tables above.

**A method read as a value (J86-R finding 3).** A member whose target is callable may only be
the callee of a direct call: `const f = a.get`, `a.get === a.get`, `[xs.push]`, `g(s.trim)`,
`xs['map']` and `this.m` are refused, `a.get(k)` and `this.m()` are not. In JS such a read is a
function (`this` lost on a later call, the same function on every read); in Python it was a fresh
bound method or `undefined`. On any receiver but `this` the NAME decides: a method of String,
Array, Map, Set, RegExp, Number, Function or `Object.prototype` (`JS_METHOD_NAMES` in
`src/lower.rs`, the whole prototype, not only the methods the call table lowers), or a method any
compiled or adapter class declares; on `this` the class's own method list decides exactly.

J87 (#316): **a data field named like a method is read as data where the receiver's declared type
says so.** When the receiver is a binding (a `const`/`let`, a parameter, a module `const`) whose
annotation is an object type literal, an interface or a type alias of either, declared in the
module, and that type declares the member as a property signature whose type is data (a
primitive, a literal, an array or tuple, an object type with no call signature, a `Record`/`Map`/
`Set`, or a union of those, never a function type), the read is `_js_get(o, "get")`. So
`const o: { get: number } = { get: 5 }; o.get` is `5` and `function f(x: Opts) { return x.map }`
with `interface Opts { map: string }` reads the field (`tests/types.rs`, pinned to Node). The
annotation only lifts the compile-time refusal: `_js_get` still raises at run time for a name that
is a method of the value's actual JS type (an array, a string, a `Map`, an instance), so a value
that is not what its annotation says (`any`, an adapter, `JSON.parse`) cannot read a method as
data. An untyped or `any` receiver, a method signature (`get(): number`), a function-typed field
(`get: () => number`) and a read through `as` stay refused. A computed key the compiler cannot see
is checked at run time (below).
J89-5: the annotating type may also be IMPORTED from a compiled module of the same call (`import {
type Pool } from './store.js'`, `import type { ... }`): it declares there what it declares in the
module that declares it. An annotated ARROW parameter (`(o: Omission) => o.count`) declares its
fields as a function parameter does (`tests/g3_store.rs`, `j89_5_*`, pinned to Node).
J89-5a: a method name that only a class NO EXPORT NAMES declares (queries.ts's `CountsView`) is a
method name in its own module only, as an `ImportedClass` adapter's is in a module that imports
it: there its calls dispatch (`_js_dispatch`) and a read of it as a value is refused; in the other
modules of the call a builtin call of that name is the builtin's helper (`m.get(k)` is
`_js_m_get`), which refuses an instance of the class at run time (`ts2py: .get() on _CountsView is
outside the subset`), and a property read of it is `_js_get`, which `_js_object_get` refuses on an
instance. Such a class reaches another module only as a value a function returned, so the other
modules never answer differently from Node: they answer as Node does or refuse. An exported
class's method names still reach every module (`tests/g3_store.rs`,
`j89_5a_a_private_class_keeps_its_method_names_in_its_module`, pinned to Node).

Some operations are checked at run time instead, because only the value can tell: each raises
a `TypeError` naming the subset rather than answering differently from JS. `.toUpperCase()` on a
non-ASCII string; `.replace` with a `$` in the replacement or a function; `.test` / `.exec` on a
`g` regex; a `new RegExp` repeat count that is not an integer in
0..65535; reading an `Object.prototype` name (`constructor`, `toString`, ...) that a plain
object or instance does not own (JS answers with an inherited function); assigning
`__proto__`; `Object.freeze` of anything but a class instance; `throw` of a value that is not an
Error; a method on a receiver of the wrong type (`ts2py: .<method>() on <type> is outside the
subset`); a computed key that names a method of the receiver's JS type (`xs[k]` with `k` equal
to `'push'`, a class method on an instance: `ts2py: reading the method '<k>' as a value is outside
the subset`).

## Known limits (documented, not refused)

- J86 removed the J85 limit that strings were indexed and split by code point: every position is
  now a UTF-16 code unit (Strings above).
- Iterating a `Map` or `Set` sees a snapshot: entries added during the loop are not visited. (J90-2:
  an entry DELETED before the loop reaches it is skipped, and a value set meanwhile is the one
  visited, as JS's iterator does; a key deleted and set again during the loop is visited at its old
  place, where JS visits it at the end.)
- J89-3: the general `.sort(compare)` (`_js_m_sort`) is CPython's `list.sort`, which orders an
  INCONSISTENT comparator (one a NaN makes so) differently from V8 (561 of 30,000 seeded sorts); the
  key sort above uses V8's own algorithm (`_js_v8_sort`) for that case.
- J89-3: a Float64Array longer than 2^26 elements is refused at run time (Node allocates one of
  10^10 lazily; Python would build the list).
- `JSON.stringify` on a cyclic structure raises `RecursionError` (JS raises `TypeError`).
