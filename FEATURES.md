# ESP-Workspace MCP Server — Features Reference

Comprehensive reference for all 50 tools and 1 resource implemented across 4 phases.

**Server:** `esp-workspace-mcp` v1.0
**Transport:** SSE over HTTP (port 8765) with Bearer token auth
**Repo:** https://github.com/aircable/ESP-Workspace-MCP-Server-for-Hermes

---

## Architecture

```
Client (Hermes) <--SSE/HTTP--> MCP Server (port 8765)
                                 |
                    +------------+------------+
                    |            |            |
               Tools (50)   Resources (1)  Auth (Bearer)
                    |
        +-----------+-----------+
        |           |           |
    Phase 1-2   Phase 3     Phase 4
    (24 tools)  (16 tools)  (7 tools)
```

All tools return JSON strings. All file paths are sandboxed to allowed roots.
ESP-IDF commands run through `eim run "WISH_PRODUCT=<product> idf.py ..."`.

---

## Phase 1: Core Workspace + ESP-IDF (15 tools)

### Filesystem Tools (8 tools)

| Tool | Description | Key Parameters |
|---|---|---|
| `read_file` | Read text file content with pagination | `path`, `offset` (1-indexed), `limit` |
| `write_file` | Overwrite/create file | `path`, `content` |
| `append_file` | Append to existing file | `path`, `content` |
| `list_dir` | List directory entries with metadata | `path` |
| `create_dir` | Create directory recursively | `path` |
| `delete_path` | Delete file or empty directory | `path` |
| `file_stat` | Get file metadata (size, mtime, perms) | `path` |
| `glob_search` | Find files by glob pattern | `pattern`, `path` |

Security: All paths resolved to absolute, symlink-expanded, validated against `MCP_ALLOWED_ROOTS`. Path traversal (`..`) rejected.

### Shell / Process Tools (6 tools)

| Tool | Description | Key Parameters |
|---|---|---|
| `run_command` | Synchronous command execution | `cmd`, `cwd`, `timeout` (default 30s, max 600s) |
| `start_process` | Start background job | `cmd`, `cwd`, `session_id` |
| `get_job_output` | Read output from background job | `job_id`, `offset` |
| `kill_job` | Terminate background job | `job_id` |
| `list_jobs` | List all jobs (running + recent) | -- |
| `wait_for_job` | Block until job completes | `job_id`, `timeout` |

Output truncated at 50 KB. Environment sanitized (no `LD_PRELOAD`).
Jobs auto-expire after TTL (configurable, default 3600s).

### ESP-IDF Build Tools (7 tools)

All execute via `eim run "WISH_PRODUCT=<product> idf.py <commands>"`.

| Tool | Description | Key Parameters |
|---|---|---|
| `eim_run` | Core ESP-IDF command runner | `commands`, `project_dir`, `wish_product`, `timeout` |
| `build_project` | Build firmware | `project_dir`, `wish_product`, `reconfigure` |
| `set_target` | Set target chip (esp32, esp32s3, etc.) | `project_dir`, `target`, `wish_product` |
| `flash_project` | Flash firmware to device | `project_dir`, `port`, `wish_product` |
| `clean_project` | Clean build artifacts | `project_dir` |
| `fullclean_project` | Remove entire build directory | `project_dir` |
| `reconfigure_project` | Regenerate sdkconfig + CMake cache | `project_dir`, `wish_product` |

Project validation: Checks for `CMakeLists.txt` containing `include($ENV{IDF_PATH}/tools/cmake/project.cmake)`.

---

## Phase 2: Developer Workflow (16 tools)

### Git Tools (5 tools)

Uses GitPython. All operations validated against allowed roots.

| Tool | Description | Key Parameters |
|---|---|---|
| `git_status` | Working tree status (staged, unstaged, untracked) | `directory` |
| `git_diff` | Unstaged diff (or staged with `staged=True`) | `directory`, `staged`, `file_path`, `context_lines` |
| `git_commit` | Stage all and commit | `directory`, `message`, `files` (optional list) |
| `git_branch` | List/create/delete/rename branches | `directory`, `create`, `delete`, `rename_from`, `rename_to` |
| `git_log` | Recent commits with filtering | `directory`, `count`, `file_path`, `author`, `since`, `until`, `grep` |

### Search Tools (2 tools)

Prefers ripgrep (`rg`), falls back to Python regex.

| Tool | Description | Key Parameters |
|---|---|---|
| `grep` | Regex search inside files | `pattern`, `path`, `ignore_case`, `file_pattern`, `max_results` |
| `find_files` | Find files by glob pattern | `pattern`, `path` |

### Serial Tools (6 tools)

Uses pyserial. Session-based connection management.

| Tool | Description | Key Parameters |
|---|---|---|
| `list_serial_ports` | Enumerate available serial ports | -- |
| `serial_open` | Open serial connection | `port`, `baud` (default 115200) |
| `serial_read` | Read available output | `session_id`, `timeout` (default 5s) |
| `serial_write` | Write data to serial | `session_id`, `data` |
| `serial_close` | Close connection | `session_id` |
| `serial_sessions_list` | List active serial sessions | -- |

### Diagnostics Tools (3 tools)

| Tool | Description | Key Parameters |
|---|---|---|
| `get_idf_version` | ESP-IDF version via `eim run "idf.py --version"` | `wish_product` |
| `get_project_info` | Project name, target, build directory | `project_dir` |
| `get_connected_devices` | List USB serial devices | -- |

---

## Phase 3: Persistent Agent Infrastructure (6 tools)

### Enhanced Job Management

| Tool | Description | Key Parameters |
|---|---|---|
| `wait_for_job` | Block until job completes (polls return code) | `job_id`, `timeout` (default 60s, max 300s) |
| `get_job_output` | Enhanced with offset for incremental reads | `job_id`, `offset` (1-indexed) |

### Session Management (3 tools)

In-memory session registry with thread-safe access.

| Tool | Description | Key Parameters |
|---|---|---|
| `create_session` | Create persistent session with working directory | `session_id`, `working_dir` |
| `destroy_session` | Clean up session | `session_id` |
| `list_sessions` | List all active sessions | -- |

### Build Diagnostics (3 tools)

| Tool | Description | Key Parameters |
|---|---|---|
| `parse_build_output` | Parse build log into structured errors/warnings | `output` (raw build text) |
| `idf_size` | Memory usage breakdown via `idf.py size` | `project_dir`, `wish_product` |
| `idf_sdkconfig` | Export full sdkconfig as JSON | `project_dir`, `wish_product` |

`parse_build_output` returns:
```json
{
  "errors": [{"file": "main.c", "line": 42, "severity": "error", "message": "..."}],
  "warnings": [{"file": "main.h", "line": 10, "severity": "warning", "message": "..."}],
  "error_count": 1,
  "warning_count": 1,
  "build_stopped": true
}
```

---

## Phase 4: AI-Native Firmware Automation (7 tools)

### High-Level File Operations (2 tools)

Reduce round-trips: single call instead of read, modify, write.

| Tool | Description | Key Parameters |
|---|---|---|
| `replace_text` | Find-and-replace in file | `path`, `search`, `replace`, `replace_all` |
| `patch_file` | Apply unified diff to file | `path`, `diff` |

### UART Monitor + Panic Analysis (2 tools)

| Tool | Description | Key Parameters |
|---|---|---|
| `monitor_uart` | Capture serial output with optional regex filtering | `port`, `baud`, `duration` (max 120s), `filter_pattern` |
| `decode_panic` | Parse ESP32 panic dump into structured analysis | `output` (raw panic text) |

`decode_panic` extracts: PC address, reset reason, backtrace addresses, and known error patterns (LoadProhibited, StoreProhibited, etc.).

### Symbol Indexing (2 tools)

Tries ctags, clangd, regex fallback.

| Tool | Description | Key Parameters |
|---|---|---|
| `find_symbol` | Locate function/variable/macro definition | `name`, `project_path` |
| `find_references` | Find all usages of a symbol | `symbol`, `project_path` |

### Autonomous Debug Cycle (1 tool)

The keystone tool for autonomous firmware development.

| Tool | Description | Key Parameters |
|---|---|---|
| `run_debug_cycle` | Build + flash + monitor + analyze in one call | `project_path`, `port`, `wish_product`, `target`, `flash`, `monitor_duration`, `timeout` |

Returns structured result:
```json
{
  "build": {"success": true, "errors": [], "warnings": [], "error_count": 0},
  "flash": {"success": true},
  "monitor": {"output": "...", "panic_detected": false},
  "summary": "Cycle complete: build OK, flash OK, no panics detected"
}
```

---

## Resources

| URI | Description |
|---|---|
| `project://status` | Server configuration (allowed roots, default WISH_PRODUCT, eim path) |

---

## Security Controls

| Control | Implementation |
|---|---|
| Filesystem sandbox | All paths validated against `MCP_ALLOWED_ROOTS`, symlink-resolved |
| Path traversal prevention | `..` and symlink escapes rejected |
| Shell timeout | Default 30s, max 600s |
| Output truncation | 50 KB max per response |
| Authentication | Bearer token on every request (except `/health` and `/messages`) |
| Credential safety | Tokens in env vars only, never logged |
| Network binding | Configurable bind address (default: `0.0.0.0`) |

---

## Configuration

Environment variables (or `.env` file):

| Variable | Required | Default | Description |
|---|---|---|---|
| `MCP_API_TOKEN` | Yes | -- | Bearer token for authentication |
| `MCP_ALLOWED_ROOTS` | No | `/home/juergen/AIRcableLLC` | Comma-separated allowed filesystem roots |
| `MCP_HOST` | No | `0.0.0.0` | Bind address |
| `MCP_PORT` | No | `8765` | Listen port |
| `MCP_WISH_PRODUCT` | No | -- | Default WISH_PRODUCT for ESP-IDF builds |
| `MCP_EIM_PATH` | No | `eim` | Path to eim executable |
| `MCP_LOG_LEVEL` | No | `INFO` | Logging level |
| `MCP_JOB_TTL_SECONDS` | No | `3600` | Background job TTL |

---

## Tool Summary (50 total)

| Phase | Category | Count | Tools |
|---|---|---|---|
| 1 | Filesystem | 8 | read_file, write_file, append_file, list_dir, create_dir, delete_path, file_stat, glob_search |
| 1 | Shell/Process | 6 | run_command, start_process, get_job_output, kill_job, list_jobs, wait_for_job |
| 1 | ESP-IDF Build | 7 | eim_run, build_project, set_target, flash_project, clean_project, fullclean_project, reconfigure_project |
| 2 | Git | 5 | git_status, git_diff, git_commit, git_branch, git_log |
| 2 | Search | 2 | grep, find_files |
| 2 | Serial | 6 | list_serial_ports, serial_open, serial_read, serial_write, serial_close, serial_sessions_list |
| 2 | Diagnostics | 3 | get_idf_version, get_project_info, get_connected_devices |
| 3 | Sessions | 3 | create_session, destroy_session, list_sessions |
| 3 | Build Diagnostics | 3 | parse_build_output, idf_size, idf_sdkconfig |
| 4 | File Ops | 2 | replace_text, patch_file |
| 4 | UART/Debug | 2 | monitor_uart, decode_panic |
| 4 | Symbol Indexing | 2 | find_symbol, find_references |
| 4 | Automation | 1 | run_debug_cycle |

---

*Generated: 2026-05-29 | Phases 1-4 complete | 50 tools + 1 resource*
