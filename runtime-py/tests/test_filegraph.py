import json

import pytest

from bantamkit.agent import Agent, ToolDef
from bantamkit.client import Tool
from bantamkit.filegraph import FileAccessGraph
from bantamkit.textutil import truncate


def reader_tool(contents, calls, name="read_file"):
    """A fake file-reading tool: `contents` is path->text, `calls` records every dispatch."""

    def handler(path):
        calls.append(path)
        if path not in contents:
            return f"error: unknown file '{path}'"
        return contents[path]

    return ToolDef(
        tool=Tool(name=name, description="read a file", parameters={"type": "object"}),
        handler=handler,
    )


def dispatch(agent, name, **kwargs):
    handler = next(t.handler for t in agent.tools if t.tool.name == name)
    return handler(**kwargs)


def graph_agent(graph, *tools):
    agent = Agent(client=None, tools=list(tools))
    agent.use(graph)
    return agent


def test_first_read_is_byte_identical_and_recorded():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    assert dispatch(agent, "read_file", path="a.txt") == "alpha"
    assert list(graph.reads) == ["a.txt"]
    assert graph.reads["a.txt"].count == 1 and graph.reads["a.txt"].changed is False


def test_undeclared_tool_bypasses_and_is_not_recorded():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls, name="other_tool"))
    assert dispatch(agent, "other_tool", path="a.txt") == "alpha"
    assert graph.reads == {}


def test_late_registered_reader_is_wrapped():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    agent.register_tool(reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert list(graph.reads) == ["a.txt"]


def test_direct_tools_append_bypasses_the_graph():
    """The one documented coverage gap: appending to agent.tools skips register_tool."""
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    agent.tools.append(reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert graph.reads == {}


def test_dot_slash_paths_normalize_to_one_node():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha", "./a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="./a.txt")
    assert list(graph.reads) == ["a.txt"]
    assert graph.reads["a.txt"].count == 2
    assert out.startswith("[file-graph]")  # repeat of the same node, collapsed by cache


def test_repeat_unchanged_returns_marker_and_reexecutes_handler():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="a.txt")
    assert calls == ["a.txt", "a.txt"]  # verify-on-repeat: handler ran BOTH times
    assert out.startswith("[file-graph]") and "unchanged" in out and "alpha" not in out


def test_repeat_changed_returns_full_content_with_changed_note():
    calls = []
    contents = {"a.txt": "alpha"}
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool(contents, calls))
    dispatch(agent, "read_file", path="a.txt")
    contents["a.txt"] = "beta"
    out = dispatch(agent, "read_file", path="a.txt")
    assert "CHANGED" in out and out.endswith("beta")
    assert graph.reads["a.txt"].changed is True


def test_annotate_without_cache_prefixes_note_and_keeps_content():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, cache=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    out = dispatch(agent, "read_file", path="a.txt")
    assert out.startswith("[file-graph]") and out.endswith("alpha")


def test_no_annotate_no_cache_repeats_are_byte_identical():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, annotate=False, cache=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    assert dispatch(agent, "read_file", path="a.txt") == "alpha"
    assert graph.reads["a.txt"].count == 2  # still recorded


def test_error_observation_is_not_recorded_and_not_cached():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({}, calls))
    out1 = dispatch(agent, "read_file", path="missing.txt")
    out2 = dispatch(agent, "read_file", path="missing.txt")
    assert out1.startswith("error:") and out2 == out1  # no marker on the second call
    assert graph.reads == {}


def test_raised_exception_propagates_and_is_not_recorded():
    def boom(path):
        raise RuntimeError("disk on fire")

    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(
        graph,
        ToolDef(tool=Tool(name="read_file", description="d", parameters={}), handler=boom),
    )
    with pytest.raises(RuntimeError):
        dispatch(agent, "read_file", path="a.txt")
    assert graph.reads == {}


def test_query_registers_tool_and_system_snippet():
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph)
    assert any(t.tool.name == "file_graph" for t in agent.tools)
    assert "file_graph" in agent.system


def test_query_off_registers_nothing():
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph)
    assert agent.tools == [] and agent.system is None


def test_render_map_and_empty_sentinel():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    assert graph.render() == "no files read yet"
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    dispatch(agent, "read_file", path="a.txt")
    line = graph.render()
    assert "a.txt" in line and "2 read(s)" in line and "unchanged" in line


# ---- accounting counters (bar §8 columns 1-6, Layer 1) ----
#
# These pin the INSTRUMENT, not the workload: every assertion below is a relation
# between a counter and the ledger (or between a counter and the bytes the loop would
# truncate), never a claim that some asset has some number of repeats.


def test_accounting_reconciles_with_the_ledger():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha", "b.txt": "beta"}, calls))
    for path in ("a.txt", "b.txt", "a.txt", "a.txt"):
        dispatch(agent, "read_file", path=path)
    acc = graph.accounting
    assert acc.reader_calls == 4
    assert acc.unrecorded_reader_calls == 0
    assert acc.recorded_reader_calls == sum(r.count for r in graph.reads.values())
    assert acc.repeat_reader_calls == sum(r.count - 1 for r in graph.reads.values()) == 2


def test_failed_reads_are_counted_as_attempts_and_carved_out():
    """The gap M3 read off the source: `error:` returns before `_record`.

    The ledger still sees successful reads only — that is verify-on-repeat's own
    precondition — but the attempt is no longer invisible, so the denominator cannot
    silently drop it.
    """
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    for _ in range(3):
        dispatch(agent, "read_file", path="missing.txt")
    acc = graph.accounting
    assert graph.reads.keys() == {"a.txt"}
    assert (acc.reader_calls, acc.unrecorded_reader_calls) == (4, 3)
    assert acc.recorded_reader_calls == sum(r.count for r in graph.reads.values()) == 1
    assert acc.repeat_reader_calls == 0


def test_collapsed_bytes_are_net_of_the_marker_and_of_truncation():
    """Bar §8: column 4 may not reuse `filegraph.py`'s model-facing `size`.

    `truncate` runs after this component returns (`agent.py:198`), so on an observation
    larger than the budget the full length overstates what the collapse removed. The
    column measures the transcript, so it is capped by the budget.
    """
    calls = []
    budget = 512
    content = "x" * 4000
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = Agent(client=None, observation_budget=budget)
    agent.use(graph)
    agent.register_tool(reader_tool({"a.txt": content}, calls))
    dispatch(agent, "read_file", path="a.txt")
    marker = dispatch(agent, "read_file", path="a.txt")

    assert graph.observation_budget == budget
    expected = len(truncate(content, budget).encode()) - len(truncate(marker, budget).encode())
    assert graph.accounting.collapsed_calls == 1
    assert graph.accounting.collapsed_bytes == expected
    # The whole point: strictly less than the number the marker's wording quotes.
    assert graph.accounting.collapsed_bytes < len(content.encode())
    assert str(len(content.encode())) in marker


def test_collapsed_bytes_equal_the_naive_figure_below_the_budget():
    """Under the budget the two coincide — which is why the difference has to be pinned."""
    calls = []
    content = "alpha" * 400
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph, reader_tool({"a.txt": content}, calls))
    dispatch(agent, "read_file", path="a.txt")
    marker = dispatch(agent, "read_file", path="a.txt")
    assert len(content.encode()) < agent.observation_budget  # no truncation in play
    assert graph.accounting.collapsed_bytes == len(content.encode()) - len(marker.encode()) > 0


def test_collapsing_a_file_smaller_than_the_marker_goes_negative():
    """Not clamped at zero: below the marker's own length the collapse is a net COST."""
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    marker = dispatch(agent, "read_file", path="a.txt")
    assert len(marker.encode()) > len(b"alpha")
    assert graph.accounting.collapsed_bytes == len(b"alpha") - len(marker.encode()) < 0


def test_annotate_marker_bytes_count_only_the_added_prefix():
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"}, cache=False, query=False)
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    annotated = dispatch(agent, "read_file", path="a.txt")
    added = len(annotated.encode()) - len(b"alpha")
    assert graph.accounting.annotate_marker_bytes == added > 0
    assert graph.accounting.collapsed_bytes == 0


def test_query_bytes_split_into_setup_and_render():
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph)
    tool = next(t.tool for t in agent.tools if t.tool.name == "file_graph")
    expected_setup = len(json.dumps(tool.to_wire()).encode()) + len(agent.system.encode())
    acc = graph.accounting
    assert acc.query_setup_bytes == expected_setup
    assert acc.query_render_bytes == 0
    rendered = graph.render()
    assert acc.query_render_bytes == len(rendered.encode())
    assert acc.query_bytes == acc.query_setup_bytes + acc.query_render_bytes


def test_query_off_costs_no_query_bytes():
    graph = FileAccessGraph(readers={"read_file": "path"}, query=False)
    graph_agent(graph)
    assert graph.accounting.query_bytes == 0


def test_save_load_round_trip_restores_cache_behavior(tmp_path):
    calls = []
    graph = FileAccessGraph(readers={"read_file": "path"})
    agent = graph_agent(graph, reader_tool({"a.txt": "alpha"}, calls))
    dispatch(agent, "read_file", path="a.txt")
    graph.save(tmp_path / "graph.json")

    restored = FileAccessGraph(readers={"read_file": "path"})
    restored.load(tmp_path / "graph.json")
    agent2 = graph_agent(restored, reader_tool({"a.txt": "alpha"}, calls))
    out = dispatch(agent2, "read_file", path="a.txt")
    assert out.startswith("[file-graph]") and "unchanged" in out  # remembered across instances
