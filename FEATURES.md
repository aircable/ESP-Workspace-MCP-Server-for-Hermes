# ESP-Workspace MCP Server — Features Reference

All tools available through the `esp-workspace` MCP server, organized by capability.

---

## Filesystem Tools

| Tool | Description |
|---|---|
| `read_file` | Read a text file with offset/limit pagination |
| `write_file` | Write content to a file (creates parent dirs) |
| `append_file` | Append content to an existing file |
| `list_dir` | List directory entries with type and size |
| `create_dir` | Create a directory recursively |
| `delete_path` | Delete a file or empty directory |
| `file_stat` | Get file/directory metadata (size, permissions, mtime) |
| `glob_search` | Find files matching a glob pattern (recursive) |

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
                                                      +-- FastMCP tool registry (50 tools)
                                                      |
                                                      +-- Filesystem tools   (sandboxed paths)
                                                      +-- Shell tools        (subprocess + job manager)
                                                      +-- Git tools          (gitpython)
                                                      +-- Search tools       (ripgrep fallback)
                                                      +-- Serial tools       (pyserial)
                                                      +-- ESP-IDF tools      (via eim)
                                                      +-- Diagnostics        (project parsing, panic decoder)
                                                      +-- Sessions           (working dir context)
                                                      +-- High-level ops     (replace_text, patch_file)
                                                      +-- Symbol indexing    (ctags/clangd/regex)
                                                      +-- UART monitor       (capture + filter)
                                                      +-- Debug cycle        (build+flash+monitor)
```

---

## Configuration

Server settings via environment variables or `.env` file:

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
| `MCP_OUTPUT_LIMIT` | `10000` | Max output lines |

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

SSH was only used during development for file deployment. The MCP server itself communicates via SSE/HTTP and has no SSH dependencies.

---

*Generated from source code review and test verification, 2026-05-29*
