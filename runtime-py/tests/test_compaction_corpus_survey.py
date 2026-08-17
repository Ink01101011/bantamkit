"""The corpus survey's INSTRUMENT, pinned on a synthetic fixture directory.

RB-P28 stays open and nothing here is evidence. The evidence is
`docs/eval-data/2026-08-17-compaction-corpus-survey.py` run against
`~/.claude/projects/`, outside pytest, in a fresh interpreter.

RB-P14 Gate 2 is why every fixture below is synthetic. A node asserting "the corpus has
207 transcripts" or "its median is 26 model calls" is a fact about the WORLD: it goes red
the moment the user opens another session, and the cheapest way to make it green again is
to edit the committed evidence. So no node here reads `~/.claude/projects/`, names a
transcript, or asserts any committed number. Each one hands the program a directory whose
contents this file wrote, and asserts the statistics it computes about that directory are
the right ones.

The three mutations these nodes exist to catch are the three defects that were actually
FOUND in this program while it was being written, not three invented ones:

  1. counting assistant LINES as model calls. A reply carrying a thinking block and two
     `tool_use` blocks is three lines with one `message.id` and one `requestId`;
  2. reading `usage.output_tokens` off the FIRST line of a message. It is a streaming
     value — the lines of one real reply carry 3, 3, 3, 2478 — so the first line
     under-counts the message by orders of magnitude and the max is the total;
  3. letting a non-numeric string into a committed row. The first draft committed
     `git_branches_recorded` and the program's own fence turned the run red on it,
     because a branch name carries a `/`.
"""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAM = REPO_ROOT / "docs" / "eval-data" / "2026-08-17-compaction-corpus-survey.py"


@pytest.fixture(scope="module")
def survey():
    """The program, imported by path — committed evidence that happens to be executable.

    By path and not by package for the reason `test_ladder_statistics.py` gives: moving
    its arithmetic into `bantamkit` would make the unit that measures also the unit that
    ships the ruler.
    """
    assert PROGRAM.exists(), f"{PROGRAM.name} is committed and is no longer there"
    spec = importlib.util.spec_from_file_location("compaction_corpus_survey", PROGRAM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BEFORE = "2026-08-01T00:00:00.000Z"  # comfortably under the program's declared cutoff
AFTER = "2026-09-01T00:00:00.000Z"  # comfortably over it
BK = "/Users/kktest/Documents/Claude/Projects/bantamkit"
ELSEWHERE = "/Users/kktest/Documents/Claude/Projects/somewhere-else"


def _assistant(message_id: str, request_id: str, block: dict, usage: dict, **extra) -> dict:
    return {
        "type": "assistant",
        "cwd": BK,
        "timestamp": extra.pop("timestamp", BEFORE),
        "requestId": request_id,
        "version": "9.9.9",
        "message": {
            "id": message_id,
            "role": "assistant",
            "model": extra.pop("model", "test-model"),
            "content": [block],
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
                **usage,
            },
        },
        **extra,
    }


def _user(text: str, *, timestamp: str = BEFORE, cwd: str = BK) -> dict:
    return {
        "type": "user",
        "cwd": cwd,
        "timestamp": timestamp,
        "version": "9.9.9",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _write(directory: Path, name: str, events: list[dict]) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return path


def _rows(survey, root: Path) -> tuple[list[dict], dict]:
    with redirect_stdout(io.StringIO()):
        return survey.build_rows(root)


def _one_reply_three_blocks(prompt: int) -> list[dict]:
    """One model call, three lines, streaming `output_tokens` — the shape that bit twice."""
    return [
        _assistant("msg_1", "req_1", {"type": "thinking", "thinking": "x" * 10},
                   {"cache_read_input_tokens": prompt, "output_tokens": 3}),
        _assistant("msg_1", "req_1", {"type": "text", "text": "y" * 20},
                   {"cache_read_input_tokens": prompt, "output_tokens": 3}),
        _assistant("msg_1", "req_1", {"type": "tool_use", "input": {"a": "b"}},
                   {"cache_read_input_tokens": prompt, "output_tokens": 250}),
    ]


def test_a_reply_split_across_lines_is_one_model_call(survey, tmp_path):
    """Defect 1: the line-level approximation, as a property rather than as a corpus fact."""
    _write(tmp_path, "p/one.jsonl", [_user("go")] + _one_reply_three_blocks(1000))
    rows, _ = _rows(survey, tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["assistant_lines"] == 3
    assert row["model_calls"] == 1
    assert row["model_calls_by_message_id"] == 1
    assert row["assistant_lines_per_model_call"] == 3.0


def test_output_tokens_are_the_maximum_over_a_messages_lines(survey, tmp_path):
    """Defect 2. First-line would give 3, a naive sum would give 256; the total is 250."""
    _write(tmp_path, "p/one.jsonl", [_user("go")] + _one_reply_three_blocks(1000))
    row = _rows(survey, tmp_path)[0][0]
    assert row["recorded_output_tokens_total"] == 250


def test_prompt_tokens_are_summed_once_per_call_not_once_per_line(survey, tmp_path):
    """The prompt fields repeat verbatim on every line, so per-line summing triples them."""
    _write(tmp_path, "p/one.jsonl", [_user("go")] + _one_reply_three_blocks(1000))
    row = _rows(survey, tmp_path)[0][0]
    assert row["recorded_prompt_tokens_total"] == 1000
    assert row["recorded_prompt_tokens_peak"] == 1000
    assert row["recorded_cache_read_tokens_total"] == 1000


def test_the_prompt_is_all_three_usage_fields_and_not_input_tokens_alone(survey, tmp_path):
    _write(
        tmp_path,
        "p/one.jsonl",
        [
            _user("go"),
            _assistant(
                "m", "r", {"type": "text", "text": "hi"},
                {"input_tokens": 7, "cache_creation_input_tokens": 30,
                 "cache_read_input_tokens": 900, "output_tokens": 5},
            ),
        ],
    )
    row = _rows(survey, tmp_path)[0][0]
    assert row["recorded_prompt_tokens_total"] == 937
    assert row["recorded_input_tokens_total"] == 7


def test_a_synthetic_assistant_message_is_not_a_model_call(survey, tmp_path):
    _write(
        tmp_path,
        "p/one.jsonl",
        [
            _user("go"),
            *_one_reply_three_blocks(1000),
            {
                "type": "assistant",
                "cwd": BK,
                "timestamp": BEFORE,
                "message": {
                    "id": "not-a-msg-id",
                    "role": "assistant",
                    "model": "<synthetic>",
                    "content": [{"type": "text", "text": "API error"}],
                    "usage": {"input_tokens": 0, "output_tokens": 0,
                              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                },
            },
        ],
    )
    row = _rows(survey, tmp_path)[0][0]
    assert row["model_calls"] == 1
    assert row["synthetic_assistant_lines"] == 1
    assert row["assistant_lines"] == 4


def test_a_host_compaction_boundary_is_counted_and_a_plain_system_line_is_not(survey, tmp_path):
    """Bar §5.4 outcome U-4, as an instrument property."""
    _write(
        tmp_path,
        "p/one.jsonl",
        [
            _user("go"),
            *_one_reply_three_blocks(1000),
            {"type": "system", "subtype": "turn_duration", "cwd": BK, "timestamp": BEFORE},
            {"type": "system", "subtype": "compact_boundary", "cwd": BK, "timestamp": BEFORE,
             "compactMetadata": {"trigger": "manual", "preTokens": 12345}},
            {"type": "user", "cwd": BK, "timestamp": BEFORE, "isCompactSummary": True,
             "message": {"role": "user", "content": [{"type": "text", "text": "summary"}]}},
        ],
    )
    row = _rows(survey, tmp_path)[0][0]
    assert row["host_precompacted_boundaries"] == 1
    assert row["host_compact_summary_messages"] == 1
    assert row["host_compact_pre_tokens_total"] == 12345


def test_a_file_mixing_another_project_is_excluded_and_counted(survey, tmp_path):
    """The user's fence: a session whose prefix carries another project root is out."""
    _write(
        tmp_path,
        "p/pure.jsonl",
        [_user("go")] + _one_reply_three_blocks(1000),
    )
    _write(
        tmp_path,
        "p/mixed.jsonl",
        [_user("go"), _user("elsewhere", cwd=ELSEWHERE)] + _one_reply_three_blocks(1000),
    )
    _write(tmp_path, "p/outside.jsonl", [_user("only there", cwd=ELSEWHERE)])
    rows, census = _rows(survey, tmp_path)
    assert census["corpus_transcripts"] == 1
    assert census["excluded_mixed_cwd"] == 1
    assert census["excluded_mixed_cwd_other_lines"] == 1
    assert census["excluded_outside_the_fence"] == 1
    assert len(rows) == 1


def test_events_after_the_cutoff_are_dropped_and_the_transcript_is_flagged(survey, tmp_path):
    """The cutoff truncates the INPUT, which is what makes a growing corpus reproducible."""
    _write(
        tmp_path,
        "p/one.jsonl",
        [_user("go")]
        + _one_reply_three_blocks(1000)
        + [
            _user("later", timestamp=AFTER),
            _assistant("msg_2", "req_2", {"type": "text", "text": "z"},
                       {"cache_read_input_tokens": 5000, "output_tokens": 9},
                       timestamp=AFTER),
        ],
    )
    row = _rows(survey, tmp_path)[0][0]
    assert row["truncated_at_cutoff"] is True
    assert row["model_calls"] == 1
    assert row["recorded_prompt_tokens_total"] == 1000
    assert row["lines_total"] == 6
    assert row["lines_under_cutoff"] == 4


def test_untimestamped_bookkeeping_lines_are_enumerated_not_silently_dropped(survey, tmp_path):
    """Bar §1.2: an unenumerated skip is a failed check, not a rounding error."""
    _write(
        tmp_path,
        "p/one.jsonl",
        [_user("go")]
        + _one_reply_three_blocks(1000)
        + [{"type": "mode", "mode": "default", "sessionId": "s"},
           {"type": "ai-title", "aiTitle": "t", "sessionId": "s"}],
    )
    row = _rows(survey, tmp_path)[0][0]
    assert row["untimestamped_lines_by_type"] == {"ai-title": 1, "mode": 1}
    assert "mode" not in row["line_types"]


def test_a_transcript_with_no_model_call_is_excluded_and_counted(survey, tmp_path):
    _write(tmp_path, "p/empty.jsonl", [_user("go"), _user("still nothing")])
    rows, census = _rows(survey, tmp_path)
    assert rows == []
    assert census["excluded_zero_model_calls"] == 1


def test_the_transcript_id_is_stable_and_carries_no_path(survey, tmp_path):
    _write(tmp_path, "deep/nested/one.jsonl", [_user("go")] + _one_reply_three_blocks(1000))
    first = _rows(survey, tmp_path)[0][0]["transcript_id"]
    second = _rows(survey, tmp_path)[0][0]["transcript_id"]
    assert first == second
    assert len(first) == 16
    for fragment in ("one", "nested", "deep", "/", ".jsonl"):
        assert fragment not in first


def test_the_fence_fails_on_a_path_a_filename_or_a_home_prefix(survey):
    """Defect 3, and the fence is checked on the RENDERED bytes, nested values included."""
    clean = json.dumps({"transcript_id": "abc", "n": 3, "kinds": {"user": 1}}) + "\n"
    assert survey.fence_violations(clean) == []
    for poison in (
        {"transcript_id": "abc", "branch": "feat/thing"},
        {"transcript_id": "abc", "where": "/Users/kktest/x"},
        {"transcript_id": "abc", "file": "session.jsonl"},
        {"transcript_id": "abc", "nested": {"deep": ["a\\b"]}},
    ):
        assert survey.fence_violations(json.dumps(poison) + "\n"), poison


def test_the_least_squares_fit_recovers_a_planted_factor_and_fixed_cost(survey, tmp_path):
    """The factor is FITTED, so the fit is what has to be pinned.

    Twelve calls whose prompt tokens are exactly `500 + bytes / 4`, planted by choosing
    the user-message sizes. The fit must return 4 bytes per token and 500 tokens of fixed
    cost, and `r2` must be 1.
    """
    events: list[dict] = []
    running = 0
    for index in range(12):
        text = "u" * (400 * (index + 1))
        events.append(_user(text))
        running += len(text.encode())
        events.append(
            _assistant(
                f"m{index}", f"r{index}", {"type": "text", "text": ""},
                {"cache_read_input_tokens": 500 + running // 4, "output_tokens": 1},
            )
        )
    _write(tmp_path, "p/linear.jsonl", events)
    row = _rows(survey, tmp_path)[0][0]
    assert row["fit_calls"] == 12
    assert row["bytes_per_prompt_token_messages_only"] == pytest.approx(4.0, abs=1e-3)
    assert row["fit_intercept_tokens_messages_only"] == pytest.approx(500.0, abs=1.0)
    assert row["fit_r2_messages_only"] == pytest.approx(1.0, abs=1e-6)
    assert row["bytes_per_prompt_token_incremental_median"] == pytest.approx(4.0, abs=1e-3)


def test_the_fit_stops_at_the_first_host_compaction_boundary(survey, tmp_path):
    """A boundary breaks the append-only premise the fit rests on, so it ends the fit."""
    events: list[dict] = [_user("g" * 100)]
    for index in range(6):
        events.append(
            _assistant(f"m{index}", f"r{index}", {"type": "text", "text": ""},
                       {"cache_read_input_tokens": 1000 + index, "output_tokens": 1})
        )
        if index == 2:
            events.append({"type": "system", "subtype": "compact_boundary", "cwd": BK,
                           "timestamp": BEFORE, "compactMetadata": {"preTokens": 1}})
    _write(tmp_path, "p/one.jsonl", events)
    row = _rows(survey, tmp_path)[0][0]
    assert row["model_calls"] == 6
    assert row["fit_calls"] == 3


def test_content_bytes_follow_the_declared_rule_and_nothing_else(survey, tmp_path):
    """Text, thinking, serialised tool input, and a tool result's own content."""
    assert survey._content_bytes({"type": "text", "text": "abcd"}) == 4
    thinking = {"type": "thinking", "thinking": "abc", "signature": "X" * 99}
    assert survey._content_bytes(thinking) == 3  # the signature is not content
    assert survey._content_bytes({"type": "tool_use", "input": {"a": 1}}) == len('{"a": 1}')
    assert survey._content_bytes(
        {"type": "tool_result", "content": [{"type": "text", "text": "ab"}]}
    ) == 2
    assert survey._content_bytes({"type": "image", "source": {"data": "Z" * 500}}) == 0
    assert survey._content_bytes("ünïcode") == len("ünïcode".encode())


class TestTheReproductionCheckComparesNamedColumns:
    """Bar §9 in the form RB-P46 forced. Every mutation below must be caught.

    No node here compares bytes or whole lines, and none asserts what the committed
    artifact contains — they assert what the COMPARATOR does when handed a mutation.
    """

    @staticmethod
    def _committed(rows: list[dict]) -> str:
        return "".join(json.dumps(row) + "\n" for row in rows)

    ROWS = [
        {"transcript_id": "aaa", "model_calls": 3, "bytes_per_output_token": 2.0},
        {"transcript_id": "bbb", "model_calls": 5, "bytes_per_output_token": None},
    ]

    def test_the_unmutated_pair_passes(self, survey):
        problems, added = survey.compare_on_committed_keys(
            self._committed(self.ROWS), [dict(r) for r in self.ROWS]
        )
        assert problems == []
        assert added == []

    def test_a_changed_value_fails(self, survey):
        regen = [dict(r) for r in self.ROWS]
        regen[1]["model_calls"] = 6
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert any("model_calls" in p for p in problems)

    def test_an_int_against_a_float_fails(self, survey):
        regen = [dict(r) for r in self.ROWS]
        regen[0]["model_calls"] = 3.0
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems, "3 against 3.0 must fail: absent and zero are not the same either"

    def test_a_null_turning_into_a_zero_fails(self, survey):
        """A column that reads 0 must stay distinguishable from one that is absent."""
        regen = [dict(r) for r in self.ROWS]
        regen[1]["bytes_per_output_token"] = 0
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems

    def test_an_undeclared_new_key_fails(self, survey):
        regen = [dict(r) for r in self.ROWS]
        regen[0]["a_new_column"] = 1
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems

    def test_a_declared_additive_key_passes_and_is_named(self, survey, monkeypatch):
        monkeypatch.setattr(
            survey, "ADDITIVE_KEYS_THE_ARTIFACT_PREDATES", ("a_declared_column",)
        )
        regen = [dict(r) for r in self.ROWS]
        for row in regen:
            row["a_declared_column"] = 1
        problems, added = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems == []
        assert added == ["a_declared_column"]

    def test_a_deleted_committed_key_fails(self, survey):
        """Tolerance stated over a set is tolerance in BOTH directions — RB-P46's trap."""
        regen = [dict(r) for r in self.ROWS]
        for row in regen:
            row.pop("bytes_per_output_token")
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems

    def test_the_committed_keys_reordered_among_themselves_fail(self, survey):
        regen = [
            {"model_calls": r["model_calls"], "transcript_id": r["transcript_id"],
             "bytes_per_output_token": r["bytes_per_output_token"]}
            for r in self.ROWS
        ]
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert problems

    def test_a_missing_row_fails_on_the_count(self, survey):
        problems, _ = survey.compare_on_committed_keys(
            self._committed(self.ROWS), [dict(self.ROWS[0])]
        )
        assert any("row count" in p for p in problems)

    def test_a_row_whose_transcript_is_gone_fails_even_at_the_same_count(self, survey):
        """Matched by `transcript_id`, so a substitution at the same count is caught."""
        regen = [dict(self.ROWS[0]), dict(self.ROWS[1])]
        regen[1]["transcript_id"] = "ccc"
        problems, _ = survey.compare_on_committed_keys(self._committed(self.ROWS), regen)
        assert any("not in the regenerated corpus" in p for p in problems)

    def test_a_reordered_artifact_still_passes(self, survey):
        """Row ORDER is not a property this artifact asserts; row CONTENT is."""
        problems, _ = survey.compare_on_committed_keys(
            self._committed(self.ROWS), [dict(self.ROWS[1]), dict(self.ROWS[0])]
        )
        assert problems == []
