# ts2py adapters: hand-written Python for the imports and Node globals ts2py does not compile.
# Every name here is declared in tools/ts2py/src/adapters.rs with the reason it is faithful, and
# RULES.md (Adapters) records how each was measured. Nothing else may be imported this way.
import datetime as _datetime

from __RUNTIME__ import _JS_UNDEFINED, _js_num, _JsObject

__all__ = ["Date", "TextDecoder", "py_float_repr", "py_strip"]


def py_float_repr(x):
    """`pyFloatRepr` (runtime-ts/src/memory/pyfs.ts): CPython's `repr(float)`, which it ports."""
    return repr(float(_js_num(x)))


def py_strip(s):
    """`pyStrip` (runtime-ts/src/pysem.ts): CPython's `str.strip()` with no argument, which it
    ports."""
    return s.strip()


class TextDecoder(_JsObject):
    """`new TextDecoder('utf-8')`: WHATWG UTF-8 decode. Invalid bytes become one U+FFFD per maximal
    subpart (Python's 'replace' handler does the same) and a leading BOM is dropped."""

    _js_name = "TextDecoder"
    _js_own = frozenset({"decode"})
    _js_own_methods = frozenset({"decode"})

    def __init__(self, label="utf-8", *_):
        if str(label).strip().lower() not in ("utf-8", "utf8", "unicode-1-1-utf-8"):
            raise TypeError("ts2py: a TextDecoder for anything but UTF-8 is outside the subset")

    def decode(self, data=_JS_UNDEFINED, *_):
        if data is _JS_UNDEFINED:
            return ""
        text = bytes(data).decode("utf-8", "replace")
        return text[1:] if text.startswith("﻿") else text


class Date(_JsObject):
    """`new Date()` with no argument: the local calendar fields of the current instant."""

    _js_name = "Date"
    _js_own = frozenset({"getFullYear", "getMonth", "getDate"})
    _js_own_methods = frozenset({"getFullYear", "getMonth", "getDate"})

    def __init__(self, *args):
        if args:
            raise TypeError("ts2py: new Date(...) with an argument is outside the subset")
        object.__setattr__(self, "_js_now", _datetime.datetime.now())

    def getFullYear(self):
        return self._js_now.year

    def getMonth(self):
        return self._js_now.month - 1

    def getDate(self):
        return self._js_now.day
