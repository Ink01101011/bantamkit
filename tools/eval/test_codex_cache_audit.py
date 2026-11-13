import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("codex_cache_audit", HERE / "codex_cache_audit.py")
cca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cca)


def _rollout(path: Path, usages: list[tuple[int, int]]) -> Path:
    lines = [{"type": "session_meta", "payload": {"id": "s"}}]
    for i, (inp, cached) in enumerate(usages):
        lines.append({"type": "response_item", "payload": {"type": "custom_tool_call_output"}})
        lines.append({"type": "event_msg", "timestamp": f"t{i}", "payload": {
            "type": "token_count", "info": {"last_token_usage": {
                "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": 10}}}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


def test_a_healthy_session_has_no_miss(tmp_path):
    f = _rollout(tmp_path / "a.jsonl", [(12000, 9600), (12300, 11904), (12600, 12288)])
    r = cca.audit([str(f)])
    assert r["misses"] == 0 and r["miss_extra_uncached"] == 0
    assert r["uncached_input"] == 2400 + 396 + 312


def test_a_fall_back_to_the_preamble_is_a_miss_and_its_cost_is_the_lost_prefix(tmp_path):
    f = _rollout(tmp_path / "b.jsonl", [(12000, 9600), (16510, 15232), (16925, 9600)])
    r = cca.audit([str(tmp_path)])
    assert r["misses"] == 1 and r["requests_after_first"] == 2
    miss = r["by_session"][str(f)]["misses"][0]
    assert miss["index"] == 2 and miss["cached"] == 9600
    assert miss["lost"] == 16510 // 128 * 128 - 9600
    assert r["miss_fallback_cached_counts"] == {9600: 1}
    assert miss["appended"] == ["custom_tool_call_output"]


def test_the_first_request_is_never_a_miss_and_empty_input_reports_nothing(tmp_path):
    f = _rollout(tmp_path / "c.jsonl", [(12000, 0)])
    assert cca.audit([str(f)])["misses"] == 0
    (tmp_path / "empty").mkdir()
    assert cca.main([str(tmp_path / "empty")]) == 1
