# esp-workspace-mcp — Implementation Plan

## Project Goal

Extend Espressif's ESP-IDF MCP server into a **full autonomous embedded firmware workspace server** — the infrastructure layer for autonomous firmware agents like Hermes.

The server will support: ESP-IDF project operations (via Espressif Install Manager / `eim`), filesystem access, shell execution, search, git integration, serial/UART interaction, multi-project workspaces, network-accessible MCP transport (SSE/HTTP), and authentication with filesystem sandboxing.

**Key Design Principle:** Hermes thinks. MCP acts. Keep tools deterministic and high-level so the AI agent reasons with fewer, semantic operations.

---

## Current State

The `MCPserver/` directory contains:

| File | Description |
|---|---|
| `mcp_server.md` | Full architecture spec and requirements |
| `mcp_ext.py` (279 LOC) | ESP-IDF stdio-only MCP extension (build, flash, clean, set_target) — serves as reference/blueprint |

---

## Build Environment: Espressif Install Manager (EIM)

All ESP-IDF tools are invoked through the **Espressif Install Manager** (`eim`), not by sourcing `export.sh` manually. This handles environment setup automatically.

### Invocation Pattern

```bash
# Basic project build
eim run "WISH_PRODUCT=TargetS3 idf.py build"

# Full cycle example (fullclean + reconfigure + build + flash + monitor)
eim run "WISH_PRODUCT=TargetS3 idf.py fullclean reconfigure build flash monitor"
```

### Key Concepts

- **`WISH_PRODUCT`** — Environment variable that selects the target hardware configuration. Must be set in every `eim run` invocation. Examples: `TargetS3`, `TargetC6`, etc. This variable drives sdkconfig generation and component selection.
- **`eim run "..."`** — Wraps any command with the proper ESP-IDF environment (IDF_PATH, PATH, etc.). Equivalent to sourcing `export.sh` but works consistently regardless of shell state.
- **`reconfigure`** — Regenerates sdkconfig from defaults + `sdkconfig.defaults` / project configuration files. Only needed when configuration changes (new defaults file, changed `WISH_PRODUCT`, or toggled menuconfig options). Skippable on regular incremental builds.

### Build Step Decision Tree

```
Is sdkconfig missing or have defaults changed?
├── YES → eim run "WISH_PRODUCT=<product> idf.py reconfigure build"
└── NO  → eim run "WISH_PRODUCT=<product> idf.py build"
```

### ESP-IDF Tool `idf.py` Commands Used

| Command | Purpose | When to Use |
|---|---|---|
| `fullclean` | Remove entire build directory | After CMake/sdkconfig changes, before reconfigure |
| `reconfigure` | Regenerate sdkconfig + CMake cache | After config changes or `WISH_PRODUCT` changes |
| `build` | Compile and link firmware | Every code change |
| `set-target <chip>` | Set target chip (esp32, esp32s3, etc.) | Once per project (persisted in sdkconfig) |
| `flash [-p PORT]` | Write firmware to device | After successful build |
| `monitor` | Open serial monitor | After flash |
| `size` | Show memory usage | Diagnostics |
| `menuconfig` | Interactive config editor | Manual config changes only |

---

## Phase 1: Minimal Autonomous Build Environment

**Objective:** Stand up a network-accessible MCP server with filesystem, shell, build, and flash capabilities. This is the MVP that enables Hermes to edit → build → flash without human intervention.

### 1.1 — Project Scaffolding

Create the full project skeleton:

```
esp-workspace-mcp/
├── pyproject.toml
├── README.md
├── requirements.txt
├── .env.example
├── run_server.py
├── esp_workspace_mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── auth.py
│   ├── config.py
│   ├── models.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── filesystem.py
│   │   ├── shell.py
│   │   ├── esp_idf.py
│   │   ├── git_tools.py
│   │   ├── search.py
│   │   ├── serial_tools.py
│   │   └── diagnostics.py
│   ├── resources/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── build.py
│   │   └── git_status.py
│   ├── transports/
│   │   ├── __init__.py
│   │   ├── sse.py
│   │   └── stdio.py
│   └── utils/
│       ├── __init__.py
│       ├── process.py
│       ├── security.py
│       ├── paths.py
│       └── logging.py
├── examples/
│   ├── hermes_mcp_config.json
│   └── curl_examples.md
└── tests/
    ├── conftest.py
    ├── test_filesystem.py
    ├── test_shell.py
    ├── test_git.py
    ├── test_esp_idf.py
    └── test_security.py
```

**Dependencies (requirements.txt):**

```
mcp>=1.0
fastapi>=0.115
uvicorn>=0.34
pydantic>=2.0
gitpython>=3.1
pyserial>=3.5
python-dotenv>=1.0
```

### 1.2 — Configuration (`config.py`)

Load and validate environment at startup:

- `MCP_API_TOKEN` — Bearer token for authentication (required)
- `MCP_ALLOWED_ROOTS` — comma-separated allowed filesystem roots (default: `/home/juergen/AIRcableLLC`)
- `MCP_HOST` — bind address (default: `0.0.0.0`)
- `MCP_PORT` — listen port (default: `8765`)
- `MCP_LOG_LEVEL` — logging level (default: `INFO`)
- `MCP_WISH_PRODUCT` — default `WISH_PRODUCT` value for ESP-IDF builds (required for ESP-IDF tools; can be overridden per-call)
- `MCP_IDF_PATH` — path to ESP-IDF installation (optional; `eim` handles env setup)
- `MCP_EIM_PATH` — full path to `eim` executable (default: auto-detect from PATH)

Fail fast on missing required config.

### 1.3 — Security Module (`utils/security.py`)

Implement path sandboxing — **this is critical since the server has remote execution capability:**

- `is_path_allowed(path, allowed_roots)` — resolves symlinks, rejects `..` traversal, verifies path is under an allowed root
- `validate_cwd(cwd, allowed_roots)` — validates working directory for shell commands
- `sanitize_env(env)` — strips dangerous environment variables

**Test cases:**

- `/home/juergen/AIRcableLLC/project/main.c` → allowed
- `/etc/passwd` → rejected
- `/home/juergen/AIRcableLLC/../../etc/shadow` → rejected (resolved path escapes root)

### 1.4 — Path Utilities (`utils/paths.py`)

- `safe_resolve(path, allowed_roots)` — resolve to absolute path, check against roots
- `list_safe_dir(path, allowed_roots)` — list entries with metadata (name, type, size, modified)

### 1.5 — Filesystem Tools (`tools/filesystem.py`)

Core file operations, all path-validated:

| Tool | Description |
|---|---|
| `read_file(path)` | Read text file, return content with line count |
| `write_file(path, content)` | Overwrite file, create parent dirs if needed |
| `append_file(path, content)` | Append to existing file |
| `list_dir(path)` | List directory entries |
| `create_dir(path)` | Create directory (recursive) |
| `delete_path(path)` | Delete file or empty directory |
| `file_stat(path)` | Return file metadata (size, mtime, permissions) |
| `glob_search(pattern, path)` | Find files by glob pattern |

### 1.6 — Shell / Process Tools (`tools/shell.py`)

Safe command execution:

| Tool | Description |
|---|---|
| `run_command(cmd, cwd, timeout=30)` | Execute command, return stdout+stderr |
| `start_process(cmd, cwd)` | Start background job, return `job_id` |
| `get_job_output(job_id)` | Read output from background job |
| `kill_job(job_id)` | Terminate background job |
| `list_jobs()` | List running/recent jobs |

Requirements:

- `cwd` validated against allowed roots
- Subprocess timeout enforced
- Output truncated at 50 KB
- Environment sanitized (no `LD_PRELOAD`, etc.)
- Completed jobs auto-cleaned after TTL

### 1.7 — ESP-IDF Tools (`tools/esp_idf.py`)

All IDF commands invoked via `eim run "WISH_PRODUCT=<product> idf.py ..."`.

Port the pattern from `mcp_ext.py`, extending with validation, the `eim` wrapper, `WISH_PRODUCT` support, and `reconfigure`.

| Tool | Description |
|---|---|
| `eim_run(project_dir, commands, wish_product)` | Core runner: `eim run "WISH_PRODUCT=<wish> idf.py <commands>"`. All other ESP-IDF tools call this. |
| `build_project(project_dir, wish_product, reconfigure=False)` | Run `eim run "WISH_PRODUCT=<w> idf.py [reconfigure] build"`. Pass `reconfigure=True` when sdkconfig/defaults changed. |
| `set_target(project_dir, target)` | Run `eim run "idf.py set-target <target>"` (target is persisted in sdkconfig, only needed once per project). |
| `flash_project(project_dir, port, wish_product)` | Run `eim run "WISH_PRODUCT=<w> idf.py flash [-p <port>]"`. |
| `clean_project(project_dir)` | Run `eim run "idf.py clean"`. |
| `fullclean_project(project_dir)` | Run `eim run "idf.py fullclean"`. |
| `reconfigure_project(project_dir, wish_product)` | Run `eim run "WISH_PRODUCT=<w> idf.py reconfigure"`. |

Each tool:

- Validates `project_dir` is a valid ESP-IDF project (has `CMakeLists.txt` with `include($ENV{IDF_PATH}/tools/cmake/project.cmake)`)
- Validates path against allowed roots
- Captures and truncates output (50 KB max)
- Returns structured result: `{success: bool, output: str, return_code: int}`
- The `wish_product` parameter passed through to the `WISH_PRODUCT` env var in the `eim` invocation

#### `eim_run` Implementation Details

```python
def eim_run(project_dir: str, commands: str, wish_product: str = None) -> dict:
    """
    Run ESP-IDF command via eim.
    
    Args:
        project_dir: Absolute path to the ESP-IDF project
        commands: idf.py arguments, e.g. "fullclean reconfigure build"
        wish_product: WISH_PRODUCT value (e.g. "TargetS3")
    
    Returns:
        {"success": bool, "output": str, "return_code": int}
    
    Example:
        eim_run("/path/to/project", "reconfigure build", "TargetS3")
        # Executes: eim run "WISH_PRODUCT=TargetS3 idf.py reconfigure build"
    """
    env = os.environ.copy()
    idf_py_cmd = f"idf.py {commands}"
    
    if wish_product:
        idf_py_cmd = f"WISH_PRODUCT={wish_product} {idf_py_cmd}"
    
    cmd = ["eim", "run", idf_py_cmd]
    # ... subprocess with cwd=project_dir, timeout, capture output
```

#### Project Validation

Uses improved version of `mcp_ext.py`'s `is_valid_project_dir()`:

```python
IDF_CMAKE_SIGNATURES = [
    r'include($ENV{IDF_PATH}/tools/cmake/project.cmake)',
    r'include($ENV{IDF_PATH}/tools/cmakev2/idf.cmake)',
]

def is_valid_project_dir(directory: str) -> bool:
    root = Path(directory)
    if not root.is_dir():
        return False
    cmakelists = root / 'CMakeLists.txt'
    if not cmakelists.is_file():
        return False
    try:
        content = cmakelists.read_text(encoding='utf-8')
        return any(sig in content for sig in IDF_CMAKE_SIGNATURES)
    except Exception:
        return False
```

### 1.8 — SSE Transport + Auth

- FastMCP with SSE transport via uvicorn
- Bearer token middleware: checks `Authorization: Bearer ***` header, returns 401 on failure
- CORS configured for Hermes origin
- Configurable bind host/port

### 1.9 — Entry Point (`run_server.py`)

Load .env, create FastMCP instance, register all tool modules, start server.

### Phase 1 Verification Checklist

- [ ] Server starts and responds on configured port
- [ ] Auth required: requests without token get 401, with token get tools list
- [ ] `read_file` and `write_file` work for allowed paths
- [ ] Path traversal attempts blocked (return error, not content)
- [ ] `run_command` with timeout works
- [ ] `build_project` work on an ESP-IDF project via `eim run` with `WISH_PRODUCT`
- [ ] `reconfigure_project` regenerates sdkconfig when config changes
- [ ] Output truncated for large responses

---

## Phase 2: Developer Workflow Support

**Objective:** Add git, search, serial/UART, and diagnostics — the tools needed for a complete compile-flash-debug cycle.

### 2.1 — Git Tools (`tools/git_tools.py`)

| Tool | Description |
|---|---|
| `git_status(project_path)` | Working tree status |
| `git_diff(project_path)` | Unstaged diff |
| `git_commit(project_path, message)` | Stage all and commit |
| `git_branch(project_path)` | List branches, mark current |
| `git_log(project_path, count=10)` | Recent commits |

All paths validated. Uses gitpython library. Future additions: `git_checkout`, `git_create_branch`, `git_restore`, `git_stage`.

### 2.2 — Search Tools (`tools/search.py`)

| Tool | Description |
|---|---|
| `grep(pattern, path, ignore_case=False)` | Regex search inside files |
| `find_files(pattern, path)` | Find files by glob pattern |

Prefer ripgrep (`rg`) if available, fall back to Python regex. Output truncated, result count limited.

### 2.3 — Serial / UART Tools (`tools/serial_tools.py`)

| Tool | Description |
|---|---|
| `list_serial_ports()` | Enumerate available serial ports |
| `serial_open(port, baud=115200)` | Open serial connection, return `session_id` |
| `serial_read(session_id, timeout=5)` | Read available output |
| `serial_write(session_id, data)` | Write data to serial |
| `serial_close(session_id)` | Close connection |
| `serial_sessions()` | List active serial sessions |

Session registry tracks open connections. Uses pyserial.

### 2.4 — Diagnostics Tools (`tools/diagnostics.py`)

| Tool | Description |
|---|---|
| `get_idf_version(wish_product?)` | Return ESP-IDF version via `eim run "idf.py --version"` |
| `get_project_info(project_path)` | Project name, target, build dir |
| `get_connected_devices()` | List USB serial devices |

### Phase 2 Verification Checklist

- [ ] Git operations work on a test repository
- [ ] `grep` finds patterns, `find_files` locates files by glob
- [ ] Serial ports are listed, open/read/write/close works
- [ ] Diagnostics return expected info

---

## Phase 3: Persistent Autonomous Agent Infrastructure

**Objective:** Enable long-running background operations and structured diagnostics for autonomous iteration loops.

### 3.1 — Background Job Management

Enhance shell tools with persistent job tracking:

| Tool | Description |
|---|---|
| `list_jobs()` | All jobs (running + recent, with status) |
| `get_job_output(job_id, offset=0)` | Read output from any offset |
| `cancel_job(job_id)` | Terminate a running job |
| `wait_for_job(job_id, timeout)` | Block until job completes |

Auto-cleanup of completed jobs (TTL: 1 hour, configurable).

### 3.2 — Persistent Sessions

Allow Hermes to maintain working context across tool calls:

| Tool | Description |
|---|---|
| `create_session(label, working_dir)` | Create persistent session with cwd |
| `destroy_session(session_id)` | Clean up session |
| `list_sessions()` | List active sessions |

All tools accept optional `session_id` to inherit working directory and context.

### 3.3 — Structured Build Diagnostics

| Tool | Description |
|---|---|
| `parse_build_output(project_path)` | Parse build log into structured errors/warnings |
| `idf_size(project_dir, wish_product)` | Run `eim run "WISH_PRODUCT=<w> idf.py size"`, return memory usage breakdown |
| `idf_fullclean(project_dir)` | Run `eim run "idf.py fullclean"` |
| `idf_sdkconfig(project_dir, wish_product)` | Run `eim run "WISH_PRODUCT=<w> idf.py sdkconfig"` |

Build parser output format:

```json
{
  "errors": [{"file": "...", "line": 42, "message": "..."}],
  "warnings": [{"file": "...", "line": 10, "message": "..."}],
  "summary": "Build failed with 2 errors, 1 warning"
}
```

### Phase 3 Verification Checklist

- [ ] Background jobs persist, output retrievable by offset
- [ ] Sessions maintain working directory across tool calls
- [ ] Build output parser correctly extracts errors and warnings

---

## Phase 4: Advanced AI-Native Firmware Automation

**Objective:** High-level semantic tools that enable the full autonomous edit → build → flash → monitor → analyze → retry → optimize loop.

### 4.1 — High-Level File Operations

| Tool | Description |
|---|---|
| `replace_text(path, search, replace, replace_all=False)` | Find-and-replace in file |
| `patch_file(path, diff)` | Apply a unified diff to a file |

These reduce round-trips: one call instead of read → modify → write.

### 4.2 — Intelligent UART Monitor

| Tool | Description |
|---|---|
| `monitor_uart(port, baud, duration=30, filter_pattern=None)` | Capture serial output with filtering |
| `decode_panic(output)` | Parse ESP32 panic dump into structured analysis |

Panic decoder extracts: PC address, reset reason, backtrace, and known error patterns.

### 4.3 — Symbol Indexing

| Tool | Description |
|---|---|
| `find_symbol(name, project_path)` | Locate function/variable definition |
| `find_references(symbol, project_path)` | Find all usages of a symbol |

Uses `ctags`/`clangd` if available, falls back to regex-based search.

### 4.4 — Autonomous Debug Cycle

The keystone tool that enables full autonomy:

| Tool | Description |
|---|---|
| `run_debug_cycle(project_path, port, wish_product, target=None)` | Build + flash + monitor + analyze |

Returns structured result:

```json
{
  "build": {"success": false, "errors": [...], "warnings": [...]},
  "flash": {"success": true},
  "monitor": {"output": "...", "panic_detected": true, "panic_analysis": {...}},
  "summary": "Build failed: undefined reference to `my_function` in main.c:42"
}
```

### Phase 4 Verification Checklist

- [ ] `replace_text` correctly modifies files
- [ ] `monitor_uart` captures serial output; panic decoder handles ESP32 panic dumps
- [ ] `run_debug_cycle` completes a full cycle and returns structured results

---

## Security Hardening Summary

| Control | Implementation |
|---|---|
| Filesystem sandbox | All paths validated against `ALLOWED_ROOTS`, symlink-resolved |
| Path traversal prevention | `..` and symlink escapes rejected |
| Shell timeout | Configurable, default 30s, max 300s |
| Output truncation | 50 KB max per response |
| Authentication | Bearer token on every request |
| Network binding | Configurable bind address (default: `0.0.0.0`) |
| Credential safety | Tokens in env vars only, never logged |
| Firewall | Restrict to trusted IPs (e.g., `192.168.1.75`) |

---

## Hermes Integration

Add the server to Hermes MCP configuration:

```bash
hermes mcp add esp-workspace \
  --url http://192.168.1.220:8765/sse \
  --header "Authorization: Bearer ***"
```

Once connected, Hermes can autonomously edit firmware, build, flash, monitor serial, parse errors, and iterate — no human in the loop.

---

## Long-Term Vision

The end goal is a fully autonomous firmware engineering platform:

```
edit → build → flash → monitor → analyze → retry → optimize
```

Each phase above brings us closer to this goal. Hermes handles reasoning and planning; the MCP server handles deterministic execution.

---

*Plan created: 2026-05-27 | Last updated: 2026-05-27*
