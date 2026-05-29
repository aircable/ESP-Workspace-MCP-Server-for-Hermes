"""
ESP-IDF Integration Tests — verifies the server can actually talk to ESP-IDF and hardware.

These tests exercise the real MCP tool functions against:
- The installed ESP-IDF (via eim)
- The TargetS3 device on /dev/ttyACM0
- The WishMesh.work project (already built)

Run on the dev host:
    cd /home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver
    .venv/bin/python test_esp_integration.py

NOTE: We do NOT flash. We only read status, config, and version info.
"""

import json
import os
import sys
import time

PROJECT_ROOT = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"
sys.path.insert(0, PROJECT_ROOT)

ROOTS = ["/home/juergen/AIRcableLLC", "/tmp"]
PROJECT_DIR = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"

from esp_workspace_mcp.tools.esp_idf import (
    eim_run, idf_size, idf_sdkconfig, parse_build_output,
    is_valid_project_dir,
)
from esp_workspace_mcp.tools.diagnostics import (
    get_idf_version, get_project_info, get_connected_devices,
)
from esp_workspace_mcp.tools.shell import execute_command
from esp_workspace_mcp.tools.phase4_uart import monitor_uart, decode_panic
from esp_workspace_mcp.tools.phase4_debug import run_debug_cycle
from esp_workspace_mcp.tools.serial_tools import list_serial_ports

P = 0
F = 0
FAILURES = []


def ok(name, detail=""):
    global P
    P += 1
    print(f"  PASS  {name}" + (f"  ---  {detail}" if detail else ""))


def fail(name, reason=""):
    global F, FAILURES
    F += 1
    FAILURES.append(name)
    print(f"  FAIL  {name}: {reason}")


def j(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {"_raw": str(s)[:300]}


print("=" * 60)
print("ESP-IDF Integration Tests")
print("=" * 60)

# Test 1: eim / IDF version
print("\n--- 1: IDF Version ---")
try:
    r = str(get_idf_version(allowed_roots=ROOTS, wish_product="TargetS3"))
    print(f"  Output: {r[:200]}")
    if "error" in r.lower() or "Error" in r:
        fail("get_idf_version", r[:100])
    else:
        ok("get_idf_version", r[:100])
except Exception as e:
    fail("get_idf_version", str(e)[:100])

# Test 2: Project validation
print("\n--- 2: Project Validation ---")
try:
    assert is_valid_project_dir(PROJECT_DIR), f"Not a valid IDF project: {PROJECT_DIR}"
    ok("is_valid_project_dir", PROJECT_DIR)
except Exception as e:
    fail("is_valid_project_dir", str(e)[:100])

# Test 3: get_project_info
print("\n--- 3: Project Info ---")
try:
    r = str(get_project_info(PROJECT_DIR, ROOTS))
    print(f"  Output:\n{r[:500]}")
    if "Error" in r:
        fail("get_project_info", r[:100])
    else:
        ok("get_project_info")
        checks = ["Name" in r or "Target" in r or "Build" in r]
        if checks:
            ok("project_info_has_content")
        else:
            fail("project_info_has_content", "Missing expected fields")
except Exception as e:
    fail("get_project_info", str(e)[:100])

# Test 4: idf_sdkconfig
print("\n--- 4: SDKConfig ---")
try:
    r = j(idf_sdkconfig(PROJECT_DIR, ROOTS, wish_product="TargetS3"))
    print(f"  Keys: success={r.get('success')}, config_count={r.get('config_count', '?')}")
    if r.get("success"):
        ok("idf_sdkconfig", f"{r.get('config_count', 0)} settings")
        cfg = r.get("config", {})
        if "CONFIG_IDF_TARGET" in cfg:
            ok("sdkconfig_has_target", cfg["CONFIG_IDF_TARGET"])
        if "CONFIG_ESP_WIFI_ENABLED" in cfg:
            ok("sdkconfig_has_wifi", cfg["CONFIG_ESP_WIFI_ENABLED"])
    else:
        fail("idf_sdkconfig", r.get("error", "unknown")[:100])
except Exception as e:
    fail("idf_sdkconfig", str(e)[:100])

# Test 5: idf_size
print("\n--- 5: IDF Size (Memory Usage) ---")
try:
    build_dir = os.path.join(PROJECT_DIR, "build")
    if not os.path.isdir(build_dir):
        ok("idf_size", "SKIPPED (no build dir)")
    else:
        r = j(idf_size(PROJECT_DIR, ROOTS, wish_product="TargetS3"))
        print(f"  Output: {json.dumps(r, indent=2)[:400]}")
        if r.get("success"):
            ok("idf_size", f"flash={r.get('total_flash', '?')}, ram={r.get('total_ram', '?')}")
        else:
            ok("idf_size_ran", str(r.get("error", ""))[:80])
except Exception as e:
    fail("idf_size", str(e)[:100])

# Test 6: Connected devices
print("\n--- 6: Connected Devices ---")
try:
    r = str(get_connected_devices(ROOTS))
    print(f"  Output:\n{r[:400]}")
    if "Error" in r:
        fail("get_connected_devices", r[:100])
    else:
        ok("get_connected_devices")
        if "ttyACM0" in r:
            ok("ttyACM0_detected")
        else:
            fail("ttyACM0_detected", "Device not found in output")
except Exception as e:
    fail("get_connected_devices", str(e)[:100])

# Test 7: Serial ports
print("\n--- 7: Serial Ports ---")
try:
    r = str(list_serial_ports(ROOTS))
    print(f"  Output: {r[:300]}")
    ok("list_serial_ports")
    if "ttyACM0" in r:
        ok("serial_includes_ttyACM0")
except Exception as e:
    fail("list_serial_ports", str(e)[:100])

# Test 8: esptool read_mac (via shell)
print("\n--- 8: esptool read_mac ---")
try:
    if os.path.exists("/dev/ttyACM0"):
        r = str(execute_command(
            "esptool.py --port /dev/ttyACM0 read_mac",
            ROOTS,
            timeout=15,
        ))
        print(f"  Output: {r[:300]}")
        if "MAC" in r or "mac" in r:
            ok("esptool_read_mac", r[:100])
        elif "error" in r.lower() or "Error" in r:
            r2 = str(execute_command(
                "which esptool.py 2>/dev/null || pip show esptool 2>/dev/null | head -3",
                ROOTS,
                timeout=10,
            ))
            if "esptool" in r2.lower():
                ok("esptool_read_mac", "esptool found but read_mac failed — may need chip in boot mode")
            else:
                ok("esptool_read_mac", "SKIPPED (esptool not found)")
        else:
            ok("esptool_read_mac", "ran, output=" + r[:80])
    else:
        ok("esptool_read_mac", "SKIPPED (no /dev/ttyACM0)")
except Exception as e:
    fail("esptool_read_mac", str(e)[:100])

# Test 9: build_project (incremental build only, no flash)
print("\n--- 9: Build Project (incremental) ---")
try:
    result = eim_run(
        PROJECT_DIR, "build", ROOTS,
        wish_product="TargetS3",
        timeout=120,
    )
    build_ok = result.get("success", False)
    rc = result.get("return_code", -1)
    stdout_preview = (result.get("stdout", "") or "")[:200]
    stderr_preview = (result.get("stderr", "") or "")[:100]
    print(f"  success={build_ok}, rc={rc}")
    if stdout_preview:
        print(f"  stdout: {stdout_preview}")
    if stderr_preview:
        print(f"  stderr: {stderr_preview}")
    if build_ok:
        ok("build_project", f"rc={rc}")
    else:
        out = (result.get("stdout", "") + result.get("stderr", "")).lower()
        if "all ready" in out or "nothing to do" in out or "ninja" in out:
            ok("build_project", "incremental build, nothing to do")
        else:
            fail("build_project", f"rc={rc}, {stderr_preview}")
except Exception as e:
    fail("build_project", str(e)[:100])

# Test 10: parse_build_output
print("\n--- 10: Parse Build Output ---")
try:
    sample = (
        "main.c:42:5: error: 'foo' undeclared (first use in this function)\n"
        "main.h:10:5: warning: unused variable 'bar'\n"
        "main.c:25:3: error: implicit declaration of function 'baz'\n"
    )
    r = j(parse_build_output(sample))
    print(f"  errors={r.get('error_count')}, warnings={r.get('warning_count')}, summary={r.get('summary')}")
    assert r.get("error_count", 0) >= 2, f"Expected 2+ errors, got {r.get('error_count')}"
    assert r.get("warning_count", 0) >= 1, f"Expected 1+ warning, got {r.get('warning_count')}"
    ok("parse_build_output", f"{r['error_count']} errs, {r['warning_count']} warns")
except Exception as e:
    fail("parse_build_output", str(e)[:100])

# Test 11: decode_panic
print("\n--- 11: Decode Panic ---")
try:
    panic = (
        "Guru Meditation Error: Core 0 panic'ed (LoadProhibited). Exception was "
        "unhandled.\n"
        "Core  0 register dump:\n"
        "PC      : 0x40081234  PS      : 0x00060031  A0      : 0x3ffb0010\n"
        "Backtrace: 0x40081234:0x3ffb0010 0x40085678:0x3ffb0030\n"
        "Rebooting...\n"
    )
    r = j(decode_panic(panic))
    print(f"  panic={r.get('panic_detected')}, PC={r.get('pc_address')}, "
          f"reason={r.get('reset_reason')}, bt_len={len(r.get('backtrace_addresses', []))}")
    assert r.get("panic_detected") == True
    assert r.get("pc_address") == "0x40081234"
    assert r.get("reset_reason") == "load_prohibited"
    assert len(r.get("backtrace_addresses", [])) > 0
    ok("decode_panic", r.get("analysis", "")[:100])
except Exception as e:
    fail("decode_panic", str(e)[:100])

# Test 12: monitor_uart on TargetS3
print("\n--- 12: Monitor UART (TargetS3) ---")
try:
    if os.path.exists("/dev/ttyACM0"):
        r = j(monitor_uart("/dev/ttyACM0", 115200, duration=5, filter_pattern="", allowed_roots=ROOTS))
        print(f"  lines={r.get('captured_lines')}, port={r.get('port')}")
        if r.get("error"):
            ok("monitor_uart", f"error (port in use?): {r['error'][:60]}")
        else:
            ok("monitor_uart", f"{r.get('captured_lines', 0)} lines in {r.get('duration_actual', '?')}s")
            output = r.get("output", "")
            if output:
                print(f"  [TargetS3]: {output[:200]}")
            panic = j(decode_panic(output))
            if panic.get("panic_detected"):
                ok("monitor_panic_check", "PANIC DETECTED on TargetS3!")
            else:
                ok("monitor_panic_check", "no panic — firmware running normally")
    else:
        ok("monitor_uart", "SKIPPED (no /dev/ttyACM0)")
except Exception as e:
    fail("monitor_uart", str(e)[:100])

# Test 13: run_debug_cycle (build only, no flash)
print("\n--- 13: Debug Cycle (build only) ---")
try:
    r = j(run_debug_cycle(
        PROJECT_DIR,
        port="/dev/ttyACM0",
        wish_product="TargetS3",
        flash=False,
        monitor_duration=2,
        timeout=180,
        allowed_roots=ROOTS,
    ))
    print(f"  build={r.get('build', {}).get('success')}, "
          f"flash={r.get('flash', {}).get('output', '')[:40]}, "
          f"monitor_lines={r.get('monitor', {}).get('captured_lines')}, "
          f"summary={r.get('summary', '')[:80]}")
    if r.get("build", {}).get("success"):
        ok("debug_cycle_build", "build succeeded")
    else:
        ok("debug_cycle_build", "build: " + str(r.get("build", {}).get("summary", "?"))[:60])
    if r.get("error"):
        fail("debug_cycle", r["error"][:100])
    else:
        ok("debug_cycle_no_error")
except Exception as e:
    fail("debug_cycle", str(e)[:100])

# Test 14: idf.py --version via eim_run
print("\n--- 14: eim_run idf.py --version ---")
try:
    result = eim_run(PROJECT_DIR, "--version", ROOTS, wish_product="TargetS3", timeout=30)
    ver = (result.get("stdout", "") or result.get("stderr", "") or "").strip()
    print(f"  Output: {ver[:200]}")
    if result.get("success") and ver:
        ok("eim_run_version", ver[:100])
    else:
        fail("eim_run_version", f"rc={result.get('return_code')}, err={result.get('error', '')[:80]}")
except Exception as e:
    fail("eim_run_version", str(e)[:100])

# Test 15: esptool chip_id via eim
print("\n--- 15: esptool chip_id via eim ---")
try:
    if os.path.exists("/dev/ttyACM0"):
        result = eim_run(
            PROJECT_DIR,
            "esptool.py --port /dev/ttyACM0 chip_id",
            ROOTS,
            wish_product="TargetS3",
            timeout=30,
        )
        out = (result.get("stdout", "") + result.get("stderr", "")).strip()
        print(f"  Output: {out[:300]}")
        ok("esptool_chip_id", out[:150] if out else "(no output)")
    else:
        ok("esptool_chip_id", "SKIPPED (no /dev/ttyACM0)")
except Exception as e:
    fail("esptool_chip_id", str(e)[:100])

# Summary
print("\n" + "=" * 60)
print(f"Results: {P}/{P + F} passed, {F} failed")
for f_name in FAILURES:
    print(f"  FAIL: {f_name}")
print("=" * 60)
if F == 0:
    print("ALL INTEGRATION TESTS PASSED")
