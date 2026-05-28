"""Main MCP server: registers all tools and resources."""
import logging
from typing import List

from mcp.server.fastmcp import FastMCP

from esp_workspace_mcp.config import Settings

logger = logging.getLogger(__name__)


def create_server(settings: Settings) -> FastMCP:
    """Create and configure the FastMCP server with all tools registered."""
    
    mcp = FastMCP("esp-workspace")
    
    # Store settings in app state
    mcp.settings = settings
    
    # Import tool modules
    from esp_workspace_mcp.tools import filesystem
    from esp_workspace_mcp.tools import shell as shell_tools
    from esp_workspace_mcp.tools import esp_idf as idf_tools
    from esp_workspace_mcp.utils.process import JobManager
    
    job_mgr = JobManager(ttl_seconds=settings.MCP_JOB_TTL_SECONDS)
    
    # ---- Filesystem Tools ----
    
    @mcp.tool()
    def read_file(path: str, offset: int = 0, limit: int = 500) -> str:
        """Read a text file with optional offset and limit for pagination.
        
        Args:
            path: Absolute path to the file
            offset: Line number to start reading from (0 = beginning)
            limit: Maximum number of lines to return
        """
        return filesystem.read_file(
            path, settings.allowed_roots, offset=offset, limit=limit
        )
    
    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """Write content to a file. Creates parent directories if needed.
        
        Args:
            path: Absolute path to the file
            content: Text content to write
        """
        return filesystem.write_file(path, content, settings.allowed_roots)
    
    @mcp.tool()
    def append_file(path: str, content: str) -> str:
        """Append content to an existing file.
        
        Args:
            path: Absolute path to the file
            content: Text content to append
        """
        return filesystem.append_file(path, content, settings.allowed_roots)
    
    @mcp.tool()
    def list_dir(path: str) -> str:
        """List directory entries with type and size info.
        
        Args:
            path: Absolute path to the directory
        """
        return filesystem.list_dir(path, settings.allowed_roots)
    
    @mcp.tool()
    def create_dir(path: str) -> str:
        """Create a directory recursively.
        
        Args:
            path: Absolute path to the directory to create
        """
        return filesystem.create_dir(path, settings.allowed_roots)
    
    @mcp.tool()
    def delete_path(path: str) -> str:
        """Delete a file or empty directory.
        
        Args:
            path: Absolute path to the file or empty directory
        """
        return filesystem.delete_path(path, settings.allowed_roots)
    
    @mcp.tool()
    def file_stat(path: str) -> str:
        """Get file or directory metadata (size, permissions, mtime).
        
        Args:
            path: Absolute path to the file or directory
        """
        return filesystem.file_stat(path, settings.allowed_roots)
    
    @mcp.tool()
    def glob_search(pattern: str, path: str) -> str:
        """Find files matching a glob pattern (recursive).
        
        Args:
            pattern: Glob pattern, e.g. '*.c', '**/*.h', 'CMakeLists.txt'
            path: Directory to search in
        """
        return filesystem.glob_search(pattern, path, settings.allowed_roots)
    
    # ---- Shell / Process Tools ----
    
    @mcp.tool()
    def run_command(cmd: str, cwd: str = "", timeout: int = 30) -> str:
        """Execute a shell command and wait for completion.
        
        Args:
            cmd: Shell command to execute
            cwd: Working directory (optional, must be within allowed roots)
            timeout: Maximum execution time in seconds (max 300)
        """
        result = shell_tools.execute_command(
            cmd, settings.allowed_roots, cwd=cwd,
            timeout=timeout, max_timeout=settings.MCP_MAX_TIMEOUT,
            output_limit=settings.MCP_OUTPUT_LIMIT,
        )
        return shell_tools.format_result(result)
    
    @mcp.tool()
    def start_process(cmd: str, cwd: str = "") -> str:
        """Start a background process and return its job ID.
        
        Args:
            cmd: Shell command to execute
            cwd: Working directory (optional)
        """
        result = shell_tools.execute_command(
            cmd, settings.allowed_roots, cwd=cwd,
            job_mgr=job_mgr, background=True,
        )
        return shell_tools.format_result(result)
    
    @mcp.tool()
    def get_job_output(job_id: str, offset: int = 0) -> str:
        """Get output from a background job.
        
        Args:
            job_id: Job identifier from start_process
            offset: Line offset to start reading from
        """
        result = job_mgr.get_output(job_id, offset)
        
        if 'error' in result:
            return f"Error: {result['error']}"
        
        lines = [
            f"Job: {result['id']} | Status: {result['status']} | Lines: {result['total_lines']}",
            f"Cmd: {result['cmd']}",
        ]
        if result['output']:
            lines.append(f"\n{result['output']}")
        else:
            lines.append("(no output yet)")
        
        return '\n'.join(lines)
    
    @mcp.tool()
    def kill_job(job_id: str) -> str:
        """Terminate a running background job.
        
        Args:
            job_id: Job identifier
        """
        result = job_mgr.kill_job(job_id)
        if 'error' in result:
            return f"Error: {result['error']}"
        return f"Job {job_id} killed"
    
    @mcp.tool()
    def list_jobs() -> str:
        """List all background jobs with their status."""
        jobs = job_mgr.list_jobs()
        if not jobs:
            return "No jobs"
        
        lines = [f"Jobs: {len(jobs)} total\n"]
        lines.append(f"{'ID':<10} {'STATUS':<12} {'OUTPUT':>6} {'CMD'}")
        lines.append("-" * 70)
        
        for j in jobs:
            lines.append(f"{j['id']:<10} {j['status']:<12} {j.get('output_lines', 0):>6} {j['cmd']}")
        
        return '\n'.join(lines)
    
    # ---- ESP-IDF Tools ----
    
    @mcp.tool()
    def eim_run(commands: str, project_dir: str, wish_product: str = "", timeout: int = 600) -> str:
        """Run an arbitrary ESP-IDF command via the Espressif Install Manager.
        
        This is the core ESP-IDF tool. All build/flash operations go through here.
        
        Args:
            commands: idf.py arguments, e.g. "fullclean reconfigure build flash"
            project_dir: Absolute path to the ESP-IDF project
            wish_product: Target hardware product (e.g. "TargetS3", "TargetC6")
            timeout: Maximum execution time in seconds (default: 600)
        
        Examples:
            eim_run("build", "/path/to/project", "TargetS3")
            eim_run("fullclean reconfigure build", "/path/to/project", "TargetS3")
            eim_run("flash -p /dev/ttyUSB0", "/path/to/project", "TargetS3")
        """
        return idf_tools.format_eim_result(
            idf_tools.eim_run(
                project_dir, commands,
                settings.allowed_roots,
                wish_product=wish_product or settings.MCP_WISH_PRODUCT,
                eim_path=settings.MCP_EIM_PATH,
                timeout=timeout,
            )
        )
    
    @mcp.tool()
    def build_project(project_dir: str, wish_product: str = "", reconfigure: bool = False) -> str:
        """Build an ESP-IDF project.
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
            wish_product: Target hardware product (e.g. "TargetS3")
            reconfigure: If True, run reconfigure before build (when sdkconfig/defaults changed)
        """
        commands = "reconfigure build" if reconfigure else "build"
        return eim_run(commands, project_dir, wish_product, timeout=600)
    
    @mcp.tool()
    def set_target(project_dir: str, target: str, wish_product: str = "") -> str:
        """Set the ESP-IDF target chip (esp32, esp32s3, esp32c6, etc.).
        
        Only needed once per project — the target is persisted in sdkconfig.
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
            target: Target chip name (esp32, esp32s3, esp32c6, etc.)
            wish_product: Target hardware product
        """
        return eim_run(f"set-target {target}", project_dir, wish_product, timeout=120)
    
    @mcp.tool()
    def flash_project(project_dir: str, port: str = "", wish_product: str = "") -> str:
        """Flash the built firmware to a connected device.
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
            port: Serial port (e.g. "/dev/ttyUSB0"). If empty, uses default.
            wish_product: Target hardware product
        """
        commands = f"flash -p {port}" if port else "flash"
        return eim_run(commands, project_dir, wish_product, timeout=120)
    
    @mcp.tool()
    def clean_project(project_dir: str) -> str:
        """Clean build artifacts (preserves sdkconfig).
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
        """
        return eim_run("clean", project_dir, wish_product="", timeout=60)
    
    @mcp.tool()
    def fullclean_project(project_dir: str) -> str:
        """Remove the entire build directory.
        
        Use this before reconfigure when sdkconfig or project configuration has changed.
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
        """
        return eim_run("fullclean", project_dir, wish_product="", timeout=60)
    
    @mcp.tool()
    def reconfigure_project(project_dir: str, wish_product: str = "") -> str:
        """Regenerate sdkconfig and CMake cache.
        
        Use this when sdkconfig.defaults, WISH_PRODUCT, or project configuration changes.
        Typically followed by: eim_run("build", project_dir, wish_product)
        
        Args:
            project_dir: Absolute path to the ESP-IDF project
            wish_product: Target hardware product (required for proper sdkconfig generation)
        """
        return eim_run("reconfigure", project_dir, wish_product, timeout=120)
    
    # ---- Resources ----
    
    @mcp.resource("project://status")
    def get_project_status() -> str:
        """Get current project configuration (stub — returns server status)."""
        import json
        return json.dumps({
            'server': 'esp-workspace-mcp',
            'allowed_roots': settings.allowed_roots,
            'wish_product_default': settings.MCP_WISH_PRODUCT,
            'eim_path': settings.MCP_EIM_PATH,
        }, indent=2)
    
    logger.info(f"ESP-Workspace server created with {len(settings.allowed_roots)} allowed root(s)")
    return mcp
