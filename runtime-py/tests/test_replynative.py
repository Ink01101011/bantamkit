from __future__ import annotations

import json

import pytest

from bantamkit import replynative as rn
from bantamkit.assets import AssetNotFound, load_lang


@pytest.mark.parametrize(
    ("env", "want"),
    [
        ({}, ("off", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": "off"}, ("off", None, None, None)),
        ({"BANTAMKIT_REPLY_NATIVE": " ON "}, ("latest", None, None, None)),
        (
            {"BANTAMKIT_REPLY_NATIVE": "1", "BANTAMKIT_REPLY_LANG": " TH "},
            ("fixed", "th", None, None),
        ),
        (
            {"BANTAMKIT_REPLY_NATIVE": "yes", "BANTAMKIT_REPLY_LANG": "ko"},
            ("fixed", "ko", None, None),
        ),
        (
            {"BANTAMKIT_REPLY_NATIVE": "true", "BANTAMKIT_REPLY_LANG": ""},
            ("latest", None, None, None),
        ),
        (
            {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th-TH"},
            ("latest", None, "th-TH", "invalid-lang"),
        ),
        (
            {"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "thai"},
            ("latest", None, "thai", "invalid-lang"),
        ),
        (
            {"BANTAMKIT_REPLY_NATIVE": "garbage", "BANTAMKIT_REPLY_LANG": "th"},
            ("off", None, None, None),
        ),
    ],
)
def test_mode(env, want):
    m = rn.mode(env)
    assert (m.kind, m.lang, m.raw_lang, m.reason) == want


def test_mode_caps_raw_lang_at_32_code_points():
    raw = "😀" * 40
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": raw})
    assert m.raw_lang == "😀" * 32


@pytest.mark.parametrize(
    ("prompt", "want"),
    [
        ('What is this "สวัสดี"?', None),
        ("What is this สวัสดี?", "th"),
        ("merge main เข้า feat/207", "th"),
        ("ทำต่อ", "th"),
        ("fix the login bug", None),
        ("check C:\\Users\\สมชาย\\app.log", None),
        ("check /Users/สมชาย/app.log", None),
        ("see https://example.com/สวัสดี now", None),
        ("run `echo สวัสดี` please", None),
        ("```\nสวัสดี\n```\nwhy does this fail", None),
        ('<pasted_content id="a">ข้อความ</pasted_content> explain this', None),
        ('รัน release ไม่ผ่าน\n<pasted_content id="b">\nError: boom\n</pasted_content>', "th"),
        ('"ship เลย"', "th"),
        ("これはなぜ壊れていますか", "ja"),
        ("漢字だけ", "ja"),
        ("漢字", None),
        ("「こんにちは」 means what", None),
        ("", None),
    ],
)
def test_classify(prompt, want):
    assert rn.classify(prompt) == want


def test_frame_falls_back_to_whole_prompt_when_nothing_is_left():
    assert rn.frame('"ship เลย"') == '"ship เลย"'


def test_load_lang_strips_trailing_newline_and_refuses_missing():
    text = load_lang("th")
    assert text.startswith("[reply-native th]") and not text.endswith("\n")
    with pytest.raises(AssetNotFound, match="lang asset not found"):
        load_lang("zz")


def test_plan_latest_first_thai_prompt_injects_core_and_th():
    p = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"}), "th", ())
    assert p.parts == ("core", "th")
    assert p.text == load_lang("core-latest") + "\n" + load_lang("th")
    assert len(p.text.encode("utf-8")) == 885
    assert p.reason is None


def test_plan_latest_dedupes_by_part():
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"})
    assert rn.plan(m, "th", {"core", "th"}).parts == ()
    p = rn.plan(m, "ja", {"core", "th"})
    assert p.parts == ("ja",) and p.text == load_lang("ja")


def test_plan_latest_without_a_language_is_empty():
    p = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"}), None, ())
    assert (p.parts, p.text, p.reason) == ((), "", None)


def test_plan_fixed():
    th = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "th"}), "th", ())
    assert th.parts == ("core", "th")
    assert "ISO 639-1 code is th," in th.text and "{lang}" not in th.text
    assert len(th.text.encode("utf-8")) == 898
    ko = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "ko"}), "ko", ())
    assert ko.parts == ("core",) and len(ko.text.encode("utf-8")) == 508
    en = rn.plan(rn.mode({"BANTAMKIT_REPLY_NATIVE": "on", "BANTAMKIT_REPLY_LANG": "en"}), "en", ())
    assert (en.parts, en.text, en.reason) == ((), "", "english")


def test_plan_over_budget_and_missing_asset(tmp_path, monkeypatch):
    pack = tmp_path / "langs"
    pack.mkdir()
    (pack / "core-latest.md").write_text("x" * 601 + "\n", encoding="utf-8")
    (pack / "th.md").write_text("y\n", encoding="utf-8")
    monkeypatch.setenv("BANTAMKIT_ASSETS", str(tmp_path))
    m = rn.mode({"BANTAMKIT_REPLY_NATIVE": "on"})
    assert rn.plan(m, "th", ()).reason == "over-budget"
    (pack / "core-latest.md").unlink()
    assert rn.plan(m, "th", ()) == rn.Plan((), "", "asset-missing")


def test_status_line(tmp_path):
    assert rn.status_line(tmp_path) == "reply-native: off"
    state = tmp_path / ".bantamkit" / "hooks" / rn.STATE_FILE
    state.parent.mkdir(parents=True)
    state.write_text("{not json", encoding="utf-8")
    assert rn.status_line(tmp_path) == "reply-native: the last record is unreadable"
    state.write_text(
        json.dumps(
            {
                "ts": "2026-11-07T00:00:00.000Z",
                "event": "UserPromptSubmit",
                "mode": "latest",
                "lang": "th",
                "parts": ["core", "th"],
                "bytes": 885,
            }
        ),
        encoding="utf-8",
    )
    assert rn.status_line(tmp_path) == (
        "reply-native: latest; last UserPromptSubmit at 2026-11-07T00:00:00.000Z: "
        "injected core+th (885 bytes)"
    )
    state.write_text(
        json.dumps(
            {
                "ts": "T",
                "event": "SessionStart",
                "mode": "fixed",
                "lang": "en",
                "parts": [],
                "bytes": 0,
                "reason": "english",
            }
        ),
        encoding="utf-8",
    )
    assert (
        rn.status_line(tmp_path)
        == "reply-native: fixed en; last SessionStart at T: nothing injected (english)"
    )
    state.write_text(
        json.dumps(
            {
                "ts": "T",
                "event": "UserPromptSubmit",
                "mode": "latest",
                "lang": "th",
                "parts": [],
                "bytes": 0,
                "reason": "invalid-lang",
                "rawLang": "th-TH",
            }
        ),
        encoding="utf-8",
    )
    assert rn.status_line(tmp_path) == (
        "reply-native: latest; last UserPromptSubmit at T: nothing injected (invalid-lang); "
        "BANTAMKIT_REPLY_LANG=th-TH invalid, fell back to latest"
    )
