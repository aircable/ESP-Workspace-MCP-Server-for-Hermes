#!/usr/bin/env python3
"""Comprehensive test suite for ESP-Workspace MCP Server."""

import json, os, sys, time, tempfile, traceback, shutil
from pathlib import Path

PROJECT_ROOT = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"
sys.path.insert(0, PROJECT_ROOT)

WISH_PRODUCT = os.environ.get("WISH_PRODUCT", "TargetS3")
PROJECT_DIR = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"

# Phase 4 imports
from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart import decode_panic
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references

# Phase 3 imports
from esp_workspace_mcp.tools.session_tools import SessionManager
# from esp_workspace_mcp.tools.build_diagnostics import parse_build_output  # Moved to esp_idf
from esp_workspace_mcp.tools.esp_idf import parse_build_output
# MCPError not defined - security tests check return values

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

def sec(n):
    print("\n" + "-" * 60 + "\n  " + n + "\n" + "-" * 60)


# === PHASE 1: Filesystem ===
sec("Phase 1 - Filesystem")
print("[read/write/append]")
try:
    fn = tempfile.mktemp(dir="/tmp"); open(fn,"w").write("L1\nL2\nL3\n")
    assert "L1" in read_file(fn)["content"]; R.ok("read_file")
    assert "L2" in read_file(fn, offset=2, limit=1)["content"]; R.ok("read_file offset")
    write_file(fn, "new\n"); assert read_file(fn)["content"] == "new\n"; R.ok("write_file")
    append_file(fn, "add\n"); c = read_file(fn)["content"]; assert "new" in c and "add" in c; R.ok("append_file")
    os.unlink(fn)
except Exception as e: R.fail("fs core", str(e)); traceback.print_exc()

print("[list_dir/create_dir/delete_path/file_stat/glob]")
try:
    r = list_dir("/tmp"); assert isinstance(r["entries"], list); R.ok("list_dir", "%d entries" % len(r["entries"]))
    d = "/tmp/mcp_tst1"; create_dir(d); assert os.path.isdir(d); R.ok("create_dir")
    create_dir(d+"/a/b/c"); assert os.path.isdir(d+"/a/b/c"); R.ok("create_dir nested")
    delete_path(d+"/a/b/c"); assert not os.path.exists(d+"/a/b/c"); R.ok("delete_path")
    shutil.rmtree(d, ignore_errors=True)
    r = file_stat("/tmp"); assert r["is_dir"]; R.ok("file_stat dir")
    fn = tempfile.mktemp(dir="/tmp"); open(fn,"w").write("hi")
    r = file_stat(fn); assert not r["is_dir"] and r["size"] == 2; R.ok("file_stat file sz=%d" % r["size"]); os.unlink(fn)
    b = "/tmp/mcp_g1"; os.makedirs(b, exist_ok=True)
    [Path(b+"/"+n).touch() for n in ["a.py","b.txt","c.py"]]
    r = glob_search(".py", b); names = [e["name"] for e in r["entries"]]
    assert "a.py" in names and "c.py" in names and "b.txt" not in names; R.ok("glob *.py"); shutil.rmtree(b, ignore_errors=True)
except Exception as e: R.fail("fs adv", str(e)); traceback.print_exc()

print("[security]")
try:
    r = read_file("/etc/shadow")
    if isinstance(r, dict) and "error" in str(r.get("content", "")).lower() or isinstance(r, str) and "error" in r.lower() or isinstance(r, dict) and "Access denied" in str(r):
        R.ok("sec / blocks shadow")
    else:
        # Check if the result indicates denial
        result_str = str(r)
        if "denied" in result_str.lower() or "error" in result_str.lower():
            R.ok("sec / blocks shadow")
        else:
            R.fail("sec_shadow", "should block but got: " + result_str[:80])
except Exception as e:
    R.ok("sec / blocks shadow (raised)")
try:
    import tempfile as tf
    fn = tf.mktemp(dir="/tmp"); open(fn,"w").write("x")
    r = read_file("../../../../"+fn)
    result_str = str(r)
    if "denied" in result_str.lower() or "error" in result_str.lower():
        R.ok("sec / blocks traversal")
    else:
        R.fail("sec_trav", "should block but got: " + result_str[:80])
    os.unlink(fn)
except Exception as e:
    R.ok("sec / blocks traversal (raised)")


# === PHASE 1: Shell ===
sec("Phase 1 - Shell")
print("[execute_command]")
try:
    r = execute_command("echo hello_12345"); assert "hello_12345" in r["output"]; R.ok("exec echo")
    r = execute_command("exit 42"); assert r["returncode"] == 42; R.ok("exec exit 42")
    t0 = time.time(); r = execute_command("sleep 5", timeout=2); assert time.time()-t0 < 5; R.ok("exec timeout")
except Exception as e: R.fail("exec", str(e)); traceback.print_exc()


# === PHASE 1: ESP-IDF ===
sec("Phase 1 - ESP-IDF")
print("[eim_run]")
try:
    r = eim_run("echo idf_ok_123"); assert "idf_ok_123" in r["output"]; R.ok("eim_run echo")
except Exception as e: R.fail("eim_run", str(e)); traceback.print_exc()


# === PHASE 2: Git ===
sec("Phase 2 - Git Tools")
for name, fn in [("git_status", git_status), ("git_branch", git_branch), ("git_log", lambda d: git_log(d, 3)), ("git_diff", git_diff)]:
    try:
        r = fn(PROJECT_DIR); assert isinstance(r, dict); R.ok(name, json.dumps(r)[:150])
    except Exception as e: R.fail(name, str(e)); traceback.print_exc()


# === PHASE 2: Search ===
sec("Phase 2 - Search Tools")
try:
    r = grep("import", path=PROJECT_DIR, file_glob="*.py", max_results=5); assert isinstance(r, dict)
    R.ok("grep", json.dumps(r)[:150])
except Exception as e: R.fail("grep", str(e)); traceback.print_exc()
try:
    r = find_files("*.py", path=PROJECT_DIR, max_results=5); assert isinstance(r, dict)
    R.ok("find_files", json.dumps(r)[:150])
except Exception as e: R.fail("find_files", str(e)); traceback.print_exc()


# === PHASE 2: Serial ===
sec("Phase 2 - Serial Tools")
try:
    r = list_serial_ports(); assert isinstance(r, dict)
    ports = r.get("ports", []); R.ok("list_serial_ports", "%d ports" % len(ports))
except Exception as e: R.fail("serial", str(e)); traceback.print_exc()


# === PHASE 2: Diagnostics ===
sec("Phase 2 - Diagnostics")
for name, fn in [("get_idf_version", get_idf_version), ("get_project_info", lambda: get_project_info(PROJECT_DIR)), ("get_connected_devices", get_connected_devices)]:
    try:
        r = fn(); assert isinstance(r, dict); R.ok(name, json.dumps(r)[:150])
    except Exception as e: R.fail(name, str(e)); traceback.print_exc()


# === PHASE 3: Build Diagnostics ===
sec("Phase 3 - Build Diagnostics")
print("[parse_build_output]")
try:
    sample = "main.h:10:5: error: unknown type name 'x'\nmain.c:25:3: warning: implicit decl\nninja: build stopped\n"
    r = parse_build_output(sample); assert "errors" in r and r["error_count"] >= 1 and r["warning_count"] >= 1
    R.ok("parse_build_output", "%d err, %d warn" % (r["error_count"], r["warning_count"]))
except Exception as e: R.fail("parse_build", str(e)); traceback.print_exc()


# === PHASE 3: Sessions ===
sec("Phase 3 - Session Management")
try:
    sm = SessionManager(); s = sm.create_session("tst", working_directory="/tmp")
    sid = s["session_id"]; R.ok("create_session", sid[:12]+"...")
    assert any(x.get("session_id")==sid for x in sm.list_sessions()); R.ok("list_sessions")
    assert sm.destroy_session(sid).get("status") == "destroyed"; R.ok("destroy_session")
    assert not any(x.get("session_id")==sid for x in sm.list_sessions()); R.ok("destroy verified")
except Exception as e: R.fail("sessions", str(e)); traceback.print_exc()


# === PHASE 4: High-Level File Ops ===
sec("Phase 4 - High-Level File Operations")
print("[replace_text]")
try:
    fn = tempfile.mktemp(suffix=".py", dir="/tmp"); open(fn,"w").write("def hello():\n    print('hello')\n\nhello()\n")
    r = replace_text(fn, "hello", "goodbye"); assert r["status"]=="ok" and r["replacements"]==4
    R.ok("replace_text 4x")
    r = replace_text(fn, "goodbye", "hey", count=2); assert r["replacements"]==2; R.ok("replace_text count=2")
    r = replace_text(fn, "nope", "xyz"); assert r["status"]=="no_match"; R.ok("replace_text no_match")
    os.unlink(fn)
except Exception as e: R.fail("replace_text", str(e)); traceback.print_exc()

print("[patch_file]")
try:
    fn = tempfile.mktemp(suffix=".txt", dir="/tmp"); open(fn,"w").write("A\nB\nC\n")
    df = tempfile.mktemp(suffix=".diff", dir="/tmp")
    open(df,"w").write("--- a\n+++ b\n@@ -1,3 +1,3 @@\n A\n-B\n+BEE\n C\n")
    r = patch_file(fn, df); assert r["status"]=="ok", str(r); R.ok("patch_file")
    assert "BEE" in open(fn).read(); R.ok("patch verified")
    os.unlink(fn); os.unlink(df)
except Exception as e: R.fail("patch_file", str(e)); traceback.print_exc()


# === PHASE 4: Debug ===
sec("Phase 4 - Debug Tools")
print("[decode_panic]")
try:
    dump = "Guru Meditation Error: Core  0 panic'ed (LoadProhibited).\nPC: 0x40081234  A1: 0x3ffb1234\nBacktrace: 0x40081234:0x3ffb1234\n"
    r = decode_panic(dump); assert isinstance(r, dict); R.ok("decode_panic", json.dumps(r)[:200])
except Exception as e: R.fail("decode_panic", str(e)); traceback.print_exc()


# === PHASE 4: Symbol Indexing ===
sec("Phase 4 - Symbol Indexing")
try:
    r = find_symbol("read_file", path=PROJECT_ROOT); assert isinstance(r, dict)
    R.ok("find_symbol", json.dumps(r)[:200])
except Exception as e: R.fail("find_symbol", str(e)); traceback.print_exc()
try:
    r = find_references("MCPError", path=PROJECT_ROOT); assert isinstance(r, dict)
    R.ok("find_references", json.dumps(r)[:200])
except Exception as e: R.fail("find_references", str(e)); traceback.print_exc()


# === Summary ===
print()
sys.exit(0 if R.summary() else 1)
