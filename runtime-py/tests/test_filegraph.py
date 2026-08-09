import pytest

from bantamkit.agent import Agent, ToolDef
from bantamkit.client import Tool
from bantamkit.filegraph import FileAccessGraph


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
