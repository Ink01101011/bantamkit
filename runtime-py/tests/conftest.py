import sys

import pytest

from bantamkit.client import Message, Response, ToolCall, Usage
from bantamkit.memory.layers import MEMORY_DIR_ENV

#: The one mark that opts out of `_no_ambient_memory_pin` below. Spelled once, here,
#: because a marker name duplicated between a fixture and the node it exempts is how the
#: two come to be talking about different marks.
REAL_PAIR_MARK = "realpair"


@pytest.fixture(autouse=True)
def _no_ambient_memory_pin(request, monkeypatch):
    """No node in this suite may be answered by -- or WRITE INTO -- a pinned store.

    `BANTAMKIT_MEMORY_DIR` outranks the whole discovery walk by design, so a
    developer who has set it -- which `docs/mcp.md` now tells every operator to do
    -- silently redirects every store this suite resolves.

    RE-MEASURED on this tree, because the first number aged badly: it was taken
    when the suite was 1790 and said `2 failed` in two files. Command, rerunnable:

        cp -R <a populated store> /tmp/pinrun
        BANTAMKIT_MEMORY_DIR=/tmp/pinrun PYTHONPATH=runtime-py/src \
            python -m pytest runtime-py/tests -q

    - guard intact: `1802 passed, 2 skipped, 2 xfailed`, byte-identical to an
      unpinned run, and `/tmp/pinrun` unchanged afterwards (`diff -rq`).
    - guard body deleted: `26 failed, 1776 passed` across FOUR files --
      `test_memory_component.py` (23), `test_memory_layers.py` (1, this fixture's
      own node), `test_mcpserver.py` (1), `test_memory.py` (1). Twenty-five of
      those are the pin's doing; the twenty-sixth is the node below noticing that
      the guard stopped guarding.
    - and the part no failure count shows: that run MUTATES the pinned store. Two
      fact files the suite invented (`a-fact.md`, `leaked-fact.md`) appear in it,
      and eight more files are rewritten -- recall stamps plus a rebuilt
      `index.md`. An operator who pins their real store and runs the suite has
      their memory written to. That is the cost this one line buys off.

    Session-wide and autouse, not per-module: the nodes that break live in four
    files, none of which is about pinning, and the next one will land in a fifth.
    A node that wants a pin sets one itself; `monkeypatch.setenv` inside the test
    body runs after this and wins.

    Watched by `test_memory_layers.py::test_the_ambient_pin_guard_reaches_this_
    node_without_being_asked` (kills `autouse=True`) and
    `::test_the_ambient_pin_guard_puts_back_the_store_a_pin_had_taken` (kills the
    body). Before those existed, both mutations left CI green, because CI has no
    ambient pin to delete.

    ONE EXEMPTION, and it is the opposite case rather than an exception to the rule.
    Every node this fixture is for asks a question about the CODE and must not be
    answered by the operator's environment. `test_memory_store_tripwire.py`'s
    `realpair` node asks a question about THE OPERATOR'S MACHINE -- do the two stores
    this machine actually writes agree -- and under a pin the store it writes IS the
    pinned one. Clearing the pin there does not isolate that node from the environment,
    it points it at a store nobody is using and lets it report clean, which is the exact
    false green the gate was built to prevent. Measured 2026-08-23: with the pin live and
    this fixture unconditional, the tripwire compares the abandoned repo store. So the
    mark is honoured here and pinned from the other side by
    `test_the_ambient_pin_survives_into_a_realpair_node`.
    """
    if REAL_PAIR_MARK in request.keywords:
        return
    monkeypatch.delenv(MEMORY_DIR_ENV, raising=False)


class FakeClient:
    """Scripted ModelClient: returns queued responses, records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        return self.responses.pop(0)


def assistant(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    return Response(
        message=Message(role="assistant", content=content, tool_calls=tool_calls or []),
        usage=Usage(prompt_tokens, completion_tokens),
    )


def call(name, arguments, id="c1"):
    return ToolCall(id=id, name=name, arguments=arguments)


# ---- W9: a scenario Windows cannot be put into, closed by name and PRICED ----
#
# USER DECISION (job 31): a POSIX-only scenario is closed with `skipif`, and the skip has
# to state in the node what it thereby FAILS TO MEASURE. RB-P51's rule is that a skip
# measures nothing, so it is a recorded cost and never a free out -- the reason string is
# where that cost is written down, and "POSIX only" does not write it down.
#
# WHAT QUALIFIES, AND WHAT DOES NOT. This marker is for a scenario the platform cannot be
# put INTO -- the harness raises before the code under test is reached, or the state it
# needs is not one a Windows process can be launched in. It is NOT for a scenario that
# constructs fine and whose OUTCOME nobody has measured yet: skipping that throws away the
# measurement the matrix exists to take, and the errno a platform reports is exactly the
# kind of thing that has to be read from a run rather than reasoned about. Every mark
# applied here names the measurement that proved the scenario impossible.

ON_WINDOWS = sys.platform == "win32"

WINDOWS_SKIP_TOKEN = "FAILS TO MEASURE on Windows"
"""The needle `test_the_windows_only_skips_do_not_fire_on_this_platform` searches for.

A `skipif` whose condition went true everywhere would be a deleted test wearing a
disguise -- green suite, node never executed, nobody told. That node evaluates every
condition carrying this token and requires them all FALSE off Windows, so the disguise
does not survive a run here.
"""


def windows_cannot_construct(*, because: str, unmeasured: str):
    """`pytest.mark.skipif` for a scenario Windows cannot be put into, with its bill attached.

    `because` is the platform fact AND the measurement that established it. `unmeasured`
    is the property this node would have pinned and now does not, phrased as the claim
    itself rather than as the node's name -- that is what a reader of `-rs` has to be able
    to act on.
    """
    return pytest.mark.skipif(
        ON_WINDOWS,
        reason=f"{because}. This run therefore {WINDOWS_SKIP_TOKEN}: {unmeasured}",
    )
