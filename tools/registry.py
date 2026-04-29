from __future__ import annotations

from typing import Dict, List

from tools.base import ToolDef

CALCULATOR_TOOL: ToolDef = ToolDef(
    name="calculator",
    description="Safely evaluate a mathematical expression. Supports: +, -, *, /, **, ^, %, sqrt, sin, cos, tan, log, exp, pi, e, and more.",
    parameters={"expression": "the mathematical expression to evaluate"},
)

WEB_SEARCH_TOOL: ToolDef = ToolDef(
    name="web_search",
    description="Search the web for current, up-to-date information. Returns top results with titles, snippets, and URLs.",
    parameters={"query": "the search query"},
)

FILE_READ_TOOL: ToolDef = ToolDef(
    name="file_read",
    description="Read the contents of a text file from the local filesystem. Returns up to 2000 lines at a time. Use offset=N to read more.",
    parameters={
        "path": "Relative or absolute path to the file",
        "offset": "Starting line number (1-indexed, default 1)",
        "limit": "Maximum lines to return (max 2000, default 2000)",
    },
)

ALL_TOOLS: Dict[str, ToolDef] = {
    "calculator": CALCULATOR_TOOL,
    "web_search": WEB_SEARCH_TOOL,
    "file_read": FILE_READ_TOOL,
}


def get_tool_defs(tool_names: List[str] | None = None) -> List[ToolDef]:
    if not tool_names:
        return list(ALL_TOOLS.values())
    return [ALL_TOOLS[name] for name in tool_names if name in ALL_TOOLS]
