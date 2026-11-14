# ts2py: the accepted TypeScript subset

`ts2py <input.ts> -o <output.py>` compiles one TypeScript module into one Python module (#314).
The parser is `oxc_parser` (exact-pinned in `Cargo.toml`); this crate only lowers its AST.

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
| regex literal | a compiled `re.Pattern`, hoisted to a module constant `_JS_RE_<n>` |

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
- A regex without flags (the only kind accepted) matches UTF-16 code units: ts2py writes an
  astral literal in the pattern as its two surrogates (in a class, two members), and `re.test`
  splits each astral character of the subject into its surrogates before matching. So `.` and a
  class like `[^x]` match one code unit, and `/^a.b$/.test('a😀b')` is `false` while
  `/^a..b$/.test('a😀b')` is `true`, as in Node.
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
| `const f = (...) => ...` (module level) | `def _f(...):` (`return <expr>` for an expression body) | same as a function |
| `const X = <expr>` (module level) | `X = <expr>` | evaluated once, in source order |
| `interface`, `type` alias, `import type`, `export type` | erased | type-only |

### Statements (inside a function)

| Construct | Lowering | Preserved |
|---|---|---|
| `const x = e` / `let x = e` / `let x;` | `x = e` / `x = _JS_UNDEFINED` | uninitialised `let` reads as `undefined` |
| `x = e` (statement) | `x = e` | |
| `o.k = e` (statement) | `_js_put(o, "k", e)` | sets a key on a plain object |
| `if / else if / else` | `if / elif / else` | condition through ToBoolean (below) |
| `while (c)` | `while c:` | condition through ToBoolean |
| `for (const x of xs)` | `for x in xs:` | iterates a list, a `Map` (as `[key, value]` pairs), a `Set`, a string |
| `for (const [i, x] of xs.entries())` | `for i, x in _js_m_entries(xs):` | pairs are exact, so a plain unpack |
| `for (const [a, b] of xs)` (other iterables) | `for _js_itemN in xs:` + `a = _js_get(_js_itemN, 0)` ... | a short element reads `undefined`, not an unpack error |
| `break` / `continue` (unlabelled) | `break` / `continue` | |
| `return e` / `return` | `return e` / `return _JS_UNDEFINED` | a bare return yields `undefined` |
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
| `a - b`, unary `-a` | `_js_num(_js_num(a) - _js_num(b))`, `-_js_num(a)` | numbers as doubles |
| `a + b` | `_js_num(...)` of `a + b` when both are known numbers, `a + b` when both known strings, else `_js_add(a, b)` | string concatenation via `String()` when either side is a string; numbers as doubles |
| `f(args)` (a module function or a local) | `f(args)` | |
| `new Map(entries?)`, `new Set(items?)` | `_JsMap(...)`, `_JsSet(...)` | insertion order; SameValueZero keys, so `true` and `1` are different keys and `1.0` and `1` the same |
| `/pattern/` (no flags) | `_JS_RE_<n> = re.compile(<translated>, re.ASCII)` | `\d`, `\w`, `\b` are ASCII; `$` is end of input (`\Z`); `.` excludes `\n`, `\r`, U+2028, U+2029; an astral literal is written as its two surrogates (Strings above). The pattern is parsed against a whitelist grammar, so every accepted pattern is valid JS and compiles under `re`; anything else is refused at compile time with its reason, never an `re.error` at import (Refused below) |
| `(params) => expr` **as a callback argument** of the methods below | `lambda params, *_: expr` | JS passes `(item, index, array)`; extra arguments are absorbed |
| `as T`, `x!`, `satisfies T`, `<T>x`, `f<T>(...)`, generics, `readonly`, parameter and return annotations, `p?:` | erased (`p?:` becomes `p=_JS_UNDEFINED`) | a missing optional argument is `undefined` |

### Builtins

| Call | Lowering | Preserved |
|---|---|---|
| `Array.isArray(x)` | `_js_is_array(x)` | a `list` only |
| `Number.isInteger(x)` | `_js_number_is_integer(x)` | `3.0` is an integer; `True` is not (not a number); an int past the double range is not (it is Infinity in JS) |
| `JSON.stringify(x)` (one argument) | `_js_json_stringify(x)` | byte for byte: compact, non-ASCII unescaped, lone surrogates and control characters `\u00xx`, integral floats as `3`, `1e21` as `1e+21`, an int beyond 2^53 as the double it rounds to, non-finite as `null`, `undefined` members skipped (`null` in arrays), object keys in JS own-property order (array-index keys ascending first, then insertion order) |
| `m.has(k)`, `m.get(k)`, `m.set(k, v)` | `_js_m_has` / `_js_m_get` / `_js_m_set` | `Map`; `get` of a missing key is `undefined`; `set` keeps the original position |
| `s.has(x)`, `s.add(x)` | `_js_m_has` / `_js_m_add` | `Set` |
| `a.every(cb)`, `a.some(cb)` | `_js_m_every` / `_js_m_some` | callback result through ToBoolean |
| `a.find(cb)` | `_js_m_find` | no match is `undefined`, never `None` |
| `a.map(cb)` | `_js_m_map` | |
| `a.push(...xs)` | `_js_m_push` | returns the new length |
| `a.slice(start?, end?)` | `_js_m_slice` | negative and out-of-range bounds clamp as in JS |
| `a.join(sep?)` | `_js_m_join` | default `,`; `null`/`undefined` elements join as empty |
| `a.sort(cmp?)` | `_js_m_sort` | in place, returns the array, **stable**; with a comparator, the comparator's sign orders (NaN is 0); without one, by `String()` in UTF-16 code-unit order; `undefined` last |
| `a.entries()` | `_js_m_entries` | `[index, item]` pairs (a `Map` gives `[key, value]`) |
| `s.includes(x)`, `a.includes(x)` | `_js_m_includes` | substring; array membership by SameValueZero |
| `s.startsWith(p)` | `_js_m_startsWith` | |
| `s.split(sep)` (string separator) | `_js_m_split` | `""` splits into characters |
| `re.test(s)` | `_js_m_test` | `re.search` on `String(s)` with each astral character split into its surrogates, so the pattern sees UTF-16 code units |

A method above called on a receiver of the wrong runtime type raises
`TypeError("ts2py: .<method>() on <type> is outside the subset")` instead of guessing.

## Names

- A module-level **exported** name is `snake_case(name)`: `touchesRefusal` -> `touches_refusal`,
  `plan` -> `plan`. An acronym run is one word (`parseJSONValue` -> `parse_json_value`); an
  all-caps name (`MAX_WIDTH`) is kept.
- A module-level **non-exported** name is `_` + `snake_case(name)`: `readNodes` -> `_read_nodes`.
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

## Refused (not exhaustive: anything unlisted above is refused)

`class`, generator functions and `yield`, `async` functions and `await`, `this`, labelled
statements / `break label` / `continue label`, any builtin or method not in the tables above
(`Object.keys`, `Math.max`, `s.toUpperCase()`, ...), `var`, destructuring declarations and
parameters, default parameters, rest parameters, nested function declarations, function
expressions, arrow functions anywhere but as an inline callback argument (and block-bodied
arrows there), a callback that is not an inline arrow, optional chaining `?.`, loose equality
`==` other than against `null`/`undefined`, the operators `*`, `/`, `%`, `**`, bitwise, `in`,
`instanceof`, `void`, `delete`, unary `+`, `++`/`--`, compound assignment, assignment inside an
expression, the comma operator, `throw`, `try`, `switch`, `do-while`, C-style `for`, `for-in`,
`for await`, object spread, computed or integer-like object keys, getters/setters and object
methods, tagged templates, bigint, non-finite literals, regex flags and regex syntax whose
meaning differs between the engines (`\s`, `\B`, named groups, lookbehind, backreferences,
Annex B leniencies such as a bare `{`, `}` or `]`, a quantified lookahead, a class escape as a
range endpoint), regexes JS itself rejects (a range out of order in UTF-16 code units such as
`[😀-😂]`, `{3,2}`, a quantifier with nothing to repeat, unbalanced parentheses), and regexes
`re` cannot compile (a repeat count above 65535, groups nested deeper than 64), `enum`,
`namespace`, value imports and exports lists, a block binding that shadows an enclosing one, a
local that shadows a module-level name, and any global identifier other than `undefined`.

## Known limits (documented, not refused)

- Strings are indexed and split into characters by code point, not UTF-16 code unit (only
  `.length` counts code units). For the same reason `.includes`, `.startsWith` and `.split` do not
  find a lone surrogate that is half of a pair in the receiver (JS finds it).
- Iterating a `Map` or `Set` sees a snapshot: entries added during the loop are not visited.
- `JSON.stringify` on a cyclic structure raises `RecursionError` (JS raises `TypeError`).
