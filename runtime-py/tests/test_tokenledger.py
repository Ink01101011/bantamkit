"""`token_ledger` (job46, AS-1(c)): the transcript ledger, engine and surface.

WHAT THIS FILE OWNS. `tools/conformance/suites/tokenledger.mjs` owns the PARITY — that Node
emits the same bytes. This file owns the properties one runtime can hold alone: the accounting
identity, the `requestId` dedupe across files, the walk order, the four refusals, the
registration, and the event log's silence about the paths and session ids it was handed.

THE FIXTURE IS ALWAYS A BUILT TREE OR THE COMMITTED CORPUS, NEVER `~/.claude/projects`. The
host's transcripts grow while a test runs — J46-1 measured two runs of one tool on one day
disagreeing because the session in between added a call — so a node reading them would fail for
a reason nobody caused. The committed corpus is the one this suite and the conformance suite
share, so a change to it is visible in both.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bantamkit import tokenledger
from bantamkit.pricing import MAX_SAFE_INT, PriceTableError

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "tools" / "ledger" / "fixtures" / "token-ledger" / "projects"

#: Every path segment, session id and cwd in a built fixture is a sentinel, so the privacy
#: node below can assert on the STRING rather than on a policy someone read.
SENTINEL = "SECRET-CORPUS-4c1b"

FIXED_MS = 1756029153412


def usage(**kw) -> dict:
    block = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    block.update(kw)
    return block


def record(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


# ------------------------------------------------------------------ the accounting identity


def test_every_line_is_counted_or_omitted_over_the_committed_corpus():
    """`lines == requests + sum(omission counts)`, over the tree the conformance suite reads.

    This is the property that makes a small total readable: it separates "your transcripts
    hold no usage" from "I skipped most of your transcripts". A reader who cannot tell those
    apart cannot act on either.
    """
    ledger = tokenledger.read(CORPUS)
    omitted = sum(o.count for o in ledger.omissions)
    assert ledger.lines == ledger.requests + omitted
    assert (ledger.lines, ledger.requests, omitted) == (19, 7, 12)


def test_the_identity_holds_when_nothing_at_all_is_counted(tmp_path):
    """The arm a corpus of interesting inputs never reaches: `requests` 0 and `lines` not."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text('{\n[]\n{"type": "assistant"}\n', encoding="utf-8")
    ledger = tokenledger.read(root)
    assert ledger.requests == 0
    assert ledger.lines == 3
    assert sum(o.count for o in ledger.omissions) == 3
    assert [o.subject for o in ledger.omissions] == [
        "unparsed-line",
        "not-an-object",
        "no-session-id",
    ]


def test_an_empty_corpus_answers_a_whole_document(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    ledger = tokenledger.read(root)
    assert (ledger.transcripts, ledger.lines, ledger.requests) == (0, 0, 0)
    assert ledger.sessions == ()
    assert ledger.omissions == ()
    assert ledger.totals == {cls: 0 for cls in tokenledger.TOKEN_CLASSES}
    assert ledger.cost is None


def test_a_blank_line_is_not_a_record(tmp_path):
    """The trailing newline every JSONL file ends with must not put a permanent off-by-one in
    the identity. Two records, three newlines, and a blank line in the middle for good
    measure."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        record(type="assistant", sessionId="s", requestId="r1", message={"usage": usage()})
        + "\n\n"
        + record(type="assistant", sessionId="s", requestId="r2", message={"usage": usage()})
        + "\n",
        encoding="utf-8",
    )
    ledger = tokenledger.read(root)
    assert (ledger.lines, ledger.requests) == (2, 2)
    assert ledger.omissions == ()


# ----------------------------------------------------------------------- the dedupe


def test_one_response_written_as_several_records_is_one_request(tmp_path):
    """The host writes a text block and a tool_use block carrying the SAME `usage`."""
    root = tmp_path / "projects"
    root.mkdir()
    one = record(
        type="assistant", sessionId="s", requestId="r1", message={"usage": usage(output_tokens=7)}
    )
    (root / "a.jsonl").write_text(one + "\n" + one + "\n" + one + "\n", encoding="utf-8")
    ledger = tokenledger.read(root)
    assert ledger.requests == 1
    assert ledger.totals["output_tokens"] == 7
    assert [(o.subject, o.count) for o in ledger.omissions] == [("duplicate-request", 2)]


def test_the_dedupe_spans_files_and_not_just_one(tmp_path):
    """THE CORRECTION over `tools/ledger/token-ledger.mjs`, which dedupes per FILE.

    A resumed session rewrites earlier records verbatim into a new file, so one request is on
    disk twice under two paths. A per-file `seen` set counts it twice; this one does not, and
    the second copy is REPORTED rather than dropped in silence.
    """
    root = tmp_path / "projects"
    root.mkdir()
    one = record(
        type="assistant", sessionId="s", requestId="r1", message={"usage": usage(output_tokens=7)}
    )
    (root / "a.jsonl").write_text(one + "\n", encoding="utf-8")
    (root / "b.jsonl").write_text(one + "\n", encoding="utf-8")
    ledger = tokenledger.read(root)
    assert ledger.requests == 1
    assert ledger.totals["output_tokens"] == 7
    assert [(o.subject, o.count, o.what) for o in ledger.omissions] == [
        ("duplicate-request", 1, "b.jsonl:1")
    ]


def test_what_names_the_first_site_and_counts_the_rest(tmp_path):
    """Bounded on purpose: a real corpus omits tens of thousands of lines under one subject."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text("{\n{\n{\n", encoding="utf-8")
    ledger = tokenledger.read(root)
    assert ledger.omissions[0].what == "a.jsonl:1 and 2 more"


# -------------------------------------------------------------- what counts as a record


def test_a_usage_missing_a_class_is_malformed_and_never_a_zero(tmp_path):
    """`pricing`'s rule about money, applied one layer earlier: a class defaulted to zero is a
    token invented. The host's OTHER usage keys are ignored, which is the other half."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        record(
            type="assistant",
            sessionId="s",
            requestId="r1",
            message={"usage": {"input_tokens": 1, "cache_read_input_tokens": 2}},
        )
        + "\n"
        + record(
            type="assistant",
            sessionId="s",
            requestId="r2",
            message={
                "usage": dict(
                    usage(input_tokens=4),
                    service_tier="standard",
                    iterations=[{"input_tokens": 4}],
                )
            },
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tokenledger.read(root)
    assert ledger.requests == 1
    assert ledger.totals["input_tokens"] == 4
    assert [(o.subject, o.count) for o in ledger.omissions] == [("malformed-usage", 1)]


def test_true_is_not_one_and_an_integral_float_is(tmp_path):
    """`isinstance(True, int)` is this runtime's hole and the port has no such hole, so `true`
    must be refused HERE for the two to agree. `7.0` is the opposite: indistinguishable from
    `7` there, so it must be accepted here."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        '{"type": "assistant", "sessionId": "s", "requestId": "r1", "message": {"usage": '
        '{"input_tokens": true, "cache_creation_input_tokens": 0, '
        '"cache_read_input_tokens": 0, "output_tokens": 0}}}\n'
        '{"type": "assistant", "sessionId": "s", "requestId": "r2", "message": {"usage": '
        '{"input_tokens": 7.0, "cache_creation_input_tokens": 0, '
        '"cache_read_input_tokens": 0, "output_tokens": 0}}}\n',
        encoding="utf-8",
    )
    ledger = tokenledger.read(root)
    assert ledger.requests == 1
    assert ledger.totals["input_tokens"] == 7
    assert [(o.subject, o.count) for o in ledger.omissions] == [("malformed-usage", 1)]


def test_a_bare_infinity_is_an_unparsed_line(tmp_path):
    """`json.loads` accepts the token and `JSON.parse` throws. Closed here, or the same file is
    a counted record on one runtime and an omission on the other."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        '{"type": "assistant", "sessionId": "s", "requestId": "r1", "message": {"usage": '
        '{"input_tokens": Infinity, "cache_creation_input_tokens": 0, '
        '"cache_read_input_tokens": 0, "output_tokens": 0}}}\n',
        encoding="utf-8",
    )
    ledger = tokenledger.read(root)
    assert ledger.requests == 0
    assert [(o.subject, o.count) for o in ledger.omissions] == [("unparsed-line", 1)]


def test_a_transcript_that_is_not_utf8_is_one_omission_and_not_a_crash(tmp_path):
    """One, not N: N is not knowable for bytes nobody can decode."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_bytes(b'{"type": "assistant", "sessionId": "\xff\xfe"}\n')
    ledger = tokenledger.read(root)
    assert (ledger.transcripts, ledger.lines, ledger.requests) == (1, 1, 0)
    assert [(o.subject, o.count, o.what) for o in ledger.omissions] == [
        ("undecodable-file", 1, "a.jsonl:1")
    ]


def test_a_file_that_is_not_a_transcript_is_not_read_and_not_omitted(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    (root / "notes.txt").write_text("not a transcript\n", encoding="utf-8")
    ledger = tokenledger.read(root)
    assert (ledger.transcripts, ledger.lines) == (0, 0)
    assert ledger.omissions == ()


# ------------------------------------------------------------------------ sessions


def test_a_subagent_lands_in_its_parent_session_and_says_so():
    """The asymmetry stated rather than discovered late: a subagent transcript carries the
    PARENT's `sessionId` with `isSidechain: true`, so its cost is the parent's and it is not a
    session of its own."""
    ledger = tokenledger.read(CORPUS)
    by_id = {s.session: s for s in ledger.sessions}
    assert by_id["s1"].sidechain_requests == 1
    assert by_id["s1"].requests == 5
    assert sum(s.sidechain_requests for s in ledger.sessions) == 1


def test_first_is_the_minimum_timestamp_and_not_the_first_line_seen():
    """`s1.jsonl` writes `r2` at 09:59 AFTER `r1` at 10:00:05, which is what the host does when
    a record is written out of order."""
    ledger = tokenledger.read(CORPUS)
    s1 = next(s for s in ledger.sessions if s.session == "s1")
    assert s1.first == "2026-09-10T09:59:00.000Z"
    assert s1.last == "2026-09-10T10:07:00.000Z"


def test_sessions_are_ordered_by_first_then_by_code_point():
    """The committed corpus holds two sessions with the SAME `first` and ids that sort one way
    by code point and the other by UTF-16 code unit. `！` (U+FF01) wins by code point;
    `.sort()` in the port would answer the astral one first."""
    ledger = tokenledger.read(CORPUS)
    assert [s.session for s in ledger.sessions] == ["s-！", "s-\U0001d11e", "s1"]


# ------------------------------------------------------------------------- the walk


#: Twelve names per directory rather than three, created in an order that is not their sorted
#: one. This node asserts SORTEDNESS, which it can do exactly; what it CANNOT do is guarantee
#: that an unsorted walk would look different, because that depends on what the filesystem
#: hands back. Twelve names in three directories makes a coincidence unlikely rather than
#: impossible, and the limit is stated here rather than left for someone to discover.
_WALK_NAMES = ["k", "c", "z", "a", "q", "m", "b", "y", "d", "n", "e", "l"]


def test_the_walk_is_sorted_by_name_at_every_level(tmp_path):
    """An unsorted walk makes the ANSWER depend on inode order: the walk decides which copy of
    a duplicated `requestId` is the one that counts."""
    root = tmp_path / "projects"
    (root / "b-dir").mkdir(parents=True)
    (root / "a-dir").mkdir()
    for name in _WALK_NAMES:
        for where in (root, root / "b-dir", root / "a-dir"):
            (where / f"{name}.jsonl").write_text("", encoding="utf-8")
    rels = [rel for _, rel in tokenledger._walk(root)]
    assert rels == sorted(rels)
    assert rels[0] == "a-dir/a.jsonl"
    assert rels[-1] == "z.jsonl"
    assert len(rels) == 36


def test_the_walk_over_the_committed_corpus_is_this_exact_sequence():
    """Spelled out rather than derived: the directory `s1` sorts BEFORE `s1.jsonl`, which sorts
    before `s1b.jsonl`, so the subagent transcript is read first and the resumed file last.
    That order is what decides which copy of `r2` is counted and which is the duplicate."""
    assert [rel for _, rel in tokenledger._walk(CORPUS)] == [
        "-proj-a/s1/subagents/agent-1.jsonl",
        "-proj-a/s1.jsonl",
        "-proj-a/s1b.jsonl",
        "-proj-b/bad.jsonl",
        "-proj-b/t.jsonl",
    ]


# ------------------------------------------------------------------------ the ceiling


def test_a_total_above_2_53_refuses_rather_than_answering_a_rounded_number(tmp_path):
    """The place the two runtimes would part company is a refusal, not a wrong answer: a JS
    `number` rounds past 2**53 and an `int` does not."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        record(
            type="assistant",
            sessionId="s",
            requestId="r1",
            message={"usage": usage(input_tokens=MAX_SAFE_INT)},
        )
        + "\n"
        + record(
            type="assistant",
            sessionId="s",
            requestId="r2",
            message={"usage": usage(input_tokens=1)},
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(tokenledger.TokenLedgerError) as caught:
        tokenledger.read(root)
    assert "input_tokens total exceeds 2**53-1" in str(caught.value)


def test_exactly_2_53_minus_one_is_accepted(tmp_path):
    """The boundary the refusal must not swallow: the ceiling is the largest legal answer."""
    root = tmp_path / "projects"
    root.mkdir()
    (root / "a.jsonl").write_text(
        record(
            type="assistant",
            sessionId="s",
            requestId="r1",
            message={"usage": usage(input_tokens=MAX_SAFE_INT)},
        )
        + "\n",
        encoding="utf-8",
    )
    assert tokenledger.read(root).totals["input_tokens"] == MAX_SAFE_INT


# ------------------------------------------------------------------------ refusals


def test_an_empty_root_is_refused_and_never_the_processs_own_cwd():
    """`Path("")` is `Path(".")`, so an empty root would read whatever directory the server
    happens to be standing in — a different answer per host, from an argument naming no
    directory at all."""
    with pytest.raises(tokenledger.TokenLedgerError) as caught:
        tokenledger.read("")
    assert str(caught.value) == "root must not be empty; name the directory of transcripts to read"


def test_a_missing_root_and_a_file_root_refuse_differently(tmp_path):
    missing = tmp_path / "nowhere"
    with pytest.raises(tokenledger.TokenLedgerError) as caught:
        tokenledger.read(missing)
    assert str(caught.value) == f"no such directory: {missing}"

    plain = tmp_path / "a.jsonl"
    plain.write_text("", encoding="utf-8")
    with pytest.raises(tokenledger.TokenLedgerError) as caught:
        tokenledger.read(plain)
    assert str(caught.value) == f"{plain} is a file, not a directory of transcripts"


def test_an_empty_model_is_refused_and_an_absent_one_asks_for_no_cost():
    """An absent model asks for no cost and gets no `cost` key. An empty string names no model
    and would otherwise be reported as "no rate recorded for model ''", which reads like a
    missing price rather than a missing argument."""
    assert tokenledger.read(CORPUS).cost is None
    with pytest.raises(tokenledger.TokenLedgerError) as caught:
        tokenledger.read(CORPUS, model="")
    assert str(caught.value) == "model must not be empty; name the model to price, or omit it"


# --------------------------------------------------------------------------- the cost


def test_the_shipped_table_answers_the_refusal_for_every_model():
    """THE NORMAL ANSWER, and the whole point of AS-1(b): `assets/pricing/default.json` ships
    with no rates, so a cost is `{"unavailable": ...}` until an operator records one with its
    date and its source. This is not an error path."""
    from bantamkit.pricing import price_table_path

    ledger = tokenledger.read(CORPUS, model="any-model", prices=price_table_path())
    assert ledger.cost is not None
    assert set(ledger.cost) == {"unavailable"}
    assert "no rate recorded for model 'any-model'" in ledger.cost["unavailable"]


def test_a_recorded_rate_prices_the_four_classes_separately(tmp_path):
    """One rate per model would average away a prompt that is 98 % `cache_read`, which is the
    direction that matters. So the answer carries a per-class breakdown and the total is the
    sum of the rounded parts."""
    table = tmp_path / "prices.json"
    table.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "currency": "USD",
                "unit": "micro_usd_per_million_tokens",
                "rates": {
                    "m": {
                        "recorded": "2026-09-11",
                        "source": "this test, which is not a price source",
                        "input_tokens": 3000000,
                        "cache_creation_input_tokens": 3750000,
                        "cache_read_input_tokens": 300000,
                        "output_tokens": 15000000,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    ledger = tokenledger.read(CORPUS, model="m", prices=table)
    assert ledger.cost["model"] == "m"
    assert ledger.cost["currency"] == "USD"
    assert set(ledger.cost["breakdown"]) == set(tokenledger.TOKEN_CLASSES)
    assert ledger.cost["micros"] == sum(ledger.cost["breakdown"].values())
    assert ledger.cost["amount"].count(".") == 1


def test_a_price_table_that_will_not_load_stops_rather_than_reporting_no_rate(tmp_path):
    """The split `pricing` draws: a broken table is an operator configuration fault that must
    name itself, an unpriced model is a normal answer a caller keeps working past."""
    table = tmp_path / "prices.json"
    table.write_text('{"schema_version": 1,', encoding="utf-8")
    with pytest.raises(PriceTableError):
        tokenledger.read(CORPUS, model="m", prices=table)


# ------------------------------------------------------------------ the MCP surface


mcp = pytest.importorskip("mcp")
from mcp import Client  # noqa: E402

from bantamkit.assets import load_tool_asset  # noqa: E402
from bantamkit.eventlog import EventLog  # noqa: E402
from bantamkit.mcpserver import build_server  # noqa: E402
from bantamkit.memory import Memory  # noqa: E402

SERVED_ORDER = [
    "memory_save",
    "memory_recall",
    "validate_json",
    "shiftwork_clock_in",
    "shiftwork_clock_out",
    "shiftwork_status",
    "build_identity",
    "bantamkit_status",
    "memory_compact",
    "bantamkit_read",
    "skill_audit",
    "memory_dream",
    "repo_map",
    "token_ledger",
]


def make(tmp_path):
    log = tmp_path / "log.jsonl"
    server = build_server(Memory(store=tmp_path / "store"), EventLog(log, clock=lambda: FIXED_MS))
    return server, log


def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines()]


def call(server, **args):
    """`(is_error, text)` — the refusals are ANSWERS here, not exceptions."""

    async def scenario():
        async with Client(server) as c:
            answer = await c.call_tool("token_ledger", args)
            return answer.is_error, answer.content[0].text

    return asyncio.run(scenario())


def test_the_tool_is_served_fourteenth_and_its_schema_is_the_asset(tmp_path):
    """Registration order IS served order, and the schema comes from the manifest.

    The index is pinned rather than `[-1]`: this node is about where `token_ledger` sits, and a
    later tool moving in behind it must not be able to satisfy it.
    """
    server, _ = make(tmp_path)

    async def scenario():
        async with Client(server) as c:
            listed = (await c.list_tools()).tools
            assert [t.name for t in listed] == SERVED_ORDER
            assert listed[13].name == "token_ledger"
            return listed[13]

    served = asyncio.run(scenario())
    manifest = load_tool_asset("token_ledger")
    assert served.description == manifest["description"]
    assert served.input_schema == manifest["parameters"]
    assert served.output_schema == manifest["output_schema"]


def test_the_reply_is_the_modules_own_document(tmp_path):
    """The tool adds not one byte: `as_json()` is the reply, so the conformance suite's
    comparison of that string is a comparison of what the model receives."""
    server, _ = make(tmp_path)
    is_error, text = call(server, root=str(CORPUS))
    assert not is_error
    assert tokenledger.read(CORPUS).as_json() in text


def test_the_four_refusals_reach_the_wire_as_answers(tmp_path):
    server, log = make(tmp_path)
    _, text = call(server, root="")
    assert "root must not be empty; name the directory of transcripts to read" in text

    missing = tmp_path / "nowhere"
    _, text = call(server, root=str(missing))
    assert f"no such directory: {missing}" in text

    plain = tmp_path / "a.jsonl"
    plain.write_text("", encoding="utf-8")
    _, text = call(server, root=str(plain))
    assert f"{plain} is a file, not a directory of transcripts" in text

    _, text = call(server, root=str(CORPUS), model="")
    assert "model must not be empty; name the model to price, or omit it" in text

    assert [r["outcome"] for r in records(log)] == ["refused"] * 4
    # A refusal carries no detail at all: `skill_audit`'s rule, and for the same reason — the
    # only facts available at this point are the caller's own arguments.
    assert all(r["detail"] == {} for r in records(log))


def test_a_broken_price_table_refuses_on_the_wire_and_does_not_crash(tmp_path):
    server, log = make(tmp_path)
    table = tmp_path / "prices.json"
    table.write_text('{"schema_version": 1,', encoding="utf-8")
    _, text = call(server, root=str(CORPUS), model="m", prices=str(table))
    assert f"price table is not valid JSON: {table}" in text
    assert [r["outcome"] for r in records(log)] == ["refused"]


def test_no_free_text_argument_reaches_the_event_log(tmp_path):
    """The paths, session ids and working directories this tool is handed are the operator's.

    `eventlog`'s rule is metadata only, and this is `token_ledger`'s half of it: the record
    carries four counts the host cannot see and not one string. Asserted on the raw BYTES of
    the log, over a corpus whose directory name, session id and `cwd` are all sentinels.
    """
    root = tmp_path / SENTINEL
    root.mkdir()
    (root / "a.jsonl").write_text(
        record(
            type="assistant",
            sessionId=f"{SENTINEL}-session",
            cwd=f"/w/{SENTINEL}",
            requestId=f"{SENTINEL}-request",
            message={"usage": usage(output_tokens=3)},
        )
        + "\n",
        encoding="utf-8",
    )
    server, log = make(tmp_path)
    is_error, text = call(server, root=str(root), model=f"{SENTINEL}-model")
    assert not is_error
    # The sentinels ARE in the reply — that is the answer the caller asked for.
    assert SENTINEL in text

    raw = log.read_bytes()
    assert SENTINEL.encode() not in raw
    assert [r["outcome"] for r in records(log)] == ["read"]
    assert records(log)[0]["detail"] == {
        "transcripts": 1,
        "lines": 1,
        "requests": 1,
        "sessions": 1,
    }
