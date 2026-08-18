#!/usr/bin/env python
"""Is a truncated run distinguishable from a complete one? Measured OUTSIDE pytest.

    .venv/bin/python docs/eval-data/2026-08-19-truncation-visibility-field-measurement.py .
    .venv/bin/python docs/eval-data/2026-08-19-truncation-visibility-field-measurement.py . \
        --mutate stop-instead-of-length

J3 of job `instrument-hygiene`, dated 2026-08-19. RB-P53's class, sites S4 and C-6.

WHAT IS BEING MEASURED, AND WHY IT IS A LATENT DEFECT AND NOT A CONTAMINATION.
The shape probe ranked nine call sites at which something was cut and nothing
recorded that it had been. Two of the nine are in this repository at this base:

  * S4, `client.py` (Layer 3): the endpoint's `usage` block is copied without
    validation and `finish_reason` does not appear in the file at all. A
    length-stopped completion and a finished one are the same object.
  * C-6, `agent.py` / `textutil.py` (Layer 1): a tool observation over the byte
    budget is cut and the cut is announced IN BAND, inside the string handed to
    the model, as `[truncated N bytes]`. The number is known at the truncation
    site and thrown away, so no column of any run says a run was cut.

NEITHER HAS CORRUPTED A COMMITTED NUMBER, and the negative is measured rather
than assumed. SHAPE N-7, run in this job: `tokens / model_calls` over 7,804 rows
across 78 committed files gives 1,770 distinct values, ZERO exact hits on any
power-of-two cap {512 … 32768}, and a per-call maximum of 2,625 — three orders of
magnitude below the windows in question. No committed row is sitting on a cap.
This program therefore measures a CODE PATH, not an artifact, and every claim it
makes is about what the code can and cannot report.

WHY THIS IS A FIELD MEASUREMENT AND NOT A TEST. RB-P28: the suite is not
evidence. This file is a standalone program in a fresh interpreter; it imports
nothing from `runtime-py/tests`, defines no fixture and no node, and asserts
`pytest not in sys.modules` before it measures — printed as line 1 of the report.

WHAT IT MAKES REAL AND WHAT IT DOES NOT. The HTTP half drives the real
`OpenAICompatible.chat` over an `httpx.MockTransport`, so the real request is
built, the real retry ladder is entered and the real `_parse` runs; only the
socket is fake. The loop half drives the real `Agent.run` with a scripted
`ModelClient` and a real tool handler, so the real `truncate` call at the real
observation budget does the cutting. It CANNOT make real: an endpoint that
actually clamps. The clamp is SIMULATED by a reply whose `prompt_tokens` equals
the declared window, which is exactly the shape RB-P53 measured on ollama's
`/v1` endpoint, and saying so is the point — the detector is being shown to fire
on that shape, not being shown to have caught a live clamp.

THE MUTATIONS CHANGE THE INPUT, NEVER A FLAG THE CONDITION READS. C-U5-2 measured
a sibling program whose 11 of 14 mutation modes moved nothing but the check line
they named, because the only consumer of the policy flag was the condition of its
own check. Every mode below instead changes what the stub endpoint says or what
the loop is given, so a check that survives its mutation survived a different
world and not a different boolean.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RULE = "=" * 78

# The value a machine-readable field takes when the attribute does not exist at
# all. It is a state, not a failure to look: `ABSENT` is what the BEFORE tree
# reports and it is the whole finding.
ABSENT = "ABSENT"

# The stub endpoint's declared context window. Any number would do; 4096 is the
# one RB-P53's own evidence sits on — 213 of 216 non-zero committed
# `summarizer_prompt_tokens_the_endpoint_saw` values are exact multiples of 4096.
WINDOW = 4096

# C-6's declared scenario. Two observations of 5,000 and 9,000 bytes, offered first
# against a budget that cuts both and then against one that cuts neither, so that the
# column has a positive case and a null control. Both are constants of the scenario and
# neither is recomputed from a mutation — see `measure_loop`.
CUT_BUDGET = 1000
UNCUT_BUDGET = 1_000_000

# Each mutation FALSIFIES one claim by changing the WORLD the claim is about, and
# must turn RED the check that claim NAMES.
MUTATIONS: dict[str, str] = {
    "stop-instead-of-length": "CHK-FINISH-REASON-CARRIED",
    "length-instead-of-stop": "CHK-A-FINISHED-CALL-IS-NOT-REPORTED-AS-CUT",
    "prompt-tokens-below-the-window": "CHK-PROMPT-TOKENS-AT-THE-WINDOW-ARE-VOID",
    "window-equals-prompt-tokens": "CHK-PROMPT-TOKENS-BELOW-THE-WINDOW-ARE-MEASURED",
    "declare-a-window-everywhere": "CHK-AN-UNDECLARED-WINDOW-IS-UNCHECKED",
    "aggregate-two-measured": "CHK-VOID-SURVIVES-AGGREGATION",
    "observations-under-budget": "CHK-OBSERVATION-DROP-IS-A-COLUMN",
    "one-observation-over-budget": "CHK-AN-UNCUT-RUN-READS-ZERO",
}


def _import_bantamkit(root: Path):
    sys.path.insert(0, str(root / "runtime-py" / "src"))
    import httpx
    from bantamkit.agent import Agent, ToolDef
    from bantamkit.client import (
        Message,
        OpenAICompatible,
        Response,
        Tool,
        ToolCall,
        Usage,
    )

    return httpx, Agent, ToolDef, Message, OpenAICompatible, Response, Tool, ToolCall, Usage


class Report:
    """Named checks and their machine-readable fields. Nothing asserts on prose.

    N-12, filed 2026-08-19: a sibling selfcheck reddened when a message string was
    reverted and stayed green when the ternary that assigned the classification was
    reverted. The claim named the classifier and the covered line was the formatter.
    So here the only thing a check compares is a FIELD, printed as `field=value`,
    and every sentence in this program is a note that no check reads.
    """

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []
        self.fields: list[tuple[str, dict]] = []

    def observe(self, case: str, **fields: object) -> None:
        self.fields.append((case, dict(fields)))

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append((name, passed, detail))


def _reply(finish_reason: str, prompt_tokens: int) -> dict:
    """One OpenAI-compatible chat completion, as a server would send it."""
    return {
        "id": "stub",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": "an answer"},
            }
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 11},
    }


def _call(httpx, OpenAICompatible, payload: dict, window: int | None):
    """Drive the real client against a stub socket. Returns (response, accepted).

    `accepted` is False when the constructor refuses a declared context window,
    which is the BEFORE tree's answer and is reported as a field rather than as an
    exception: a program that died here would report nothing about the other seven
    checks, and RB-P51 says an unmeasured thing is a verdict, not a crash.
    """
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    common = {
        "base_url": "http://stub.invalid/v1",
        "model": "stub-model",
        "transport": transport,
        "max_retries": 1,
    }
    accepted = True
    try:
        client = OpenAICompatible(context_window=window, **common)
    except TypeError:
        accepted = False
        client = OpenAICompatible(**common)
    try:
        return client.chat([_user_message("hello")]), accepted
    finally:
        client.close()


def _user_message(text: str):
    from bantamkit.client import Message

    return Message(role="user", content=text)


def _finish(usage) -> object:
    return getattr(usage, "finish_reason", ABSENT)


def _verdict(usage) -> object:
    return getattr(usage, "prompt_tokens_verdict", ABSENT)


def measure_transport(report: Report, mutate: str | None, httpx, OpenAICompatible) -> None:
    """S4. Four replies, one client each, every field read off the real response."""
    cut_reason = "stop" if mutate == "stop-instead-of-length" else "length"
    finished_reason = "length" if mutate == "length-instead-of-stop" else "stop"
    clamped_tokens = WINDOW - 1 if mutate == "prompt-tokens-below-the-window" else WINDOW
    below_window = 1000
    below_case_window = below_window if mutate == "window-equals-prompt-tokens" else WINDOW
    undeclared_window = WINDOW if mutate == "declare-a-window-everywhere" else None

    cut, accepted = _call(httpx, OpenAICompatible, _reply(cut_reason, below_window), WINDOW)
    clamped, _ = _call(httpx, OpenAICompatible, _reply("stop", clamped_tokens), WINDOW)
    undeclared, _ = _call(
        httpx, OpenAICompatible, _reply("stop", below_window), undeclared_window
    )
    finished, _ = _call(
        httpx, OpenAICompatible, _reply(finished_reason, below_window), below_case_window
    )

    report.observe(
        "S4-CUT",
        endpoint_said=cut_reason,
        client_reports=_finish(cut.usage),
        context_window_accepted=accepted,
    )
    report.observe(
        "S4-CLAMPED",
        endpoint_prompt_tokens=clamped_tokens,
        declared_window=WINDOW,
        client_reports=_verdict(clamped.usage),
    )
    report.observe(
        "S4-UNDECLARED",
        endpoint_prompt_tokens=below_window,
        declared_window=undeclared_window,
        client_reports=_verdict(undeclared.usage),
    )
    report.observe(
        "S4-FINISHED",
        endpoint_said=finished_reason,
        endpoint_prompt_tokens=below_window,
        declared_window=below_case_window,
        client_reports=_finish(finished.usage),
        prompt_tokens_verdict=_verdict(finished.usage),
    )

    report.check(
        "CHK-FINISH-REASON-CARRIED",
        _finish(cut.usage) == "length",
        "the endpoint stopped the generation on its cap and said so; the client "
        "carries " + repr(_finish(cut.usage)) + " (a length stop that the runtime "
        "cannot see is a shorter answer, not an unfinished one)",
    )
    report.check(
        "CHK-A-FINISHED-CALL-IS-NOT-REPORTED-AS-CUT",
        _finish(finished.usage) == "stop",
        "the null control on the same field: a completion that finished reports "
        + repr(_finish(finished.usage))
        + ", so the field is read from the reply and is not a constant",
    )
    report.check(
        "CHK-PROMPT-TOKENS-AT-THE-WINDOW-ARE-VOID",
        _verdict(clamped.usage) == "VOID",
        "prompt_tokens = " + str(clamped_tokens) + " against a declared window of "
        + str(WINDOW) + " -> " + repr(_verdict(clamped.usage)) + " (RB-P53: the "
        "endpoint reports the WINDOW, not the prompt, and the clamp is silent)",
    )
    report.check(
        "CHK-PROMPT-TOKENS-BELOW-THE-WINDOW-ARE-MEASURED",
        _verdict(finished.usage) == "MEASURED",
        "the null control on the same field: prompt_tokens = " + str(below_window)
        + " against a declared window of " + str(below_case_window) + " -> "
        + repr(_verdict(finished.usage)) + ", so VOID is not always-on",
    )
    report.check(
        "CHK-AN-UNDECLARED-WINDOW-IS-UNCHECKED",
        _verdict(undeclared.usage) == "UNCHECKED",
        "no window was declared, so nothing could be compared -> "
        + repr(_verdict(undeclared.usage))
        + " (RB-P51: unmeasured is a verdict, and it is not MEASURED)",
    )
    # The aggregation is where a per-call verdict either survives or is summed away.
    left = finished.usage
    right = finished.usage if mutate == "aggregate-two-measured" else clamped.usage
    total = left + right
    report.observe(
        "S4-AGGREGATE",
        left=_verdict(left),
        right=_verdict(right),
        summed=_verdict(total),
        prompt_tokens=total.prompt_tokens,
    )
    report.check(
        "CHK-VOID-SURVIVES-AGGREGATION",
        _verdict(total) == "VOID",
        "a measured call plus a void call sums to " + repr(_verdict(total))
        + "; a sum that contains a non-measurement is a non-measurement, and the "
        "run-level total is the number a reader will quote",
    )


def _scripted_client(Message, Response, ToolCall, Usage, calls: list[tuple[str, str]]):
    """A ModelClient that emits one batch of tool calls, then a final answer."""

    class ScriptedClient:
        def __init__(self) -> None:
            self.turn = 0

        def chat(self, messages, tools=None):
            self.turn += 1
            if self.turn == 1:
                return Response(
                    message=Message(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            ToolCall(id="c" + str(i), name=name, arguments={"key": key})
                            for i, (name, key) in enumerate(calls)
                        ],
                    ),
                    usage=Usage(10, 5),
                )
            return Response(
                message=Message(role="assistant", content="done"), usage=Usage(10, 5)
            )

    return ScriptedClient()


def measure_loop(
    report: Report, mutate: str | None, Agent, ToolDef, Tool, Message, Response, ToolCall, Usage
) -> None:
    """C-6. Two runs of the real loop: one whose observations are cut, one not."""
    blobs = {"big": "x" * 5000, "bigger": "y" * 9000}

    def handler(key: str) -> str:
        return blobs[key]

    tool = ToolDef(
        tool=Tool(
            name="fetch",
            description="return a blob",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        ),
        handler=handler,
    )

    def run(budget: int, keys: list[str]):
        agent = Agent(
            client=_scripted_client(
                Message, Response, ToolCall, Usage, [("fetch", k) for k in keys]
            ),
            tools=[tool],
            observation_budget=budget,
        )
        return agent.run("go")

    # THE EXPECTATION IS PINNED TO THE DECLARED SCENARIO, NOT RECOMPUTED FROM THE
    # MUTATED BUDGET. An earlier draft derived it from `cut_budget`, so raising the
    # budget moved the expectation and the reality together and the mutation falsified
    # nothing — the program's own exit-2 detector caught it (C-U5-2's shape: a check
    # whose expectation is a function of the thing being mutated is a tautology). The
    # numbers below are properties of the scenario this program declares.
    expected_bytes = sum(
        max(0, len(blobs[k].encode()) - CUT_BUDGET) for k in ("big", "bigger")
    )
    expected_count = sum(1 for k in ("big", "bigger") if len(blobs[k].encode()) > CUT_BUDGET)

    cut_budget = UNCUT_BUDGET if mutate == "observations-under-budget" else CUT_BUDGET
    cut = run(cut_budget, ["big", "bigger"])
    uncut_budget = CUT_BUDGET if mutate == "one-observation-over-budget" else UNCUT_BUDGET
    uncut = run(uncut_budget, ["big", "bigger"])

    cut_bytes = getattr(cut, "observation_bytes_dropped", ABSENT)
    cut_count = getattr(cut, "observations_truncated", ABSENT)
    uncut_bytes = getattr(uncut, "observation_bytes_dropped", ABSENT)
    uncut_count = getattr(uncut, "observations_truncated", ABSENT)

    report.observe(
        "C6-CUT",
        observation_budget=cut_budget,
        bytes_offered=sum(len(blobs[k].encode()) for k in ("big", "bigger")),
        expected_bytes_dropped=expected_bytes,
        expected_observations_truncated=expected_count,
        column_bytes_dropped=cut_bytes,
        column_observations_truncated=cut_count,
    )
    report.observe(
        "C6-UNCUT",
        observation_budget=uncut_budget,
        column_bytes_dropped=uncut_bytes,
        column_observations_truncated=uncut_count,
    )
    report.check(
        "CHK-OBSERVATION-DROP-IS-A-COLUMN",
        cut_bytes == expected_bytes and cut_count == expected_count,
        "two observations against a " + str(cut_budget)
        + "-byte budget: the run reports bytes_dropped=" + str(cut_bytes)
        + " truncated=" + str(cut_count) + " against " + str(expected_bytes) + " and "
        + str(expected_count) + " actually cut",
    )
    report.check(
        "CHK-AN-UNCUT-RUN-READS-ZERO",
        uncut_bytes == 0 and uncut_count == 0,
        "the null control: the same two observations under a "
        + str(uncut_budget) + "-byte budget report bytes_dropped=" + str(uncut_bytes)
        + " truncated=" + str(uncut_count) + ", so the column is not always-on",
    )


def _print_tautology_note() -> None:
    print()
    print("--- ONE CHECK THAT IS NOT SHIPPED, AND WHY (RB-P47) ---------------------------")
    print("  A check comparing the column against the `[truncated N bytes]` note already")
    print("  inside the observation string would be a TAUTOLOGY: both come from")
    print("  `len(raw) - budget` at the same site, so no input makes them disagree. What")
    print("  the column adds is not a second opinion about the number, it is the number")
    print("  being OUT of band -- in the run's accounting rather than only in the model's")
    print("  context, where nothing but the model ever reads it. That is the whole defect")
    print("  and a transcription check would not have measured it.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path, help="repository root (required, never defaulted)")
    parser.add_argument("--mutate", default=None)
    args = parser.parse_args(argv)

    if "pytest" in sys.modules:
        print("this is a FIELD measurement and refuses to run inside pytest", file=sys.stderr)
        return 2
    if args.mutate is not None and args.mutate not in MUTATIONS:
        print("unknown --mutate mode: " + str(args.mutate), file=sys.stderr)
        print("known modes: " + ", ".join(sorted(MUTATIONS)), file=sys.stderr)
        return 1

    root = args.repo_root.resolve()
    httpx, Agent, ToolDef, Message, OpenAICompatible, Response, Tool, ToolCall, Usage = (
        _import_bantamkit(root)
    )

    print(RULE)
    print("TRUNCATION VISIBILITY -- S4 (client.py, Layer 3) and C-6 (agent.py /")
    print("textutil.py, Layer 1). A code-path measurement, not an artifact audit:")
    print("SHAPE N-7 measured 7,804 committed rows and found no row on a cap.")
    print("pytest in sys.modules: " + str("pytest" in sys.modules) + " (must be False)")
    print("repo root: " + str(root))
    print("mutation: " + str(args.mutate))
    print(RULE)

    report = Report()
    measure_transport(report, args.mutate, httpx, OpenAICompatible)
    measure_loop(
        report, args.mutate, Agent, ToolDef, Tool, Message, Response, ToolCall, Usage
    )

    print()
    print("--- OBSERVED FIELDS ----------------------------------------------------------")
    for case, fields in report.fields:
        rendered = " ".join(k + "=" + str(v) for k, v in fields.items())
        print("FIELD case=" + case + " " + rendered)

    _print_tautology_note()

    print()
    print("--- NAMED CHECKS -------------------------------------------------------------")
    red = []
    for name, passed, detail in report.checks:
        print("CHECK name=" + name + " state=" + ("PASS" if passed else "RED"))
        print("      " + detail)
        if not passed:
            red.append(name)
    print()
    print(
        "SUMMARY checks=" + str(len(report.checks)) + " red=" + str(len(red))
        + " mutation=" + str(args.mutate)
    )
    print(RULE)

    if args.mutate is not None:
        expected = MUTATIONS[args.mutate]
        if expected in red:
            print("MUTATION " + repr(args.mutate) + " turned RED the check it names: " + expected)
            return 1
        print(
            "MUTATION " + repr(args.mutate) + " did NOT turn red " + expected + " -- the claim "
            "survived its own falsification, which means the claim is not measured. This is "
            "a FAILURE.",
            file=sys.stderr,
        )
        # 2, not 1. Returning 1 on both branches would pin the exit code to nothing:
        # 1 means the named check went red, 2 means the mutation falsified nothing.
        return 2
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
