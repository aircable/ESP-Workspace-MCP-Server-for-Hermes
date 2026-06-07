"""
ESP-Workspace MCP Server — Core Server Module.

Creates a FastMCP server and registers tools from categories.
Falls back to legacy flat tool loading if categories are not configured.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Union

from mcp.server.fastmcp import FastMCP

from esp_workspace_mcp.config import MCPSettings, load_settings

# Category registry — new in Phase 5
try:
    from esp_workspace_mcp.categories import CategoryRegistry
    HAS_CATEGORIES = True
except ImportError:
    HAS_CATEGORIES = False


def _to_dict(config: Union[dict, object]) -> dict:
    """Convert a config object or dict to a plain nested dict.

    Handles both:
    - MCPSettings/BaseSettings objects with MCP_* flat attributes → nested dict
    - Already-nested dicts (passed through as-is)
    """
    if isinstance(config, dict):
        return config

    result: dict[str, Any] = {}
    # Known MCPSettings fields → map to nested structure
    _FIELD_MAP = {
        "mcp_api_token": ("auth", "token"),
        "mcp_host": ("server", "host"),
        "mcp_port": ("server", "port"),
        "mcp_log_level": ("server", "log_level"),
        "mcp_allowed_roots": ("filesystem", "allowed_roots"),
        "mcp_wish_product": ("esp_idf", "wish_product"),
        "mcp_idf_path": ("esp_idf", "idf_path"),
        "mcp_eim_path": ("esp_idf", "eim_path"),
        "mcp_default_timeout": ("shell", "default_timeout"),
        "mcp_max_timeout": ("shell", "max_timeout"),
        "mcp_output_limit": ("shell", "output_limit"),
        "mcp_job_ttl_seconds": ("jobs", "ttl_seconds"),
    }

    for attr in dir(config):
        if attr.startswith("_"):
            continue
        val = getattr(config, attr, None)
        if val is None or callable(val):
            continue
        # Skip pydantic internals
        if attr in ("model_computed_fields", "model_fields", "model_fields_set", "model_config", "model_extra", "model_fields"):
            continue

        key = attr.lower()
        if key in _FIELD_MAP:
            section, field = _FIELD_MAP[key]
            if section not in result:
                result[section] = {}
            # For allowed_roots, split comma-separated string into list
            if key == "mcp_allowed_roots" and isinstance(val, str):
                val = [r.strip() for r in val.split(",") if r.strip()]
            result[section][field] = val
        else:
            # Unknown field → put at top level
            result[key] = val

    return result


# ── Job Manager ──────────────────────────────────────────────────────────────

class JobManager:
    """Manages background subprocesses."""
    
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._lock = asyncio.Lock()

    async def start(self, command: str, cwd: str | None = None) -> str:
        async with self._lock:
            self._counter += 1
            job_id = f"job-{self._counter}"
        
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        
        async with self._lock:
            self._jobs[job_id] = {
                "proc": proc,
                "command": command,
                "cwd": cwd,
                "start_time": time.time(),
            }
        return job_id

    async def poll(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        
        proc = job["proc"]
        returncode = proc.returncode
        
        stdout, stderr = b"", b""
        if returncode is not None:
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        
        elapsed = time.time() - job["start_time"]
        return {
            "job_id": job_id,
            "command": job["command"],
            "returncode": returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[-50000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-50000:],
            "elapsed_seconds": round(elapsed, 1),
            "running": returncode is None,
        }

    async def read_output(self, job_id: str, offset: int = 1, limit: int = 500) -> str:
        """Read stdout from a completed job with offset and limit."""
        info = await self.poll(job_id)
        if "error" in info:
            return info["error"]
        lines = info["stdout"].split("\n")
        start = max(0, offset - 1)
        return "\n".join(lines[start:start + limit])

    async def kill(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        proc = job["proc"]
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
            return {"job_id": job_id, "status": "killed"}
        return {"job_id": job_id, "status": "already_finished", "returncode": proc.returncode}

    def list_jobs(self) -> list[dict[str, Any]]:
        now = time.time()
        result = []
        for jid, job in self._jobs.items():
            result.append({
                "job_id": jid,
                "command": job["command"],
                "returncode": job["proc"].returncode,
                "elapsed_seconds": round(now - job["start_time"], 1),
                "running": job["proc"].returncode is None,
            })
        return result


# ── Session Manager ──────────────────────────────────────────────────────────

class SessionManager:
    """Manages persistent working sessions."""
    
    def __init__(self):
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self, tag: str, working_dir: str) -> dict[str, Any]:
        if tag in self._sessions:
            return {"error": f"Session '{tag}' already exists"}
        self._sessions[tag] = {
            "tag": tag,
            "working_dir": str(Path(working_dir).resolve()),
            "created_at": time.time(),
        }
        return {"session": tag, "working_dir": working_dir}

    def destroy(self, tag: str) -> dict[str, Any]:
        if tag not in self._sessions:
            return {"error": f"Session '{tag}' not found"}
        del self._sessions[tag]
        return {"session": tag, "status": "destroyed"}

    def list_sessions(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "tag": s["tag"],
                "working_dir": s["working_dir"],
                "age_seconds": round(now - s["created_at"], 0),
            }
            for s in self._sessions.values()
        ]


# ── Server Factory ───────────────────────────────────────────────────────────

def create_server(config: "MCPSettings | dict | None" = None) -> FastMCP:
    """Create and configure the MCP server.
    
    Accepts MCPSettings, dict, or None (loads from .env).
    If categories are configured, loads only those categories.
    Otherwise, loads all registered categories or falls back to legacy tools.
    """
    if config is None:
        config = load_settings()
    
    config_dict = _to_dict(config)
    server_cfg = config_dict.get("server", {})
    name = server_cfg.get("name", "esp-workspace")
    
    mcp = FastMCP(name)
    jobs = JobManager()
    sessions = SessionManager()

    # ── Tool call logging ──────────────────────────────────────────────────
    import logging as _logging
    _tool_logger = _logging.getLogger("esp_workspace_mcp.tools")

    # Monkey-patch FastMCP to log all tool calls
    _original_tool = mcp.tool
    def _logged_tool(*args, **kwargs):
        """Decorator that wraps tool functions with logging."""
        def _decorator(func):
            _tool_name = func.__name__
            import functools
            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def _async_wrapper(*a, **kw):
                    _tool_logger.info("TOOL: %s(%s)", _tool_name, ", ".join(
                        [repr(x) for x in a] + [f"{k}={v!r}" for k, v in kw.items()]
                    ))
                    try:
                        result = await func(*a, **kw)
                        _tool_logger.info("DONE: %s", _tool_name)
                        return result
                    except Exception as exc:
                        _tool_logger.error("FAIL: %s: %s", _tool_name, exc)
                        raise
                return _original_tool(*args, **kwargs)(_async_wrapper)
            else:
                @functools.wraps(func)
                def _sync_wrapper(*a, **kw):
                    _tool_logger.info("TOOL: %s(%s)", _tool_name, ", ".join(
                        [repr(x) for x in a] + [f"{k}={v!r}" for k, v in kw.items()]
                    ))
                    try:
                        result = func(*a, **kw)
                        _tool_logger.info("DONE: %s", _tool_name)
                        return result
                    except Exception as exc:
                        _tool_logger.error("FAIL: %s: %s", _tool_name, exc)
                        raise
                return _original_tool(*args, **kwargs)(_sync_wrapper)
        return _decorator
    mcp.tool = _logged_tool
    
    # Check if categories are configured
    enabled_categories = config_dict.get("categories", {}).get("enabled", [])
    
    if enabled_categories and HAS_CATEGORIES:
        # New behavior: load only enabled categories
        for cat_name in enabled_categories:
            cat_cls = CategoryRegistry.get(cat_name)
            if cat_cls:
                cat_cls.register(mcp, config_dict)
                print(f"  [category] {cat_name}: {len(cat_cls.TOOLS)} tools")
            else:
                print(f"  [WARNING] Unknown category: {cat_name}")
        # Always register core tools (jobs, sessions)
        _register_core_tools(mcp, jobs, sessions)
    elif HAS_CATEGORIES:
        # No categories specified — load ALL registered categories
        CategoryRegistry.load_all()
        for cat_name in CategoryRegistry.list_categories():
            cat_cls = CategoryRegistry.get(cat_name)
            if cat_cls:
                cat_cls.register(mcp, config_dict)
                print(f"  [category] {cat_name}: {len(cat_cls.TOOLS)} tools")
        _register_core_tools(mcp, jobs, sessions)
    else:
        # Fallback: legacy flat tool loading (original behavior)
        _register_legacy_tools(mcp, config)
    
    return mcp


def _register_core_tools(mcp: FastMCP, jobs: JobManager, sessions: SessionManager):
    """Register cross-cutting tools (jobs, sessions)."""

    @mcp.tool()
    async def run_command(command: str, cwd: str | None = None, timeout: int = 60) -> str:
        """Execute a shell command and wait for completion."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = ""
            if stdout:
                out += stdout.decode("utf-8", errors="replace")
            if stderr:
                out += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0 and not out.strip():
                out += f"\n[exit code: {proc.returncode}]"
            return out[-50000:]
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Command timed out after {timeout}s"

    @mcp.tool()
    async def start_process(command: str, cwd: str | None = None) -> str:
        """Start a background process and return its job ID."""
        job_id = await jobs.start(command, cwd=cwd)
        return job_id

    @mcp.tool()
    async def get_job_output(job_id: str, offset: int = 1, limit: int = 500) -> str:
        """Get output from a background job with pagination.

        Args:
            job_id: The job identifier returned by start_process.
            offset: 1-indexed line number to start from. Default 1.
            limit: Maximum number of lines to return. Default 500.
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

        info = await jobs.poll(job_id)
        if "error" in info:
            return info["error"]
        lines = info["stdout"].split("\n")
        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        selected = lines[start:end]
        header = "Lines %d-%d of %d (job: %s)\n" % (start + 1, end, total, job_id)
        return header + "\n".join(selected)

    @mcp.tool()
    async def kill_job(job_id: str) -> str:
        """Terminate a running background job."""
        result = await jobs.kill(job_id)
        return str(result)

    @mcp.tool()
    def list_jobs() -> list:
        """List all background jobs with their status."""
        return jobs.list_jobs()

    @mcp.tool()
    def create_session(tag: str, working_dir: str) -> str:
        """Create a persistent working session."""
        result = sessions.create(tag, working_dir)
        return str(result)

    @mcp.tool()
    def destroy_session(tag: str) -> str:
        """Destroy a working session."""
        result = sessions.destroy(tag)
        return str(result)

    @mcp.tool()
    def list_sessions() -> list:
        """List all active working sessions."""
        return sessions.list_sessions()


def _register_legacy_tools(mcp: FastMCP, config):
    """Original flat tool registration — backward compatibility fallback.
    
    This imports and registers all the original tools from the tools/ modules.
    Used when categories module is not available.
    """
    loaded = []
    failed = []
    
    for mod_name in ("filesystem", "shell", "esp_idf", "git_tools", "search",
                     "serial_tools", "diagnostics", "session_tools"):
        try:
            mod = importlib.import_module(f"esp_workspace_mcp.tools.{mod_name}")
            if hasattr(mod, "register"):
                mod.register(mcp, config)
                loaded.append(mod_name)
        except ImportError as e:
            failed.append(f"{mod_name}: {e}")
        except Exception as e:
            failed.append(f"{mod_name}: {e}")
    
    if loaded:
        print(f"  [legacy] Loaded: {', '.join(loaded)}")
    if failed:
        print(f"  [legacy] Skipped: {', '.join(failed)}")
