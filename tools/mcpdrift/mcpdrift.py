"""Notice when two endpoints registered under ONE MCP server name stop being one tool.

THE RULE IS `docs/mcp.md#one-name-two-endpoints`. THIS IS THE MECHANISM, and the two
land together for the reason `amendguard` names: a rule with no checker is one more
intention for the next drift to walk past.

WHAT THIS EXISTS FOR, MEASURED. `bantamkit` is registered twice on a developer machine:
user scope (a PINNED install, frozen at whatever `main` was on the day it was installed)
and project scope (the repo's EDITABLE `.venv`, which tracks HEAD). `claude mcp list`
prints `[Conflicting scopes]` and then connects you to one of them without saying which
build you got. On 2026-08-20 those two were twelve minor versions apart for eleven days
and nothing anywhere noticed. A silent disagreement between two builds under one name is
indistinguishable from a bug in whichever one you happened to reach.

WHY NOT THE VERSION STRING. Because it has already lied in this program's history: before
`RB-P45`, `_version()` read the INSTALLED dist-info, so an editable checkout of `v0.25.0`
advertised `0.3.0`. Two endpoints agreeing on `serverInfo.version` is therefore evidence
about one string and nothing else. Every surface below is compared, and the version is
only one of them:

    identity     serverInfo.name / serverInfo.version, capabilities
    instructions the MCP `instructions` field, which carries the memory skill ASSET
    tools        every tool's name, description and inputSchema (the asset pack verbatim)
    behaviour    what the SERVER ACTUALLY DOES when the tools are called

BEHAVIOUR IS THE PART THAT DOES THE WORK, and it is compared over a fixture this file
authors, in a temp directory, REBUILT BYTE-IDENTICALLY FOR EACH ENDPOINT — never over the
operator's real memory store. That is deliberate and it is the difference between a
discriminator and a coincidence: a probe reading the real store measures the store, so
it changes its verdict when a fact is saved and cannot be replayed tomorrow. Each server
is launched with `cwd` = a fresh fixture project and `HOME` = a fresh empty home, so the
project layer is the fixture, the profile layer is empty, and every byte of the answer is
a function of the BUILD. `BANTAMKIT_ASSETS` is stripped from the child environment for
the same reason: if it were inherited, both builds would read ONE asset pack and asset
drift — the thing `instructions` and `tools` exist to catch — would be masked.

The fixture is rebuilt per endpoint because `memory_recall` stamps `last_recalled` into
the fact files it returns. A shared fixture would hand the second server different bytes
than the first, and the difference would be reported as drift. That false positive was
the reason this is written the way it is.

THE PROBES, AND WHY EACH ONE.

  * `recall_k1` — `memory_recall(k=1)` over a fixture seeded with four matching facts.
    `RB-P1`'s k-floor makes a current build answer with the operator's configured
    default (3) and a pre-fix build answer with 1. This is the ONLY discriminator that
    ever worked on this machine while the version string was lying, and it is here
    because of that, not because it is elegant.
  * `recall_k5` — the same call above the floor, so a build that lost the floor entirely
    is distinguishable from one that lost only the clamp.
  * `recall_miss` — a query that matches nothing: the empty-result contract sentence.
  * `validate_json_invalid` — Layer-2 contract wording, model-free and deterministic.
    Contract text is exactly what drifts between two builds at the same version.
  * `shiftwork_status` — the checkpoint schema asset and the shift-work surface, over
    the committed `tools/shiftwork/example-checkpoint.json` copied into the fixture.
  * `recall_bad_arg_type` — a declared argument of the wrong type (`RB-P86`'s surface).
    It also catches DEPENDENCY drift, because the SDK's validation error text carries the
    validator's version. Two endpoints whose pydantic differs are not the same tool from
    the model's point of view, and this is the probe that says so.

WHAT IT COSTS, STATED PLAINLY.

  1. It calls the tools. Only read-only calls are made — `memory_save` is never called,
     `shiftwork_clock_out` is never called — but "run the probe" is a heavier act than
     "read a version string", and a future write-shaped probe would need its own fixture
     discipline.
  2. It is SENSITIVE. Any wording change, any asset edit, any dependency bump between the
     two endpoints fires it. That is the intended direction — a difference IS drift — but
     the verdict is "these two are not the same tool", never "this one is wrong". Which
     one you want is a decision for a person.
  3. It is BOUNDED BY WHAT IT PROBES. Two builds differing only on a path no probe touches
     are reported as agreeing. The surfaces are listed above so that gap is visible rather
     than implied.
  4. It needs a LIVE REGISTRATION, so it cannot run on CI (no `~/.claude.json`, no
     user-scope install). It is run deliberately, and `runtime-py/tests/test_mcpdrift.py`
     guards this file's LOGIC on synthetic servers it writes itself — never on a fact
     about this machine. Nothing skips: what CI cannot see, CI does not pretend to check.

EXIT CODES ARE THE INTERFACE.

    0  AGREE       two or more endpoints, every surface identical
    0  SINGLE      exactly one endpoint registered under the name; nothing can drift
    1  DIFFER      the endpoints disagree; the differing surfaces are named
    2  ERROR       an endpoint could not be handshaken — CANNOT COMPARE, which is not
                   the same statement as "compared and agreed"
    3  UNDETERMINED  no registration found for the name

`UNDETERMINED` is a separate code from `AGREE` on purpose. A checker that discovers
nothing and exits 0 is `RB-P51`'s defect wearing this file's name: an unmeasured check is
not a passed one.

USAGE

    python tools/mcpdrift/mcpdrift.py check
    python tools/mcpdrift/mcpdrift.py check --repo /path/to/project --json
    python tools/mcpdrift/mcpdrift.py check --endpoint a=/x/bin/bantamkit-mcp \\
                                            --endpoint b=/y/bin/bantamkit-mcp
    python tools/mcpdrift/mcpdrift.py check --endpoint a=/usr/bin/python3 /x/server.py \\
                                            --endpoint b=/usr/bin/python3 /y/server.py

`--endpoint` REPLACES discovery entirely and is how the checker is calibrated against a
deliberately older build. It takes `LABEL=COMMAND` followed by zero or more arguments,
because that is the shape a registration actually has: `.claude.json` and `.mcp.json`
both carry a `command` AND an `args` list, `discover` already folds that pair into a
multi-token argv, and a calibration flag that could express only a bare command could
not calibrate against the registrations this checker exists to compare — an interpreter
plus a script (`python -m ...`, `npx -y ...`) is the common shape, not the exotic one.
Nothing here relies on the operating system reading a `#!` line: the interpreter is
named on the command line, or it is not named at all.

`--repo` defaults to the cwd, because project scope is resolved
relative to the project you are actually in — not relative to where this file lives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CHECKPOINT = REPO_ROOT / "tools" / "shiftwork" / "example-checkpoint.json"

PROTOCOL_VERSION = "2024-11-05"

AGREE, DIFFER, ERROR, UNDETERMINED, SINGLE = 0, 1, 2, 3, 0

# Four facts sharing the query word, so a k-floor of three is distinguishable from a
# literal k=1 AND from "the store only had one match anyway".
FIXTURE_FACTS = [
    ("deploy-command", "how to deploy the service", "project", "Run `make deploy`."),
    ("deploy-window", "when the deploy window opens", "project", "Tuesdays, 09:00 UTC."),
    ("deploy-owner", "who owns the deploy pipeline", "project", "Team Atlas owns it."),
    ("deploy-rollback", "how to roll back a deploy", "reference", "`make deploy-undo`."),
]

FIXTURE_QUERY = "deploy"
FIXTURE_MISS_QUERY = "zzqqxx no fact uses these letters"


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


@dataclass
class Endpoint:
    label: str
    scope: str
    argv: list[str]
    cwd: str | None = None


@dataclass
class Fingerprint:
    endpoint: Endpoint
    surfaces: dict[str, Any] = field(default_factory=dict)
    excerpts: dict[str, str] = field(default_factory=dict)
    error: str | None = None


# --------------------------------------------------------------------------- discovery


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def discover(name: str, repo: Path, home: Path) -> list[Endpoint]:
    """Every registration of `name` a Claude Code session in `repo` could reach.

    Three scopes, in the order the CLI reports them. A relative `command` in a project's
    `.mcp.json` is resolved against the project directory, which is what the client does
    and what makes the same file mean different binaries in a worktree.
    """
    found: list[Endpoint] = []
    claude_json = _read_json(home / ".claude.json")

    entry = (claude_json.get("mcpServers") or {}).get(name)
    if entry:
        found.append(_endpoint("user", entry, repo))

    project_entry = (
        ((claude_json.get("projects") or {}).get(str(repo)) or {}).get("mcpServers") or {}
    ).get(name)
    if project_entry:
        found.append(_endpoint("local", project_entry, repo))

    mcp_entry = (_read_json(repo / ".mcp.json").get("mcpServers") or {}).get(name)
    if mcp_entry:
        found.append(_endpoint("project", mcp_entry, repo))

    return found


def _endpoint(scope: str, entry: dict[str, Any], repo: Path) -> Endpoint:
    command = entry.get("command", "")
    resolved = command
    if command and not command.startswith("/"):
        candidate = repo / command
        resolved = str(candidate) if candidate.exists() else command
    argv = [resolved, *(entry.get("args") or [])]
    return Endpoint(label=f"{scope}:{resolved}", scope=scope, argv=argv)


# ----------------------------------------------------------------------------- fixture


def _write_fixture(root: Path) -> tuple[Path, Path]:
    """A project directory and an empty home, authored here, identical every time."""
    home = root / "home"
    project = root / "project"
    facts = project / ".bantamkit" / "memory" / "facts"
    facts.mkdir(parents=True)
    home.mkdir()
    for slug, description, kind, body in FIXTURE_FACTS:
        (facts / f"{slug}.md").write_text(
            "---\n"
            f"name: {slug}\n"
            f"description: {description}\n"
            f"type: {kind}\n"
            "last_recalled: null\n"
            "links: []\n"
            "---\n\n"
            f"{body}\n", encoding="utf-8"
        )
    if EXAMPLE_CHECKPOINT.is_file():
        shutil.copyfile(EXAMPLE_CHECKPOINT, project / "checkpoint.json")
    return project, home


# ---------------------------------------------------------------------------- handshake


class _Session:
    """One stdio MCP session. Real subprocess, real JSON-RPC, no mocks anywhere."""

    def __init__(self, argv: list[str], cwd: Path, home: Path, timeout: float):
        env = {k: v for k, v in os.environ.items() if k != "BANTAMKIT_ASSETS"}
        env["HOME"] = str(home)
        self.timeout = timeout
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(cwd),
            env=env, encoding="utf-8",
        )
        self._id = 0

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        message = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise OSError(f"{method}: the server closed stdout without answering")
            try:
                parsed = json.loads(line)
            except ValueError:
                continue  # a server that logs to stdout; skip its noise, keep reading
            if parsed.get("id") == self._id:
                return parsed

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            self.proc.wait(timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def _call_text(session: _Session, tool: str, arguments: dict[str, Any]) -> str:
    """A tool call flattened to the text a model would actually receive.

    Errors are kept, not raised: `isError` responses are a behavioural surface too, and
    an endpoint that rejects a call the other accepts is precisely the disagreement this
    checker exists to name.
    """
    answer = session.request("tools/call", {"name": tool, "arguments": arguments})
    if "error" in answer:
        return "RPC-ERROR " + json.dumps(answer["error"], sort_keys=True)
    result = answer.get("result") or {}
    text = "".join(part.get("text", "") for part in result.get("content", []))
    return ("ERR " if result.get("isError") else "OK ") + text


def fingerprint(endpoint: Endpoint, timeout: float) -> Fingerprint:
    """Every compared surface of one endpoint, over a fixture built fresh for it."""
    out = Fingerprint(endpoint=endpoint)
    with tempfile.TemporaryDirectory(prefix="mcpdrift-") as tmp:
        project, home = _write_fixture(Path(tmp))
        try:
            session = _Session(endpoint.argv, project, home, timeout)
        except OSError as exc:
            out.error = f"cannot launch {endpoint.argv[0]}: {exc}"
            return out
        try:
            init = session.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcpdrift", "version": "1"},
                },
            )
            if "result" not in init:
                out.error = f"initialize failed: {json.dumps(init)[:200]}"
                return out
            result = init["result"]
            info = result.get("serverInfo") or {}
            out.surfaces["server_name"] = info.get("name")
            out.surfaces["server_version"] = info.get("version")
            out.surfaces["capabilities"] = _digest(result.get("capabilities"))
            instructions = result.get("instructions") or ""
            out.surfaces["instructions"] = _digest(instructions)
            out.excerpts["instructions"] = instructions[:120]

            session.notify("notifications/initialized")

            listed = session.request("tools/list", {})
            tools = (listed.get("result") or {}).get("tools") or []
            out.surfaces["tool_names"] = sorted(t.get("name", "") for t in tools)
            for tool in sorted(tools, key=lambda t: t.get("name", "")):
                key = f"tool_schema[{tool.get('name')}]"
                out.surfaces[key] = _digest(
                    {
                        "description": tool.get("description"),
                        "inputSchema": tool.get("inputSchema"),
                    }
                )

            for probe, tool, arguments in probes():
                text = _call_text(session, tool, arguments)
                out.surfaces[f"behaviour[{probe}]"] = _digest(text)
                out.excerpts[f"behaviour[{probe}]"] = text[:160]
                if probe == "recall_k1":
                    # Counted from the SAME response, never a second call: `recall`
                    # stamps `last_recalled`, so a repeat call reads a fixture the
                    # first call already mutated.
                    out.surfaces["behaviour[recall_k1_fact_count]"] = _fact_count(text)
        except (OSError, subprocess.SubprocessError) as exc:
            out.error = f"{type(exc).__name__}: {exc}"
        finally:
            session.close()
    return out


def probes() -> list[tuple[str, str, dict[str, Any]]]:
    """The behavioural probe set. `checkpoint.json` is relative to the fixture cwd."""
    return [
        ("recall_k1", "memory_recall", {"query": FIXTURE_QUERY, "k": 1}),
        ("recall_k5", "memory_recall", {"query": FIXTURE_QUERY, "k": 5}),
        ("recall_miss", "memory_recall", {"query": FIXTURE_MISS_QUERY, "k": 1}),
        (
            "validate_json_invalid",
            "validate_json",
            {
                "output": '{"a": 1}',
                "schema": {
                    "type": "object",
                    "required": ["b"],
                    "properties": {"b": {"type": "string"}},
                },
            },
        ),
        ("shiftwork_status", "shiftwork_status", {"checkpoint": "checkpoint.json"}),
        ("recall_bad_arg_type", "memory_recall", {"query": FIXTURE_QUERY, "k": "three"}),
    ]


def _fact_count(recall_text: str) -> int:
    """How many facts came back, counted the way the store formats them.

    Reported as its own surface rather than folded into the response digest, because it
    is the number a human can act on: `1` where the other endpoint says `3` is `RB-P1`,
    named, in the output, without anybody having to diff two hashes.

    The `OK `/`ERR ` marker `_call_text` prepends is stripped first — leaving it on made
    the FIRST fact uncountable and turned three facts into two, which is the kind of
    off-by-one that would have quietly weakened the only discriminator that matters. The
    fixture's bodies are authored here and none of them begins with `[`, so the count is
    exact for this fixture and is not claimed to be exact for any other.
    """
    body = recall_text.removeprefix("OK ").removeprefix("ERR ")
    return sum(1 for line in body.splitlines() if line.lstrip().startswith("["))


# ----------------------------------------------------------------------------- compare


def compare(prints: list[Fingerprint]) -> tuple[str, list[str]]:
    """The verdict and the surfaces that disagree. Never a judgement about which is right."""
    keys: list[str] = []
    for fp in prints:
        for key in fp.surfaces:
            if key not in keys:
                keys.append(key)
    differing = [
        key
        for key in keys
        if len({_digest(fp.surfaces.get(key, "<absent>")) for fp in prints}) > 1
    ]
    return ("DIFFER" if differing else "AGREE"), differing


def render(prints: list[Fingerprint], verdict: str, differing: list[str]) -> str:
    lines = [f"VERDICT {verdict}  endpoints={len(prints)}"]
    for fp in prints:
        lines.append(f"  endpoint {fp.endpoint.label}")
        lines.append(f"    argv    {' '.join(fp.endpoint.argv)}")
        if fp.error:
            lines.append(f"    ERROR   {fp.error}")
            continue
        lines.append(f"    version {fp.surfaces.get('server_version')!r}")
        lines.append(
            f"    recall(k=1) returned {fp.surfaces.get('behaviour[recall_k1_fact_count]')} fact(s)"
        )
    if differing:
        lines.append(f"  DIFFERING SURFACES ({len(differing)}):")
        for key in differing:
            lines.append(f"    {key}")
            for fp in prints:
                value = fp.surfaces.get(key, "<absent>")
                excerpt = fp.excerpts.get(key, "")
                shown = value if isinstance(value, (str, int, list)) else repr(value)
                lines.append(f"      {fp.endpoint.scope:<8} {shown}")
                if excerpt:
                    lines.append(f"               {excerpt!r}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcpdrift", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--server", default="bantamkit", help="registered server name")
    parser.add_argument("--repo", default=None, help="project directory (default: cwd)")
    parser.add_argument(
        "--endpoint",
        action="append",
        nargs="+",
        default=[],
        metavar="LABEL=COMMAND [ARG ...]",
        help="compare these instead of discovering; repeatable. Trailing tokens are the "
             "command's arguments, mirroring a registration's command+args pair",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    home = Path(os.path.expanduser("~"))

    if not EXAMPLE_CHECKPOINT.is_file():
        # Loud, not skipped: the `shiftwork_status` probe would otherwise degrade into
        # "both endpoints failed identically", which compares equal and says nothing.
        print(f"ERROR fixture source missing: {EXAMPLE_CHECKPOINT}", file=sys.stderr)
        return ERROR

    if args.endpoint:
        endpoints = []
        for spec in args.endpoint:
            label, _, command = spec[0].partition("=")
            if not label or not command:
                print(f"ERROR --endpoint needs LABEL=COMMAND, got {spec[0]!r}", file=sys.stderr)
                return ERROR
            argv_for = [command, *spec[1:]]
            endpoints.append(
                Endpoint(label=f"{label}:{' '.join(argv_for)}", scope=label, argv=argv_for)
            )
    else:
        endpoints = discover(args.server, repo, home)

    if not endpoints:
        print(
            f"VERDICT UNDETERMINED  no registration of {args.server!r} found "
            f"(searched {home / '.claude.json'} user+local scope, {repo / '.mcp.json'})"
        )
        return UNDETERMINED

    prints = [fingerprint(endpoint, args.timeout) for endpoint in endpoints]

    broken = [fp for fp in prints if fp.error]
    if broken:
        verdict, differing = "ERROR", []
    elif len(prints) == 1:
        verdict, differing = "SINGLE", []
    else:
        verdict, differing = compare(prints)

    if args.as_json:
        print(
            json.dumps(
                {
                    "verdict": verdict,
                    "differing": differing,
                    "endpoints": [
                        {
                            "label": fp.endpoint.label,
                            "scope": fp.endpoint.scope,
                            "argv": fp.endpoint.argv,
                            "error": fp.error,
                            "surfaces": fp.surfaces,
                        }
                        for fp in prints
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render(prints, verdict, differing))

    return {"AGREE": AGREE, "SINGLE": SINGLE, "DIFFER": DIFFER, "ERROR": ERROR}[verdict]


if __name__ == "__main__":
    raise SystemExit(main())
