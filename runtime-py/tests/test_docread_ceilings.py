"""The ceilings a document reader owes: what it will not materialise, and what it says instead.

job44 U1, from `docs/roadmap-toolbox.md` row 8, entries (v), (k), (u) and (w). Four registered
defects with one property between them: **this reader never turns a bounded file into unbounded
text, and never drops anything in silence.** `TEXT_MAX_BYTES` and its `size-cap` omission were
the shape that already existed for plain text; these tests hold the same shape one container
over (html, mhtml), one grain up (a whole workbook rather than one row), and one cell over (a
reference two cells claim).

The sentences asserted here are load-bearing across runtimes: `runtime-ts/src/docread.ts` emits
the identical strings and `tools/conformance` compares them byte for byte, so changing one here
without changing it there is a divergence rather than a wording preference.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

from test_docread import inline_cell, row, write_mhtml, write_xlsx

from bantamkit import docread
from bantamkit.docread import TEXT_MAX_BYTES, extract

SRC = Path(__file__).resolve().parents[1] / "src"


class monkeyed:
    """`setattr` with an undo, as a context manager, so a test can name the scope of the swap.

    A ceiling is a module constant on purpose — "named, not inlined, so a bar can vary it and
    prove the shortfall is REPORTED rather than the content quietly truncated" is what
    `TEXT_MAX_BYTES` says about itself. Varying it is how these tests stay cheap.
    """

    def __init__(self, target: object, name: str, value: object) -> None:
        self.target, self.name, self.value = target, name, value

    def __enter__(self) -> monkeyed:
        self.previous = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)
        return self

    def __exit__(self, *exc: object) -> bool:
        setattr(self.target, self.name, self.previous)
        return False


def deflated_xlsx(path: Path, body: str) -> Path:
    """`write_xlsx`'s members, DEFLATED — the register's input is 53,967 bytes, not 1.35 MB.

    `write_xlsx` stores its members, which is right for a fixture whose bytes must be a
    function of its members and wrong for measuring an amplification ratio: the whole point of
    (v) is that a file this small materialises one that large.
    """
    write_xlsx(path, [("S", "worksheets/sheet1.xml", body)])
    with zipfile.ZipFile(path) as stored:
        members = [(name, stored.read(name)) for name in stored.namelist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return path


# --------------------------------------------------------------------------------- (v) xlsx


def test_a_workbook_cannot_materialise_unbounded_text_out_of_a_bounded_file(tmp_path):
    """The register's own input, at the register's own numbers.

    MEASURED before the fix (2026-09-06, this machine): 20,000 rows each holding one `XFD1`
    cell deflate to 53,967 bytes and materialise **327,680,000 bytes in 9.02 s** — 6,072x.
    `XLSX_MAX_COLUMNS` bounds how wide ONE row gets (16,384 fields); nothing bounded the
    workbook, so the amplification was simply bought a row at a time.

    The budget is the `TEXT_MAX_BYTES` analogue one grain up, and the shortfall is DISCLOSED:
    the rows this reader did not render are counted, never quietly absent.
    """
    body = "".join(row(inline_cell("XFD1", "x"), index=i + 1) for i in range(20_000))
    path = deflated_xlsx(tmp_path / "wide.xlsx", body)
    assert path.stat().st_size < 100_000  # a bounded file in
    doc = extract(path)
    # bounded text out: the budget, plus at most the one row that crossed it
    assert doc.text_bytes <= docread.XLSX_MAX_TEXT_BYTES + 16_384
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            18_976,
            0,
            "20000 rows in this workbook; this reader renders 16777216 bytes of cell text",
        )
    ]
    assert doc.parts[0].row_count == 1_024  # 16 MiB / 16,384 bytes a row, exactly


def test_the_workbook_budget_is_the_documents_and_not_one_sheets(tmp_path):
    """A per-sheet budget would let an N-sheet workbook materialise N budgets.

    The count is the document's too: every row no sheet rendered is in the one omission, so a
    caller reads one number for "what this workbook did not give me" rather than summing.
    """
    wide = "".join(row(inline_cell(f"A{i + 1}", "abcde"), index=i + 1) for i in range(4))
    path = tmp_path / "two.xlsx"
    write_xlsx(
        path,
        [
            ("First", "worksheets/sheet1.xml", wide),
            ("Second", "worksheets/sheet2.xml", wide),
        ],
    )
    with monkeyed(docread, "XLSX_MAX_TEXT_BYTES", 10):
        doc = extract(path)
    assert [(p.name, p.rows) for p in doc.parts] == [
        ("First", ("abcde", "abcde")),
        ("Second", ()),
    ]
    assert [(o.subject, o.count, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            6,
            "8 rows in this workbook; this reader renders 10 bytes of cell text",
        )
    ]


def test_a_workbook_under_the_budget_says_nothing_about_it(tmp_path):
    """The ceiling must be invisible to every real workbook. MEASURED 2026-09-06 over the
    goal's roots (`~/Downloads`, `~/Documents/Claude/Projects`, `~/Documents`, pruned as J25
    prunes them): 15 `.xlsx`, the largest 8,664,227 bytes on disk, and the largest RENDERING
    is 754,520 bytes — 22x under this budget. An omission on any of them would be a false
    disclosure, which is the same defect as a missing one wearing the other sign."""
    path = write_xlsx(
        tmp_path / "xfd.xlsx", [("S", "worksheets/sheet1.xml", row(inline_cell("XFD1", "end")))]
    )
    doc = extract(path)
    assert doc.parts[0].rows == ("\t" * 16383 + "end",)
    assert doc.omissions == () and doc.parts[0].omissions == ()


def test_the_workbook_budget_has_its_own_name_and_can_move_alone():
    """Named, not inlined, and NOT an alias of `TEXT_MAX_BYTES` — the two bound different
    things (bytes read off a disk, bytes rendered out of a container), and a bar that varies
    one must not silently be varying the other."""
    assert docread.XLSX_MAX_TEXT_BYTES == 16 * 1024 * 1024
    source = (SRC / "bantamkit" / "docread.py").read_text(encoding="utf-8")
    assert "XLSX_MAX_TEXT_BYTES = 16 * 1024 * 1024" in source
    assert "XLSX_MAX_TEXT_BYTES = TEXT_MAX_BYTES" not in source


# -------------------------------------------------------------------------- (k) html, mhtml


def test_an_html_file_is_read_to_the_ceiling_and_says_how_much_it_left(tmp_path):
    """`extract_html` did `path.read_bytes()`: a 1 GB `.html` was held whole, where a 1 GB
    `.txt` stops at `TEXT_MAX_BYTES` and counts the rest. Same ceiling and the SAME SENTENCE —
    this reader states one number for "how much of a file I read", not one per container."""
    path = tmp_path / "big.html"
    path.write_bytes(("<html><body><p>first</p>" + "<p>row</p>\n" * 12).encode())
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", size - 40):
        doc = extract(path)
    assert doc.kind == "html"
    assert doc.parts[0].rows[0] == "first"
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions] == [
        (docread.OMIT_SIZE_CAP, 40, 40, f"{size} bytes on disk; this reader reads {size - 40}")
    ]


def test_an_mhtml_archive_is_read_to_the_ceiling_and_says_how_much_it_left(tmp_path):
    """`email.message_from_binary_file` reads the handle to EOF. The register named `:1254`
    off a grep and did not read the mhtml half line by line; read line by line here, it was
    unbounded too, in its own spelling — the whole file goes into the MIME parser."""
    path = write_mhtml(tmp_path / "big.mht")
    size = path.stat().st_size
    with monkeyed(docread, "TEXT_MAX_BYTES", size - 100):
        doc = extract(path)
    assert doc.kind == "mhtml"
    assert [(o.subject, o.count, o.size, o.what) for o in doc.omissions][0] == (
        docread.OMIT_SIZE_CAP,
        100,
        100,
        f"{size} bytes on disk; this reader reads {size - 100}",
    )


def test_the_cap_is_stated_before_what_was_seen_underneath_it(tmp_path):
    """An mhtml past the ceiling carries both omissions, and the CAP comes first: the media
    tally counts what the reader met *within* the cap, so a caller who reads that tally without
    the cap above it has read a number that is quietly a lower bound."""
    path = write_mhtml(tmp_path / "big.mht")
    with monkeyed(docread, "TEXT_MAX_BYTES", path.stat().st_size - 1):
        doc = extract(path)
    assert [o.subject for o in doc.omissions] == [docread.OMIT_SIZE_CAP, docread.OMIT_MEDIA]


def test_the_real_html_ceiling_is_the_one_plain_text_states(tmp_path):
    """At the SHIPPED constant, not a patched one: 16 MiB and a bit of markup reads 16 MiB and
    counts the rest. A ceiling only a monkeypatch has ever met is a ceiling nobody measured."""
    path = tmp_path / "huge.html"
    with path.open("wb") as handle:
        handle.write(b"<html><body><p>first</p>")
        block = b"<p>x</p>" * 4096  # 32 KiB a write
        written = 24
        while written <= TEXT_MAX_BYTES:
            handle.write(block)
            written += len(block)
    size = path.stat().st_size
    doc = extract(path)
    assert doc.parts[0].rows[0] == "first"
    assert [(o.subject, o.count, o.what) for o in doc.omissions] == [
        (
            docread.OMIT_SIZE_CAP,
            size - TEXT_MAX_BYTES,
            f"{size} bytes on disk; this reader reads {TEXT_MAX_BYTES}",
        )
    ]


# ---------------------------------------------------- (u) the two rebound CPython methods


def test_a_method_this_reader_cannot_rebind_is_contained_not_an_import_error(monkeypatch):
    """`_with_bounded_unescape` answers `None` rather than raising, for each of the three
    things it depends on that a future CPython may change: the method existing, the method
    resolving `unescape` as a MODULE GLOBAL, and the method carrying no closure.

    `runtime-py/pyproject.toml` declares `requires-python = ">=3.11"` while CI measures 3.11
    and 3.12, so every interpreter from 3.13 up is PERMITTED and none is measured. On one
    where either method is renamed or inlined, the pre-fix `getattr` raised `AttributeError`
    at MODULE IMPORT — the MCP server did not start, and the reader never got as far as
    refusing anything.
    """
    assert docread._with_bounded_unescape("no_such_method_exists") is None
    assert docread._with_bounded_unescape("__init__") is None  # `unescape` not in its names

    def closed_over():  # a `goahead` that resolves `unescape` through a CLOSURE
        unescape = str

        def goahead(self, end):
            return unescape("")

        return goahead

    monkeypatch.setattr(docread.html.parser.HTMLParser, "goahead", closed_over())
    assert docread._with_bounded_unescape("goahead") is None


def test_the_fallback_to_the_whole_markup_cap_is_observable():
    """The fallback is not a silent swallow: forcing it changes an answer a test can read.

    H1 measured this difference and refused the whole-markup rewrite as the DEFAULT because of
    it — `&#<4301 digits>;` inside `<xmp>` is CDATA the parser never unescapes, so the bounded
    binding keeps the digits where the whole-markup cap turns them into U+FFFD. That is the
    price of the fallback, stated rather than hidden, and it is the price of a reader that
    still answers instead of a package that will not import.
    """
    markup = "<xmp>&#" + "1" * 4301 + ";</xmp>"
    assert docread.HTML_UNESCAPE_BOUNDED is True
    assert docread.html_rows(markup) == ("&#" + "1" * 4301 + ";",)
    with monkeyed(docread, "HTML_UNESCAPE_BOUNDED", False):
        assert docread.html_rows(markup) == ("�",)


def test_the_package_still_imports_when_the_method_is_gone():
    """The claim is "the package imports", so it is proved by IMPORTING it — in a fresh
    interpreter with `HTMLParser.goahead` deleted before `bantamkit.docread` is loaded.
    In-process this would prove nothing: this module is already imported."""
    script = (
        "import html.parser\n"
        "del html.parser.HTMLParser.goahead\n"
        "import bantamkit.docread as d\n"
        "print(d.HTML_UNESCAPE_BOUNDED)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["False"]


# --------------------------------------------------------------- (w) a duplicate reference


def test_a_duplicate_cell_reference_is_disclosed_instead_of_dropped_in_silence(tmp_path):
    """MEASURED before the fix, on this exact fixture: `('second',)` and ZERO omissions.

    Last-wins is KEPT — it is what both runtimes do and what a writer's own later cell means.
    The silence is the defect: every other cell this reader cannot place is disclosed, and a
    cell it placed another cell on top of is a cell the rows do not carry.
    """
    body = row(inline_cell("A1", "first"), inline_cell("A1", "second"))
    doc = extract(write_xlsx(tmp_path / "dup.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("second",)
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_DUPLICATE_CELL, 1, ("A",), docread.DUPLICATE_CELL)
    ]
    assert docread.DUPLICATE_CELL == (
        "the text of a cell a later cell in the same row and column replaced"
    )


def test_the_duplicate_omission_never_echoes_the_files_own_reference(tmp_path):
    """`UNPLACED_SHAPE`'s rule, one omission over: `r` is whatever the file says, and an
    omission that echoed it would carry the file's bytes into the manifest with no bound at
    all. The column LETTER is derived and bounded; the reference is not."""
    ref = "A" * 4 + "1"  # past XFD, so it falls back to its XML position — column A twice
    body = row(inline_cell("A1", "first"), inline_cell(ref, "second"))
    doc = extract(write_xlsx(tmp_path / "echo.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    rendered = " ".join(o.what for o in doc.parts[0].omissions)
    assert "AAAA" not in rendered


def test_duplicates_are_counted_across_the_sheet_with_their_columns_in_order(tmp_path):
    """One omission for the sheet, columns in column order — the shape `number-format` and
    `unplaced-cell` already use, so a caller that renders one renders this one."""
    body = (
        row(inline_cell("C1", "a"), inline_cell("C1", "b"), inline_cell("C1", "c"))
        + row(inline_cell("A2", "d"), inline_cell("A2", "e"), index=2)
        + row(inline_cell("B3", "f"), index=3)
    )
    doc = extract(write_xlsx(tmp_path / "dups.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("\t\tc", "e", "\tf")
    assert [(o.subject, o.count, o.where, o.what) for o in doc.parts[0].omissions] == [
        (docread.OMIT_DUPLICATE_CELL, 3, ("A", "C"), docread.DUPLICATE_CELL)
    ]


def test_an_empty_cell_on_top_of_a_full_one_is_not_a_duplicate(tmp_path):
    """A cell with no text was never going to be in the rows, so it replaced nothing. Counting
    it would inflate the disclosure with cells nobody lost."""
    body = row(inline_cell("A1", "kept"), '<c r="A1" t="inlineStr"><is><t></t></is></c>')
    doc = extract(write_xlsx(tmp_path / "blank.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    assert doc.parts[0].rows == ("kept",)
    assert doc.parts[0].omissions == ()


def test_a_duplicate_renders_through_the_contract_layers_generic_line(tmp_path):
    """`contract._omission_line` has no branch for this subject and does not need one — the
    generic line prints an unknown subject's count rather than dropping it. Pinned here so the
    lag between the two layers stays a slightly generic sentence and never a lost count."""
    from bantamkit import contract

    body = row(inline_cell("A1", "first"), inline_cell("A1", "second"))
    doc = extract(write_xlsx(tmp_path / "dup.xlsx", [("S", "worksheets/sheet1.xml", body)]))
    line = contract._omission_line(
        contract.load_contract(), {"row_count": 1}, doc.parts[0].omissions[0].as_dict()
    )
    assert line == (
        "  NOT in those rows: 1 duplicate-cell (the text of a cell a later cell in the same "
        "row and column replaced)"
    )

