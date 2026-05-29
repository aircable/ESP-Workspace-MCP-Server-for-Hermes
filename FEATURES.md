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
All filesystem tools validate paths against configured allowed roots (`/home/juergen/AIRcableLLC`). Symlink resolution and path traversal prevention enforced. Requests to paths outside roots (e.g. `/etc/passwd`) are rejected.

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

### Detected Devices (example)
```
/dev/ttyACM0  USB JTAG/serial debug unit  [VID:PID=303A:1001]
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

## High-Level File Operations (Phase 4)

| Tool | Description |
|---|---|
| `replace_text` | Find-and-replace in a file (single call, returns diff preview) |
| `patch_file` | Apply a unified diff to a file |

---

## Symbol Indexing (Phase 4)

| Tool | Description |
|---|---|
| `find_symbol` | Locate function/variable/macro definition (tries ctags, clangd, then regex) |
| `find_references` | Find all usages of a symbol in a project |

---

## Debug Cycle (Phase 4)

| Tool | Description |
|---|---|
| `run_debug_cycle` | Build + flash + monitor + analyze in one call. Set `flash=False` for build-only. |

Returns structured JSON with build results, flash status, captured serial output, and panic analysis.

---

## Architecture

```
Client (Hermes)  <--SSE/HTTP-->  MCP Server (port 8765)
                                    |
                                    +-- Bearer auth middleware
                                    +-- Starlette ASGI (sse + messages routing)
                                    +-- FastMCP tool registry
                                    |
                                    +-- Filesystem tools   (sandboxed paths)
                                    +-- Shell tools        (subprocess + job manager)
                                    +-- Git tools          (gitpython)
                                    +-- Search tools       (ripgrep fallback)
                                    +-- Serial tools       (pyserial)
                                    +-- ESP-IDF tools      (via eim)
                                    +-- Diagnostics        (project parsing)
                                    +-- Sessions           (working dir context)
                                    +-- High-level ops     (replace, patch)
                                    +-- Symbol indexing    (ctags/clangd/regex)
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

---

## Test Coverage

Two test files exist:

- **test_final.py** — 33 unit/integration tests covering all tool functions directly
- **test_esp_integration.py** — 22 integration tests exercising real ESP-IDF, hardware, and eim

Both run on the dev host with:
```bash
cd MCPserver
.venv/bin/python test_final.py
.venv/bin/python test_esp_integration.py
```

---

*Auto-generated from PLAN.md and source code review, 2026-05-29*
