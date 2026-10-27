"""skillreport (#205 Task 3): the record, the disable proposals and the rendered report.

`runtime-ts/test/skillreport.test.mjs` mirrors these; `tools/conformance/suites/skill-host.mjs`
compares the two runtimes. Every path is under `tmp_path`: nothing here reads a real home.
"""

import hashlib
import json

from bantamkit import skillaudit, skillreport
from bantamkit.skillhost import Gathered, UsageScan
from bantamkit.storage import retention

NOW = "2026-10-16T00:00:00.000Z"
SETTINGS = '{\n  "enabledPlugins": {\n    "alpha@mk": true,\n    "beta@mk": true\n  }\n}\n'


def _skill(base, rel, description):
    p = base / rel / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {p.parent.name}\ndescription: {description}\n---\n", encoding="utf-8")


def _bed(tmp_path, counts, span, settings_text=SETTINGS):
    cache = tmp_path / "cache"
    _skill(cache, "mk/alpha/1.0.0/skills/a1", "a one")
    _skill(cache, "mk/alpha/1.0.0/skills/a2", "a two")
    _skill(cache, "mk/beta/1.0.0/skills/b1", "b one")
    settings = tmp_path / "settings.json"
    settings.write_bytes(settings_text.encode("utf-8"))
    usage = None if counts is None else UsageScan(counts, span, 3, 0, 0)
    src = {"alpha@mk": str(settings), "beta@mk": str(settings)}
    roots = (("plugins", str(cache)),)
    g = Gathered("claude-code", roots, ("alpha@mk", "beta@mk"), None, src, usage)
    return g, settings


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_a_plugin_with_every_skill_at_zero_over_30_days_is_proposed(tmp_path):
    g, settings = _bed(tmp_path, {"beta:b1": 4}, 30)
    rec = skillreport.build_record(g, NOW)
    assert rec["proposals"] == [
        {
            "plugin": "alpha@mk",
            "file": str(settings),
            "line": 3,
            "before": '    "alpha@mk": true,',
            "after": '    "alpha@mk": false,',
            "skills": ["alpha:a1", "alpha:a2"],
        }
    ]
    assert rec["version"] == skillreport.STATE_VERSION and rec["surfaced"] == []


def test_no_proposal_without_usage(tmp_path):
    g, _ = _bed(tmp_path, None, 0)
    assert skillreport.build_record(g, NOW)["proposals"] == []


def test_propose_refuses_a_missing_measurement_even_at_30_days(tmp_path):
    """D1 on its own: `build_record` passes span 0 when usage is None, so only `propose` itself
    can show that a missing measurement is not read as "nothing was called"."""
    g, _ = _bed(tmp_path, None, 0)
    found = skillaudit.scan_roots(list(g.roots), list(g.enabled), None)
    assert skillreport.propose(found, None, 30, g.sources) == []
    assert [p["plugin"] for p in skillreport.propose(found, {}, 30, g.sources)] == [
        "alpha@mk",
        "beta@mk",
    ]


def test_no_proposal_under_30_days(tmp_path):
    g, _ = _bed(tmp_path, {"beta:b1": 4}, 29)
    assert skillreport.build_record(g, NOW)["proposals"] == []


def test_one_called_skill_keeps_its_plugin(tmp_path):
    g, _ = _bed(tmp_path, {"alpha:a2": 1, "beta:b1": 4}, 30)
    assert skillreport.build_record(g, NOW)["proposals"] == []


def test_personal_skills_never_get_a_diff(tmp_path):
    user = tmp_path / "user"
    _skill(user, "solo", "s")
    settings = tmp_path / "settings.json"
    # Even a settings file that switches on the id a non-plugin skill would group under.
    settings.write_text('{\n  "enabledPlugins": {\n    "@": true\n  }\n}\n', encoding="utf-8")
    usage = UsageScan({}, 30, 1, 0, 0)
    g = Gathered("claude-code", (("user", str(user)),), ("@",), None, {"@": str(settings)}, usage)
    rec = skillreport.build_record(g, NOW)
    assert rec["proposals"] == []
    assert rec["findings"][0]["kind"] == "never-invoked"
    assert rec["findings"][0]["skills"] == ["solo"]


def test_render_shows_the_diff_and_never_claims_it_was_applied(tmp_path):
    g, settings = _bed(tmp_path, {"beta:b1": 4}, 30)
    before = _sha(settings)
    text = skillreport.render_report(skillreport.build_record(g, NOW))
    assert (
        f"--- {settings}\n+++ {settings}\n@@ -3 +3 @@\n"
        '-    "alpha@mk": true,\n+    "alpha@mk": false,'
    ) in text
    assert "NOT applied; bantamkit never edits settings.json" in text
    assert _sha(settings) == before


def test_minified_settings_is_not_located_and_says_so(tmp_path):
    g, settings = _bed(
        tmp_path, {"beta:b1": 4}, 30, '{"enabledPlugins":{"alpha@mk":true,"beta@mk":true}}'
    )
    before = _sha(settings)
    rec = skillreport.build_record(g, NOW)
    assert [(p["line"], p["before"], p["after"]) for p in rec["proposals"]] == [(None, None, None)]
    text = skillreport.render_report(rec)
    assert (
        f'set enabledPlugins["alpha@mk"] to false in {settings} (the line could not be located)'
        in text
    )
    assert "--- " not in text
    assert _sha(settings) == before


def test_only_a_line_inside_enabled_plugins_is_located(tmp_path):
    text = (
        '{\r\n  "other": {\r\n    "alpha@mk": true\r\n  },\r\n'
        '  "enabledPlugins": {\r\n    "alpha@mk" : true ,\r\n    "beta@mk": true\r\n  }\r\n}\r\n'
    )
    g, _ = _bed(tmp_path, {"beta:b1": 4}, 30, text)
    (p,) = skillreport.build_record(g, NOW)["proposals"]
    assert (p["line"], p["before"], p["after"]) == (
        6,
        '    "alpha@mk" : true ,',
        '    "alpha@mk" : false ,',
    )


def test_young_render_ends_with_the_span_sentence(tmp_path):
    g, _ = _bed(tmp_path, {"beta:b1": 4}, 12)
    text = skillreport.render_report(skillreport.build_record(g, NOW))
    assert text.endswith("proposed change: none — the transcripts span 12 days; a change needs 30")


def test_null_host_report(tmp_path):
    rec = skillreport.build_record(Gathered("none"), NOW)
    assert rec == {
        "version": 1,
        "ts": NOW,
        "host": "none",
        "error": "no skill directory was found for this host",
        "surfaced": [],
    }
    assert skillreport.render_report(rec).startswith(
        "skill audit — could not run: no skill directory was found for this host."
    )


def test_run_live_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(skillreport, "select_adapter", boom)
    rec = skillreport.run_live(tmp_path, None, NOW)
    assert rec["error"] == "the gather failed" and rec["host"] == "none"


def test_run_live_over_a_home_with_no_claude_is_the_null_report(tmp_path):
    rec = skillreport.run_live(tmp_path, None, NOW)
    assert rec["host"] == "none" and rec["error"] == skillreport.NO_ROOTS


# ------------------------------------------------------------- Task 4: the daily run


def _home_with_claude(tmp_path):
    home = tmp_path / "home"
    (home / ".bantamkit").mkdir(parents=True)
    p = home / ".claude" / "skills" / "solo" / "SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text('---\ndescription: Use "x" now\n---\n', encoding="utf-8")
    return home


def test_daily_writes_the_record_and_keeps_surfaced_that_still_apply(tmp_path):
    home = _home_with_claude(tmp_path)
    skillreport.daily(home, None, NOW)
    raw = skillreport.state_path(home).read_bytes()
    assert raw.endswith(b"}\n") and b"\r" not in raw
    rec = skillreport.read_state(home)
    assert rec["host"] == "claude-code" and rec["surfaced"] == [] and rec["ts"] == NOW
    key = skillreport.surface_key(rec["findings"][0])
    assert key == "never-invoked\tsolo\t0 calls"
    rec["surfaced"] = ["gone\t\t", key]
    skillreport.state_path(home).write_text(json.dumps(rec), encoding="utf-8")
    skillreport.daily(home, None, "2026-10-17T00:00:00.000Z")
    assert skillreport.read_state(home)["surfaced"] == [key]
    assert not list((home / ".bantamkit").glob("*.tmp"))
    assert not list((home / ".bantamkit").glob("*.lock"))


def test_corrupt_or_wrong_version_is_recomputed(tmp_path, monkeypatch):
    monkeypatch.delenv("BANTAMKIT_SKILL_AUDIT", raising=False)
    home = _home_with_claude(tmp_path)
    for bad in (
        '{"version": 9}',
        "not json",
        '﻿{"version": 1}',
        '{"version": true, "ts": "t", "host": "h", "surfaced": [], "error": "e"}',
        '{"version": 1, "ts": "t", "host": "h", "surfaced": [1], "error": "e"}',
        '{"version": 1, "ts": "t", "host": "h", "surfaced": [], "skills": 1.5}',
    ):
        skillreport.state_path(home).write_text(bad, encoding="utf-8")
        assert skillreport.read_state(home) is None, bad
        assert skillreport.status_line(home) == (
            "skill audit: the last record is unreadable; the next run recomputes it"
        )
    skillreport.daily(home, None, NOW)
    assert skillreport.read_state(home)["version"] == 1


def test_a_whole_float_reads_as_the_integer_json_parse_makes_it(tmp_path):
    home = _home_with_claude(tmp_path)
    skillreport.state_path(home).write_text(
        '{"version": 1.0, "ts": "t", "host": "h", "surfaced": [], "error": "e"}', encoding="utf-8"
    )
    assert skillreport.read_state(home)["version"] == 1


def test_status_lines(tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "off")
    monkeypatch.delenv("BANTAMKIT_RETENTION", raising=False)
    assert skillreport.status_line(bare) == "skill audit: off; never ran; usage adapter none"
    # Amendment A3: the prefix reads the AUDIT switch, never retention's.
    monkeypatch.delenv("BANTAMKIT_SKILL_AUDIT")
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    assert skillreport.status_line(bare) == "skill audit: never ran; usage adapter none"
    home = _home_with_claude(tmp_path)
    assert skillreport.status_line(home) == "skill audit: never ran; usage adapter claude-code"
    skillreport.daily(home, None, NOW)
    assert skillreport.status_line(home) == (
        "skill audit: last ran 2026-10-16T00:00:00.000Z on claude-code; 1 skill, 11 catalogue "
        "bytes; findings 0 high, 0 medium, 1 low; usage over 0 days (a proposed change needs 30)"
    )
    skillreport.state_path(home).write_text(
        json.dumps({"version": 1, "ts": NOW, "host": "none", "error": "boom", "surfaced": []}),
        encoding="utf-8",
    )
    assert skillreport.status_line(home) == (
        "skill audit: last ran 2026-10-16T00:00:00.000Z; no report — boom"
    )


def test_the_retention_child_runs_the_audit_under_the_claimed_day(tmp_path, monkeypatch):
    monkeypatch.delenv("BANTAMKIT_SKILL_AUDIT", raising=False)
    monkeypatch.setenv("BANTAMKIT_RETENTION", "off")
    home = _home_with_claude(tmp_path)
    assert retention.child_main([str(tmp_path), str(home)], now=NOW) == 0
    assert skillreport.read_state(home)["ts"] == NOW
    assert json.loads(retention.state_path(home).read_text(encoding="utf-8")) == {"ran_at": NOW}
    # The claimed day holds: a second child the same day neither sweeps nor audits again.
    skillreport.state_path(home).unlink()
    assert retention.child_main([str(tmp_path), str(home)], now="2026-10-16T12:00:00.000Z") == 0
    assert not skillreport.state_path(home).exists()


def test_skill_audit_off_stops_the_daily_run(tmp_path, monkeypatch):
    monkeypatch.setenv("BANTAMKIT_SKILL_AUDIT", "off")
    monkeypatch.delenv("BANTAMKIT_RETENTION", raising=False)
    home = _home_with_claude(tmp_path)
    retention.child_main([str(tmp_path), str(home)], now=NOW)
    assert not skillreport.state_path(home).exists()
    assert "report" in json.loads(retention.state_path(home).read_text(encoding="utf-8"))


def test_daily_never_raises(tmp_path):
    home = tmp_path / "home"  # no `.bantamkit`: the write fails, the run is silent
    (home / ".claude" / "skills").mkdir(parents=True)
    skillreport.daily(home, None, NOW)
    assert not (home / ".bantamkit").exists()


# --- Task 5: the SessionStart line -------------------------------------------------------


def _rec(findings, span=30, surfaced=()):
    return {"version": 1, "ts": "t", "host": "claude-code", "roots": [], "skills": 1,
            "catalogue_bytes": 1, "findings": findings, "omissions": [], "proposals": [],
            "usage": {"calls": 0, "counts": {}, "span_days": span, "transcripts": 1,
                      "unreadable": 0, "skipped_lines": 0},
            "surfaced": list(surfaced)}


HIGH = {"kind": "shared-trigger-phrase", "severity": "high", "skills": ["alpha:a1", "beta:b2"],
        "detail": "deploy the thing"}


def _never(s):
    return {"kind": "never-invoked", "severity": "low", "skills": [s], "detail": "0 calls"}


FULL = [HIGH, _never("alpha:a1"), _never("alpha:a2"), _never("beta:b2"), _never("proj")]
LINE = ("[bantamkit] skill audit: 5 new — shared-trigger-phrase: alpha:a1, beta:b2; "
        "alpha:a1 30 days without a call; alpha:a2 30 days without a call; +2 more — "
        "/mcp__bantamkit__skill_audit has the report.")


def _put(home, rec):
    skillreport.state_path(home).parent.mkdir(parents=True, exist_ok=True)
    skillreport.state_path(home).write_text(json.dumps(rec), encoding="utf-8")


def test_the_line_is_capped_and_then_silent(tmp_path):
    _put(tmp_path, _rec(FULL))
    line = skillreport.session_line(tmp_path)
    assert line == LINE and len(line.encode()) == 199 <= skillreport.LINE_MAX_BYTES
    assert skillreport.session_line(tmp_path) is None
    stored = skillreport.read_state(tmp_path)
    assert stored["surfaced"] == sorted(skillreport.surface_key(f) for f in FULL)


def test_nothing_new_is_none_and_writes_nothing(tmp_path):
    keys = [skillreport.surface_key(f) for f in FULL]
    _put(tmp_path, _rec(FULL, surfaced=keys))
    before = skillreport.state_path(tmp_path).read_bytes()
    assert skillreport.session_line(tmp_path) is None
    assert skillreport.state_path(tmp_path).read_bytes() == before


def test_never_invoked_waits_for_30_days(tmp_path):
    _put(tmp_path, _rec([_never("x")], span=29))
    assert skillreport.session_line(tmp_path) is None
    _put(tmp_path, _rec([_never("x")], span=30))
    assert skillreport.session_line(tmp_path) == (
        "[bantamkit] skill audit: 1 new — x 30 days without a call — "
        "/mcp__bantamkit__skill_audit has the report."
    )


def test_one_long_item_is_clipped_on_a_code_point(tmp_path):
    long = {**HIGH, "skills": ["ก" * 80]}
    _put(tmp_path, _rec([long]))
    line = skillreport.session_line(tmp_path)
    raw = line.encode()
    assert len(raw) <= 200 and "…" in line
    raw.decode("utf-8")  # no split code point


def test_a_finding_shown_once_is_never_shown_again_but_a_new_one_is(tmp_path):
    _put(tmp_path, _rec([HIGH]))
    assert skillreport.session_line(tmp_path) is not None
    stored = skillreport.read_state(tmp_path)
    stored["findings"].append(_never("late"))
    _put(tmp_path, stored)
    assert skillreport.session_line(tmp_path) == (
        "[bantamkit] skill audit: 1 new — late 30 days without a call — "
        "/mcp__bantamkit__skill_audit has the report."
    )
    assert skillreport.session_line(tmp_path) is None


def test_no_record_an_error_record_or_a_corrupt_file_is_silent(tmp_path):
    assert skillreport.session_line(tmp_path) is None
    assert not skillreport.state_path(tmp_path).exists()
    _put(tmp_path, {"version": 1, "ts": "t", "host": "none", "error": "x", "surfaced": []})
    assert skillreport.session_line(tmp_path) is None
    skillreport.state_path(tmp_path).write_bytes(b"{not json")
    assert skillreport.session_line(tmp_path) is None
    assert skillreport.state_path(tmp_path).read_bytes() == b"{not json"


def test_a_malformed_finding_is_skipped_not_fatal(tmp_path):
    bad = {"kind": "x", "severity": "high", "skills": "alpha", "detail": "d"}
    _put(tmp_path, _rec([bad, HIGH]))
    assert skillreport.session_line(tmp_path) == (
        "[bantamkit] skill audit: 1 new — shared-trigger-phrase: alpha:a1, beta:b2 — "
        "/mcp__bantamkit__skill_audit has the report."
    )


def test_render_line_items_never_overflow():
    for n in range(0, 40):
        items = [f"item-{i} " + "x" * (i * 7 % 90) for i in range(n)]
        assert len(skillreport.render_line(items).encode()) <= skillreport.LINE_MAX_BYTES
