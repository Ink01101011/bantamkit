# ts2py runtime support: the JavaScript semantics the generated code leans on.
# Pure standard library. Every name starts with `_js_`, `_Js` or `_JS_`, and ts2py refuses a
# TypeScript identifier with one of those prefixes, so nothing here can be shadowed by source.
import base64 as _js_base64
import bisect as _js_bisect
import decimal as _js_decimal
import errno as _js_errno
import functools as _js_functools
import gc as _js_gc
import itertools as _js_itertools
import json as _js_jsonlib
import math as _js_math
import operator as _js_operator
import re as _js_re
import sys as _js_sys
import time as _js_time
from typing import Any as _JsAny  # noqa: F401 -- re-exported to the generated modules
from typing import ClassVar as _ClassVar
from typing import Final as _Final


# J90-P7 (#316 G4): the runtime and the generated modules compile with mypyc as they stand. Only
# mypyc reads `_mypyc_attr` (it knows the name as `mypy_extensions.mypyc_attr`); at run time that
# decorator returns the class unchanged, and so does the stand-in where `mypy_extensions` is absent.
def _js_late(fn):
    """J90-P7: the identity, as a decorator: mypyc calls a decorated function through the module's
    globals, so a shim that rebinds the name (`lib.rs`' `REBOUND`) reaches compiled callers."""
    return fn


def _js_identity(cls):
    return cls


def _js_no_mypyc_attr(*_args, **_kwargs):
    return _js_identity


try:
    from mypy_extensions import mypyc_attr as _mypyc_attr
except ImportError:
    _mypyc_attr = _js_no_mypyc_attr  # type: ignore


class _JsUndefined:
    """`undefined`: one sentinel, distinct from `None` (which is `null`)."""

    __slots__ = ()

    def __repr__(self):
        return "undefined"

    def __bool__(self) -> bool:
        return False


_JS_UNDEFINED: _Final = _JsUndefined()


def _js_is_nullish(value):
    """`value == null`: `null` and `undefined` alike, nothing else."""
    return value is None or value is _JS_UNDEFINED


def _js_typeof(value):
    """`typeof value`. A Python bool is `boolean`, never `number`."""
    # J89-2: the exact types first (a `str` and a `dict` are what JSON rows hold).
    kind = type(value)
    if kind is str:
        return "string"
    if kind is dict or kind is list:
        return "object"
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
    # J90-P: the exact types first, each the answer of its branch below.
    kind = type(value)
    if kind is bool:
        return value
    if kind is str:
        return value != ""
    if kind is int:
        return value != 0
    if kind is list or kind is dict:
        return True
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
_JS_SAFE_MIN: _Final = -(2**53)
_JS_SAFE_MAX: _Final = 2**53


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
    # J90-P2: a plain int a double holds exactly, the general path's answer (True) at once.
    if type(value) is int and _JS_SAFE_MIN <= value <= _JS_SAFE_MAX:
        return True
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
    # J90-PF: a plain int a double holds exactly is its own `_js_num`, so `_js_num_str` below
    # answers `str(value)`; `type(...) is` excludes bool.
    if type(value) is int and _JS_SAFE_MIN <= value <= _JS_SAFE_MAX:
        return str(value)
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
    if isinstance(value, _JS_OBJECT_CLASS):
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
    # J89-2: two floats are two doubles; their IEEE sum is the general path's `_js_num(l + r)`.
    if type(left) is float and type(right) is float:
        return left + right
    if isinstance(left, str) or isinstance(right, str):
        return _js_cat(_js_str(left), _js_str(right))
    if _js_is_number(left) and _js_is_number(right):
        return _js_num(_js_num(left) + _js_num(right))
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        a, b = _js_bigint_operands(left, right)
        return _JsBigInt(a + b)
    raise TypeError("ts2py: + on non-number, non-string operands is outside the subset")


# StrWhiteSpaceChar: WhiteSpace and LineTerminator, what ToNumber trims off a string.
_JS_WHITESPACE: _Final = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_JS_DECIMAL: _Final = _js_re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z", _js_re.ASCII
)
_JS_RADIX: _Final = _js_re.compile(r"0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\Z", _js_re.ASCII)


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
    # J90-P: a plain object (`dict`) read by a `str` key, the general path's dict branch for
    # exactly that pair of types, ahead of every other test.
    if type(obj) is dict and type(key) is str:
        value = obj.get(key, _JS_UNDEFINED)
        if value is _JS_UNDEFINED and key in _JS_OBJECT_PROTO_NAMES and key not in obj:
            raise _js_inherited(key)
        return value
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
        if key in ("index", "input") and isinstance(obj, _JS_MATCH_ARRAY_CLASS):
            return getattr(obj, key)
        if key in _JS_ARRAY_METHODS:
            raise _js_method_value(key)
        return _JS_UNDEFINED
    if obj is None or obj is _JS_UNDEFINED:
        raise TypeError(f"Cannot read properties of {_js_str(obj)} (reading '{_js_str(key)}')")
    if isinstance(obj, _JS_BYTES):
        # J88-2: a Buffer (`bytes`, `bytearray` or a `memoryview` sharing one): `length` and an
        # index in range are the byte; anything else is outside the subset.
        if key == "length":
            return len(obj)
        index = _js_index_key(key)
        if index is not None:
            return obj[index] if 0 <= index < len(obj) else _JS_UNDEFINED
        raise TypeError(f"ts2py: reading {key!r} of a Buffer is outside the subset")
    if isinstance(obj, BaseException) and not isinstance(obj, _JS_OBJECT_CLASS):
        # J88-2: a Python exception a `catch` holds (an adapter's OSError, the runtime's JS-worded
        # TypeError) or a hand-written caller passed. Its `code` is what JS reads: an fs error's is
        # libuv's errno name, the C errno's name CPython records in `errno.errorcode`; any other
        # has none. Every other property (`message`, `errno`, `path`) is spelled differently by
        # Node and CPython, so reading one is outside the subset.
        if key == "code":
            errno = getattr(obj, "errno", None) if isinstance(obj, OSError) else None
            name = _js_errno.errorcode.get(errno) if isinstance(errno, int) else None
            return _JS_UNDEFINED if name is None else name
        raise TypeError(
            f"ts2py: reading {_js_str(key)!r} of a Python exception is outside the subset"
        )
    if isinstance(obj, (_JsMap, _JsSet)) and key == "size":
        return len(obj)
    if isinstance(obj, _JS_OBJECT_CLASS):
        return _js_object_get(obj, key if isinstance(key, str) else _js_str(key))
    if isinstance(key, str) and key in _js_methods_of(obj):
        raise _js_method_value(key)
    return _JS_UNDEFINED


def _js_put(obj, key, value):
    """`obj.key = value` on a plain object. J89-2: `xs[i] = value` on an array, `i` an index
    within it or exactly its length (an append); one past the end would leave a hole, and any
    other key on an array is a property, both outside the subset."""
    if type(obj) is list:
        if type(key) is int and 0 <= key < len(obj):
            obj[key] = value
            return
        index = _js_index_key(key)
        canonical = index is not None and _js_str(index) == _js_str(key)
        if canonical and -1 < index < 2**32 - 1:
            if index < len(obj):
                obj[index] = value
                return
            if index == len(obj):
                obj.append(value)
                return
            raise TypeError("ts2py: an array write past its end (a hole) is outside the subset")
        raise TypeError("ts2py: a property write on an array is outside the subset")
    key = key if isinstance(key, str) else _js_str(key)
    if isinstance(obj, _JS_OBJECT_CLASS):
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
    # J90-P: a plain list first (its element count, the branch below).
    if type(value) is list:
        return len(value)
    if isinstance(value, str):
        # J86-5: one code unit per character of `_js_code_units` (an ASCII string is its own),
        # the count the UTF-16 encoding gives, without encoding the string on every read.
        return len(value) if value.isascii() else len(_js_code_units(value))
    if isinstance(value, (list, _JS_BYTES)):
        return len(value)
    return _js_get(value, "length")


# J87 (#316): helpers for a receiver the compiler PROVED to be a `str` or a `list` (SUBSET.md,
# Types). Each returns exactly what the general helper named in its docstring returns for that
# receiver; it only skips the type dispatch the proof made redundant, and takes the general path for
# any argument its own fast case does not cover.


def _js_is_double(value):
    """The guard of a parameter annotated `number`: an int a double holds exactly, or a float."""
    kind = type(value)
    return kind is float or (kind is int and _JS_SAFE_MIN <= value <= _JS_SAFE_MAX)


def _js_str_len(text):
    """`_js_len(text)` for a `str`: UTF-16 code units."""
    return len(text) if text.isascii() else len(_js_code_units(text))


def _js_str_at(text, key):
    """`_js_get(text, key)` for a `str`: the UTF-16 code unit at a plain int index."""
    if type(key) is int:
        units = text if text.isascii() else _js_code_units(text)
        return units[key] if 0 <= key < len(units) else _JS_UNDEFINED
    return _js_get(text, key)


def _js_units_at(units, text, key):
    """`_js_str_at(text, key)` given `units`, the hoisted `_js_code_units(text)`."""
    if type(key) is int:
        return units[key] if 0 <= key < len(units) else _JS_UNDEFINED
    return _js_get(text, key)


def _js_units_index_of(units, search, position=0):
    """`_js_m_indexOf(text, search, position)` given `units`, the hoisted `_js_code_units(text)`,
    and an ASCII `search` (its own code units)."""
    if type(position) is int:
        return units.find(search, min(max(position, 0), len(units)))
    return units.find(search, int(min(max(_js_to_integer(position), 0), len(units))))


def _js_units_slice(units, start=_JS_UNDEFINED, end=_JS_UNDEFINED):
    """`_js_m_slice(text, start, end)` given `units`, the hoisted `_js_code_units(text)`."""
    length = len(units)
    if type(start) is int and (end is _JS_UNDEFINED or type(end) is int):
        lo = max(length + start, 0) if start < 0 else min(start, length)
        if end is _JS_UNDEFINED:
            hi = length
        else:
            hi = max(length + end, 0) if end < 0 else min(end, length)
    else:
        lo = _js_slice_bound(start, length, 0)
        hi = _js_slice_bound(end, length, length)
    return _js_from_units(units[lo:hi])


def _js_list_join(items, separator):
    """`_js_m_join(items, separator)` for a `list` and a `str` separator: when every element is a
    `str` (the only elements `str.join` accepts), joining them is the same join."""
    try:
        joined = separator.join(items)
    except TypeError:
        return _js_m_join(items, separator)
    return _js_from_units(joined)


def _js_re_exec(pattern, text):
    """`_js_m_exec(pattern, text)` for a regex literal and a `str`; an ASCII subject is its own code
    units and every group of it is its own canonical spelling."""
    if not text.isascii():
        return _js_m_exec(pattern, text)
    match = pattern.search(text)
    if match is None:
        return None
    out = _JsMatchArray(
        _JS_UNDEFINED if group is None else group for group in [match.group(0), *match.groups()]
    )
    out.index = match.start()
    out.input = text
    return out


def _js_re_replace(text, pattern, replacement):
    """`_js_m_replace(text, pattern, replacement)` for a `str`, a regex literal (no `g`) and a
    literal replacement holding neither `$` nor a backslash, which `re.sub` inserts as it is."""
    units = text if text.isascii() else _js_code_units(text)
    return _js_from_units(pattern.sub(replacement, units, count=1))


def _js_list_at(items, key):
    """`_js_get(items, key)` for a `list`: the element at a plain int index."""
    if type(key) is int:
        return items[key] if 0 <= key < len(items) else _JS_UNDEFINED
    return _js_get(items, key)


def _js_str_includes(text, search):
    """`_js_m_includes(text, search)` for two `str`s: by UTF-16 code unit."""
    if text.isascii() and search.isascii():
        return search in text
    return _js_code_units(search) in _js_code_units(text)


def _js_str_starts_with(text, prefix):
    """`_js_m_startsWith(text, prefix)` for two `str`s."""
    if text.isascii() and prefix.isascii():
        return text.startswith(prefix)
    return _js_code_units(text).startswith(_js_code_units(prefix))


def _js_str_index_of(text, search, position=0):
    """`_js_m_indexOf(text, search, position)` for two `str`s (a missing position is 0, which is
    what ToIntegerOrInfinity makes of `undefined`)."""
    if type(position) is int and text.isascii() and search.isascii():
        return text.find(search, min(max(position, 0), len(text)))
    return _js_m_indexOf(text, search, position)


def _js_str_slice(text, start=_JS_UNDEFINED, end=_JS_UNDEFINED):
    """`_js_m_slice(text, start, end)` for a `str`; an ASCII string cut at plain int bounds is its
    own code units, so the cut is Python's."""
    if (
        text.isascii()
        and type(start) is int
        and (end is _JS_UNDEFINED or type(end) is int)
    ):
        length = len(text)
        lo = max(length + start, 0) if start < 0 else min(start, length)
        if end is _JS_UNDEFINED:
            hi = length
        else:
            hi = max(length + end, 0) if end < 0 else min(end, length)
        return text[lo:hi]
    return _js_m_slice(text, start, end)


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

    J90-RF2: `-0` is the key `0`. SameValueZero already finds one under the other (Python's
    `-0.0 == 0`), but a Map or Set also STORES `+0` for a `-0` key (ECMA-262 `Map.prototype.set`
    and `Set.prototype.add`, step "If key is -0, set key to +0"), so `[...m.keys()]` gives `0`.
    The tag of `-0.0` is the int `0`, and `set` / `add` store the tag as the key whenever the tag
    is an int that is not the key itself (only `-0.0` gives one).
    """
    # J90-P: a `str` is its own key, and so is a plain int a double holds exactly (`_js_num`
    # returns it unchanged); `type(...) is` excludes bool and every subclass.
    kind = type(key)
    if kind is str or (kind is int and _JS_SAFE_MIN <= key <= _JS_SAFE_MAX):
        return key
    if kind is float:
        if key != key:
            return (_JsMap, "NaN")
        if key == 0.0 and _js_math.copysign(1.0, key) < 0.0:
            return 0
        return key
    if isinstance(key, bool):
        return (_JsMap, key)
    if isinstance(key, float) and key != key:
        return (_JsMap, "NaN")
    if isinstance(key, int):
        return _js_num(key)
    if isinstance(key, (list, dict)):
        return (_JsSet, id(key))
    return key


@_mypyc_attr(allow_interpreted_subclasses=True)
class _JsMap:
    """`Map`: insertion-ordered, keyed by SameValueZero, missing key reads as `undefined`.

    J90-P: `_entries` maps each key's `_js_key` tag to its value. A key that is its own tag (a
    string, a number, `null`, an instance) is the dict's key itself; any other (a bool, NaN, an
    array or object, an int past 2^53) is kept in `_keys` beside it, by tag, as first set.
    `_keys` is `_JS_REORDER` while `_entries` holds the right entries in a pending order (a Map
    built from an object whose array-index keys come first in JS): the first iteration or write
    puts them in `_js_own_keys`' order (`_settle`); a read by key needs no order."""

    __slots__ = ("_entries", "_keys")

    def __init__(self, entries=None):
        self._entries = {}
        self._keys = None
        # J90-P: a list of `[str, value, ...]` lists (what `Object.entries` of a plain object
        # makes) at C speed: the loop below's answer for exactly those entries, a repeated key
        # keeping its first position and its last value.
        if (
            type(entries) is list
            and entries
            and set(map(type, entries)) == _JS_LIST_ONLY
            and min(map(len, entries)) >= 2
        ):
            keys = list(map(_js_item0, entries))
            if set(map(type, keys)) == _JS_STR_ONLY:
                self._entries = dict(zip(keys, map(_js_item1, entries), strict=False))
                return
        if entries is not None:
            held = self._entries
            for entry in entries:
                # J90-2: a `[key, value]` list with a string key, the common entry, set inline (a
                # string is its own `_js_key`); anything else through `set`, as before.
                if type(entry) is list and len(entry) >= 2 and type(entry[0]) is str:
                    held[entry[0]] = entry[1]
                else:
                    self.set(_js_get(entry, 0), _js_get(entry, 1))

    def has(self, key):
        return _js_key(key) in self._entries

    def get(self, key):
        return self._entries.get(_js_key(key), _JS_UNDEFINED)

    def _settle(self):
        entries = self._entries
        keys = _js_own_keys(entries)
        self._entries = dict(zip(keys, map(entries.__getitem__, keys), strict=False))
        self._keys = None

    def set(self, key, value):
        if self._keys is _JS_REORDER:
            self._settle()
        tag = _js_key(key)
        entries = self._entries
        if tag is not key and type(tag) is int:
            # J90-RF2: `-0.0`, whose tag `0` is the key JS stores. Nothing goes in `_keys`, and a
            # key `0.0` the dict already holds stays its key (it prints as `0` too).
            key = tag
        elif tag is not key and tag not in entries:
            if self._keys is None:
                self._keys = {}
            self._keys[tag] = key
        entries[tag] = value
        return self

    def delete(self, key):
        # J90-2: `Map.prototype.delete`: whether the key was there. A later `set` of it appends.
        if self._keys is _JS_REORDER:
            self._settle()
        tag = _js_key(key)
        if self._keys is not None:
            self._keys.pop(tag, None)
        return self._entries.pop(tag, _JS_ABSENT) is not _JS_ABSENT

    def __len__(self):
        return len(self._entries)

    def __iter__(self):
        # J90-2: an entry deleted before the loop reaches it is not visited, and one whose value
        # was set meanwhile is visited with that value, as a JS Map iterator does (entries added
        # during the loop are still not visited: Known limits in SUBSET.md).
        if self._keys is _JS_REORDER:
            self._settle()
        entries = self._entries
        keys = self._keys
        for tag in list(entries):
            value = entries.get(tag, _JS_ABSENT)
            if value is not _JS_ABSENT:
                yield [tag if keys is None else keys.get(tag, tag), value]


_JS_ABSENT: _Final = object()
_JS_REORDER: _Final = object()


class _JsSet:
    """`Set`: insertion-ordered, SameValueZero membership."""

    __slots__ = ("_items",)

    def __init__(self, items=None):
        self._items = {}
        # J90-P4: a list of `str`s (each its own `_js_key`) at once: the loop's dict, a repeated
        # string keeping its first position (its value an equal string).
        if type(items) is list and set(map(type, items)) <= _JS_STR_ONLY:
            self._items = dict(zip(items, items, strict=True))
            return
        if items is not None:
            for item in items:
                self.add(item)

    def has(self, item):
        return _js_key(item) in self._items

    def add(self, item):
        tag = _js_key(item)
        # J90-RF2: a `-0.0` item is stored as `0`, its tag (the only int tag that is not the item).
        self._items.setdefault(tag, tag if tag is not item and type(tag) is int else item)
        return self

    def delete(self, item):
        # J90-2: `Set.prototype.delete`: whether the item was there.
        tag = _js_key(item)
        if tag in self._items:
            del self._items[tag]
            return True
        return False

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        # J90-2: an item deleted before the loop reaches it is not visited, as in JS.
        items = self._items
        for tag in list(items):
            if tag in items:
                yield items[tag]


def _js_outside(method, receiver):
    return TypeError(f"ts2py: .{method}() on {type(receiver).__name__} is outside the subset")


def _js_m_has(receiver, key):
    # J90-P: a `str` key is its own `_js_key`, so the lookup is the dict's. J90-PF: so is a plain
    # int a double holds exactly (`_js_key` returns it as it is).
    if type(key) is str or (type(key) is int and _JS_SAFE_MIN <= key <= _JS_SAFE_MAX):
        kind = type(receiver)
        if kind is _JsMap:
            return key in receiver._entries
        if kind is _JsSet:
            return key in receiver._items
    if isinstance(receiver, (_JsMap, _JsSet)):
        return receiver.has(key)
    raise _js_outside("has", receiver)


def _js_m_delete(receiver, key):
    """J90-2: `m.delete(k)` on a Map or a Set."""
    if isinstance(receiver, (_JsMap, _JsSet)):
        return receiver.delete(key)
    raise _js_outside("delete", receiver)


def _js_m_get(receiver, key):
    # J90-P: `_JsMap.get` inline for a `str` key (its own `_js_key`). J90-PF: and a plain int a
    # double holds exactly, also its own `_js_key`.
    if type(receiver) is _JsMap and (
        type(key) is str or (type(key) is int and _JS_SAFE_MIN <= key <= _JS_SAFE_MAX)
    ):
        return receiver._entries.get(key, _JS_UNDEFINED)
    if isinstance(receiver, _JsMap):
        return receiver.get(key)
    raise _js_outside("get", receiver)


def _js_m_set(receiver, key, value):
    # J90-P: `_JsMap.set` inline for a `str` key (its own `_js_key`). J90-PF: and a plain int a
    # double holds exactly, also its own `_js_key` (so `set` would keep nothing in `_keys`).
    if (
        type(receiver) is _JsMap
        and (type(key) is str or (type(key) is int and _JS_SAFE_MIN <= key <= _JS_SAFE_MAX))
        and receiver._keys is None
    ):
        receiver._entries[key] = value
        return receiver
    if isinstance(receiver, _JsMap):
        return receiver.set(key, value)
    raise _js_outside("set", receiver)


def _js_m_add(receiver, item):
    # J90-P: `_JsSet.add` inline for a `str` item (its own `_js_key`).
    if type(receiver) is _JsSet and type(item) is str:
        receiver._items.setdefault(item, item)
        return receiver
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
    if isinstance(receiver, str) and isinstance(separator, (_js_re.Pattern, _JsGlobalRegExp)):
        return _js_split_regex(receiver, separator)
    if isinstance(receiver, str) and isinstance(separator, str):
        if receiver.isascii() and separator.isascii():
            return list(receiver) if separator == "" else receiver.split(separator)
        # J86: by UTF-16 code unit, so `""` splits an astral character into its two surrogates
        # and a separator that is half of a pair is found inside one, as in JS.
        units = _js_code_units(receiver)
        if separator == "":
            return list(units)
        parts = units.split(_js_code_units(separator))
        # J89-2: with no surrogate anywhere in the units, every part is already canonical
        # (`_js_from_units` would return it unchanged), so the per-part pass is skipped.
        if _JS_SURROGATE.search(units) is None:
            return parts
        return [_js_from_units(part) for part in parts]
    raise _js_outside("split", receiver)


def _js_split_regex(text, separator):
    """`s.split(re)` (J89-5c): ECMA-262's `RegExp.prototype[@@split]` with no limit, over UTF-16
    code units. The splitter is tried at each position `q` from the end of the last piece (Python's
    `search(units, q)` finds the first `q` it matches at, the same match a sticky `exec` there
    finds); a match ending where the last piece ended (an empty one there) moves on one unit, and
    one starting at the end of the string is never taken. Each capture group joins the result
    after its piece (`undefined` for one that did not take part). An empty string is `[]` when the
    splitter matches it, else `[""]`. A `g` flag changes nothing (JS builds its own sticky
    splitter)."""
    pattern = separator.pattern if isinstance(separator, _JsGlobalRegExp) else separator
    units = _js_code_units(text)
    size = len(units)
    if size == 0:
        return [] if pattern.match(units, 0) is not None else [text]
    out = []
    p = q = 0
    while q < size:
        m = pattern.search(units, q)
        if m is None or m.start() >= size:
            break
        q = m.start()
        e = min(m.end(), size)
        if e == p:
            q += 1
            continue
        out.append(_js_from_units(units[p:q]))
        out.extend(_JS_UNDEFINED if g is None else _js_from_units(g) for g in m.groups())
        p = q = e
    out.append(_js_from_units(units[p:]))
    return out


# J86-5: `_js_code_units` of a non-ASCII string, remembered. The answer is a function of the
# string's value alone, so a remembered one is the one a fresh computation gives; the scanners
# index one string thousands of times, and each read recomputed it (an O(n) `max`) before.
# Bounded: cleared when full, and a long string is never kept.
_JS_UNITS: dict = {}
_JS_UNITS_ENTRIES: _Final = 512
_JS_UNITS_LONGEST: _Final = 1 << 16


def _js_code_units(text):
    """`text` with every astral character split into its two surrogates: the string as a JS regex
    without the `u` flag sees it, one UTF-16 code unit per Python character."""
    # J90-3: a string longer than `_JS_UNITS_LONGEST` is held by IDENTITY, the last one only: a
    # loop over one long text that is not ASCII (`charCodeAt` / `slice` at every index, the
    # tokenizer over an archived job's text) rescanned it at every call, quadratic (a 640 KB job
    # did not finish in 40 s). A str is immutable, so the same object has the same units; the pair
    # is replaced whole.
    held = _JS_UNITS_LAST[0]
    if text is held[0]:
        return held[1]
    if text.isascii():
        return text
    units = _JS_UNITS.get(text)
    if units is None:
        units = _js_code_units_of(text)
        if len(text) <= _JS_UNITS_LONGEST:
            if len(_JS_UNITS) >= _JS_UNITS_ENTRIES:
                _JS_UNITS.clear()
            _JS_UNITS[text] = units
        else:
            _JS_UNITS_LAST[0] = (text, units)
    return units


_JS_UNITS_LAST: _Final = [(None, "")]


def _js_code_units_of(text):
    # J90-P: a string with no astral character is its own code units. CPython stores a str in the
    # narrowest of three widths that holds its largest character, so one stored 4 bytes wide is
    # exactly one that holds an astral character: its size answers at once (`_JS_STR_WIDTH`,
    # checked when the runtime loads), where `max(text)` reads every character.
    if _JS_STR_WIDTH is not None:
        if _js_sys.getsizeof(text) - _JS_STR_WIDTH < 4 * (len(text) + 1):
            return text
    elif max(text) < "\U00010000":
        return text
    # Each astral character as its surrogate pair; the rest kept, at C speed.
    return _JS_ASTRAL.sub(_js_surrogates, text)


def _js_surrogates(match):
    code = ord(match.group()) - 0x10000
    return chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF))


_JS_ASTRAL: _Final = _js_re.compile("[\U00010000-\U0010FFFF]")


def _js_str_width():
    """The header size of a compact non-ASCII str when `sys.getsizeof` measures one as that
    header plus `(len + 1) * width` (1, 2 or 4 bytes a character), else None (and `max` decides).
    A str that also caches its UTF-8 bytes measures larger, never smaller, so a size below the
    4-byte width's is always a narrower str."""
    try:
        if _js_sys.implementation.name != "cpython":
            return None
        head = _js_sys.getsizeof("".join(["\u0100", "\u0101", "\u0102"])) - 2 * 4
        samples = (
            ("".join(["\x80", "\x81", "\xff"]), 1),
            ("".join(["\u0100", "\uffff", "\x80", "a"]), 2),
            ("".join(["\U00010000", "\u0100"]), 4),
            ("".join(["a", "\U0010ffff", "b", "c"]), 4),
        )
        for sample, width in samples:
            if _js_sys.getsizeof(sample) - head != width * (len(sample) + 1):
                return None
        return head
    except (AttributeError, TypeError, ValueError):
        return None


_JS_STR_WIDTH: _Final = _js_str_width()


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


def _js_every_integer(receiver):
    """J90-2: `xs.every((x) => Number.isInteger(x))`. A list of Python ints only (no bool: its
    type is `bool`) is answered at once, every int being an integral JS number; any other list
    runs `Number.isInteger` on each element, as `_js_m_every` would with that callback."""
    items = _js_array("every", receiver)
    if set(map(type, items)) <= _JS_INT_ONLY:
        return True
    return all(_js_number_is_integer(item) for item in items)


def _js_every_string(receiver):
    """J90-2: `xs.every((x) => typeof x === 'string')`: a list of Python `str` only is answered at
    once; any other list runs `typeof` on each element, as `_js_m_every` would."""
    items = _js_array("every", receiver)
    if set(map(type, items)) <= _JS_STR_ONLY:
        return True
    return all(_js_typeof(item) == "string" for item in items)


_JS_INT_ONLY: _Final = frozenset({int})
_JS_LIST_ONLY: _Final = frozenset({list})
_js_item0 = _js_operator.itemgetter(0)
_js_item1 = _js_operator.itemgetter(1)
_JS_STR_ONLY: _Final = frozenset({str})


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
    # J90-P: a `str` cut at plain int bounds (or to its end): `_js_slice_bound` inline. An ASCII
    # string is its own code units and every cut of it is canonical.
    if type(receiver) is str and type(start) is int and (end is _JS_UNDEFINED or type(end) is int):
        ascii_ = receiver.isascii()
        units = receiver if ascii_ else _js_code_units(receiver)
        length = len(units)
        lo = max(length + start, 0) if start < 0 else min(start, length)
        if end is _JS_UNDEFINED:
            hi = length
        else:
            hi = max(length + end, 0) if end < 0 else min(end, length)
        return units[lo:hi] if ascii_ else _js_from_units(units[lo:hi])
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
    elif getattr(compare, "_js_codepoint_order", False) and all(type(x) is str for x in present):
        # J89-5: a comparator that IS code-point order on strings (`cmpCodepoint`'s adapter says
        # so) sorts strings exactly as Python's own `<` on `str` does; both sorts are stable and
        # two strings it ties are equal, so the order is the same and the comparator never runs.
        present.sort()
    else:
        # J90-P2: V8's own sort (`_js_v8_timsort`), so a comparator that is not a consistent order
        # (a NaN key, a comparator of the two values' parity) leaves V8's order, not CPython's.

        def order(left, right):
            result = compare(left, right)
            if isinstance(result, bool):
                result = int(result)
            if not _js_is_number(result) or result != result:
                return 0
            return result

        _js_v8_timsort(present, order)
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
    keys = list(obj)
    if not set(map(type, keys)) <= _JS_STR_ONLY:
        keys = [key if isinstance(key, str) else _js_str(key) for key in keys]
    # J90-P: an array index is a canonical decimal (`0`, or ASCII digits not starting with `0`),
    # so only a key made of digits can be one; none, and the insertion order stands.
    indices = list(filter(str.isascii, filter(str.isdigit, keys)))
    if not indices:
        return keys
    # Sorted as text, the ones with a leading `0` come first, before "1"; of those only "0"
    # itself is canonical (and sorts first of them). Numeric order of canonical decimals is
    # length, then text: a second, stable sort by length. A canonical decimal of at most 9
    # digits is below 2^32 - 1.
    indices.sort()
    cut = _js_bisect.bisect_left(indices, "1")
    indices = (["0"] if cut and indices[0] == "0" else []) + indices[cut:]
    if indices and max(map(len, indices)) > 9:
        indices = [key for key in indices if int(key) < 2**32 - 1]
    indices.sort(key=len)
    chosen = set(indices)
    return indices + list(_js_itertools.filterfalse(chosen.__contains__, keys))


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


_JS_JSON_PLAIN: _Final = frozenset({str, bool, type(None), int, list})


def _js_json_plain(values):
    """J90-PF: whether every value of `values` (a list) is a string, a boolean, null, a safe int
    (within 2^53) or a list of such, at any depth (64 levels at most, and no list twice in one
    level, so a list holding itself answers False and each level holds distinct lists). Checked a
    level at a time over all the values at once, at C speed. For such a
    value `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` writes `_js_json`'s text
    but for a lone surrogate, which `_js_json_quote` escapes and `json.dumps` keeps (the caller
    checks the text for one): the same escapes (`\\"`, `\\\\`, `\\b\\f\\n\\r\\t`, `\\u00xx` for
    the other controls, lower-case hex), every other character as it is, `true` / `false` /
    `null`, an int's digits. A float (JS spells numbers its own way), a dict (JS orders an
    index-like key first), anything else answers False."""
    for _ in range(64):
        kinds = set(map(type, values))
        if not kinds <= _JS_JSON_PLAIN:
            return False
        if int in kinds:
            ints = values if kinds == _JS_INT_ONLY else [v for v in values if type(v) is int]
            if not (_JS_SAFE_MIN <= min(ints) and max(ints) <= _JS_SAFE_MAX):
                return False
        if list not in kinds:
            return True
        lists = [v for v in values if type(v) is list]
        if len(set(map(id, lists))) != len(lists):
            return False
        values = list(_js_itertools.chain.from_iterable(lists))
    return False


def _js_json_stringify(value):
    """`JSON.stringify(value)`, byte for byte, for JSON-shaped values (and `undefined`)."""
    # J90-PF: a list of plain values (`_js_json_plain`) at C speed; a text holding a lone
    # surrogate (which strict UTF-8 refuses) is `_js_json`'s, which escapes it as JS does.
    if type(value) is list and _js_json_plain(value):
        text = _js_jsonlib.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            pass
        else:
            return text
    text = _js_json(value)
    return _JS_UNDEFINED if text is None else text


# ---------------------------------------------------------------- J86: strings as UTF-16

_JS_SURROGATE: _Final = _js_re.compile("[\\ud800-\\udfff]")
# J90-P7: no lone surrogate is spelled as a literal (mypyc writes literals as UTF-8, which has none).
_JS_LEAD_MIN: _Final = chr(0xD800)
_JS_LEAD_MAX: _Final = chr(0xDBFF)
_JS_TRAIL_MIN: _Final = chr(0xDC00)
_JS_TRAIL_MAX: _Final = chr(0xDFFF)


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
    if (
        left
        and right
        and _JS_LEAD_MIN <= left[-1] <= _JS_LEAD_MAX
        and _JS_TRAIL_MIN <= right[0] <= _JS_TRAIL_MAX
    ):
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
    """`s.indexOf(search, position)` in UTF-16 code units (strings only). J89-2: also
    `buf.indexOf(byte, offset)` on a Buffer, `byte` a number."""
    if isinstance(receiver, _JS_BYTES):
        return _js_buffer_index_of(receiver, search, position)
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


# J88-2 / J89-7: the code points whose lowercase CPython and Node 26.13 (ICU, Unicode 17.0) spell
# differently, measured over every code point but the surrogates: 55 on CPython 3.11, 3.12 and
# 3.13 (28 on 3.14), every one unassigned (`Cn`) in CPython's table and every one a single code
# point to a single code point. The table is Node's answer for all 55, so `str.lower()` after it
# is Node's answer whatever CPython's Unicode version is.
_JS_LOWER_NODE: _Final = {
    0x1C89: 0x1C8A, 0xA7CB: 0x0264, 0xA7CC: 0xA7CD, 0xA7CE: 0xA7CF, 0xA7D2: 0xA7D3,
    0xA7D4: 0xA7D5, 0xA7DA: 0xA7DB, 0xA7DC: 0x019B,
    **{cp: cp + 0x20 for cp in range(0x10D50, 0x10D66)},
    **{cp: cp + 0x1B for cp in range(0x16EA0, 0x16EB9)},
}
# J89-7b: those 55 as a precompiled class of ranges (a class of 55 single astral code points is
# slower to search than `str.translate`), so a string without one never pays for `translate`.
_JS_LOWER_NODE_FIND: _Final = _js_re.compile(
    "[\u1c89\ua7cb\ua7cc\ua7ce\ua7d2\ua7d4\ua7da\ua7dc\U00010d50-\U00010d65\U00016ea0-\U00016eb8]"
).search
# J89-7 / J89-7b: U+03A3 lowers to U+03C2 or U+03C3 by its Final_Sigma context: walk out from it
# over Case_Ignorable code points to the first that is not, and ask whether that one is Cased. The
# two tables classify a code point apart in 307 places on CPython 3.11, 196 on 3.12 and 3.13 and
# 100 on 3.14 (each a subset of 3.11's; J89-7b's sweep of every code point, Node 26.13 against each
# interpreter, probing both walk directions: symmetric on every side). Those 307 carry Node's class
# here, as code point ranges: 1 Case_Ignorable, 2 Cased (and not Case_Ignorable); U+0295 and
# U+1171E are neither to Node. Every other code point is classed by CPython's own `str.lower()`.
_JS_SIGMA_NODE: dict = {}
for _js_first, _js_last, _js_class in (
    (0x0897, 0x0897, 1), (0x0ECE, 0x0ECE, 1), (0x1ACF, 0x1ADD, 1), (0x1AE0, 0x1AEB, 1),
    (0xA7F1, 0xA7F1, 1), (0x10D4E, 0x10D4E, 1), (0x10D69, 0x10D6D, 1), (0x10D6F, 0x10D6F, 1),
    (0x10EC5, 0x10EC5, 1), (0x10EFA, 0x10EFF, 1), (0x11241, 0x11241, 1), (0x113BB, 0x113C0, 1),
    (0x113CE, 0x113CE, 1), (0x113D0, 0x113D0, 1), (0x113D2, 0x113D2, 1), (0x113E1, 0x113E2, 1),
    (0x11B60, 0x11B60, 1), (0x11B62, 0x11B64, 1), (0x11B66, 0x11B66, 1), (0x11DD9, 0x11DD9, 1),
    (0x11F00, 0x11F01, 1), (0x11F36, 0x11F3A, 1), (0x11F40, 0x11F40, 1), (0x11F42, 0x11F42, 1),
    (0x11F5A, 0x11F5A, 1), (0x13439, 0x13440, 1), (0x13447, 0x13455, 1), (0x1611E, 0x16129, 1),
    (0x1612D, 0x1612F, 1), (0x16D40, 0x16D42, 1), (0x16D6B, 0x16D6C, 1), (0x16FF2, 0x16FF3, 1),
    (0x1E030, 0x1E06D, 1), (0x1E08F, 0x1E08F, 1), (0x1E4EB, 0x1E4EF, 1), (0x1E5EE, 0x1E5EF, 1),
    (0x1E6E3, 0x1E6E3, 1), (0x1E6E6, 0x1E6E6, 1), (0x1E6EE, 0x1E6EF, 1), (0x1E6F5, 0x1E6F5, 1),
    (0x1E6FF, 0x1E6FF, 1),
    (0x1C89, 0x1C8A, 2), (0xA7CB, 0xA7CF, 2), (0xA7D2, 0xA7D2, 2), (0xA7D4, 0xA7D4, 2),
    (0xA7DA, 0xA7DC, 2), (0x10D50, 0x10D65, 2), (0x10D70, 0x10D85, 2), (0x16EA0, 0x16EB8, 2),
    (0x16EBB, 0x16ED3, 2), (0x1DF25, 0x1DF2A, 2),
    (0x0295, 0x0295, 0), (0x1171E, 0x1171E, 0),
):
    for _js_cp in range(_js_first, _js_last + 1):
        _JS_SIGMA_NODE[chr(_js_cp)] = _js_class
del _js_first, _js_last, _js_class, _js_cp


@_js_functools.lru_cache(maxsize=4096)
def _js_sigma_class(ch):
    """Node's class of `ch` for the Final_Sigma walk: 1 Case_Ignorable, 2 Cased, 0 neither. Off
    the table, CPython's own, read back off `str.lower()`: skipped when U+03A3 after it is final
    behind a cased letter and not behind a space, Cased when it alone makes U+03A3 final."""
    known = _JS_SIGMA_NODE.get(ch)
    if known is not None:
        return known
    behind_cased = ("A" + ch + "\u03a3").lower()[-1] == "\u03c2"
    behind_space = (" " + ch + "\u03a3").lower()[-1] == "\u03c2"
    if behind_cased and not behind_space:
        return 1
    return 2 if behind_space else 0


def _js_final_sigma(text, at):
    """Unicode's Final_Sigma for the U+03A3 at `at`: a Cased code point before it, past any
    Case_Ignorable ones, and none after it, past the same."""
    j = at - 1
    while j >= 0 and _js_sigma_class(text[j]) == 1:
        j -= 1
    if j < 0 or _js_sigma_class(text[j]) != 2:
        return False
    j = at + 1
    while j < len(text) and _js_sigma_class(text[j]) == 1:
        j += 1
    return j == len(text) or _js_sigma_class(text[j]) != 2


def _js_lower_no_sigma(text):
    """`toLowerCase()` of text holding no U+03A3: context-free on both sides, so the 55 first."""
    if _JS_LOWER_NODE_FIND(text) is not None:
        text = text.translate(_JS_LOWER_NODE)
    return text.lower()


def _js_m_toLowerCase(receiver):
    """`s.toLowerCase()`: full Unicode lowercase mapping, Final_Sigma included. Outside U+03A3
    both sides lower one code point at a time, and `str.lower()` is Node's answer for every one
    but the 55 `_JS_LOWER_NODE` maps first. Each U+03A3 is lowered here, by the Final_Sigma walk
    over Node's classes (J89-7b: never refused; 0 answers apart from Node 26.13 over every code
    point alone and in eleven sigma contexts, on CPython 3.11 to 3.14)."""
    text = _js_string_receiver("toLowerCase", receiver)
    if text.isascii():
        return text.lower()
    if "\u03a3" not in text:
        return _js_lower_no_sigma(text)
    parts = text.split("\u03a3")
    out = [_js_lower_no_sigma(parts[0])]
    at = len(parts[0])
    for part in parts[1:]:
        out.append("\u03c2" if _js_final_sigma(text, at) else "\u03c3")
        out.append(_js_lower_no_sigma(part))
        at += 1 + len(part)
    return "".join(out)


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


@_mypyc_attr(native_class=False)
class _JsMatchArray(list):
    """What `re.exec(s)` returns: the match and its groups (`undefined` for one that did not take
    part), plus `index` (a UTF-16 position) and `input`."""

    __slots__ = ("index", "input")


# J90-P7: compiled, `isinstance(x, C)` of a non-native class C tests the exact type only (mypyc
# 2.4.1 takes it for a native one), so it misses every subclass; through a `type` variable it is
# the builtin. The runtime's isinstance of these classes reads these variables.
_JS_MATCH_ARRAY_CLASS: type = _JsMatchArray


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


_JS_DYNAMIC_RE: dict = {}


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

_JS_INFINITY: _Final = _js_math.inf
_JS_NAN: _Final = _js_math.nan


def _js_double_out(value):
    """A float result back in the int-when-exact spelling: an integral finite value within 2^53
    becomes an `int`, except -0, which only a float can hold."""
    # J89-2: the common case first, the same test in a cheaper order (a non-integral float, NaN
    # and the infinities are not `is_integer()`).
    if type(value) is float:
        if not value.is_integer() or not -9007199254740992.0 <= value <= 9007199254740992.0:
            return value
        if value == 0 and _js_math.copysign(1.0, value) < 0:
            return value
        return int(value)
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
    # J89-2: the general path's answer for two floats, or two non-zero ints in the exact range.
    kind = type(left)
    if kind is float and type(right) is float:
        product = left * right
        # J89-3: a product that is not integral (NaN and the infinities included) is what
        # `_js_double_out` returns unchanged.
        if not product.is_integer():
            return product
        return _js_double_out(product)
    if (
        kind is int
        and type(right) is int
        and left
        and right
        and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX
        and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX
    ):
        return _js_num(left * right)
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
    # J89-2: the general path's answer for two numbers that are floats or ints in the exact range,
    # the divisor not zero.
    kind, other = type(left), type(right)
    if (
        (kind is float or (kind is int and _JS_SAFE_MIN <= left <= _JS_SAFE_MAX))
        and (other is float or (other is int and _JS_SAFE_MIN <= right <= _JS_SAFE_MAX))
        and right != 0
    ):
        return _js_double_out(float(left) / float(right))
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
    # J89-2: a non-negative int over a positive one, both in the exact range: Python's `%` is the
    # remainder the general path's `fmod` computes exactly.
    if (
        type(left) is int
        and type(right) is int
        and 0 <= left <= _JS_SAFE_MAX
        and 0 < right <= _JS_SAFE_MAX
    ):
        return left % right
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
    # J89-2: an int in the exact range is its own floor (`_js_math_arg` returns it unchanged), and
    # a float is its own ToNumber, so the general path's answer is read straight off it.
    kind = type(value)
    if kind is int and _JS_SAFE_MIN <= value <= _JS_SAFE_MAX:
        return value
    if kind is float:
        if value != value or value in (_js_math.inf, -_js_math.inf) or value == 0:
            return value
        return _js_math.floor(value)
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


def _js_number_pair(values):
    """J89-2: True for exactly two operands that are floats or ints in the exact range (each its
    own ToNumber), neither NaN and not both zero (where the sign of a zero decides)."""
    if len(values) != 2:
        return False
    a, b = values
    for v in (a, b):
        kind = type(v)
        if kind is float:
            if v != v:
                return False
        elif not (kind is int and _JS_SAFE_MIN <= v <= _JS_SAFE_MAX):
            return False
    return not (a == 0 and b == 0)


def _js_max(*values):
    """`Math.max`: any NaN is NaN, +0 beats -0, no argument is -Infinity."""
    # J89-2: `_js_extreme` keeps the first of two equal values, as Python's `max` does.
    if _js_number_pair(values):
        return max(values)
    return _js_extreme(values, True)


def _js_min(*values):
    """`Math.min`: any NaN is NaN, -0 beats +0, no argument is Infinity."""
    if _js_number_pair(values):
        return min(values)
    return _js_extreme(values, False)


def _js_number(value=0):
    """`Number(value)`: ToNumeric, and a BigInt converts to the nearest double."""
    # J89-2: a string of at most 15 ASCII digits is the int it spells (StringToNumber reads it as
    # that double exactly, and `_js_double_out` answers the int).
    if type(value) is str and 0 < len(value) <= 15 and value.isascii() and value.isdigit():
        return int(value)
    value = _js_to_numeric(value)
    if isinstance(value, _JsBigInt):
        return _js_num(value.value)
    return _js_double_out(value) if isinstance(value, float) else value


def _js_number_is_nan(value):
    """`Number.isNaN`: a number that is NaN; nothing else, no coercion."""
    return isinstance(value, float) and value != value


_JS_DIGITS: _Final = "0123456789abcdefghijklmnopqrstuvwxyz"


def _js_parse_int(text, radix=_JS_UNDEFINED):
    """`parseInt(text, radix)`: leading JS whitespace and a sign, then the longest run of digits in
    the radix (16 also accepts a `0x` prefix; radix 0 or missing reads `0x` as 16, else 10). No
    digit is NaN. A run whose value is past 2^53 in a radix other than 10 or a power of two is
    outside the subset (V8 rounds those approximately)."""
    # J90-P: a string of ASCII hex digits only, radix 16 (`sha256(...).slice(0, 8)`): no blank,
    # sign or `0x` to read past, every character a digit, so the run is the whole string.
    if (
        type(text) is str
        and type(radix) is int
        and radix == 16
        and text
        and text.isascii()
        and not text.strip(_JS_HEX_DIGITS)
    ):
        return _js_num(int(text, 16))
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


_JS_HEX_DIGITS: _Final = "0123456789abcdefABCDEF"


_JS_STR_INT_CAP: _Final = 10**4000


def _js_int_to_radix(value, radix):
    if value == 0:
        return "0"
    # J90-P4: base 10 is `str` (the loop's digits for exactly these ints; below the digit cap
    # CPython puts on `str(int)`, which JS does not have).
    if radix == 10 and -_JS_STR_INT_CAP < value < _JS_STR_INT_CAP:
        return str(value)
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
    if isinstance(receiver, _JS_OBJECT_CLASS):
        return _js_object_to_string(receiver)
    if isinstance(receiver, _JS_BYTES):
        return _js_buffer_to_string(receiver, radix)
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


_JS_BIGINT_TEXT: _Final = _js_re.compile(
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

_JS_OBJECT_PROTO_NAMES: _Final = frozenset(
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
_JS_STRING_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset(
    "anchor at big blink bold charAt charCodeAt codePointAt concat endsWith fixed fontcolor "
    "fontsize includes indexOf isWellFormed italics lastIndexOf link localeCompare match matchAll "
    "normalize padEnd padStart repeat replace replaceAll search slice small split startsWith "
    "strike sub substr substring sup toLocaleLowerCase toLocaleUpperCase toLowerCase toUpperCase "
    "toWellFormed trim trimEnd trimLeft trimRight trimStart".split()
)
_JS_ARRAY_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset(
    "at concat copyWithin entries every fill filter find findIndex findLast findLastIndex flat "
    "flatMap forEach includes indexOf join keys lastIndexOf map pop push reduce reduceRight "
    "reverse shift slice some sort splice toReversed toSorted toSpliced unshift values with".split()
)
_JS_MAP_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset(
    "clear delete entries forEach get has keys set values".split()
)
_JS_SET_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset(
    "add clear delete difference entries forEach has intersection isDisjointFrom isSubsetOf "
    "isSupersetOf keys symmetricDifference union values".split()
)
_JS_NUMBER_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset(
    "toExponential toFixed toPrecision".split()
)
_JS_REGEXP_METHODS: _Final = _JS_OBJECT_PROTO_NAMES | frozenset("compile exec test".split())


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
    # J90-P: the union over the MRO, made once per class and attribute. Both members are class
    # attributes ts2py writes in the class body (`_js_own`, `_js_own_methods`), never assigned
    # later, so the union a class answers never changes.
    names = _JS_CLASS_NAMES.get((cls, attribute))
    if names is None:
        names = set()
        for klass in cls.__mro__:
            names |= klass.__dict__.get(attribute, frozenset())
        names = _JS_CLASS_NAMES[(cls, attribute)] = frozenset(names)
    return names


_JS_CLASS_NAMES: dict = {}


@_mypyc_attr(native_class=False)
class _JsObject:
    """Base of every class ts2py compiles. Fields are instance attributes spelled as in JS; the
    class lists its own members in `_js_own` and its methods in `_js_own_methods`, so a reflective
    read (`_js_get`) sees exactly what JS would and nothing Python adds. `Object.freeze` makes every
    later assignment the TypeError strict-mode JS raises."""

    _js_name: _ClassVar[str] = "Object"
    _js_own: _ClassVar[frozenset[str]] = frozenset()
    _js_own_methods: _ClassVar[frozenset[str]] = frozenset()
    _js_frozen = False

    def __setattr__(self, name, value):
        if self._js_frozen:
            if name in self.__dict__:
                raise _JsTypeError(
                    f"Cannot assign to read only property '{name}' of object '#<{self._js_name}>'"
                )
            raise _JsTypeError(f"Cannot add property {name}, object is not extensible")
        object.__setattr__(self, name, value)


_JS_OBJECT_CLASS: type = _JsObject


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
    if key in ("stack", "cause") and isinstance(obj, _JS_ERROR_CLASS):
        raise TypeError(f"ts2py: reading an Error's {key!r} is outside the subset")
    return _JS_UNDEFINED


def _js_object_to_string(obj):
    if "toString" in _js_class_names(type(obj), "_js_own_methods"):
        result = obj.toString()
        if isinstance(result, (dict, list, _JS_OBJECT_CLASS)):
            raise _JsTypeError("Cannot convert object to primitive value")
        return _js_str(result)
    return "[object Object]"


def _js_invoke(receiver, name, *args):
    """`receiver.name(...args)` for a method a compiled class declares."""
    if isinstance(receiver, _JS_OBJECT_CLASS) and name in _js_class_names(
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
    if isinstance(receiver, _JS_OBJECT_CLASS) and name in _js_class_names(
        type(receiver), "_js_own_methods"
    ):
        return getattr(receiver, name)(*args)
    return builtin(receiver, *args)


def _js_freeze(value):
    """`Object.freeze(value)` on a class instance (a plain object or array is outside the
    subset)."""
    if not isinstance(value, _JS_OBJECT_CLASS):
        raise TypeError(
            "ts2py: Object.freeze of anything but a class instance is outside the subset"
        )
    object.__setattr__(value, "_js_frozen", True)
    return value


@_mypyc_attr(native_class=False)
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


_JS_ERROR_CLASS: type = _JsError


@_mypyc_attr(native_class=False)
class _JsTypeError(_JsError, TypeError):
    _js_name = "TypeError"
    name = "TypeError"


_JS_TYPE_ERROR_CLASS: type = _JsTypeError


@_mypyc_attr(native_class=False)
class _JsRangeError(_JsError, ValueError):
    _js_name = "RangeError"
    name = "RangeError"


_JS_RANGE_ERROR_CLASS: type = _JsRangeError


@_mypyc_attr(native_class=False)
class _JsSyntaxError(_JsError, ValueError):
    _js_name = "SyntaxError"
    name = "SyntaxError"


_JS_SYNTAX_ERROR_CLASS: type = _JsSyntaxError


def _js_throw(value):
    """`throw value`: an Error (any Python exception) is raised as itself; throwing anything else
    is outside the subset."""
    if isinstance(value, BaseException):
        return value
    return TypeError("ts2py: throwing a value that is not an Error is outside the subset")


_JS_PROTOTYPES: dict = {}


class _JsPrototype:
    """A stand-in for a built-in prototype object, compared by identity only."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


_JS_OBJECT_PROTOTYPE: _Final = _JsPrototype("Object.prototype")


def _js_get_prototype_of(value):
    """`Object.getPrototypeOf(value)`: `Object.prototype` for a plain object, the class for a class
    instance, a distinct stand-in for every other kind of value."""
    if value is None or value is _JS_UNDEFINED:
        raise _JsTypeError("Cannot convert undefined or null to object")
    if isinstance(value, dict):
        return _JS_OBJECT_PROTOTYPE
    if isinstance(value, _JS_OBJECT_CLASS):
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
    if isinstance(value, _JS_OBJECT_CLASS):
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
    if type(value) is dict and set(map(type, value)) <= _JS_STR_ONLY:
        # J90-P: no key made of digits only, so none is an array index and `_js_own_keys`'
        # order is the dict's own: its items, each as a `[key, value]` list.
        if not any(map(str.isdigit, value)):
            return list(map(list, value.items()))
        # J90-2: a plain object's own string keys read straight from the dict (each is there:
        # `_js_get` would answer the same value), in `_js_own_keys`' order.
        keys = _js_own_keys(value)
        return list(map(list, zip(keys, map(value.__getitem__, keys), strict=False)))
    return [[key, _js_get(value, key)] for key in _js_own_property_names(value)]


def _js_map_entries(value):
    """J90-P: `new Map(Object.entries(value))`. A plain object with string keys only is read
    straight into the Map's entries, in `_js_own_keys`' order (each key its own `_js_key`); any
    other value through `Object.entries` and the Map constructor, as written."""
    if type(value) is dict and set(map(type, value)) <= _JS_STR_ONLY:
        # The dict's entries are the Map's; a key made of digits only may be an array index,
        # which JS orders first: then the order is settled when the Map is first walked.
        out = _JsMap()
        out._entries = value.copy()
        if any(map(str.isdigit, value)):
            out._keys = _JS_REORDER
        return out
    return _JsMap(_js_object_entries(value))


def _js_is_primitive_key(key) -> bool:
    """A property key ToPropertyKey spells as `String(key)`: a primitive, never an object."""
    return isinstance(key, (bool, int, float, _JsBigInt)) or key is None or key is _JS_UNDEFINED


def _js_object_has_own(obj, key):
    """`Object.hasOwn(obj, key)`: an OWN property only, never what `Object.prototype` gives; so a
    plain object answers for its own keys, `__proto__` included, an array or a string for an index
    in range and `length`, and a number, boolean or BigInt has none (J87-3F)."""
    if obj is None or obj is _JS_UNDEFINED:
        raise _JsTypeError("Cannot convert undefined or null to object")
    if not isinstance(key, str):
        if not _js_is_primitive_key(key):
            raise TypeError("ts2py: Object.hasOwn of a non-primitive key is outside the subset")
        key = _js_str(key)
    if isinstance(obj, dict):
        return key in obj
    if isinstance(obj, (list, str)) and not isinstance(obj, _JS_MATCH_ARRAY_CLASS):
        # A match array also owns `index` and `input`; it is refused below rather than modelled.
        if key == "length":
            return True
        index = _js_index_key(key)
        return index is not None and index < _js_len(obj)
    if isinstance(obj, (bool, int, float, _JsBigInt)):
        return False
    raise TypeError(f"ts2py: Object.hasOwn on {type(obj).__name__} is outside the subset")


def _js_object_from_entries(entries):
    """`Object.fromEntries(entries)` over an array of `[key, value]` arrays: each key an OWN data
    property (CreateDataProperty, so `__proto__` is a key, not the prototype), a repeated key
    keeping its first position and its last value, a missing value `undefined` (J87-3F). Any
    other iterable or entry, whose JS answer the subset does not model, raises."""
    if not isinstance(entries, list):
        raise TypeError("ts2py: Object.fromEntries of anything but an array is outside the subset")
    out = {}
    for entry in entries:
        if not isinstance(entry, list):
            raise TypeError("ts2py: an Object.fromEntries entry not an array is outside the subset")
        key = _js_get(entry, 0)
        if not isinstance(key, str):
            if not _js_is_primitive_key(key):
                raise TypeError("ts2py: Object.fromEntries of an object key is outside the subset")
            key = _js_str(key)
        out[key] = _js_get(entry, 1)
    return out


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
    if isinstance(obj, _JS_OBJECT_CLASS):
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
    if isinstance(obj, (_JsMap, _JsSet)):
        # J89-2: a Map or Set has no own string keys; `in` sees what its prototype chain holds.
        names = _JS_MAP_PROTO_NAMES if isinstance(obj, _JsMap) else _JS_SET_PROTO_NAMES
        return key in names or key in _JS_OBJECT_PROTO_NAMES
    raise _JsTypeError(f"Cannot use 'in' operator to search for '{key}' in {_js_str(obj)}")


# J89-2: the string-keyed members of Map.prototype and Set.prototype (Node 26.13).
_JS_MAP_PROTO_NAMES: _Final = frozenset(
    ("clear", "constructor", "delete", "entries", "forEach", "get", "getOrInsert",
     "getOrInsertComputed", "has", "keys", "set", "size", "values")
)
_JS_SET_PROTO_NAMES: _Final = frozenset(
    ("add", "clear", "constructor", "delete", "difference", "entries", "forEach", "has",
     "intersection", "isDisjointFrom", "isSubsetOf", "isSupersetOf", "keys", "size",
     "symmetricDifference", "union", "values")
)


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


# ------------------------------------------------------------ J87-3 (#316 G1): pricing, jobbudget


def _js_number_is_finite(value):
    """`Number.isFinite`: a number that is neither NaN nor +-Infinity; no coercion, so a string or
    a boolean is not finite. An int past the double range is Infinity in JS, so not finite."""
    if not _js_is_number(value):
        return False
    value = _js_num(value)
    return type(value) is int or _js_math.isfinite(value)


def _js_trunc(value):
    """`Math.trunc`: ToNumber, then toward zero; NaN, the infinities and the sign of a zero kept, so
    `Math.trunc(-0.5)` is -0."""
    value = _js_math_arg(value)
    if type(value) is int or value != value or value in (_js_math.inf, -_js_math.inf):
        return value
    whole = float(_js_math.trunc(value))
    if whole == 0:
        return _js_math.copysign(0.0, value)
    return _js_double_out(whole)


def _js_m_splice(receiver, start, *rest):
    """`a.splice(start, deleteCount?, ...items)`: in place; returns the removed elements. `start`
    and `deleteCount` are ToIntegerOrInfinity, clamped as JS clamps them."""
    items = _js_array("splice", receiver)
    length = len(items)
    begin = _js_to_integer(start)
    if begin == -_js_math.inf:
        begin = 0
    elif begin < 0:
        begin = max(length + begin, 0)
    else:
        begin = min(begin, length)
    if not rest:
        count = length - begin
    else:
        count = _js_to_integer(rest[0])
        count = 0 if count == -_js_math.inf else count
        count = int(min(max(count, 0), length - begin))
    removed = items[begin : begin + count]
    items[begin : begin + count] = list(rest[1:])
    return removed


def _js_m_reduce(receiver, callback, *initial):
    """`a.reduce(cb, initial?)`: left to right over the length read once at the start (an index the
    callback made disappear is skipped, as a hole is); with no initial value and no element, JS's
    TypeError."""
    items = _js_array("reduce", receiver)
    length = len(items)
    index = 0
    if initial:
        accumulator = initial[0]
    else:
        if length == 0:
            raise _JsTypeError("Reduce of empty array with no initial value")
        accumulator = items[0]
        index = 1
    while index < length:
        if index < len(items):
            accumulator = callback(accumulator, items[index], index, items)
        index += 1
    return accumulator


def _js_opt_get(obj, key):
    """`obj?.[key]` / `obj?.key`: `undefined` when `obj` is null or undefined, else the read."""
    if obj is None or obj is _JS_UNDEFINED:
        return _JS_UNDEFINED
    return _js_get(obj, key)


def _js_json_number(text):
    """A JSON number token as the JS number `JSON.parse` reads it: the nearest double (so a long
    integer rounds and one past the range is Infinity), spelled as an int when integral within
    2^53 and not -0."""
    return _js_double_out(float(text))


@_mypyc_attr(native_class=False)
class _JsJsonParseError(_JsSyntaxError):
    """The SyntaxError `JSON.parse` throws. Its JS `message` is V8's wording, which CPython's
    decoder does not reproduce, so generated code reading it raises instead of answering a different
    sentence; a Python caller sees CPython's own decoder message as the exception's text."""

    def __init__(self, python_message):
        Exception.__init__(self, python_message)
        object.__setattr__(self, "_js_python_message", python_message)

    @property
    def message(self) -> str:  # type: ignore[override]
        raise TypeError("ts2py: the message of a JSON.parse SyntaxError is outside the subset")

    def __str__(self):
        return self._js_python_message


_JS_JSON_PARSE_ERROR_CLASS: type = _JsJsonParseError


def _js_json_int(text):
    """J90-P: `_js_json_number` for an integer token. One shorter than 16 characters other than
    `-0` (JSON has no leading zeros, so `-0` is the only negative zero) is below 10^15 < 2^53 in
    magnitude, so `int(text)` is the double JS reads, exactly; any other takes `_js_json_number`."""
    if len(text) < 16 and text != "-0":
        return int(text)
    return _js_json_number(text)


def _js_json_ints_exact(text):
    """J90-P: whether `int()` reads every integer token of `text` as `JSON.parse` does: no `-0`
    token and no token of 16 digits or more. A run of 16 digits counts unless what precedes it
    (past a `-` and blanks) is a character no token follows (a letter, a quote): only after `[`,
    `,`, `:` or at the start can a run be a token. Conservative: a string that only looks like
    a token answers False, which costs the per-token hook, never a wrong number.

    J90-PF: a `-0` likewise: only one after `[`, `,`, `:` or at the start (past blanks) can be a
    token; one after any other character is inside a string (`"audit-0"`) or an exponent
    (`1e-0`, a float token) and never reaches `parse_int`. A hot index head names files and
    slugs such as `x-0-y`, and one such `-0` sent the whole 180 KB text through the hook."""
    for match in _JS_JSON_NEG_ZERO.finditer(text):
        before = match.start() - 1
        while before >= 0 and text[before] in " \t\n\r":
            before -= 1
        if before < 0 or text[before] in "[,:":
            return False
    data = text.encode("utf-8", "surrogatepass")
    zeros = data.translate(_JS_DIGITS_TO_ZERO)
    at = zeros.find(_JS_SIXTEEN_ZEROS)
    while at != -1:
        # `find` answers the leftmost match, so `at` starts its run of digits.
        before = at - 1
        if before >= 0 and data[before] == 0x2D:
            before -= 1
        while before >= 0 and data[before] in b" \t\n\r":
            before -= 1
        if before < 0 or data[before] in b"[,:":
            return False
        at = zeros.find(_JS_SIXTEEN_ZEROS, _JS_ZERO_RUN.match(zeros, at).end())
    return True


def _js_json_reject_constant(name):
    # CPython's decoder accepts the bare tokens NaN, Infinity and -Infinity; JSON.parse does not.
    raise ValueError(name)


def _js_json_parse(text):
    """`JSON.parse(text)`: the JSON grammar exactly (CPython's decoder, strict, with the three
    non-standard constants refused), numbers as JS numbers (`_js_json_number`), objects as dicts in
    source order with a repeated key keeping its first position and its last value, as JS's
    CreateDataProperty does, and `__proto__` an ordinary own key. A malformed text is a SyntaxError
    (`_JsJsonParseError`). Nesting deeper than CPython's recursion limit is read without recursion
    (`_js_json_parse_deep`, J88-2), as V8 reads it."""
    if not isinstance(text, str):
        raise TypeError("ts2py: JSON.parse of anything but a string is outside the subset")
    # J90-P: one decoder, made once (`json.loads` with hooks builds a new one, and its scanner,
    # per call: half the cost of a short line). `json.loads` refuses a leading BOM before it
    # decodes; so does this, with its error.
    try:
        if text.startswith("\ufeff"):
            raise _js_jsonlib.JSONDecodeError(
                "Unexpected UTF-8 BOM (decode using utf-8-sig)", text, 0
            )
        # J90-P: a long text whose every integer token `int()` reads exactly (no run of 16 digits
        # anywhere, no `-0` token: `_js_json_int`'s test, made once over the raw text, so a string
        # that only looks like such a token costs the per-token hook, never the reverse) takes
        # CPython's own integers; a short one, the per-token hook (cheaper than the scan).
        # J90-PF: and a text of 513-2048 characters with a comma every eight or fewer (an index
        # shard: an integer at nearly every comma), which took twice as long through the hook
        # (the scan costs about 0.17 us and 0.7 ns a character, the hook 0.07 us an integer).
        # An event line (a few integers among strings, mostly under 512 characters) does not
        # qualify. Which decoder is a cost only: both read every text the scan admits alike.
        decoder = _JS_JSON_DECODER
        size = len(text)
        if (
            size > 2048 or (size > 512 and text.count(",") * 8 > size)
        ) and _js_json_ints_exact(text):
            decoder = _JS_JSON_DECODER_INTS
        # J90-P: the cyclic collector off while the decoder only allocates (J68-5 measured a
        # postings shard parse at half the time with it off); back on only if it was on.
        collecting = _js_gc.isenabled()
        _js_gc.disable()
        try:
            return decoder.decode(text)
        finally:
            if collecting:
                _js_gc.enable()
    except RecursionError:
        # J88-2: V8 parses any depth; the iterative reading answers what `json.loads` would
        # have answered with no recursion limit.
        pass
    except ValueError as error:
        raise _JsJsonParseError(str(error)) from None
    try:
        return _js_json_parse_deep(text)
    except _JsJsonParseError:
        raise
    except ValueError as error:
        raise _JsJsonParseError(str(error)) from None


def _js_catch(error):
    """`catch`: `error` when a JS `catch` would see it, else re-raised. A JS throw is a `_JsError`,
    an `OSError` an adapter raised where Node throws an fs Error, or the one plain `TypeError` the
    runtime raises with JS's own sentence (`Cannot read properties of null ...`). A subset refusal
    (`ts2py: ...`), a recursion or memory limit, and any other Python exception are not something
    JS could have thrown, so a `catch` never swallows them."""
    if isinstance(error, _JS_ERROR_CLASS) or isinstance(error, OSError):
        return error
    if type(error) is TypeError and str(error).startswith("Cannot read properties of "):
        return error
    raise error


def _js_py_value(value):
    """A JS value lifted into the Python value a hand-written caller is given, as a host's `fromJs`
    (the JS side's lift into a JSON-ready value) lifts it for `dumpJson`: a number that is a safe integer (and not
    -0) is an `int`, any other number a `float`; `undefined` is `None`; lists and dicts are copied
    through. Not used by generated code: shims call it on what a generated function returns."""
    if value is _JS_UNDEFINED or value is None:
        return None
    if isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        if -(2**53 - 1) <= value <= 2**53 - 1:
            return value
        return float(_js_num(value))
    if isinstance(value, float):
        if (
            value == value
            and _js_math.isfinite(value)
            and value.is_integer()
            and abs(value) <= 2**53 - 1
            and not (value == 0 and _js_math.copysign(1.0, value) < 0)
        ):
            return int(value)
        return value
    if isinstance(value, list):
        return [_js_py_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _js_py_value(item) for key, item in value.items()}
    raise TypeError(
        f"ts2py: lifting {type(value).__name__} into a Python value is outside the subset"
    )


# ---------------------------------------------------------------- J88-2 (#316 G2: event log,
# token ledger, log segment)

# A Node `Buffer`: `bytes` (what Node hands back from a read or a `concat`), a `bytearray` (from
# `Buffer.alloc`, which `readSync` fills in place) or a `memoryview` of one (`subarray`, which
# shares the bytes it views, as Node's does).
_JS_BYTES: _Final = (bytes, bytearray, memoryview)


def _js_buffer_to_string(buffer, encoding=_JS_UNDEFINED):
    """`buf.toString(encoding?)`: `utf8` (the default) decodes as Node's does, one U+FFFD per
    maximal invalid subpart and a BOM kept, which `bytes.decode('utf-8', 'replace')` is (J86's
    measurement, the TextDecoder row); `hex` is two lowercase digits a byte; J89-2: `latin1` is one
    character U+0000..U+00FF a byte, as Node's `latin1` (alias `binary`) decoder writes it."""
    if encoding is _JS_UNDEFINED or encoding in ("utf8", "utf-8"):
        return bytes(buffer).decode("utf-8", "replace")
    if encoding in ("latin1", "binary"):
        return bytes(buffer).decode("latin-1")
    if encoding == "hex":
        return bytes(buffer).hex()
    if encoding == "base64":
        # J90-3: RFC 4648 base64 with `=` padding, Node's `base64` encoder (`retention.ts`'s
        # `entry` of a file that is not UTF-8).
        return _js_base64.b64encode(bytes(buffer)).decode("ascii")
    raise TypeError(f"ts2py: Buffer.toString({encoding!r}) is outside the subset")


def _js_m_equals(receiver, other):
    """`buf.equals(other)` (J90-3): whether two Buffers hold the same bytes; anything but two
    Buffers is outside the subset (Node throws ERR_INVALID_ARG_TYPE for a second not a Buffer)."""
    if not isinstance(receiver, _JS_BYTES):
        raise _js_outside("equals", receiver)
    if not isinstance(other, _JS_BYTES):
        raise TypeError("ts2py: Buffer.equals of anything but a Buffer is outside the subset")
    return bytes(receiver) == bytes(other)


def _js_m_subarray(receiver, start=_JS_UNDEFINED, end=_JS_UNDEFINED):
    """`buf.subarray(start, end)`: a view sharing the bytes (a `memoryview`), bounds as `slice`."""
    if not isinstance(receiver, _JS_BYTES):
        raise _js_outside("subarray", receiver)
    length = len(receiver)
    lo = _js_slice_bound(start, length, 0)
    hi = _js_slice_bound(end, length, length)
    return memoryview(receiver)[lo : max(lo, hi)]


def _js_m_endsWith(receiver, suffix):
    """`s.endsWith(suffix)`, by UTF-16 code unit (as `_js_m_startsWith`)."""
    # J90-P4: two ASCII `str`s, the branch below's answer for exactly them, ahead of its calls.
    if type(receiver) is str and type(suffix) is str and receiver.isascii() and suffix.isascii():
        return receiver.endswith(suffix)
    if isinstance(receiver, str):
        suffix = _js_str(suffix)
        if receiver.isascii() and suffix.isascii():
            return receiver.endswith(suffix)
        return _js_code_units(receiver).endswith(_js_code_units(suffix))
    raise _js_outside("endsWith", receiver)


def _js_m_trim(receiver):
    """`s.trim()`: WhiteSpace and LineTerminator off both ends (`_JS_WHITESPACE`, which is not
    `str.strip()`'s set: U+FEFF is JS whitespace, U+001C-U+001F and U+0085 are not)."""
    if isinstance(receiver, str):
        return receiver.strip(_JS_WHITESPACE)
    raise _js_outside("trim", receiver)


def _js_m_values(receiver):
    """`m.values()` spread at once (`[...m.values()]`, `for (const v of m.values())`): a Map's
    values, a Set's items or an array's elements, in order, as a fresh list."""
    if isinstance(receiver, _JsMap):
        return [value for _, value in receiver]
    if isinstance(receiver, (_JsSet, list)):
        return list(receiver)
    raise _js_outside("values", receiver)


def _js_m_keys(receiver):
    """`m.keys()` iterated or spread at once (J89-4a): a Map's keys, a Set's items or an array's
    indexes, in order, as a fresh list (a snapshot, as `values` is)."""
    if isinstance(receiver, _JsMap):
        return [key for key, _ in receiver]
    if isinstance(receiver, _JsSet):
        return list(receiver)
    if isinstance(receiver, list):
        return list(range(len(receiver)))
    raise _js_outside("keys", receiver)


def _js_m_forEach(receiver, callback):
    """`a.forEach(cb)` (J89-4a), an array only: `cb(item, index, a)` for each index below the
    length read once at the start that is still present when reached (one the callback removed is
    skipped, as JS skips a missing index); answers `undefined`."""
    items = _js_array("forEach", receiver)
    for index in range(len(items)):
        if index < len(items):
            callback(items[index], index, items)
    return _JS_UNDEFINED


def _js_m_copyWithin(receiver, target, start, end=_JS_UNDEFINED):
    """`a.copyWithin(target, start, end?)` (J89-4a), an array only: ECMA-262's steps (each bound
    ToIntegerOrInfinity, a negative one from the end, clamped to the length; the count the smaller
    of what is left of the source and of the target), copying in place as if through a temporary,
    which is what JS's direction-aware loop amounts to on an array without holes. Answers the
    array."""
    items = _js_array("copyWithin", receiver)
    length = len(items)

    def bound(value, default):
        if value is _JS_UNDEFINED:
            return default
        n = _js_to_integer(value)
        if n == -_js_math.inf:
            return 0
        if n < 0:
            return max(length + int(n), 0)
        return length if n == _js_math.inf else min(int(n), length)

    to = bound(target, 0)
    begin = bound(start, 0)
    finish = bound(end, length)
    count = min(finish - begin, length - to)
    if count > 0:
        items[to : to + count] = items[begin : begin + count]
    return items


def _js_to_int32(value):
    number = _js_to_number(_js_to_primitive(value))
    if number != number or number in (_js_math.inf, -_js_math.inf):
        return 0
    n = int(number) & 0xFFFFFFFF
    return n - 0x100000000 if n >= 0x80000000 else n


def _js_shl(left, right):
    """`left << right`: ToInt32 of the left, the count mod 32, the result wrapped to Int32."""
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        raise TypeError("ts2py: << on a BigInt is outside the subset")
    n = (_js_to_int32(left) << (_js_to_int32(right) & 31)) & 0xFFFFFFFF
    return n - 0x100000000 if n >= 0x80000000 else n


def _js_sar(left, right):
    """`left >> right` (J89-4a): ToInt32 of the left, ToUint32 of the count mod 32 (the low five
    bits, which ToInt32's carry too), and the sign-propagating shift: a Python `>>` of an int in
    Int32 range is that arithmetic shift."""
    if isinstance(left, _JsBigInt) or isinstance(right, _JsBigInt):
        raise TypeError("ts2py: >> on a BigInt is outside the subset")
    return _js_to_int32(left) >> (_js_to_int32(right) & 31)


def _js_now():
    """`Date.now()`: whole milliseconds since the epoch, the realtime clock floored."""
    return _js_time.time_ns() // 1_000_000


def _js_sleep_ms(ms):
    """`Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)`: nothing ever notifies a
    fresh buffer, so the call blocks for `ms` milliseconds (ToNumber; NaN is forever, a negative
    count no time) and answers `"timed-out"`."""
    wait = _js_to_number(_js_to_primitive(ms))
    if wait != wait or wait == _js_math.inf:
        raise TypeError("ts2py: an Atomics.wait that never times out is outside the subset")
    if wait > 0:
        _js_time.sleep(wait / 1000)
    return "timed-out"


def _js_civil(days):
    """(year, month, day) of a day count since 1970-01-01, proleptic Gregorian, any year."""
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    return year + (month <= 2), month, day


def _js_date_to_iso(value):
    """`new Date(value).toISOString()` for a number (a boolean or `null` read through ToNumber,
    `undefined` as NaN; a string, which `Date.parse` would read, is outside the subset): TimeClip
    (a value that is not finite or past 8.64e15 in magnitude is the RangeError `Invalid time
    value`), the time truncated toward zero, then `YYYY-MM-DDTHH:mm:ss.sssZ`, a year outside
    0..9999 spelled `+YYYYYY` / `-YYYYYY`."""
    if isinstance(value, bool) or value is None:
        value = 1 if value is True else 0  # ToNumber(true) is 1; false and null are 0
    elif value is _JS_UNDEFINED:
        raise _JsRangeError("Invalid time value")  # ToNumber(undefined) is NaN
    elif not isinstance(value, (int, float)):
        raise TypeError("ts2py: new Date() of anything but a number is outside the subset")
    if isinstance(value, float) and (value != value or value in (_js_math.inf, -_js_math.inf)):
        raise _JsRangeError("Invalid time value")
    if abs(value) > 8.64e15:
        raise _JsRangeError("Invalid time value")
    ms = int(value)  # toward zero, as ToIntegerOrInfinity
    days, rest = divmod(ms, 86_400_000)
    year, month, day = _js_civil(days)
    hours, rest = divmod(rest, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    if 0 <= year <= 9999:
        spelled = f"{year:04d}"
    else:
        spelled = ("-" if year < 0 else "+") + f"{abs(year):06d}"
    return f"{spelled}-{month:02d}-{day:02d}T{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}Z"


def _js_object_assign(target, *sources):
    """`Object.assign(target, ...sources)` onto a class instance (an Error) or a plain object: each
    source's own enumerable properties [[Set]] in key order; `null`/`undefined` sources skipped."""
    if not isinstance(target, (_JS_OBJECT_CLASS, dict)):
        raise TypeError("ts2py: Object.assign onto anything but an object is outside the subset")
    for source in sources:
        if source is None or source is _JS_UNDEFINED:
            continue
        if not isinstance(source, dict):
            raise TypeError(
                "ts2py: Object.assign from anything but a plain object is outside the subset"
            )
        for key in _js_own_keys(source):
            _js_put(target, key, source[key])
    return target


def _js_constructor_of(value):
    """`value.constructor`, read only for its `name`: a plain object's is `Object`, an array's
    `Array`, a compiled class's or a built-in Error's its JS name, a Python exception a
    hand-written caller passed its Python class name (what `type(exc).__name__` reads)."""
    if value is None or value is _JS_UNDEFINED:
        raise TypeError(f"Cannot read properties of {_js_str(value)} (reading 'constructor')")
    if isinstance(value, _JS_OBJECT_CLASS):
        name = type(value)._js_name
    elif isinstance(value, bool):
        name = "Boolean"
    elif isinstance(value, (int, float)):
        name = "Number"
    elif isinstance(value, str):
        name = "String"
    elif isinstance(value, list):
        name = "Array"
    elif isinstance(value, dict):
        name = "Object"
    elif isinstance(value, _JsMap):
        name = "Map"
    elif isinstance(value, _JsSet):
        name = "Set"
    elif isinstance(value, BaseException):
        name = type(value).__name__
    else:
        raise TypeError(f"ts2py: the constructor of {type(value).__name__} is outside the subset")
    return {"name": name}


def _js_json_gap(space):
    if isinstance(space, bool) or space is None or space is _JS_UNDEFINED:
        return ""
    if isinstance(space, (int, float)):
        count = min(10, int(_js_to_integer(space)))
        return " " * count if count >= 1 else ""
    if isinstance(space, str):
        return _js_from_units(_js_code_units(space)[:10])
    raise TypeError("ts2py: a JSON.stringify space of that type is outside the subset")


def _js_json_full(value, replacer, gap):
    """SerializeJSONProperty over the whole value with a function `replacer` and a `gap`, both as
    ECMA-262 25.5.2.2 orders them (the replacer sees the root under the key `""`). A cycle is the
    TypeError JS throws; nesting past Python's recursion limit is outside the subset."""
    stack = []

    def prop(holder_value, key, indent):
        value = holder_value
        if replacer is not None:
            value = replacer(key, value)
        if value is None:
            return "null"
        if value is _JS_UNDEFINED or (callable(value) and not isinstance(value, _JS_OBJECT_CLASS)):
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            number = _js_num(value)
            if isinstance(number, float) and not _js_math.isfinite(number):
                return "null"
            return _js_num_str(number)
        if isinstance(value, str):
            return _js_json_quote(value)
        if isinstance(value, _JsBigInt):
            raise _JsTypeError("Do not know how to serialize a BigInt")
        if isinstance(value, (_JsMap, _JsSet)):
            items = []
        elif isinstance(value, (list, dict)):
            items = None
        else:
            raise TypeError(
                f"ts2py: JSON.stringify of {type(value).__name__} is outside the subset"
            )
        if any(entry is value for entry in stack):
            raise _JsTypeError("Converting circular structure to JSON")
        stack.append(value)
        inner = indent + gap
        if isinstance(value, list):
            parts = []
            for index, item in enumerate(value):
                part = prop(item, str(index), inner)
                parts.append("null" if part is None else part)
            open_, close = "[", "]"
        else:
            parts = []
            if items is None:
                lookup = {k if isinstance(k, str) else _js_str(k): k for k in value}
                for k in _js_own_keys(value):
                    part = prop(value[lookup[k]], k, inner)
                    if part is not None:
                        parts.append(_js_json_quote(k) + (": " if gap else ":") + part)
            open_, close = "{", "}"
        stack.pop()
        if not parts:
            return open_ + close
        if not gap:
            return open_ + ",".join(parts) + close
        return open_ + "\n" + inner + (",\n" + inner).join(parts) + "\n" + indent + close

    try:
        return prop(value, "", "")
    except RecursionError:
        raise TypeError(
            "ts2py: JSON.stringify nested deeper than the recursion limit is outside the subset"
        ) from None


def _js_json_stringify_with(value, replacer=_JS_UNDEFINED, space=_JS_UNDEFINED):
    """`JSON.stringify(value, replacer, space)`: `replacer` a function or `null`/`undefined` (an
    array of keys is outside the subset), `space` a count or a string, as JS reads them."""
    if replacer is None or replacer is _JS_UNDEFINED:
        replacer = None
    elif not callable(replacer) or isinstance(replacer, (list, dict, _JS_OBJECT_CLASS)):
        raise TypeError(
            "ts2py: a JSON.stringify replacer that is not a function is outside the subset"
        )
    gap = _js_json_gap(space)
    if replacer is None and not gap:
        return _js_json_stringify(value)
    text = _js_json_full(value, replacer, gap)
    return _JS_UNDEFINED if text is None else text


_JS_JSON_WS: _Final = _js_re.compile(r"[ \t\n\r]*")
_JS_JSON_DECODER: _Final = _js_jsonlib.JSONDecoder(
    parse_int=_js_json_int,
    parse_float=_js_json_number,
    parse_constant=_js_json_reject_constant,
)
_JS_JSON_DECODER_INTS: _Final = _js_jsonlib.JSONDecoder(
    parse_int=int,
    parse_float=_js_json_number,
    parse_constant=_js_json_reject_constant,
)
# The digits of the UTF-8 bytes as `0` (a multi-byte character's bytes are all >= 0x80, never
# an ASCII digit), so a run of 16 digits in the text is 16 zero bytes in a row.
_JS_DIGITS_TO_ZERO: _Final = bytes.maketrans(b"123456789", b"000000000")
_JS_SIXTEEN_ZEROS: _Final = b"0" * 16
_JS_JSON_NEG_ZERO: _Final = _js_re.compile(r"-0(?![.eE0-9])")
_JS_ZERO_RUN: _Final = _js_re.compile(b"0+")
_JS_JSON_NUMBER: _Final = _js_re.compile(r"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?")


def _js_json_parse_deep(text):
    """`JSON.parse` for a text nested past CPython's recursion limit: the same grammar, strings
    read by `json.decoder.scanstring` (the decoder's own, so escapes, surrogates and control
    characters are refused or kept exactly as `json.loads` does), with an explicit stack in place
    of recursion. V8's parser is iterative, so such a text is a value in JS too."""
    scan = _js_jsonlib.decoder.scanstring
    ws = _JS_JSON_WS.match
    number = _JS_JSON_NUMBER.match
    n = len(text)

    def fail(at):
        raise _JsJsonParseError(f"Expecting value: char {at}")

    # Each frame: [container, pending key or None]
    stack = []
    i = ws(text, 0).end()
    while True:
        if i >= n:
            fail(i)
        ch = text[i]
        # 1. read one value (or open a container)
        if ch == "{":
            i = ws(text, i + 1).end()
            if i < n and text[i] == "}":
                value = {}
                i += 1
            else:
                if i >= n or text[i] != '"':
                    fail(i)
                key, i = scan(text, i + 1, True)
                i = ws(text, i).end()
                if i >= n or text[i] != ":":
                    fail(i)
                i = ws(text, i + 1).end()
                stack.append([{}, key])
                continue
        elif ch == "[":
            i = ws(text, i + 1).end()
            if i < n and text[i] == "]":
                value = []
                i += 1
            else:
                stack.append([[], None])
                continue
        elif ch == '"':
            value, i = scan(text, i + 1, True)
        elif ch == "n" and text.startswith("null", i):
            value, i = None, i + 4
        elif ch == "t" and text.startswith("true", i):
            value, i = True, i + 4
        elif ch == "f" and text.startswith("false", i):
            value, i = False, i + 5
        else:
            m = number(text, i)
            if m is None:
                fail(i)
            value, i = _js_json_number(m.group()), m.end()
        # 2. hand it to the open container, closing every container that ends here
        while True:
            if not stack:
                i = ws(text, i).end()
                if i != n:
                    raise _JsJsonParseError(f"Extra data: char {i}")
                return value
            frame = stack[-1]
            container = frame[0]
            if isinstance(container, list):
                container.append(value)
            else:
                container[frame[1]] = value
            i = ws(text, i).end()
            if i < n and text[i] == ",":
                i = ws(text, i + 1).end()
                if isinstance(container, dict):
                    if i >= n or text[i] != '"':
                        fail(i)
                    key, i = scan(text, i + 1, True)
                    i = ws(text, i).end()
                    if i >= n or text[i] != ":":
                        fail(i)
                    i = ws(text, i + 1).end()
                    frame[1] = key
                break
            closer = "]" if isinstance(container, list) else "}"
            if i < n and text[i] == closer:
                i += 1
                stack.pop()
                value = container
                continue
            fail(i)


# ---------------------------------------------------------------- J89-2 (#316 G3): usage, retrieval


def _js_inc(value):
    """`x++` / `++x` as a statement: ToNumeric(x) + 1 (a string `"1"` becomes 2, never `"11"`)."""
    if isinstance(value, _JsBigInt):
        raise TypeError("ts2py: ++ on a BigInt is outside the subset")
    return _js_num(_js_to_number(_js_to_primitive(value)) + 1)


def _js_dec(value):
    """`x--` / `--x` as a statement: ToNumeric(x) - 1."""
    if isinstance(value, _JsBigInt):
        raise TypeError("ts2py: -- on a BigInt is outside the subset")
    return _js_num(_js_to_number(_js_to_primitive(value)) - 1)


def _js_m_charCodeAt(receiver, position=_JS_UNDEFINED):
    """`s.charCodeAt(i)`: the UTF-16 code unit at `i` (half of an astral character's pair), NaN
    outside the string; `i` is ToIntegerOrInfinity (missing or NaN is 0)."""
    # J90-P: a `str` and a plain int index, the path below without its type tests.
    if type(receiver) is str and type(position) is int:
        units = receiver if receiver.isascii() else _js_code_units(receiver)
        return ord(units[position]) if 0 <= position < len(units) else _js_math.nan
    text = _js_string_receiver("charCodeAt", receiver)
    if type(position) is int:
        index = position
    else:
        index = _js_to_integer(position)
    units = text if text.isascii() else _js_code_units(text)
    if 0 <= index < len(units):
        return ord(units[int(index)])
    return _js_math.nan




def _js_m_match(receiver, pattern):
    """`s.match(re)` for a regex literal: with `g`, every match's text over the UTF-16 code units
    (an empty match advances one unit, as `RegExpBuiltinExec` and Python's `finditer` both do),
    or `null` when there is none; without `g`, what `re.exec(s)` answers."""
    text = _js_string_receiver("match", receiver)
    if isinstance(pattern, _JsGlobalRegExp):
        units = _js_code_units(text)
        found = [_js_from_units(m.group(0)) for m in pattern.pattern.finditer(units)]
        return found if found else None
    if isinstance(pattern, _js_re.Pattern):
        return _js_m_exec(pattern, text)
    raise TypeError("ts2py: .match() of anything but a regex literal is outside the subset")


# Wide enough for every double times 10**100 exactly (a double's decimal expansion has at most 767
# significant digits), so `scaleb` rounds nothing.
_JS_EXACT: _Final = _js_decimal.Context(prec=1200, Emax=2000, Emin=-2000)


def _js_m_toFixed(receiver, digits=_JS_UNDEFINED):
    """`x.toFixed(f)` (Number.prototype.toFixed): the integer `n` nearest to `x * 10**f` on the
    EXACT binary value of `x`, the LARGER of two on a tie (so a tie rounds away from zero, where
    Python's `format(x, '.9f')` rounds it to even), written with `f` fraction digits; `-0` is
    `"0"`, NaN and the infinities are their `String()`, and from 1e21 the number's `String()`."""
    if isinstance(receiver, bool) or not isinstance(receiver, (int, float)):
        raise _JsTypeError("Number.prototype.toFixed requires that 'this' be a Number")
    f = _js_to_integer(digits)
    if f in (_js_math.inf, -_js_math.inf) or not 0 <= f <= 100:
        raise _JsRangeError("toFixed() digits argument must be between 0 and 100")
    x = _js_num(receiver)
    if x != x or x in (_js_math.inf, -_js_math.inf):
        return _js_str(x)
    sign = ""
    if x < 0:
        sign, x = "-", -x
    if x >= 1e21:
        return sign + _js_str(x)
    exact = _js_decimal.Decimal(x).scaleb(int(f), _JS_EXACT)
    n = int(exact.to_integral_value(_js_decimal.ROUND_HALF_UP, _JS_EXACT))
    m = str(n)
    if f != 0:
        k = len(m)
        if k <= f:
            m = "0" * (int(f) + 1 - k) + m
            k = int(f) + 1
        m = m[: k - int(f)] + "." + m[k - int(f) :]
    return sign + m


def _js_buffer_index_of(buffer, search, offset):
    """`buf.indexOf(value, byteOffset)` for a number `value` (lib/buffer.js `bidirectionalIndexOf`
    and node_buffer.cc `IndexOfNumber`): the byte `value >>> 0` truncated to eight bits; the
    offset is ToNumber, NaN (or missing) is 0, a negative one counts from the end (clamped to 0),
    and a fraction truncates toward zero."""
    if isinstance(search, bool) or not isinstance(search, (int, float)):
        raise TypeError("ts2py: Buffer.indexOf of anything but a byte number is outside the subset")
    number = _js_to_number(_js_to_primitive(search))
    byte = 0 if number != number or number in (_js_math.inf, -_js_math.inf) else int(number) % 256
    length = len(buffer)
    start = _js_to_number(_js_to_primitive(offset)) if offset is not _JS_UNDEFINED else 0
    if start != start:
        start = 0
    start = _js_to_integer(start)
    if start < 0:
        start = max(length + start, 0)
    if start >= length:
        return -1
    if isinstance(buffer, (bytes, bytearray)):
        return buffer.find(byte, int(start))
    return bytes(buffer).find(byte, int(start))


# ---------------------------------------------------------------- J89-3 (#316 G3): numeric lowering
#
# A `Float64Array` is a Python `list` whose every element is a `float` (SUBSET.md, *Typed arrays*):
# the compiler admits one only as a `const`'s initializer and only indexed, written by index or
# measured (`.length`), so nothing but these helpers and the proven fast lowerings ever touch it,
# and every write stores a `float`.

# The longest Float64Array a Python list is built for (Node allocates far longer ones lazily).
_JS_F64_MAX: _Final = 2**26
_JS_FLOAT_KINDS: _Final = frozenset({float})
_JS_NUMBER_KINDS: _Final = frozenset({float, int})
_JS_INT_KINDS: _Final = frozenset({int})


def _js_f64_new(length):
    """`new Float64Array(length)` for a primitive `length`: ToIndex (ToNumber, a fraction truncated
    toward zero, NaN as 0); a negative length, or one past 2**53 - 1, is the RangeError Node throws,
    naming the value as given. Every element is the float 0.0. An object argument (Node copies its
    elements) is outside the subset."""
    original = length
    if not _js_is_number(length):
        if isinstance(length, _JsBigInt):
            raise _JsTypeError("Cannot convert a BigInt value to a number")
        if not (length is None or length is _JS_UNDEFINED or isinstance(length, (bool, str))):
            raise TypeError(
                "ts2py: new Float64Array of anything but a length is outside the subset"
            )
        length = _js_to_number(length)
    length = _js_num(length)
    if length != length:
        count = 0
    elif length in (_js_math.inf, -_js_math.inf):
        count = -1
    else:
        count = int(length)
    if count < 0 or count > 2**53 - 1:
        raise _JsRangeError("Invalid typed array length: " + _js_str(original))
    if count > _JS_F64_MAX:
        raise TypeError("ts2py: a Float64Array longer than 2**26 elements is outside the subset")
    return [0.0] * count


def _js_f64_index(array, key):
    """The element index `array[key]` names (a number, or a string that is a canonical numeric
    string), or -1 when that numeric key is not a valid integer index (out of range, a fraction,
    -0 spelled as the string `"-0"`, NaN, an infinity). Any other key would be an ordinary property
    of the typed array, which the subset does not have."""
    kind = type(key)
    if kind is int:
        return key if 0 <= key < len(array) else -1
    if kind is float:
        # `-0.0` is the key "0" (ToPropertyKey), so it names element 0.
        if key.is_integer() and 0 <= key < len(array):
            return int(key)
        return -1
    if kind is str:
        if key == "-0":
            return -1
        number = _js_to_number(key)
        if _js_num_str(number) == key:
            return _js_f64_index(array, number)
    if _js_is_number(key):  # a subclass of int or float, or an int past 2**53
        return _js_f64_index(array, float(_js_num(key)))
    raise TypeError("ts2py: a Float64Array key that is not a number is outside the subset")


def _js_ta_get(array, key):
    """`array[key]` on a Float64Array: the element, or `undefined` for a numeric key that is not a
    valid index."""
    if type(key) is int:
        return array[key] if 0 <= key < len(array) else _JS_UNDEFINED
    at = _js_f64_index(array, key)
    return array[at] if at >= 0 else _JS_UNDEFINED


def _js_to_f64(value):
    """What a Float64Array stores for `value`: ToNumber (a BigInt is the TypeError Node throws), as
    a float."""
    if type(value) is float:
        return value
    number = _js_to_numeric(value)
    if isinstance(number, _JsBigInt):
        raise _JsTypeError("Cannot convert a BigInt value to a number")
    return float(_js_num(number))


def _js_ta_put(array, key, value):
    """`array[key] = value` on a Float64Array: the value is converted first (ToNumber), then stored
    as a float at a valid index; a numeric key that is not one stores nothing."""
    number = _js_to_f64(value)
    if type(key) is int:
        if 0 <= key < len(array):
            array[key] = number
        return
    at = _js_f64_index(array, key)
    if at >= 0:
        array[at] = number


def _js_fdiv(left, right):
    """`left / right` for two numbers at least one of which is a float: IEEE division, and a zero
    divisor is `_js_div`'s answer (NaN or a signed Infinity, never Python's ZeroDivisionError)."""
    return left / right if right else _js_div(left, right)


def _js_doubles(items, start, stop):
    """The guard of a counted loop that reads `items[i]` for `start <= i < stop` (the caller has
    checked `0 <= start` and `stop <= len(items)`): every element read is a float or an int a
    double holds exactly, so each read is a proven number."""
    part = items if start == 0 and stop == len(items) else items[start:stop]
    kinds = frozenset(map(type, part))
    if kinds <= _JS_FLOAT_KINDS:
        return True
    if not kinds <= _JS_NUMBER_KINDS:
        return False
    if kinds == _JS_INT_KINDS:
        return _JS_SAFE_MIN <= min(part) and max(part) <= _JS_SAFE_MAX
    return all(_JS_SAFE_MIN <= v <= _JS_SAFE_MAX for v in part if type(v) is int)


# J89-3: V8's Array.prototype.sort (`third_party/v8/builtins/array-sort.tq`, a port of CPython's
# listsort as it was before 3.11), step for step: the comparator is called on the same pairs in the
# same order, so an inconsistent comparator (one a NaN makes so) leaves the order V8 leaves.
# CPython's own `list.sort` is TimSort too, but since 3.11 merges runs by another rule
# (powersort), and V8 insertion-sorts a short array without looking for a run first: on an
# inconsistent comparator the two orders differ (J89-3 measured 561 of 30,000 seeded sorts against
# Node; this port, 0, with the same number of comparator calls in every one).
_JS_V8_MIN_GALLOP: _Final = 7


def _js_v8_timsort(items, cmp):
    n = len(items)
    if n < 2:
        return items
    a = items  # work array, sorted in place
    # Node v26.13.0 (V8) sorts seven or fewer elements by binary insertion alone, without
    # looking for a run first (measured: the comparator calls it makes).
    if n <= 7:
        _js_v8_binary_insertion(a, cmp, 0, 1, n)
        return items
    st = {"min_gallop": _JS_V8_MIN_GALLOP}
    runs = []  # [base, len]
    remaining = n
    low = 0
    minrun = _js_v8_min_run(n)
    while remaining:
        run = _js_v8_count_run(a, cmp, low, low + remaining)
        if run < minrun:
            forced = min(minrun, remaining)
            _js_v8_binary_insertion(a, cmp, low, low + run, low + forced)
            run = forced
        runs.append([low, run])
        _js_v8_merge_collapse(a, cmp, runs, st)
        low += run
        remaining -= run
    _js_v8_merge_force_collapse(a, cmp, runs, st)
    return items


def _js_v8_lt(cmp, x, y):
    return cmp(x, y) < 0


def _js_v8_min_run(n):
    r = 0
    while n >= 64:
        r |= n & 1
        n >>= 1
    return n + r


def _js_v8_binary_insertion(a, cmp, low, start, high):
    if start == low:
        start += 1
    while start < high:
        pivot = a[start]
        left, right = low, start
        while left < right:
            mid = left + ((right - left) >> 1)
            if _js_v8_lt(cmp, pivot, a[mid]):
                right = mid
            else:
                left = mid + 1
        a[left + 1 : start + 1] = a[left:start]
        a[left] = pivot
        start += 1


def _js_v8_count_run(a, cmp, low, high):
    lo = low + 1
    if lo == high:
        return 1
    run = 2
    descending = _js_v8_lt(cmp, a[lo], a[lo - 1])
    prev = a[lo]
    idx = lo + 1
    while idx < high:
        cur = a[idx]
        order_lt = _js_v8_lt(cmp, cur, prev)
        if descending:
            if not order_lt:
                break
        elif order_lt:
            break
        prev = cur
        run += 1
        idx += 1
    if descending:
        a[low : low + run] = a[low : low + run][::-1]
    return run


def _js_v8_merge_collapse(a, cmp, runs, st):
    while len(runs) > 1:
        n = len(runs) - 2
        if (n > 0 and runs[n - 1][1] <= runs[n][1] + runs[n + 1][1]) or (
            n > 1 and runs[n - 2][1] <= runs[n - 1][1] + runs[n][1]
        ):
            if runs[n - 1][1] < runs[n + 1][1]:
                n -= 1
            _js_v8_merge_at(a, cmp, runs, n, st)
        elif runs[n][1] <= runs[n + 1][1]:
            _js_v8_merge_at(a, cmp, runs, n, st)
        else:
            break


def _js_v8_merge_force_collapse(a, cmp, runs, st):
    while len(runs) > 1:
        n = len(runs) - 2
        if n > 0 and runs[n - 1][1] < runs[n + 1][1]:
            n -= 1
        _js_v8_merge_at(a, cmp, runs, n, st)


def _js_v8_merge_at(a, cmp, runs, i, st):
    base_a, len_a = runs[i]
    base_b, len_b = runs[i + 1]
    runs[i][1] = len_a + len_b
    del runs[i + 1]
    k = _js_v8_gallop_right(a, cmp, a[base_b], base_a, len_a, 0)
    base_a += k
    len_a -= k
    if len_a == 0:
        return
    len_b = _js_v8_gallop_left(a, cmp, a[base_a + len_a - 1], base_b, len_b, len_b - 1)
    if len_b == 0:
        return
    if len_a <= len_b:
        _js_v8_merge_low(a, cmp, base_a, len_a, base_b, len_b, st)
    else:
        _js_v8_merge_high(a, cmp, base_a, len_a, base_b, len_b, st)


def _js_v8_gallop_left(arr, cmp, key, base, length, hint):
    """The leftmost position in arr[base:base+length] where key belongs (a[k-1] < key <= a[k])."""
    last_ofs, ofs = 0, 1
    if _js_v8_lt(cmp, arr[base + hint], key):
        max_ofs = length - hint
        while ofs < max_ofs:
            if _js_v8_lt(cmp, arr[base + hint + ofs], key):
                last_ofs = ofs
                ofs = (ofs << 1) + 1
            else:
                break
        if ofs > max_ofs:
            ofs = max_ofs
        last_ofs += hint
        ofs += hint
    else:
        max_ofs = hint + 1
        while ofs < max_ofs:
            if _js_v8_lt(cmp, arr[base + hint - ofs], key):
                break
            last_ofs = ofs
            ofs = (ofs << 1) + 1
        if ofs > max_ofs:
            ofs = max_ofs
        last_ofs, ofs = hint - ofs, hint - last_ofs
    last_ofs += 1
    while last_ofs < ofs:
        m = last_ofs + ((ofs - last_ofs) >> 1)
        if _js_v8_lt(cmp, arr[base + m], key):
            last_ofs = m + 1
        else:
            ofs = m
    return ofs


def _js_v8_gallop_right(arr, cmp, key, base, length, hint):
    """The rightmost position where key belongs (a[k-1] <= key < a[k])."""
    last_ofs, ofs = 0, 1
    if _js_v8_lt(cmp, key, arr[base + hint]):
        max_ofs = hint + 1
        while ofs < max_ofs:
            if _js_v8_lt(cmp, key, arr[base + hint - ofs]):
                last_ofs = ofs
                ofs = (ofs << 1) + 1
            else:
                break
        if ofs > max_ofs:
            ofs = max_ofs
        last_ofs, ofs = hint - ofs, hint - last_ofs
    else:
        max_ofs = length - hint
        while ofs < max_ofs:
            if _js_v8_lt(cmp, key, arr[base + hint + ofs]):
                break
            last_ofs = ofs
            ofs = (ofs << 1) + 1
        if ofs > max_ofs:
            ofs = max_ofs
        last_ofs += hint
        ofs += hint
    last_ofs += 1
    while last_ofs < ofs:
        m = last_ofs + ((ofs - last_ofs) >> 1)
        if _js_v8_lt(cmp, key, arr[base + m]):
            ofs = m
        else:
            last_ofs = m + 1
    return ofs


def _js_v8_merge_low(a, cmp, base_a, len_a, base_b, len_b, st):
    temp = a[base_a : base_a + len_a]
    dest = base_a
    ct = 0
    cb = base_b
    a[dest] = a[cb]
    dest += 1
    cb += 1
    len_b -= 1
    if len_b == 0:
        a[dest : dest + len_a] = temp[ct : ct + len_a]
        return
    if len_a == 1:
        a[dest : dest + len_b] = a[cb : cb + len_b]
        a[dest + len_b] = temp[ct]
        return
    min_gallop = st["min_gallop"]
    while True:
        wins_a = wins_b = 0
        done = None
        while True:
            if _js_v8_lt(cmp, a[cb], temp[ct]):
                a[dest] = a[cb]
                dest += 1
                cb += 1
                wins_b += 1
                wins_a = 0
                len_b -= 1
                if len_b == 0:
                    done = "succeed"
                    break
                if wins_b >= min_gallop:
                    break
            else:
                a[dest] = temp[ct]
                dest += 1
                ct += 1
                wins_a += 1
                wins_b = 0
                len_a -= 1
                if len_a == 1:
                    done = "copyb"
                    break
                if wins_a >= min_gallop:
                    break
        if done is None:
            min_gallop += 1
            first = True
            while first or wins_a >= _JS_V8_MIN_GALLOP or wins_b >= _JS_V8_MIN_GALLOP:
                first = False
                min_gallop = max(1, min_gallop - 1)
                st["min_gallop"] = min_gallop
                wins_a = _js_v8_gallop_right(temp, cmp, a[cb], ct, len_a, 0)
                if wins_a > 0:
                    a[dest : dest + wins_a] = temp[ct : ct + wins_a]
                    dest += wins_a
                    ct += wins_a
                    len_a -= wins_a
                    if len_a == 1:
                        done = "copyb"
                        break
                    if len_a == 0:
                        done = "succeed"
                        break
                a[dest] = a[cb]
                dest += 1
                cb += 1
                len_b -= 1
                if len_b == 0:
                    done = "succeed"
                    break
                wins_b = _js_v8_gallop_left(a, cmp, temp[ct], cb, len_b, 0)
                if wins_b > 0:
                    a[dest : dest + wins_b] = a[cb : cb + wins_b]
                    dest += wins_b
                    cb += wins_b
                    len_b -= wins_b
                    if len_b == 0:
                        done = "succeed"
                        break
                a[dest] = temp[ct]
                dest += 1
                ct += 1
                len_a -= 1
                if len_a == 1:
                    done = "copyb"
                    break
            if done is None:
                min_gallop += 1
                st["min_gallop"] = min_gallop
                continue
        if done == "succeed":
            if len_a > 0:
                a[dest : dest + len_a] = temp[ct : ct + len_a]
        else:
            a[dest : dest + len_b] = a[cb : cb + len_b]
            a[dest + len_b] = temp[ct]
        return


def _js_v8_merge_high(a, cmp, base_a, len_a, base_b, len_b, st):
    temp = a[base_b : base_b + len_b]
    dest = base_b + len_b - 1
    ct = len_b - 1
    ca = base_a + len_a - 1
    a[dest] = a[ca]
    dest -= 1
    ca -= 1
    len_a -= 1
    if len_a == 0:
        a[dest - (len_b - 1) : dest + 1] = temp[0:len_b]
        return
    if len_b == 1:
        dest -= len_a
        ca -= len_a
        a[dest + 1 : dest + 1 + len_a] = a[ca + 1 : ca + 1 + len_a]
        a[dest] = temp[ct]
        return
    min_gallop = st["min_gallop"]
    while True:
        wins_a = wins_b = 0
        done = None
        while True:
            if _js_v8_lt(cmp, temp[ct], a[ca]):
                a[dest] = a[ca]
                dest -= 1
                ca -= 1
                wins_a += 1
                wins_b = 0
                len_a -= 1
                if len_a == 0:
                    done = "succeed"
                    break
                if wins_a >= min_gallop:
                    break
            else:
                a[dest] = temp[ct]
                dest -= 1
                ct -= 1
                wins_b += 1
                wins_a = 0
                len_b -= 1
                if len_b == 1:
                    done = "copya"
                    break
                if wins_b >= min_gallop:
                    break
        if done is None:
            min_gallop += 1
            first = True
            while first or wins_a >= _JS_V8_MIN_GALLOP or wins_b >= _JS_V8_MIN_GALLOP:
                first = False
                min_gallop = max(1, min_gallop - 1)
                st["min_gallop"] = min_gallop
                k = _js_v8_gallop_right(a, cmp, temp[ct], base_a, len_a, len_a - 1)
                wins_a = len_a - k
                if wins_a > 0:
                    dest -= wins_a
                    ca -= wins_a
                    a[dest + 1 : dest + 1 + wins_a] = a[ca + 1 : ca + 1 + wins_a]
                    len_a -= wins_a
                    if len_a == 0:
                        done = "succeed"
                        break
                a[dest] = temp[ct]
                dest -= 1
                ct -= 1
                len_b -= 1
                if len_b == 1:
                    done = "copya"
                    break
                k = _js_v8_gallop_left(temp, cmp, a[ca], 0, len_b, len_b - 1)
                wins_b = len_b - k
                if wins_b > 0:
                    dest -= wins_b
                    ct -= wins_b
                    a[dest + 1 : dest + 1 + wins_b] = temp[ct + 1 : ct + 1 + wins_b]
                    len_b -= wins_b
                    if len_b == 1:
                        done = "copya"
                        break
                    if len_b == 0:
                        done = "succeed"
                        break
                a[dest] = a[ca]
                dest -= 1
                ca -= 1
                len_a -= 1
                if len_a == 0:
                    done = "succeed"
                    break
            if done is None:
                min_gallop += 1
                st["min_gallop"] = min_gallop
                continue
        if done == "succeed":
            if len_b > 0:
                a[dest - (len_b - 1) : dest + 1] = temp[0:len_b]
        else:
            dest -= len_a
            ca -= len_a
            a[dest + 1 : dest + 1 + len_a] = a[ca + 1 : ca + 1 + len_a]
            a[dest] = temp[ct]
        return


def _js_v8_sort(items, compare):
    """`items.sort(compare)` as V8 orders it: `undefined` last (never compared), the comparator's
    sign orders (NaN is 0, a boolean its number), in place."""
    present = [item for item in items if item is not _JS_UNDEFINED]
    missing = len(items) - len(present)

    def order(left, right):
        result = compare(left, right)
        if isinstance(result, bool):
            result = int(result)
        if not _js_is_number(result) or result != result:
            return 0
        return result

    _js_v8_timsort(present, order)
    items[:] = present + [_JS_UNDEFINED] * missing
    return items


def _js_rows(items, n, wanted):
    """J90-P: `for (const [a, b, , d] of items)`, `n` names (holes included) and `wanted` the
    indices named. A list of at least `n` items is its first `n` at once (each `_js_get(item, k)`
    of it is `item[k]`); anything else is read as the general lowering reads it: `_js_get` of each
    wanted index, in order (a hole is never read).

    J90-PF: two names over a plain Map (not a subclass) whose every key is its own tag (`_keys is
    None`, so not waiting to be settled either): `_JsMap.__iter__`'s own walk, each `[key, value]`
    pair yielded as a tuple (the loop unpacks it at once, so its type is never seen). The keys are
    listed at the first item, as `__iter__` lists them, and an entry deleted meanwhile is not
    visited."""
    if n == 2 and type(items) is _JsMap and items._keys is None:
        entries = items._entries
        for tag in list(entries):
            value = entries.get(tag, _JS_ABSENT)
            if value is not _JS_ABSENT:
                yield tag, value
        return
    for item in items:
        if type(item) is list and len(item) >= n:
            yield item if len(item) == n else item[:n]
        else:
            yield [_js_get(item, k) if k in wanted else None for k in range(n)]


def _js_sort_keyed(items, key, descending, compare):
    """J90-P: `items.sort((a, b) => key(a) - key(b))` (`descending`: `key(b) - key(a)`), `key`
    an expression with no effect (ts2py proved it). When every key is a number JS holds exactly (a
    float, or an int within 2^53) and none is NaN, the comparator is a consistent total preorder,
    so every stable sort gives the one order V8's does: stably by key (`0` and `-0` tie, their
    difference being 0; so do two infinities of one sign, whose difference is NaN, read as 0).
    Otherwise, and when computing a key raises (JS may never have compared that item), the
    general sort with `compare`."""
    if type(items) is list and len(items) > 1 and _JS_UNDEFINED not in items:
        try:
            keys = list(map(key, items))
        except Exception:  # noqa: BLE001 - the general sort below raises what JS would
            return _js_m_sort(items, compare)
        if _js_doubles(keys, 0, len(keys)) and not any(map(_js_math.isnan, keys)):
            order = sorted(range(len(items)), key=keys.__getitem__, reverse=descending)
            items[:] = list(map(items.__getitem__, order))
            return items
    return _js_m_sort(items, compare)


def _js_sort_num(items, descending, compare):
    """J90-PF: `items.sort((a, b) => a - b)` (`descending`: `b - a`), `_js_sort_keyed` with each
    item its own key. A list of two or more plain ints a double holds exactly is sorted by value:
    `_js_sort_keyed`'s stable order by key, since items that tie are equal ints and no order of
    them differs from another. Anything else: `_js_sort_keyed`, as before."""
    if (
        type(items) is list
        and len(items) > 1
        and set(map(type, items)) == _JS_INT_ONLY
        and _JS_SAFE_MIN <= min(items)
        and max(items) <= _JS_SAFE_MAX
    ):
        items.sort(reverse=descending is True)
        return items
    return _js_sort_keyed(items, _js_sort_self, descending, compare)


def _js_sort_self(a, *_):
    """The key of `_js_sort_num`'s general path: the item itself (`(a, b) => a - b`'s `a`)."""
    return a


def _js_sort_unique(items, compare):
    """J90-PF: `[...new Set(items)].sort(compare)`, `compare` an adapter whose row promises
    code-point order (ts2py proved the name; its `_js_codepoint_order` is checked again here, as
    `_js_m_sort` checks it). A list of `str`s only: its distinct strings in `str` order, which is
    the general path's answer (`_JsSet` keeps one of each equal string, and `_js_m_sort` sorts a
    list of `str`s by `<` under such a comparator). Anything else: the general path, as written."""
    if (
        type(items) is list
        and getattr(compare, "_js_codepoint_order", False)
        and set(map(type, items)) <= _JS_STR_ONLY
    ):
        return sorted(set(items))
    return _js_m_sort([*_JsSet(items)], compare)


def _js_sort_lex(items, parts, compare):
    """J90-P2: `items.sort((a, b) => c1 || c2 || ...)`, each part `(key, descending, codepoint)`
    one `ci`: `key(a) - key(b)` (`descending`: `key(b) - key(a)`), or `cmpCodepoint` of the two
    keys (`codepoint`), every key an expression with no effect (ts2py proved it). When every
    number key is a number JS holds exactly and none is NaN, and every code-point key is a `str`,
    the comparator is a consistent total preorder (a part answers 0, or NaN read as 0, exactly
    when its keys tie: two infinities of one sign; `cmpCodepoint` is `str` order), so every stable
    sort gives V8's order: stably by each key, the last first. Otherwise, and when computing a
    key raises, the general sort with `compare`."""
    if type(items) is list and len(items) > 1 and _JS_UNDEFINED not in items:
        try:
            cols = [list(map(key, items)) for key, _, _ in parts]
        except Exception:  # noqa: BLE001 - the general sort below raises what JS would
            return _js_m_sort(items, compare)
        for (_, _, codepoint), keys in zip(parts, cols, strict=True):
            if codepoint:
                if not all(type(k) is str for k in keys):
                    return _js_m_sort(items, compare)
            elif not _js_doubles(keys, 0, len(keys)) or any(map(_js_math.isnan, keys)):
                return _js_m_sort(items, compare)
        order = list(range(len(items)))
        for (_, descending, _), keys in reversed(list(zip(parts, cols, strict=True))):
            order.sort(key=keys.__getitem__, reverse=descending)
        items[:] = list(map(items.__getitem__, order))
        return items
    return _js_m_sort(items, compare)


def _js_sort_by_f64(items, keys, descending, compare):
    """`items.sort((a, b) => keys[b] - keys[a] || a - b)` (`descending`), or with `keys[a] -
    keys[b]`, for `keys` a Float64Array. When every item is an int index into `keys` and no key it
    names is NaN, the comparator is a total order (key, then index), so any stable sort gives V8's
    order: ascending by index, then stably by key. Otherwise (a NaN key makes the comparator
    inconsistent) V8's own sort runs with `compare` (`_js_v8_sort`), so the order is still V8's.
    Anything but a list is the general `.sort`'s refusal."""
    if type(items) is list:
        if not items:
            return items
        ints = frozenset(map(type, items)) == _JS_INT_KINDS
        if ints and min(items) >= 0 and max(items) < len(keys):
            if not any(map(_js_math.isnan, map(keys.__getitem__, items))):
                items.sort()
                items.sort(key=keys.__getitem__, reverse=descending)
                return items
        return _js_v8_sort(items, compare)
    return _js_m_sort(items, compare)


def _js_instanceof(value, cls) -> bool:
    """J90-P7: `value instanceof C` for a compiled or adapter class: the builtin `isinstance`, called
    here so that mypyc compiles it as the builtin, which sees an interpreted subclass of a class
    the generated module defines (an inline `isinstance` of such a class tests the exact type).
    The `-> bool` is load-bearing: compiled, an unannotated function returning the builtin's
    answer hands back the int 1 or 0 (mypy 2.4.1), where `instanceof` is `true` or `false`."""
    return isinstance(value, cls)


# ---------------------------------------------------------------- J90-P7: `fromJs`, from the adapters

_JS_LIFT_SAFE_INT: _Final = 2**53 - 1
# Values `fromJs` keeps as they are, and a list or a dict of nothing else is handed over as it is.
_JS_LIFT_SAME: _Final = frozenset({str, bool, type(None)})


_JS_LIFT_INT: _Final = frozenset({int})


def _js_lift_ints_safe(ints):
    """J90-P: Python ints only, each a safe integer: each is its own `_js_lifted` (an int kept as it
    is), so the container is too."""
    return -_JS_LIFT_SAFE_INT <= min(ints) and max(ints) <= _JS_LIFT_SAFE_INT


_JS_LIFT_LIST: _Final = frozenset({list})
_JS_LIFT_DICT: _Final = frozenset({dict})
_JS_LIFT_STR: _Final = frozenset({str})
# J90-P5: the kinds a value may have and still be its own `_js_lifted` (see `_js_lift_values_same`).
_JS_LIFT_FLAT: _Final = _JS_LIFT_SAME | {int, list, dict}


def _js_lift_values_same(values):
    """J90-P5: the per-call shape guard of `_js_lifted`. True only when EVERY value of `values` (a
    list) is equal to its own `_js_lifted`, so the container holding them may be handed to
    `json.dumps` unconverted: a string, boolean or null; a safe int; a list whose items all are; a
    plain dict whose keys are all strings, none of them all digits (so `_js_own_keys` is its own
    order), and whose values all are. Checked a level at a time over all the values at once
    (`map(type, ...)`, one `min` and `max` of the ints, the lists' items and the dicts' keys and
    values chained), at C speed. Anything else (a float, a Map, undefined, a BigInt, an unsafe int,
    a key `_js_own_keys` would move) answers False, and `_js_lifted` takes its general path, value
    by value, which is what Node's `fromJs` reads. False is always safe."""
    kinds = set(map(type, values))
    if kinds <= _JS_LIFT_SAME:
        return True
    if not kinds <= _JS_LIFT_FLAT:
        return False
    if int in kinds and not _js_lift_ints_safe(
        values if kinds == _JS_LIFT_INT else [v for v in values if type(v) is int]
    ):
        return False
    if list in kinds:
        lists = values if kinds == _JS_LIFT_LIST else [v for v in values if type(v) is list]
        if not _js_lift_values_same(list(_js_itertools.chain.from_iterable(lists))):
            return False
    if dict in kinds:
        dicts = values if kinds == _JS_LIFT_DICT else [v for v in values if type(v) is dict]
        keys = list(_js_itertools.chain.from_iterable(dicts))
        if not set(map(type, keys)) <= _JS_LIFT_STR or any(map(str.isdigit, keys)):
            return False
        values = list(_js_itertools.chain.from_iterable(map(dict.values, dicts)))
        if not _js_lift_values_same(values):
            return False
    return True


def _js_py_round_float9(x, *_):
    """`pyRoundFloat9` (a host's TypeScript port of it): CPython's `round(x, 9)`. The host
    adapters' `py_round_float9`, moved here (#316 G4, J90-P7B) with `pyRoundFloat9`'s own fast
    path (J68-5): for a float `0 < x` with `y = x * 1e9 < 2**40` whose fraction is more than 1e-3
    from one half, the nearer whole `y` over 1e9 IS what `round` answers (`y` is within 2**-13 of
    the exact `x * 10**9`, and one IEEE division of that whole number by 1e9 is the double its
    decimal parses to), without CPython's decimal string. Every other value is `round`'s."""
    if type(x) is float and x > 0.0:
        y = x * 1e9
        if y < 1099511627776.0:
            whole = _js_math.floor(y)
            frac = y - whole
            if abs(frac - 0.5) > 1e-3:
                return (whole if frac < 0.5 else whole + 1) / 1e9
    return round(x if type(x) is float else _js_num(x), 9)


def _js_lifted(value):
    """`value` as a host's `fromJs` reads it (its JS lift), as the Python value `json.dumps`
    is handed: a number that is a safe integer (`Number.isSafeInteger`) and not -0 is an int, any
    other a float; a Map or a plain object a dict keyed by
    `String(key)` in `Object.entries` order; an array a list; null and undefined None; a BigInt an
    int. A list or a dict holding only strings, booleans and nulls is the same object."""
    kind = type(value)
    if kind in _JS_LIFT_SAME:
        return value
    if kind is int:
        return value if -_JS_LIFT_SAFE_INT <= value <= _JS_LIFT_SAFE_INT else float(value)
    if kind is float:
        # `Number.isSafeInteger(v) && !Object.is(v, -0)`: 2**53 itself is not safe (a float).
        if value.is_integer() and -_JS_LIFT_SAFE_INT <= value <= _JS_LIFT_SAFE_INT and not (
            value == 0 and _js_math.copysign(1.0, value) < 0
        ):
            return int(value)
        return value
    if kind is list:
        if _js_lift_values_same(value):
            return value
        return [_js_lifted(item) for item in value]
    if kind is dict:
        keys = _js_own_keys(value)
        if keys == list(value) and _js_lift_values_same(list(value.values())):
            return value
        return {key: _js_lifted(value[key]) for key in keys}
    if value is _JS_UNDEFINED:
        return None
    # J90-P5: a plain Map (not a subclass) whose every key is its own tag (`_keys is None`: a str
    # or a safe int), all of them strings, in insertion order (not waiting to be settled), whose
    # values pass the shape guard: the dict of its entries, which is what the general path below
    # builds (`String(key)` of a string is the string; each value its own `_js_lifted`).
    if kind is _JsMap and value._keys is None:
        entries = value._entries
        if set(map(type, entries)) <= _JS_LIFT_STR and _js_lift_values_same(list(entries.values())):
            return dict(entries)
    if isinstance(value, _JsMap):
        return {_js_str(key): _js_lifted(item) for key, item in value}
    if kind is _JsBigInt:
        return value.value
    raise TypeError(f"ts2py: dumpJsValue of a {kind.__name__} is outside the subset")
