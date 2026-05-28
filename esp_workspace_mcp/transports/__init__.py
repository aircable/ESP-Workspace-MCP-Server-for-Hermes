"""Transport configurations for the MCP server."""
from mcp.server.fastmcp import FastMCP


def setup_stdio(mcp: FastMCP) -> None:
    """Configure the server for stdio transport (local use)."""
    pass  # Default FastMCP transport is stdio


def setup_sse(mcp: FastMCP, host: str = "0.0.0.0", port: int = 8765) -> None:
    """Configure the server for SSE transport via HTTP.
    
    This is primarily done in run_server.py via uvicorn.
    This module provides transport-related helpers.
    """
    pass


# For Phase 1, transport selection is handled by run_server.py
# Future: add WebSocket transport here
