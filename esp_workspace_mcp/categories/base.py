"""
Abstract base class for tool categories.

Each category is a self-contained module that:
1. Defines metadata (NAME, DESCRIPTION, TOOLS list)
2. Implements register(mcp, config) to wire up all its tools
3. Keeps all tool functions in the same module or imports them

Categories declare which tools they provide, enabling configuration-driven
enablement so clients only see the tools they actually need.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class ToolCategory(ABC):
    """Base class for a group of related MCP tools."""
    
    NAME: str = ""
    DESCRIPTION: str = ""
    TOOLS: list[str] = []
    
    @classmethod
    @abstractmethod
    def register(cls, mcp: "FastMCP", config: dict) -> None:
        """Register all tools in this category with the FastMCP instance.
        
        Args:
            mcp: The FastMCP server instance
            config: The parsed configuration dict (for paths, tokens, etc.)
        """
        ...
    
    @classmethod
    def info(cls) -> dict[str, object]:
        return {
            "name": cls.NAME,
            "description": cls.DESCRIPTION,
            "tools": cls.TOOLS,
            "tool_count": len(cls.TOOLS),
        }
