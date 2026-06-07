# ESP-Workspace MCP Server — Features Reference

All tools available through the `esp-workspace` MCP server, organized by capability.

## Architecture: Tool Categories

Tools are organized into **plug-in categories** that can be enabled or disabled via configuration. This keeps the token context clean — an OpenMV developer doesn't need ESP-IDF flash tools, and vice versa.

```
esp_workspace_mcp/categories/
├── __init__.py          # CategoryRegistry — auto-discovers categories
├── base.py              # ToolCategory ABC
├── filesystem.py        # read_file, write_file, copy_file, list_dir, etc.
├── shell.py             # run_command, start_process, jobs
├── git.py               # git_status, git_commit, git_branch, etc.
├── esp_idf.py           # build_project, flash_project, idf_size, etc.
├── serial.py            # serial_open, serial_read, serial_write, etc.
├── diagnostics.py       # get_project_info, get_connected_devices
├── sessions.py          # create_session, destroy_session, list_sessions
├── ai_native.py         # decode_panic, monitor_uart, run_debug_cycle, find_symbol
└── openmv.py            # OpenMV camera development (stub — enable when needed)
```

### Enabling Categories

In `~/.config/esp-workspace/config.toml`:
```toml
[categories]
enabled = ["filesystem", "shell", "git", "esp_idf", "serial"]
# "openmv" not listed = not loaded = invisible to LLM
```

Adding a new category (e.g. OpenMV): create `categories/openmv.py` and add `"openmv"` to the enabled list. No other files change.

---

## Filesystem Tools

| Tool | Description |
|---|---|
| `read_file` | Read a text file with 1-indexed offset/limit pagination |
| `read_file_base64` | Read a file and return base64-encoded content (for binary files) |
| `write_file` | Write content to a file (creates parent dirs) |
| `write_file_base64` | Write base64-encoded content to a file (for binary files) |
| `append_file` | Append content to an existing file |
| `list_dir` | List directory entries with type and size |
| `create_dir` | Create a directory recursively |
| `delete_path` | Delete a file or empty directory |
| `file_stat` | Get file/directory metadata (size, permissions, mtime) |
| `glob_search` | Find files matching a glob pattern (recursive) |
| `copy_file` | Copy a file (source and destination must be within allowed roots) |
| `copy_dir` | Copy a directory recursively |
| `move_path` | Move/rename a file or directory |

### Security
All filesystem tools validate paths against configured allowed roots (`/home/juergen/...`). Symlink resolution and path traversal prevention enforced. Requests to paths outside roots (e.g. `/etc/passwd`) are rejected.

---

## Shell & Process Tools

| Tool | Description |
|---|---|
| `run_command` | Execute a shell command and wait for completion |
| `start_process` | Start a background process, return job ID |
| `get_job_output` | Get output from a job (supports offset/limit for incremental reads) |
| `kill_job` | Terminate a running background job |
| `list_jobs` | List all background jobs with status |
| `wait_for_job` | Block until a job completes (with timeout) |

---

## Search Tools

| Tool | Description |
|---|---|
| `grep` | Regex search inside files (tries `rg` first, falls back to Python regex) |
| `find_files` | Find files by glob pattern (recursive) |

---

## Git Tools

| Tool | Description |
|---|---|
| `git_status` | Show working tree status |
| `git_diff` | Show staged/unstaged changes |
| `git_commit` | Stage and commit changes |
| `git_branch` | List/create/delete branches |
| `git_log` | Show commit history (with filtering) |

Uses gitpython. All operations are sandboxed to allowed roots.

---

## Serial / UART Tools

| Tool | Description |
|---|---|
| `list_serial_ports` | List all detected serial ports (USB, TTY, pyserial) |
| `serial_open` | Open a serial connection, return session handle |
| `serial_read` | Read lines from an open serial session |
| `serial_write` | Write data to an open serial session |
| `serial_close` | Close a serial session |
| `serial_sessions_list` | List all open serial sessions |
| `monitor_uart` | Capture serial output for a duration with optional regex filtering |

### Connected Device
```
/dev/ttyACM0  USB JTAG/serial debug unit  [VID:PID=303A:1001]  TargetS3
```

---

## ESP-IDF Tools

| Tool | Description |
|---|---|
| `eim_run` | Run any command via Espressif Install Manager (`eim run "..."`) |
| `build_project` | Build an ESP-IDF project (`idf.py build`) |
| `set_target` | Set target chip (`idf.py set-target esp32s3`) |
| `flash_project` | Flash firmware to device (`idf.py flash -p PORT`) |
| `clean_project` | Clean build artifacts (preserves sdkconfig) |
| `fullclean_project` | Remove entire build directory |
| `reconfigure_project` | Regenerate sdkconfig and CMake cache |
| `idf_size` | Memory usage breakdown (`idf.py size`) |
| `idf_sdkconfig` | Export sdkconfig as JSON |
| `get_idf_version` | Get ESP-IDF version string |
| `get_project_info` | Parse project metadata (name, target, features, build status) |

### Build Invocation Pattern
```
eim run "WISH_PRODUCT=<product> idf.py <command>"
```
Example: `eim run "WISH_PRODUCT=TargetS3 idf.py build"`

---

## Diagnostics Tools

| Tool | Description |
|---|---|
| `get_connected_devices` | Enumerate USB devices (lsusb), serial ports (pyserial), and TTY devices |
| `get_idf_version` | ESP-IDF version check |
| `get_project_info` | Project metadata extractor |
| `parse_build_output` | Parse build output into structured errors/warnings JSON |
| `decode_panic` | Parse ESP32 panic handler output into structured analysis |

### Panic Decoder Patterns
Recognizes: `GDBStub`, `abort`, `IllegalInstruction`, `LoadProhibited`, `StoreProhibited`, `StackCanary`, `BrownOut`, `TaskWDT`, `IntWdt`, `CacheError`, `MemoryAllocation`, `assert`

---

## Session Tools

| Tool | Description |
|---|---|
| `create_session` | Create a named session with working directory |
| `destroy_session` | Destroy a session |
| `list_sessions` | List all active sessions |

Sessions maintain working directory context for multi-step operations.

---

## High-Level File Operations (Phase 4.1)

| Tool | Description |
|---|---|
| `replace_text` | Find-and-replace in a file (single call, returns diff preview) |
| `patch_file` | Apply a unified diff to a file |

---

## Intelligent UART Monitor (Phase 4.2)

| Tool | Description |
|---|---|
| `monitor_uart` | Capture serial output for N seconds with optional regex filter |
| `decode_panic` | Parse panic output — extracts PC, backtrace, reset reason, pattern match |

---

## Symbol Indexing (Phase 4.3)

| Tool | Description |
|---|---|
| `find_symbol` | Locate function/variable/macro definition (tries ctags, clangd, then regex) |
| `find_references` | Find all usages of a symbol in a project |

---

## Autonomous Debug Cycle (Phase 4.4)

| Tool | Description |
|---|---|
| `run_debug_cycle` | Build + flash + monitor + analyze in one call. Set `flash=False` for build-only. |

Returns structured JSON with build results, flash status, captured serial output, and panic analysis.

---

## Architecture

```
Client (Hermes/any MCP client)  <--SSE/HTTP-->  MCP Server (port 8765)
                                                      |
                                                      +-- Bearer auth middleware
                                                      +-- Starlette ASGI routing
                                                      +-- FastMCP tool registry
                                                      |
                                                      +-- CategoryRegistry (plug-in system)
                                                      |     |
                                                      |     +-- filesystem   (13 tools)
                                                      |     +-- shell        (5 tools)
                                                      |     +-- git          (5 tools)
                                                      |     +-- search       (2 tools)
                                                      |     +-- serial       (6 tools)
                                                      |     +-- esp_idf      (10 tools)
                                                      |     +-- diagnostics  (3 tools)
                                                      |     +-- sessions     (3 tools)
                                                      |     +-- ai_native    (5 tools)
                                                      |     +-- openmv       (4 tools, stub)
                                                      |
                                                      +-- Legacy fallback (tools/ directory)
                                                            Used when categories/ is not available
```

### Category Loading

At startup, `server.py` checks for the `categories/` directory:
- **With categories**: Only enabled categories are loaded (config-driven)
- **Without categories**: Falls back to legacy flat tool loading from `tools/` directory
- **Mixed**: Categories take precedence; legacy tools fill gaps

This means the server works with OR WITHOUT the category system — backward compatible.

---

## Configuration

Server settings via environment variables, `.env` file, or `config.toml`:

### Environment Variables (.env)

| Variable | Default | Description |
|---|---|---|
| `MCP_API_TOKEN` | (required) | Bearer token for authentication |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8765` | Listen port |
| `MCP_ALLOWED_ROOTS` | (required) | Comma-separated allowed filesystem roots |
| `MCP_WISH_PRODUCT` | `""` | Default WISH_PRODUCT for builds |
| `MCP_EIM_PATH` | `eim` | Path to eim executable |
| `MCP_LOG_LEVEL` | `INFO` | Logging level |
| `MCP_JOB_TTL_SECONDS` | `3600` | Job manager TTL |
| `MCP_MAX_TIMEOUT` | `300` | Max command timeout |
| `MCP_OUTPUT_LIMIT` | `51200` | Max output (50 KB) |

### TOML Configuration (categories)

`~/.config/esp-workspace/config.toml`:
```toml
[server]
name = "esp-workspace"
host = "0.0.0.0"
port = 8765
log_level = "INFO"

[auth]
token = "your-secret-token"

[filesystem]
allowed_roots = ["/home/juergen/AIRcableLLC"]

[esp_idf]
wish_product = "TargetS3"
eim_path = "eim"

[shell]
default_timeout = 30
max_timeout = 300
output_limit = 51200

[jobs]
ttl_seconds = 3600

[categories]
enabled = ["filesystem", "shell", "git", "esp_idf", "serial", "diagnostics", "sessions", "ai_native"]
# "openmv" not listed = not loaded
```

---

## Test Coverage

Three test suites exist:

- **test_final.py** — 33 unit/integration tests covering all tool functions directly
- **test_mcp_server.py** — 50 comprehensive tests across 8 groups: server registration, filesystem, git, Phase 4 tools, serial, ESP-IDF, diagnostics, search, and live ESP device
- **test_esp_integration.py** — 22 integration tests exercising real ESP-IDF, hardware, and eim

All tests pass (105 tests, 100% pass rate). Run on the dev host with:
```bash
cd MCPserver
.venv/bin/python test_final.py
.venv/bin/python test_mcp_server.py
.venv/bin/python test_esp_integration.py
```

### Test Groups (test_mcp_server.py)

| Group | Tests | Coverage |
|---|---|---|
| Server & Registration | 8 | Server creation, 50 tools registered, all 7 Phase 4 tools |
| Filesystem & Security | 11 | CRUD ops, path traversal blocking, symlink safety |
| Git (read-only) | 4 | status, diff, log, branch |
| Phase 4 Tools | 12 | replace_text, patch_file, decode_panic (4 types), find_symbol, find_references |
| Serial | 2 | Port listing, ESP device detection |
| ESP-IDF & Diagnostics | 6 | version, project info, sdkconfig, build parser, devices |
| Search | 2 | grep, find_files |
| ESP Device | 2 | Device presence, 2-second UART monitor capture |

---

## Deployment

The MCP server runs standalone. No SSH is required for normal operation.

```bash
# Start server
python run_server.py                   # SSE mode on port 8765
python run_server.py --stdio           # Stdio mode (for local clients)

# With custom config
python run_server.py --port 9000 --env-file /path/to/.env
```

### PyPI Installation

```bash
pip install esp-workspace-mcp
esp-workspace-mcp configure    # Interactive setup
esp-workspace-mcp start        # Start the server
```

---

*Generated from source code review and test verification, 2026-05-29*
