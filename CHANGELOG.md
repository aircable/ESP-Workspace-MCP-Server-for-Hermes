# CHANGELOG.md — ESP-Workspace MCP Server

## TL;DR (git commit message)

```
Phase 5: Category-based tool architecture, ClosedResourceError fix, tool call logging, new file ops, TOML config, CLI subcommands, OpenMV stub

- Add plug-in category system (CategoryRegistry + ToolCategory ABC) with config-driven enable/disable
- Suppress noisy uvicorn access logs; add TOOL/DONE/FAIL logging for every tool call
- Catch ClosedResourceError in POST /messages → return 410 Gone instead of 500
- Add copy_file, copy_dir, move_path, read_file_base64, write_file_base64 tools
- Add create_session, destroy_session, list_sessions tools
- Add async JobManager with start_process, get_job_output, kill_job, list_jobs
- Replace .env-only config with TOML config.toml + CLI (configure/init/start)
- Add OpenMV category stub (4 tools) showing how to extend the category system
- Fix _register_legacy_tools to handle missing gitpython/pyserial gracefully
- Fix read_file offset bug (1-indexed vs 0-indexed slicing) in legacy filesystem.py
- Version bump to 1.1.0
```

---

## [1.1.0] — 2026-06-08

### Added — Category Architecture

New `esp_workspace_mcp/categories/` directory with a plug-in system for organizing tools into domain-specific groups. Categories can be enabled/disabled via `config.toml`:

- **`esp_workspace_mcp/categories/__init__.py`** — `CategoryRegistry` class with `register()`, `get()`, `list_categories()`, `load_all()`. Auto-discovers category modules via `importlib`.
- **`esp_workspace_mcp/categories/base.py`** — `ToolCategory` abstract base class. Each category declares `NAME`, `DESCRIPTION`, `TOOLS` metadata and implements `register(mcp, config)`.
- **`esp_workspace_mcp/categories/filesystem.py`** — Full filesystem category with 13 tools (see below).
- **`esp_workspace_mcp/categories/openmv.py`** — Stub category with 4 example tools (`openmv_list_scripts`, `openmv_run`, `openmv_capture`, `openmv_list_devices`) demonstrating how to add a new domain.
- **`esp_workspace_mcp/categories/config.example.toml`** — Example TOML showing all configuration sections and category enablement.

### Added — New Filesystem Tools (in categories/filesystem.py)

| Tool | Description |
|---|---|
| `copy_file` | Copy a file with path sandboxing on both source and destination |
| `copy_dir` | Recursive directory copy with file/dir count reporting |
| `move_path` | Move or rename files and directories |
| `read_file_base64` | Read any file (including binary), return base64-encoded content |
| `write_file_base64` | Write base64-encoded binary content to a file |

### Added — Core Tools (in server.py `_register_core_tools()`)

| Tool | Description |
|---|---|
| `run_command` | Execute shell command with timeout, async subprocess |
| `start_process` | Start background process, returns job ID |
| `get_job_output` | Read job stdout with 1-indexed offset pagination |
| `kill_job` | Terminate a running background job |
| `list_jobs` | List all background jobs with status |
| `create_session` | Create named persistent working session with directory |
| `destroy_session` | Destroy a named session |
| `list_sessions` | List all active sessions with age info |

### Changed — run_server.py (SSE Entry Point)

- **Raw ASGI handlers**: `/sse` and `/messages` handled by raw ASGI functions instead of Starlette `request_response` wrapper. Fixes `AssertionError` from double `http.response.start` when `EventSourceResponse` and Starlette both send the HTTP response.
- **ClosedResourceError handling**: `messages_asgi_handler` catches `ClosedResourceError` and returns HTTP 410 Gone instead of 500 crash when client disconnects.
- **Auth inlined**: Bearer token check moved inline in `sse_asgi_handler` instead of ASGI middleware (middleware incompatible with raw ASGI handlers).
- **Access log suppressed**: `uvicorn.access` logger set to WARNING; `access_log=False` in `uvicorn.run()`.
- **Dual-method /sse handler**: GET establishes SSE stream; POST handles StreamableHTTP with session_id.
- **Dual-path routing**: `/messages` handled separately from `/sse` for standard MCP SSE clients.

### Changed — server.py (Core Server)

- **Category-driven loading**: `create_server()` checks `config.categories.enabled` list. If specified, loads only those categories. If categories module available but no enabled list, loads all registered categories. Falls back to legacy flat tool import if categories unavailable.
- **Tool call logging via monkey-patch**: `mcp.tool()` wrapped at startup to log `TOOL: name(args)`, `DONE: name`, or `FAIL: name: error` via `esp_workspace_mcp.tools` logger.
- **Async JobManager**: New class using `asyncio.create_subprocess_shell` instead of threaded `subprocess.Popen`. Supports start, poll, read_output, kill, list_jobs.
- **SessionManager**: New class for persistent working sessions (create/destroy/list).
- **`_to_dict()`**: Helper converting flat `MCPSettings` attributes to nested config dict for category consumption.
- **`_register_legacy_tools()`**: Fixed to use `importlib.import_module` with per-module `ImportError` handling (won't crash if `gitpython` or `pyserial` missing).

### Fixed — Critical Bugs

- **`ClosedResourceError`** (run_server.py): POST /messages with expired/disconnected session now returns 410 Gone instead of unhandled 500 exception crashing the ASGI handler.
- **`read_file` offset** (tools/filesystem.py): Fixed 1-indexed vs 0-indexed slicing. `offset=1` now correctly returns from line 1 (was incorrectly skipping to line 2).
- **Starlette AssertionError** (run_server.py): Fixed by using raw ASGI handlers for SSE/streaming endpoints instead of Starlette's `request_response` wrapper that conflicts with `EventSourceResponse`.
- **Missing gitpython/pyserial** (server.py): Server no longer crashes at import time if these optional packages are absent. Legacy tools depending on them are skipped with a warning.

### Added — cli.py (CLI Subcommands)

| Command | Description |
|---|---|
| `esp-workspace-mcp configure` | Interactive wizard — generates token, sets allowed roots, outputs Hermes config snippet |
| `esp-workspace-mcp init` | Non-interactive config generation with random token |
| `esp-workspace-mcp start` | Start server from TOML config (exports env vars, execs run_server.py) |
| `esp_workspace_mcp/__main__.py` | Enables `python -m esp_workspace_mcp start` |

### Changed — pyproject.toml

- Version bumped to `0.5.0`
- Entry points added: `esp-workspace-mcp`, `esp-workspace-mcp-configure`, `esp-workspace-mcp-init`
- Project URLs for GitHub repo and issues

### Preserved — Legacy Tools (backward compatible)

All original tool files in `esp_workspace_mcp/tools/` are preserved unchanged for backward compatibility:

| File | Tools |
|---|---|
| `filesystem.py` | read_file, write_file, append_file, list_dir, create_dir, delete_path, file_stat, glob_search |
| `shell.py` | run_command, start_process, kill_job |
| `esp_idf.py` | eim_run, build_project, flash_project, set_target, clean_project, fullclean_project, reconfigure_project, idf_size, idf_sdkconfig |
| `git_tools.py` | git_status, git_diff, git_commit, git_branch, git_log |
| `search.py` | grep, find_files |
| `serial_tools.py` | list_serial_ports, serial_open, serial_read, serial_write, serial_close, serial_sessions_list |
| `diagnostics.py` | get_project_info, get_connected_devices |
| `session_tools.py` | (legacy session helpers) |
| `phase4_tools.py` | replace_text, patch_file |
| `phase4_uart.py` | monitor_uart, decode_panic |
| `phase4_symbols.py` | find_symbol, find_references |
| `phase4_debug.py` | run_debug_cycle |

Legacy tools are loaded automatically when the categories module is not present or when no categories are enabled in config.

### Preserved — Supporting Modules

- **`esp_workspace_mcp/auth.py`** — `AuthMiddleware`, `BearerAuthMiddleware`, `create_api_key_middleware`
- **`esp_workspace_mcp/config.py`** — `MCPSettings` (pydantic-settings), `load_settings()`
- **`esp_workspace_mcp/utils/security.py`** — `safe_resolve()`, `is_path_allowed()`, `validate_cwd()`, `sanitize_env()`, `list_safe_dir()`
- **`esp_workspace_mcp/utils/process.py`** — `run_subprocess()`, threaded `JobManager`
- **`esp_workspace_mcp/resources/`** — Stub resources (build, git_status, project)
- **`esp_workspace_mcp/transports/__init__.py`** — Transport layer stub
- **`esp_workspace_mcp/server_new.py`** — Alternative server implementation (kept for reference)
- **`esp_workspace_mcp/verify_imports.py`** — Import verification utility

### Documentation

- **`FEATURES.md`** — Complete rewrite with category architecture diagrams, per-category tool tables (50+ tools), TOML config examples, deployment instructions, test coverage matrix
- **`README.md`** — Updated architecture section, category enablement instructions
- **`mcp_server.md`** — Unchanged (original design notes)

---

## [0.4.0] — 2026-06-03

### Summary

- 50 tools across filesystem, shell, ESP-IDF, git, search, serial, diagnostics, sessions, AI-native
- SSE transport over HTTP via Starlette/uvicorn
- Bearer token authentication
- Path sandboxing against configurable allowed roots
- ESP-IDF integration via eim (Espressif Install Manager)
- Session management, background job tracking
- Build output parsing, panic decoding, UART monitoring, symbol indexing

---

## Migration Notes

### From v0.4.x to v0.5.0

1. **No action required if using .env only**: Server falls back to legacy tool loading when categories module is unavailable. Existing `.env` files work unchanged.

2. **To enable categories**: Create `~/.config/esp-workspace/config.toml`:
   ```toml
   [server]
   host = "0.0.0.0"
   port = 8765
   log_level = "INFO"
   name = "esp-workspace"

   [auth]
   token = "your-secret-token"

   [filesystem]
   allowed_roots = ["/home/user/projects"]

   [categories]
   enabled = ["filesystem", "openmv"]
   ```

3. **Missing packages**: `gitpython` and `pyserial` are optional. The server skips git/serial tools if those packages aren't installed.
