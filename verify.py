#!/usr/bin/env python3
"""
ESP-Workspace MCP Server — Verification Suite
==============================================
One-pass verification of all tool categories.
Tests the INTERFACE, not every permutation.
One success per tool proves the path works.

Usage (on dev host):
    cd MCPserver && source .venv/bin/activate && python verify.py

Tools NOT tested here (infrastructure, owned by others):
    - esptool / idf.py (tested via eim_run wrapper)
    - pyserial internals (tested via serial_open/read)
    - git internals (tested via git_status wrapper)
"""

import json, os, sys, tempfile, shutil, time, traceback
from pathlib import Path

# ── Setup ────────────────────────────────────────────────────
PROJECT_ROOT = str(Path(__file__).parent)
sys.path.insert(0, PROJECT_ROOT)

WISH_PRODUCT = os.environ.get("WISH_PRODUCT", "TargetS3")
PROJECT_DIR  = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"
TEST_PORT    = os.environ.get("TEST_PORT", "/dev/ttyACM0")
ROOTS        = ["/home/juergen/AIRcableLLC", "/tmp", "/opt", "/home/juergen"]

# ── Imports (all tool modules) ──────────────────────────────
from esp_workspace_mcp.tools.filesystem   import read_file, write_file, list_dir, create_dir, delete_path, file_stat, glob_search
from esp_workspace_mcp.tools.shell        import execute_command
from esp_workspace_mcp.tools.esp_idf     import eim_run, build_project, set_target, flash_project, clean_project, fullclean_project, reconfigure_project, parse_build_output, idf_size, idf_sdkconfig
from esp_workspace_mcp.tools.git_tools    import git_status, git_diff, git_branch, git_log, git_commit
from esp_workspace_mcp.tools.search       import grep, find_files
from esp_workspace_mcp.tools.serial_tools import list_serial_ports, serial_open, serial_read, serial_write, serial_close, serial_sessions_list
from esp_workspace_mcp.tools.diagnostics  import get_idf_version, get_project_info, get_connected_devices
from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart  import monitor_uart, decode_panic
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references
from esp_workspace_mcp.tools.phase4_debug import run_debug_cycle
from esp_workspace_mcp.tools.session_tools import SessionManager

# ── Test harness ─────────────────────────────────────────────
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
    for f in FAILURES:
        print(f"  FAIL: {f}")
    print(f"{'='*60}")
    return F == 0

# ══════════════════════════════════════════════════════════════
# VERIFICATION TESTS
# ══════════════════════════════════════════════════════════════

# ── Phase 1: Filesystem (spot-check) ────────────────────────
sec("Phase 1 — Filesystem (spot-check)")

fn = tempfile.mktemp(dir="/tmp", prefix="mcp_verify_")
try:
    write_file(fn, "hello\nworld\n", ROOTS)
    r = j(read_file(fn, ROOTS))
    c = r.get("content", r.get("_raw", ""))
    assert "hello" in c, f"got: {c[:50]}"
    ok("write_file + read_file")

    r2 = j(read_file(fn, ROOTS, offset=1, limit=1))
    c2 = r2.get("content", r2.get("_raw", ""))
    assert "world" in c2, f"offset got: {c2[:50]}"
    ok("read_file offset/limit")

    r3 = j(list_dir("/tmp", ROOTS))
    assert "entries" in r3 or "_raw" in r3
    ok("list_dir")

    r4 = j(glob_search("mcp_verify_*", "/tmp", ROOTS))
    assert fn.split("/")[-1] in str(r4)
    ok("glob_search")

    r5 = j(file_stat(fn, ROOTS))
    assert "size" in str(r5).lower()
    ok("file_stat")

    os.unlink(fn)
except Exception as e:
    fail("filesystem", str(e)[:80])
    traceback.print_exc()

# Security: path outside roots
try:
    r = j(read_file("/etc/passwd", ROOTS))
    s = str(r).lower()
    assert "error" in s or "denied" in s or "not allowed" in s
    ok("security: blocks /etc/passwd")
except Exception as e:
    fail("security", str(e)[:80])

# ── Phase 1: Shell ─────────────────────────────────────────
sec("Phase 1 — Shell")

try:
    r = j(execute_command("echo verify_ok_12345", ROOTS))
    assert "verify_ok_12345" in str(r)
    ok("execute_command")
except Exception as e:
    fail("execute_command", str(e)[:80])

# ── Phase 2: Git ────────────────────────────────────────────
sec("Phase 2 — Git")

try:
    r = j(git_status(PROJECT_DIR, ROOTS))
    assert "Branch" in str(r) or "branch" in str(r).lower()
    ok("git_status", str(r)[:60])
except Exception as e:
    fail("git_status", str(e)[:80])

try:
    r = j(git_branch(PROJECT_DIR, ROOTS))
    assert "*" in str(r) or "main" in str(r).lower()
    ok("git_branch")
except Exception as e:
    fail("git_branch", str(e)[:80])

try:
    r = j(git_log(PROJECT_DIR, ROOTS, count=2))
    assert "commit" in str(r).lower() or "author" in str(r).lower()
    ok("git_log")
except Exception as e:
    fail("git_log", str(e)[:80])

try:
    r = j(git_diff(PROJECT_DIR, ROOTS))
    ok("git_diff", "clean" if not str(r).strip() else "has changes")
except Exception as e:
    fail("git_diff", str(e)[:80])

# ── Phase 2: Search ────────────────────────────────────────
sec("Phase 2 — Search")

try:
    r = j(grep("import os", PROJECT_ROOT, ROOTS, file_pattern="*.py", max_results=3))
    assert ".py" in str(r)
    ok("grep", str(r)[:60])
except Exception as e:
    fail("grep", str(e)[:80])

try:
    r = j(find_files("*.py", PROJECT_ROOT, ROOTS))
    assert ".py" in str(r)
    ok("find_files")
except Exception as e:
    fail("find_files", str(e)[:80])

# ── Phase 2: Diagnostics ───────────────────────────────────
sec("Phase 2 — Diagnostics")

try:
    r = j(get_connected_devices(ROOTS))
    s = str(r).lower()
    assert "tty" in s or "usb" in s or "serial" in s
    ok("get_connected_devices", str(r)[:80])
except Exception as e:
    fail("get_connected_devices", str(e)[:80])

try:
    r = j(get_project_info(PROJECT_DIR, ROOTS))
    assert "Project:" in str(r) or "Name:" in str(r)
    ok("get_project_info", str(r)[:80])
except Exception as e:
    fail("get_project_info", str(e)[:80])

# eim_run: use esptool read_mac (read-only, safe)
try:
    r = j(eim_run(PROJECT_DIR, f"esptool.py -p {TEST_PORT} read_mac", ROOTS, wish_product=WISH_PRODUCT))
    output = r.get("output", "") if isinstance(r, dict) else str(r)
    assert "MAC" in output or "mac" in output.lower()
    ok("eim_run + esptool read_mac", output[:80])
except Exception as e:
    fail("eim_run esptool", str(e)[:80])

# ── Phase 2: Serial ────────────────────────────────────────
sec("Phase 2 — Serial")

try:
    r = j(list_serial_ports())
    ok("list_serial_ports", str(r)[:80])
except Exception as e:
    fail("list_serial_ports", str(e)[:80])

if os.path.exists(TEST_PORT):
    sid = None
    try:
        r = j(serial_open(TEST_PORT, baud=115200))
        import re as _re
        m = _re.search(r'session[:\s]+(\S+)', str(r), _re.I)
        sid = m.group(1).rstrip("'\").,;") if m else j(r).get("session_id", "")
        assert sid
        ok("serial_open", f"session={sid[:20]}")

        r2 = j(serial_read(sid, timeout=2))
        ok("serial_read", "ok" if r2 else "no-data")

        r3 = j(serial_write(sid, "\n"))
        ok("serial_write")

        r4 = j(serial_close(sid))
        ok("serial_close")

    except Exception as e:
        fail("serial", str(e)[:80])
        if sid:
            try: serial_close(sid)
            except: pass
else:
    skip("serial_open/write/read/close", f"{TEST_PORT} not found")

# ── Phase 3: Sessions ──────────────────────────────────────
sec("Phase 3 — Sessions")

mgr = SessionManager()
try:
    r = mgr.create_session("verify_test", "/tmp")
    assert "error" not in str(r).lower()
    ok("create_session")

    sessions = mgr.list_sessions()
    assert len(sessions) >= 1
    ok("list_sessions", f"{len(sessions)} active")

    r2 = mgr.destroy_session("verify_test")
    assert "error" not in str(r2).lower()
    ok("destroy_session")
except Exception as e:
    fail("sessions", str(e)[:80])
    traceback.print_exc()

# ── Phase 3: Build Diagnostics ─────────────────────────────
sec("Phase 3 — Build Diagnostics")

sample_build = (
    "Building component: main\n"
    "CC build/main/main.o\n"
    "LD build/project.elf\n"
    "error: undefined reference to `foo'\n"
    "warning: unused variable 'x'\n"
    "note: declared here\n"
)
try:
    r = j(parse_build_output(sample_build))
    assert "errors" in r or "_raw" in r
    ok("parse_build_output", str(r)[:80])
except Exception as e:
    fail("parse_build_output", str(e)[:80])

# ── Phase 4.1: High-Level File Ops ────────────────────────
sec("Phase 4 — replace_text + patch_file")

fn2 = tempfile.mktemp(dir="/tmp", prefix="mcp_p4_")
try:
    write_file(fn2, "old_value = 42\nkeep = 1\nold_value = 99\n", ROOTS)

    r = j(replace_text(fn2, "old_value", "new_value", replace_all=True, allowed_roots=ROOTS))
    c = j(read_file(fn2, ROOTS)).get("content", "")
    assert "new_value" in c and "old_value" not in c
    ok("replace_text (replace_all)")

    patch = (
        "--- a/file\n"
        "+++ b/file\n"
        "@@ -1,2 +1,2 @@\n"
        "-new_value = 42\n"
        "+patched_value = 42\n"
        " keep = 1\n"
    )
    r2 = j(patch_file(fn2, patch, allowed_roots=ROOTS))
    c2 = j(read_file(fn2, ROOTS)).get("content", "")
    assert "patched_value" in c2
    ok("patch_file")

    os.unlink(fn2)
except Exception as e:
    fail("phase4_fileops", str(e)[:80])
    try: os.unlink(fn2)
    except: pass

# ── Phase 4.2: UART Monitor / Panic Decode ────────────────
sec("Phase 4 — decode_panic + monitor_uart")

panic_text = (
    "Guru Meditation Error: Core  0 panic'ed (IllegalInstruction). Exception was unhandled.\n"
    "Core  0 register dump:\n"
    "PC      : 0x40081234  PS      : 0x00060e30  A0      : 0x80081234  A1      : 0x3ffb1234\n"
    "Backtrace: 0x40081234:0x3ffb1234 0x40085678:0x3ffb5678\n"
    "Rebooting...\n"
)
try:
    r = j(decode_panic(panic_text))
    s = str(r)
    assert "panic" in s.lower() or "0x" in s
    ok("decode_panic", s[:80])
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

# ── Phase 4.3: Symbol Indexing ────────────────────────────
sec("Phase 4 — find_symbol + find_references")

try:
    r = j(find_symbol("app_main", PROJECT_DIR, allowed_roots=ROOTS))
    s = str(r)
    assert ".c" in s or ".h" in s or "app_main" in s
    ok("find_symbol ('app_main')", s[:80])
except Exception as e:
    fail("find_symbol", str(e)[:80])

try:
    r2 = j(find_references("app_main", PROJECT_DIR, allowed_roots=ROOTS))
    ok("find_references", str(r2)[:80])
except Exception as e:
    fail("find_references", str(e)[:80])

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════
if summary():
    print("\nAll critical paths verified. Server is operational.\n")
else:
    print("\nSome tests failed — review output above.\n")
    sys.exit(1)
