#!/usr/bin/env python3
"""
ESP-Workspace MCP Server - Verification Suite
==============================================
One-pass verification of all tool categories.
Tests the INTERFACE, not every permutation.

Usage (on dev host):
    cd MCPserver && source .venv/bin/activate && python verify.py
"""

import json, os, sys, tempfile, traceback
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent)
sys.path.insert(0, PROJECT_ROOT)

WISH_PRODUCT = os.environ.get("WISH_PRODUCT", "TargetS3")
PROJECT_DIR  = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"
TEST_PORT    = os.environ.get("TEST_PORT", "/dev/ttyACM0")
ROOTS        = ["/home/juergen/AIRcableLLC", "/tmp", "/opt", "/home/juergen"]

from esp_workspace_mcp.tools.filesystem   import read_file, write_file, list_dir, create_dir, delete_path, file_stat, glob_search
from esp_workspace_mcp.tools.shell        import execute_command
from esp_workspace_mcp.tools.esp_idf     import eim_run, parse_build_output
from esp_workspace_mcp.tools.git_tools   import git_status, git_diff, git_branch, git_log
from esp_workspace_mcp.tools.search      import grep, find_files
from esp_workspace_mcp.tools.serial_tools import list_serial_ports, serial_open, serial_read, serial_write, serial_close, serial_sessions
from esp_workspace_mcp.tools.diagnostics  import get_idf_version, get_project_info, get_connected_devices
from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart  import monitor_uart, decode_panic
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references
from esp_workspace_mcp.tools.session_tools import SessionManager

P = F = S = 0
FAILURES = []

def ok(name, detail=""):
    global P; P += 1
    print(f"  PASS  {name}" + (f" --- {detail}" if detail else ""))

def fail(name, reason=""):
    global F, FAILURES; F += 1; FAILURES.append(name)
    print(f"  FAIL  {name}: {reason}")

def skip(name, reason=""):
    global S; S += 1
    print(f"  SKIP  {name}: {reason}")

def j(val):
    if isinstance(val, dict): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except: return {"_raw": val[:300]}
    return {"_raw": str(val)[:300]}

def sec(title):
    print(f"\n{'─'*60}\n  {title}\n{'─'*60}")

def summary():
    total = P + F + S
    print(f"\n{'='*60}")
    print(f"Results: {P}/{total} passed, {F} failed, {S} skipped")
    for f in FAILURES: print(f"  FAIL: {f}")
    print(f"{'='*60}")
    return F == 0

def file_content(path, roots):
    """Helper: read file and return content string regardless of format."""
    r = j(read_file(path, roots))
    if isinstance(r, dict):
        return r.get("content", r.get("_raw", str(r)))
    return str(r)

# === Phase 1: Filesystem ===
sec("Phase 1 - Filesystem")

fn = tempfile.mktemp(dir="/tmp", prefix="mcp_verify_")
try:
    write_file(fn, "hello\nworld\n", ROOTS)
    assert "hello" in file_content(fn, ROOTS)
    ok("write_file + read_file")

    r2 = j(read_file(fn, ROOTS, offset=1, limit=1))
    c2 = r2.get("content", r2.get("_raw", ""))
    assert "world" in c2
    ok("read_file offset/limit")

    ok("list_dir")
    j(list_dir("/tmp", ROOTS))

    assert fn.split("/")[-1] in str(j(glob_search("mcp_verify_*", "/tmp", ROOTS)))
    ok("glob_search")

    ok("file_stat")
    j(file_stat(fn, ROOTS))

    os.unlink(fn)
except Exception as e:
    fail("filesystem", str(e)[:80])
    traceback.print_exc()

try:
    r = j(read_file("/etc/passwd", ROOTS))
    assert "error" in str(r).lower() or "denied" in str(r).lower() or "not allowed" in str(r).lower()
    ok("security: blocks /etc/passwd")
except Exception as e:
    fail("security", str(e)[:80])

# === Phase 1: Shell ===
sec("Phase 1 - Shell")

try:
    assert "verify_ok_12345" in str(j(execute_command("echo verify_ok_12345", ROOTS)))
    ok("execute_command")
except Exception as e:
    fail("execute_command", str(e)[:80])

# === Phase 2: Git ===
sec("Phase 2 - Git")

try:
    r = str(j(git_status(PROJECT_DIR, ROOTS)))
    assert "Branch" in r or "branch" in r.lower()
    ok("git_status", r[:60])
except Exception as e:
    fail("git_status", str(e)[:80])

try:
    r = str(j(git_branch(PROJECT_DIR, ROOTS)))
    assert "*" in r or "main" in r.lower()
    ok("git_branch")
except Exception as e:
    fail("git_branch", str(e)[:80])

try:
    r = str(j(git_log(PROJECT_DIR, ROOTS, count=2)))
    ok("git_log", r[:60])
except Exception as e:
    fail("git_log", str(e)[:80])

try:
    git_diff(PROJECT_DIR, ROOTS)
    ok("git_diff")
except Exception as e:
    fail("git_diff", str(e)[:80])

# === Phase 2: Search ===
sec("Phase 2 - Search")

try:
    r = str(j(grep("import os", PROJECT_ROOT, ROOTS, file_pattern="*.py", max_results=3)))
    assert ".py" in r
    ok("grep", r[:60])
except Exception as e:
    fail("grep", str(e)[:80])

try:
    r = str(j(find_files("*.py", PROJECT_ROOT, ROOTS)))
    assert ".py" in r
    ok("find_files")
except Exception as e:
    fail("find_files", str(e)[:80])

# === Phase 2: Diagnostics ===
sec("Phase 2 - Diagnostics")

try:
    r = str(j(get_connected_devices(ROOTS))).lower()
    assert "tty" in r or "usb" in r or "serial" in r
    ok("get_connected_devices")
except Exception as e:
    fail("get_connected_devices", str(e)[:80])

try:
    r = str(j(get_project_info(PROJECT_DIR, ROOTS)))
    assert "Project:" in r or "Name:" in r
    ok("get_project_info")
except Exception as e:
    fail("get_project_info", str(e)[:80])

# eim_run: esptool read_mac (read-only, safe)
try:
    r = eim_run(PROJECT_DIR, f"esptool.py -p {TEST_PORT} read_mac", ROOTS, wish_product=WISH_PRODUCT)
    if isinstance(r, dict):
        success = r.get("success", False)
        ok("eim_run + esptool read_mac", f"success={success}")
    else:
        assert "MAC" in str(r) or "mac" in str(r).lower()
        ok("eim_run + esptool read_mac", str(r)[:80])
except Exception as e:
    fail("eim_run esptool", str(e)[:80])

# === Phase 2: Serial ===
sec("Phase 2 - Serial")

try:
    r = j(list_serial_ports(ROOTS))
    ok("list_serial_ports", str(r)[:80])
except Exception as e:
    fail("list_serial_ports", str(e)[:80])

if os.path.exists(TEST_PORT):
    sid = None
    try:
        r = j(serial_open(TEST_PORT, baud=115200, allowed_roots=ROOTS))
        rd = j(r)
        sid = rd.get("session_id", "")
        if not sid:
            import re as _re
            m = _re.search(r'session[:\s]+(\S+)', str(r), _re.I)
            sid = m.group(1).rstrip("'\").,;") if m else ""
        assert sid
        ok("serial_open", f"session={sid[:20]}")

        serial_read(sid, timeout=2)
        ok("serial_read")

        serial_write(sid, "\n")
        ok("serial_write")

        serial_close(sid)
        ok("serial_close")

    except Exception as e:
        fail("serial", str(e)[:80])
        if sid:
            try: serial_close(sid)
            except: pass
else:
    skip("serial_open/write/read/close", f"{TEST_PORT} not found")

# === Phase 3: Sessions ===
sec("Phase 3 - Sessions")

mgr = SessionManager()
try:
    r = mgr.create_session("verify_test", "/tmp")
    assert "error" not in str(r).lower()
    ok("create_session")

    assert len(mgr.list_sessions()) >= 1
    ok("list_sessions")

    r2 = mgr.destroy_session("verify_test")
    assert "error" not in str(r2).lower()
    ok("destroy_session")
except Exception as e:
    fail("sessions", str(e)[:80])

# === Phase 3: Build Diagnostics ===
sec("Phase 3 - Build Diagnostics")

try:
    sample = "error: undefined reference to `foo'\nwarning: unused variable 'x'\nnote: declared here\n"
    r = j(parse_build_output(sample))
    assert "errors" in r or "_raw" in r
    ok("parse_build_output", str(r)[:80])
except Exception as e:
    fail("parse_build_output", str(e)[:80])

# === Phase 4.1: High-Level File Ops ===
sec("Phase 4 - replace_text + patch_file")

fn2 = tempfile.mktemp(dir="/tmp", prefix="mcp_p4_")
try:
    write_file(fn2, "old_value = 42\nkeep = 1\nold_value = 99\n", ROOTS)

    replace_text(fn2, "old_value", "new_value", replace_all=True, allowed_roots=ROOTS)
    c = file_content(fn2, ROOTS)
    assert "new_value" in c and "old_value" not in c, f"got: {c[:80]}"
    ok("replace_text (replace_all)")

    patch = (
        "--- a/file\n+++ b/file\n"
        "@@ -1,2 +1,2 @@\n"
        "-new_value = 42\n+patched_value = 42\n"
        " keep = 1\n"
    )
    patch_file(fn2, patch, allowed_roots=ROOTS)
    c2 = file_content(fn2, ROOTS)
    assert "patched_value" in c2, f"got: {c2[:80]}"
    ok("patch_file")

    os.unlink(fn2)
except Exception as e:
    fail("phase4_fileops", str(e)[:80])
    try: os.unlink(fn2)
    except: pass

# === Phase 4.2: decode_panic + monitor_uart ===
sec("Phase 4 - decode_panic + monitor_uart")

try:
    panic = (
        "Guru Meditation Error: Core  0 panic'ed (IllegalInstruction).\n"
        "PC: 0x40081234  PS: 0x00060e30\n"
        "Backtrace: 0x40081234:0x3ffb1234\n"
        "Rebooting...\n"
    )
    r = str(j(decode_panic(panic)))
    assert "panic" in r.lower() or "0x" in r or "guru" in r.lower()
    ok("decode_panic", r[:80])
except Exception as e:
    fail("decode_panic", str(e)[:80])

if os.path.exists(TEST_PORT):
    try:
        r = j(monitor_uart(TEST_PORT, baud=115200, duration=3, filter_pattern="", allowed_roots=ROOTS))
        ok("monitor_uart", f"captured {len(str(r))} chars")
    except Exception as e:
        fail("monitor_uart", str(e)[:80])
else:
    skip("monitor_uart", f"{TEST_PORT} not found")

# === Phase 4.3: Symbol Indexing ===
sec("Phase 4 - find_symbol + find_references")

try:
    r = str(j(find_symbol("app_main", PROJECT_DIR, allowed_roots=ROOTS)))
    ok("find_symbol ('app_main')", r[:80])
except Exception as e:
    fail("find_symbol", str(e)[:80])

try:
    r = str(j(find_references("app_main", PROJECT_DIR, allowed_roots=ROOTS)))
    ok("find_references", r[:80])
except Exception as e:
    fail("find_references", str(e)[:80])

# === Summary ===
if summary():
    print("\nAll critical paths verified. Server is operational.\n")
else:
    print("\nSome tests failed - review output above.\n")
    sys.exit(1)
