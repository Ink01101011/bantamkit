# The test host's adapters (tests/host.rs).
from __RUNTIME__ import _js_num

# A comment line below the header, which the shipped form drops.


def twice(n):
    """Twice `n`; this docstring is dropped when shipped."""
    return _js_num(n) * 2


def cmp_cp(a, b):
    return -1 if a < b else (1 if a > b else 0)
