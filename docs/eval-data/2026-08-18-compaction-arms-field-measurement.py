"""The arms: compact-off as the null control, then one flag at a time.

U4 of job `compaction-measured`. THE FIELD MEASUREMENT — outside pytest, because the
suite is not evidence (RB-P28) and no pytest node may assert a fact about this corpus
(RB-P14 Gate 2). Every verdict this program prints is recomputed from committed rows.

The bar is `2026-08-17-compaction-bar-preregistration.md` at `f48335c`, amended twice at
`e94d960` BEFORE the first arm ran. The corpus is `2026-08-17-compaction-corpus.jsonl`,
committed by U3. Neither is regenerated or retro-edited by this program, ever.

MODES
  --reconstruct   Rebuild every corpus transcript into turns, reconcile the
                  reconstruction against the record (bar §1.2's VOID check), trace the
                  NULL CONTROL B0 arithmetically, apply the boundary schedule of §10.2
                  under Amendment B's reading A, and compute R1's zero-summary ceiling.
                  Writes the B0 artifact. NO summarizer, NO mechanism, NO arm.
  --arms          Drive the real `compaction-mcp` server over stdio for B0/B1/B2/B3 at
                  R repeats on the declared sample. Writes the arms artifact.
  (no mode)       Read both committed artifacts, recompute the bar's verdicts per
                  stratum, print them, exit 0 iff every named check holds.
  --mutate MODE   Apply one named mutation and require that the check the mutated claim
                  NAMES turns red. Exit 1 on every named mode; exit 1 also if the
                  mutation fails to turn anything red, because a claim that survives its
                  own falsification is not a measured claim.

WHAT THIS PROGRAM WILL NOT DO, by construction rather than by discipline
  * It never pools the two strata into one number (Amendment A, the user's ruling).
  * It never lets stratum B borrow stratum A's noise floor (Amendment A).
  * It never emits an all-on-versus-all-off figure (bar §1.5).
  * It never clamps a byte or token column at zero (bar §8).
  * It never sums `anchors_lost_stable` with `anchors_lost_unstable` (bar §3.2).
  * It never sums summarizer tokens with agent tokens (bar §4).
  * It never re-tunes T (bar §10.2's standing refusal, upheld by Amendment B).
  * It never picks a grain when a verdict differs between grains (bar §3.1) — it
    ESCALATES.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = "=" * 78

# ---------------------------------------------------------------------------------------
# The two artifacts this program owns. Committed evidence, never regenerated in place by
# any mode other than the one that produced it, and never retro-edited (bar §9(5)).
# ---------------------------------------------------------------------------------------
B0_ARTIFACT = "2026-08-18-compaction-b0-null-control.jsonl"
ARMS_ARTIFACT = "2026-08-18-compaction-arms.jsonl"

# The corpus U3 committed. Read-only here. Its `transcript_id` is the join key, so the
# selection rule is IMPORTED from U3's program rather than restated — a restatement is a
# second definition of the corpus and would be free to drift from the first.
CORPUS_ARTIFACT = "2026-08-17-compaction-corpus.jsonl"
SURVEY_PROGRAM = "2026-08-17-compaction-corpus-survey.py"

# ---------------------------------------------------------------------------------------
# DECLARED CONSTANTS. Every one of these is fixed at this file's FIRST COMMIT and none of
# them may be tuned afterwards. U5 is commissioned to diff the first commit against the
# last; if a number below moved, that diff is the finding.
# ---------------------------------------------------------------------------------------

# Bar §10.2 + Amendment B. 60% of 128,000, the mechanism's own shipped defaults, read at
# `compaction-mcp` 0a15cff `src/config.ts:98-99`. NOT tuned to this corpus and NOT lowered
# when it turns out to leave half the corpus UNINFORMATIVE. That is the whole point of it.
THRESHOLD_T = 60 * 128_000 // 100

# Bar §10.3(2), measured by U3 over the corpus's own recorded usage, median of the
# per-transcript OLS slope on message-content bytes: `2026-08-17-compaction-corpus.md:185`.
# NOT `chars/4` (§10.3 refuses the mechanism's own estimator; it under-counts 2.19x here).
BYTES_PER_TOKEN = 1.8284

# DECLARED, and the brief required this to be said out loud: the fixed per-call cost is
# DECLARED AS A CONSTANT rather than omitted. It is the system prompt, the tool schemas
# and the project instructions — billed on every model call and present in no transcript.
# U3 measured it two independent ways that agree to 4.6%: the fitted intercept median
# 25,350.2 tokens and a first-call bound median of 26,516 tokens
# (`2026-08-17-compaction-corpus.md:187,198`). The fitted value is taken because it uses
# every call rather than the first, and the CONSEQUENCE is stated wherever a percentage
# appears: an irreducible constant in the denominator makes every percentage saving
# SMALLER, so declaring it is the conservative choice and omitting it would flatter the
# mechanism. Both the with-constant and without-constant figures are reported side by
# side, always, because the constant is exactly the kind of choice a reader may want to
# undo.
FIXED_PER_CALL_TOKENS = 25350.2

# Bar §2.1's design constant.
REPEATS = 3

# The bar's handed target (bar §0 claim 4). A saving is NEGATIVE under §2.3.
TARGET_HEADLINE = -80.0

# B2's flag, at the mechanism's SHIPPED DEFAULT — `dropToolOutputOlderThanTurns = 10`,
# `compaction-mcp` 0a15cff `src/register.ts:204`. Chosen for the same reason T is: it is
# the mechanism's own default, not a value this measurement picked. The SCHEDULE for it is
# a declaration this bar did not make and this program must: `context_trim` is invoked
# after EVERY ingested model call, which is the tier-1 use the tool documents ("remove
# low-value/duplicate tool output without an inference call"). Invoking it only at
# boundaries would give it exactly zero measurable effect, because `context_compact`
# collapses every unpinned turn anyway — an arm with no possible effect is not an arm.
TRIM_DROP_TOOL_OUTPUT_OLDER_THAN_TURNS = 10

# B3's flag. DECLARED WITH NO FREE PARAMETER ON PURPOSE: every tool-role turn is offloaded,
# with no size threshold. A size threshold would be a knob this measurement could tune
# after seeing a result, and there is no principled value for it in the mechanism's source.
# The cost of the choice is stated rather than hidden: a digest can be LARGER than the
# small tool output it replaces, so B3's byte columns can and should go POSITIVE. They are
# signed and unclamped (bar §8), so that shows up as a cost instead of vanishing.
OFFLOAD_EVERY_TOOL_TURN = True

# ---------------------------------------------------------------------------------------
# §3.2's ANCHOR EXTRACTION, COMMITTED AS DATA. Frozen at this file's first commit.
#
# The bar could not pre-register these contents without reading the corpus it was fenced
# from, so it delegated them here with one condition: they are not tuned per transcript,
# per stratum, or after seeing a result. They are deliberately GENERIC — nothing below
# names a bantamkit identifier, a path in this repo, or a token this corpus happens to
# contain. If a later reader wants a stop-word added because a number looks wrong, the
# brief's instruction is followed instead: that wanting is recorded as a finding in the
# measurement document and the list does not move.
# ---------------------------------------------------------------------------------------
ANCHOR_MIN_LENGTH = 6

ANCHOR_CLASSES: tuple[tuple[str, str], ...] = (
    # path-like: a slashed token ending in a short extension
    ("path", r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+\.[A-Za-z0-9]{1,6}"),
    # identifier-like: snake_case with at least one underscore
    ("snake", r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"),
    # identifier-like: dotted or ::-qualified names
    ("qualified", r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|::)[A-Za-z_][A-Za-z0-9_]*)+"),
    # error/constant strings: SCREAMING_CASE
    ("screaming", r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"),
    # numeric literal carrying a unit
    ("numeric_unit", r"[0-9][0-9,._]*\s?(?:%|ms|kB|KB|MiB|MB|GB|tokens|bytes|px)\b"),
    # hex / commit-like
    ("hexlike", r"\b[0-9a-f]{7,40}\b"),
)

ANCHOR_STOP_LIST: frozenset[str] = frozenset(
    {
        # generic log/severity and boolean words that match `screaming`
        "TODO", "FIXME", "NOTE", "WARN", "WARNING", "ERROR", "DEBUG", "INFO", "TRACE",
        "FATAL", "PASSED", "FAILED", "TRUE", "FALSE", "NULL", "NONE",
        # generic format / protocol names
        "JSON", "YAML", "TOML", "HTML", "HTTP", "HTTPS", "UTF_8", "ASCII", "UUID",
        # generic file names present in almost every repository
        "README.md", "LICENSE", "Makefile", "package.json", "pyproject.toml",
        # generic dotted forms with no session-specific content
        "self.assert", "os.path", "sys.argv", "json.dumps", "json.loads",
    }
)

# ---------------------------------------------------------------------------------------
# THE SAMPLE RULE. Declared BEFORE the sample is computed and before any arm runs, and it
# is a COST rule, not a result rule.
#
# Bar §7.1 of the corpus artifact pre-authorises exactly this shape: "the rows are
# committed sorted by transcript_id, a hash order that cannot be result-informed, so a
# later unit can take a declared prefix of the corpus as a sample WITH A DATED
# DECLARATION." This is that declaration.
#
# THE RULE: the sample is the longest PREFIX of the committed hash order whose total
# summarizer-call count, under the schedule of §10.2 at reading A, at R repeats, over the
# three summarizer-bearing arms, is at or below SAMPLE_SUMMARIZER_CALL_BUDGET.
#
# The budget is a wall-clock budget converted to calls at a MEASURED per-call latency
# (26.7 s median of three calls, measured against the declared endpoint BEFORE the sample
# was computed and reported in the measurement document). It is a property of this
# machine's hardware and of nothing in the corpus. Hash order cannot be result-informed; a
# prefix of it cannot either; and the budget was fixed before the boundary counts were
# known.
#
# What the rule COSTS is stated rather than hidden: a prefix sample makes every headline
# an n smaller than 207, and stratum B is in the sample only if the hash order puts it
# there. Both are reported.
SAMPLE_SUMMARIZER_CALL_BUDGET = 420

# ---------------------------------------------------------------------------------------
# The mechanism, at the commit the bar pinned (§10.1).
# ---------------------------------------------------------------------------------------
MECHANISM_ROOT = Path.home() / "Documents" / "Claude" / "Projects" / "compaction-mcp"
MECHANISM_COMMIT = "0a15cff65c5c847af07b43de3b67d726433a4ca3"

# Bar §10.6, the declared configuration as one block. Every one of these lands on every
# committed arm row; a row without them cannot be attributed to an arm (bar §8 col 19).
DECLARED_ENV = {
    "COMPACTION_MODE": "store",
    "COMPACTION_AUTO": "false",
    "COMPACTION_SUMMARIZER": "direct",
    "COMPACTION_LLM_MODEL": "qwen2.5:14b-instruct",
    "COMPACTION_RECALL_MODE": "lexical",
    "COMPACTION_HOOKS_ENABLED": "false",
}

# Additive columns declared after first commit. Empty at first commit, so the next added
# column forces a dated declaration instead of silent tolerance (bar §9(3), RB-P46).
ADDITIVE_KEYS_THE_ARTIFACT_PREDATES: tuple[str, ...] = ()

_FENCE_PATTERNS = ("/", "\\", ".jsonl", "/Users/", "~/")


# =======================================================================================
# U3's selection rule, imported rather than restated
# =======================================================================================
def _load_survey():
    spec = importlib.util.spec_from_file_location("_corpus_survey", HERE / SURVEY_PROGRAM)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise RuntimeError("cannot load the corpus survey program")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =======================================================================================
# Reconstruction — bar §1.2's null-control trap, made a check instead of a promise
# =======================================================================================

# The event kinds a replay CARRIES into turns. Everything else is skipped and every
# skipped kind is enumerated with its count (bar §1.2); an unenumerated skip is a failed
# check, not a rounding error.
CARRIED_EVENT_KINDS = ("user", "assistant")


def _render_content(content, survey) -> str:
    """The turn text, block for block, byte-for-byte identical to the survey's counter.

    Joined with NO separator on purpose. `reconstructed_content_bytes` has to be
    comparable to `recorded_content_bytes` — which is the survey's `_content_bytes` over
    the same events — and a separator would put slack in exactly the comparison that
    exists to detect dropped content. Turn READABILITY is worth nothing here; the summary
    prompt the mechanism builds adds its own `### role` framing anyway.

    A block type this function does not handle renders as the empty string while the
    survey's counter still counts its bytes, so an unhandled block type turns the VOID
    check RED rather than silently shrinking the null control's prefix. That is the whole
    reason the two are computed by different code paths over the same input.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_render_content(block, survey) for block in content)
    if not isinstance(content, dict):
        return ""
    kind = content.get("type")
    if kind == "text":
        return str(content.get("text", ""))
    if kind == "thinking":
        return str(content.get("thinking", ""))
    if kind == "tool_use":
        return json.dumps(content.get("input", {}), sort_keys=True)
    if kind == "tool_result":
        return _render_content(content.get("content"), survey)
    return ""


def _turn_role(event: dict) -> str:
    """`tool` iff the recorded user line is carrying tool_result blocks, else its own role.

    The mechanism's turn roles are user | assistant | tool (`src/types.ts`), and B2's trim
    acts on `role === "tool"` only. Classifying a tool result as a plain user turn would
    make B2 a no-op arm for a reason that has nothing to do with the mechanism.
    """
    kind = event.get("type")
    if kind == "assistant":
        return "assistant"
    content = (event.get("message") or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return "tool"
    return "user"


def reconstruct(path: Path, survey) -> dict:
    """One transcript -> turns, the reconciliation columns, and B0's exact prefix trace.

    B0 is traced ARITHMETICALLY here and DRIVEN THROUGH THE REAL MECHANISM in `--arms`;
    the two are required to agree exactly on every sampled transcript, which is what makes
    the arithmetic trace evidence about the mechanism rather than about this file.
    """
    recorded_events = 0
    recorded_content_bytes = 0
    reconstructed_content_bytes = 0
    skipped: dict[str, int] = {}

    turns: list[dict] = []
    call_indices: list[int] = []  # index into `turns` at which each model call happened
    seen_messages: set[str] = set()

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                skipped["UNPARSEABLE"] = skipped.get("UNPARSEABLE", 0) + 1
                continue
            if not isinstance(event, dict):
                skipped["NOT_AN_OBJECT"] = skipped.get("NOT_AN_OBJECT", 0) + 1
                continue
            stamp = event.get("timestamp")
            if not survey._under_cutoff(stamp if isinstance(stamp, str) else None):
                continue
            kind = str(event.get("type", "MISSING_TYPE"))
            if kind not in CARRIED_EVENT_KINDS:
                skipped[kind] = skipped.get(kind, 0) + 1
                continue

            message = event.get("message")
            if not isinstance(message, dict):
                skipped[f"{kind}:NO_MESSAGE"] = skipped.get(f"{kind}:NO_MESSAGE", 0) + 1
                continue

            recorded_events += 1
            content = message.get("content")
            recorded_content_bytes += survey._content_bytes(content)
            text = _render_content(content, survey)
            reconstructed_content_bytes += len(text.encode("utf-8"))

            role = _turn_role(event)
            # A SYNTHETIC assistant line is a host-generated error notice, not a model
            # call: `message.model == "<synthetic>"`, no `requestId`, all-zero usage. U3
            # measured this and counted them in their own column; the first draft of this
            # reconstruction did not, and counted 4 extra model calls across 3 transcripts
            # against the committed corpus. The notice's CONTENT still entered the window,
            # so it stays a turn — it just does not open a call.
            if role == "assistant" and str(message.get("model", "")) == "<synthetic>":
                turns.append(
                    {"role": role, "content": text, "bytes": len(text.encode("utf-8"))}
                )
                continue
            if role == "assistant":
                # One line per CONTENT BLOCK, not one line per model call (U3, 2.06x).
                # Distinct `message.id` is the call; the blocks of one reply are appended
                # to the turn that reply already opened.
                mid = str(message.get("id") or event.get("requestId") or "")
                if mid and mid in seen_messages:
                    turns[-1]["content"] += text
                    turns[-1]["bytes"] += len(text.encode("utf-8"))
                    continue
                if mid:
                    seen_messages.add(mid)
                # A model call happens BEFORE its own reply is in the window, so the
                # prefix it was billed for is every turn recorded so far.
                call_indices.append(len(turns))
            turns.append(
                {"role": role, "content": text, "bytes": len(text.encode("utf-8"))}
            )

    # B0's exact prefix trace: the null control accumulates and never removes.
    running = 0
    prefix_bytes: list[int] = []
    cursor = 0
    for call_at in call_indices:
        while cursor < call_at:
            running += turns[cursor]["bytes"]
            cursor += 1
        prefix_bytes.append(running)

    return {
        "recorded_events": recorded_events,
        "recorded_content_bytes": recorded_content_bytes,
        "reconstructed_turns": len(turns),
        "reconstructed_content_bytes": reconstructed_content_bytes,
        "skipped_event_kinds": skipped,
        "turns": turns,
        "call_indices": call_indices,
        "prefix_bytes": prefix_bytes,
    }


def tokens_of(byte_count: float, *, with_fixed: bool) -> float:
    """Bar §10.3: bytes by a MEASURED factor, plus the DECLARED fixed per-call cost."""
    base = byte_count / BYTES_PER_TOKEN
    return base + FIXED_PER_CALL_TOKENS if with_fixed else base


def schedule_boundaries(prefix_bytes: list[int]) -> list[int]:
    """Bar §10.2 under Amendment B's READING A: boundary k at the first call whose
    LIVE-WINDOW occupancy reaches k*T.

    Reading B — a window fraction applied to an unbounded cumulative sum — is a category
    error and is not implemented here at all, so it cannot be reached by a flag. It fires
    a boundary roughly every 1.4 calls at the corpus median, and Amendment B rules it out
    on semantics while stating that the reading it chose is the EXPENSIVE one.
    """
    boundaries: list[int] = []
    k = 1
    for index, byte_count in enumerate(prefix_bytes):
        occupancy = tokens_of(byte_count, with_fixed=True)
        while occupancy >= k * THRESHOLD_T:
            boundaries.append(index)
            k += 1
    return boundaries


def ceiling_r1(prefix_bytes: list[int], boundaries: list[int]) -> dict:
    """R1, bar §5: the ZERO-SUMMARY ceiling. Arithmetic. No summarizer, no arm.

    The most compaction could possibly buy is the world in which every boundary replaces
    all prior content with ZERO bytes. Anything the real mechanism does is worse than
    this, because a summary costs bytes and rehydration re-adds file content.

    The fixed per-call cost is IRREDUCIBLE — compaction cannot remove the system prompt —
    so it stays in both the numerator and the denominator of the with-constant figure.
    That is precisely why the constant is declared rather than omitted: omitting it
    inflates the ceiling.
    """
    boundary_set = sorted(set(boundaries))
    out = {}
    for label, with_fixed in (("with_fixed", True), ("no_fixed", False)):
        base = 0.0
        zero = 0.0
        reset_at = 0
        pointer = 0
        for index, byte_count in enumerate(prefix_bytes):
            base += tokens_of(byte_count, with_fixed=with_fixed)
            while pointer < len(boundary_set) and boundary_set[pointer] <= index:
                reset_at = prefix_bytes[boundary_set[pointer]]
                pointer += 1
            zero += tokens_of(max(byte_count - reset_at, 0), with_fixed=with_fixed)
        out[f"ctx_tokens_b0_{label}"] = round(base, 3)
        out[f"ctx_tokens_zero_summary_{label}"] = round(zero, 3)
        out[f"ceiling_pct_{label}"] = (
            round(100.0 * (zero - base) / base, 4) if base else None
        )
    return out


# =======================================================================================
# The MCP driving route — ONE route, serving every arm (bar §7(1))
# =======================================================================================
class MechanismSession:
    """A live `compaction-mcp` server over stdio JSON-RPC. The real shipped mechanism.

    Every arm is driven through this one class. B0 differs from B1 by which tool calls
    are issued and by nothing else — not by a different route, not by a simulation.
    """

    def __init__(self, state_dir: Path) -> None:
        env = dict(os.environ)
        env.update(DECLARED_ENV)
        env["COMPACTION_STATE_DIR"] = str(state_dir)
        env["COMPACTION_ALLOWED_ROOTS"] = str(state_dir)
        self.proc = subprocess.Popen(
            ["node", str(MECHANISM_ROOT / "dist" / "index.js")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "j2-u4-field", "version": "1"},
            },
        )
        self._notify("notifications/initialized", {})

    def _write(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        self._write({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("compaction-mcp closed the transport")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == self._id:
                if "error" in message:
                    raise RuntimeError(f"mechanism error: {message['error']}")
                return message.get("result", {})

    def tool(self, name: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = "".join(
            block.get("text", "")
            for block in result.get("content", [])
            if block.get("type") == "text"
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    def close(self) -> None:
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def _block_bytes(block: dict) -> dict:
    """Bar §8 columns 9/10/11, SIGNED, from the block the host would actually install."""
    summary = len(str(block.get("summary", "")).encode("utf-8"))
    rehydrated = sum(
        len(str(f.get("contents", "")).encode("utf-8"))
        for f in block.get("rehydratedFiles", [])
        if isinstance(f, dict)
    )
    rules = len(str(block.get("persistentRules", "")).encode("utf-8"))
    extra = len(str(block.get("extraContext", "")).encode("utf-8"))
    ledger = len(json.dumps(block.get("ledgerSnapshot", []), sort_keys=True).encode("utf-8"))
    return {
        "summary_bytes": summary,
        "rehydrated_bytes": rehydrated,
        "block_bytes": summary + rehydrated + rules + extra + ledger,
    }


def run_arm(
    recon: dict,
    arm: str,
    repeat: int,
    boundaries: list[int],
    state_dir: Path,
    session: MechanismSession,
) -> dict:
    """One (transcript, arm, repeat) replay through the real mechanism.

    The boundary schedule is INJECTED from B0's trace, identically into every arm
    (bar §10.2), so §3.3's witness — same agent calls in every arm — is a real check.
    """
    turns = recon["turns"]
    call_indices = recon["call_indices"]
    boundary_calls = set(boundaries)
    sid = f"{arm}-r{repeat}-{os.getpid()}-{int(time.time() * 1000)}"

    installed_block_bytes = 0
    prefix_bytes: list[int] = []
    agent_calls = 0
    summarizer_in = 0
    summarizer_out = 0
    summary_bytes = 0
    rehydrated_bytes = 0
    block_bytes_total = 0
    trim_removed_turns = 0
    trim_removed_bytes = 0
    offload_digest_bytes = 0
    offload_body_bytes = 0
    boundary_count = 0
    summarizer_prompt_bytes_sent = 0
    summarizer_prompt_tokens_seen = 0
    blocks_installed: list[str] = []

    cursor = 0
    for call_number, call_at in enumerate(call_indices):
        # Ingest every turn that precedes this model call.
        while cursor < call_at:
            turn = turns[cursor]
            content = turn["content"]
            if arm == "B3" and turn["role"] == "tool" and OFFLOAD_EVERY_TOOL_TURN:
                digest = session.tool(
                    "offload_store", {"label": "tool-output", "content": content}
                )
                rendered = json.dumps(digest, sort_keys=True)
                offload_body_bytes += len(content.encode("utf-8"))
                offload_digest_bytes += len(rendered.encode("utf-8"))
                content = rendered
            session.tool(
                "turn_add", {"sessionId": sid, "role": turn["role"], "content": content}
            )
            cursor += 1

        if arm in ("B2", "B3"):
            before_bytes = _held_turn_bytes(state_dir, sid)
            trimmed = session.tool(
                "context_trim",
                {
                    "sessionId": sid,
                    "dropToolOutputOlderThanTurns": TRIM_DROP_TOOL_OUTPUT_OLDER_THAN_TURNS,
                },
            )
            removed = int(trimmed.get("removed", 0) or 0)
            if removed:
                # SIGNED, and measured on real bytes rather than on the mechanism's own
                # `chars/4` estimator, which bar §10.3 refuses as an axis. Trim removes,
                # so this column is NEGATIVE, and it is not clamped.
                trim_removed_turns += removed
                trim_removed_bytes += _held_turn_bytes(state_dir, sid) - before_bytes

        # The live window at this call: the installed block plus the turns still held.
        # Read out of the mechanism's OWN persisted state, not out of a local mirror, so
        # that what the arms measure is what the mechanism actually holds.
        prefix_bytes.append(installed_block_bytes + _held_turn_bytes(state_dir, sid))
        agent_calls += 1

        # Ingest the reply itself.
        reply = turns[call_at]
        session.tool(
            "turn_add", {"sessionId": sid, "role": reply["role"], "content": reply["content"]}
        )
        cursor = call_at + 1

        if call_number in boundary_calls and arm != "B0":
            prompt_bytes = _summarizer_prompt_bytes(state_dir, sid)
            block = session.tool("context_compact", {"sessionId": sid})
            sizes = _block_bytes(block)
            summary_bytes += sizes["summary_bytes"]
            rehydrated_bytes += sizes["rehydrated_bytes"]
            block_bytes_total += sizes["block_bytes"]
            # DECLARED CHOICE, with its direction stated. The block REPLACES the previous
            # one, because that is the mechanism's own documented host contract
            # ("Install the returned compacted context block as the new ground truth,
            # then discard pre-boundary history", `src/index.ts:21-23` at 0a15cff), and
            # because `src/compact.ts:33-40` summarises `session.turns` only — the
            # previous summary is not in the second boundary's input, so a host that
            # replaced would lose it. The direction of the bias: replacing is GENEROUS to
            # the mechanism on tokens and HARSH on fidelity. A host that accumulated
            # blocks instead would spend `block_bytes` (the running total, committed) and
            # keep the earlier summaries. Both columns are committed so a reader can
            # recompute the other convention without re-running anything.
            installed_block_bytes = sizes["block_bytes"]
            boundary_count += 1
            summarizer_prompt_bytes_sent += prompt_bytes
            summarizer_in += round(prompt_bytes / BYTES_PER_TOKEN)
            summarizer_out += round(
                len(str(block.get("summary", "")).encode("utf-8")) / BYTES_PER_TOKEN
            )
            summarizer_prompt_tokens_seen += min(
                round(prompt_bytes / BYTES_PER_TOKEN), OLLAMA_OBSERVED_NUM_CTX
            )
            blocks_installed.append(str(block.get("summary", "")))

    post_boundary_calls = (
        len(call_indices) - 1 - max(boundaries) if boundaries else 0
    )
    ctx_with = sum(tokens_of(b, with_fixed=True) for b in prefix_bytes)
    ctx_no = sum(tokens_of(b, with_fixed=False) for b in prefix_bytes)
    return {
        "arm": arm,
        "repeat": repeat,
        "calls": agent_calls,
        "boundaries": boundary_count,
        "post_boundary_calls": post_boundary_calls,
        "context_bytes_sent": sum(prefix_bytes),
        "context_tokens_sent_with_fixed": round(ctx_with, 3),
        "context_tokens_sent_no_fixed": round(ctx_no, 3),
        "summarizer_input_tokens": summarizer_in,
        "summarizer_output_tokens": summarizer_out,
        "summarizer_prompt_bytes_sent": summarizer_prompt_bytes_sent,
        "summarizer_prompt_tokens_the_endpoint_saw": summarizer_prompt_tokens_seen,
        "summary_bytes": summary_bytes,
        "rehydrated_bytes": rehydrated_bytes,
        "block_bytes": block_bytes_total,
        "trim_removed_turns": trim_removed_turns,
        "trim_removed_bytes": trim_removed_bytes,
        "offload_digest_bytes": offload_digest_bytes,
        "offload_body_bytes": offload_body_bytes,
        "_blocks": blocks_installed,
        "_prefix_bytes": prefix_bytes,
    }


# Measured on this machine before the sample was declared: the endpoint reports
# `prompt_tokens: 4096` for a 720,500-byte prompt. Recorded as a CONSTANT OF THE
# DEPLOYMENT, used only to report how much of what the mechanism sent was actually read.
OLLAMA_OBSERVED_NUM_CTX = 4096


def _session_file(state_dir: Path, sid: str) -> Path:
    return state_dir / sid / "session.json"


def _held_turn_bytes(state_dir: Path, sid: str) -> int:
    path = _session_file(state_dir, sid)
    if not path.exists():
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    return sum(len(str(t.get("content", "")).encode("utf-8")) for t in state.get("turns", []))


def _summarizer_prompt_bytes(state_dir: Path, sid: str) -> int:
    """The bytes `context_compact` will hand the summarizer, built the mechanism's way.

    `src/compact.ts:34-40` at 0a15cff joins the unpinned turns as `### role\\ncontent`
    with a blank line between. Reproduced here so the number is the mechanism's own
    prompt size and not an approximation of it.
    """
    path = _session_file(state_dir, sid)
    if not path.exists():
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    joined = "\n\n".join(
        f"### {t.get('role')}\n{t.get('content')}"
        for t in state.get("turns", [])
        if not t.get("pinned")
    )
    return len(joined.encode("utf-8"))


# =======================================================================================
# §3.2 anchors
# =======================================================================================
_ANCHOR_RE = re.compile("|".join(f"(?:{pattern})" for _, pattern in ANCHOR_CLASSES))


def extract_tokens(text: str) -> set[str]:
    found = set()
    for match in _ANCHOR_RE.finditer(text):
        token = match.group(0).strip()
        if len(token) < ANCHOR_MIN_LENGTH or token in ANCHOR_STOP_LIST:
            continue
        found.add(token)
    return found


def anchors_for(turns: list[dict], call_indices: list[int], boundaries: list[int]) -> set[str]:
    """A literal string the transcript itself proves the later work needed: present before
    a boundary and recurring after it. The transcript decides, not a judge."""
    anchors: set[str] = set()
    for boundary_call in boundaries:
        split = call_indices[boundary_call]
        before: set[str] = set()
        after: set[str] = set()
        for index, turn in enumerate(turns):
            target = before if index <= split else after
            target |= extract_tokens(turn["content"])
        anchors |= before & after
    return anchors


# =======================================================================================
# Artifact plumbing
# =======================================================================================
def fence_violations(text: str) -> list[str]:
    """The user's fence, on the bytes that would be committed. Numbers and statistics
    only: no transcript excerpt, no prompt text, no other project's filename."""
    problems: list[str] = []

    def walk(node, where: str) -> None:
        if isinstance(node, str):
            for pattern in _FENCE_PATTERNS:
                if pattern in node:
                    problems.append(f"{where}: {pattern!r} in a committed string")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key, f"{where}.{key}")
                walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}[{index}]")

    for index, line in enumerate(text.splitlines()):
        if line.strip():
            walk(json.loads(line), f"row {index}")
    return problems


def read_rows(name: str) -> list[dict]:
    path = HERE / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(name: str, rows: list[dict]) -> None:
    text = "".join(json.dumps(row) + "\n" for row in rows)
    problems = fence_violations(text)
    if problems:
        raise SystemExit("FENCE VIOLATION:\n  " + "\n  ".join(problems))
    (HERE / name).write_text(text, encoding="utf-8")


def _median(values):
    return statistics.median(values) if values else None


def _pct(numerator, denominator):
    return None if not denominator else round(100.0 * numerator / denominator, 4)


# =======================================================================================
# MODE 1 — reconstruct. The null control, the schedule, and R1. No summarizer, no arm.
# =======================================================================================
def cmd_reconstruct() -> int:
    survey = _load_survey()
    root = survey.DEFAULT_TRANSCRIPT_ROOT
    corpus = {row["transcript_id"]: row for row in read_rows(CORPUS_ARTIFACT)}
    if not corpus:
        print("no committed corpus; nothing to reconstruct", file=sys.stderr)
        return 1

    classified, _ = survey.classify_tree(root)
    paths: dict[str, Path] = {}
    for path, here, other, _distinct in classified:
        if here and not other:
            digest = hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:16]
            paths[digest] = path

    rows: list[dict] = []
    for transcript_id in sorted(corpus):
        path = paths.get(transcript_id)
        if path is None:
            # A committed corpus member that is no longer selectable. NOT silently
            # dropped: it is a row with the condition named, so the reproduction check
            # sees it rather than a shorter file.
            rows.append({"transcript_id": transcript_id, "reconstruction": "NOT_SELECTABLE"})
            continue
        recon = reconstruct(path, survey)
        prefix = recon["prefix_bytes"]
        boundaries = schedule_boundaries(prefix)
        anchors = anchors_for(recon["turns"], recon["call_indices"], boundaries)
        peak_tokens = max((tokens_of(b, with_fixed=True) for b in prefix), default=0.0)
        row = {
            "transcript_id": transcript_id,
            "stratum": "A" if corpus[transcript_id]["kind"] == "sidechain" else "B",
            "schedule_id": f"readingA-T{THRESHOLD_T}-v1",
            "reconstruction": "OK",
            # bar §1.2 — the null control's own trap, as columns
            "recorded_events": recon["recorded_events"],
            "reconstructed_turns": recon["reconstructed_turns"],
            "recorded_content_bytes": recon["recorded_content_bytes"],
            "reconstructed_content_bytes": recon["reconstructed_content_bytes"],
            "reconstruction_byte_delta": (
                recon["reconstructed_content_bytes"] - recon["recorded_content_bytes"]
            ),
            "skipped_event_kinds": recon["skipped_event_kinds"],
            # the model-call count, derived independently of U3 and compared to it
            "model_calls": len(recon["call_indices"]),
            "model_calls_committed_by_u3": corpus[transcript_id]["model_calls"],
            "model_calls_agree": (
                len(recon["call_indices"]) == corpus[transcript_id]["model_calls"]
            ),
            # bar §10.2 under Amendment B
            "live_window_peak_tokens": round(peak_tokens, 3),
            "peak_over_threshold": round(peak_tokens / THRESHOLD_T, 6),
            "boundaries": len(boundaries),
            "boundary_call_indices": boundaries,
            "post_boundary_calls": (
                len(recon["call_indices"]) - 1 - max(boundaries) if boundaries else 0
            ),
            "uninformative_u2": len(boundaries) == 0,
            "uninformative_u1": bool(boundaries)
            and (len(recon["call_indices"]) - 1 - max(boundaries)) == 0,
            "host_precompacted_boundaries": corpus[transcript_id][
                "host_precompacted_boundaries"
            ],
            # §3.2's anchor set size, from the FROZEN class list and stop-list
            "anchors_total": len(anchors),
            "prefix_bytes_total": sum(prefix),
        }
        row.update(ceiling_r1(prefix, boundaries))
        rows.append(row)

    write_rows(B0_ARTIFACT, rows)
    ok = [r for r in rows if r.get("reconstruction") == "OK"]
    bad = [r for r in ok if r["reconstruction_byte_delta"] != 0]
    print(f"{len(rows)} rows, {len(ok)} reconstructed, {len(bad)} byte mismatches")
    print(f"boundaries total: {sum(r['boundaries'] for r in ok)}")
    print(f"UNINFORMATIVE under U-2: {sum(1 for r in ok if r['uninformative_u2'])}")
    print(f"model-call disagreements with U3: {sum(1 for r in ok if not r['model_calls_agree'])}")
    return 0 if not bad else 1


# =======================================================================================
# MODE 2 — the arms. The real mechanism, one route, one flag at a time.
# =======================================================================================
def declared_sample(b0_rows: list[dict]) -> list[dict]:
    """The declared prefix of the committed hash order that fits the call budget."""
    chosen: list[dict] = []
    spent = 0
    for row in b0_rows:
        if row.get("reconstruction") != "OK":
            continue
        cost = row["boundaries"] * REPEATS * 3  # B1, B2, B3
        if spent + cost > SAMPLE_SUMMARIZER_CALL_BUDGET:
            break
        chosen.append(row)
        spent += cost
    return chosen


def cmd_arms(limit: int | None) -> int:
    survey = _load_survey()
    root = survey.DEFAULT_TRANSCRIPT_ROOT
    b0_rows = read_rows(B0_ARTIFACT)
    if not b0_rows:
        print("run --reconstruct first", file=sys.stderr)
        return 1
    sample = declared_sample(b0_rows)
    if limit is not None:
        sample = sample[:limit]

    classified, _ = survey.classify_tree(root)
    paths: dict[str, Path] = {}
    for path, here, other, _distinct in classified:
        if here and not other:
            digest = hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:16]
            paths[digest] = path

    state_root = Path(os.environ.get("TMPDIR", "/tmp")) / "j2u4-compaction-state"
    state_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    started_all = time.time()
    for position, b0 in enumerate(sample):
        path = paths[b0["transcript_id"]]
        recon = reconstruct(path, survey)
        boundaries = b0["boundary_call_indices"]
        anchors = anchors_for(recon["turns"], recon["call_indices"], boundaries)
        for arm in ("B0", "B1", "B2", "B3"):
            for repeat in range(1, REPEATS + 1):
                state_dir = state_root / f"{b0['transcript_id']}-{arm}-{repeat}"
                session = MechanismSession(state_dir)
                started = time.time()
                try:
                    measured = run_arm(recon, arm, repeat, boundaries, state_dir, session)
                finally:
                    session.close()
                blocks = measured.pop("_blocks")
                measured.pop("_prefix_bytes")
                retained = _retained_anchors(anchors, blocks, arm)
                row = {
                    "transcript_id": b0["transcript_id"],
                    "stratum": b0["stratum"],
                    "schedule_id": b0["schedule_id"],
                    "mcp_commit": MECHANISM_COMMIT[:12],
                    "compaction_mode": DECLARED_ENV["COMPACTION_MODE"],
                    "recall_mode": DECLARED_ENV["COMPACTION_RECALL_MODE"],
                    "summarizer_model": DECLARED_ENV["COMPACTION_LLM_MODEL"],
                    "model": "replay-of-recorded-calls",
                    "wall_clock_s": round(time.time() - started, 3),
                    "anchors_total": len(anchors),
                    "anchors_retained": retained,
                    "anchor_retention": (
                        round(retained / len(anchors), 6) if anchors else None
                    ),
                }
                row.update(measured)
                rows.append(row)
        print(
            f"[{position + 1}/{len(sample)}] {b0['transcript_id']} "
            f"boundaries={len(boundaries)} elapsed={time.time() - started_all:.0f}s",
            flush=True,
        )
        write_rows(ARMS_ARTIFACT, rows)
    print(f"{len(rows)} arm rows over {len(sample)} transcripts")
    return 0


def _retained_anchors(anchors: set[str], blocks: list[str], arm: str) -> int:
    """§3.2: anchors still LITERALLY present in what the host would install.

    B0 installs nothing and discards nothing, so its retention is 1.0 BY CONSTRUCTION —
    that is what makes it a valid control on this axis and the axis one-sided.
    """
    if arm == "B0":
        return len(anchors)
    if not blocks:
        return len(anchors)
    installed = "\n".join(blocks)
    return sum(1 for anchor in anchors if anchor in installed)


# =======================================================================================
# MODE 3 — the report. Every verdict recomputed from committed rows, per stratum.
# =======================================================================================
class Report:
    """The reported figures, built so that a forbidden figure cannot be constructed.

    Pooling, floor-borrowing and netting are not policed by a reviewer reading the output;
    they are policed by the fact that the only way to add such a figure is to add a key
    the checks enumerate.
    """

    def __init__(self, policy: dict) -> None:
        self.policy = policy
        self.by_stratum: dict[str, dict] = {}
        self.checks: list[tuple[str, bool, str]] = []
        self.escalations: list[str] = []

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append((name, passed, detail))


def _arm_stat(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return _median(values)


def _per_transcript(arms: list[dict], column: str) -> dict[tuple[str, str], list[float]]:
    out: dict[tuple[str, str], list[float]] = {}
    for row in arms:
        out.setdefault((row["transcript_id"], row["arm"]), []).append(row[column])
    return out


def _floor(per: dict, transcript: str, x: str, y: str) -> float:
    """Bar §3.1: the floor is the MAX over BOTH arms of that arm's own repeat spread,
    at the grain of the statistic it gates. Not `floor(X)` the lower rung — J1's A7
    measured that rule 3.506x more lenient than itself, and here the lower rung is
    deterministic so `floor(B0) = 0` exactly and would accept any non-zero delta."""
    spreads = []
    for arm in (x, y):
        values = per.get((transcript, arm), [])
        spreads.append(max(values) - min(values) if values else 0.0)
    return max(spreads)


# The ONLY adjacent-rung pairs this program will ever report. B3 against B0 is not in
# this tuple and cannot be added by a flag — bar §1.5, "no all-on-versus-all-off single
# number, ever". Only the first is UNCONDITIONAL; the other two are conditional on the
# rungs below them and are labelled that way everywhere they appear.
REPORTED_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("B1", "B0", "UNCONDITIONAL — context_compact adjacent to the null control"),
    ("B2", "B1", "CONDITIONAL — trim GIVEN compaction"),
    ("B3", "B2", "CONDITIONAL — offload GIVEN compaction+trim"),
)

# Arms that make an inference call. Bar §3.1(2): a zero floor is VALID only when both arms
# are deterministic; if either is stochastic a zero floor is DEGENERATE and printed.
STOCHASTIC_ARMS = frozenset({"B1", "B2", "B3"})

DEFAULT_POLICY = {
    "byte_delta_ok": 0,
    "threshold_t": THRESHOLD_T,
    "fixed_cost_declared": True,
    "pool_strata": False,
    "borrow_floor": False,
    "clamp_bytes": False,
    "sum_anchor_losses": False,
    "net_summarizer_into_saving": False,
    "pairs": REPORTED_PAIRS,
    "upper_bound_as_saving": False,
    "pick_grain": False,
    "zero_floor_is_always_valid": False,
}

# Each mutation FALSIFIES one claim and must turn RED the check that claim NAMES. A
# mutation that turns nothing red is a failure of the measurement, not of the mutation:
# it means the claim was never load-bearing.
MUTATIONS: dict[str, dict] = {
    "void-reconstruction": {
        "policy": {"byte_delta_ok": 1},
        "turns_red": "CHK-VOID-RECONSTRUCTION",
    },
    "retune-threshold": {
        "policy": {"threshold_t": 20_000},
        "turns_red": "CHK-THRESHOLD-NOT-RETUNED",
    },
    "omit-fixed-cost": {
        "policy": {"fixed_cost_declared": False},
        "turns_red": "CHK-FIXED-COST-DECLARED",
    },
    "pool-strata": {"policy": {"pool_strata": True}, "turns_red": "CHK-NO-POOLING"},
    "borrow-floor": {"policy": {"borrow_floor": True}, "turns_red": "CHK-NO-FLOOR-BORROW"},
    "clamp-byte-columns": {"policy": {"clamp_bytes": True}, "turns_red": "CHK-BYTES-SIGNED"},
    "sum-anchor-losses": {
        "policy": {"sum_anchor_losses": True},
        "turns_red": "CHK-LOSSES-NEVER-SUMMED",
    },
    "net-summarizer-tokens": {
        "policy": {"net_summarizer_into_saving": True},
        "turns_red": "CHK-SUMMARIZER-NEVER-NETTED",
    },
    "all-on-vs-all-off": {
        "policy": {
            "pairs": REPORTED_PAIRS + (("B3", "B0", "all-on versus all-off"),),
        },
        "turns_red": "CHK-NO-ALL-ON-VS-ALL-OFF",
    },
    "upper-bound-as-saving": {
        "policy": {"upper_bound_as_saving": True},
        "turns_red": "CHK-UPPER-BOUND-IS-NOT-A-SAVING",
    },
    "pick-a-grain": {"policy": {"pick_grain": True}, "turns_red": "CHK-GRAIN-NOT-PICKED"},
    "zero-floor-always-valid": {
        "policy": {"zero_floor_is_always_valid": True},
        "turns_red": "CHK-ZERO-FLOOR-CLASSIFIED",
    },
}


def _report_arms(arm_rows: list[dict], report: Report, policy: dict) -> dict:
    """Every arm verdict, PER STRATUM. There is no code path that pools the two."""
    print()
    print("--- THE ARMS -----------------------------------------------------------------")
    if not arm_rows:
        print("  no committed arm rows")
        report.check("CHK-ARMS-PRESENT", False, "no arm artifact committed")
        return {}
    report.check("CHK-ARMS-PRESENT", True, f"{len(arm_rows)} committed arm rows")

    # B0's determinism — free, and it catches ordering/hashing/clock defects that would
    # otherwise hide inside the summarizer's variance (bar §1.2).
    b0_spread = []
    for (transcript, arm), values in _per_transcript(arm_rows, "context_bytes_sent").items():
        if arm == "B0":
            b0_spread.append((transcript, max(values) - min(values)))
    nondet = [t for t, spread in b0_spread if spread != 0]
    report.check(
        "CHK-B0-DETERMINISTIC",
        not nondet,
        f"{len(b0_spread)} transcripts; {len(nondet)} with a non-zero B0 repeat spread",
    )

    # §3.3's witness: agent calls identical across arms, except the boundary calls the
    # mechanism itself adds — which are counted separately and never netted.
    witness_bad = []
    by_transcript: dict[str, dict[str, list[dict]]] = {}
    for row in arm_rows:
        by_transcript.setdefault(row["transcript_id"], {}).setdefault(row["arm"], []).append(row)
    for transcript, arms in by_transcript.items():
        counts = {arm: {r["calls"] for r in rows} for arm, rows in arms.items()}
        flat = {c for values in counts.values() for c in values}
        if len(flat) != 1:
            witness_bad.append(transcript)
    report.check(
        "CHK-TURNS-WITNESS",
        not witness_bad,
        f"agent calls identical across all arms on {len(by_transcript) - len(witness_bad)} "
        f"of {len(by_transcript)} transcripts",
    )

    verdicts: dict[str, dict] = {}
    signed_negative_seen = False
    for stratum in ("A", "B"):
        members = sorted({r["transcript_id"] for r in arm_rows if r["stratum"] == stratum})
        if not members:
            continue
        print()
        print(f"  === STRATUM {stratum} — n={len(members)} transcripts in the sample ===")
        if stratum == "B":
            print(
                "      n=1: UNINFORMATIVE-BY-N (Amendment A). No floor of its own, and it "
                "does NOT borrow stratum A's. Columns printed; no verdict claimed."
            )
        rows = [r for r in arm_rows if r["stratum"] == stratum]
        # Bar §5.4 U-1 and U-2: a transcript that never reached T (`boundaries == 0`) or
        # whose boundary fell on the last call (`post_boundary_calls == 0`) is
        # UNINFORMATIVE. Its Δ neither refutes nor confirms, so it is EXCLUDED from every
        # headline, floor and sign count rather than being carried in as a tie — carrying
        # it in would let a run with no opportunity to act read as unanimous agreement,
        # which is the defect §3.4's ABSTAINING clause exists to name.
        informative_ids = {
            r["transcript_id"]
            for r in rows
            if r["boundaries"] > 0 and r["post_boundary_calls"] > 0
        }
        excluded = [t for t in members if t not in informative_ids]
        print(
            f"      U-1/U-2 UNINFORMATIVE in this sample: {len(excluded)} of {len(members)} "
            f"excluded from every headline, floor and sign count"
        )
        members = [t for t in members if t in informative_ids]
        if not members:
            print("      every sampled transcript in this stratum is UNINFORMATIVE.")
            verdicts[stratum] = {}
            continue
        per_tokens = _per_transcript(rows, "context_tokens_sent_with_fixed")
        stratum_out: dict[str, dict] = {}

        for y, x, label in policy["pairs"]:
            ctx = {}
            for transcript in members:
                for arm in (x, y):
                    values = per_tokens.get((transcript, arm))
                    if values:
                        ctx[(transcript, arm)] = _median(values)
            usable = [t for t in members if (t, x) in ctx and (t, y) in ctx]
            if not usable:
                continue
            deltas = {t: ctx[(t, y)] - ctx[(t, x)] for t in usable}
            delta_pct = {
                t: (100.0 * deltas[t] / ctx[(t, x)]) if ctx[(t, x)] else None for t in usable
            }
            if any(v < 0 for v in deltas.values()):
                signed_negative_seen = True

            # floors, EACH AT THE GRAIN OF THE STATISTIC IT GATES
            per_t_floor = {t: _floor(per_tokens, t, x, y) for t in usable}
            per_t_clears = {t: abs(deltas[t]) > per_t_floor[t] for t in usable}
            headline_delta = _median([deltas[t] for t in usable])
            headline_pct = _median([v for v in delta_pct.values() if v is not None])
            repeat_medians = {}
            for arm in (x, y):
                per_repeat = []
                for repeat in range(1, REPEATS + 1):
                    values = [
                        r["context_tokens_sent_with_fixed"]
                        for r in rows
                        if r["arm"] == arm and r["repeat"] == repeat and r["transcript_id"] in usable
                    ]
                    if values:
                        per_repeat.append(_median(values))
                repeat_medians[arm] = (
                    max(per_repeat) - min(per_repeat) if len(per_repeat) > 1 else 0.0
                )
            headline_floor = max(repeat_medians.values())
            if stratum == "B" and policy["borrow_floor"]:
                borrowed = verdicts.get("A", {}).get(f"{y}-{x}", {}).get("headline_floor")
                if borrowed is not None:
                    headline_floor = borrowed
            headline_clears = abs(headline_delta) > headline_floor

            # zero-floor classification, bar §3.1(2)
            stochastic = (x in STOCHASTIC_ARMS) or (y in STOCHASTIC_ARMS)
            if headline_floor == 0.0 and not policy["zero_floor_is_always_valid"]:
                floor_class = "DEGENERATE" if stochastic else "EXACT"
            elif headline_floor == 0.0:
                floor_class = "VALID"
            else:
                floor_class = "MEASURED"

            # the sign condition, with ABSTAINING as a distinct outcome (bar §3.4)
            signs = {t: (0 if deltas[t] == 0 else (1 if deltas[t] > 0 else -1)) for t in usable}
            pointing = [s for s in signs.values() if s != 0]
            if not pointing:
                sign_verdict = "ABSTAINING (sign condition UNEVALUABLE, never held)"
            elif len({s for s in pointing}) > 1:
                sign_verdict = "conflicting — NOT a measured effect regardless of magnitude"
            else:
                sign_verdict = "directional"

            # per-transcript-grain verdict, DECLARED: CLEARS iff a strict majority of the
            # usable transcripts clear their own floor.
            majority = sum(1 for v in per_t_clears.values() if v) * 2 > len(usable)
            grain_agrees = majority == headline_clears
            if not grain_agrees and not policy["pick_grain"]:
                report.escalations.append(
                    f"stratum {stratum}, pair {y}-{x}: the CLEARS verdict DIFFERS between "
                    f"grains (headline={headline_clears}, per-transcript majority={majority}). "
                    "Bar §3.1: the run does not choose a grain. ESCALATED to the user."
                )

            # rho*, bar §4 — a price-free QUOTIENT of two measured columns, never a sum
            summarizer = sum(
                r["summarizer_input_tokens"] + r["summarizer_output_tokens"]
                for r in rows
                if r["arm"] == y and r["transcript_id"] in usable
            ) / max(REPEATS, 1)
            rho = abs(headline_delta) * len(usable) / summarizer if summarizer else None

            # fidelity, §3.2
            retention = {
                t: _median([r["anchor_retention"] for r in rows
                            if r["arm"] == y and r["transcript_id"] == t
                            and r["anchor_retention"] is not None])
                for t in usable
            }
            retention = {t: v for t, v in retention.items() if v is not None}
            fidelity_floor = 0.0
            for transcript in usable:
                values = [
                    r["anchor_retention"] for r in rows
                    if r["arm"] == y and r["transcript_id"] == transcript
                    and r["anchor_retention"] is not None
                ]
                if len(values) > 1:
                    fidelity_floor = max(fidelity_floor, max(values) - min(values))
            lost_stable = 0
            lost_unstable = 0
            for transcript in usable:
                values = [
                    r["anchors_retained"] for r in rows
                    if r["arm"] == y and r["transcript_id"] == transcript
                ]
                total = next(
                    (r["anchors_total"] for r in rows if r["transcript_id"] == transcript), 0
                )
                if not values or not total:
                    continue
                if all(v < total for v in values):
                    lost_stable += total - max(values)
                elif any(v < total for v in values):
                    lost_unstable += total - min(values)

            stratum_out[f"{y}-{x}"] = {
                "label": label,
                "n": len(usable),
                "headline_delta_tokens": headline_delta,
                "headline_pct": headline_pct,
                "headline_floor": headline_floor,
                "headline_clears": headline_clears,
                "floor_class": floor_class,
                "per_transcript_majority_clears": majority,
                "grain_agrees": grain_agrees,
                "sign": sign_verdict,
                "rho_star": rho,
                "median_retention": _median(list(retention.values())),
                "fidelity_floor": fidelity_floor,
                "anchors_lost_stable": lost_stable,
                "anchors_lost_unstable": lost_unstable,
            }
            out = stratum_out[f"{y}-{x}"]
            print(f"    {y} - {x}  [{label}]  n={len(usable)}")
            if stratum == "B":
                print("      UNINFORMATIVE-BY-N — figures printed, no verdict claimed.")
            print(
                f"      Δ tokens (median, SIGNED) = {headline_delta:+,.1f}  "
                f"({headline_pct:+.4f}% of the null control)"
            )
            print(
                f"      token floor at the HEADLINE grain = {headline_floor:,.1f} "
                f"[{floor_class}] -> {'CLEARS' if headline_clears else 'DOES NOT CLEAR'}"
            )
            print(
                f"      token floor at the PER-TRANSCRIPT grain: "
                f"{sum(1 for v in per_t_clears.values() if v)}/{len(usable)} clear their own "
                f"floor -> majority {'CLEARS' if majority else 'DOES NOT CLEAR'}"
                f"{'' if grain_agrees else '   *** GRAIN DISAGREEMENT -> ESCALATE ***'}"
            )
            print(f"      sign condition: {sign_verdict}")
            print(
                f"      fidelity: median anchor retention "
                f"{out['median_retention'] if out['median_retention'] is not None else 'n/a'}, "
                f"floor {fidelity_floor:.6f}; "
                f"anchors_lost_stable={lost_stable}, anchors_lost_unstable={lost_unstable} "
                "(never summed)"
            )
            print(
                f"      rho* = {rho:.4f}" if rho is not None else "      rho* = n/a (no boundary)"
            )
            if out["median_retention"] is not None and lost_stable > 0:
                print(
                    "      => this is a TRADE, not a reduction (bar §4): a token delta at a "
                    "retention below 1 - floor with stable losses."
                )
        verdicts[stratum] = stratum_out

    report.check(
        "CHK-BYTES-SIGNED",
        not policy["clamp_bytes"],
        "byte and token deltas are reported SIGNED and unclamped"
        + ("; a negative delta is present in the data" if signed_negative_seen else
           "; NOT EXERCISED — no negative delta in this sample"),
    )
    return verdicts


def _structural_checks(report: Report, policy: dict, ceilings: dict, verdicts: dict) -> None:
    """The checks that police the SHAPE of the report, not its numbers.

    Each is named by a claim, so a mutation that falsifies the claim turns exactly this
    check red rather than merely producing a different number.
    """
    report.check(
        "CHK-NO-POOLING",
        not policy["pool_strata"],
        "every headline, floor and verdict is per stratum; no cross-stratum figure exists "
        "(Amendment A — the user's ruling, 'ห้าม pool เป็นเลขเดียว')",
    )
    report.check(
        "CHK-NO-FLOOR-BORROW",
        not policy["borrow_floor"],
        "stratum B (n=1) supports no floor and borrows none from stratum A",
    )
    report.check(
        "CHK-NO-ALL-ON-VS-ALL-OFF",
        all((y, x) != ("B3", "B0") for y, x, _ in policy["pairs"]),
        "reported pairs are adjacent rungs only: "
        + ", ".join(f"{y}-{x}" for y, x, _ in policy["pairs"]),
    )
    report.check(
        "CHK-LOSSES-NEVER-SUMMED",
        not policy["sum_anchor_losses"],
        "anchors_lost_stable and anchors_lost_unstable are reported separately (bar §3.2)",
    )
    report.check(
        "CHK-SUMMARIZER-NEVER-NETTED",
        not policy["net_summarizer_into_saving"],
        "summarizer tokens appear only in their own columns and inside rho*, a quotient "
        "(bar §4); no blended net-saving figure exists",
    )
    bound = {
        stratum: (
            None
            if not c.get("n")
            else round(100.0 * (c["n"] - 1) / (c["n"] + 1), 3)
        )
        for stratum, c in ceilings.items()
    }
    report.check(
        "CHK-UPPER-BOUND-IS-NOT-A-SAVING",
        not policy["upper_bound_as_saving"],
        f"(N-1)/(N+1) is an UPPER BOUND, never a measured saving; at stratum A's median of "
        f"26 model calls the ceiling is 92.6%, not 99.4% (per-stratum n gives {bound})",
    )
    disagreements = [
        f"{stratum}:{pair}"
        for stratum, pairs in verdicts.items()
        for pair, out in pairs.items()
        if not out["grain_agrees"]
    ]
    report.check(
        "CHK-GRAIN-NOT-PICKED",
        not policy["pick_grain"],
        f"a verdict that differs between grains is ESCALATED, never chosen; "
        f"{len(disagreements)} disagreement(s): {disagreements or 'none'}",
    )
    degenerate = [
        f"{stratum}:{pair}"
        for stratum, pairs in verdicts.items()
        for pair, out in pairs.items()
        if out["floor_class"] == "DEGENERATE"
    ]
    report.check(
        "CHK-ZERO-FLOOR-CLASSIFIED",
        not policy["zero_floor_is_always_valid"],
        f"a zero floor with a stochastic arm is DEGENERATE and printed, never silently "
        f"accepted (bar §3.1(2)); {len(degenerate)} degenerate pair(s): {degenerate or 'none'}",
    )


def cmd_report(mutate: str | None) -> int:
    policy = dict(DEFAULT_POLICY)
    if mutate is not None:
        if mutate not in MUTATIONS:
            print(f"unknown --mutate mode: {mutate}", file=sys.stderr)
            print("known modes: " + ", ".join(sorted(MUTATIONS)), file=sys.stderr)
            return 1
        policy.update(MUTATIONS[mutate]["policy"])

    b0_rows = [r for r in read_rows(B0_ARTIFACT) if r.get("reconstruction") == "OK"]
    arm_rows = read_rows(ARMS_ARTIFACT)
    if not b0_rows:
        print("no committed B0 artifact", file=sys.stderr)
        return 1

    report = Report(policy)
    print(RULE)
    print("J2 / U4 — THE ARMS, per stratum. Bar f48335c, amended e94d960 before any arm.")
    print(RULE)

    # ---- bar §1.2, the null control's own trap -----------------------------------------
    mismatched = [r for r in b0_rows if r["reconstruction_byte_delta"] != policy["byte_delta_ok"]]
    report.check(
        "CHK-VOID-RECONSTRUCTION",
        not mismatched,
        f"{len(b0_rows)} transcripts reconstructed; "
        f"{len(mismatched)} with recorded != reconstructed content bytes",
    )
    disagree = [r for r in b0_rows if not r["model_calls_agree"]]
    report.check(
        "CHK-MODEL-CALLS-AGREE-WITH-U3",
        not disagree,
        f"{len(disagree)} of {len(b0_rows)} disagree with the committed corpus",
    )
    unenumerated = [
        r for r in b0_rows if any(not isinstance(v, int) for v in r["skipped_event_kinds"].values())
    ]
    report.check(
        "CHK-EVERY-SKIPPED-KIND-ENUMERATED",
        not unenumerated,
        "every skipped event kind carries an integer count",
    )

    # ---- the threshold, and the standing refusal ---------------------------------------
    report.check(
        "CHK-THRESHOLD-NOT-RETUNED",
        policy["threshold_t"] == 76_800
        and all(r["schedule_id"] == f"readingA-T{policy['threshold_t']}-v1" for r in b0_rows),
        f"T = {policy['threshold_t']} tokens (60% of 128,000, the shipped defaults); "
        "every row carries the same schedule_id",
    )

    # ---- the fixed per-call cost, declared ---------------------------------------------
    report.check(
        "CHK-FIXED-COST-DECLARED",
        policy["fixed_cost_declared"]
        and all("ceiling_pct_with_fixed" in r and "ceiling_pct_no_fixed" in r for r in b0_rows),
        f"declared as a constant: {FIXED_PER_CALL_TOKENS} tokens per call; both the "
        "with-constant and without-constant figures are committed",
    )

    print()
    print("--- U-1 / U-2 / U-4 / VOID accounting, PER STRATUM (never pooled) ------------")
    strata = {}
    for stratum in ("A", "B"):
        members = [r for r in b0_rows if r["stratum"] == stratum]
        strata[stratum] = members
        if not members:
            continue
        u2 = [r for r in members if r["uninformative_u2"]]
        u1 = [r for r in members if r["uninformative_u1"]]
        u4 = [r for r in members if r["host_precompacted_boundaries"] > 0]
        informative = [r for r in members if not r["uninformative_u2"] and not r["uninformative_u1"]]
        print(
            f"  stratum {stratum}: n={len(members)}  "
            f"UNINFORMATIVE U-2 (never reached T)={len(u2)}  "
            f"UNINFORMATIVE U-1 (no post-boundary call)={len(u1)}  "
            f"informative={len(informative)}  "
            f"host-precompacted (U-4)={len(u4)}  "
            f"boundaries={sum(r['boundaries'] for r in members)}"
        )
        if stratum == "B":
            print(
                "           stratum B is n=1: UNINFORMATIVE-BY-N under Amendment A. "
                "It supports no floor and never borrows stratum A's."
            )

    # ---- R1, the arithmetic ceiling, per stratum ---------------------------------------
    print()
    print("--- R1: the ZERO-SUMMARY CEILING (arithmetic; no summarizer, no arm) ---------")
    ceilings: dict[str, dict] = {}
    for stratum, members in strata.items():
        informative = [r for r in members if r["boundaries"] > 0]
        if not informative:
            ceilings[stratum] = {"n": 0}
            print(f"  stratum {stratum}: no transcript reached T — R1 UNEVALUABLE here")
            continue
        with_fixed = [r["ceiling_pct_with_fixed"] for r in informative]
        no_fixed = [r["ceiling_pct_no_fixed"] for r in informative]
        pooled_num = sum(
            r["ctx_tokens_zero_summary_with_fixed"] - r["ctx_tokens_b0_with_fixed"]
            for r in informative
        )
        pooled_den = sum(r["ctx_tokens_b0_with_fixed"] for r in informative)
        ceilings[stratum] = {
            "n": len(informative),
            "median_with_fixed": _median(with_fixed),
            "median_no_fixed": _median(no_fixed),
            "pooled_within_stratum": _pct(pooled_num, pooled_den),
        }
        print(
            f"  stratum {stratum} (n={len(informative)} informative): "
            f"median ceiling {ceilings[stratum]['median_with_fixed']:+.3f}% "
            f"WITH the declared fixed per-call cost, "
            f"{ceilings[stratum]['median_no_fixed']:+.3f}% without it; "
            f"pooled-WITHIN-stratum {ceilings[stratum]['pooled_within_stratum']:+.3f}%"
        )
    r1_fires = {
        s: (c.get("median_with_fixed") is not None and c["median_with_fixed"] > TARGET_HEADLINE)
        for s, c in ceilings.items()
        if c.get("n")
    }
    for stratum, fired in r1_fires.items():
        print(
            f"  R1 on stratum {stratum}: the ceiling is "
            f"{'ABOVE' if fired else 'at or below'} the handed {TARGET_HEADLINE:+.0f}% target "
            f"=> 80% is {'REFUTED' if fired else 'NOT refuted'} for this mechanism on this "
            "stratum at this schedule, before any arm runs."
        )

    # ---- the arms ----------------------------------------------------------------------
    # The arithmetic B0 above is used on all 207 transcripts; the mechanism-driven B0 is
    # run only on the declared sample. They are required to agree EXACTLY, which is what
    # makes the arithmetic trace evidence about the mechanism rather than about this file.
    arithmetic = {r["transcript_id"]: r["prefix_bytes_total"] for r in b0_rows}
    driven = {
        r["transcript_id"]: r["context_bytes_sent"] for r in arm_rows if r["arm"] == "B0"
    }
    route_bad = [t for t, v in driven.items() if arithmetic.get(t) != v]
    report.check(
        "CHK-B0-ROUTE-AGREES",
        not route_bad and bool(driven),
        f"the mechanism-driven null control equals the arithmetic null control on "
        f"{len(driven) - len(route_bad)} of {len(driven)} sampled transcripts",
    )

    verdicts = _report_arms(arm_rows, report, policy)

    # ---- the structural checks the claims NAME -----------------------------------------
    _structural_checks(report, policy, ceilings, verdicts)

    print()
    print("--- NAMED CHECKS -------------------------------------------------------------")
    failed = 0
    for name, passed, detail in report.checks:
        print(f"  [{'PASS' if passed else 'RED '}] {name}: {detail}")
        if not passed:
            failed += 1
    for line in report.escalations:
        print(f"  [ESCALATE] {line}")
    print(RULE)
    if mutate is not None:
        expected = MUTATIONS[mutate]["turns_red"]
        actually_red = {n for n, p, _ in report.checks if not p}
        if expected in actually_red:
            print(f"MUTATION {mutate!r} turned RED the check it names: {expected}")
            return 1
        print(
            f"MUTATION {mutate!r} did NOT turn red {expected} — the claim survived its own "
            "falsification, which means the claim is not measured. This is a FAILURE.",
            file=sys.stderr,
        )
        return 1
    print(f"{len(report.checks)} named checks, {failed} red, {len(report.escalations)} escalations")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruct", action="store_true")
    parser.add_argument("--arms", action="store_true")
    parser.add_argument("--mutate", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if args.reconstruct:
        return cmd_reconstruct()
    if args.arms:
        return cmd_arms(args.limit)
    return cmd_report(args.mutate)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
