import sys

import pytest

from bantamkit.client import Message, Response, ToolCall, Usage
from bantamkit.memory.layers import MEMORY_DIR_ENV


@pytest.fixture(autouse=True)
def _no_ambient_memory_pin(monkeypatch):
    """No node in this suite may be answered by the operator's own pinned store.

    `BANTAMKIT_MEMORY_DIR` outranks the whole discovery walk by design, so a
    developer who has set it -- which `docs/mcp.md` now tells every operator to do
    -- silently redirects every store this suite resolves. Measured 2026-08-22 on
    this machine before this fixture existed: running the full suite with
    `BANTAMKIT_MEMORY_DIR` set to a populated store took it from 1790 passed to
    `2 failed, 1788 passed` -- `test_mcpserver.py::test_layered_recall_reads_
    granted_store_readonly` and `test_memory.py::test_start_discovers_the_project_
    store_and_never_the_profile`. Both are real nodes whose verdict came from the
    environment rather than from the code, which is the same defect as a node that
    reads the operator's real `~/.bantamkit`.

    Session-wide and autouse, not per-module: the two nodes that broke live in two
    files, neither of which is about pinning, and the next one will land in a third.
    A node that wants a pin sets one itself; `monkeypatch.setenv` inside the test
    body runs after this and wins.
    """
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
