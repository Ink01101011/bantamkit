"""Reply-native eval (#292). Drives `claude -p` over arms × sequences × repeats.

    python3 -I tools/eval/reply-native/run_eval.py --out <dir> [--reps 3] [--model claude-opus-5-5]

Each session runs in a fresh scratch project whose .claude/settings.json sets the arm's env.
Every arm except G passes --disallowedTools Skill; every arm passes --strict-mcp-config with an
empty MCP config, so neither the think-english skill nor its MCP server can act. Hooks are
user-scope and still run. One JSONL record per turn is appended to <out>/turns.jsonl.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE = (
    "Think in English: understand, plan, reason and draft in English. Reply in the language of the "
    "user's LATEST message, judged by their own sentence, not by quoted text, code or pasted logs. "
    "Keep code, commands, paths, identifiers, error text and developer tech terms in English."
)
ARMS = {
    "OFF": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": None, "skill": False},
    "E": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": RULE, "skill": False},
    "G": {"env": {"BANTAMKIT_REPLY_NATIVE": "off"}, "claude_md": None, "skill": True},
    "A2": {"env": {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": ""}, "claude_md": None, "skill": False},
    "A3": {"env": {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th"}, "claude_md": None, "skill": False},
}


def _project(arm: dict) -> Path:
    d = Path(tempfile.mkdtemp(prefix="rn-eval-"))
    (d / ".claude").mkdir()
    (d / ".claude" / "settings.json").write_text(json.dumps({"env": arm["env"]}), encoding="utf-8")
    (d / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    if arm["claude_md"]:
        (d / "CLAUDE.md").write_text(arm["claude_md"] + "\n", encoding="utf-8")
    return d


def _turn(proj: Path, arm: dict, prompt: str, session: str, first: bool, model: str) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--strict-mcp-config", "--mcp-config", str(proj / "mcp.json")]
    cmd += ["--session-id", session] if first else ["--resume", session]
    if not arm["skill"]:
        cmd += ["--disallowedTools", "Skill"]
    done = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, encoding="utf-8", timeout=900, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"claude -p failed ({done.returncode}): {done.stderr[:400]}")
    return json.loads(done.stdout)


def _thinking(session: str) -> list[str]:
    """Thinking blocks of the session's assistant turns, in order, one string per turn."""
    hits = list(Path.home().glob(f".claude/projects/*/{session}.jsonl"))
    if not hits:
        return []
    per_turn: list[str] = []
    current: list[str] | None = None  # None until the first prompt: one entry per prompt, always
    for line in hits[0].read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "user" and isinstance((o.get("message") or {}).get("content"), str):
            if current is not None:
                per_turn.append("\n".join(current))
            current = []
        if o.get("type") == "assistant":
            for block in (o.get("message") or {}).get("content") or []:
                if current is not None and isinstance(block, dict) and block.get("type") == "thinking":
                    current.append(block.get("thinking", ""))
    if current is not None:
        per_turn.append("\n".join(current))
    return per_turn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--seqs", default="", help="comma-separated sequence ids; empty means all")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seqs = json.loads((HERE / "sequences.json").read_text(encoding="utf-8"))
    sink = (out / "turns.jsonl").open("a", encoding="utf-8")
    for rep in range(a.reps):
        for seq_id, prompts in seqs.items():
            if a.seqs and seq_id not in a.seqs.split(","):
                continue
            for arm_id in a.arms.split(","):
                arm = ARMS[arm_id]
                proj = _project(arm)
                session = str(uuid.uuid4())
                results = [_turn(proj, arm, p, session, i == 0, a.model) for i, p in enumerate(prompts)]
                thinking = _thinking(session)
                for i, (p, r) in enumerate(zip(prompts, results, strict=True)):
                    usage = r.get("usage") or {}
                    sink.write(json.dumps({
                        "arm": arm_id, "seq": seq_id, "rep": rep, "turn": i, "prompt": p,
                        "reply": r.get("result", ""), "thinking": thinking[i] if i < len(thinking) else None,
                        "output_tokens": usage.get("output_tokens"), "input_tokens": usage.get("input_tokens"),
                        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                        "model": a.model, "session_id": session,
                    }, ensure_ascii=False) + "\n")
                    sink.flush()


if __name__ == "__main__":
    main()
