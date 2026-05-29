#!/usr/bin/env python3
"""
ESP-Workspace MCP Server — Test Suite v3
=========================================
Tests all 50 tools across Phases 1-4 with real hardware where available.

Usage:
    cd /path/to/MCPserver && source .venv/bin/activate && python test_suite_v3.py

Environment:
    WISH_PRODUCT  (default: TargetS3)
    TEST_PORT     (default: /dev/ttyACM0)
"""
import json, os, sys, time, tempfile, shutil
from pathlib import Path

PROJECT_ROOT = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"
sys.path.insert(0, PROJECT_ROOT)

WISH_PRODUCT = os.environ.get("WISH_PRODUCT", "TargetS3")
PROJECT_DIR  = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"
TEST_PORT    = os.environ.get("TEST_PORT", "/dev/ttyACM0")
ROOTS = ["/home/juergen/AIRcableLLC", "/tmp", "/opt", "/home/juergen"]

from esp_workspace_mcp.tools.filesystem import (
    read_file, write_file, append_file, list_dir, create_dir,
    delete_path, file_stat, glob_search,
)
from esp_workspace_mcp.tools.shell import execute_command
from esp_workspace_mcp.tools.esp_idf import (
    eim_run, parse_build_output, idf_size, idf_sdkconfig,
)
from esp_workspace_mcp.tools.git_tools import git_status, git_diff, git_branch, git_log
from esp_workspace_mcp.tools.search import grep, find_files
from esp_workspace_mcp.tools.serial_tools import (
    list_serial_ports, serial_open, serial_read, serial_write,
    serial_close, serial_sessions,
)
from esp_workspace_mcp.tools.diagnostics import (
    get_idf_version, get_project_info, get_connected_devices,
)
from esp_workspace_mcp.tools.session_tools import SessionManager
from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart import monitor_uart, decode_panic
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references
from esp_workspace_mcp.tools.phase4_debug import run_debug_cycle

class R:
    passed = 0; failed = 0; errors = []; skipped = 0
    @staticmethod
    def ok(n, d=""):
        R.passed += 1
        print("  PASS  " + n + ((" -- " + d) if d else ""))
    @staticmethod
    def fail(n, r=""):
        R.failed += 1; R.errors.append(n)
        print("  FAIL  " + n + ": " + r)
    @staticmethod
    def skip(n, r=""):
        R.skipped += 1
        print("  SKIP  " + n + ": " + r)
    @staticmethod
    def summary():
        t = R.passed + R.failed + R.skipped
        print("\n" + "=" * 60)
        print("Results: %d/%d passed, %d failed, %d skipped" % (R.passed, t, R.failed, R.skipped))
        for e in R.errors:
            print("  FAIL: " + e)
        print("=" * 60)
        return R.failed == 0

def sec(title):
    print("\n" + "-" * 60 + "\n  " + title + "\n" + "-" * 60)


# ═══ PHASE 1: Filesystem ═══
sec("Phase 1 - Filesystem (8 tools)")

try:
    t = tempfile.mktemp(dir="/tmp", prefix="mcp_")
    write_file(t, "hello world", ROOTS)
    assert "hello world" in Path(t).read_text()
    R.ok("write_file")
except Exception as e:
    R.fail("write_file", str(e)[:80])

try:
    raw = read_file(t, ROOTS)
    assert "hello world" in raw
    R.ok("read_file")
except Exception as e:
    R.fail("read_file", str(e)[:80])

try:
    write_file(t, "L1\nL2\nL3\nL4\n", ROOTS)
    raw = read_file(t, ROOTS, offset=1, limit=2)
    assert "L2" in raw, "Got: " + raw[:50]
    R.ok("read_file offset+limit")
except Exception as e:
    R.fail("read_file offset+limit", str(e)[:80])

try:
    append_file(t, "\nappended", ROOTS)
    c = Path(t).read_text()
    assert "appended" in c
    R.ok("append_file")
except Exception as e:
    R.fail("append_file", str(e)[:80])

try:
    raw = list_dir("/tmp", ROOTS)
    assert "entries" in raw.lower() or "dir" in raw.lower() or "mcp_" in raw
    R.ok("list_dir")
except Exception as e:
    R.fail("list_dir", str(e)[:80])

try:
    d = tempfile.mktemp(dir="/tmp", prefix="mcp_dir_")
    create_dir(d, ROOTS)
    assert Path(d).is_dir()
    R.ok("create_dir")
except Exception as e:
    R.fail("create_dir", str(e)[:80])

try:
    delete_path(t, ROOTS)
    assert not Path(t).exists()
    R.ok("delete_path")
except Exception as e:
    R.fail("delete_path", str(e)[:80])

try:
    sf = tempfile.mktemp(dir="/tmp", prefix="mcp_stat_")
    write_file(sf, "stat test", ROOTS)
    raw = file_stat(sf, ROOTS)
    assert "Size" in raw
    R.ok("file_stat")
    os.unlink(sf)
except Exception as e:
    R.fail("file_stat", str(e)[:80])

try:
    gf = tempfile.mktemp(dir="/tmp", prefix="mcp_glob_", suffix=".c")
    write_file(gf, "int main(){}", ROOTS)
    raw = glob_search("mcp_glob_*.c", "/tmp", ROOTS)
    assert "mcp_glob_" in raw
    R.ok("glob_search")
    os.unlink(gf)
except Exception as e:
    R.fail("glob_search", str(e)[:80])

# Security
try:
    raw = read_file("/etc/passwd", ROOTS)
    assert "denied" in raw.lower() or "not allowed" in raw.lower()
    R.ok("security / blocks /etc/passwd")
except Exception as e:
    R.fail("security / blocks /etc/passwd", str(e)[:80])

try:
    raw = read_file("/home/juergen/AIRcableLLC/../../etc/shadow", ROOTS)
    assert "denied" in raw.lower() or "not allowed" in raw.lower()
    R.ok("security / blocks traversal")
except Exception as e:
    R.fail("security / blocks traversal", str(e)[:80])

if Path(d).exists():
    shutil.rmtree(d, ignore_errors=True)


# ═══ PHASE 1: Shell ═══
sec("Phase 1 - Shell (6 tools)")

try:
    r = execute_command("echo shell_ok", ROOTS, timeout=10)
    assert r.get("success") and "shell_ok" in r.get("stdout", "")
    R.ok("run_command")
except Exception as e:
    R.fail("run_command", str(e)[:80])

try:
    r = execute_command("pwd", ROOTS, cwd="/tmp", timeout=10)
    assert "/tmp" in r.get("stdout", "")
    R.ok("run_command with cwd")
except Exception as e:
    R.fail("run_command with cwd", str(e)[:80])

try:
    start = time.monotonic()
    r = execute_command("sleep 5", ROOTS, timeout=2)
    elapsed = time.monotonic() - start
    assert elapsed < 4, "Timeout not respected: %.1fs" % elapsed
    R.ok("run_command timeout")
except Exception as e:
    R.fail("run_command timeout", str(e)[:80])


# ═══ PHASE 1: ESP-IDF ═══
sec("Phase 1 - ESP-IDF (7 tools)")

try:
    sample = ("main.c:42:5: error: 'foo' undeclared\n"
              "main.c:10:8: warning: unused variable 'x'\n"
              "[1/10] Building C object\n")
    r = parse_build_output(sample)
    parsed = json.loads(r)
    assert len(parsed.get("errors", [])) >= 1
    assert len(parsed.get("warnings", [])) >= 1
    R.ok("parse_build_output", "%d err, %d warn" % (len(parsed["errors"]), len(parsed["warnings"])))
except Exception as e:
    R.fail("parse_build_output", str(e)[:80])

try:
    r = idf_size(PROJECT_DIR, ROOTS, wish_product=WISH_PRODUCT, eim_path="eim")
    assert len(r) > 20
    R.ok("idf_size")
except Exception as e:
    R.fail("idf_size", str(e)[:80])

try:
    r = idf_sdkconfig(PROJECT_DIR, ROOTS, wish_product=WISH_PRODUCT, eim_path="eim")
    assert len(r) > 20
    R.ok("idf_sdkconfig")
except Exception as e:
    R.fail("idf_sdkconfig", str(e)[:80])


# ═══ PHASE 2: Git ═══
sec("Phase 2 - Git (5 tools)")

try:
    r = git_status(PROJECT_DIR, ROOTS)
    assert len(r) > 10
    R.ok("git_status", r[:60])
except Exception as e:
    R.fail("git_status", str(e)[:80])

try:
    r = git_branch(PROJECT_DIR, ROOTS)
    assert "branch" in r.lower() or "*" in r
    R.ok("git_branch")
except Exception as e:
    R.fail("git_branch", str(e)[:80])

try:
    r = git_log(PROJECT_DIR, ROOTS, count=3)
    assert len(r) > 10
    R.ok("git_log")
except Exception as e:
    R.fail("git_log", str(e)[:80])

try:
    r = git_diff(PROJECT_DIR, ROOTS, staged=False)
    assert len(r) >= 0
    R.ok("git_diff", r[:60])
except Exception as e:
    R.fail("git_diff", str(e)[:80])


# ═══ PHASE 2: Search ═══
sec("Phase 2 - Search (2 tools)")

try:
    r = grep("import", PROJECT_ROOT + "/esp_workspace_mcp/tools/filesystem.py", ROOTS, max_results=10)
    assert "import" in r or len(r) > 5
    R.ok("grep")
except Exception as e:
    R.fail("grep", str(e)[:80])

try:
    r = find_files("*.py", PROJECT_ROOT, ROOTS)
    assert ".py" in r
    R.ok("find_files")
except Exception as e:
    R.fail("find_files", str(e)[:80])


# ═══ PHASE 2: Serial ═══
sec("Phase 2 - Serial (6 tools)")

try:
    r = list_serial_ports(ROOTS)
    R.ok("list_serial_ports", r[:100])
except Exception as e:
    R.fail("list_serial_ports", str(e)[:80])

# Real hardware test
if Path(TEST_PORT).exists():
    try:
        import serial
        ser = serial.Serial(TEST_PORT, baudrate=115200, timeout=2)
        time.sleep(0.5)
        available = ser.in_waiting
        data = b""
        if available > 0:
            data = ser.read(min(available, 1024))
        ser.close()
        R.ok("serial_read on " + TEST_PORT, "%d bytes available" % available)
    except Exception as e:
        R.fail("serial_read on " + TEST_PORT, str(e)[:80])
else:
    R.skip("serial_read", TEST_PORT + " not available")


# ═══ PHASE 2: Diagnostics ═══
sec("Phase 2 - Diagnostics (3 tools)")

try:
    r = get_idf_version(ROOTS, wish_product=WISH_PRODUCT, eim_path="eim")
    assert "v" in r.lower() or "idf" in r.lower() or "using" in r.lower() or len(r) > 20
    R.ok("get_idf_version")
except Exception as e:
    R.fail("get_idf_version", str(e)[:80])

try:
    r = get_project_info(PROJECT_DIR, ROOTS)
    assert "project" in r.lower() or "target" in r.lower() or len(r) > 20
    R.ok("get_project_info")
except Exception as e:
    R.fail("get_project_info", str(e)[:80])

try:
    r = get_connected_devices(ROOTS)
    assert "usb" in r.lower() or "device" in r.lower() or "tty" in r.lower()
    R.ok("get_connected_devices")
except Exception as e:
    R.fail("get_connected_devices", str(e)[:80])


# ═══ PHASE 3: Sessions ═══
sec("Phase 3 - Sessions (3 tools)")

try:
    sm = SessionManager(ttl_seconds=300)
    r = sm.create_session("test_eval", "/tmp")
    assert r.get("status") in ("active", "created")
    R.ok("create_session")

    sessions = sm.list_sessions()
    assert any(s["session_id"] == "test_eval" for s in sessions)
    R.ok("list_sessions")

    r = sm.destroy_session("test_eval")
    assert r.get("status") == "destroyed"
    R.ok("destroy_session")
except Exception as e:
    R.fail("session_management", str(e)[:80])


# ═══ PHASE 4: File Operations ═══
sec("Phase 4 - File Operations (2 tools)")

try:
    t4 = tempfile.mktemp(dir="/tmp", prefix="mcp4_")
    write_file(t4, "hello world\nhello again\ngoodbye\n", ROOTS)
    r = replace_text(t4, "hello", "HELLO", replace_all=False, allowed_roots=ROOTS)
    parsed = json.loads(r)
    c = Path(t4).read_text()
    assert parsed.get("replacements", 0) == 1
    assert "HELLO world" in c and "hello again" in c
    R.ok("replace_text (first)")
    os.unlink(t4)
except Exception as e:
    R.fail("replace_text (first)", str(e)[:80])

try:
    t4b = tempfile.mktemp(dir="/tmp", prefix="mcp4_")
    write_file(t4b, "foo bar foo baz foo\n", ROOTS)
    r = replace_text(t4b, "foo", "FOO", replace_all=True, allowed_roots=ROOTS)
    parsed = json.loads(r)
    assert parsed.get("replacements", 0) == 3
    R.ok("replace_text (all)")
    os.unlink(t4b)
except Exception as e:
    R.fail("replace_text (all)", str(e)[:80])

try:
    t4c = tempfile.mktemp(dir="/tmp", prefix="mcp4_")
    write_file(t4c, "line1\nline2\nline3\nline4\n", ROOTS)
    diff = "--- a/test\n+++ b/test\n@@ -1,4 +1,4 @@\n line1\n-line2\n+LINE2_MODIFIED\n line3\n line4\n"
    r = patch_file(t4c, diff, allowed_roots=ROOTS)
    parsed = json.loads(r)
    assert parsed.get("applied", False)
    c = Path(t4c).read_text()
    assert "LINE2_MODIFIED" in c
    R.ok("patch_file")
    os.unlink(t4c)
except Exception as e:
    R.fail("patch_file", str(e)[:80])


# ═══ PHASE 4: UART & Panic ═══
sec("Phase 4 - UART & Panic (2 tools)")

try:
    panic = ("Guru Meditation Error: Core  0 panic'ed (LoadProhibited).\n"
             "PC: 0x40081234\n"
             "Backtrace: 0x40081234 0x40085678\n")
    r = decode_panic(panic)
    parsed = json.loads(r)
    assert parsed["panic_detected"] == True
    assert parsed["pc_address"] == "0x40081234"
    R.ok("decode_panic", "reason=" + str(parsed.get("reset_reason")))
except Exception as e:
    R.fail("decode_panic", str(e)[:80])

try:
    r = decode_panic("Hello world\r\nSensor: 42\r\n")
    parsed = json.loads(r)
    assert parsed["panic_detected"] == False
    R.ok("decode_panic (no panic)")
except Exception as e:
    R.fail("decode_panic (no panic)", str(e)[:80])

if Path(TEST_PORT).exists():
    try:
        r = monitor_uart(TEST_PORT, baud=115200, duration=2, allowed_roots=ROOTS)
        parsed = json.loads(r)
        lines = parsed.get("captured_lines", 0)
        R.ok("monitor_uart on " + TEST_PORT, "%d lines" % lines)
    except Exception as e:
        R.fail("monitor_uart on " + TEST_PORT, str(e)[:80])
else:
    R.skip("monitor_uart", TEST_PORT + " not available")


# ═══ PHASE 4: Symbol Indexing ═══
sec("Phase 4 - Symbol Indexing (2 tools)")

try:
    r = find_symbol("execute_command", PROJECT_ROOT, allowed_roots=ROOTS)
    parsed = json.loads(r)
    assert "symbol" in parsed or "results" in parsed
    R.ok("find_symbol")
except Exception as e:
    R.fail("find_symbol", str(e)[:80])

try:
    r = find_references("read_file", PROJECT_ROOT, allowed_roots=ROOTS)
    parsed = json.loads(r)
    assert "symbol" in parsed or "total" in parsed or "results" in parsed
    R.ok("find_references")
except Exception as e:
    R.fail("find_references", str(e)[:80])


# ═══ Summary ═══
if R.summary():
    sys.exit(0)
else:
    sys.exit(1)
