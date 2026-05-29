#!/usr/bin/env python3
"""Test suite for ESP-Workspace MCP Server - Phases 1-4.

All tools require allowed_roots as first positional arg (injected by MCP server).
All tools return JSON strings that must be parsed with json.loads().
"""

import json, os, sys, time, tempfile, traceback, shutil
from pathlib import Path

PROJECT_ROOT = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"
sys.path.insert(0, PROJECT_ROOT)

WISH_PRODUCT = os.environ.get("WISH_PRODUCT", "TargetS3")
PROJECT_DIR = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"

# Allowed roots for testing (same as server config)
ROOTS = ["/home/juergen/AIRcableLLC", "/tmp", "/opt", "/home/juergen"]

# Phase 4 imports
from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart import decode_panic
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references

# Phase 3 imports
from esp_workspace_mcp.tools.session_tools import SessionManager
from esp_workspace_mcp.tools.esp_idf import parse_build_output

# Phase 2 imports
from esp_workspace_mcp.tools.git_tools import git_status, git_diff, git_branch, git_log
from esp_workspace_mcp.tools.search import grep, find_files
from esp_workspace_mcp.tools.serial_tools import list_serial_ports
from esp_workspace_mcp.tools.diagnostics import get_idf_version, get_project_info, get_connected_devices

# Phase 1 imports
from esp_workspace_mcp.tools.filesystem import read_file, write_file, append_file, list_dir, create_dir, delete_path, file_stat, glob_search
from esp_workspace_mcp.tools.shell import execute_command


class R:
    passed = 0; failed = 0; errors = []
    @staticmethod
    def ok(n, d=""):
        R.passed += 1
        print("  PASS  " + n + ((" --- " + d) if d else ""))
    @staticmethod
    def fail(n, r=""):
        R.failed += 1; R.errors.append(n)
        print("  FAIL  " + n + ": " + r)
    @staticmethod
    def summary():
        t = R.passed + R.failed
        print("\n" + "=" * 60)
        print("Results: %d/%d passed, %d failed" % (R.passed, t, R.failed))
        for e in R.errors: print("  - " + e)
        print("=" * 60)
        return R.failed == 0


def jloads(s):
    """Parse JSON string to dict."""
    if isinstance(s, dict):
        return s
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return {"_raw": s}
    return s


def sec(n):
    print("\n" + "-" * 60 + "\n  " + n + "\n" + "-" * 60)


# === PHASE 1: Filesystem ===
sec("Phase 1 - Filesystem")
print("[read/write/append]")
try:
    fn = tempfile.mktemp(dir="/tmp")
    open(fn, "w").write("L1\nL2\nL3\n")
    r = jloads(read_file(fn, ROOTS))
    assert "L1" in r.get("content", r.get("_raw", "")); R.ok("read_file")
    r = jloads(read_file(fn, ROOTS, offset=2, limit=1))
    assert "L2" in r.get("content", r.get("_raw", "")); R.ok("read_file offset")
    write_file(fn, "new\n", ROOTS)
    r = jloads(read_file(fn, ROOTS))
    assert "new" in r.get("content", r.get("_raw", "")); R.ok("write_file")
    append_file(fn, "add\n", ROOTS)
    r = jloads(read_file(fn, ROOTS))
    c = r.get("content", r.get("_raw", ""))
    assert "new" in c and "add" in c; R.ok("append_file")
    os.unlink(fn)
except Exception as e: R.fail("fs core", str(e)); traceback.print_exc()

print("[list_dir/create_dir/delete_path/file_stat/glob]")
try:
    r = jloads(list_dir("/tmp", ROOTS))
    entries = r.get("entries", [])
    assert isinstance(entries, list); R.ok("list_dir", "%d entries" % len(entries))
    d = "/tmp/mcp_tst2"
    create_dir(d, ROOTS); assert os.path.isdir(d); R.ok("create_dir")
    create_dir(d+"/a/b/c", ROOTS); assert os.path.isdir(d+"/a/b/c"); R.ok("create_dir nested")
    delete_path(d+"/a/b/c", ROOTS); assert not os.path.exists(d+"/a/b/c"); R.ok("delete_path")
    shutil.rmtree(d, ignore_errors=True)
    r = jloads(file_stat("/tmp", ROOTS))
    assert r.get("is_dir", False); R.ok("file_stat dir")
    fn = tempfile.mktemp(dir="/tmp"); open(fn, "w").write("hi")
    r = jloads(file_stat(fn, ROOTS))
    assert not r.get("is_dir") and r.get("size") == 2; R.ok("file_stat file sz=%d" % r.get("size"))
    os.unlink(fn)
    b = "/tmp/mcp_g2"; os.makedirs(b, exist_ok=True)
    [Path(b+"/"+n).touch() for n in ["a.py", "b.txt", "c.py"]]
    r = jloads(glob_search(".py", b, ROOTS))
    names = [e.get("name","") for e in r.get("entries", [])]
    assert "a.py" in names and "c.py" in names and "b.txt" not in names
    R.ok("glob *.py", str(names)); shutil.rmtree(b, ignore_errors=True)
except Exception as e: R.fail("fs adv", str(e)); traceback.print_exc()

print("[security / path sandboxing]")
try:
    r = read_file("/etc/shadow", ROOTS)
    result = str(r)
    if "denied" in result.lower() or "error" in result.lower():
        R.ok("sec / blocks shadow")
    else:
        R.fail("sec_shadow", "should block but got: " + result[:80])
except Exception as e:
    R.ok("sec / blocks shadow (raised: %s)" % type(e).__name__)
try:
    fn = tempfile.mktemp(dir="/tmp"); open(fn, "w").write("x")
    try:
        r = read_file("../../../../"+fn, ROOTS)
        result = str(r)
        if "denied" in result.lower() or "error" in result.lower():
            R.ok("sec / blocks traversal")
        else:
            R.fail("sec_trav", "should block but got: " + result[:80])
    finally:
        os.unlink(fn)
except Exception as e:
    R.ok("sec / blocks traversal (raised: %s)" % type(e).__name__)


# === PHASE 1: Shell ===
sec("Phase 1 - Shell")
print("[execute_command]")
try:
    r = jloads(execute_command("echo hello_12345", ROOTS))
    assert "hello_12345" in r.get("output", r.get("_raw", "")); R.ok("exec echo")
    r = jloads(execute_command("exit 42", ROOTS))
    assert r.get("returncode") == 42; R.ok("exec exit 42, rc=%d" % r.get("returncode"))
    t0 = time.time()
    r = jloads(execute_command("sleep 5", ROOTS, timeout=2))
    elapsed = time.time() - t0
    assert elapsed < 5; R.ok("exec timeout", "%.1fs" % elapsed)
except Exception as e: R.fail("exec", str(e)); traceback.print_exc()


# === PHASE 1: ESP-IDF ===
sec("Phase 1 - ESP-IDF")
print("[eim_run]")
try:
    r = jloads(eim_run("echo idf_ok_123", PROJECT_DIR, ROOTS))
    assert "idf_ok_123" in r.get("output", r.get("_raw", "")); R.ok("eim_run echo")
except Exception as e: R.fail("eim_run", str(e)); traceback.print_exc()


# === PHASE 2: Git ===
sec("Phase 2 - Git Tools")
for name, cmd in [("git_status", lambda: git_status(PROJECT_DIR, ROOTS)),
                   ("git_branch", lambda: git_branch(PROJECT_DIR, ROOTS)),
                   ("git_log", lambda: git_log(PROJECT_DIR, ROOTS, count=3)),
                   ("git_diff", lambda: git_diff(PROJECT_DIR, ROOTS))]:
    try:
        r = jloads(cmd())
        R.ok(name, json.dumps(r)[:120])
    except Exception as e: R.fail(name, str(e)); traceback.print_exc()


# === PHASE 2: Search ===
sec("Phase 2 - Search Tools")
print("[grep]")
try:
    r = jloads(grep("import", PROJECT_DIR, ROOTS, file_pattern="*.py", max_results=5))
    R.ok("grep", json.dumps(r)[:120])
except Exception as e: R.fail("grep", str(e)); traceback.print_exc()

print("[find_files]")
try:
    r = jloads(find_files("*.py", PROJECT_DIR, ROOTS))
    R.ok("find_files", json.dumps(r)[:120])
except Exception as e: R.fail("find_files", str(e)); traceback.print_exc()


# === PHASE 2: Serial ===
sec("Phase 2 - Serial Tools")
try:
    r = jloads(list_serial_ports(ROOTS))
    ports = r.get("ports", r.get("entries", []))
    R.ok("list_serial_ports", "%d ports" % len(ports))
    if ports:
        for p in ports[:3]:
            print("    port: %s" % str(p))
except Exception as e: R.fail("serial", str(e)); traceback.print_exc()


# === PHASE 2: Diagnostics ===
sec("Phase 2 - Diagnostics")
for name, cmd in [("get_idf_version", lambda: get_idf_version(ROOTS, wish_product=WISH_PRODUCT)),
                   ("get_project_info", lambda: get_project_info(PROJECT_DIR, ROOTS)),
                   ("get_connected_devices", lambda: get_connected_devices(ROOTS))]:
    try:
        r = jloads(cmd())
        R.ok(name, json.dumps(r)[:120])
    except Exception as e: R.fail(name, str(e)); traceback.print_exc()


# === PHASE 3: Build Diagnostics ===
sec("Phase 3 - Build Diagnostics")
print("[parse_build_output]")
try:
    sample = "main.h:10:5: error: unknown type name 'x'\nmain.c:25:3: warning: implicit declaration\nninja: build stopped\n"
    r = jloads(parse_build_output(sample))
    assert "errors" in r and r.get("error_count", 0) >= 1 and r.get("warning_count", 0) >= 1
    R.ok("parse_build_output", "%d err, %d warn" % (r.get("error_count", 0), r.get("warning_count", 0)))
except Exception as e: R.fail("parse_build", str(e)); traceback.print_exc()


# === PHASE 3: Sessions ===
sec("Phase 3 - Session Management")
try:
    sm = SessionManager()
    s = sm.create_session("tst_session", "/tmp")
    sid = s["session_id"]; R.ok("create_session", sid[:16]+"...")
    sessions = sm.list_sessions()
    assert any(x.get("session_id") == sid for x in sessions); R.ok("list_sessions")
    d = sm.destroy_session(sid)
    assert d.get("status") == "destroyed"; R.ok("destroy_session")
    sessions = sm.list_sessions()
    assert not any(x.get("session_id") == sid for x in sessions); R.ok("destroy verified")
except Exception as e: R.fail("sessions", str(e)); traceback.print_exc()


# === PHASE 4: High-Level File Ops ===
sec("Phase 4 - High-Level File Operations")
print("[replace_text]")
try:
    fn = tempfile.mktemp(suffix=".py", dir="/tmp")
    open(fn, "w").write("def hello():\n    print('hello')\n\nhello()\n")
    r = jloads(replace_text(fn, "hello", "goodbye", allowed_roots=ROOTS))
    assert r.get("status") == "ok" and r.get("replacements", 0) == 4
    R.ok("replace_text 4x")
    r = jloads(replace_text(fn, "goodbye", "hey", count=2, allowed_roots=ROOTS))
    assert r.get("replacements", 0) == 2; R.ok("replace_text count=2")
    r = jloads(replace_text(fn, "nope", "xyz", allowed_roots=ROOTS))
    assert r.get("status") == "no_match"; R.ok("replace_text no_match")
    os.unlink(fn)
except Exception as e: R.fail("replace_text", str(e)); traceback.print_exc()

print("[patch_file]")
try:
    fn = tempfile.mktemp(suffix=".txt", dir="/tmp"); open(fn, "w").write("A\nB\nC\n")
    df = tempfile.mktemp(suffix=".diff", dir="/tmp")
    open(df, "w").write("--- a\n+++ b\n@@ -1,3 +1,3 @@\n A\n-B\n+BEE\n C\n")
    r = jloads(patch_file(fn, df, allowed_roots=ROOTS))
    assert r.get("status") == "ok", str(r); R.ok("patch_file")
    assert "BEE" in open(fn).read(); R.ok("patch verified")
    os.unlink(fn); os.unlink(df)
except Exception as e: R.fail("patch_file", str(e)); traceback.print_exc()


# === PHASE 4: Debug Tools ===
sec("Phase 4 - Debug Tools")
print("[decode_panic]")
try:
    dump = (
        "Guru Meditation Error: Core  0 panic'ed (LoadProhibited).\n"
        "PC: 0x40081234  A1: 0x3ffb1234\n"
        "Backtrace: 0x40081234:0x3ffb1234 0x40085678:0x3ffb5678\n"
    )
    r = jloads(decode_panic(dump))
    R.ok("decode_panic", json.dumps(r)[:200])
    assert "pc" in str(r).lower() or "reset_reason" in r or "panic" in str(r).lower()
except Exception as e: R.fail("decode_panic", str(e)); traceback.print_exc()


# === PHASE 4: Symbol Indexing ===
sec("Phase 4 - Symbol Indexing")
print("[find_symbol]")
try:
    r = jloads(find_symbol("read_file", PROJECT_ROOT, allowed_roots=ROOTS))
    R.ok("find_symbol", json.dumps(r)[:200])
except Exception as e: R.fail("find_symbol", str(e)); traceback.print_exc()

print("[find_references]")
try:
    r = jloads(find_references("read_file", PROJECT_ROOT, allowed_roots=ROOTS))
    R.ok("find_references", json.dumps(r)[:200])
except Exception as e: R.fail("find_references", str(e)); traceback.print_exc()


# === PHASE 4: UART Monitor (real hardware /dev/ttyACM0) ===
sec("Phase 4 - Real Hardware: /dev/ttyACM0")
try:
    import serial
    ser = serial.Serial("/dev/ttyACM0", 115200, timeout=3)
    time.sleep(0.5)
    # Try to get a response - just read whatever is available
    available = ser.in_waiting
    if available > 0:
        output = ser.read(available).decode("utf-8", errors="replace")
        R.ok("serial_read_raw", "%d bytes: %s" % (available, output[:100]))
    else:
        R.ok("serial_read_raw", "no data available (port open OK)")
    ser.close()
except serial.SerialException as e:
    R.fail("serial_ttyACM0", "Serial error: %s" % str(e))
except Exception as e:
    R.fail("serial_ttyACM0", str(e))


# === Summary ===
print()
success = R.summary()
sys.exit(0 if success else 1)
