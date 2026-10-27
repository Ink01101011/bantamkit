"""skillreport (#205 Task 3): the record, the disable proposals and the rendered report.

`runtime-ts/test/skillreport.test.mjs` mirrors these; `tools/conformance/suites/skill-host.mjs`
compares the two runtimes. Every path is under `tmp_path`: nothing here reads a real home.
"""

import hashlib

from bantamkit import skillaudit, skillreport
from bantamkit.skillhost import Gathered, UsageScan

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
