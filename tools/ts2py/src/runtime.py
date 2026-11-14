# ts2py runtime support: the JavaScript semantics the generated code leans on.
# Pure standard library. Every name starts with `_js_`, `_Js` or `_JS_`, and ts2py refuses a
# TypeScript identifier with one of those prefixes, so nothing here can be shadowed by source.
import functools as _js_functools
import math as _js_math
import re as _js_re


class _JsUndefined:
    """`undefined`: one sentinel, distinct from `None` (which is `null`)."""

    __slots__ = ()

    def __repr__(self):
        return "undefined"

    def __bool__(self):
        return False


_JS_UNDEFINED = _JsUndefined()


def _js_is_nullish(value):
    """`value == null`: `null` and `undefined` alike, nothing else."""
    return value is None or value is _JS_UNDEFINED


def _js_typeof(value):
    """`typeof value`. A Python bool is `boolean`, never `number`."""
    if value is _JS_UNDEFINED:
        return "undefined"
    if value is None:
        return "object"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if callable(value):
        return "function"
    return "object"


def _js_truthy(value):
    """ToBoolean: `0`, `NaN`, `""`, `null`, `undefined`, `false` are falsy; `[]` and `{}` truthy."""
    if value is None or value is _JS_UNDEFINED:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == value and value != 0
    if isinstance(value, str):
        return value != ""
    return True


def _js_or(left, right):
    """`left || right`, `right` a thunk evaluated only when `left` is falsy."""
    return left if _js_truthy(left) else right()


def _js_and(left, right):
    """`left && right`, `right` a thunk evaluated only when `left` is truthy."""
    return right() if _js_truthy(left) else left


def _js_coalesce(left, right):
    """`left ?? right`, `right` a thunk evaluated only when `left` is null or undefined."""
    return right() if _js_is_nullish(left) else left


def _js_or_value(left, right):
    """`left || right` where `right` has no side effect, so it may be evaluated eagerly."""
    return left if _js_truthy(left) else right


def _js_and_value(left, right):
    """`left && right` where `right` has no side effect."""
    return right if _js_truthy(left) else left


def _js_coalesce_value(left, right):
    """`left ?? right` where `right` has no side effect."""
    return right if _js_is_nullish(left) else left


def _js_num(value):
    """A number as a JS double holds it; anything that is not a number is returned unchanged.

    An int beyond +-2^53 rounds to the nearest double (ties to even), as `Number()` would, and one
    past the double range is +-Infinity. Within +-2^53 an int is already exact and stays an int.
    """
    if type(value) is int and not -(2**53) <= value <= 2**53:
        try:
            return float(value)
        except OverflowError:
            return _js_math.inf if value > 0 else -_js_math.inf
    return value


def _js_strict_eq(left, right):
    """`left === right`: no coercion, so `true !== 1`; numbers by value, objects by identity."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _js_num(left) == _js_num(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return left is right


def _js_is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _js_number_is_integer(value):
    """`Number.isInteger`: `3.0` is an integer, `True` is not a number at all.

    The value is first read as the double JS holds (`_js_num`), so an int past the double range
    (a 309-digit literal, which `JSON.parse` reads as Infinity) is not an integer, as in JS.
    """
    if not _js_is_number(value):
        return False
    value = _js_num(value)
    if isinstance(value, int):
        return True
    return _js_math.isfinite(value) and value.is_integer()


def _js_is_array(value):
    """`Array.isArray`: a Python list, and only a list."""
    return isinstance(value, list)


def _js_num_str(value):
    """`String(number)`: Number::toString, so `3.0` is `3`, `1e21` is `1e+21`, `1e-7` is `1e-7`."""
    value = _js_num(value)
    if isinstance(value, int):
        return str(value)
    if value != value:
        return "NaN"
    if value == _js_math.inf:
        return "Infinity"
    if value == -_js_math.inf:
        return "-Infinity"
    if value == 0:
        return "0"
    if value < 0:
        return "-" + _js_num_str(-value)
    text = repr(value)
    mantissa, _, exponent = text.partition("e")
    whole, _, fraction = mantissa.partition(".")
    raw = whole + fraction
    stripped = raw.lstrip("0")
    point = len(whole) + (int(exponent) if exponent else 0) - (len(raw) - len(stripped))
    digits = stripped.rstrip("0")
    k = len(digits)
    if k <= point <= 21:
        return digits + "0" * (point - k)
    if 0 < point <= 21:
        return digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return "0." + "0" * (-point) + digits
    power = point - 1
    sign = "+" if power >= 0 else "-"
    head = digits if k == 1 else digits[0] + "." + digits[1:]
    return head + "e" + sign + str(abs(power))


def _js_str(value):
    """`String(value)`, as a template literal stringifies a substitution."""
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if value is _JS_UNDEFINED:
        return "undefined"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _js_num_str(value)
    if isinstance(value, list):
        return ",".join("" if _js_is_nullish(item) else _js_str(item) for item in value)
    if isinstance(value, _JsMap):
        return "[object Map]"
    if isinstance(value, _JsSet):
        return "[object Set]"
    if isinstance(value, dict):
        return "[object Object]"
    raise TypeError(f"ts2py: String() of {type(value).__name__} is outside the subset")


def _js_add(left, right):
    """`left + right`: string concatenation when either side is a string, else numeric addition."""
    if isinstance(left, str) or isinstance(right, str):
        return _js_str(left) + _js_str(right)
    if _js_is_number(left) and _js_is_number(right):
        return _js_num(_js_num(left) + _js_num(right))
    raise TypeError("ts2py: + on non-number, non-string operands is outside the subset")


# StrWhiteSpaceChar: WhiteSpace and LineTerminator, what ToNumber trims off a string.
_JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_JS_DECIMAL = _js_re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z", _js_re.ASCII
)
_JS_RADIX = _js_re.compile(r"0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\Z", _js_re.ASCII)


def _js_to_number(value):
    """ToNumber, for a value already through ToPrimitive (`_js_to_primitive`)."""
    if _js_is_number(value):
        return _js_num(value)
    if value is _JS_UNDEFINED:
        return _js_math.nan
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    text = value.strip(_JS_WHITESPACE)
    if text == "":
        return 0
    if _JS_RADIX.match(text):
        return _js_num(int(text[2:], {"x": 16, "o": 8, "b": 2}[text[1].lower()]))
    if _JS_DECIMAL.match(text):
        if text.lstrip("+-") == "Infinity":
            return -_js_math.inf if text[0] == "-" else _js_math.inf
        return float(text)
    return _js_math.nan


def _js_to_primitive(value):
    """ToPrimitive (hint number) in the subset: an array, object, Map or Set is its `String()`."""
    if value is None or value is _JS_UNDEFINED or isinstance(value, (bool, int, float, str)):
        return value
    return _js_str(value)


def _js_less(left, right):
    """IsLessThan(left, right): True, False, or None for JS `undefined` (a NaN operand).

    Two strings compare by UTF-16 code unit, as JS does; Python's `<` compares code points, which
    orders an astral character (one surrogate pair) after U+E000..U+FFFF instead of before it.
    Anything else is compared as numbers after ToNumber, so `"10" < 9` is false and `null < 1` true.
    """
    left, right = _js_to_primitive(left), _js_to_primitive(right)
    if isinstance(left, str) and isinstance(right, str):
        if left.isascii() and right.isascii():
            return left < right
        return _js_utf16(left) < _js_utf16(right)
    left, right = _js_to_number(left), _js_to_number(right)
    if left != left or right != right:
        return None
    return left < right


def _js_lt(left, right):
    """`left < right`."""
    return _js_less(left, right) is True


def _js_gt(left, right):
    """`left > right`."""
    return _js_less(right, left) is True


def _js_le(left, right):
    """`left <= right`: false when `right < left` or either side is NaN."""
    return _js_less(right, left) is False


def _js_ge(left, right):
    """`left >= right`: false when `left < right` or either side is NaN."""
    return _js_less(left, right) is False


def _js_index_key(key):
    """An array index from a property key, or None when the key is not one."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return key
    if isinstance(key, float) and key.is_integer():
        return int(key)
    if isinstance(key, str) and key.isascii() and key.isdigit() and (key == "0" or key[0] != "0"):
        return int(key)
    return None


def _js_get(obj, key):
    """`obj[key]` / `obj.key`: a missing key reads as `undefined`, never raises."""
    if isinstance(obj, dict):
        if not isinstance(key, str):
            key = _js_str(key)
        return obj.get(key, _JS_UNDEFINED)
    if isinstance(obj, (list, str)):
        if key == "length" and isinstance(key, str):
            return _js_len(obj)
        index = _js_index_key(key)
        if index is not None and 0 <= index < len(obj):
            return obj[index]
        return _JS_UNDEFINED
    if obj is None or obj is _JS_UNDEFINED:
        raise TypeError(f"Cannot read properties of {_js_str(obj)} (reading '{_js_str(key)}')")
    if isinstance(obj, (_JsMap, _JsSet)) and key == "size":
        return len(obj)
    return _JS_UNDEFINED


def _js_put(obj, key, value):
    """`obj.key = value` on a plain object."""
    if not isinstance(obj, dict):
        raise TypeError("ts2py: property assignment on a non-object is outside the subset")
    obj[key if isinstance(key, str) else _js_str(key)] = value


def _js_len(value):
    """`value.length`: UTF-16 code units for a string, element count for an array."""
    if isinstance(value, str):
        return len(value.encode("utf-16-le", "surrogatepass")) // 2
    if isinstance(value, list):
        return len(value)
    return _js_get(value, "length")


def _js_size(value):
    """`value.size` of a Map or Set."""
    if isinstance(value, (_JsMap, _JsSet)):
        return len(value)
    return _js_get(value, "size")


def _js_key(key):
    """A dict key that keeps JS SameValueZero apart where Python would merge it.

    `true` and `1` are different Map keys in JS and equal ones in Python, so a bool is tagged; NaN
    equals NaN; an array or object is keyed by identity. A tuple never appears as a JS value, so
    the tags cannot collide with a real key.
    """
    if isinstance(key, bool):
        return (_JsMap, key)
    if isinstance(key, float) and key != key:
        return (_JsMap, "NaN")
    if isinstance(key, int):
        return _js_num(key)
    if isinstance(key, (list, dict)):
        return (_JsSet, id(key))
    return key


class _JsMap:
    """`Map`: insertion-ordered, keyed by SameValueZero, missing key reads as `undefined`."""

    __slots__ = ("_entries",)

    def __init__(self, entries=None):
        self._entries = {}
        if entries is not None:
            for entry in entries:
                self.set(_js_get(entry, 0), _js_get(entry, 1))

    def has(self, key):
        return _js_key(key) in self._entries

    def get(self, key):
        entry = self._entries.get(_js_key(key))
        return _JS_UNDEFINED if entry is None else entry[1]

    def set(self, key, value):
        tag = _js_key(key)
        existing = self._entries.get(tag)
        self._entries[tag] = (key if existing is None else existing[0], value)
        return self

    def __len__(self):
        return len(self._entries)

    def __iter__(self):
        return iter([[key, value] for key, value in list(self._entries.values())])


class _JsSet:
    """`Set`: insertion-ordered, SameValueZero membership."""

    __slots__ = ("_items",)

    def __init__(self, items=None):
        self._items = {}
        if items is not None:
            for item in items:
                self.add(item)

    def has(self, item):
        return _js_key(item) in self._items

    def add(self, item):
        self._items.setdefault(_js_key(item), item)
        return self

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(list(self._items.values()))


def _js_outside(method, receiver):
    return TypeError(f"ts2py: .{method}() on {type(receiver).__name__} is outside the subset")


def _js_m_has(receiver, key):
    if isinstance(receiver, (_JsMap, _JsSet)):
        return receiver.has(key)
    raise _js_outside("has", receiver)


def _js_m_get(receiver, key):
    if isinstance(receiver, _JsMap):
        return receiver.get(key)
    raise _js_outside("get", receiver)


def _js_m_set(receiver, key, value):
    if isinstance(receiver, _JsMap):
        return receiver.set(key, value)
    raise _js_outside("set", receiver)


def _js_m_add(receiver, item):
    if isinstance(receiver, _JsSet):
        return receiver.add(item)
    raise _js_outside("add", receiver)


def _js_same_value_zero(left, right):
    if isinstance(left, float) and isinstance(right, float) and left != left and right != right:
        return True
    return _js_strict_eq(left, right)


def _js_m_includes(receiver, item):
    if isinstance(receiver, str):
        return _js_str(item) in receiver
    if isinstance(receiver, list):
        return any(_js_same_value_zero(element, item) for element in receiver)
    raise _js_outside("includes", receiver)


def _js_m_startsWith(receiver, prefix):
    if isinstance(receiver, str):
        return receiver.startswith(_js_str(prefix))
    raise _js_outside("startsWith", receiver)


def _js_m_split(receiver, separator):
    if isinstance(receiver, str) and isinstance(separator, str):
        if separator == "":
            return [unit for unit in receiver]
        return receiver.split(separator)
    raise _js_outside("split", receiver)


def _js_code_units(text):
    """`text` with every astral character split into its two surrogates: the string as a JS regex
    without the `u` flag sees it, one UTF-16 code unit per Python character."""
    if text.isascii() or max(text) < "\U00010000":
        return text
    out = []
    for char in text:
        code = ord(char)
        if code < 0x10000:
            out.append(char)
        else:
            code -= 0x10000
            out.append(chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF)))
    return "".join(out)


def _js_m_test(receiver, text):
    """`re.test(s)`: the pattern (astral literals already split by ts2py) runs over code units, so
    `.` and a class match one UTF-16 code unit, never a whole astral character."""
    if isinstance(receiver, _js_re.Pattern):
        return receiver.search(_js_code_units(_js_str(text))) is not None
    raise _js_outside("test", receiver)


def _js_array(method, receiver):
    if not isinstance(receiver, list):
        raise _js_outside(method, receiver)
    return receiver


def _js_m_every(receiver, callback):
    items = _js_array("every", receiver)
    return all(_js_truthy(callback(item, index, items)) for index, item in enumerate(items))


def _js_m_some(receiver, callback):
    items = _js_array("some", receiver)
    return any(_js_truthy(callback(item, index, items)) for index, item in enumerate(items))


def _js_m_find(receiver, callback):
    """`.find`: the first match, or `undefined` — never `None`, which is `null`."""
    items = _js_array("find", receiver)
    for index, item in enumerate(items):
        if _js_truthy(callback(item, index, items)):
            return item
    return _JS_UNDEFINED


def _js_m_map(receiver, callback):
    items = _js_array("map", receiver)
    return [callback(item, index, items) for index, item in enumerate(items)]


def _js_m_push(receiver, *items):
    _js_array("push", receiver).extend(items)
    return len(receiver)


def _js_slice_bound(value, length, default):
    if value is _JS_UNDEFINED:
        return default
    if value != value:
        return 0
    if value in (_js_math.inf, -_js_math.inf):
        return length if value > 0 else 0
    value = int(value)
    if value < 0:
        return max(length + value, 0)
    return min(value, length)


def _js_m_slice(receiver, start=_JS_UNDEFINED, end=_JS_UNDEFINED):
    items = _js_array("slice", receiver)
    length = len(items)
    return items[_js_slice_bound(start, length, 0) : _js_slice_bound(end, length, length)]


def _js_m_join(receiver, separator=_JS_UNDEFINED):
    items = _js_array("join", receiver)
    glue = "," if separator is _JS_UNDEFINED else _js_str(separator)
    return glue.join("" if _js_is_nullish(item) else _js_str(item) for item in items)


def _js_m_entries(receiver):
    if isinstance(receiver, list):
        return [[index, item] for index, item in enumerate(receiver)]
    if isinstance(receiver, _JsMap):
        return list(receiver)
    raise _js_outside("entries", receiver)


def _js_utf16(text):
    return text.encode("utf-16-be", "surrogatepass")


def _js_m_sort(receiver, compare=_JS_UNDEFINED):
    """`.sort`: stable, in place, returns the array; `undefined` last; NaN from `compare` is 0."""
    items = _js_array("sort", receiver)
    present = [item for item in items if item is not _JS_UNDEFINED]
    missing = len(items) - len(present)
    if compare is _JS_UNDEFINED:
        present.sort(key=lambda item: _js_utf16(_js_str(item)))
    else:

        def order(left, right):
            result = compare(left, right)
            if isinstance(result, bool):
                result = int(result)
            if not _js_is_number(result) or result != result:
                return 0
            return result

        present.sort(key=_js_functools.cmp_to_key(order))
    items[:] = present + [_JS_UNDEFINED] * missing
    return items


def _js_json_quote(text):
    out = ['"']
    for char in text:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\b":
            out.append("\\b")
        elif char == "\f":
            out.append("\\f")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _js_own_keys(obj):
    """OrdinaryOwnPropertyKeys: array-index keys ascending, then the rest in insertion order."""
    keys = [key if isinstance(key, str) else _js_str(key) for key in obj]
    indices = sorted(
        (key for key in keys if _js_index_key(key) is not None and int(key) < 2**32 - 1),
        key=int,
    )
    chosen = set(indices)
    return indices + [key for key in keys if key not in chosen]


def _js_json(value):
    if value is None:
        return "null"
    if value is _JS_UNDEFINED or callable(value):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        value = _js_num(value)
        if isinstance(value, float) and not _js_math.isfinite(value):
            return "null"
        return _js_num_str(value)
    if isinstance(value, str):
        return _js_json_quote(value)
    if isinstance(value, list):
        parts = [_js_json(item) for item in value]
        return "[" + ",".join("null" if part is None else part for part in parts) + "]"
    if isinstance(value, (_JsMap, _JsSet)):
        return "{}"
    if isinstance(value, dict):
        lookup = {key if isinstance(key, str) else _js_str(key): key for key in value}
        parts = []
        for key in _js_own_keys(value):
            part = _js_json(value[lookup[key]])
            if part is not None:
                parts.append(_js_json_quote(key) + ":" + part)
        return "{" + ",".join(parts) + "}"
    raise TypeError(f"ts2py: JSON.stringify of {type(value).__name__} is outside the subset")


def _js_json_stringify(value):
    """`JSON.stringify(value)`, byte for byte, for JSON-shaped values (and `undefined`)."""
    text = _js_json(value)
    return _JS_UNDEFINED if text is None else text
