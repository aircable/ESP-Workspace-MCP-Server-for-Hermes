"""Main MCP server: registers all tools and resources."""
import logging
from typing import List

from mcp.server.fastmcp import FastMCP

from esp_workspace_mcp.config import Settings

logger = logging.getLogger(__name__)


def create_server(settings: Settings) -> FastMCP:
    """Create and configure the FastMCP server with all tools registered."""

    mcp = FastMCP("esp-workspace")

    # Store settings in app state for access in tool handlers
    mcp.settings = settings

    # Import tool modules
    from esp_workspace_mcp.tools import filesystem
    from esp_workspace_mcp.tools import shell as shell_tools
    from esp_workspace_mcp.tools import esp_idf as idf_tools
    from esp_workspace_mcp.tools import git_tools as git
    from esp_workspace_mcp.tools import search as search_tools
    from esp_workspace_mcp.tools import serial_tools as serial
    from esp_workspace_mcp.tools import diagnostics as diag
    from esp_workspace_mcp.tools import phase4_tools as p4tools
    from esp_workspace_mcp.tools import phase4_uart as p4uart
    from esp_workspace_mcp.tools import phase4_symbols as p4sym
    from esp_workspace_mcp.tools import phase4_debug as p4debug
    from esp_workspace_mcp.tools.session_tools import SessionManager
    from esp_workspace_mcp.utils.process import JobManager

    job_mgr = JobManager(ttl_seconds=settings.MCP_JOB_TTL_SECONDS)
    session_mgr = SessionManager(ttl_seconds=7200)
    roots = settings.allowed_roots

    # Helper to get active sessions dict
    def get_sessions():
        return session_mgr.get_all()

    # ================================================================
    # Filesystem Tools
    # ================================================================

    @mcp.tool()
    def read_file(path: str, offset: int = 0, limit: int = 500) -> str:
        """Read a text file with optional offset and limit for pagination.

        Args:
            path: Absolute path to the file
            offset: Line number to start reading from (0 = beginning)
            limit: Maximum number of lines to return
        """
        return filesystem.read_file(path, roots, offset=offset, limit=limit)

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """Write content to a file. Creates parent directories if needed.

        Args:
            path: Absolute path to the file
            content: Text content to write
        """
        return filesystem.write_file(path, content, roots)

    @mcp.tool()
    def append_file(path: str, content: str) -> str:
        """Append content to an existing file.

        Args:
            path: Absolute path to the file
            content: Text content to append
        """
        return filesystem.append_file(path, content, roots)

    @mcp.tool()
    def list_dir(path: str) -> str:
        """List directory entries with type and size info.

        Args:
            path: Absolute path to the directory
        """
        return filesystem.list_dir(path, roots)

    @mcp.tool()
    def create_dir(path: str) -> str:
        """Create a directory recursively.

        Args:
            path: Absolute path to the directory to create
        """
        return filesystem.create_dir(path, roots)

    @mcp.tool()
    def delete_path(path: str) -> str:
        """Delete a file or empty directory.

        Args:
            path: Absolute path to the file or empty directory
        """
        return filesystem.delete_path(path, roots)

    @mcp.tool()
    def file_stat(path: str) -> str:
        """Get file or directory metadata (size, permissions, mtime).

        Args:
            path: Absolute path to the file or directory
        """
        return filesystem.file_stat(path, roots)

    @mcp.tool()
    def glob_search(pattern: str, path: str) -> str:
        """Find files matching a glob pattern (recursive).

        Args:
            pattern: Glob pattern, e.g. '*.c', '**/*.h', 'CMakeLists.txt'
            path: Directory to search in
        """
        return filesystem.glob_search(pattern, path, roots)

    # ================================================================
    # Shell / Process Tools
    # ================================================================

    @mcp.tool()
    def run_command(cmd: str, cwd: str = "", timeout: int = 30, session_id: str = "") -> str:
        """Execute a shell command and wait for completion.

        Args:
            cmd: Shell command to execute
            cwd: Working directory (optional, must be within allowed roots)
            timeout: Maximum execution time in seconds (max 300)
            session_id: Optional session ID to inherit working directory
        """
        result = shell_tools.execute_command(
            cmd, roots, cwd=cwd,
            timeout=timeout, max_timeout=settings.MCP_MAX_TIMEOUT,
            output_limit=settings.MCP_OUTPUT_LIMIT,
            session_id=session_id,
            sessions=get_sessions(),
        )
        return shell_tools.format_result(result)

    @mcp.tool()
    def start_process(cmd: str, cwd: str = "", session_id: str = "") -> str:
        """Start a background process and return its job ID.

        Args:
            cmd: Shell command to execute
            cwd: Working directory (optional)
            session_id: Optional session ID to inherit working directory
        """
        effective_cwd = cwd
        if session_id:
            s = session_mgr.get_session(session_id)
            if s:
                effective_cwd = s.get('working_dir', cwd)
        result = shell_tools.execute_command(
            cmd, roots, cwd=effective_cwd,
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
            f"Job: {result['job_id']} | Status: {result['status']} | Lines: {result['total_lines']}",
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

    @mcp.tool()
    def wait_for_job(job_id: str, timeout: float = 60) -> str:
        """Wait for a background job to complete.

        Args:
            job_id: Job identifier from start_process
            timeout: Maximum seconds to wait (default: 60)
        """
        result = job_mgr.wait_for_job(job_id, timeout)
        if 'error' in result:
            return f"Error: {result['error']}"
        
        lines = [
            f"Job: {result.get('job_id', job_id)}",
            f"Status: {result.get('status', 'unknown')}",
            f"Return code: {result.get('return_code', 'N/A')}",
            f"Message: {result.get('message', '')}",
        ]
        if 'output_lines' in result:
            lines.append(f"Output lines: {result['output_lines']}")
        return '\n'.join(lines)

    # ================================================================
    # ESP-IDF Tools
    # ================================================================

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
                roots,
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

        Only needed once per project -- the target is persisted in sdkconfig.

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

    @mcp.tool()
    def parse_build_output(output: str) -> str:
        """Parse build output into structured errors and warnings.

        Takes raw build output text and returns a JSON structure with
        arrays of errors and warnings, each with file, line, message info.

        Args:
            output: Raw build text (e.g. from a previous build_project or eim_run)
        """
        return idf_tools.parse_build_output(output)

    @mcp.tool()
    def idf_size(project_dir: str, wish_product: str = "") -> str:
        """Run idf.py size and return memory usage breakdown.

        Args:
            project_dir: Absolute path to the ESP-IDF project
            wish_product: Target hardware product
        """
        return idf_tools.idf_size(
            project_dir, roots,
            wish_product=wish_product or settings.MCP_WISH_PRODUCT,
            eim_path=settings.MCP_EIM_PATH,
        )

    @mcp.tool()
    def idf_sdkconfig(project_dir: str, wish_product: str = "") -> str:
        """Export sdkconfig as structured data.

        Reads the project's sdkconfig file and returns all configuration
        key-value pairs. If sdkconfig doesn't exist, runs reconfigure first.

        Args:
            project_dir: Absolute path to the ESP-IDF project
            wish_product: Target hardware product
        """
        return idf_tools.idf_sdkconfig(
            project_dir, roots,
            wish_product=wish_product or settings.MCP_WISH_PRODUCT,
            eim_path=settings.MCP_EIM_PATH,
        )

    # ================================================================
    # Git Tools  (Phase 2)
    # ================================================================

    @mcp.tool()
    def git_status(directory: str) -> str:
        """Get the working tree status of a git repository.

        Shows branch info, remote tracking, staged/unstaged changes,
        and untracked files.

        Args:
            directory: Absolute path to the git repository root
        """
        return git.git_status(directory, roots)

    @mcp.tool()
    def git_diff(directory: str, staged: bool = False, file_path: str = "", context_lines: int = 3) -> str:
        """Get the diff of changes in a git repository.

        Args:
            directory: Absolute path to the git repository root
            staged: If True, show staged changes instead of unstaged
            file_path: Optional file path to limit diff to a single file
            context_lines: Number of context lines around changes
        """
        return git.git_diff(directory, roots, staged=staged, file_path=file_path, context_lines=context_lines)

    @mcp.tool()
    def git_commit(directory: str, message: str, files: list[str] = None) -> str:
        """Stage and commit changes in a git repository.

        Args:
            directory: Absolute path to the git repository root
            message: Commit message
            files: Optional list of specific file paths to stage. If None, stages all changes.
        """
        return git.git_commit(directory, roots, message, files=files)

    @mcp.tool()
    def git_branch(directory: str, create: str = "", delete: str = "", rename_from: str = "", rename_to: str = "") -> str:
        """List, create, delete, or rename branches in a git repository.

        Args:
            directory: Absolute path to the git repository root
            create: Name of a new branch to create
            delete: Name of a branch to delete
            rename_from: Current name of branch to rename
            rename_to: New name for the branch
        """
        return git.git_branch(directory, roots, create=create, delete=delete, rename_from=rename_from, rename_to=rename_to)

    @mcp.tool()
    def git_log(directory: str, count: int = 20, file_path: str = "", author: str = "", since: str = "", until: str = "", grep: str = "") -> str:
        """Show commit history with optional filtering.

        Args:
            directory: Absolute path to the git repository root
            count: Maximum number of commits to show (max 200)
            file_path: Only show commits affecting this file
            author: Filter by author name/email
            since: Only show commits after this date (e.g. "2025-01-01", "1 week ago")
            until: Only show commits before this date
            grep: Filter by commit message pattern
        """
        return git.git_log(directory, roots, count=count, file_path=file_path, author=author, since=since, until=until, grep=grep)

    # ================================================================
    # Search Tools  (Phase 2)
    # ================================================================

    @mcp.tool()
    def grep(pattern: str, path: str, ignore_case: bool = False, file_pattern: str = "", max_results: int = 200) -> str:
        """Search for a regex pattern inside files.

        Uses ripgrep (rg) if available, otherwise falls back to Python regex.

        Args:
            pattern: Regex pattern to search for
            path: Directory or file to search in
            ignore_case: If True, perform case-insensitive search
            file_pattern: Glob pattern to filter files (e.g. '*.c', '*.h')
            max_results: Maximum number of matching lines to return
        """
        return search_tools.grep(
            pattern, path, roots,
            ignore_case=ignore_case, file_pattern=file_pattern, max_results=max_results,
        )

    @mcp.tool()
    def find_files(pattern: str, path: str) -> str:
        """Find files matching a glob pattern (recursive).

        Args:
            pattern: Glob pattern, e.g. '*.c', '**/*.h', 'CMakeLists.txt'
            path: Directory to search in
        """
        return search_tools.find_files(pattern, path, roots)

    # ================================================================
    # Serial / UART Tools  (Phase 2)
    # ================================================================

    @mcp.tool()
    def list_serial_ports() -> str:
        """Enumerate available serial ports with descriptions."""
        return serial.list_serial_ports(roots)

    @mcp.tool()
    def serial_open(port: str, baud: int = 115200) -> str:
        """Open a serial connection and return a session ID.

        Args:
            port: Serial port path (e.g. '/dev/ttyUSB0')
            baud: Baud rate (default: 115200)
        """
        return serial.serial_open(port, baud, roots)

    @mcp.tool()
    def serial_read(session_id: str, timeout: float = 5) -> str:
        """Read available output from a serial session.

        Args:
            session_id: Session ID from serial_open
            timeout: Read timeout in seconds (default: 5)
        """
        return serial.serial_read(session_id, timeout=timeout)

    @mcp.tool()
    def serial_write(session_id: str, data: str) -> str:
        """Write data to a serial session.

        Args:
            session_id: Session ID from serial_open
            data: Text data to send
        """
        return serial.serial_write(session_id, data)

    @mcp.tool()
    def serial_close(session_id: str) -> str:
        """Close a serial session.

        Args:
            session_id: Session ID from serial_open
        """
        return serial.serial_close(session_id)

    @mcp.tool()
    def serial_sessions_list() -> str:
        """List all active serial sessions with status."""
        return serial.serial_sessions_list(roots)

    # ================================================================
    # Diagnostics Tools  (Phase 2)
    # ================================================================

    @mcp.tool()
    def get_idf_version(wish_product: str = "") -> str:
        """Get the ESP-IDF version via eim.

        Args:
            wish_product: WISH_PRODUCT value for the eim invocation
        """
        return diag.get_idf_version(
            roots,
            wish_product=wish_product or settings.MCP_WISH_PRODUCT,
            eim_path=settings.MCP_EIM_PATH,
        )

    @mcp.tool()
    def get_project_info(project_dir: str) -> str:
        """Get project metadata: name, target, build dir status, features.

        Args:
            project_dir: Absolute path to the ESP-IDF project
        """
        return diag.get_project_info(project_dir, roots)

    @mcp.tool()
    def get_connected_devices() -> str:
        """List connected USB/serial devices (lsusb, serial ports, /dev/tty*)."""
        return diag.get_connected_devices(roots)

    # ================================================================
    # Session Tools  (Phase 3)
    # ================================================================

    @mcp.tool()
    def create_session(session_id: str, working_dir: str = "") -> str:
        """Create a persistent working session.

        Sessions maintain a working directory that tools like run_command
        and start_process can inherit via the session_id parameter.

        Args:
            session_id: Unique identifier for the session
            working_dir: Optional absolute path to use as default working directory
        """
        result = session_mgr.create_session(session_id, working_dir)
        if 'error' in result:
            return f"Error: {result['error']}"
        
        lines = [
            f"Session: {result['session_id']}",
            f"Status: {result['status']}",
        ]
        if result.get('working_dir'):
            lines.append(f"Working dir: {result['working_dir']}")
        return '\n'.join(lines)

    @mcp.tool()
    def destroy_session(session_id: str) -> str:
        """Destroy a persistent session and clean up resources.

        Args:
            session_id: Session to destroy
        """
        result = session_mgr.destroy_session(session_id)
        if 'error' in result:
            return f"Error: {result['error']}"
        return f"Session {session_id} destroyed"

    @mcp.tool()
    def list_sessions() -> str:
        """List all active sessions with their status."""
        sessions = session_mgr.list_sessions()
        if not sessions:
            return "No active sessions"

        lines = [f"Sessions: {len(sessions)} active\n"]
        lines.append(f"{'ID':<20} {'STATUS':<10} {'WORKING DIR':<40} {'IDLE(s)':>8}")
        lines.append("-" * 80)

        for s in sessions:
            lines.append(
                f"{s['session_id']:<20} {s['status']:<10} "
                f"{s['working_dir']:<40} {s['idle_seconds']:>8}"
            )

        return '\n'.join(lines)

    # ================================================================
    # Phase 4.1: High-Level File Operations
    # ================================================================

    @mcp.tool()
    def replace_text(path: str, search: str, replace: str, replace_all: bool = False) -> str:
        """Find and replace text in a file (single-call read/modify/write).

        Args:
            path: Absolute path to the file
            search: Text to find
            replace: Replacement text
            replace_all: If True, replace all occurrences (default: first only)
        """
        return p4tools.replace_text(path, search, replace, replace_all=replace_all, allowed_roots=roots)

    @mcp.tool()
    def patch_file(path: str, diff: str) -> str:
        """Apply a unified diff to a file.

        Args:
            path: Absolute path to the file to patch
            diff: Unified diff text
        """
        return p4tools.patch_file(path, diff, allowed_roots=roots)

    # ================================================================
    # Phase 4.2: Intelligent UART Monitor
    # ================================================================

    @mcp.tool()
    def monitor_uart(port: str, baud: int = 115200, duration: float = 30, filter_pattern: str = "") -> str:
        """Capture serial output from a UART port with optional filtering.

        Args:
            port: Serial port path (e.g. '/dev/ttyUSB0', '/dev/ttyACM0')
            baud: Baud rate (default: 115200)
            duration: Seconds to capture (max 120)
            filter_pattern: Optional regex - only matching lines returned
        """
        return p4uart.monitor_uart(port, baud, duration, filter_pattern=filter_pattern, allowed_roots=roots)

    @mcp.tool()
    def decode_panic(output: str) -> str:
        """Parse ESP32 panic handler output into structured analysis.

        Extracts PC address, reset reason, backtrace, and known error patterns.

        Args:
            output: Raw serial output text containing a panic dump
        """
        return p4uart.decode_panic(output)

    # ================================================================
    # Phase 4.3: Symbol Indexing
    # ================================================================

    @mcp.tool()
    def find_symbol(name: str, project_path: str) -> str:
        """Locate the definition of a function, variable, or macro.

        Tries ctags first, then clangd, then falls back to regex search.

        Args:
            name: Symbol name to find
            project_path: Absolute path to project root
        """
        return p4sym.find_symbol(name, project_path, allowed_roots=roots)

    @mcp.tool()
    def find_references(symbol: str, project_path: str) -> str:
        """Find all usages of a symbol in a project.

        Args:
            symbol: Symbol name to search for
            project_path: Absolute path to project root
        """
        return p4sym.find_references(symbol, project_path, allowed_roots=roots)

    # ================================================================
    # Phase 4.4: Autonomous Debug Cycle
    # ================================================================

    @mcp.tool()
    def run_debug_cycle(project_path: str, port: str, wish_product: str = "", target: str = "", flash: bool = True, monitor_duration: float = 15, timeout: int = 600) -> str:
        """Run a complete debug cycle: build + flash + monitor + analyze.

        The keystone tool for autonomous firmware development.

        Args:
            project_path: Absolute path to the ESP-IDF project
            port: Serial port for flashing and monitoring
            wish_product: Target hardware product (e.g. 'TargetS3')
            target: Target chip (e.g. 'esp32s3'). Empty = use sdkconfig default.
            flash: If True, flash the firmware (default: True)
            monitor_duration: Seconds of serial capture after flash (default: 15)
            timeout: Maximum seconds for the entire cycle (default: 600)
        """
        return p4debug.run_debug_cycle(
            project_path, port,
            wish_product=wish_product or settings.MCP_WISH_PRODUCT,
            target=target,
            flash=flash,
            monitor_duration=monitor_duration,
            eim_path=settings.MCP_EIM_PATH,
            timeout=timeout,
            allowed_roots=roots,
        )




    # Resources
    # ================================================================

    @mcp.resource("project://status")
    def get_project_status() -> str:
        """Get current project configuration (stub -- returns server status)."""
        import json
        return json.dumps({
            'server': 'esp-workspace-mcp',
            'allowed_roots': roots,
            'wish_product_default': settings.MCP_WISH_PRODUCT,
            'eim_path': settings.MCP_EIM_PATH,
        }, indent=2)

    logger.info(f"ESP-Workspace server created with {len(roots)} allowed root(s)")
    return mcp
