# J25-D3 bar — a stdlib PDF text reader, pre-registered before it exists

**Written at `6994f96`, before one line of the reader was written.** Every number below is
either a measurement already taken at `6994f96` (marked so) or a *prediction*. Nothing here was
edited after the reader ran; what the reader did to it is recorded in the CLOSEOUT section,
appended, never overwriting.

## Why this bar exists at all

J25-PREP measured the shipped reader over the user's own `~/Downloads` and found **4 of 34**
readable at `1a8e382`; D1 and D2 took it to **6 of 34** at `6994f96`. The remainder is one
format: **27 of the 34 files are PDFs the reader refuses**, and no PDF library exists on this
machine — `pypdf`, `PyPDF2`, `fitz`, `pdfminer`, `pdfplumber`, `pdftotext`, `mutool` and `qpdf`
are all absent (measured, J25-PREP, 2026-08-20), `/usr/bin/textutil` is present and does not do
PDF. The dependency list is fixed at three (`httpx`, `jsonschema`, `pyyaml`), so the reader is
written or there is none. `zlib` is stdlib, which is the whole of the compression problem.

## The corpus, pinned by content

`~/Downloads` is the user's live directory and it may grow, so *"the PDFs in ~/Downloads"* is
not a reproducible corpus. **This bar is scored against the 34 files pinned in
`docs/eval-data/2026-08-20-j25-corpus-pin.tsv`** — sha256, byte size and name for each, taken
2026-08-20. A file whose sha256 is not in that list is not in this corpus; a pinned file that
has disappeared is scored as a miss, not skipped. The census rule that produced the list is
J25-PREP's, unchanged: every file under `~/Downloads` whose suffix is one of
`.xlsx .docx .doc .pdf .mov .csv`. The corpus is **read-only** and every probe against it opens
files and never writes, moves, renames or deletes one.

Its shape, measured at `6994f96`: 28 `.pdf`-suffixed files (one of which is really a `.docx`
and already reads), 4 `.xlsx`, 1 `.doc` (really MHTML, already reads), 1 `.mov`.

## THE CLAIM

> **C1 — Coverage.** With the PDF reader in place, `docread.extract` reads **at least 24 of the
> 34 pinned files**, up from 6 at `6994f96`.

C1 is a fraction over the pinned list, from one rerunnable command, and it is the number this
unit is judged by.

Two subordinate claims, each independently falsifiable:

> **C2 — No silent empty.** The count of files that `extract` **returns** with zero characters
> of text and no `Omission` saying why stays **0**.

> **C3 — Every refusal names a reason from a closed list.** Every file `extract` refuses raises
> `DocumentReadError` whose message names the container and one of exactly these reasons:
> (a) the pages carry no text-showing operator — it is a scan; (b) the text is encoded through
> fonts with no usable character map, so the recoverable bytes are glyph indices and not
> characters; (c) the file is encrypted; (d) the PDF structure could not be parsed, naming what
> failed; (e) the container is not one this reader reads at all (the `.mov`). A refusal that
> names none of these — or names one it did not actually measure — falsifies C3.

## THE FALSIFIER — what reading would mean the reader does not work

- **F1.** Coverage over the pinned 34 comes out **below 24**. C1 is REFUTED. There is no
  "directionally better"; 23 is a refutation and gets written up as one.
- **F2.** Any pinned file is **returned** by `extract` with zero characters of text — not
  merely zero bytes, see the hole below — and no omission record stating why. C2 is REFUTED and
  this is the defect the whole unit exists to prevent, so F2 outranks F1: a reader that hits 30
  of 34 by returning empty pages has failed, not passed.
- **F3.** Any file the reader returns fails the UNINFORMATIVE audit below. Returning text the
  reader cannot vouch for is worse than refusing, because the caller cannot tell it from
  content. F3 also outranks F1.
- **F4.** The refusal budget is exceeded, or any refusal's stated reason is not the reason
  (e.g. a file called a scan that in fact carries a text layer the reader failed to parse).

**The emptiness test must not be `text_bytes == 0`.** D2 measured that `step test.xlsx` renders
28 empty rows and reports `text_bytes=27` — 27 newline separators and **zero characters** — so
a zero-bytes test slips straight past it. Independently re-derived here at `6994f96`: 28 rows,
0 total characters, joined length 27. **The check is on characters, after stripping
whitespace**, at both document and part level.

## THE CONTROL — what must not change

| control | pinned at | how it is checked |
|---|---|---|
| the 4 `.xlsx` extractions | `6994f96` | `J25-D1-coverage.py` rows/`text_bytes` identical before and after |
| the `.docx` (the `.pdf` that is really a `.docx`) | `6994f96` | same |
| the MHTML (the `.doc` that is really MHTML) | `6994f96` | same |
| the nine committed J10 `document-read` rows | `6994f96` | `J25-D2-j10-rows.py` before/after, `diff` **empty** |
| dependency list | three: `httpx`, `jsonschema`, `pyyaml` | `runtime-py/pyproject.toml` diff empty in that block |
| the suite | 1301 passed, 2 xfailed at `6994f96` | `pytest runtime-py/tests -q`, no regression |

A coverage gain bought by moving a J10 row is not a coverage gain. The nine rows are committed
measurements; this unit may not touch them.

## UNINFORMATIVE — text extracted but not vouched for

This is the hardest clause and it is the one that decides whether this reader is worth having.
**A PDF string's bytes are not characters.** They are indices into a font's encoding, and for a
composite font with `Identity-H` encoding and no `/ToUnicode` map they are *glyph indices in
that font's private subset* — recoverable as bytes, meaningless as text. Decoding them anyway
produces exactly the `textutil` mojibake class this program already has a number for: output
that is indistinguishable from content, that no caller can detect, and that a model will quote.

Two independent checks, and they must agree:

**U1 — the reader's own trust accounting (internal).** Every character the reader emits is
sourced from one of: a `/ToUnicode` CMap in the file, or a simple font under a standard base
encoding (`WinAnsiEncoding`, `MacRomanEncoding`, `StandardEncoding`, `PDFDocEncoding`), or a
`/Differences` glyph name that resolves to a Unicode codepoint. **Anything else is not emitted**
— it is counted, and the count is disclosed as an `Omission`. A page whose characters are all
untrusted yields no rows and says so; a document whose every page is like that is refused under
C3(b).

**U2 — an external character-class audit that knows nothing about fonts.** A separate script
takes the reader's output text and computes, over all non-whitespace characters:

- `bad` = fraction in Unicode categories `Cc`, `Cf`, `Co` (private use), `Cn` (unassigned), or
  equal to `U+FFFD`. **A file passes only if `bad <= 0.005`.**
- `alnum` = fraction in categories `L*` or `N*`. **A file passes only if `alnum >= 0.50`.**

U2 is the check on U1. If the reader's trust accounting were wrong — if it vouched for glyph
indices — U2 would see the resulting text as unassigned codepoints and CJK-range noise and fail
it. **U2 is scored on every file C1 counts as read.** If U1 says "fine" and U2 says "bad" on the
same file, the file is a **failure of this unit**, not a disagreement to be argued away.

**Proof obligation.** U1 is worthless if it never fires. This unit must **demonstrate U1
catching a real file**: show a pinned PDF whose text the reader refuses to vouch for, and show
by U2 that the text it *would* have emitted is in fact mojibake. If no pinned file exercises
U1, that must be stated in those words — "the mojibake guard is unexercised on this corpus" —
and a constructed fixture used instead, with the difference declared.

## THE REFUSAL BUDGET — pre-registered, with reasons

Predicted **refusals: at most 10 of the 34**, by reason:

| # | reason (C3 code) | predicted count | which files, predicted |
|---|---|---|---|
| 1 | (e) container this reader does not read | **1** | the `.mov` — no stdlib video reader exists and none is being written |
| 2 | (a) scan: no text-showing operator on any page | **3–5** | the `submission-juma-acct-signature` trio (199, 199, 229 images and 2 show-ops each, measured `6994f96`), possibly `AP1827-[STB]…` (1289 streams, 24 images, 22 show-ops) and `CV_Pattanapol.pdf` (961 streams, 0 show-ops on the naive pass) |
| 3 | (b) no usable character map | **0–3** | unknown before the reader exists; Thai-script files are the candidates |
| 4 | (c) encrypted | **0** | measured `6994f96`: `/Encrypt` absent from all 28 |
| 5 | (d) structure unparseable | **0–1** | budgeted, not expected |

**More than 10 refusals falsifies the budget** (F4) even if C1 still passes — that combination
cannot occur arithmetically at 34 files, which is the point: the budget and the claim are the
same statement checked from both ends.

Two predictions that are deliberately falsifiable, and the reason each is uncertain:

- The naive J25-PREP pass counted only literal-string show-operators `( … ) Tj`, so a PDF that
  writes its text as **hex strings** `<0041> Tj` scored zero there and may read fine here.
  `crypto_agreement.pdf`, `customer_agreement.pdf`, `Supakit_Kitjanabumrungsak_CV.pdf` and
  `CV_Pattanapol.pdf` are all in that shape — many fonts, few or no literal-string ops. **I
  predict at least two of those four read.**
- The 13 object-stream PDFs need one more parsing layer (`/Type/ObjStm` plus xref streams, all
  `zlib`) and no new dependency. **I predict at least 10 of the 13 read.**

## THE COMMAND

Coverage, before and after, is the same script under two `PYTHONPATH`s — it prints
`bantamkit.docread.__file__` so there is no doubt which reader answered:

    PYTHONPATH=<tree>/runtime-py/src BANTAMKIT_ASSETS=<tree>/assets \
      /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python \
      /Users/kktest/Documents/Claude/Projects/bantamkit/.shiftwork/probes/J25-D1-coverage.py

The pin check, the U2 audit and the U1 demonstration are
`.shiftwork/probes/J25-D3-pdf-coverage.py`, added by this unit beside D1's and D2's.

## What this bar does NOT claim

- **Not layout.** A PDF has no rows; it has glyphs at coordinates. This reader groups glyphs
  into rows by baseline and orders them by x. A multi-column page will interleave, and a table
  will not come back as columns. Rows here are a *slicing unit*, not a claim about structure.
- **Not images.** No OCR, ever, on this dependency list. A scan refuses; a scanned page inside
  a text document is declared, not silently empty.
- **Not fidelity to the printed page.** Ligatures, hyphenation and soft breaks are whatever the
  file's own `/ToUnicode` says they are.
- **Not encrypted files.** Not one file on this corpus is encrypted, so any code for it would
  be unmeasured. Encryption is refused by name.

---

# CLOSEOUT — measured at `d709b17`, appended, nothing above edited

Command, and it prints which reader answered:

    PYTHONPATH=<tree>/runtime-py/src BANTAMKIT_ASSETS=<tree>/assets \
      /Users/kktest/Documents/Claude/Projects/bantamkit/.venv/bin/python \
      /Users/kktest/Documents/Claude/Projects/bantamkit/.shiftwork/probes/J25-D3-pdf-coverage.py \
      <tree>/docs/eval-data/2026-08-20-j25-corpus-pin.tsv

## The claims

| claim | bar said | measured at `d709b17` | verdict |
|---|---|---|---|
| **C1** coverage over the pinned 34 | ≥ 24 | **33 of 34** (6 at `6994f96`) | **HELD** |
| **C2** files returned with no character and no omission | 0 | **0** | **HELD** |
| **C2** parts with no character and no omission | 0 | **0**, of 12 such parts | **HELD** |
| **C3** refusals naming a reason from the closed list | all | **1 of 1** — the `.mov`, reason (e) | **HELD** |
| **U2** files failing the character-class audit | 0 | **0 of 32 audited** | **HELD** |

**One file returns no character: `step test.xlsx`**, and it is not a C2 violation — it declares
56 embedded files, 18,590,162 bytes and 28 blank rows through D2's omissions. It is also the
one file U2 cannot score, because U2 audits *text that was returned* and there is none. That is
the domain of each check, stated; the raw character count stays printed beside it either way.

## The refusal budget, and the prediction that was WRONG

Budget was ≤ 10 refusals. **Measured: 1.** But the prediction underneath it failed:

| # | reason | predicted | measured | |
|---|---|---|---|---|
| 1 | (e) container not read at all | 1 | **1** — the `.mov` | held |
| 2 | (a) scan, no text-showing operator | 3–5 | **0** | **REFUTED** |
| 3 | (b) no usable character map | 0–3 | **0** whole files (514 characters) | held |
| 4 | (c) encrypted | 0 | **0** | held |
| 5 | (d) structure unparseable | 0–1 | **0** | held |

**The `submission-juma-acct-signature` trio are not scans.** They carry 199, 199 and 229 images
*and* a full text layer — 824, 824 and 869 rows. The J25-PREP census called them `SCAN?` because
its naive pass counted only literal-string show-operators `( … ) Tj` and these files write hex
strings. The same mislabel covered `AP1827-[STB]…` (37 pages, 882 rows), `CV_Pattanapol.pdf`
(75 rows) and `crypto_agreement.pdf` / `customer_agreement.pdf` (1,056 and 1,410 rows). **The
two hedged predictions the bar did make both held**: at least two of those four read (all four
did), and at least 10 of the 13 object-stream files read (all 13 did).

**Not one PDF on this corpus is a scan.** The scanned-page refusal path is therefore
**unexercised on real data** and is held only by `test_a_scanned_page_refuses_and_says_it_is_a_scan`.

## The mojibake guard — U1 fired, and U2 proves what it suppressed

**514 characters across 6 files** were recovered and refused. Rendered permissively
(`read_pdf(vouch=False)`, which nothing in the runtime calls), the exact suppressed characters
audit as:

| file | suppressed | fonts | U2 on the suppressed characters |
|---|---|---|---|
| `submission-juma-…-035623.pdf` | 95 | `?`, `FAAAAA+Loma` | **bad 100%** — U+F70A×47, U+F70B×47, U+F70E×1 |
| `submission-juma-…-042849.pdf` | 95 | same | **bad 100%** |
| `submission-juma-…-103139.pdf` | 96 | same | **bad 100%** |
| `AP1827-[STB]…pdf` | 113 | `?`, `BAAAAA+Loma` | **bad 100%** — U+F70B×68, U+F70A×40, U+F70E×4 |
| `21_Day_Challenge.pdf` | 64 | `AGTMRD+Mali-Regular`, … | **bad 100%** — U+FFFD×64 |
| `Approved_Timesheet_July_2026….pdf` | 51 | `AAAAAD+font000000003010a7b1` | bad 0%, alnum 82% — *see below* |

Five of six are private-use or replacement codepoints: U2's `bad ≤ 0.5%` rule rejects them
outright. **The sixth is the interesting one and it is reported rather than hidden.** Its
suppressed characters render as `چѰѰٖٖ҃щщщщ҆٘٘ҿҿҿ…` — Arabic and Cyrillic letters inside a Thai
and English timesheet, from a subset font's raw codes read as `chr(code)`. **U2 would pass that
text**: they are letters, category `L`. It is caught by U1 alone, because U1 asks where a
character came from and U2 only asks what it looks like. That is the case that justifies having
both, and it is also the honest limit of U2 as a check: *U2 cannot catch mojibake that happens
to be well-formed letters.*

The guard is exercised on real data, and on synthetic data in both directions:
`test_identity_h_without_tounicode_refuses_and_names_the_font` and
`test_identity_h_with_tounicode_is_read` differ only in whether the file states what its codes
mean.

## The control — nothing moved

| control | result at `d709b17` |
|---|---|
| the 4 `.xlsx` | rows 1000 / 22 / 22 / 28, `text_bytes` 4276 / 2433 / 2433 / 27 — **identical to `6994f96`** |
| the `.docx` named `.pdf` | 15 rows, 1489 B — **identical** |
| the MHTML named `.doc` | 667 rows, 27528 B — **identical** |
| the nine J10 `document-read` rows | `J25-D2-j10-rows.py` before vs after: **`diff` empty** |
| dependencies | `["httpx>=0.27", "jsonschema>=4.21", "pyyaml>=6.0"]` — **three, unchanged** |
| suite | **1338 passed, 2 xfailed** (1301 / 2 at `6994f96`); `ruff check runtime-py` clean |

## Non-vacuity — 23 mutations, 22 redden

`.shiftwork/probes/J25-D3-mutations.py`. Three findings the pass produced that the tests alone
did not:

1. **`_Font.has_map` was dead.** Computed in three places, read in none. A field that names the
   vouching property without enforcing it is a check that cannot fail. Deleted; no test moved,
   which is the proof.
2. **Three decoys could not fire.** The inline-image fixture wrote `Tj\x03\x04`, and the binary
   ran into the operator token so the show never happened with the guard removed. The
   false-object fixture first redefined the catalogue (which `pages()` routes around via the
   `/Type/Page` fallback) and then sat inside the content stream (where it is content and runs
   either way). The PNG predictor had a row for `Up` and none for `Sub` or TIFF.
3. **The harness itself lied once.** Two mutations of one file that change its length by the
   *same* number of bytes, run in the same wall-clock second, satisfy CPython's `(mtime, size)`
   cache check — so the second run imports the first mutation's bytecode. `M12b` was called a
   survivor twice before `PYTHONDONTWRITEBYTECODE` was added.

**The one stated survivor, kept rather than tuned away.** `M4` replaces the character-based
emptiness test with `doc.text_bytes != 0` and the suite stays green: on the PDF path the two are
**equivalent today**, because `_rows_from_runs` drops any row that strips to nothing. The
character form stays — that equivalence is a property of the renderer one layer down — and
`test_a_row_is_never_whitespace_only` (mutation `M21`) is what holds it.

## What this unit did NOT close

- **The `.mov`.** 1 of 34, refused by name. No stdlib video reader exists and none was written.
- **No OCR, and that is permanent on this dependency list.** No pinned file needed it.
- **A `/ToUnicode` map can be wrong, and this reader is wrong with it.** In
  `ทำรายการ MA ปฏิเสธ Consent….pdf` the file's own CMap maps code `0xB5` to U+0E33 (ำ) and
  maps *nothing* to U+0E32 (า), so `ทำรายการ` extracts as `ทำรำยกำร`. The character is wrong
  and it is wrong **because the file says so**. U2 cannot see it — both are valid Thai letters
  — and the alternative is guessing, which is the one thing this reader is built not to do.
  **This is the largest open correctness gap and it is not closable without a font-shaping
  layer.**
- **Thai combining marks come out in visual order**, not logical order: `หน้า` extracts as
  `หนา้`, `ข้อมูล` as `ขอม้ ลู`. The characters are right; their order is the order the page
  paints them. Reordering would require a shaping engine.
- **A symbolic simple font whose codes are not ASCII is trusted in the ASCII range.** A
  subset TrueType marked symbolic that draws something other than `A` at code `0x41` would be
  read as `A`, and neither U1 nor U2 would see it. No pinned file is known to be in that shape;
  none was checked for it.
- **`21_Day_Challenge.pdf` takes ~34 s** (87.7 MB, 241 pages). No performance work was done.
- **A 241-page PDF becomes 241 parts**, and `document_manifest` prints a line per part. Whether
  that fits a worker window is a question for the manifest, not the reader, and it was not
  measured here.
- **The scan-refusal path is unexercised on real data** (see the budget above).
- **Encryption is unexercised on real data**: `/Encrypt` is absent from all 28 files, so
  `test_an_encrypted_pdf_refuses_by_name` is the only thing holding it.
