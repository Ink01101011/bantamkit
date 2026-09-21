from bantamkit.agent import Agent, AgentResult, MaxTurnsExceeded, ToolDef
from bantamkit.client import (
    APIError,
    BantamError,
    Message,
    ModelClient,
    OpenAICompatible,
    Response,
    Tool,
    ToolCall,
    TransportError,
    Usage,
)
from bantamkit.critique import (
    CritiqueExhausted,
    CritiqueGate,
    GroundedCritiqueGate,
    Rubric,
    load_rubric,
    render_evidence,
)
from bantamkit.evalrun import CONFIGS, format_report, run_suite
from bantamkit.filegraph import FileAccessGraph
from bantamkit.loopguard import LoopGuard
from bantamkit.memory import Memory, MemoryStore
from bantamkit.structured import StructuredOutputError, extract_json, structured

# RB-P45. The one place this checkout declares its version. `pyproject.toml` names this
# file as its dynamic version source, so the wheel's metadata and the string the MCP
# server advertises are the same committed bytes, and neither is a function of when
# someone last ran `pip`.
__version__ = "0.35.4"
