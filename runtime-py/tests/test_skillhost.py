"""skillhost (#205 Task 2): the Claude Code and Null adapters and the transcript scan.

`runtime-ts/test/skillhost.test.mjs` mirrors these; `tools/conformance/suites/skill-host.mjs`
compares the two runtimes. Every path is under `tmp_path`: nothing here reads a real home.
"""

import json
import os

from bantamkit import skillhost
from bantamkit.storage.retention import parse_now

NOW = "2026-10-16T00:00:00.000Z"
NOW_MS = parse_now(NOW)
DAY = 86_400_000


def _use(id_, skill, ts="2026-10-15T00:00:00.000Z"):
    block = {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}
    if id_ is not None:
        block["id"] = id_
    return json.dumps({"timestamp": ts, "message": {"content": [block]}})


def _typed(name, uuid=None, ts="2026-10-15T00:00:00.000Z", **extra):
    rec = {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": (
                f"<command-name>/{name}</command-name>\n"
                f"<command-message>{name}</command-message>\n"
                "<command-args></command-args>"
            ),
        },
        **extra,
    }
    if uuid is not None:
        rec["uuid"] = uuid
    return json.dumps(rec)


def _write(p, lines, age_days=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\n".join(x if isinstance(x, bytes) else x.encode() for x in lines) + b"\n")
    t = (NOW_MS - age_days * DAY) / 1000
    os.utime(p, (t, t))


def test_dedupe_by_id_subagents_counted_old_lines_dropped(tmp_path):
    projects = tmp_path / "projects"
    _write(
        projects / "p1" / "s1.jsonl",
        [
            _use("t1", "beta:b1"),
            _use(None, "solo"),
            _use("t3", "alpha:a1", ts="2026-09-01T00:00:00.000Z"),
            b'{"bad "Skill" "tool_use"',
            b'\xff "Skill" "tool_use"',
            '{"text": "Skill without the block type"}',
        ],
    )
    _write(projects / "p1" / "s2.jsonl", [_use("t1", "beta:b1"), _use(None, "solo")])
    _write(projects / "p1" / "s1" / "subagents" / "agent-a.jsonl", [_use("t4", "beta:b1")])
    _write(projects / "p2" / "old.jsonl", [_use("t9", "alpha:a2")], age_days=40)
    got = skillhost.count_skill_usage(projects, NOW_MS)
    assert got.counts == {"beta:b1": 2, "solo": 2}
    assert (got.transcripts, got.unreadable, got.skipped_lines, got.span_days) == (3, 0, 2, 30)


def test_span_is_the_oldest_seen_in_days(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "p" / "s.jsonl", [_use("t1", "x", ts="2026-10-04T00:00:00.000Z")], age_days=0)
    assert skillhost.count_skill_usage(projects, NOW_MS).span_days == 12


def test_no_transcripts_is_span_zero(tmp_path):
    got = skillhost.count_skill_usage(tmp_path / "missing", NOW_MS)
    assert (got.counts, got.span_days, got.transcripts) == ({}, 0, 0)


def test_a_bom_line_is_skipped_not_parsed(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "p" / "s.jsonl", [b"\xef\xbb\xbf" + _use("t1", "solo").encode()])
    got = skillhost.count_skill_usage(projects, NOW_MS)
    assert (got.counts, got.skipped_lines) == ({}, 1)


# ------------------------------------------------------------- Amendment A2: typed commands


def test_both_shapes_count_one_call_each(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "p" / "s.jsonl", [_use("t1", "solo"), _typed("alpha:a1", "u1")])
    got = skillhost.count_skill_usage(projects, NOW_MS, known={"solo", "alpha:a1"})
    assert got.counts == {"alpha:a1": 1, "solo": 1}
    assert got.summary()["calls"] == 2


def test_a_command_is_counted_only_when_it_names_a_known_skill(tmp_path):
    projects = tmp_path / "projects"
    tool_result = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-10-15T00:00:00.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "<command-name>/solo</command-name>"}
                ],
            },
        }
    )
    tool_input = json.dumps(
        {
            "type": "assistant",
            "timestamp": "2026-10-15T00:00:00.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "id": "b1",
                        "input": {"command": "<command-name>/solo</command-name>"},
                    }
                ],
            },
        }
    )
    _write(
        projects / "p" / "s.jsonl",
        [
            _typed("clear", "u0"),  # a built-in: never a skill
            _typed("solo", "u1"),
            _typed("solo", "u1"),  # a resumed copy: the same uuid, one call
            _typed("solo"),  # no uuid: counted
            _typed("solo", "u2", isMeta=True),  # the expansion record is not a second call
            _typed("solo", "u3", ts="2026-09-01T00:00:00.000Z"),  # before the cutoff
            tool_result,
            tool_input,
        ],
    )
    got = skillhost.count_skill_usage(projects, NOW_MS, known={"solo"})
    assert got.counts == {"solo": 2}
    assert skillhost.count_skill_usage(projects, NOW_MS).counts == {}


def test_known_skills_spells_ids_as_the_audit_does(tmp_path):
    cache = tmp_path / "cache"
    (cache / "mk" / "alpha" / "1.0.0" / "skills" / "a1").mkdir(parents=True)
    (cache / "mk" / "alpha" / "1.0.0" / "skills" / "a1" / "SKILL.md").write_text(
        "x", encoding="utf-8"
    )
    (cache / "mk" / "alpha" / "1.0.0" / "skills" / "notaskill").mkdir()
    local = tmp_path / "skills"
    (local / "solo").mkdir(parents=True)
    (local / "solo" / "SKILL.md").write_text("x", encoding="utf-8")
    assert skillhost.known_skills([cache, local]) == {"alpha:a1", "solo"}


# --------------------------------------------------------------------------- the adapters


def _claude_home(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "proj"
    (home / ".claude" / "plugins" / "cache" / "mk" / "alpha" / "1.0.0" / "skills").mkdir(
        parents=True
    )
    (home / ".claude" / "skills").mkdir(parents=True)
    (cwd / ".claude" / "skills").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"alpha@mk": True, "beta@mk": True, "gamma@mk": False}}),
        encoding="utf-8",
    )
    (cwd / ".claude" / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"beta@mk": False}}), encoding="utf-8"
    )
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "alpha@mk": [
                        {
                            "scope": "user",
                            "installPath": str(home / ".claude/plugins/cache/mk/alpha/1.0.0"),
                        },
                        {
                            "scope": "project",
                            "projectPath": str(cwd),
                            "installPath": "/x/mk/alpha/2.0.0",
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return home, cwd


def test_claude_code_gather(tmp_path):
    home, cwd = _claude_home(tmp_path)
    adapter = skillhost.select_adapter(home)
    assert adapter.host == "claude-code"
    g = adapter.gather(home, str(cwd), NOW_MS)
    assert [label for label, _ in g.roots] == ["plugins", "project", "user"]
    assert g.enabled == ("alpha@mk",)
    assert g.sources == {"alpha@mk": str(home / ".claude" / "settings.json")}
    assert g.versions == {"alpha@mk": "2.0.0"}
    assert g.usage is not None and g.usage.span_days == 0


def test_gather_counts_a_typed_skill_from_its_roots(tmp_path):
    home, cwd = _claude_home(tmp_path)
    (cwd / ".claude" / "skills" / "proj").mkdir()
    (cwd / ".claude" / "skills" / "proj" / "SKILL.md").write_text("x", encoding="utf-8")
    _write(
        home / ".claude" / "projects" / "p" / "s.jsonl",
        [_typed("proj", "u1"), _typed("compact", "u2")],
    )
    g = skillhost.select_adapter(home).gather(home, str(cwd), NOW_MS)
    assert g.usage is not None and g.usage.counts == {"proj": 1}


def test_project_root_dropped_when_it_is_the_user_root(tmp_path):
    home, _ = _claude_home(tmp_path)
    g = skillhost.select_adapter(home).gather(home, str(home), NOW_MS)
    assert [label for label, _ in g.roots] == ["plugins", "user"]


def test_null_adapter(tmp_path):
    adapter = skillhost.select_adapter(tmp_path)
    assert adapter.host == "none"
    g = adapter.gather(tmp_path, None, NOW_MS)
    assert (g.roots, g.enabled, g.versions, g.sources, g.usage) == ((), (), None, {}, None)
    assert g.as_dict()["usage"] is None


def test_gather_writes_nothing(tmp_path):
    home, cwd = _claude_home(tmp_path)
    before = sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    skillhost.select_adapter(home).gather(home, str(cwd), NOW_MS)
    assert sorted((p, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before
