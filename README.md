# ESP-Workspace MCP

A full autonomous embedded firmware workspace server — the MCP (Model Context Protocol) infrastructure layer for AI agents working with ESP-IDF projects.

## What it does

ESP-Workspace MCP turns an AI coding assistant into an autonomous firmware engineer. It provides tools for:

- **Filesystem operations** — read, write, list, glob with path sandboxing
- **Shell execution** — run commands with timeout, background jobs, output capture
- **ESP-IDF build system** — build, flash, clean, reconfigure via `eim run` with `WISH_PRODUCT` support
- **Security** — Bearer token auth, path traversal prevention, configurable filesystem roots

## Quick Start

### Prerequisites

- Python 3.10+
- [Espressif Install Manager (`eim`](https://github.com/espressif/esp-idf-installer) — handles ESP-IDF installation and environment setup

### Installation

```bash
pip install esp-workspace-mcp
```

Or from source:

```bash
git clone https://github.com/AIRcableLLC/esp-workspace-mcp.git
cd esp-workspace-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configuration

Create a `.env` file:

```env
MCP_API_TOKEN=your-secret-token-here
MCP_HOST=0.0.0.0
MCP_PORT=8765
MCP_ALLOWED_ROOTS=/home/user/projects
MCP_WISH_PRODUCT=TargetS3
MCP_EIM_PATH=eim
```

Or set environment variables directly.

### Run the server

```bash
# SSE mode (default, for network access)
python run_server.py

# Stdio mode (for local MCP clients)
python run_server.py --stdio
```

The server exposes:
- `GET /sse` — SSE connection endpoint (requires Bearer token)
- `POST /messages` — MCP message endpoint
- `GET /health` — health check (no auth required)

## MCP Tools

### Filesystem Tools

| Tool | Description |
|---|---|
| `read_file(path, offset, limit)` | Read text file with pagination |
| `write_file(path, content)` | Write content to a file |
| `append_file(path, content)` | Append to an existing file |
| `list_dir(path)` | List directory entries |
| `create_dir(path)` | Create directory recursively |
| `delete_path(path)` | Delete file or empty directory |
| `file_stat(path)` | Get file/directory metadata |
| `glob_search(pattern, path)` | Find files by glob pattern |

### Shell Tools

| Tool | Description |
|---|---|
| `run_command(cmd, cwd, timeout)` | Execute command and wait |
| `start_process(cmd, cwd)` | Start background job |
| `get_job_output(job_id, offset)` | Read job output |
| `kill_job(job_id)` | Terminate background job |
| `list_jobs()` | List all jobs |

### ESP-IDF Tools

All ESP-IDF operations are invoked through `eim run "WISH_PRODUCT=<product> idf.py ..."` which handles environment setup automatically.

| Tool | Description |
|---|---|
| `eim_run(commands, project_dir, wish_product)` | Run any `idf.py` command via `eim` |
| `build_project(project_dir, wish_product, reconfigure)` | Build an ESP-IDF project |
| `set_target(project_dir, target, wish_product)` | Set target chip (esp32, esp32s3, etc.) |
| `flash_project(project_dir, port, wish_product)` | Flash firmware to device |
| `clean_project(project_dir)` | Clean build artifacts |
| `fullclean_project(project_dir)` | Remove entire build directory |
| `reconfigure_project(project_dir, wish_product)` | Regenerate sdkconfig + CMake cache |

### Build Step Decision Tree

```
Is sdkconfig missing or have defaults changed?
├── YES → eim_run("reconfigure build", project_dir, wish_product)
└── NO  → eim_run("build", project_dir, wish_product)
```

## Security

| Control | Implementation |
|---|---|
| Filesystem sandbox | All paths validated against `MCP_ALLOWED_ROOTS` |
| Path traversal prevention | Symlink-resolved, `..` escapes rejected |
| Shell timeout | Configurable, default 30s, max 300s |
| Output truncation | 50 KB max per response |
| Authentication | Bearer token on every request |
| Credential safety | Tokens in env vars only, never logged |

## Integration with AI Agents

### Hermes

```bash
hermes mcp add esp-workspace \
  --url http://host:port/sse \
  --header "Authorization: Bearer your-token"
```

### Generic MCP Client

Any MCP-compatible client can connect to the SSE endpoint. The server implements the standard MCP protocol over SSE/HTTP transport.

## Architecture

```
esp_workspace_mcp/
├── config.py          # Settings from env, fail-fast validation
├── server.py          # FastMCP server, tool registration
├── auth.py            # Bearer token middleware
├── tools/
│   ├── filesystem.py  # 8 path-validated file operations
│   ├── shell.py       # Command execution + background jobs
│   └── esp_idf.py     # eim-run wrapper, build/flash/clean
├── utils/
│   ├── security.py    # Path sandboxing, symlink resolution
│   └── process.py     # Subprocess management, JobManager
└── resources/
    └── project.py     # MCP resources (project status, etc.)
```

## License

Apache-2.0
