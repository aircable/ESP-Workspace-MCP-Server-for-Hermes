"""
Filesystem tools category.

Provides: read_file, read_file_base64, write_file, write_file_base64,
          append_file, list_dir, create_dir, delete_path, file_stat,
          glob_search, copy_file, copy_dir, move_path
"""

from __future__ import annotations

import os
import shutil
import glob as globlib
import base64
from pathlib import Path
from typing import TYPE_CHECKING

from esp_workspace_mcp.categories.base import ToolCategory
from esp_workspace_mcp.categories import register

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _resolve(path: str, allowed_roots: list[str]) -> Path:
    """Resolve path against allowed roots. Raises ValueError if outside."""
    p = Path(path).resolve()
    # Check against configured roots, fall back to cwd
    roots = [Path(r).resolve() for r in allowed_roots] if allowed_roots else [Path.cwd()]
    for root in roots:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    raise ValueError(f"Path '{path}' is outside allowed roots: {allowed_roots}")


def _register_filesystem(mcp: "FastMCP", config: dict) -> None:
    """Register all filesystem tools."""
    roots = config.get("filesystem", {}).get("allowed_roots", [])
    
    @mcp.tool()
    async def read_file(path: str, offset: int = 1, limit: int = 500) -> str:
        """Read a text file with pagination.

        Args:
            path: Absolute or relative path to the file.
            offset: 1-indexed line number to start reading from. Default 1 (start of file).
            limit: Maximum number of lines to return. Default 500.

        Returns:
            File content with line numbers in "LINE_NUM|CONTENT" format,
            with a header showing the range and total line count.
        """
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 1
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 500
        limit = max(1, min(limit, 2000))
        offset = max(1, offset)

        try:
            p = _resolve(path, roots)
        except ValueError as e:
            return f"Error: {e}"

        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Not a file: {path}"

        try:
            lines = p.read_text(errors="replace").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            return f"Error reading file: {e}"

        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        selected = lines[start:end]
        header = f"Lines {start+1}-{end} of {total} (file: {path})\n"
        return header + "\n".join(f"{start+1+i}|{line}" for i, line in enumerate(selected))
    
    @mcp.tool()
    async def write_file(path: str, content: str) -> str:
        """Write content to a file. Creates parent directories if needed."""
        p = _resolve(path, roots)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    
    @mcp.tool()
    async def append_file(path: str, content: str) -> str:
        """Append content to an existing file."""
        p = _resolve(path, roots)
        if not p.exists():
            return f"Error: File not found: {path}"
        with open(p, "a") as f:
            f.write(content)
        return f"Appended {len(content)} bytes to {path}"
    
    @mcp.tool()
    async def list_dir(path: str = ".") -> str:
        """List directory entries with type and size info."""
        p = _resolve(path, roots)
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        entries = []
        for child in sorted(p.iterdir()):
            prefix = "DIR " if child.is_dir() else "FILE"
            size = child.stat().st_size if child.is_file() else 0
            entries.append(f"{prefix:4s} {size:>10d}  {child.name}")
        header = f"Directory: {path} ({len(entries)} entries)\n"
        return header + "\n".join(entries)
    
    @mcp.tool()
    async def create_dir(path: str) -> str:
        """Create a directory recursively."""
        p = _resolve(path, roots)
        p.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"
    
    @mcp.tool()
    async def delete_path(path: str) -> str:
        """Delete a file or empty directory."""
        p = _resolve(path, roots)
        if p.is_file():
            p.unlink()
            return f"Deleted file: {path}"
        elif p.is_dir():
            p.rmdir()
            return f"Deleted directory: {path}"
        return f"Error: Not found: {path}"
    
    @mcp.tool()
    async def file_stat(path: str) -> str:
        """Get file or directory metadata."""
        p = _resolve(path, roots)
        st = p.stat()
        return (
            f"Path: {path}\n"
            f"Size: {st.st_size} bytes\n"
            f"Modified: {st.st_mtime}\n"
            f"Permissions: {oct(st.st_mode)}\n"
            f"Is file: {p.is_file()}\n"
            f"Is dir:  {p.is_dir()}"
        )
    
    @mcp.tool()
    async def copy_file(src: str, dst: str) -> str:
        """Copy a file from source to destination. Creates parent dirs if needed.
        
        Both paths must be within the configured allowed roots."""
        src_p = _resolve(src, roots)
        dst_p = _resolve(dst, roots)
        if not src_p.exists():
            return f"Error: Source not found: {src}"
        if not src_p.is_file():
            return f"Error: Source is not a file: {src}"
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_p, dst_p)
        size = dst_p.stat().st_size
        return f"Copied {src} -> {dst} ({size} bytes)"
    
    @mcp.tool()
    async def copy_dir(src: str, dst: str) -> str:
        """Copy a directory recursively from source to destination.
        
        Both paths must be within the configured allowed roots.
        The destination must not already exist."""
        src_p = _resolve(src, roots)
        dst_p = _resolve(dst, roots)
        if not src_p.exists():
            return f"Error: Source not found: {src}"
        if not src_p.is_dir():
            return f"Error: Source is not a directory: {src}"
        if dst_p.exists():
            return f"Error: Destination already exists: {dst}"
        shutil.copytree(src_p, dst_p)
        # Count files/dirs copied
        file_count = sum(1 for _ in dst_p.rglob("*") if _.is_file())
        dir_count = sum(1 for _ in dst_p.rglob("*") if _.is_dir())
        return f"Copied directory {src} -> {dst} ({file_count} files, {dir_count} dirs)"
    
    @mcp.tool()
    async def move_path(src: str, dst: str) -> str:
        """Move or rename a file or directory.
        
        Both paths must be within the configured allowed roots."""
        src_p = _resolve(src, roots)
        dst_p = _resolve(dst, roots)
        if not src_p.exists():
            return f"Error: Source not found: {src}"
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))
        return f"Moved {src} -> {dst}"
    
    @mcp.tool()
    async def read_file_base64(path: str) -> str:
        """Read a file and return its contents as base64-encoded string.
        
        Use this for binary files (images, firmware blobs, etc.) that cannot
        be represented as text."""
        p = _resolve(path, roots)
        if not p.exists():
            return f"Error: File not found: {path}"
        data = p.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"File: {path}\nSize: {len(data)} bytes\nBase64: {encoded}"
    
    @mcp.tool()
    async def write_file_base64(path: str, b64content: str) -> str:
        """Write base64-encoded content to a file. Creates parent dirs if needed.
        
        Use this to write binary files (images, firmware blobs, etc.) by providing
        the base64-encoded content string."""
        p = _resolve(path, roots)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = base64.b64decode(b64content)
        p.write_bytes(data)
        return f"Wrote {len(data)} bytes to {path}"
    
    @mcp.tool()
    async def glob_search(pattern: str, path: str = ".") -> str:
        """Find files matching a glob pattern (recursive)."""
        base = _resolve(path, roots)
        matches = list(base.rglob(pattern))
        if not matches:
            return f"No files matching '{pattern}' in {path}"
        lines = [f"Found {len(matches)} files matching '{pattern}' in {path}:"]
        for m in sorted(matches):
            rel = m.relative_to(base)
            prefix = "DIR " if m.is_dir() else "FILE"
            size = m.stat().st_size if m.is_file() else 0
            lines.append(f"  {prefix} {size:>10d}  {rel}")
        return "\n".join(lines)


class FilesystemCategory(ToolCategory):
    NAME = "filesystem"
    DESCRIPTION = "File and directory operations with path sandboxing"
    TOOLS = [
        "read_file", "write_file", "append_file", "list_dir",
        "create_dir", "delete_path", "file_stat", "glob_search",
        "copy_file", "copy_dir", "move_path", "read_file_base64",
        "write_file_base64",
    ]
    
    @classmethod
    def register(cls, mcp: "FastMCP", config: dict) -> None:
        _register_filesystem(mcp, config)


# Register this category at import time
register("filesystem", "esp_workspace_mcp.categories.filesystem", "FilesystemCategory")
