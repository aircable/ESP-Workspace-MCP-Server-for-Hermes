"""
Core MCP server for esp-workspace.

Creates a FastMCP server and registers tool categories based on configuration.
Categories are loaded from esp_workspace_mcp.categories for modularity.
Falls back to legacy flat tool loading if no categories are specified.
"""

from __future__ import annotations

import tomllib
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
import asyncio

from esp_workspace_mcp.auth import create_auth_middleware
from esp_workspace_mcp.categories import CategoryRegistry


# ── Job Manager ──────────────────────────────────────────────────────────────

class JobManager:
    """Manages background subprocesses."""
    
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._lock = asyncio.Lock()
    
    async def start(self, command: str, cwd: str | None = None,
                    env: dict | None = None) -> str:
        import subprocess
        async with self._lock:
            self._counter += 1
            job_id = f"job-{self._counter:04d}"
        
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        
        async with self._lock:
            self._jobs[job_id] = {
                "proc": proc,
                "command": command,
                "cwd": cwd,
            }
        return job_id
    
    async def poll(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        proc = job["proc"]
        running = proc.returncode is None
        stdout = ""
        stderr = ""
        if not running:
            out = await proc.stdout.read()
            err = await proc.stderr.read()
            stdout = out.decode(errors="replace")
            stderr = err.decode(errors="replace")
        return {
            "job_id": job_id,
            "running": running,
            "returncode": proc.returncode,
            "stdout": stdout[-50000:],  # truncate
            "stderr": stderr[-50000:],
        }
    
    async def wait(self, job_id: str, timeout: float = 30) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}
        try:
            await asyncio.wait_for(job["proc"].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return await self.poll(job_id)
    
    async def kill(self, job_id: str) -> str:
        job = self._jobs.get(job_id)
        if not job:
            return f"Job {job_id} not found"
        job["proc"].kill()
        return f"Killed {job_id}"
    
    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "job_id": jid,
                "command": j["command"],
                "running": j["proc"].returncode is None,
                "returncode": j["proc"].returncode,
            }
            for jid, j in self._jobs.items()
        ]
    
    async def read_output(self, job_id: str, offset: int = 1,
                          limit: int = 500) -> str:
        result = await self.poll(job_id)
        if "error" in result:
            return result["error"]
        lines = result["stdout"].splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        selected = lines[start:end]
        return "\n".join(f"{start+1+i}|{line}" for i, line in enumerate(selected))


class SessionManager:
    """Manages persistent working sessions."""
    
    def __init__(self):
        self._sessions: dict[str, dict[str, Any]] = {}
        self._counter = 0
    
    def create(self, cwd: str | None = None, description: str = "") -> str:
        import time
        self._counter += 1
        sid = f"session-{self._counter:04d}"
        self._sessions[sid] = {
            "cwd": cwd or str(Path.cwd()),
            "description": description,
            "created": time.time(),
        }
        return sid
    
    def destroy(self, session_id: str) -> str:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return f"Destroyed {session_id}"
        return f"Session {session_id} not found"
    
    def list_sessions(self) -> list[dict]:
        import time
        return [
            {
                "session_id": sid,
                "cwd": s["cwd"],
                "description": s["description"],
                "age_seconds": int(time.time() - s["created"]),
            }
            for sid, s in self._sessions.items()
        ]


# ── Config ───────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATHS = [
    Path.home() / ".config" / "esp-workspace" / "config.toml",
    Path(".env.server"),
]

def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from TOML file."""
    paths = [Path(config_path)] if config_path else DEFAULT_CONFIG_PATHS
    for p in paths:
        if p.exists():
            with open(p, "rb") as f:
                return tomllib.load(f)
    return {}


# ── Server Factory ───────────────────────────────────────────────────────────

def create_server(config: dict[str, Any] | None = None) -> FastMCP:
    """Create and configure the MCP server.
    
    If config['categories']['enabled'] is set, only those categories are loaded.
    Otherwise, all categories are loaded (backward-compatible default).
    """
    if config is None:
        config = load_config()
    
    server_cfg = config.get("server", {})
    name = server_cfg.get("name", "esp-workspace")
    
    mcp = FastMCP(name)
    jobs = JobManager()
    sessions = SessionManager()
    
    # Determine which categories to load
    enabled = config.get("categories", {}).get("enabled", [])
    
    if enabled:
        # New behavior: load only enabled categories
        for cat_name in enabled:
            cat_cls = CategoryRegistry.get(cat_name)
            if cat_cls:
                cat_cls.register(mcp, config)
                print(f"  [category] {cat_name}: {len(cat_cls.TOOLS)} tools")
            else:
                print(f"  [WARNING] Unknown category: {cat_name}")
    else:
        # Fallback: try to load all registered categories
        CategoryRegistry.load_all()
        for cat_name in CategoryRegistry.list_categories():
            cat_cls = CategoryRegistry.get(cat_name)
            if cat_cls:
                cat_cls.register(mcp, config)
                print(f"  [category] {cat_name}: {len(cat_cls.TOOLS)} tools")
    
    # Register core tools that don't belong to any category (jobs, sessions)
    _register_core_tools(mcp, jobs, sessions)
    
    return mcp


def _register_core_tool(mcp, jobs, sessions):
    """Register cross-cutting tools (jobs, sessions)."""
    
    @mcp.tool()
    async def run_command(command: str, cwd: str | None = None,
                          timeout: int = 60) -> str:
        """Execute a shell command and wait for completion."""
        import asyncio
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            out = stdout.decode(errors="replace")[-50000:]
            err = stderr.decode(errors="replace")[-50000:]
            result = f"Exit code: {proc.returncode}\n"
            if out:
                result += f"\n--- stdout ---\n{out}"
            if err:
                result += f"\n--- stderr ---\n{err}"
            return result
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s and was killed"
    
    @mcp.tool()
    async def start_process(command: str, cwd: str | None = None) -> str:
        """Start a background process and return its job ID."""
        job_id = await jobs.start(command, cwd=cwd)
        return job_id
    
    @mcp.tool()
    async def get_job_output(job_id: str) -> str:
        """Get output from a background job."""
        result = await jobs.poll(job_id)
        if "error" in result:
            return result["error"]
        status = "RUNNING" if result["running"] else f"EXITED({result['returncode']})"
        lines = [
            f"Job: {job_id}  Status: {status}",
            "",
            "--- stdout ---",
            result["stdout"] or "(empty)",
        ]
        if result["stderr"]:
            lines.append("\n--- stderr ---")
            lines.append(result["stderr"])
        return "\n".join(lines)
    
    @mcp.tool()
    async def read_job_output(job_id: str, offset: int = 1,
                               limit: int = 500) -> str:
        """Get output from a background job with offset/limit pagination."""
        return await jobs.read_output(job_id, offset, limit)
    
    @mcp.tool()
    async def wait_for_job(job_id: str, timeout: float = 30) -> str:
        """Wait for a background job to complete, with timeout."""
        result = await jobs.wait(job_id, timeout=timeout)
        if "error" in result:
            return result["error"]
        status = "RUNNING" if result["running"] else f"EXITED({result['returncode']})"
        return f"Job: {job_id}  Status: {status}"
    
    @mcp.tool()
    async def kill_job(job_id: str) -> str:
        """Terminate a running background job."""
        return await jobs.kill(job_id)
    
    @mcp.tool()
    async def list_jobs() -> str:
        """List all background jobs with their status."""
        job_list = jobs.list_jobs()
        if not job_list:
            return "No jobs"
        lines = []
        for j in job_list:
            status = "RUNNING" if j["running"] else f"EXITED({j['returncode']})"
            lines.append(f"  {j['job_id']}  [{status}]  {j['command']}")
        return f"Jobs ({len(job_list)}):\n" + "\n".join(lines)
    
    @mcp.tool()
    async def create_session(cwd: str = "", description: str = "") -> str:
        """Create a persistent working session."""
        return sessions.create(cwd=cwd or None, description=description)
    
    @mcp.tool()
    async def destroy_session(session_id: str) -> str:
        """Destroy a working session."""
        return sessions.destroy(session_id)
    
    @mcp.tool()
    async def list_sessions() -> str:
        """List all active working sessions."""
        session_list = sessions.list_sessions()
        if not session_list:
            return "No active sessions"
        lines = []
        for s in session_list:
            lines.append(
                f"  {s['session_id']}  age={s['age_seconds']}s  "
                f"cwd={s['cwd']}  {s['description']}"
            )
        return f"Sessions ({len(session_list)}):\n" + "\n".join(lines)
