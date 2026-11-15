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
  literal, a template, a concatenation of strings). On anything else they are whatever the
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
| `[a, b] = e` (J86) | `a, b = _js_destructure(e, 2)` | as the declaration |
| `o.k = e`, `o[k] = e` (statement) | `_js_put(o, "k", e)` | sets a key on a plain object (`__proto__` is refused at run time: JS would set the prototype); on a class instance (J86) the attribute, a TypeError on a frozen one |
| `this.x = e` (J86) | `self.x = e` | a declared member; a TypeError once `Object.freeze(this)` ran |
| `if / else if / else` | `if / elif / else` | condition through ToBoolean (below) |
| `while (c)` | `while c:` | condition through ToBoolean |
| `for (;;)` (J86) | `while True:` | a C-style loop with any clause stays refused |
| `switch (x) { case a: ... }` (J86) | `x` once into `_js_switchN`, then `if _js_strict_eq(...) / elif / else` | `===` per case, in order; empty cases group (`case a: case b:`); each case group must end in `return` / `throw` or a trailing `break` (dropped); fallthrough, a `break` elsewhere in a case, and a `default` that is not last are refused |
| `throw e` (J86) | `raise e` for `new <class or Error>(...)`, else `raise _js_throw(e)` | throwing a value that is not an Error raises a TypeError instead |
| `for (const x of xs)` | `for x in xs:` | iterates a list, a `Map` (as `[key, value]` pairs), a `Set`, a string |
| `for (const [i, x] of xs.entries())` | `for i, x in _js_m_entries(xs):` | pairs are exact, so a plain unpack |
| `for (const [a, b] of xs)` (other iterables) | `for _js_itemN in xs:` + `a = _js_get(_js_itemN, 0)` ... | a short element reads `undefined`, not an unpack error |
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
| `this` (J86, in a class) | `self` | refused outside a class body |
| `this.x`, `this.m(...)` (J86) | `self.x`, `self.m(...)` | refused unless the class (or Error) declares the member |
| `new C(...)` (J86) | `C(...)` for a compiled class; `_JsError(...)` / `_JsTypeError(...)` for `Error` / `TypeError`; an adapter class (`new TextDecoder(...)`, `new Date()`) from the adapter module | extra arguments ignored, as JS ignores them |
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
| `new Map(entries?)`, `new Set(items?)` | `_JsMap(...)`, `_JsSet(...)` | insertion order; SameValueZero keys, so `true` and `1` are different keys and `1.0` and `1` the same |
| `/pattern/` (no flags, or `g`, J86) | `_JS_RE_<n> = re.compile(<translated>, re.ASCII)`; with `g`, wrapped in `_JsGlobalRegExp` (only `.replace` accepts it: `.test` / `.exec` on a `g` regex read `lastIndex`, which is not modelled, and raise) | `\d`, `\w`, `\b` are ASCII; `$` is end of input (`\Z`); `.` excludes `\n`, `\r`, U+2028, U+2029; an astral literal is written as its two surrogates (Strings above). The pattern is parsed against a whitelist grammar, so every accepted pattern is valid JS and compiles under `re`; anything else is refused at compile time with its reason, never an `re.error` at import (Refused below). J86 adds `\xHH` and `\uHHHH` (one code unit each, in and out of a class) and a lookbehind `(?<=...)` / `(?<!...)` holding only single-unit atoms, so its width is fixed (as `re` requires) and reading it backwards (JS) or forwards (`re`) is the same |
| `(params) => expr` **as a callback argument** of the methods below | `lambda params, *_: expr` | JS passes `(item, index, array)`; extra arguments are absorbed. J86: a parameter may be an array pattern of names, `([k]) => e` is `lambda _js_argN, *_: (lambda k: e)(*_js_destructure(_js_argN, 1))` |
| `as T`, `x!`, `satisfies T`, `<T>x`, `f<T>(...)`, generics, `readonly`, parameter and return annotations, `p?:` | erased (`p?:` becomes `p=_JS_UNDEFINED`) | a missing optional argument is `undefined` |

### Builtins

| Call | Lowering | Preserved |
|---|---|---|
| `Array.isArray(x)` | `_js_is_array(x)` | a `list` only |
| `Number.isNaN(x)` (J86) | `_js_number_is_nan(x)` | a number that is NaN; no coercion |
| `Number(x)`, `String(x)`, `BigInt(x)`, `parseInt(s, radix?)` (J86) | `_js_number`, `_js_str`, `_js_bigint`, `_js_parse_int` | ToNumeric / `String()` / StringToBigInt / parseInt's prefix grammar (JS whitespace, sign, `0x`); a parseInt past 2^53 in a radix V8 rounds approximately is outside the subset |
| `Math.floor`, `Math.abs`, `Math.max(...)`, `Math.min(...)` (J86) | `_js_floor`, `_js_abs`, `_js_max`, `_js_min` | NaN, the infinities and `-0` kept; any NaN argument makes max/min NaN; +0 beats -0 for max; no argument is -Infinity / Infinity |
| `Object.keys(o)`, `Object.entries(o)` (J86) | `_js_object_keys`, `_js_object_entries` | own enumerable keys in JS order (array indices ascending first); an instance's fields in definition order |
| `Object.freeze(this)` (J86) | `_js_freeze(self)` | later writes raise JS's TypeError; freezing a plain object or array is outside the subset |
| `Object.getPrototypeOf(o)` (J86) | `_js_get_prototype_of(o)` | `Object.prototype` for a plain object, the class for an instance, a distinct stand-in for anything else |
| `String.fromCodePoint(...cps)` (J86) | `_js_from_code_point` | each an integer in 0..0x10FFFF, else RangeError; two halves passed separately form one character |
| `s.codePointAt(i)` (J86) | `_js_m_codePointAt` | UTF-16 position; a lead surrogate followed by a trail gives the astral code point, otherwise the unit; out of range is `undefined` |
| `s.indexOf(x, from?)`, `s.lastIndexOf(x, from?)` (J86) | `_js_m_indexOf`, `_js_m_lastIndexOf` | UTF-16 positions, `from` clamped as JS clamps it (a NaN `from` of lastIndexOf is +Infinity); strings only |
| `s.padStart(n, f?)`, `s.padEnd(n, f?)`, `s.repeat(n)` (J86) | `_js_m_padStart`, `_js_m_padEnd`, `_js_m_repeat` | length in UTF-16 units; the filler cut to fit; a negative or infinite count is RangeError |
| `s.toLowerCase()`, `s.toUpperCase()` (J86) | `_js_m_toLowerCase`, `_js_m_toUpperCase` | ASCII exactly; a non-ASCII string raises (CPython and V8 follow different Unicode versions) |
| `s.replace(p, r)` (J86) | `_js_m_replace` | a string `p` replaces its first occurrence, a regex its first match, a `g` regex every match (empty matches as JS steps over them); `r` must be a string without `$` (JS's substitution patterns are outside the subset) |
| `re.exec(s)` (J86) | `_js_m_exec` | `null` on no match; else an array of the match and groups (`undefined` for a group that did not take part) with `index` and `input` |
| `x.toString(radix?)` (J86) | `_js_m_toString` | an instance's own `toString`; `Error.prototype.toString` (`name: message`); a number or BigInt in radix 2..36 (a fraction only in radix 10) |
| `a.reverse()`, `a.pop()`, `a.filter(cb)` (J86) | `_js_m_reverse`, `_js_m_pop`, `_js_m_filter` | in place / `undefined` when empty / callback through ToBoolean |
| `x.m(...)` for a method a compiled class declares (J86) | `_js_invoke(x, "m", ...)`; when a builtin above has the same name, `_js_dispatch(x, "m", _js_m_m, ...)` | the receiver decides, as JS's prototype lookup does: an instance runs its own method, anything else the builtin |
| `Number.isInteger(x)` | `_js_number_is_integer(x)` | `3.0` is an integer; `True` is not (not a number); an int past the double range is not (it is Infinity in JS) |
| `JSON.stringify(x)` (one argument) | `_js_json_stringify(x)` | byte for byte: compact, non-ASCII unescaped, lone surrogates and control characters `\u00xx`, integral floats as `3`, `1e21` as `1e+21`, an int beyond 2^53 as the double it rounds to, non-finite as `null`, `undefined` members skipped (`null` in arrays), object keys in JS own-property order (array-index keys ascending first, then insertion order) |
| `m.has(k)`, `m.get(k)`, `m.set(k, v)` | `_js_m_has` / `_js_m_get` / `_js_m_set` | `Map`; `get` of a missing key is `undefined`; `set` keeps the original position |
| `s.has(x)`, `s.add(x)` | `_js_m_has` / `_js_m_add` | `Set` |
| `a.every(cb)`, `a.some(cb)` | `_js_m_every` / `_js_m_some` | callback result through ToBoolean |
| `a.find(cb)` | `_js_m_find` | no match is `undefined`, never `None` |
| `a.map(cb)` | `_js_m_map` | |
| `a.push(...xs)` | `_js_m_push` | returns the new length; J86: a spread argument (`a.push(...b)`) iterates `b` |
| `a.slice(start?, end?)` | `_js_m_slice` | negative and out-of-range bounds clamp as in JS; J86: on a string, by UTF-16 unit |
| `a.join(sep?)` | `_js_m_join` | default `,`; `null`/`undefined` elements join as empty; J86: two surrogate halves that meet form one character |
| `a.sort(cmp?)` | `_js_m_sort` | in place, returns the array, **stable**; with a comparator, the comparator's sign orders (NaN is 0); without one, by `String()` in UTF-16 code-unit order; `undefined` last |
| `a.entries()` | `_js_m_entries` | `[index, item]` pairs (a `Map` gives `[key, value]`) |
| `s.includes(x)`, `a.includes(x)` | `_js_m_includes` | substring (J86: by UTF-16 unit); array membership by SameValueZero |
| `s.startsWith(p)` | `_js_m_startsWith` | J86: by UTF-16 unit |
| `s.split(sep)` (string separator) | `_js_m_split` | J86: by UTF-16 unit, so `""` splits into code units |
| `re.test(s)` | `_js_m_test` | `re.search` on `String(s)` with each astral character split into its surrogates, so the pattern sees UTF-16 code units |

A method above called on a receiver of the wrong runtime type raises
`TypeError("ts2py: .<method>() on <type> is outside the subset")` instead of guessing.

## Classes (J86)

| Construct | Lowering | Preserved |
|---|---|---|
| `class C { ... }` | `class C(_JsObject):` (exported: as written; else `_C`), with `_js_name`, `_js_own` (fields, methods, getters) and `_js_own_methods` | a reflective read (`_js_get(x, "k")`, `k in x`, `Object.keys(x)`) sees exactly the members JS would, nothing Python adds |
| field `x = e;` / `x: T;` | `self.x = e` / `self.x = _JS_UNDEFINED` at the start of `__init__`, in declaration order | ES2022 class fields (`target: ES2022`): own properties, initialised before the constructor body runs |
| `constructor(p) { ... }` | `def __init__(self, p, *_):` (fields first, then the body) | extra `new` arguments ignored |
| method `m(p) { ... }` | `def m(self, p):` | a body that can run off its end returns `undefined` |
| getter `get g() { ... }` | `@property def g(self):` | |
| `class E extends Error {}` | `class E(_JsError):` | `e.message` is the argument (as `String()`), `e.name` is `"Error"` (inherited, as JS gives every subclass that does not set its own), `String(e)` is `name: message`; `e.name = "X"` makes an own `name`; a `_JsError` is a Python exception, `_JsTypeError` also a Python `TypeError` |
| `Object.freeze(this)` | `_js_freeze(self)` | a later write raises JS's TypeError (`Cannot assign to read only property 'v' of object '#<C>'`) |

Refused in a class: `static` members, computed or `#private` keys, setters, accessor properties,
decorators, `abstract`, `extends` anything but `Error`, a constructor in a class that extends
`Error` (it would need `super`), a member whose name is a Python keyword or starts with `_` (the
runtime's own attributes do), and on an Error subclass a member named `args`, `with_traceback` or
`add_note` (Python's exceptions carry those).

## Modules and the adapter seam (J86)

- Several modules compiled in one run (`--out-dir`) import each other: `import { a } from
  './m.js'` in a module whose path is `runtime-ts/src/memory/x.ts` resolves to
  `runtime-ts/src/memory/m.ts`; if that is one of the inputs, the import is
  `from .m import <a's Python name>` (classes keep their name). The modules form a package, so
  `--runtime-module` (and the adapter module) must be importable from it.
- Any other import resolves only through the table in `src/adapters.rs`: a row names the
  TypeScript module (or a Node global such as `TextDecoder`), the name, the Python name in
  `src/adapters.py` (`--emit-adapters <file>` writes it, importing the runtime from
  `--runtime-module`), and the reason the hand-written Python is the same function. Every row and
  its measurement is in `RULES.md`, Adapters.
- An import with no compiled module and no row is a compile error naming it:
  `<path>:<line>:<col>: unsupported import of pyRepr from ./pyfs.js: no compiled module and no declared adapter: pyRepr`.
- Renamed imports and exports, default and namespace imports, and side-effect imports are refused.

## Names

- A module-level **exported** name is `snake_case(name)`: `touchesRefusal` -> `touches_refusal`,
  `plan` -> `plan`. An acronym run is one word (`parseJSONValue` -> `parse_json_value`); an
  all-caps name (`MAX_WIDTH`) is kept.
- A module-level **non-exported** name is `_` + `snake_case(name)`: `readNodes` -> `_read_nodes`.
- J86: a class keeps its name (`PyScalar`), with `_` when it is not exported (`_Emitter`); its
  members keep their JS spelling (`self.bestWidth`, `def writeIndent(self)`), because a
  reflective read looks them up by that spelling.
- A local or parameter is `snake_case(name)`: `nodeId` -> `node_id`.
- A Python keyword gets a trailing `_` (`lambda` -> `lambda_`); so does a module-level name
  that would shadow a builtin the runtime support calls (`len` -> `len_`).
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

Generator functions and `yield`, `async` functions and `await`, `this` outside a class body,
labelled statements / `break label` / `continue label`, any builtin or method not in the tables
above (`Object.assign`, `Math.round`, `s.trim()`, `s.charCodeAt()`, `String.fromCharCode()`,
...), `var`, `let` bound to an arrow function, nested `function` declarations, function
expressions, a `const` arrow inside a loop, arrow functions anywhere else but as an inline
callback argument (and block-bodied arrows there), a callback that is not an inline arrow,
destructuring with defaults, rest elements, nesting or computed keys, rest parameters, optional
chaining `?.`, loose equality `==` other than against `null`/`undefined`, the operators `**` and
bitwise, `void`, `delete`, unary `+`, `++`/`--`, compound assignment other than `+=` `-=` `*=`
on a local or `this.x`, assignment inside an expression (other than a chain of `=` between
locals), assignment to a module-level name, the comma operator, `try` / `catch` / `finally`,
`switch` fallthrough between non-empty cases, a `break` that does not end its case, a `default`
that is not the last case, `do-while`, C-style `for` with any clause, `for-in`, `for await`,
computed or integer-like object keys, getters/setters and methods in object literals, tagged
templates, non-finite number literals, regex flags other than `g`, regex syntax whose meaning
differs between the engines (`\s`, `\B`, named groups, backreferences, a lookbehind holding
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
bound method or `undefined`. ts2py has no type checker, so on any receiver but `this` the NAME
decides: a method of String, Array, Map, Set, RegExp, Number, Function or `Object.prototype`
(`JS_METHOD_NAMES` in `src/lower.rs`, the whole prototype, not only the methods the call table
lowers), or a method any compiled or adapter class declares. So a data property that shares such
a name (`input.big`, `o.link`) is refused too, because the receiver's type is not known to the
compiler; on `this` the class's own method list decides exactly. A computed key the compiler
cannot see is checked at run time (below).

Some operations are checked at run time instead, because only the value can tell: each raises
a `TypeError` naming the subset rather than answering differently from JS. `.toLowerCase()` /
`.toUpperCase()` on a non-ASCII string; `.replace` with a `$` in the replacement or a function;
`.test` / `.exec` on a `g` regex; a `new RegExp` repeat count that is not an integer in
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
- Iterating a `Map` or `Set` sees a snapshot: entries added during the loop are not visited.
- `JSON.stringify` on a cyclic structure raises `RecursionError` (JS raises `TypeError`).
