"""Matched review-only FIXTURE REPLAY; never a production dispatcher.

The external JSON adapter owns any real-agent orchestration (including the repo's
Shiftwork clock-in/out policy). The harness starts a fresh process and scratch cwd
per review. Synthetic author labels describe intended topology, not author work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import statistics
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
LIMITS = [
    "Synthetic review-only fixture replay; intended topology is not actual delegated author work.",
    "Predetermined fixes do not measure model-authored repair, planner, dispatch, integration or author cost.",
    "Full workflow tokens and savings are unknown; review-token savings alone cannot establish adoption.",
    "Small fixture samples and deterministic oracle checks do not establish general review quality.",
    "Fresh reviewer process/context IDs are adapter obligations, not proof of independent human authorship.",
]


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def builtin_cases() -> list[dict]:
    """Host-only answer keys accompany reproducible, deliberately small snippets."""
    definitions = [
        (
            "native-chain",
            ["parent", "parent", "parent"],
            [
                (
                    "A",
                    "clean",
                    "def clean(text):\n    return text\n",
                    "def clean(text):\n    return text.strip()\n",
                    "Trim whitespace from both ends.",
                    "clean(' Ada ')",
                    "Ada",
                ),
                (
                    "B",
                    "key",
                    "def key(text):\n    return text.upper()\n",
                    "def key(text):\n    return text.lower()\n",
                    "Return the lowercase lookup key.",
                    "key('Ada')",
                    "ada",
                ),
                (
                    "C",
                    "greet",
                    "def greet(text):\n    return 'Hello ' + text\n",
                    "def greet(text):\n    return 'Hello ' + text + '!'\n",
                    "Prefix Hello and a space, then append an exclamation mark.",
                    "greet(key(clean(' Ada ')))",
                    "Hello ada!",
                ),
            ],
        ),
        (
            "delegated-chain",
            ["delegate-1", "delegate-2", "delegate-3"],
            [
                (
                    "A",
                    "subtotal",
                    "def subtotal(qty, price):\n    return qty + price\n",
                    "def subtotal(qty, price):\n    return qty * price\n",
                    "Subtotal is quantity multiplied by unit price.",
                    "subtotal(3, 10)",
                    30,
                ),
                (
                    "B",
                    "discount",
                    "def discount(value, pct):\n    return value * pct / 100\n",
                    "def discount(value, pct):\n    return value * (1 - pct / 100)\n",
                    "Return the remaining value after a percentage discount.",
                    "discount(30, 10)",
                    27,
                ),
                (
                    "C",
                    "shipping",
                    "def shipping(value):\n    return value + 50\n",
                    "def shipping(value):\n    return value + 5\n",
                    "Add a flat shipping cost of 5.",
                    "shipping(discount(subtotal(3, 10), 10))",
                    32,
                ),
            ],
        ),
        (
            "mixed-fork-join",
            ["parent", "delegate-1", "parent-integrator"],
            [
                (
                    "A",
                    "net",
                    "def net(gross):\n    return gross - 2\n",
                    "def net(gross):\n    return gross - 1\n",
                    "Net subtracts a flat fee of 1 from gross.",
                    "net(10)",
                    9,
                ),
                (
                    "B",
                    "tax",
                    "def tax(gross):\n    return gross * 0.2\n",
                    "def tax(gross):\n    return gross * 0.1\n",
                    "Tax is ten percent of the original gross.",
                    "tax(10)",
                    1,
                ),
                (
                    "C",
                    "receipt",
                    "def receipt(gross):\n    return net(gross) - tax(gross)\n",
                    "def receipt(gross):\n    return net(gross) + tax(gross)\n",
                    "Receipt joins the net and tax branches by adding their values.",
                    "receipt(10)",
                    10,
                ),
            ],
        ),
    ]
    cases = []
    for name, authors, rows in definitions:
        units, oracle = [], []
        for i, (uid, function, seeded, fixed, text, expression, expected) in enumerate(rows):
            criterion = f"{uid}-behavior"
            units.append(
                {
                    "id": uid,
                    "author_id": authors[i],
                    "status": "done",
                    "depends_on": (
                        ["A", "B"]
                        if i == 2 and name == "mixed-fork-join"
                        else ([rows[i - 1][0]] if i and name != "mixed-fork-join" else [])
                    ),
                    "seeded": seeded,
                    "fixed": fixed,
                    "acceptance_criteria": [
                        {"id": criterion, "text": text},
                        {
                            "id": f"{uid}-interface",
                            "text": f"Keep the {function} function signature.",
                        },
                    ],
                    "evidence": {
                        "attempt_id": f"{uid}-fixture-attempt",
                        "artifact": f"{uid}.py",
                        "revision": digest(fixed),
                        "fast_check_passed": True,
                    },
                }
            )
            oracle.append(
                {
                    "unit": uid,
                    "criterion": criterion,
                    "expression": expression,
                    "expected": expected,
                }
            )
        cases.append(
            {
                "id": name,
                "execution_mode": f"intended {name} topology replay",
                "units": units,
                "oracle": oracle,
            }
        )
    return cases


def check_oracle(case: dict, stage: str) -> dict:
    """Execute only trusted host fixtures, never adapter output or arbitrary code."""
    checks = []
    namespace = {}
    try:
        for unit in case["units"]:
            exec(unit[stage], namespace)
        for check in case["oracle"]:
            actual = eval(check["expression"], namespace)
            checks.append(
                {
                    "unit": check["unit"],
                    "criterion": check["criterion"],
                    "passed": actual == check["expected"],
                }
            )
    except (ArithmeticError, LookupError, NameError, SyntaxError, TypeError, ValueError) as exc:
        return {"passed": False, "checks": checks, "error": f"{type(exc).__name__}: {exc}"}
    return {"passed": bool(checks) and all(c["passed"] for c in checks), "checks": checks}


def make_request(case: dict, stage: str, membership: list[str], context: str) -> dict:
    context_units = [
        {
            "id": u["id"],
            "author_id": u["author_id"],
            "revision": digest(u[stage]),
            "snippet": u[stage],
            "acceptance_criteria": u["acceptance_criteria"],
            "depends_on": u["depends_on"],
            "evidence": (
                {**u["evidence"], "revision": digest(u[stage]), "fast_check_passed": None}
                if stage == "seeded" and isinstance(u.get("evidence"), dict)
                else u.get("evidence")
            ),
        }
        for u in case["units"]
    ]
    return {
        "instructions": (
            "Independently review units in membership against every acceptance criterion. "
            "context_units supplies the identical complete integrated context to both review arms; "
            "use it to evaluate dependencies, but report findings/evidence only for membership. "
            "Report concrete defects only as {unit,criterion,detail}; use [] when no defects remain. "
            "Return a JSON object with actual model, actual settings, findings, usage (input_tokens, "
            "output_tokens, cache_read_input_tokens, cache_creation_input_tokens; omit unknowns), "
            "reviewer_context_id echoed exactly, and evidence:[{unit,revision,criteria:[criterion IDs]}] "
            "for every reviewed member. Bind evidence to the supplied exact revision. "
            "This is synthetic fixture replay, not delegated implementation work. "
            "External reviewer adapters must obey applicable real-agent orchestration policies."
        ),
        "case_id": case["id"],
        "execution_mode": case["execution_mode"],
        "stage": stage,
        "membership": membership,
        "reviewer_context_id": context,
        "context_units": context_units,
        "units": [u for u in context_units if u["id"] in membership],
    }


def validate_response(request: dict, response: object) -> str | None:
    if not isinstance(response, dict):
        return "response must be a JSON object"
    if not isinstance(response.get("model"), str) or not response["model"].strip():
        return "response model must be nonempty"
    if not isinstance(response.get("findings"), list):
        return "response findings must be an array"
    criteria = {u["id"]: {c["id"] for c in u["acceptance_criteria"]} for u in request["units"]}
    for finding in response["findings"]:
        if (
            not isinstance(finding, dict)
            or not isinstance(finding.get("unit"), str)
            or finding.get("unit") not in criteria
            or not isinstance(finding.get("criterion"), str)
            or finding.get("criterion") not in criteria[finding["unit"]]
            or not isinstance(finding.get("detail"), str)
            or not finding["detail"].strip()
        ):
            return "response finding has invalid member, criterion or detail"
    return None


def assess_approval(case: dict, request: dict, response: dict) -> dict:
    """Fail closed on coverage, contribution, membership and revision faults."""
    reasons = []
    if validate_response(request, response):
        return {"approved": False, "reasons": ["invalid response"]}
    if request.get("stage") != "fixed" or response.get("findings") != []:
        reasons.append("final revision requires fresh review without findings")
    if not request.get("reviewer_context_id") or response.get("reviewer_context_id") != request.get(
        "reviewer_context_id"
    ):
        reasons.append("reviewer context not bound")
    case_units = {u["id"]: u for u in case["units"]}
    context = request.get("context_units", [])
    if len(context) != len(case_units) or {u["id"] for u in context} != set(case_units):
        reasons.append("missing integrated context")
    for item in context:
        source = case_units.get(item["id"])
        if (
            not source
            or item.get("revision") != digest(source["fixed"])
            or item.get("snippet") != source["fixed"]
            or item.get("acceptance_criteria") != source["acceptance_criteria"]
        ):
            reasons.append("changed integrated context")
    requested = request.get("units", [])
    membership = request.get("membership", [])
    if (
        not membership
        or len(membership) != len(set(membership))
        or {u["id"] for u in requested} != set(membership)
    ):
        reasons.append("invalid membership")
    if request.get("reviewer_context_id") in {u["author_id"] for u in case["units"]}:
        reasons.append("reviewer contributed to outcome")
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    if len(evidence) != len(membership) or {
        e.get("unit") for e in evidence if isinstance(e, dict) and isinstance(e.get("unit"), str)
    } != set(membership):
        reasons.append("missing member coverage")
    for reviewed in requested:
        unit = case_units.get(reviewed["id"])
        if not unit or unit.get("status") != "done" or not unit.get("evidence"):
            reasons.append("missing successful member evidence or dropped member")
            continue
        host_evidence = unit["evidence"]
        if (
            not isinstance(host_evidence, dict)
            or not host_evidence.get("attempt_id")
            or not host_evidence.get("artifact")
            or host_evidence.get("fast_check_passed") is not True
            or host_evidence.get("revision") != digest(unit["fixed"])
        ):
            reasons.append("invalid successful member evidence")
        if (
            reviewed.get("revision") != digest(unit["fixed"])
            or reviewed.get("snippet") != unit["fixed"]
        ):
            reasons.append("changed exact revision")
        required = {c["id"] for c in unit["acceptance_criteria"]}
        if reviewed.get("acceptance_criteria") != unit["acceptance_criteria"]:
            reasons.append("changed criteria")
        matches = [e for e in evidence if isinstance(e, dict) and e.get("unit") == unit["id"]]
        if (
            len(matches) != 1
            or matches[0].get("revision") != digest(unit["fixed"])
            or not isinstance(matches[0].get("criteria"), list)
            or not all(isinstance(c, str) for c in matches[0]["criteria"])
            or set(matches[0]["criteria"]) != required
        ):
            reasons.append("stale or incomplete criterion evidence")
    if not check_oracle(case, "fixed")["passed"]:
        reasons.append("deterministic final oracle failed")
    return {"approved": not reasons, "reasons": sorted(set(reasons))}


def usage_total(usage: object) -> int | None:
    if not isinstance(usage, dict):
        return None
    values = [usage.get(field) for field in TOKEN_FIELDS]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(values)


def now() -> str:
    return datetime.now(UTC).isoformat()


# How long to keep reading pipes after the kill; a holder outside the group cannot hang us.
DRAIN_SECONDS = 2.0


# Windows creation flag: the adapter's first thread does not run until resumed.
CREATE_SUSPENDED = 0x00000004
# SetInformationJobObject class and the flag that kills members when the job closes.
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def _job_limit_info(ctypes):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION with KILL_ON_JOB_CLOSE set."""

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = Extended()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return info


def _windows() -> bool:
    return os.name == "nt"


_popen = subprocess.Popen


class _WindowsJob:
    """A Job Object holding the adapter and every process it starts (Windows only).

    The adapter is created suspended, so it has executed nothing - not even a venv
    ``python.exe`` launcher that would start the real interpreter - when its own
    handle is assigned to the job. Only then is it resumed, so every descendant is
    born inside the job (no breakaway flag is granted). TerminateJobObject kills
    them all, whether or not the adapter has exited. Reasoned and checked against
    stubbed kernel32/ntdll; never executed on a Windows host.
    """

    def __init__(self, process: subprocess.Popen, kernel32=None, ntdll=None):
        self._job = None
        try:
            self._jail(process, kernel32, ntdll)
        except BaseException:
            # Never leave a suspended adapter behind, whatever failed; a failing
            # kill must not mask the jailing error, nor skip the wait and close.
            try:
                process.kill()
            except OSError:
                pass
            finally:
                try:
                    process.wait()
                finally:
                    self.close()
            raise

    def _jail(self, process: subprocess.Popen, kernel32, ntdll) -> None:
        import ctypes

        if kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            ntdll = ctypes.WinDLL("ntdll")
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        kernel32.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        ntdll.NtResumeProcess.argtypes = (ctypes.c_void_p,)
        ntdll.NtResumeProcess.restype = ctypes.c_long
        self._kernel = kernel32
        self._job = kernel32.CreateJobObjectW(None, None)
        if not self._job:
            raise OSError("CreateJobObjectW failed")
        # Members die when the last job handle closes, even if the harness is killed.
        info = _job_limit_info(ctypes)
        if not kernel32.SetInformationJobObject(
            self._job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise OSError("SetInformationJobObject failed")
        handle = int(process._handle)
        if not kernel32.AssignProcessToJobObject(self._job, handle):
            raise OSError("AssignProcessToJobObject failed")
        if ntdll.NtResumeProcess(handle) != 0:
            raise OSError("NtResumeProcess failed")

    def kill(self) -> None:
        if self._job and not self._kernel.TerminateJobObject(self._job, 1):
            raise OSError("TerminateJobObject failed")

    def close(self) -> None:
        if self._job:
            self._kernel.CloseHandle(self._job)
            self._job = None


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def run_contained(
    command: list[str], stdin: str, cwd: str, timeout: float
) -> subprocess.CompletedProcess:
    """Like subprocess.run, but a timeout or a return never leaves a descendant running.

    POSIX (measured): the adapter leads a new session, and its whole process group
    is killed on timeout, on any error, and after a normal exit, so no straggler of
    call N overlaps call N+1. A process that deliberately leaves the group (setsid)
    is outside this guarantee, but cannot hang the call: reading after the kill is
    bounded by DRAIN_SECONDS. If the adapter exited before the deadline and only a
    straggler held its pipe, the adapter's own exit status and output stand.
    Windows (reasoned, never executed there): the adapter starts suspended inside a
    Job Object (see _WindowsJob), which is terminated on the same three paths. The
    drain bound is POSIX-only; on Windows it rests on the job containing every pipe
    holder, and partial timeout output is lost only if a holder escaped the job.
    """
    windows = _windows()
    process = _popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        **({"creationflags": CREATE_SUSPENDED} if windows else {"start_new_session": True}),
    )
    try:
        job = _WindowsJob(process) if windows else None
    except BaseException:
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        raise

    def kill_tree() -> None:
        if job is not None:
            job.kill()
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def drain() -> tuple[str, str]:
        try:
            return process.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired as exc:
            out, err = _decode(exc.stdout), _decode(exc.stderr)
            for pipe in (process.stdout, process.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
            process.wait()
            return out, err

    try:
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            exited = process.poll() is not None
            kill_tree()
            stdout, stderr = drain()
            if not exited:
                raise subprocess.TimeoutExpired(command, timeout, stdout, stderr) from None
        except BaseException:
            kill_tree()
            process.wait()
            raise
        kill_tree()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        if job is not None:
            job.close()


def failed_envelope(stdout: str) -> dict | None:
    """The last JSON object a failed adapter printed, if it printed one."""
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def invoke(out: Path, command: list[str], request: dict, timeout: float, call_id: str) -> dict:
    directory = out / "calls" / call_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    call = {
        "id": call_id,
        "stage": request["stage"],
        "request": request,
        "started_at": now(),
        "artifact_dir": str(directory.relative_to(out)),
        "stdout": "",
        "stderr": "",
        "error": None,
        "response": None,
        "usage": None,
        "review_tokens": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="grouped-review-") as scratch:
            completed = run_contained(command, json.dumps(request), scratch, timeout)
        call.update(
            stdout=completed.stdout, stderr=completed.stderr, returncode=completed.returncode
        )
        if completed.returncode:
            call["error"] = f"exit status {completed.returncode}"
            envelope = failed_envelope(completed.stdout)
            if envelope is not None:
                # A failed call still spent its known tokens; keep them, never approve.
                if isinstance(envelope.get("error"), str):
                    call["error"] += f": {envelope['error']}"
                call["usage"] = envelope.get("usage")
                call["review_tokens"] = usage_total(call["usage"])
        else:
            try:
                response = json.loads(completed.stdout)
                call["response"] = response
                call["error"] = validate_response(request, response)
                if isinstance(response, dict):
                    call["usage"] = response.get("usage")
                    call["review_tokens"] = usage_total(call["usage"])
            except (ValueError, TypeError) as exc:
                call["error"] = f"json response error: {exc}"
    except subprocess.TimeoutExpired as exc:
        call["error"] = f"timeout after {timeout}s"
        call["stdout"] = exc.stdout or ""
        call["stderr"] = exc.stderr or ""
    except OSError as exc:
        call["error"] = f"process error: {exc}"
    call["elapsed_ms"] = (time.monotonic() - started) * 1000
    call["stopped_at"] = now()
    (directory / "stdout.txt").write_text(call["stdout"], encoding="utf-8")
    (directory / "stderr.txt").write_text(call["stderr"], encoding="utf-8")
    (directory / "call.json").write_text(json.dumps(call, indent=2) + "\n", encoding="utf-8")
    return call


def run_arm(
    out: Path, command: list[str], timeout: float, case: dict, arm: str, repeat: int, order: int
) -> dict:
    started = time.monotonic()
    record = {
        "case_id": case["id"],
        "execution_mode": case["execution_mode"],
        "repeat": repeat,
        "arm": arm,
        "order": order,
        "started_at": now(),
        "calls": [],
        "accepted": False,
        "full_job_tokens": None,
        "elapsed_to_accepted_ms": None,
        "rework": {"kind": "predetermined fixed fixture replay", "author_tokens": None},
    }
    members = [u["id"] for u in case["units"]]
    batches = [[u] for u in members] if arm == "per-task" else [members]
    approvals = []
    for stage in ("seeded", "fixed"):
        for membership in batches:
            context = "independent-reviewer-" + uuid.uuid4().hex
            request = make_request(case, stage, membership, context)
            call_id = f"{case['id']}-{repeat}-{arm}-{stage}-{len(record['calls'])}"
            call = invoke(out, command, request, timeout, call_id)
            record["calls"].append(call)
            if stage == "fixed":
                verdict = (
                    assess_approval(case, request, call["response"])
                    if not call["error"]
                    else {"approved": False, "reasons": [call["error"]]}
                )
                call["approval"] = verdict
                approvals.append(verdict["approved"])
    initial = [
        f
        for c in record["calls"]
        if c["stage"] == "seeded" and not c["error"]
        for f in c["response"]["findings"]
    ]
    keys = {(c["unit"], c["criterion"]) for c in case["oracle"]}
    found = {(f["unit"], f["criterion"]) for f in initial}
    record["quality"] = {
        "caught": len(keys & found),
        "missed": len(keys - found),
        "false_findings": sum((f["unit"], f["criterion"]) not in keys for f in initial),
    }
    record["caught_keys"] = [list(k) for k in sorted(keys & found)]
    record["missed_keys"] = [list(k) for k in sorted(keys - found)]
    totals = [c["review_tokens"] for c in record["calls"]]
    record["review_tokens"] = sum(totals) if all(t is not None for t in totals) else None
    record["accepted"] = all(approvals) and not any(c["error"] for c in record["calls"])
    record["oracle"] = {
        "seeded": check_oracle(case, "seeded"),
        "fixed": check_oracle(case, "fixed"),
    }
    record["elapsed_to_stop_ms"] = (time.monotonic() - started) * 1000
    if record["accepted"]:
        record["elapsed_to_accepted_ms"] = record["elapsed_to_stop_ms"]
    record["stopped_at"] = now()
    record["status"] = "accepted" if record["accepted"] else "failed/censored"
    return record


def distribution(values: list) -> dict:
    known = [v for v in values if v is not None]
    return {
        "sample_size": len(known),
        "unknown_or_censored": len(values) - len(known),
        "median": statistics.median(known) if known else None,
        "range": [min(known), max(known)] if known else None,
    }


def fingerprint(record: dict) -> str | None:
    identities = set()
    for call in record["calls"]:
        response = call.get("response")
        if (
            call.get("error")
            or not isinstance(response, dict)
            or not isinstance(response.get("settings"), dict)
        ):
            return None
        identities.add(
            json.dumps(
                {"model": response["model"], "settings": response["settings"]}, sort_keys=True
            )
        )
    return next(iter(identities)) if len(identities) == 1 else None


def summarize(records: list[dict]) -> dict:
    pairs, modes = [], {}
    keys = sorted({(r["case_id"], r["repeat"]) for r in records})
    for case_id, repeat in keys:
        matched = [r for r in records if r["case_id"] == case_id and r["repeat"] == repeat]
        arms = {r["arm"]: r for r in matched}
        per, grouped = arms.get("per-task"), arms.get("grouped")
        comparable = bool(
            len(matched) == 2
            and per
            and grouped
            and fingerprint(per) is not None
            and fingerprint(per) == fingerprint(grouped)
        )
        saving = None
        if comparable and per["review_tokens"] and grouped["review_tokens"] is not None:
            saving = 1 - grouped["review_tokens"] / per["review_tokens"]
        pairs.append(
            {
                "case_id": case_id,
                "repeat": repeat,
                "comparable": comparable,
                "reason": None
                if comparable
                else "Missing/failed arm or unknown/mixed actual model/settings.",
                "review_saving": saving,
                "total_saving": None,
                "grouped_missed_caught_by_per_task": sorted(
                    [
                        list(k)
                        for k in (
                            {tuple(k) for k in per["caught_keys"]}
                            - {tuple(k) for k in grouped["caught_keys"]}
                        )
                    ]
                )
                if per and grouped
                else None,
                "both_accepted": bool(per and grouped and per["accepted"] and grouped["accepted"]),
            }
        )
    for case_id in sorted({r["case_id"] for r in records}):
        modes[case_id] = {}
        for arm in ("per-task", "grouped"):
            cohort = [r for r in records if r["case_id"] == case_id and r["arm"] == arm]
            modes[case_id][arm] = {
                "sample_size": len(cohort),
                "accepted": sum(r["accepted"] for r in cohort),
                "failed_or_censored": sum(not r["accepted"] for r in cohort),
                **{
                    key: distribution([r[key] for r in cohort])
                    for key in ("review_tokens", "elapsed_to_accepted_ms", "elapsed_to_stop_ms")
                },
                "quality": {
                    key: distribution([r["quality"][key] for r in cohort])
                    for key in ("caught", "missed", "false_findings")
                },
            }
    return {
        "adoption": "inconclusive",
        "full_job_tokens": None,
        "limitations": LIMITS,
        "run_count": len(records),
        "pairs": pairs,
        "modes": modes,
        "review_saving": distribution([p["review_saving"] for p in pairs]),
    }


def run_pilot(
    out: Path,
    command: list[str],
    repeats: int = 3,
    timeout: float = 120,
    cases: list[dict] | None = None,
) -> dict:
    if type(repeats) is not int or repeats < 1 or timeout <= 0:
        raise ValueError("repeats and timeout must be positive")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(x, str) or not x for x in command)
    ):
        raise ValueError("command must be a nonempty JSON argv array")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    cases = builtin_cases() if cases is None else cases
    metadata = {
        "started_at": now(),
        "command": command,
        "repeats": repeats,
        "timeout": timeout,
        "host": platform.platform(),
        "python": platform.python_version(),
        "harness_sha256": digest(Path(__file__).read_text(encoding="utf-8")),
        "cases": cases,
        "limitations": LIMITS,
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    records = []
    with (out / "runs.jsonl").open("w", encoding="utf-8") as stream:
        for case in cases:
            for repeat in range(repeats):
                arms = ("per-task", "grouped") if repeat % 2 == 0 else ("grouped", "per-task")
                for order, arm in enumerate(arms):
                    record = run_arm(out, command, timeout, case, arm, repeat, order)
                    records.append(record)
                    stream.write(json.dumps(record) + "\n")
                    stream.flush()
    summary = summarize(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--command", help="JSON argv; use absolute executable and adapter paths (fresh scratch cwd)"
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--summarize",
        type=Path,
        help="Existing runs.jsonl or output directory; print recomputed summary",
    )
    args = parser.parse_args()
    if args.summarize:
        source = args.summarize / "runs.jsonl" if args.summarize.is_dir() else args.summarize
        result = summarize(
            [
                json.loads(line)
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        )
    else:
        if not args.out or not args.command:
            parser.error("--out and --command are required unless --summarize is given")
        result = run_pilot(args.out, json.loads(args.command), args.repeats, args.timeout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
