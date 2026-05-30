#!/usr/bin/env python3
"""
Comprehensive MCP Server Test Suite
====================================
Run: cd MCPserver && .venv/bin/python test_mcp_server.py

Tests the most important and complex items across all tool categories.
"""
import sys
import os
import shutil

os.chdir("/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver")
sys.path.insert(0, ".")

from esp_workspace_mcp.server import create_server
from esp_workspace_mcp.config import load_settings

settings = load_settings()
mcp = create_server(settings)
roots = settings.allowed_roots
TEST_DIR = "/tmp/mcp_test_final"
P = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"  # project path

passed = 0
failed = 0
skipped = 0


def ok(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}: {detail}")


def skip(name, reason):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name}: {reason}")


def contains(s, *kw):
    s = str(s).lower()
    return any(k.lower() in s for k in kw)


# ================================================================
# GROUP 1: Server & Tool Registration
# ================================================================
print("\n=== GROUP 1: Server & Tool Registration ===")

ok("Server created", mcp is not None)
ok("Settings loaded", settings is not None)
ok(f"Allowed roots ({len(roots)})", len(roots) > 0)

import re
with open("esp_workspace_mcp/server.py") as f:
    src = f.read()
tool_count = src.count("@mcp.tool()")
ok(f"@mcp.tool() count = {tool_count}", tool_count >= 45)

for t in ["replace_text", "patch_file", "monitor_uart", "decode_panic",
          "find_symbol", "find_references", "run_debug_cycle"]:
    ok(f"Phase 4: {t}", f"def {t}(" in src)


# ================================================================
# GROUP 2: Filesystem Tools + Security
# ================================================================
print("\n=== GROUP 2: Filesystem Tools & Security ===")

from esp_workspace_mcp.tools.filesystem import (
    create_dir, delete_path, write_file, read_file, list_dir,
    file_stat, glob_search, append_file
)
try:
    delete_path(TEST_DIR, roots)
except:
    pass

tf = f"{TEST_DIR}/test.txt"
r = create_dir(TEST_DIR, roots); ok("create_dir", contains(r, "created", "already"))
r = write_file(tf, "line1\nline2\nline3\n", roots); ok("write_file", contains(r, "wrote", "bytes"))
r = read_file(tf, roots); ok("read_file", "line1" in r and "line3" in r)
r = read_file(tf, roots, offset=1, limit=1); ok("read_file offset/limit", "line2" in r)
r = append_file(tf, "line4\n", roots); ok("append_file", contains(r, "appended", "bytes"))
r = read_file(tf, roots); ok("verify append", "line4" in r)
r = file_stat(tf, roots); ok("file_stat", "size" in r.lower())
r = glob_search("*.txt", TEST_DIR, roots); ok("glob_search", "test.txt" in r)
r = list_dir(TEST_DIR, roots); ok("list_dir", "test.txt" in r)

# Security - path traversal
r = read_file("/etc/passwd", roots); ok("SECURITY: /etc/passwd", contains(r, "not allowed", "denied"))
r = read_file("/var/log/syslog", roots); ok("SECURITY: /var/log/syslog", contains(r, "not allowed", "denied"))

try:
    shutil.rmtree(TEST_DIR, ignore_errors=True)
except:
    pass


# ================================================================
# GROUP 3: Git Tools (read-only)
# ================================================================
print("\n=== GROUP 3: Git Tools (read-only) ===")

from esp_workspace_mcp.tools.git_tools import git_status, git_diff, git_log, git_branch

r = git_status(directory=P, allowed_roots=roots); ok("git_status", r is not None and len(str(r)) > 0)
r = git_diff(directory=P, allowed_roots=roots); ok("git_diff", r is not None)
r = git_log(directory=P, count=5, allowed_roots=roots); ok("git_log(5)", r is not None and len(str(r)) > 0)
r = git_branch(directory=P, allowed_roots=roots); ok("git_branch", r is not None and len(str(r)) > 0)


# ================================================================
# GROUP 4: Phase 4 Tools
# ================================================================
print("\n=== GROUP 4: Phase 4 Tools ===")

from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart import decode_panic, monitor_uart
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references

# replace_text
rt = f"{TEST_DIR}/rt.txt"
write_file(rt, "hello world\nfoo bar\nhello world\n", roots)
r = replace_text(rt, "hello", "hi", replace_all=False, allowed_roots=roots)
ok("replace_text (single)", "replacements" in r)
r = replace_text(rt, "foo", "baz", replace_all=True, allowed_roots=roots)
ok("replace_text (replace_all)", "replacements" in r)
r = replace_text(rt, "NONEXISTENT_XYZ", "xxx", allowed_roots=roots)
ok("replace_text (no match)", contains(r, "not found", "0"))

# patch_file
pt = f"{TEST_DIR}/pt.txt"
write_file(pt, "line A\nline B\nline C\n", roots)
diff = "--- a/pt.txt\n+++ b/pt.txt\n@@ -1,3 +1,3 @@\n-line A\n+line A mod\n line B\n line C\n"
r = patch_file(pt, diff, allowed_roots=roots); ok("patch_file", contains(r, "applied", "success"))

# decode_panic
r = decode_panic("GDBStub Init\nabort() was called at PC 0x400d1234 on core 0\n")
ok("decode_panic (abort)", contains(r, "panic_detected", "true"))
r = decode_panic("GDBStub Init\nLoadProhibited: A load operation prohibited by PMP.\nEXCVADDR: 0x00000000\n")
ok("decode_panic (LoadProhibited)", contains(r, "load", "prohibited", "panic"))
r = decode_panic("GDBStub Init\nBrownOut: VDD voltage dropped\n")
ok("decode_panic (BrownOut)", contains(r, "brownout", "panic"))
r = decode_panic("GDBStub Init\nTaskWDT: Task watchdog got triggered\n")
ok("decode_panic (TaskWDT)", contains(r, "taskwdt", "watchdog", "panic"))
r = decode_panic("Normal boot\nHello world\n")
ok("decode_panic (no panic)", contains(r, "panic_detected", "false"))

# find_symbol
r = find_symbol("create_server", project_path=P, allowed_roots=roots)
ok("find_symbol (create_server)", r is not None and len(str(r)) > 0)
r = find_symbol("NONEXISTENT_XYZ_12345", project_path=P, allowed_roots=roots)
ok("find_symbol (not found)", contains(r, "not found", "could not", "none"))

# find_references
r = find_references("create_server", project_path=P, allowed_roots=roots)
ok("find_references", r is not None)


# ================================================================
# GROUP 5: Serial Tools
# ================================================================
print("\n=== GROUP 5: Serial Tools ===")

from esp_workspace_mcp.tools.serial_tools import list_serial_ports

r = list_serial_ports(allowed_roots=roots); ok("list_serial_ports", r is not None)
ok("ESP at /dev/ttyACM0", "/dev/ttyACM0" in str(r) or "ttyACM" in str(r))

try:
    shutil.rmtree(TEST_DIR, ignore_errors=True)
except:
    pass


# ================================================================
# GROUP 6: ESP-IDF & Diagnostics
# ================================================================
print("\n=== GROUP 6: ESP-IDF & Diagnostics ===")

from esp_workspace_mcp.tools.diagnostics import get_idf_version, get_project_info, get_connected_devices
from esp_workspace_mcp.tools.esp_idf import idf_sdkconfig, parse_build_output, idf_size

r = get_idf_version(allowed_roots=roots)
ok("get_idf_version", r is not None)
r = get_project_info(project_dir=P, allowed_roots=roots)
ok("get_project_info", r is not None)
r = idf_sdkconfig(project_dir=P, allowed_roots=roots)
ok("idf_sdkconfig", r is not None)
r = parse_build_output("[1000/1000] Linking executable.elf\n")
ok("parse_build_output", r is not None)
r = parse_build_output("main.cpp:42:10: error: 'x' was not declared\n")
ok("parse_build_output (error)", "error" in r.lower())
r = get_connected_devices(allowed_roots=roots)
ok("get_connected_devices", r is not None)


# ================================================================
# GROUP 7: Search Tools
# ================================================================
print("\n=== GROUP 7: Search Tools ===")

from esp_workspace_mcp.tools.search import grep, find_files

r = grep("create_server", path=P, allowed_roots=roots, file_pattern="*.py", max_results=10)
ok("grep", r is not None and len(str(r)) > 0)
r = find_files("*.py", path=P, allowed_roots=roots)
ok("find_files", r is not None and len(str(r)) > 0)


# ================================================================
# GROUP 8: ESP Device (monitor only, no flashing)
# ================================================================
print("\n=== GROUP 8: ESP Device (monitor only) ===")

if os.path.exists("/dev/ttyACM0"):
    ok("ESP device present", True)
    try:
        r = monitor_uart("/dev/ttyACM0", 115200, duration=2, filter_pattern=None, allowed_roots=[])
        ok("monitor_uart (2s)", r is not None)
    except Exception as e:
        ok("monitor_uart (2s)", False, str(e)[:100])
else:
    skip("ESP device", "No /dev/ttyACM0")
    skip("monitor_uart", "No device")


# ================================================================
# SUMMARY
# ================================================================
print("\n" + "=" * 60)
print(f"  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
denom = max(passed + failed, 1)
print(f"  Score:  {passed}/{denom} ({100*passed//denom}%)")

sys.exit(0 if failed == 0 else 1)
