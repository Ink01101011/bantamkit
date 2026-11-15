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
    if isinstance(value, _JsBigInt):
        return "bigint"
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
    if isinstance(value, _JsBigInt):
        return value.value != 0
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


# J86-5: the ints a double holds exactly. A fast path below takes an int only inside this range,
# where `_js_num` would return it unchanged, so it never skips a rounding JS would do.
_JS_SAFE_MIN = -(2**53)
_JS_SAFE_MAX = 2**53


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
    # J86-5 fast paths, each the answer the general path below gives for exactly these types: two
    # `str` compare by value; two plain ints inside the exact range compare by value (`_js_num`
    # would return both unchanged). `type(...) is` excludes bool and every subclass.
    kind = type(left)
    if kind is str and type(right) is str:
        return left == right
    if (
        kind is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left == right
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _js_num(left) == _js_num(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, _JsBigInt) and isinstance(right, _JsBigInt):
        return left.value == right.value
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
        return _js_from_units(
            ",".join("" if _js_is_nullish(item) else _js_str(item) for item in value)
        )
    if isinstance(value, _JsBigInt):
        return str(value.value)
    if isinstance(value, _JsObject):
        return _js_object_to_string(value)
    if isinstance(value, _JsMap):
        return "[object Map]"
    if isinstance(value, _JsSet):
        return "[object Set]"
    if isinstance(value, dict):
        return "[object Object]"
    raise TypeError(f"ts2py: String() of {type(value).__name__} is outside the subset")


def _js_add(left, right):
    """`left + right`: string concatenation when either side is a string, else numeric addition."""
    # J86-5: two plain ints inside the exact range add exactly; `_js_num` rounds the sum as the
    # general path does.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return _js_num(left + right)
    if isinstance(left, str) or isinstance(right, str):
        return _js_cat(_js_str(left), _js_str(right))
    if _js_is_number(left) and _js_is_number(right):
        return _js_num(_js_num(left) + _js_num(right))
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        a, b = _js_bigint_operands(left, right)
        return _JsBigInt(a + b)
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
    if (
        value is None
        or value is _JS_UNDEFINED
        or isinstance(value, (bool, int, float, str, _JsBigInt))
    ):
        return value
    return _js_str(value)


def _js_less(left, right):
    """IsLessThan(left, right): True, False, or None for JS `undefined` (a NaN operand).

    Two strings compare by UTF-16 code unit, as JS does; Python's `<` compares code points, which
    orders an astral character (one surrogate pair) after U+E000..U+FFFF instead of before it.
    Anything else is compared as numbers after ToNumber, so `"10" < 9` is false and `null < 1` true.
    """
    # J86-5: two plain ints inside the exact range are their own ToNumber, never NaN.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left < right
    left, right = _js_to_primitive(left), _js_to_primitive(right)
    if isinstance(left, str) and isinstance(right, str):
        if left.isascii() and right.isascii():
            return left < right
        return _js_utf16(left) < _js_utf16(right)
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        return _js_bigint_less(left, right)
    left, right = _js_to_number(left), _js_to_number(right)
    if left != left or right != right:
        return None
    return left < right


def _js_lt(left, right):
    """`left < right`."""
    # J86-5: `_js_less`'s exact-int fast path, taken here to save the call.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left < right
    return _js_less(left, right) is True


def _js_gt(left, right):
    """`left > right`."""
    # J86-5: `_js_less`'s exact-int fast path, taken here to save the call.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left > right
    return _js_less(right, left) is True


def _js_le(left, right):
    """`left <= right`: false when `right < left` or either side is NaN."""
    # J86-5: `_js_less`'s exact-int fast path, taken here to save the call.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left <= right
    return _js_less(right, left) is False


def _js_ge(left, right):
    """`left >= right`: false when `left < right` or either side is NaN."""
    # J86-5: `_js_less`'s exact-int fast path, taken here to save the call.
    if (
        type(left) is int
        and type(right) is int
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return left >= right
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
    # J86-5: an index into a string or an array by a plain int, the general path's answer for
    # exactly that pair of types (`_js_index_key` returns such an int as itself).
    if type(key) is int:
        if type(obj) is str:
            units = obj if obj.isascii() else _js_code_units(obj)
            return units[key] if 0 <= key < len(units) else _JS_UNDEFINED
        if isinstance(obj, list):
            return obj[key] if 0 <= key < len(obj) else _JS_UNDEFINED
    if isinstance(obj, dict):
        if not isinstance(key, str):
            key = _js_str(key)
        value = obj.get(key, _JS_UNDEFINED)
        if value is _JS_UNDEFINED and key in _JS_OBJECT_PROTO_NAMES and key not in obj:
            raise _js_inherited(key)
        return value
    if isinstance(obj, str):
        if key == "length" and isinstance(key, str):
            return _js_len(obj)
        index = _js_index_key(key)
        if index is None:
            if key in _JS_STRING_METHODS:
                raise _js_method_value(key)
            return _JS_UNDEFINED
        # J86: a string is indexed by UTF-16 code unit, so an astral character reads as its lead
        # or trail surrogate, as in JS.
        units = _js_code_units(obj)
        return units[index] if 0 <= index < len(units) else _JS_UNDEFINED
    if isinstance(obj, list):
        if key == "length" and isinstance(key, str):
            return _js_len(obj)
        index = _js_index_key(key)
        if index is not None and 0 <= index < len(obj):
            return obj[index]
        if key in ("index", "input") and isinstance(obj, _JsMatchArray):
            return getattr(obj, key)
        if key in _JS_ARRAY_METHODS:
            raise _js_method_value(key)
        return _JS_UNDEFINED
    if obj is None or obj is _JS_UNDEFINED:
        raise TypeError(f"Cannot read properties of {_js_str(obj)} (reading '{_js_str(key)}')")
    if isinstance(obj, (_JsMap, _JsSet)) and key == "size":
        return len(obj)
    if isinstance(obj, _JsObject):
        return _js_object_get(obj, key if isinstance(key, str) else _js_str(key))
    if isinstance(key, str) and key in _js_methods_of(obj):
        raise _js_method_value(key)
    return _JS_UNDEFINED


def _js_put(obj, key, value):
    """`obj.key = value` on a plain object."""
    key = key if isinstance(key, str) else _js_str(key)
    if isinstance(obj, _JsObject):
        if key.startswith("_") or key in _JS_OBJECT_PROTO_NAMES:
            raise TypeError(f"ts2py: assigning {key!r} on an instance is outside the subset")
        setattr(obj, key, value)
        return
    if not isinstance(obj, dict):
        raise TypeError("ts2py: property assignment on a non-object is outside the subset")
    if key == "__proto__":
        # `o.__proto__ = v` / `o["__proto__"] = v` sets the prototype in JS, not a key.
        raise TypeError("ts2py: assigning __proto__ is outside the subset")
    obj[key] = value


def _js_len(value):
    """`value.length`: UTF-16 code units for a string, element count for an array."""
    if isinstance(value, str):
        # J86-5: one code unit per character of `_js_code_units` (an ASCII string is its own),
        # the count the UTF-16 encoding gives, without encoding the string on every read.
        return len(value) if value.isascii() else len(_js_code_units(value))
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
        needle = _js_str(item)
        if receiver.isascii() and needle.isascii():
            return needle in receiver
        return _js_code_units(needle) in _js_code_units(receiver)
    if isinstance(receiver, list):
        if type(item) is str:
            # J86-5: SameValueZero against a `str` is true for a `str` element of equal value
            # and for nothing else (a bool, number, BigInt or object is never one).
            for element in receiver:
                if isinstance(element, str) and element == item:
                    return True
            return False
        return any(_js_same_value_zero(element, item) for element in receiver)
    raise _js_outside("includes", receiver)


def _js_m_startsWith(receiver, prefix):
    if isinstance(receiver, str):
        prefix = _js_str(prefix)
        if receiver.isascii() and prefix.isascii():
            return receiver.startswith(prefix)
        return _js_code_units(receiver).startswith(_js_code_units(prefix))
    raise _js_outside("startsWith", receiver)


def _js_m_split(receiver, separator):
    if isinstance(receiver, str) and isinstance(separator, str):
        if receiver.isascii() and separator.isascii():
            return list(receiver) if separator == "" else receiver.split(separator)
        # J86: by UTF-16 code unit, so `""` splits an astral character into its two surrogates
        # and a separator that is half of a pair is found inside one, as in JS.
        units = _js_code_units(receiver)
        if separator == "":
            return list(units)
        return [_js_from_units(part) for part in units.split(_js_code_units(separator))]
    raise _js_outside("split", receiver)


# J86-5: `_js_code_units` of a non-ASCII string, remembered. The answer is a function of the
# string's value alone, so a remembered one is the one a fresh computation gives; the scanners
# index one string thousands of times, and each read recomputed it (an O(n) `max`) before.
# Bounded: cleared when full, and a long string is never kept.
_JS_UNITS = {}
_JS_UNITS_ENTRIES = 512
_JS_UNITS_LONGEST = 1 << 16


def _js_code_units(text):
    """`text` with every astral character split into its two surrogates: the string as a JS regex
    without the `u` flag sees it, one UTF-16 code unit per Python character."""
    if text.isascii():
        return text
    units = _JS_UNITS.get(text)
    if units is None:
        units = _js_code_units_of(text)
        if len(text) <= _JS_UNITS_LONGEST:
            if len(_JS_UNITS) >= _JS_UNITS_ENTRIES:
                _JS_UNITS.clear()
            _JS_UNITS[text] = units
    return units


def _js_code_units_of(text):
    if max(text) < "\U00010000":
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
    if type(receiver) is list:
        # J86-5: `_js_array` passes a list unchanged.
        receiver.extend(items)
        return len(receiver)
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
    if isinstance(receiver, str):
        # J86: string positions are UTF-16 code units; a cut through a pair leaves a lone surrogate.
        units = _js_code_units(receiver)
        length = len(units)
        return _js_from_units(
            units[_js_slice_bound(start, length, 0) : _js_slice_bound(end, length, length)]
        )
    items = _js_array("slice", receiver)
    length = len(items)
    return items[_js_slice_bound(start, length, 0) : _js_slice_bound(end, length, length)]


def _js_m_join(receiver, separator=_JS_UNDEFINED):
    items = _js_array("join", receiver)
    glue = "," if separator is _JS_UNDEFINED else _js_str(separator)
    return _js_from_units(
        glue.join("" if _js_is_nullish(item) else _js_str(item) for item in items)
    )


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


# ---------------------------------------------------------------- J86: strings as UTF-16

_JS_SURROGATE = _js_re.compile("[\ud800-\udfff]")


def _js_from_units(text):
    """The canonical spelling of a JS string held as code units: every lead surrogate followed by a
    trail surrogate joined into its astral character, lone surrogates kept. Two halves that meet by
    concatenation form one character in JS, so they must here too."""
    if text.isascii() or _JS_SURROGATE.search(text) is None:
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _js_cat(left, right):
    """`left + right` on two strings: a lead surrogate ending `left` and a trail surrogate starting
    `right` become one astral character, as two UTF-16 halves do in JS."""
    if left and right and "\ud800" <= left[-1] <= "\udbff" and "\udc00" <= right[0] <= "\udfff":
        return _js_from_units(left + right)
    return left + right


def _js_to_integer(value):
    """ToIntegerOrInfinity: NaN is 0, a fraction truncates toward zero, an infinity stays."""
    value = _js_to_number(_js_to_primitive(value))
    if value != value:
        return 0
    if value in (_js_math.inf, -_js_math.inf):
        return value
    return int(value)


def _js_m_codePointAt(receiver, position=_JS_UNDEFINED):
    if not isinstance(receiver, str):
        raise _js_outside("codePointAt", receiver)
    units = _js_code_units(receiver)
    # J86-5: a plain int inside the exact range is its own ToIntegerOrInfinity.
    if type(position) is int and _JS_SAFE_MIN <= position <= _JS_SAFE_MAX:
        index = position
    else:
        index = _js_to_integer(position)
    if not 0 <= index < len(units):
        return _JS_UNDEFINED
    first = ord(units[index])
    if 0xD800 <= first <= 0xDBFF and index + 1 < len(units):
        second = ord(units[index + 1])
        if 0xDC00 <= second <= 0xDFFF:
            return 0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
    return first


def _js_from_code_point(*points):
    """`String.fromCodePoint`: each argument an integer in 0..0x10FFFF, else RangeError."""
    out = []
    for point in points:
        if type(point) is int and 0 <= point <= 0x10FFFF:
            # J86-5: the one shape the check below passes without converting anything.
            out.append(chr(point))
            continue
        number = _js_to_number(_js_to_primitive(point))
        if not (
            _js_is_number(number)
            and number == number
            and number not in (_js_math.inf, -_js_math.inf)
            and number == int(number)
            and 0 <= number <= 0x10FFFF
        ):
            raise _JsRangeError(f"Invalid code point {_js_str(number)}")
        out.append(chr(int(number)))
    return _js_from_units("".join(out))


def _js_string_receiver(method, receiver):
    if not isinstance(receiver, str):
        raise _js_outside(method, receiver)
    return receiver


def _js_m_indexOf(receiver, search, position=_JS_UNDEFINED):
    """`s.indexOf(search, position)` in UTF-16 code units (strings only)."""
    units = _js_code_units(_js_string_receiver("indexOf", receiver))
    needle = _js_code_units(_js_str(search))
    start = min(max(_js_to_integer(position), 0), len(units))
    return units.find(needle, int(start))


def _js_m_lastIndexOf(receiver, search, position=_JS_UNDEFINED):
    """`s.lastIndexOf(search, position)` in UTF-16 code units; a NaN or missing position is
    +Infinity."""
    units = _js_code_units(_js_string_receiver("lastIndexOf", receiver))
    needle = _js_code_units(_js_str(search))
    number = _js_to_number(_js_to_primitive(position))
    start = _js_math.inf if number != number else _js_to_integer(number)
    start = int(min(max(start, 0), len(units)))
    return units.rfind(needle, 0, start + len(needle))


def _js_pad(method, receiver, length, fill, at_start):
    units = _js_code_units(_js_string_receiver(method, receiver))
    target = _js_to_integer(length)
    if target <= len(units):
        return receiver
    filler = " " if fill is _JS_UNDEFINED else _js_code_units(_js_str(fill))
    if filler == "":
        return receiver
    need = int(target) - len(units)
    padding = (filler * (need // len(filler) + 1))[:need]
    return _js_from_units(padding + units if at_start else units + padding)


def _js_m_padStart(receiver, length, fill=_JS_UNDEFINED):
    return _js_pad("padStart", receiver, length, fill, True)


def _js_m_padEnd(receiver, length, fill=_JS_UNDEFINED):
    return _js_pad("padEnd", receiver, length, fill, False)


def _js_m_repeat(receiver, count=_JS_UNDEFINED):
    text = _js_string_receiver("repeat", receiver)
    times = _js_to_integer(count)
    if times < 0 or times == _js_math.inf:
        raise _JsRangeError(
            f"Invalid count value: {_js_str(_js_to_number(_js_to_primitive(count)))}"
        )
    return _js_from_units(text * int(times))


def _js_m_toLowerCase(receiver):
    """ASCII only: CPython and V8 follow different Unicode versions, so a non-ASCII string raises
    rather than risk a different answer."""
    text = _js_string_receiver("toLowerCase", receiver)
    if not text.isascii():
        raise TypeError("ts2py: .toLowerCase() on a non-ASCII string is outside the subset")
    return text.lower()


def _js_m_toUpperCase(receiver):
    """ASCII only, as `.toLowerCase()`."""
    text = _js_string_receiver("toUpperCase", receiver)
    if not text.isascii():
        raise TypeError("ts2py: .toUpperCase() on a non-ASCII string is outside the subset")
    return text.upper()


class _JsGlobalRegExp:
    """A regex literal with the `g` flag. Only `.replace` accepts one: `.test` and `.exec` on a
    global regex read and write `lastIndex`, which the subset does not model."""

    __slots__ = ("pattern",)

    def __init__(self, pattern):
        self.pattern = pattern


def _js_m_replace(receiver, pattern, replacement):
    """`s.replace(pattern, replacement)`: a string pattern replaces its first occurrence, a regex
    its first match, a `g` regex every match; matching runs over UTF-16 code units. A replacement
    that is not a string, or that holds `$` (JS's substitution patterns), is outside the subset."""
    text = _js_string_receiver("replace", receiver)
    if not isinstance(replacement, str):
        raise TypeError("ts2py: .replace() with a non-string replacement is outside the subset")
    if "$" in replacement:
        raise TypeError(
            "ts2py: .replace() with a $ pattern in the replacement is outside the subset"
        )
    units = _js_code_units(text)
    if isinstance(pattern, _JsGlobalRegExp):
        return _js_from_units(pattern.pattern.sub(lambda _m: replacement, units))
    if isinstance(pattern, _js_re.Pattern):
        return _js_from_units(pattern.sub(lambda _m: replacement, units, count=1))
    needle = _js_code_units(_js_str(pattern))
    at = units.find(needle)
    if at == -1:
        return text
    return _js_from_units(units[:at] + replacement + units[at + len(needle) :])


class _JsMatchArray(list):
    """What `re.exec(s)` returns: the match and its groups (`undefined` for one that did not take
    part), plus `index` (a UTF-16 position) and `input`."""

    __slots__ = ("index", "input")


def _js_m_exec(receiver, text):
    if not isinstance(receiver, _js_re.Pattern):
        raise _js_outside("exec", receiver)
    subject = _js_str(text)
    match = receiver.search(_js_code_units(subject))
    if match is None:
        return None
    out = _JsMatchArray(
        _JS_UNDEFINED if group is None else _js_from_units(group)
        for group in [match.group(0), *match.groups()]
    )
    out.index = match.start()
    out.input = subject
    return out


_JS_DYNAMIC_RE = {}


def _js_regexp_dynamic(*parts):
    """`new RegExp(`...${n}...`)` where every substitution is a whole `{n}` repeat count: the even
    parts are already-translated pattern text, each odd part the count, which must be an integer
    in 0..65535 (anything else would spell a different pattern in JS)."""
    pieces = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            pieces.append(part)
            continue
        number = part
        if not (
            _js_is_number(number)
            and number == number
            and number == int(number)
            and 0 <= number <= 65535
        ):
            raise TypeError(
                "ts2py: a RegExp repeat count that is not an integer in 0..65535"
                " is outside the subset"
            )
        pieces.append(str(int(number)))
    source = "".join(pieces)
    compiled = _JS_DYNAMIC_RE.get(source)
    if compiled is None:
        compiled = _JS_DYNAMIC_RE[source] = _js_re.compile(source, _js_re.ASCII)
    return compiled


def _js_m_reverse(receiver):
    items = _js_array("reverse", receiver)
    items.reverse()
    return items


def _js_m_pop(receiver):
    items = _js_array("pop", receiver)
    return items.pop() if items else _JS_UNDEFINED


def _js_m_filter(receiver, callback):
    items = _js_array("filter", receiver)
    return [item for index, item in enumerate(items) if _js_truthy(callback(item, index, items))]


# ---------------------------------------------------------------- J86: numbers

_JS_INFINITY = _js_math.inf
_JS_NAN = _js_math.nan


def _js_double_out(value):
    """A float result back in the int-when-exact spelling: an integral finite value within 2^53
    becomes an `int`, except -0, which only a float can hold."""
    if (
        isinstance(value, float)
        and value == value
        and value not in (_js_math.inf, -_js_math.inf)
        and value.is_integer()
        and abs(value) <= 2**53
        and not (value == 0 and _js_math.copysign(1.0, value) < 0)
    ):
        return int(value)
    return value


def _js_to_numeric(value):
    """ToNumeric: a BigInt stays one, anything else is ToNumber of its primitive."""
    value = _js_to_primitive(value)
    if isinstance(value, _JsBigInt):
        return value
    return _js_to_number(value)


def _js_mix_error():
    return _JsTypeError("Cannot mix BigInt and other types, use explicit conversions")


def _js_bigint_operands(left, right):
    left, right = _js_to_numeric(left), _js_to_numeric(right)
    if not (isinstance(left, _JsBigInt) and isinstance(right, _JsBigInt)):
        raise _js_mix_error()
    return left.value, right.value


def _js_float_pair(left, right):
    return float(_js_num(left)), float(_js_num(right))


def _js_mul(left, right):
    """`left * right`: numbers as doubles (the sign of a zero kept), two BigInts exactly."""
    left, right = _js_to_numeric(left), _js_to_numeric(right)
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        a, b = _js_bigint_operands(left, right)
        return _JsBigInt(a * b)
    left, right = _js_num(left), _js_num(right)
    if type(left) is int and type(right) is int and left != 0 and right != 0:
        return _js_num(left * right)
    a, b = _js_float_pair(left, right)
    return _js_double_out(a * b)


def _js_div(left, right):
    """`left / right`: IEEE division of the two doubles, so `1 / 0` is Infinity and `0 / 0` NaN;
    two BigInts divide truncating toward zero and a BigInt zero divisor is a RangeError."""
    left, right = _js_to_numeric(left), _js_to_numeric(right)
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        a, b = _js_bigint_operands(left, right)
        if b == 0:
            raise _JsRangeError("Division by zero")
        quotient = abs(a) // abs(b)
        return _JsBigInt(quotient if (a < 0) == (b < 0) else -quotient)
    a, b = _js_float_pair(left, right)
    if b == 0:
        if a == 0 or a != a:
            return _js_math.nan
        negative = (_js_math.copysign(1.0, a) < 0) != (_js_math.copysign(1.0, b) < 0)
        return -_js_math.inf if negative else _js_math.inf
    return _js_double_out(a / b)


def _js_mod(left, right):
    """`left % right`: the remainder takes the sign of the dividend (a zero result keeps it, so
    `-4 % 2` is -0); a zero divisor or an infinite dividend is NaN. BigInts exactly."""
    left, right = _js_to_numeric(left), _js_to_numeric(right)
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        a, b = _js_bigint_operands(left, right)
        if b == 0:
            raise _JsRangeError("Division by zero")
        rest = abs(a) % abs(b)
        return _JsBigInt(-rest if a < 0 else rest)
    a, b = _js_float_pair(left, right)
    if b == 0 or a != a or b != b or a in (_js_math.inf, -_js_math.inf):
        return _js_math.nan
    if b in (_js_math.inf, -_js_math.inf):
        return _js_double_out(a)
    return _js_double_out(_js_math.fmod(a, b))


def _js_neg(value):
    """Unary `-`: `-0` is a float (an int has no negative zero); a BigInt negates exactly."""
    value = _js_to_numeric(value)
    if isinstance(value, _JsBigInt):
        return _JsBigInt(-value.value)
    value = _js_num(value)
    if type(value) is int and value == 0:
        return -0.0
    return -value


def _js_math_arg(value):
    return _js_num(_js_to_number(_js_to_primitive(value)))


def _js_floor(value):
    """`Math.floor`: NaN, the infinities and -0 come back unchanged."""
    value = _js_math_arg(value)
    if type(value) is int or value != value or value in (_js_math.inf, -_js_math.inf) or value == 0:
        return value
    return _js_math.floor(value)


def _js_abs(value):
    """`Math.abs`."""
    return abs(_js_math_arg(value))


def _js_extreme(values, pick_max):
    numbers = [_js_math_arg(value) for value in values]
    best = -_js_math.inf if pick_max else _js_math.inf
    for number in numbers:
        if number != number:
            return _js_math.nan
        if number == best == 0:
            # +0 is larger than -0 for Math.max, smaller for Math.min.
            negative = _js_math.copysign(1.0, number) < 0
            if negative != pick_max:
                best = number
        elif (number > best) if pick_max else (number < best):
            best = number
    return best


def _js_max(*values):
    """`Math.max`: any NaN is NaN, +0 beats -0, no argument is -Infinity."""
    return _js_extreme(values, True)


def _js_min(*values):
    """`Math.min`: any NaN is NaN, -0 beats +0, no argument is Infinity."""
    return _js_extreme(values, False)


def _js_number(value=0):
    """`Number(value)`: ToNumeric, and a BigInt converts to the nearest double."""
    value = _js_to_numeric(value)
    if isinstance(value, _JsBigInt):
        return _js_num(value.value)
    return _js_double_out(value) if isinstance(value, float) else value


def _js_number_is_nan(value):
    """`Number.isNaN`: a number that is NaN; nothing else, no coercion."""
    return isinstance(value, float) and value != value


_JS_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _js_parse_int(text, radix=_JS_UNDEFINED):
    """`parseInt(text, radix)`: leading JS whitespace and a sign, then the longest run of digits in
    the radix (16 also accepts a `0x` prefix; radix 0 or missing reads `0x` as 16, else 10). No
    digit is NaN. A run whose value is past 2^53 in a radix other than 10 or a power of two is
    outside the subset (V8 rounds those approximately)."""
    text = _js_str(text).lstrip(_JS_WHITESPACE)
    sign = 1
    if text[:1] in ("+", "-"):
        sign = -1 if text[0] == "-" else 1
        text = text[1:]
    base = (
        0 if radix is _JS_UNDEFINED else int(_js_num(_js_to_number(_js_to_primitive(radix))) or 0)
    )
    strip_prefix = base in (0, 16)
    if base == 0:
        base = 10
    elif not 2 <= base <= 36:
        return _js_math.nan
    if strip_prefix and text[:2] in ("0x", "0X"):
        text = text[2:]
        base = 16
    digits = _JS_DIGITS[:base]
    end = 0
    while end < len(text) and text[end].lower() in digits and text[end].isascii():
        end += 1
    if end == 0:
        return _js_math.nan
    value = int(text[:end], base)
    if value > 2**53 and base not in (2, 4, 8, 10, 16, 32):
        raise TypeError("ts2py: parseInt past 2^53 in this radix is outside the subset")
    if value == 0 and sign < 0:
        return -0.0
    return _js_num(sign * value)


def _js_int_to_radix(value, radix):
    if value == 0:
        return "0"
    negative = value < 0
    value = abs(value)
    out = []
    while value:
        value, digit = divmod(value, radix)
        out.append(_JS_DIGITS[digit])
    return ("-" if negative else "") + "".join(reversed(out))


def _js_m_toString(receiver, radix=_JS_UNDEFINED):
    """`x.toString(radix?)`: a class instance's own `toString`, `Error.prototype.toString`, a number
    or BigInt in a radix 2..36 (a number with a fraction only in radix 10), a string as itself."""
    if isinstance(receiver, _JsObject):
        return _js_object_to_string(receiver)
    base = 10 if radix is _JS_UNDEFINED else _js_to_integer(radix)
    if not 2 <= base <= 36:
        raise _JsRangeError("toString() radix must be between 2 and 36")
    if isinstance(receiver, _JsBigInt):
        return _js_int_to_radix(receiver.value, int(base))
    if _js_is_number(receiver):
        if base == 10:
            return _js_num_str(receiver)
        value = _js_num(receiver)
        if value != value or value in (_js_math.inf, -_js_math.inf):
            return _js_num_str(value)
        if value != int(value):
            raise TypeError("ts2py: .toString(radix) of a fraction is outside the subset")
        return _js_int_to_radix(int(value), int(base))
    if isinstance(receiver, (str, bool, list)) or receiver is None or isinstance(receiver, dict):
        if receiver is None:
            raise TypeError("Cannot read properties of null (reading 'toString')")
        return _js_str(receiver)
    raise _js_outside("toString", receiver)


# ---------------------------------------------------------------- J86: BigInt


class _JsBigInt:
    """A JS BigInt: exact, and never equal to a number (`1n !== 1`, distinct Map keys)."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, _JsBigInt) and other.value == self.value

    def __hash__(self):
        return hash((_JsBigInt, self.value))

    def __repr__(self):
        return f"{self.value}n"

    # The J85 lowering of `a - b` and `-a` applies Python's operators to the operands; these keep
    # that lowering exact for BigInts and make a mixed operation the TypeError JS raises.
    def __sub__(self, other):
        a, b = _js_bigint_operands(self, other)
        return _JsBigInt(a - b)

    def __rsub__(self, other):
        a, b = _js_bigint_operands(other, self)
        return _JsBigInt(a - b)

    def __neg__(self):
        return _JsBigInt(-self.value)

    def __add__(self, other):
        a, b = _js_bigint_operands(self, other)
        return _JsBigInt(a + b)

    def __radd__(self, other):
        a, b = _js_bigint_operands(other, self)
        return _JsBigInt(a + b)

    # A BigInt compares with a number by exact value, as JS does (NaN is never less or greater).
    def __lt__(self, other):
        return _js_bigint_less(self, other) is True

    def __gt__(self, other):
        return _js_bigint_less(other, self) is True

    def __le__(self, other):
        return _js_bigint_less(other, self) is False

    def __ge__(self, other):
        return _js_bigint_less(self, other) is False


_JS_BIGINT_TEXT = _js_re.compile(
    r"[+-]?[0-9]+\Z|0[xX][0-9a-fA-F]+\Z|0[oO][0-7]+\Z|0[bB][01]+\Z", _js_re.ASCII
)


def _js_bigint(value):
    """`BigInt(value)`: an integral number, a boolean, or a string in StringToBigInt's grammar (JS
    whitespace trimmed, empty is 0n, a sign only on decimal digits, `0x` / `0o` / `0b`)."""
    value = _js_to_primitive(value)
    if isinstance(value, _JsBigInt):
        return value
    if isinstance(value, bool):
        return _JsBigInt(int(value))
    if _js_is_number(value):
        value = _js_num(value)
        if value != value or value in (_js_math.inf, -_js_math.inf) or value != int(value):
            raise _JsRangeError(
                f"The number {_js_num_str(value)} cannot be converted to a BigInt"
                " because it is not an integer"
            )
        return _JsBigInt(int(value))
    if isinstance(value, str):
        text = value.strip(_JS_WHITESPACE)
        if text == "":
            return _JsBigInt(0)
        if not _JS_BIGINT_TEXT.match(text):
            raise _JsSyntaxError(f"Cannot convert {value} to a BigInt")
        if text[:2].lower() in ("0x", "0o", "0b"):
            return _JsBigInt(int(text[2:], {"x": 16, "o": 8, "b": 2}[text[1].lower()]))
        return _JsBigInt(int(text))
    raise _JsTypeError(f"Cannot convert {_js_str(value)} to a BigInt")


def _js_bigint_less(left, right):
    """IsLessThan with a BigInt on either side, compared exactly against a number."""

    def exact(value):
        if isinstance(value, _JsBigInt):
            return value.value
        if isinstance(value, str):
            raise TypeError("ts2py: comparing a BigInt with a string is outside the subset")
        return _js_to_number(value)

    left, right = exact(left), exact(right)
    if left != left or right != right:
        return None
    return left < right


# ---------------------------------------------------------------- J86: objects and classes

_JS_OBJECT_PROTO_NAMES = frozenset(
    {
        "__proto__",
        "__defineGetter__",
        "__defineSetter__",
        "__lookupGetter__",
        "__lookupSetter__",
        "constructor",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "toLocaleString",
        "toString",
        "valueOf",
    }
)


# J86-R finding 3: the method names each builtin prototype carries, for a COMPUTED key the compiler
# could not see (`xs[k]` with `k === 'push'`). JS answers with the function; ts2py refuses at
# compile time every method read as a value it can name, and here every one it could not.
_JS_STRING_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset(
    "anchor at big blink bold charAt charCodeAt codePointAt concat endsWith fixed fontcolor "
    "fontsize includes indexOf isWellFormed italics lastIndexOf link localeCompare match matchAll "
    "normalize padEnd padStart repeat replace replaceAll search slice small split startsWith "
    "strike sub substr substring sup toLocaleLowerCase toLocaleUpperCase toLowerCase toUpperCase "
    "toWellFormed trim trimEnd trimLeft trimRight trimStart".split()
)
_JS_ARRAY_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset(
    "at concat copyWithin entries every fill filter find findIndex findLast findLastIndex flat "
    "flatMap forEach includes indexOf join keys lastIndexOf map pop push reduce reduceRight "
    "reverse shift slice some sort splice toReversed toSorted toSpliced unshift values with".split()
)
_JS_MAP_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset(
    "clear delete entries forEach get has keys set values".split()
)
_JS_SET_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset(
    "add clear delete difference entries forEach has intersection isDisjointFrom isSubsetOf "
    "isSupersetOf keys symmetricDifference union values".split()
)
_JS_NUMBER_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset(
    "toExponential toFixed toPrecision".split()
)
_JS_REGEXP_METHODS = _JS_OBJECT_PROTO_NAMES | frozenset("compile exec test".split())


def _js_methods_of(obj):
    if isinstance(obj, _JsMap):
        return _JS_MAP_METHODS
    if isinstance(obj, _JsSet):
        return _JS_SET_METHODS
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return _JS_NUMBER_METHODS
    if isinstance(obj, _js_re.Pattern):
        return _JS_REGEXP_METHODS
    return _JS_OBJECT_PROTO_NAMES


def _js_method_value(key):
    return TypeError(f"ts2py: reading the method {key!r} as a value is outside the subset")


def _js_inherited(key):
    """A read that would reach `Object.prototype` in JS (`o.constructor`, `o["toString"]`): JS
    answers with an inherited function, which the subset does not model, so it raises instead."""
    return TypeError(f"ts2py: reading the inherited {key!r} is outside the subset")


def _js_class_names(cls, attribute):
    names = set()
    for klass in cls.__mro__:
        names |= klass.__dict__.get(attribute, frozenset())
    return names


class _JsObject:
    """Base of every class ts2py compiles. Fields are instance attributes spelled as in JS; the
    class lists its own members in `_js_own` and its methods in `_js_own_methods`, so a reflective
    read (`_js_get`) sees exactly what JS would and nothing Python adds. `Object.freeze` makes every
    later assignment the TypeError strict-mode JS raises."""

    _js_name = "Object"
    _js_own = frozenset()
    _js_own_methods = frozenset()
    _js_frozen = False

    def __setattr__(self, name, value):
        if self._js_frozen:
            if name in self.__dict__:
                raise _JsTypeError(
                    f"Cannot assign to read only property '{name}' of object '#<{self._js_name}>'"
                )
            raise _JsTypeError(f"Cannot add property {name}, object is not extensible")
        object.__setattr__(self, name, value)


def _js_object_get(obj, key):
    own = obj.__dict__
    if key in own and not key.startswith("_"):
        return own[key]
    if key in _js_class_names(type(obj), "_js_own_methods"):
        raise _js_method_value(key)
    if key in _js_class_names(type(obj), "_js_own"):
        return getattr(obj, key)
    if key in _JS_OBJECT_PROTO_NAMES:
        raise _js_inherited(key)
    if key in ("stack", "cause") and isinstance(obj, _JsError):
        raise TypeError(f"ts2py: reading an Error's {key!r} is outside the subset")
    return _JS_UNDEFINED


def _js_object_to_string(obj):
    if "toString" in _js_class_names(type(obj), "_js_own_methods"):
        result = obj.toString()
        if isinstance(result, (dict, list, _JsObject)):
            raise _JsTypeError("Cannot convert object to primitive value")
        return _js_str(result)
    return "[object Object]"


def _js_invoke(receiver, name, *args):
    """`receiver.name(...args)` for a method a compiled class declares."""
    if isinstance(receiver, _JsObject) and name in _js_class_names(
        type(receiver), "_js_own_methods"
    ):
        return getattr(receiver, name)(*args)
    if receiver is None or receiver is _JS_UNDEFINED:
        raise TypeError(f"Cannot read properties of {_js_str(receiver)} (reading '{name}')")
    raise _js_outside(name, receiver)


def _js_dispatch(receiver, name, builtin, *args):
    """`receiver.name(...args)` where a compiled class and a builtin both declare `name`: an
    instance of such a class runs its own method, anything else the builtin, as JS's lookup
    would."""
    if type(receiver) is list:
        # J86-5: a list is never a `_JsObject`, so it always takes the builtin.
        return builtin(receiver, *args)
    if isinstance(receiver, _JsObject) and name in _js_class_names(
        type(receiver), "_js_own_methods"
    ):
        return getattr(receiver, name)(*args)
    return builtin(receiver, *args)


def _js_freeze(value):
    """`Object.freeze(value)` on a class instance (a plain object or array is outside the
    subset)."""
    if not isinstance(value, _JsObject):
        raise TypeError(
            "ts2py: Object.freeze of anything but a class instance is outside the subset"
        )
    object.__setattr__(value, "_js_frozen", True)
    return value


class _JsError(_JsObject, Exception):
    """`Error`: `message` is own only when one was passed; `name` is inherited (`"Error"` for every
    subclass that does not set its own), and `String(e)` is `name: message`."""

    _js_name = "Error"
    _js_own = frozenset({"message", "name", "toString"})
    _js_own_methods = frozenset({"toString"})
    name = "Error"
    message = ""

    def __init__(self, message=_JS_UNDEFINED, *_):
        Exception.__init__(self, "" if message is _JS_UNDEFINED else _js_str(message))
        if message is not _JS_UNDEFINED:
            self.message = _js_str(message)

    def toString(self):
        name = _js_get(self, "name")
        message = _js_get(self, "message")
        name = "Error" if name is _JS_UNDEFINED else _js_str(name)
        message = "" if message is _JS_UNDEFINED else _js_str(message)
        if name == "":
            return message
        if message == "":
            return name
        return name + ": " + message

    def __str__(self):
        return _js_str(_js_get(self, "message"))


class _JsTypeError(_JsError, TypeError):
    _js_name = "TypeError"
    name = "TypeError"


class _JsRangeError(_JsError, ValueError):
    _js_name = "RangeError"
    name = "RangeError"


class _JsSyntaxError(_JsError, ValueError):
    _js_name = "SyntaxError"
    name = "SyntaxError"


def _js_throw(value):
    """`throw value`: an Error (any Python exception) is raised as itself; throwing anything else
    is outside the subset."""
    if isinstance(value, BaseException):
        return value
    return TypeError("ts2py: throwing a value that is not an Error is outside the subset")


_JS_PROTOTYPES = {}


class _JsPrototype:
    """A stand-in for a built-in prototype object, compared by identity only."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


_JS_OBJECT_PROTOTYPE = _JsPrototype("Object.prototype")


def _js_get_prototype_of(value):
    """`Object.getPrototypeOf(value)`: `Object.prototype` for a plain object, the class for a class
    instance, a distinct stand-in for every other kind of value."""
    if value is None or value is _JS_UNDEFINED:
        raise _JsTypeError("Cannot convert undefined or null to object")
    if isinstance(value, dict):
        return _JS_OBJECT_PROTOTYPE
    if isinstance(value, _JsObject):
        return type(value)
    kind = (
        "Boolean"
        if isinstance(value, bool)
        else "Number"
        if isinstance(value, (int, float))
        else "String"
        if isinstance(value, str)
        else "Array"
        if isinstance(value, list)
        else type(value).__name__
    )
    if kind not in _JS_PROTOTYPES:
        _JS_PROTOTYPES[kind] = _JsPrototype(kind + ".prototype")
    return _JS_PROTOTYPES[kind]


def _js_own_property_names(value):
    if isinstance(value, dict):
        return _js_own_keys(value)
    if isinstance(value, list):
        return [str(index) for index in range(len(value))]
    if isinstance(value, str):
        return [str(index) for index in range(_js_len(value))]
    if isinstance(value, _JsObject):
        return [key for key in value.__dict__ if not key.startswith("_")]
    if value is None or value is _JS_UNDEFINED:
        raise _JsTypeError("Cannot convert undefined or null to object")
    if isinstance(value, (bool, int, float, _JsBigInt, _JsMap, _JsSet)):
        return []
    raise TypeError(f"ts2py: the keys of {type(value).__name__} are outside the subset")


def _js_object_keys(value):
    """`Object.keys(value)`: own enumerable string keys, array indices ascending first."""
    return _js_own_property_names(value)


def _js_object_entries(value):
    """`Object.entries(value)`: `[key, value]` pairs in `Object.keys` order."""
    return [[key, _js_get(value, key)] for key in _js_own_property_names(value)]


def _js_spread(value):
    """`{...value}`: the own enumerable properties; `null`, `undefined` and primitives give none."""
    if value is None or value is _JS_UNDEFINED or isinstance(value, (bool, int, float, _JsBigInt)):
        return {}
    return {key: _js_get(value, key) for key in _js_own_property_names(value)}


def _js_in(key, obj):
    """`key in obj`: own keys, and on a plain object or instance also what `Object.prototype`
    gives."""
    if not isinstance(key, str):
        key = _js_str(key)
    if isinstance(obj, dict):
        return key in obj or key in _JS_OBJECT_PROTO_NAMES
    if isinstance(obj, _JsObject):
        return (
            (key in obj.__dict__ and not key.startswith("_"))
            or key in _js_class_names(type(obj), "_js_own")
            or key in _JS_OBJECT_PROTO_NAMES
        )
    if isinstance(obj, list):
        index = _js_index_key(key)
        if index is not None:
            return 0 <= index < len(obj)
        if key == "length":
            return True
        raise TypeError(f"ts2py: {key!r} in an array is outside the subset")
    raise _JsTypeError(f"Cannot use 'in' operator to search for '{key}' in {_js_str(obj)}")


def _js_destructure(value, count):
    """The first `count` items an array pattern reads: through the iterator, so a string gives code
    points; short input reads `undefined`; `null`, `undefined` or a plain object is a TypeError."""
    if value is None or value is _JS_UNDEFINED:
        raise _JsTypeError(f"{_js_str(value)} is not iterable")
    if isinstance(value, list):
        items = value[:count]
    elif isinstance(value, (str, _JsMap, _JsSet)):
        items = []
        for item in value:
            if len(items) == count:
                break
            items.append(item)
    else:
        raise _JsTypeError("object is not iterable")
    return list(items) + [_JS_UNDEFINED] * (count - len(items))
