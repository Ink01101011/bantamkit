# U17 — a bzip2 `xl/styles.xml` carrying DATE FORMATS

Verdict: **PART.** The register's prediction (roadmap row 8 (t)) is CONFIRMED, and it is now
a fixture instead of a sentence.

## Was `ZIP_BZIP2` sufficient?

Yes. No writer had to be built. CPython's `zipfile` names method 12 as `zipfile.ZIP_BZIP2` and
links `bz2`, so `ZipFile.writestr(name, xml, compress_type=zipfile.ZIP_BZIP2)` produces the
member, and its raw stream, CRC and uncompressed size are read straight back off the archive's
local header — the same way `bzip2.docx` and `bzip2-optional-styles.xlsx` already get theirs.

    .venv/bin/python -c "import zipfile; print(zipfile.ZIP_BZIP2)"   ->  12

The member is carried into `runtime-ts/test/docread-fixtures.mjs` as hex, in the
`{method, raw, crc, size}` shape `zipBytes` already accepts, because Node has no bzip2
compressor either.

## The CONTROL, which is the point of the unit

Two workbooks, not one. Both carry the SAME `xl/styles.xml` content — `styles(['yyyy-mm-dd'],
[0, 164])`, 225 bytes, CRC `0x7e197e5f` — and differ in one field of one header:

| fixture | `xl/styles.xml` method |
|---|---|
| `deflate-date-styles.xlsx` | 8 (deflate) |
| `bzip2-date-styles.xlsx` | 12 (bzip2) |

The CRC and size being equal is not decoration: it is the proof that the two archives hold the
same styles, so a difference in the two answers can only be the method. `preDeflated()` in the
fixture module computes them for the method-8 member and they came out identical to the two
numbers CPython's own bzip2 archive reported — checked, not assumed.

Sheet, in both: `<row r="1"><c r="A1" s="1"><v>46235</v></c><c r="B1" t="inlineStr"><is><t>ok
</t></is></c></row>`. A1 is a bare number at `cellXfs` index 1, which is the `yyyy-mm-dd`
style. `46235` is a serial date and an ordinary number at the same time — the number format is
the only thing in an `.xlsx` that tells them apart, which is why `number-format` exists.

**Control result: YES.** With `styles.xml` readable, the date cell DOES produce a
`number-format` omission — on both runtimes:

    both, deflate-date-styles.xlsx:
      rows       ["46235\tok"]
      omissions  [{"subject":"number-format","count":1,"size":0,"where":["A"],
                   "what":"yyyy-mm-dd","facts":{}}]

So the input can show a difference. Had this come back empty, the fixture would have been
`bzip2-optional-styles.xlsx` all over again — the example where both sides agree — and the
measurement below would have been worth nothing.

## The two answers on the bzip2 file

    reference (runtime-py), bzip2-date-styles.xlsx:
      kind xlsx, text_bytes 8, one part "Sales", row_count 1
      rows       ["46235\tok"]
      omissions  [{"subject":"number-format","count":1,"size":0,"where":["A"],
                   "what":"yyyy-mm-dd","facts":{}}]

    port (runtime-ts), bzip2-date-styles.xlsx:
      kind xlsx, text_bytes 8, one part "Sales", row_count 1
      rows       ["46235\tok"]
      omissions  []

Neither side refuses. Everything else is identical — kind, part name, part index, row count,
`text_bytes`, the row itself, the document-level omission list. The whole divergence is the
one omission: the reference decompresses the member through `bz2`, resolves A1's style and
says the number is a date; `docread.ts` `dateFormats` catches the method-12 refusal through
`isUnreadableOptional` (which is what M1 made it do, and correctly — the alternative is
refusing the workbook) and answers no formats, so it hands back a `46235` it cannot explain.

## What was landed

- `runtime-ts/test/docread-fixtures.mjs` — `DATE_STYLES`, `DATE_STYLES_BZIP2`,
  `DATE_STYLED_ROW`, `preDeflated()`, and the two fixtures.
- `runtime-ts/test/docread-expected.jsonl` — two lines, WRITTEN BY THE REFERENCE
  (`bantamkit.docread` over the laid-down fixtures), never typed.
- `runtime-ts/test/docread.test.mjs` — `bzip2-date-styles.xlsx` added to `DIVERGENT` with the
  port's own answer; `deflate-date-styles.xlsx` deliberately NOT in it, so the control is
  compared against the reference's recorded line like any parity fixture.
- `tools/conformance/suites/docread.mjs` — the `bzip2Styles` ruling, its reason, two NON-ruled
  disclosure companions, and the control pinned as a literal on both sides.
- `docs/porting.md` — the divergence row "a bzip2 `xl/styles.xml` that carries date formats",
  and the bzip2/lzma row's "Residual, unfixed and unfixtured" amended: it is fixtured now.

The three CLAUDE.md costs of a deliberate difference are all paid: the porting row, the
`ruling:` case pinning the wording, and a second non-ruled case comparing the bit. Two of
them, in fact — the shape here is BOTH-READ, so "the refusal bit, side to side" is not where
the divergence lives, and the pair that carries it is
`…: the reference discloses what the unreachable member carries, as measured` against
`…: the port discloses nothing, because the member holding it is method 12`.

Nothing in `runtime-py/src/bantamkit/docread.py` or `runtime-ts/src/docread.ts` was touched:
no behaviour changed on either side, so there is no port half owing. What changed is that a
difference which existed and was invisible is now compared on every run.

## Commands

    # ZIP_BZIP2 is stdlib
    .venv/bin/python -c "import zipfile, bz2; print(zipfile.ZIP_BZIP2)"

    # the two runtimes, side by side (the suite does this itself; this is the hand probe)
    node tools/conformance/run.mjs --suite docread

    # the unit layer, without Python
    cd runtime-ts && node --test test/docread.test.mjs

Measured 2026-09-06 on darwin, `.venv` CPython 3.12.13, `runtime-ts/dist` built at 03:14 over
`src/docread.ts` at 02:55 (U2's changes compiled; nothing rebuilt here, because U5 is live in
`runtime-ts/src/mcp/`).

    node tools/conformance/run.mjs --suite docread
      PASS: 1078 cases, 357 byte-identical, 0 exact-string, 721 structural,
            16 ruled-different, 0 failures
    cd runtime-ts && node --test test/docread.test.mjs
      50 pass, 0 fail

Case counts move with repo content — these are the numbers at this tree, not a target.

## Teeth, measured both ways

Not asserted — run. The probe re-creates the M1 blind spot exactly: change the styled cell's
`s="1"` to `s="0"` in the fixture module, so neither side has a date to disclose.

    perl -0pi -e 's/s="1"><v>46235/s="0"><v>46235/' runtime-ts/test/docread-fixtures.mjs
    node tools/conformance/run.mjs --suite docread
      ✖ extract: bzip2-date-styles.xlsx: bzip2Styles is RULED — STALE RULING:
          the case no longer differs
      ✖ extract: bzip2-date-styles.xlsx: the reference discloses what the unreachable
          member carries, as measured
      ✖ the bzip2-styles ruling has a control: the same styles behind method 8 make
          BOTH sides disclose
      FAIL: 1078 cases, 3 failures

Three named failures, then reverted and green. That is the case for the control existing: a
reader that stopped resolving date styles altogether would leave both sides silent, the ruling
would start MATCHING and be reported as stale — which reads as good news — and both disclosure
companions would read `[]`. The control is the line that says the input still has teeth.

The unit layer has its own: moving `bzip2-date-styles.xlsx` out of `DIVERGENT` (claiming
parity) fails 2 of 50 tests, and the diff printed is the missing `number-format` omission.

## Left for whoever owns the register

`docs/roadmap-toolbox.md` row 8 entry **(t)** is now dischargeable and was NOT edited here —
that file is another unit's and was already modified in this working tree when U17 started.
The closure it wants: measured 2026-09-06 by job44 U17, PART confirmed, fixtured as
`bzip2-date-styles.xlsx` with the control `deflate-date-styles.xlsx`, ruled in the `docread`
suite as `bzip2Styles`, and given its own `docs/porting.md` divergence row. It closes as a
RULING, not as a fix: the underlying bzip2 decoder is still the same one the bzip2/lzma row
waits on, and nothing about that moved.
