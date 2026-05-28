# esp-workspace-mcp

## Goal

Extend Espressif's ESP-IDF MCP server into a full autonomous embedded firmware workspace server.

The server should support:

- ESP-IDF project operations
- Filesystem operations
- Shell execution
- Search and grep
- Git integration
- Serial/UART interaction
- Multi-project workspaces
- Network-accessible MCP transport
- Authentication and sandboxing

This server is intended to become the infrastructure layer for autonomous firmware agents such as Hermes.

---

# Architecture Overview

```text
Hermes Agent
    ↓
MCP over SSE/HTTP
    ↓
esp-workspace-mcp
    ├── Filesystem tools
    ├── Shell tools
    ├── Git tools
    ├── ESP-IDF tools
    ├── Serial monitor
    └── Workspace/project management
    ↓
ESP-IDF projects + hardware

Project Layout
esp-workspace-mcp/
├── pyproject.toml
├── README.md
├── requirements.txt
├── .env.example
├── run_server.py
│
├── esp_workspace_mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── auth.py
│   ├── config.py
│   ├── models.py
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── filesystem.py
│   │   ├── shell.py
│   │   ├── git_tools.py
│   │   ├── search.py
│   │   ├── serial_tools.py
│   │   ├── esp_idf.py
│   │   └── diagnostics.py
│   │
│   ├── resources/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── build.py
│   │   └── git_status.py
│   │
│   ├── transports/
│   │   ├── __init__.py
│   │   ├── sse.py
│   │   └── stdio.py
│   │
│   └── utils/
│       ├── process.py
│       ├── security.py
│       ├── paths.py
│       └── logging.py
│
├── examples/
│   ├── hermes_mcp_config.json
│   └── curl_examples.md
│
└── tests/
    ├── test_filesystem.py
    ├── test_shell.py
    ├── test_git.py
    └── test_esp_idf.py


Recommended Dependencies
requirements.txt
mcp
fastapi
uvicorn
pydantic
gitpython
pyserial
python-dotenv


Core Tool Categories


1. Filesystem Tools
Initial tools
read_file(path)
write_file(path, content)
append_file(path, content)
list_dir(path)
make_dir(path)
delete_file(path)
stat(path)
glob(pattern)

Future tools
replace_text(path, search, replace)
patch_file(path, diff)
copy_file(src, dst)
move_file(src, dst)

2. Shell / Process Tools
Initial tools

run_command(cmd, cwd=None)
start_process(cmd)
get_process_output(pid)
kill_process(pid)

Important implementation requirements
subprocess timeout
cwd restrictions
output truncation
background process tracking
safe environment handling

3. Search Tools
Initial tools
grep(pattern, path)
find_files(pattern, path)

Prefer using ripgrep (rg) if installed.

4. Git Tools
Initial tools
git_status(path)
git_diff(path)
git_commit(path, message)
git_branch(path)
git_log(path)

Future tools
git_checkout(branch)
git_create_branch(name)
git_restore(file)
git_stage(file)

5. ESP-IDF Tools

Reuse and extend Espressif's existing MCP implementation.

Existing tools
build_project()
set_target(target)
flash_project(port=None)
clean_project()

Planned additions
idf_monitor()
idf_size()
idf_menuconfig()
idf_fullclean()
idf_sdkconfig()
idf_partition_table()
idf_openocd()

6. Serial / UART Tools
Planned tools
list_serial_ports()
open_serial_monitor(port)
read_serial_output()
write_serial_input()


Security Model

This server has remote execution capabilities.

Security is mandatory.

Filesystem sandboxing

Restrict access to allowed roots only.

Example:

ALLOWED_ROOTS = [
    "/home/juergen/AIRcableLLC",
]

All filesystem and shell paths must be validated.


Network restrictions

Restrict access by firewall or bind address.

Example:

Allow:
192.168.1.75

Deny:
All others
Authentication

Require Bearer token authentication.

Example:

Authorization: Bearer YOUR_SECRET_TOKEN

Environment variable:

MCP_API_TOKEN=...

Recommended Transport
SSE / HTTP

Example:

mcp.run(
    transport="sse",
    host="0.0.0.0",
    port=8765,
)
Hermes Integration
Add MCP server
hermes mcp add esp-workspace \
  --url http://192.168.1.220:8765/sse


Example Server Skeleton
server.py
from fastmcp import FastMCP

mcp = FastMCP("ESP Workspace")

register_filesystem_tools(mcp)
register_shell_tools(mcp)
register_git_tools(mcp)
register_esp_idf_tools(mcp)

mcp.run(
    transport="sse",
    host="0.0.0.0",
    port=8765,
)

Development Phases

Phase 1

Minimal autonomous build environment.

Implement:

filesystem
shell
build
flash

Phase 2

Developer workflow support.

Implement:

git
grep
serial monitor
diagnostics

Phase 3

Persistent autonomous agent infrastructure.

Implement:

background jobs
persistent sessions
monitor parsing
structured diagnostics

Phase 4

Advanced AI-native firmware automation.

Implement:

compiler error parsing
symbol indexing
UART panic decoding
autonomous debug loops
continuous firmware iteration
Important Design Principle

The AI agent should use:

fewer tools
higher-level semantic operations
deterministic workflows

Prefer:

replace_text_in_file()

instead of:

open_file()
seek()
write()
close()


Long-Term Goal

Create an autonomous firmware engineering platform capable of:

edit
→ build
→ flash
→ monitor
→ analyze
→ retry
→ optimize

without human intervention.

Key Principle
Hermes should think.
MCP should act.

This separation provides:

robustness
maintainability
composability
autonomy


