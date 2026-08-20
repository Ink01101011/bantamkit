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
