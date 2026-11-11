"""Behavioral tests using real JSON subprocess reviewers, with no network calls."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "grouped_run_eval", Path(__file__).with_name("run_eval.py")
)


def harness():
    assert SPEC.origin and Path(SPEC.origin).exists(), "measurement harness is missing"
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def adapter(tmp_path, extra="", usage=None):
    path = tmp_path / "adapter.py"
    path.write_text(
        """import json, os, sys
r=json.load(sys.stdin)
assert os.listdir('.') == [], 'call cwd must start empty'
open('context','w').write(r['reviewer_context_id'])
findings=[]
if r['stage']=='seeded':
    for u in r['units']:
        findings.append({'unit':u['id'],'criterion':u['acceptance_criteria'][0]['id'],'detail':'The seeded implementation violates the criterion.'})
response={'model':'fixture-model','settings':{'temperature':0},'findings':findings,
          'reviewer_context_id':r['reviewer_context_id'],
          'evidence':[{'unit':u['id'],'revision':u['revision'],'criteria':[c['id'] for c in u['acceptance_criteria']]} for u in r['units']]}
"""
        + f"response['usage']={usage!r}\n"
        + extra
        + "\nprint(json.dumps(response))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(path)]


TOKENS = {
    "input_tokens": 10,
    "output_tokens": 2,
    "cache_read_input_tokens": 3,
    "cache_creation_input_tokens": 4,
}


def test_builtin_cases_have_real_seeded_failures_and_fixed_oracle_passes():
    m = harness()
    cases = m.builtin_cases()
    assert [c["id"] for c in cases] == ["native-chain", "delegated-chain", "mixed-fork-join"]
    for c in cases:
        assert len(c["units"]) == 3
        assert not m.check_oracle(c, "seeded")["passed"]
        assert m.check_oracle(c, "fixed")["passed"]
        assert len(c["oracle"]) == 3


def test_paired_replay_is_counterbalanced_fresh_and_records_cost_once(tmp_path):
    m = harness()
    out = tmp_path / "out"
    result = m.run_pilot(out, adapter(tmp_path, usage=TOKENS), repeats=2)
    records = [
        json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 12
    for offset in (0, 4, 8):
        assert [r["arm"] for r in records[offset : offset + 4]] == [
            "per-task",
            "grouped",
            "grouped",
            "per-task",
        ]
    contexts = []
    for r in records:
        assert r["accepted"]
        assert r["full_job_tokens"] is None
        assert r["elapsed_to_accepted_ms"] <= r["elapsed_to_stop_ms"]
        assert r["quality"] == {"caught": 3, "missed": 0, "false_findings": 0}
        assert r["review_tokens"] == (114 if r["arm"] == "per-task" else 38)
        assert len(r["calls"]) == (6 if r["arm"] == "per-task" else 2)
        assert r["rework"]["kind"] == "predetermined fixed fixture replay"
        for call in r["calls"]:
            contexts.append(call["request"]["reviewer_context_id"])
            prompt = json.dumps(call["request"])
            assert "oracle" not in prompt and "expected" not in prompt
            assert len(call["request"]["context_units"]) == 3
            assert call["usage"] == TOKENS
            assert (out / call["artifact_dir"] / "request.json").exists()
            assert (out / call["artifact_dir"] / "stdout.txt").exists()
            assert (out / call["artifact_dir"] / "stderr.txt").exists()
    assert len(contexts) == len(set(contexts))
    assert result["adoption"] == "inconclusive"
    assert len(result["pairs"]) == 6
    assert all(p["comparable"] for p in result["pairs"])
    assert all(p["review_saving"] == pytest.approx(2 / 3) for p in result["pairs"])
    assert result["modes"]["native-chain"]["grouped"]["review_tokens"]["sample_size"] == 2
    assert json.loads((out / "summary.json").read_text(encoding="utf-8")) == result
    with pytest.raises(FileExistsError):
        m.run_pilot(out, adapter(tmp_path), repeats=1)


def test_arms_review_identical_content_and_criteria(tmp_path):
    m = harness()
    m.run_pilot(
        tmp_path / "out", adapter(tmp_path, usage=TOKENS), repeats=1, cases=m.builtin_cases()[:1]
    )
    records = [
        json.loads(s)
        for s in (tmp_path / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for stage in ("seeded", "fixed"):
        per = [u for c in records[0]["calls"] if c["stage"] == stage for u in c["request"]["units"]]
        group = next(c["request"]["units"] for c in records[1]["calls"] if c["stage"] == stage)
        assert per == group


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": 1},
        {**TOKENS, "input_tokens": True},
        {**TOKENS, "output_tokens": -1},
    ],
)
def test_missing_or_invalid_usage_never_becomes_free(tmp_path, usage):
    m = harness()
    summary = m.run_pilot(
        tmp_path / "out", adapter(tmp_path, usage=usage), repeats=1, cases=m.builtin_cases()[:1]
    )
    records = [
        json.loads(s)
        for s in (tmp_path / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(r["review_tokens"] is None for r in records)
    assert summary["pairs"][0]["review_saving"] is None
    assert summary["modes"]["native-chain"]["grouped"]["review_tokens"]["sample_size"] == 0


@pytest.mark.parametrize(
    "extra,error",
    [
        ("raise SystemExit(7)", "exit"),
        ("print('not json'); raise SystemExit(0)", "json"),
        ("import time; print('partial',flush=True); time.sleep(3)", "timeout"),
        ("response['findings']=[{'unit':'alien','criterion':'bad','detail':'bad'}]", "response"),
    ],
)
def test_failures_preserved_and_never_approved(tmp_path, extra, error):
    m = harness()
    m.run_pilot(
        tmp_path / "out",
        adapter(tmp_path, extra, usage=TOKENS),
        repeats=1,
        timeout=0.2,
        cases=m.builtin_cases()[:1],
    )
    records = [
        json.loads(s)
        for s in (tmp_path / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(not r["accepted"] and r["elapsed_to_accepted_ms"] is None for r in records)
    assert all(any(error in c["error"] for c in r["calls"] if c["error"]) for r in records)
    if error == "response":
        assert [r["review_tokens"] for r in records] == [
            114,
            38,
        ]  # usage remains real even with invalid findings
    else:
        assert all(r["review_tokens"] is None for r in records)
    if error == "timeout":
        assert any("partial" in c["stdout"] for r in records for c in r["calls"])


@pytest.mark.parametrize(
    "fault",
    [
        "missing-evidence",
        "dropped",
        "contributor",
        "revision",
        "coverage",
        "context",
        "findings",
        "oracle",
    ],
)
def test_approval_fails_closed_for_invalid_evidence(fault):
    m = harness()
    c = m.builtin_cases()[0]
    request = m.make_request(c, "fixed", [u["id"] for u in c["units"]], "reviewer-independent")
    response = {
        "model": "model",
        "findings": [],
        "reviewer_context_id": request["reviewer_context_id"],
        "evidence": [
            {
                "unit": u["id"],
                "revision": u["revision"],
                "criteria": [x["id"] for x in u["acceptance_criteria"]],
            }
            for u in request["units"]
        ],
    }
    assert m.assess_approval(c, request, response)["approved"]
    if fault == "missing-evidence":
        c["units"][0]["evidence"] = None
    if fault == "dropped":
        c["units"][0]["status"] = "dropped"
    if fault == "contributor":
        request["reviewer_context_id"] = c["units"][0]["author_id"]
    if fault == "revision":
        request["units"][0]["revision"] = "stale"
    if fault == "coverage":
        response["evidence"].pop()
    if fault == "context":
        response["reviewer_context_id"] = "other"
    if fault == "findings":
        response["findings"] = [
            {
                "unit": request["membership"][0],
                "criterion": request["units"][0]["acceptance_criteria"][0]["id"],
                "detail": "still wrong",
            }
        ]
    if fault == "oracle":
        c["units"][0]["fixed"] = c["units"][0]["seeded"]
    assert not m.assess_approval(c, request, response)["approved"]


def test_mixed_models_or_settings_are_incomparable(tmp_path):
    m = harness()
    summary = m.run_pilot(
        tmp_path / "out",
        adapter(
            tmp_path,
            "response['model']='group-model' if len(r['units'])>1 else 'per-model'",
            usage=TOKENS,
        ),
        repeats=1,
        cases=m.builtin_cases()[:1],
    )
    assert not summary["pairs"][0]["comparable"]
    assert summary["pairs"][0]["review_saving"] is None
    summary = m.run_pilot(
        tmp_path / "other",
        adapter(tmp_path, "response['settings']={'temperature':len(r['units'])}", usage=TOKENS),
        repeats=1,
        cases=m.builtin_cases()[:1],
    )
    assert not summary["pairs"][0]["comparable"]


def test_initial_misses_and_false_findings_are_preserved(tmp_path):
    m = harness()
    extra = """if r['stage']=='seeded':
    response['findings']=[{'unit':r['units'][0]['id'],'criterion':r['units'][0]['acceptance_criteria'][1]['id'],'detail':'Unsupported complaint'}]
"""
    m.run_pilot(
        tmp_path / "out",
        adapter(tmp_path, extra, usage=TOKENS),
        repeats=1,
        cases=m.builtin_cases()[:1],
    )
    records = [
        json.loads(s)
        for s in (tmp_path / "out" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["quality"] == {"caught": 0, "missed": 3, "false_findings": 3}
    assert records[1]["quality"] == {"caught": 0, "missed": 3, "false_findings": 1}
    assert all(
        r["accepted"] for r in records
    )  # final acceptance is distinct from seeded defect detection


def test_cli_summary_round_trip(tmp_path):
    import subprocess

    m = harness()
    expected = m.run_pilot(
        tmp_path / "out", adapter(tmp_path, usage=TOKENS), repeats=1, cases=m.builtin_cases()[:1]
    )
    completed = subprocess.run(
        [sys.executable, SPEC.origin, "--summarize", str(tmp_path / "out" / "runs.jsonl")],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    assert json.loads(completed.stdout) == expected


@pytest.mark.parametrize(
    "fault",
    [
        "context-revision",
        "stale-host-evidence",
        "failed-check",
        "missing-attempt",
        "malformed-coverage",
        "empty-context",
    ],
)
def test_approval_rejects_integrated_context_and_evidence_faults(fault):
    m = harness()
    c = m.builtin_cases()[0]
    request = m.make_request(c, "fixed", ["A"], "independent")
    response = {
        "model": "model",
        "findings": [],
        "reviewer_context_id": "independent",
        "evidence": [
            {
                "unit": "A",
                "revision": request["units"][0]["revision"],
                "criteria": [x["id"] for x in request["units"][0]["acceptance_criteria"]],
            }
        ],
    }
    assert m.assess_approval(c, request, response)["approved"]
    if fault == "context-revision":
        request["context_units"][2]["revision"] = "changed"
    if fault == "stale-host-evidence":
        c["units"][0]["evidence"]["revision"] = "stale"
    if fault == "failed-check":
        c["units"][0]["evidence"]["fast_check_passed"] = False
    if fault == "missing-attempt":
        c["units"][0]["evidence"].pop("attempt_id")
    if fault == "malformed-coverage":
        response["evidence"][0]["criteria"] = [{}]
    if fault == "empty-context":
        request["reviewer_context_id"] = ""
        response["reviewer_context_id"] = ""
    assert not m.assess_approval(c, request, response)["approved"]


def test_fork_join_members_have_parallel_branch_dependencies():
    m = harness()
    units = m.builtin_cases()[2]["units"]
    assert [u["depends_on"] for u in units] == [[], [], ["A", "B"]]


def test_seeded_evidence_does_not_claim_fixed_revision_passed():
    m = harness()
    case = m.builtin_cases()[0]
    request = m.make_request(case, "seeded", ["A"], "reviewer")
    for u in request["context_units"]:
        assert u["evidence"]["revision"] == u["revision"]
        assert u["evidence"]["fast_check_passed"] is None


def test_missing_actual_settings_makes_pair_incomparable(tmp_path):
    m = harness()
    summary = m.run_pilot(
        tmp_path / "out",
        adapter(tmp_path, "response.pop('settings')", usage=TOKENS),
        repeats=1,
        cases=m.builtin_cases()[:1],
    )
    assert not summary["pairs"][0]["comparable"]
    assert summary["pairs"][0]["review_saving"] is None


def script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return [sys.executable, str(path)]


def one_request(m):
    case = m.builtin_cases()[0]
    return m.make_request(case, "seeded", [case["units"][0]["id"]], "review-ctx")


# A grandchild that outlives its parent writes the marker; a reaped one never does.
LINGERER = """import subprocess, sys
child = "import time, pathlib; time.sleep(0.6); pathlib.Path(%r).write_text('alive')" % ({marker!r},)
subprocess.Popen([sys.executable, '-c', child],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
"""


def test_timeout_kills_adapter_descendants(tmp_path):
    import time

    m = harness()
    marker = tmp_path / "survivor"
    command = script(
        tmp_path,
        "hang.py",
        LINGERER.format(marker=str(marker)) + "import time; time.sleep(5)\n",
    )
    started = time.monotonic()
    call = m.invoke(tmp_path / "out", command, one_request(m), 0.2, "hang")
    assert "timeout" in call["error"]
    assert time.monotonic() - started < 2, "invoke must not wait on the hung adapter"
    time.sleep(1.2)
    assert not marker.exists(), "a descendant survived the timeout and kept running"


def test_returned_call_leaves_no_descendant_to_overlap_the_next(tmp_path):
    import time

    m = harness()
    marker = tmp_path / "survivor"
    command = script(
        tmp_path,
        "leaky.py",
        LINGERER.format(marker=str(marker)) + "raise SystemExit(3)\n",
    )
    call = m.invoke(tmp_path / "out", command, one_request(m), 5, "leaky")
    assert "exit status 3" in call["error"]
    time.sleep(1.2)
    assert not marker.exists(), "a descendant outlived its call and could overlap the next"


def test_failed_call_envelope_keeps_known_usage(tmp_path):
    m = harness()
    usage = {
        "input_tokens": 60,
        "output_tokens": 8,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 0,
    }
    envelope = {"status": "blocked", "error": "No reviewer answer", "usage": usage}
    command = script(
        tmp_path,
        "failed.py",
        f"import json\nprint(json.dumps({envelope!r}))\nraise SystemExit(1)\n",
    )
    call = m.invoke(tmp_path / "out", command, one_request(m), 5, "failed")
    assert "exit status 1" in call["error"] and "No reviewer answer" in call["error"]
    assert call["response"] is None
    assert call["usage"] == usage
    assert call["review_tokens"] == 108


def test_straggler_holding_stdout_does_not_discard_a_printed_answer(tmp_path):
    import time

    m = harness()
    usage = {
        "input_tokens": 60,
        "output_tokens": 8,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 0,
    }
    envelope = {"status": "blocked", "error": "No reviewer answer", "usage": usage}
    # The grandchild inherits stdout, so the pipe stays open after the adapter exits.
    command = script(
        tmp_path,
        "straggler.py",
        "import json, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"print(json.dumps({envelope!r}), flush=True)\n"
        "raise SystemExit(1)\n",
    )
    started = time.monotonic()
    call = m.invoke(tmp_path / "out", command, one_request(m), 1, "straggler")
    assert time.monotonic() - started < 5
    assert "timeout" not in call["error"]
    assert "exit status 1" in call["error"]
    assert call["review_tokens"] == 108


@pytest.mark.skipif(sys.platform == "win32", reason="start_new_session is a no-op on Windows")
def test_escaped_pipe_holder_cannot_hang_invoke_after_timeout(tmp_path):
    import os
    import signal
    import time

    m = harness()
    pidfile = tmp_path / "escaped.pid"
    # A grandchild in its own session escapes the group kill but holds stderr open.
    command = script(
        tmp_path,
        "escaped.py",
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'],"
        " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, start_new_session=True)\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "print('partial', flush=True)\n"
        "time.sleep(30)\n",
    )
    started = time.monotonic()
    try:
        call = m.invoke(tmp_path / "out", command, one_request(m), 0.3, "escaped")
        assert time.monotonic() - started < m.DRAIN_SECONDS + 3
        assert "timeout" in call["error"]
        assert "partial" in call["stdout"]
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text(encoding="utf-8")), signal.SIGKILL)
            except ProcessLookupError:
                pass


class FakeProcess:
    """Stands in for a Windows Popen; records the order of what happens to it."""

    def __init__(self, events, **kwargs):
        self.events, self.kwargs = events, kwargs
        self.pid, self._handle, self.returncode = 4242, 777, None
        self.stdin, self.stdout, self.stderr = FakePipe(), FakePipe(), FakePipe()
        events.append("spawn")

    def communicate(self, stdin=None, timeout=None):
        self.events.append("communicate")
        self.returncode = 0
        return "{}", ""

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.events.append("wait")
        return self.returncode

    def kill(self):
        self.events.append("kill")


class FakePipe:
    closed = False

    def close(self):
        self.closed = True


def test_windows_adapter_is_jailed_before_it_runs(monkeypatch):
    m = harness()
    events = []
    spawned = {}

    def popen(command, **kwargs):
        spawned["kwargs"] = kwargs
        spawned["process"] = FakeProcess(events, **kwargs)
        return spawned["process"]

    class Job:
        def __init__(self, process):
            assert process is spawned["process"]
            events.append("assign+resume")

        def kill(self):
            events.append("terminate")

        def close(self):
            events.append("close")

    monkeypatch.setattr(m, "_windows", lambda: True)
    monkeypatch.setattr(m, "_popen", popen)
    monkeypatch.setattr(m, "_WindowsJob", Job)
    done = m.run_contained(["adapter"], "{}", ".", 5)
    assert done.returncode == 0
    assert spawned["kwargs"]["creationflags"] & m.CREATE_SUSPENDED
    assert "start_new_session" not in spawned["kwargs"]
    # Jailed while suspended, before any request reaches it; killed and released after.
    assert events == ["spawn", "assign+resume", "communicate", "terminate", "close"]


class FakeDll:
    def __init__(self, calls, fail=()):
        self.calls, self.fail = calls, fail

    def __getattr__(self, name):
        calls, fail = self.calls, self.fail

        class Function:
            restype = None
            argtypes = None

            def __call__(self, *args):
                calls.append((name, *args))
                if name in fail:
                    return 0 if name != "NtResumeProcess" else -1
                if name == "CreateJobObjectW":
                    return 99
                return 0 if name == "NtResumeProcess" else 1

        function = Function()
        setattr(self, name, function)
        return function


def test_windows_job_assigns_suspended_handle_then_resumes():
    m = harness()
    calls = []
    process = FakeProcess([])
    job = m._WindowsJob(process, kernel32=FakeDll(calls), ntdll=FakeDll(calls))
    job.kill()
    job.close()
    job.close()
    assert [c[0] for c in calls] == [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "NtResumeProcess",
        "TerminateJobObject",
        "CloseHandle",
    ]
    assert calls[2][1:] == (99, 777) and calls[3][1:] == (777,)
    # The job kills its members even if the harness dies before kill() runs.
    job_handle, info_class, info, size = calls[1][1:]
    assert job_handle == 99 and info_class == m.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION
    assert info._obj.BasicLimitInformation.LimitFlags & m.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert size == __import__("ctypes").sizeof(info._obj)


@pytest.mark.parametrize("failing", ["AssignProcessToJobObject", "NtResumeProcess"])
def test_windows_job_failure_kills_the_suspended_adapter(failing):
    m = harness()
    calls, events = [], []
    process = FakeProcess(events)
    with pytest.raises(OSError):
        m._WindowsJob(process, kernel32=FakeDll(calls, {failing}), ntdll=FakeDll(calls, {failing}))
    assert "kill" in events
    assert calls[-1][0] == "CloseHandle"
    if failing == "AssignProcessToJobObject":
        assert "NtResumeProcess" not in [c[0] for c in calls]


def test_windows_job_kills_adapter_when_the_dll_cannot_load():
    m = harness()
    events = []
    process = FakeProcess(events)

    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("no such dll")

    with pytest.raises(RuntimeError):
        m._WindowsJob(process, kernel32=Broken(), ntdll=Broken())
    assert "kill" in events


def test_windows_job_failure_reports_the_jailing_error_even_if_kill_fails():
    m = harness()
    calls, events = [], []

    class Unkillable(FakeProcess):
        def kill(self):
            events.append("kill")
            raise PermissionError("access denied")

    process = Unkillable(events)
    with pytest.raises(OSError, match="AssignProcessToJobObject"):
        m._WindowsJob(
            process,
            kernel32=FakeDll(calls, {"AssignProcessToJobObject"}),
            ntdll=FakeDll(calls),
        )
    assert "wait" in events
    assert calls[-1][0] == "CloseHandle"


def test_windows_terminate_failure_is_not_silent():
    m = harness()
    calls = []
    job = m._WindowsJob(
        FakeProcess([]), kernel32=FakeDll(calls, {"TerminateJobObject"}), ntdll=FakeDll(calls)
    )
    with pytest.raises(OSError, match="TerminateJobObject"):
        job.kill()
    job.close()


def test_windows_jailing_failure_closes_adapter_pipes(monkeypatch):
    m = harness()
    spawned = {}

    def popen(command, **kwargs):
        spawned["process"] = FakeProcess([], **kwargs)
        return spawned["process"]

    class Refused:
        def __init__(self, process):
            raise OSError("AssignProcessToJobObject failed")

    monkeypatch.setattr(m, "_windows", lambda: True)
    monkeypatch.setattr(m, "_popen", popen)
    monkeypatch.setattr(m, "_WindowsJob", Refused)
    with pytest.raises(OSError):
        m.run_contained(["adapter"], "{}", ".", 5)
    process = spawned["process"]
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
