"""
OpenMV development tools category.

This is a stub demonstrating how a new tool category would be implemented.
To use:Categories. categories/openmv.py
Enable in config: categories.enabled = [..., "openmv"]

OpenMV is a Python-based machine vision platform. Tools in this category
would provide:
- Flashing OpenMV firmware
- Running scripts on the OpenMV camera
- Capturing images / reading sensor data
- Managing OpenMV IDE projects
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from esp_workspace_mcp.categories.base import ToolCategory
from esp_workspace_mcp.categories import register

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _register_openmv(mcp: "FastMCP", config: dict) -> None:
    """Register OpenMV development tools."""
    
    openmv_cfg = config.get("openmv", {})
    projects_dir = openmv_cfg.get("projects_dir", "/opt/openmv-projects")
    
    @mcp.tool()
    async def openmv_list_scripts() -> str:
        """List OpenMV scripts in the projects directory."""
        import os
        p = __import__('pathlib').Path(projects_dir)
        if not p.exists():
            return f"OpenMV projects dir not found: {projects_dir}"
        scripts = list(p.glob("**/*.py"))
        if not scripts:
            return f"No Python scripts in {projects_dir}"
        lines = [f"OpenMV scripts ({len(scripts)}) in {projects_dir}:"]
        for s in sorted(scripts):
            rel = s.relative_to(p)
            lines.append(f"  {s.stat().st_size:>8d}  {rel}")
        return "\n".join(lines)
    
    @mcp.tool()
    async def openmv_run(script: str, port: str = "/dev/ttyACM0") -> str:
        """Run an OpenMV script on the connected camera.
        
        Args:
            script: Path to the .py script to run
            port: Serial port of the OpenMV camera
        """
        return f"Would run {script} on {port} (stub)"
    
    @mcp.tool()
    async def openmv_capture(port: str = "/dev/ttyACM0") -> str:
        """Capture an image from the OpenMV camera.
        
        Args:
            port: Serial port of the OpenMV camera
        """
        return f"Would capture image from {port} (stub)"
    
    @mcp.tool()
    async def openmv_list_devices() -> str:
        """List connected OpenMV devices."""
        return "Would enumerate OpenMV devices (stub)"


class OpenMVCategory(ToolCategory):
    NAME = "openmv"
    DESCRIPTION = "OpenMV camera development: flash, run scripts, capture images"
    TOOLS = [
        "openmv_list_scripts",
        "openmv_run",
        "openmv_capture",
        "openmv_list_devices",
    ]
    
    @classmethod
    def register(cls, mcp: "FastMCP", config: dict) -> None:
        _register_openmv(mcp, config)


# Register this category at import time
register("openmv", "esp_workspace_mcp.categories.openmv", "OpenMVCategory")
