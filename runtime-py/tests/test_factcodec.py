"""`memory/factcodec.py`: the generated fact codec first, PyYAML where it refuses (#315, J86-3).

The property is the user's ruling of 2026-11-15: every fact runtime-py wrote before the switch it
writes byte for byte now, and every frontmatter it read it reads to the same values, except the
two classes the ruling names (`yaml11-breaks`, `pyyaml-refuses`). The cross-runtime side is
`node tools/conformance/run.mjs --suite ts2py-codec`; this file holds the Python seam itself,
including the values only a Python caller or a PyYAML read can put into a Fact (floats at the
edges, aware datetimes, a shared list), which the conformance fuzz cannot build.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
import yaml

from bantamkit.memory import factcodec
from bantamkit.memory.store import Fact, MemoryStore

SCALARS = [
    0, 1, -7, 2**53 + 1, 10**30, True, False, None, 0.0, -0.0, 1.5, 1e16, 1e21, 5e-324, 1e-7,
    float("inf"), float("-inf"), float("nan"), date(2026, 8, 23), date(1, 1, 1),
    datetime(2026, 8, 23, 10, 0), datetime(2026, 8, 23, 10, 0, 0, 500000),
    datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
    datetime(2026, 8, 23, 10, 0, tzinfo=timezone(timedelta(hours=7))),
    datetime(2026, 8, 23, 10, 0, tzinfo=timezone(timedelta(hours=-3, minutes=-30))),
    "", "plain", "12", "yes", "null", "2026-08-23", " lead", "a: b", "# x", "ภาษาไทย", "🐔",
    "x" * 120, "a\nb", "it's", "a\tb",
]


def _value(rnd: random.Random, depth: int = 0):
    r = rnd.random()
    if depth < 2 and r < 0.15:
        return [_value(rnd, depth + 1) for _ in range(rnd.randrange(4))]
    if depth < 2 and r < 0.25:
        return {f"k{i}": _value(rnd, depth + 1) for i in range(rnd.randrange(4))}
    return rnd.choice(SCALARS)


def _fact(rnd: random.Random, i: int) -> Fact:
    extra = {rnd.choice(["priority", "source", "metadata", "zz"]): _value(rnd) for _ in range(3)}
    return Fact(
        name=f"f-{i}" if rnd.random() < 0.8 else rnd.choice(SCALARS),
        description=rnd.choice(SCALARS),
        type=rnd.choice(["user", "project", 7]),
        body=rnd.choice(["body", "  spaced  \n\n", "a\n---\nb"]),
        links=[rnd.choice(SCALARS) for _ in range(rnd.randrange(3))],
        last_recalled=rnd.choice([None, "2026-01-01", date(2026, 1, 1)]),
        created=rnd.choice(["2026-01-02", date(2026, 1, 2), None]),
        keywords=[rnd.choice(["a", "b c"]) for _ in range(rnd.randrange(3))],
        outcome=rnd.choice([None, "error", "success"]),
        status=rnd.choice([None, "active", "done"]),
        extra=extra,
    )


def _same(a, b) -> bool:
    """Equal values of equal types, NaN equal to NaN (PyYAML reads `.nan` as a fresh NaN)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and math.isnan(a):
        return math.isnan(b)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, datetime):
        return a == b and a.utcoffset() == b.utcoffset()
    return a == b


def test_every_write_is_pyyamls_bytes_and_most_go_through_the_generated_codec(monkeypatch):
    fallbacks = []
    real = factcodec._pyyaml_fact_text
    monkeypatch.setattr(
        factcodec, "_pyyaml_fact_text", lambda f: fallbacks.append(1) or real(f)
    )
    rnd = random.Random(315)
    facts = [_fact(rnd, i) for i in range(1500)]
    for fact in facts:
        assert MemoryStore._fact_text(None, fact) == real(fact)  # type: ignore[arg-type]
    # The generated path is the one that answers; the fallback is for what it refuses.
    assert 0 < len(fallbacks) < len(facts) // 2


def test_every_read_is_pyyamls_values():
    rnd = random.Random(316)
    generated = 0
    for i in range(1500):
        fact = _fact(rnd, i)
        front = factcodec._pyyaml_fact_text(fact).split("---\n", 2)[1]
        want = yaml.safe_load(front)
        got = factcodec.load_frontmatter(front)
        assert _same(got, want), front
        try:
            generated += bool(factcodec._gen.parse_frontmatter(front))
        except Exception:  # noqa: BLE001 -- a refusal; the fallback answered above
            pass
    assert generated > 1000


def test_a_shared_collection_is_written_by_pyyaml_with_its_alias():
    shared = ["a", "b"]
    fact = Fact(
        name="n", description="d", type="user", body="b", links=shared, last_recalled=None,
        created="2026-01-01", extra={"also": shared},
    )
    text = MemoryStore._fact_text(None, fact)  # type: ignore[arg-type]
    assert "&id001" in text and "*id001" in text
    assert text == factcodec._pyyaml_fact_text(fact)


@pytest.mark.parametrize("front", ["", "# only a comment\n", "\n\n"])
def test_an_empty_frontmatter_is_pyyamls_none(front):
    assert factcodec.load_frontmatter(front) is None


def test_non_text_keys_collapse_as_pyyaml_keys_them():
    front = "name: n\non: 1\nyes: 2\nnull: 3\nTrue: 4\n"
    assert factcodec.load_frontmatter(front) == yaml.safe_load(front) == {
        "name": "n", True: 4, None: 3,
    }


def test_the_two_ruled_classes_read_as_node():
    # yaml11-breaks: U+2028 and the spaces around it are kept (PyYAML folded them as a line
    # break), and a plain scalar holding one is read (PyYAML's scanner broke the line there).
    assert factcodec.load_frontmatter('a: "x \u2028 y"\n') == {"a": "x \u2028 y"}
    assert yaml.safe_load('a: "x \u2028 y"\n') == {"a": "x\u2028y"}
    assert factcodec.load_frontmatter("a: x\u2028y\n") == {"a": "x\u2028y"}
    # The class's one-time rewrite, Node's behaviour since #120 (`docs/porting.md`): PyYAML
    # writes `x<LS>y` with its continuation indent, and that indent is now read as text.
    written = yaml.safe_dump({"a": "x\u2028y"}, allow_unicode=True)
    assert yaml.safe_load(written) == {"a": "x\u2028y"}
    assert factcodec.load_frontmatter(written) == {"a": "x\u2028  y"}
    # pyyaml-refuses: a raw BEL is read.
    assert factcodec.load_frontmatter("a: \x07\n") == {"a": "\x07"}
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("a: \x07\n")


def test_a_refusal_keeps_pyyamls_sentence():
    # an anchor: the generated codec refuses it (#120), PyYAML reads it
    assert factcodec.load_frontmatter("a: &x 1\nb: *x\n") == {"a": 1, "b": 1}
    with pytest.raises(yaml.YAMLError) as theirs:
        yaml.safe_load("a: b: c\n")
    with pytest.raises(yaml.YAMLError) as ours:
        factcodec.load_frontmatter("a: b: c\n")
    assert str(ours.value) == str(theirs.value)


# ------------------------------------------------------------------ J86-5: the read cache


def test_a_cached_read_is_the_fresh_read_and_never_the_same_object(monkeypatch):
    monkeypatch.setattr(factcodec, "_READ", {})
    rnd = random.Random(317)
    for i in range(600):
        front = factcodec._pyyaml_fact_text(_fact(rnd, i)).split("---\n", 2)[1]
        first = factcodec.load_frontmatter(front)
        again = factcodec.load_frontmatter(front)
        assert _same(again, yaml.safe_load(front)), front
        assert _same(again, first), front
        if isinstance(first, dict):
            assert again is not first
    assert factcodec._READ, "the generated reads were not remembered"


def test_changing_what_a_read_returned_does_not_change_the_next_read(monkeypatch):
    monkeypatch.setattr(factcodec, "_READ", {})
    front = "name: n\nlinks:\n- a\nmetadata:\n  type: user\n  tags:\n  - x\n"
    got = factcodec.load_frontmatter(front)
    got["links"].append("forged")
    got["metadata"]["tags"].append("forged")
    got["name"] = "forged"
    assert factcodec.load_frontmatter(front) == yaml.safe_load(front) == {
        "name": "n", "links": ["a"], "metadata": {"type": "user", "tags": ["x"]},
    }


def test_the_cache_is_keyed_by_the_text_so_any_edit_is_a_new_read(monkeypatch):
    monkeypatch.setattr(factcodec, "_READ", {})
    assert factcodec.load_frontmatter("name: a\n") == {"name": "a"}
    # Same length, same everything but one byte: a path+mtime+size key could miss this edit.
    assert factcodec.load_frontmatter("name: b\n") == {"name": "b"}
    assert factcodec.load_frontmatter("name: a\n") == {"name": "a"}


def test_only_the_generated_answers_are_kept_and_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(factcodec, "_READ", {})
    # A PyYAML-only read (an anchor) and a refusal are read again every time, never kept.
    assert factcodec.load_frontmatter("a: &x 1\nb: *x\n") == {"a": 1, "b": 1}
    with pytest.raises(yaml.YAMLError):
        factcodec.load_frontmatter("a: b: c\n")
    assert factcodec._READ == {}
    # A text longer than the bound is answered and not kept.
    long = "name: " + "x" * (factcodec._READ_LONGEST + 1) + "\n"
    assert factcodec.load_frontmatter(long) == yaml.safe_load(long)
    assert factcodec._READ == {}
    # Full means emptied, then the new answer kept: never more than the bound.
    monkeypatch.setattr(factcodec, "_READ_ENTRIES", 3)
    for i in range(7):
        assert factcodec.load_frontmatter(f"name: n{i}\n") == {"name": f"n{i}"}
        assert len(factcodec._READ) <= 3


# ------------------------------------------------------------------- J86-6: the review's fixes


@pytest.mark.parametrize("front", [
    # J86-R finding 1: PyYAML assigns `True` three times in file order and the LAST wins; the
    # generated codec keys by text (`yes` keeps its first place and its last value), so folding
    # its answer gives `{True: 2}`. Any two raw keys that become one native key go to PyYAML.
    "k:\n  yes: 1\n  on: 2\n  yes: 3\n",
    "name: n\nyes: first\non: second\nyes: third\n",
    "k:\n  null: 1\n  Null: 2\n  null: 3\n",
    "k:\n  off: 1\n  false: 2\n  off: 3\n",
])
def test_raw_keys_that_fold_to_one_native_key_are_read_by_pyyaml(front, monkeypatch):
    monkeypatch.setattr(factcodec, "_READ", {})
    assert _same(factcodec.load_frontmatter(front), yaml.safe_load(front)), front
    assert factcodec._READ == {}, "a folded mapping must not be answered by the generated codec"


def test_duplicate_folding_keys_read_through_the_store_as_pyyaml_reads_them(tmp_path):
    # The reviewer's dupkey.py shape, on a scratch store.
    (tmp_path / "facts").mkdir()
    front = (
        "name: f\ndescription: d\ntype: user\ncreated: '2026-01-01'\nlast_recalled: null\n"
        "links: []\nyes: first\non: second\nyes: third\nnested:\n  yes: a\n  on: b\n  yes: c\n"
    )
    (tmp_path / "facts" / "f.md").write_text(f"---\n{front}---\n\nbody\n", encoding="utf-8")
    fact = MemoryStore(tmp_path)._facts()[0]
    assert fact.extra["nested"] == yaml.safe_load(front)["nested"] == {True: "c"}


@pytest.mark.parametrize("front", ["name: on\r\n", "name: n\r\nlinks:\r\n- a\r\n", "a: 'x\ry'\n"])
def test_a_carriage_return_is_read_by_pyyaml(front, monkeypatch):
    # J86-R finding 2: the generated codec reads `\r` as text (`'on\r'`), where PyYAML breaks the
    # line there. The seam promises `safe_load` values to every caller, not only to the ones that
    # read with universal newlines.
    monkeypatch.setattr(factcodec, "_READ", {})
    assert _same(factcodec.load_frontmatter(front), yaml.safe_load(front)), repr(front)
    assert factcodec._READ == {}


def test_the_cache_is_bounded_by_total_size_as_well_as_count(monkeypatch):
    # J86-R finding 5a: 4096 entries of up to 32 KiB each was a 128 MiB key bound; the size bound
    # (`_READ_BYTES`, 4 MiB of key text as `sys.getsizeof` measures it) holds whatever the count.
    import sys

    assert factcodec._READ_BYTES == 4 << 20
    monkeypatch.setattr(factcodec, "_READ", {})
    monkeypatch.setattr(factcodec, "_READ_SIZE", 0)
    monkeypatch.setattr(factcodec, "_READ_BYTES", 64 << 10)
    for i in range(40):
        front = f"name: n{i}\ndescription: " + "d" * 8000 + "\n"
        assert factcodec.load_frontmatter(front) == yaml.safe_load(front)
        held = sum(sys.getsizeof(text) for text in factcodec._READ)
        assert held == factcodec._READ_SIZE <= 64 << 10
    assert factcodec._READ, "nothing was kept"
