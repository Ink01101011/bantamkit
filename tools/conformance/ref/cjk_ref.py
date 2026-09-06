"""Reference side of the `charsets` suite's CJK half: CPython's multi-byte codecs, live.

`runtime-ts/src/charsets.ts` carries CPython's SINGLE-byte tables, and `charsets_ref.py`
pins them. The ten CJK codecs are not in that file at all: `docread.ts` decodes them through
ICU's `TextDecoder` (`MULTI_BYTE_LABELS`), wearing CPython's replacement policy on top
(`decodeMultiByte`), and the six `iso2022_jp*` labels go to ICU's `iso-2022-jp` decoder
whole (`ESCAPE_LABELS`). ICU's tables are not CPython's, so the two answer differently on
some inputs — a difference roadmap row 8 (o) has registered in prose since 2026-08-29 and
NOTHING has ever compared.

This script produces the reference half of that comparison: the corpora, and CPython's own
answer for every input in them.

THE RECIPE LIVES HERE, IN CODE, BECAUSE THE LAST ONE DID NOT.
-------------------------------------------------------------
Roadmap row 8 (o) quotes ten per-codec counts "300 random byte strings per codec … (seed 7)"
and the script that produced them was never checked in. Measured 2026-09-06: ninety-odd
reconstructions of that sentence — `randbytes` and `randrange` byte streams, fixed lengths 1
through 32, `randrange`/`randint` length ranges, one shared corpus and one re-seeded per
codec — and NOT ONE reproduces the ten counts together. The register's own profile rules a
single corpus out: it pairs `euc_jp` 297 (a rate only very short inputs reach) with `gb2312`
141 (a rate only longer ones fall to), and no uniform length gives both. So the numbers in
that row are not reproducible from what the repo holds, and the numbers pinned here are the
ones THIS recipe measures. The recipe is:

    rng = random.Random(7)                       # re-seeded per codec, so every codec sees
    n   = rng.randrange(2, 9)                    # the SAME 300 inputs and the counts are
    inp = bytes(rng.randrange(256) for _ in n)   # comparable across the row

Two decisions in it, both about the GATE rather than about elegance:

  * length 2..8, not 1 and not 32. A one-byte input is decided by `MULTI_BYTE_SINGLES`,
    which the suite already pins, so a corpus of them measures nothing new (measured: all
    ten codecs score 295-300 of 300). A 32-byte input is almost certainly invalid somewhere,
    so the codecs pile up against the floor (measured: `gb2312` 0 of 300, `cp949` 4). A count
    at either rail can only move one way, and a gate that can only go one way is half a gate.
    At 2..8 every one of the ten lands strictly inside — 141 to 298 — so both directions are
    visible.
  * re-seeded per codec. The ten counts are then ten answers about the SAME 300 inputs, which
    is what makes the row a row instead of ten unrelated measurements.

The corpus digest is pinned by the suite, so a CPython whose Mersenne Twister stream moved
is a named failure and not a silent re-measurement.

`iso2022_jp` is measured TWICE and neither way is the register's
-----------------------------------------------------------------
Row 8 (o)'s amendment says the ISO-2022-JP residual is "12 of 900 valid-text inputs, and
every one of the 12 is the WAVE DASH". The count is a SAMPLE statistic and the "every one"
is a claim about characters, so this script answers both, and only the second can settle it:

  * `iso_text`: 900 seeded strings of characters CPython round-trips, the shape the register
    sampled. Reproduces a count to diff against 12.
  * `iso_chars`: EVERY character CPython's `iso2022_jp` round-trips, one per input — a census,
    not a sample. This is what says which characters actually differ, and it refutes "every
    one of the 12 is the wave dash": six characters differ, and the wave dash is one of them.

Protocol: one JSON request on stdin, one JSON response on stdout.

    {"codecs": [<module name>, ...]}
      -> {"version": "3.12.13",
          "inputs": [<hex>, ...],                       # 300, shared by every codec
          "answers": {<codec>: [<string>, ...], ...},   # CPython's, errors="replace"
          "iso": {"module": "iso2022_jp",
                  "chars": [<character>, ...], "hex": [<hex>, ...],       # the census
                  "text_hex": [<hex>, ...], "text": [<string>, ...]}}     # the 900 sample

A codec the port carries and this CPython does not answers `null`, as `charsets_ref.py`
does, so the harness reports it as a case rather than crashing.
"""

from __future__ import annotations

import codecs
import json
import random
import sys

# The corpus recipe. Changing any of these three moves every pinned count in the suite, and
# the pinned corpus digest is what makes that a failure the reader is told about.
SEED = 7
COUNT = 300
LENGTH_RANGE = (2, 9)  # `random.randrange` bounds: 2..8 inclusive

ISO_MODULE = "iso2022_jp"
ISO_SWEEP_STOP = 0x30000  # past every plane CPython's iso2022_jp can name
ISO_TEXT_COUNT = 900
ISO_TEXT_LENGTH_RANGE = (1, 9)  # 1..8 characters per string


def _corpus() -> list[bytes]:
    rng = random.Random(SEED)
    return [
        bytes(rng.randrange(256) for _ in range(rng.randrange(*LENGTH_RANGE)))
        for _ in range(COUNT)
    ]


def _answers(codec: str, inputs: list[bytes]) -> list[str] | None:
    try:
        codecs.lookup(codec)
    except LookupError:
        return None
    return [b.decode(codec, errors="replace") for b in inputs]


def _iso_census() -> tuple[list[str], list[str]]:
    """Every character `iso2022_jp` round-trips, and the bytes CPython writes for it.

    The round-trip filter is what makes this a census of the CODEC and not of `encode`:
    a character that encodes but does not come back is not one the decoder is being asked
    about, and including it would compare two sides on an input neither claims to read.
    """
    chars: list[str] = []
    encoded: list[str] = []
    for cp in range(ISO_SWEEP_STOP):
        ch = chr(cp)
        try:
            raw = ch.encode(ISO_MODULE)
        except (UnicodeEncodeError, ValueError):
            continue
        if raw.decode(ISO_MODULE, errors="replace") != ch:
            continue
        chars.append(ch)
        encoded.append(raw.hex())
    return chars, encoded


def _iso_text(alphabet: list[str]) -> tuple[list[str], list[str]]:
    """The register's shape: 900 seeded strings drawn from the characters above."""
    rng = random.Random(SEED)
    text: list[str] = []
    encoded: list[str] = []
    for _ in range(ISO_TEXT_COUNT):
        n = rng.randrange(*ISO_TEXT_LENGTH_RANGE)
        s = "".join(alphabet[rng.randrange(len(alphabet))] for _ in range(n))
        text.append(s)
        encoded.append(s.encode(ISO_MODULE).hex())
    return text, encoded


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    inputs = _corpus()
    chars, encoded = _iso_census()
    text, text_hex = _iso_text(chars)
    out = {
        "version": sys.version.split()[0],
        "seed": SEED,
        "inputs": [b.hex() for b in inputs],
        "answers": {c: _answers(c, inputs) for c in payload.get("codecs", [])},
        "iso": {
            "module": ISO_MODULE,
            "chars": chars,
            "hex": encoded,
            "text": text,
            "text_hex": text_hex,
        },
    }
    json.dump(out, sys.stdout, ensure_ascii=True)


if __name__ == "__main__":
    main()
