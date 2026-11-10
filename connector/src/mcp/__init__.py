"""
XiaoZhi MCP Integration & Tool Calling Package
"""
from .tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    wewin_test_connection_tool,
    wewin_search_tool,
    wewin_get_programs_tool,
    wewin_get_contact_tool,
    wewin_get_page_tool
)

__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "wewin_test_connection_tool",
    "wewin_search_tool",
    "wewin_get_programs_tool",
    "wewin_get_contact_tool",
    "wewin_get_page_tool"
]
