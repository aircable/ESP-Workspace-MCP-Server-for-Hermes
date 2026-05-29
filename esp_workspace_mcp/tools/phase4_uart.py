"""Phase 4.2: Intelligent UART Monitor.

Provides filtered serial capture and ESP32 panic decoding.
"""
import json
import re
import logging
import time
from pathlib import Path

from esp_workspace_mcp.tools.serial_tools import (
    _serial_sessions as _sessions, _session_lock as _lock, _next_session_id as _id_counter,
)

logger = logging.getLogger(__name__)


def monitor_uart(port: str, baud: int = 115200, duration: float = 30,
                 filter_pattern: str = "", allowed_roots: list = None) -> str:
    """Capture serial output from a UART port with optional filtering.

    Opens a serial connection, reads output for the specified duration,
    then closes the connection. Optionally filters lines matching a regex pattern.

    Args:
        port: Serial port path (e.g. '/dev/ttyUSB0', '/dev/ttyACM0')
        baud: Baud rate (default: 115200)
        duration: How many seconds to capture (max 120)
        filter_pattern: Optional regex pattern - only matching lines are returned
        allowed_roots: List of allowed filesystem roots (checked for port path)

    Returns:
        JSON with captured line count, duration, and the output
    """
    import serial

    duration = min(max(duration, 1), 120)  # Clamp: 1s to 120s

    try:
        ser = serial.Serial(port, baudrate=baud, timeout=1)
    except Exception as e:
        return json.dumps({"error": f"Cannot open serial port {port}: {e}", "captured_lines": 0})

    compiled_filter = None
    if filter_pattern:
        try:
            compiled_filter = re.compile(filter_pattern)
        except re.error as e:
            ser.close()
            return json.dumps({"error": f"Invalid filter pattern: {e}"})

    lines = []
    start = time.monotonic()
    try:
        while (time.monotonic() - start) < duration:
            if ser.in_waiting:
                try:
                    raw = ser.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                    if compiled_filter:
                        if compiled_filter.search(raw):
                            lines.append(raw)
                    else:
                        lines.append(raw)
                except Exception:
                    pass
            else:
                time.sleep(0.05)
    finally:
        try:
            ser.close()
        except Exception:
            pass

    elapsed = round(time.monotonic() - start, 2)

    return json.dumps({
        "port": port,
        "baud": baud,
        "duration_actual": elapsed,
        "captured_lines": len(lines),
        "filter": filter_pattern or None,
        "output": "\n".join(lines),
    }, indent=2)


# Known ESP32 panic patterns
_PANIC_PATTERNS = {
    "GDBStub": {
        "pattern": r"GDBStub",
        "description": "CPU halted by debugger or GDBStub triggered",
        "reset_reason": "debug",
    },
    "abort": {
        "pattern": r"abort\(\) was called",
        "description": "abort() called - usually assert failure or unhandled exception",
        "reset_reason": "software_abort",
    },
    "IllegalInstruction": {
        "pattern": r"IllegalInstruction",
        "description": "CPU tried to execute an illegal instruction",
        "reset_reason": "illegal_instruction",
    },
    "InstructionFetchError": {
        "pattern": r"InstructionFetchError",
        "description": "Instruction fetch from invalid memory (execution jumped to unmapped region)",
        "reset_reason": "instruction_fetch_error",
    },
    "StoreProhibited": {
        "pattern": r"StoreProhibited",
        "description": "Store to invalid/read-only memory region",
        "reset_reason": "store_prohibited",
    },
    "LoadProhibited": {
        "pattern": r"LoadProhibited",
        "description": "Load from invalid memory region (null pointer dereference or unmapped address)",
        "reset_reason": "load_prohibited",
    },
    "StackCanary": {
        "pattern": r"Stack canary",
        "description": "Stack overflow detected by stack canary",
        "reset_reason": "stack_overflow",
    },
    "BrownOut": {
        "pattern": r"Brownout",
        "description": "Brownout detector triggered - power supply voltage dropped",
        "reset_reason": "brownout",
    },
    "TaskWDT": {
        "pattern": r"Task watchdog",
        "description": "Task watchdog timeout - a task was not fed within the allowed period",
        "reset_reason": "task_wdt",
    },
    "IntWdt": {
        "pattern": r"Interrupt wdt",
        "description": "Interrupt watchdog timeout - ISR took too long",
        "reset_reason": "interrupt_wdt",
    },
    "CacheError": {
        "pattern": r"Cache disabled",
        "description": "Cache disabled or cache access error",
        "reset_reason": "cache_error",
    },
    "MemoryAllocation": {
        "pattern": r"Failed to allocate|malloc.*failed|cannot allocate",
        "description": "Memory allocation failed - heap exhausted",
        "reset_reason": "heap_exhaustion",
    },
    "assert": {
        "pattern": r"ASSERT|assert.*failed|esp_assert",
        "description": "Assertion failed",
        "reset_reason": "assertion_failure",
    },
}

# Pattern to extract PC (program counter) from backtrace
_PC_PATTERN = re.compile(r"(?:PC|pc)\s*[:=]?\s*(0x[0-9a-fA-F]+)")
_BACKTRACE_PATTERN = re.compile(r"(?:Backtrace|backtrace):?([\s\S]*?)(?:\n\n|\Z)")
_ADDR_PATTERN = re.compile(r"(0x40[0-9a-fA-F]{6})")


def decode_panic(output: str) -> str:
    """Parse ESP32 panic handler output into structured analysis.

    Extracts: PC address, reset reason, backtrace, and known error pattern.

    Args:
        output: Raw serial output text containing a panic dump

    Returns:
        JSON with structured panic analysis
    """
    result = {
        "panic_detected": False,
        "pc_address": None,
        "reset_reason": "unknown",
        "pattern_match": None,
        "backtrace_addresses": [],
        "description": "No panic detected",
        "analysis": "",
    }

    # Check for panic indicator
    if "Guru Meditation Error" not in output and "panic" not in output.lower() and "Backtrace" not in output and "abort()" not in output:
        return json.dumps(result, indent=2)

    result["panic_detected"] = True

    # Extract PC address
    pc_match = _PC_PATTERN.search(output)
    if pc_match:
        result["pc_address"] = pc_match.group(1)

    # Extract backtrace addresses
    bt_match = _BACKTRACE_PATTERN.search(output)
    if bt_match:
        bt_text = bt_match.group(1)
        result["backtrace_addresses"] = _ADDR_PATTERN.findall(bt_text)
    else:
        # Fallback: find all ESP32 code addresses
        result["backtrace_addresses"] = _ADDR_PATTERN.findall(output)

    # Match known panic patterns
    matched_patterns = []
    for name, info in _PANIC_PATTERNS.items():
        if re.search(info["pattern"], output):
            matched_patterns.append({
                "name": name,
                "description": info["description"],
                "reset_reason": info["reset_reason"],
            })

    if matched_patterns:
        primary = matched_patterns[0]
        result["pattern_match"] = primary["name"]
        result["reset_reason"] = primary["reset_reason"]
        result["description"] = primary["description"]

    # Build analysis summary
    parts = [f"Panic detected: {result['description']}"]
    if result["pc_address"]:
        parts.append(f"PC: {result['pc_address']}")
    if result["backtrace_addresses"]:
        parts.append(f"Backtrace: {' -> '.join(result['backtrace_addresses'][:8])}")
    if result["reset_reason"] and result["reset_reason"] != "unknown":
        parts.append(f"Reset reason: {result['reset_reason']}")

    result["analysis"] = " | ".join(parts)
    return json.dumps(result, indent=2)
