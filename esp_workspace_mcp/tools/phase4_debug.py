"""Phase 4.4: Autonomous Debug Cycle.

The keystone tool: build + flash + monitor + analyze in one call.
"""
import json
import logging
import tempfile
import os

from esp_workspace_mcp.utils.security import is_path_allowed
from esp_workspace_mcp.utils.process import JobManager
from esp_workspace_mcp.tools.esp_idf import eim_run, parse_build_output
from esp_workspace_mcp.tools.phase4_uart import monitor_uart, decode_panic

logger = logging.getLogger(__name__)


def run_debug_cycle(project_path: str, port: str, wish_product: str = "",
                    target: str = "", flash: bool = True,
                    monitor_duration: float = 15,
                    eim_path: str = "eim",
                    timeout: int = 600,
                    allowed_roots: list = None) -> str:
    """Run a complete debug cycle: build + flash + monitor + analyze.

    This is the keystone tool for autonomous firmware development.
    It compiles, flashes, captures serial output, and analyzes for panics or errors.

    Args:
        project_path: Absolute path to the ESP-IDF project
        port: Serial port for flashing and monitoring (e.g. '/dev/ttyUSB0')
        wish_product: Target hardware product (e.g. 'TargetS3')
        target: Target chip (e.g. 'esp32s3'). If empty, uses sdkconfig default.
        flash: If True, flash the firmware. If False, skip flash step.
        monitor_duration: Seconds of serial capture after flash (default: 15, max: 60)
        eim_path: Path to eim executable
        timeout: Maximum seconds for the entire cycle
        allowed_roots: List of allowed filesystem roots

    Returns:
        JSON with structured results for build, flash, monitor, and analysis
    """
    import time

    if allowed_roots and not is_path_allowed(project_path, allowed_roots):
        return json.dumps({"error": f"Path not allowed: {project_path}"})

    result = {
        "project": project_path,
        "port": port,
        "wish_product": wish_product,
        "target": target,
        "build": {"success": False, "output": "", "errors": [], "warnings": []},
        "flash": {"success": False, "output": ""},
        "monitor": {"output": "", "captured_lines": 0, "panic_detected": False, "panic_analysis": None},
        "summary": "",
    }

    start = time.monotonic()

    # ---- Step 1: Build ----
    logger.info(f"[debug_cycle] Building {project_path} with WISH_PRODUCT={wish_product}")
    build_result = eim_run(
        project_path, "build",
        allowed_roots,
        wish_product=wish_product,
        eim_path=eim_path,
        timeout=min(timeout, 600),
    )

    result["build"]["success"] = build_result.get("success", False)
    result["build"]["output"] = build_result.get("output", "")

    # Parse build output for structured diagnostics
    if result["build"]["output"]:
        try:
            parsed = json.loads(parse_build_output(result["build"]["output"]))
            result["build"]["errors"] = parsed.get("errors", [])
            result["build"]["warnings"] = parsed.get("warnings", [])
            result["build"]["summary"] = parsed.get("summary", "")
        except (json.JSONDecodeError, TypeError):
            pass

    if not result["build"]["success"]:
        result["summary"] = (
            f"Build failed with {len(result['build']['errors'])} error(s)"
            + (f", {len(result['build']['warnings'])} warning(s)" if result["build"]["warnings"] else "")
        )
        return json.dumps(result, indent=2)

    # Check time budget
    elapsed = time.monotonic() - start
    remaining = timeout - elapsed
    if remaining < 5:
        result["summary"] = "Build succeeded but no time remaining for flash/monitor"
        return json.dumps(result, indent=2)

    # ---- Step 2: Flash ----
    if flash:
        logger.info(f"[debug_cycle] Flashing to {port}")
        flash_result = eim_run(
            project_path, f"flash -p {port}",
            allowed_roots,
            wish_product=wish_product,
            eim_path=eim_path,
            timeout=min(int(remaining), 120),
        )
        result["flash"]["success"] = flash_result.get("success", False)
        result["flash"]["output"] = flash_result.get("output", "")

        if not result["flash"]["success"]:
            result["summary"] = "Build succeeded but flash failed"
            return json.dumps(result, indent=2)

        # Check time budget again
        elapsed = time.monotonic() - start
        remaining = timeout - elapsed
        if remaining < 2:
            result["summary"] = "Build + flash succeeded but no time remaining for monitor"
            return json.dumps(result, indent=2)
    else:
        result["flash"]["output"] = "Skipped (flash=False)"

    # ---- Step 3: Monitor ----
    monitor_timeout = min(monitor_duration, remaining, 60)
    logger.info(f"[debug_cycle] Monitoring {port} for {monitor_timeout}s")

    monitor_result = monitor_uart(
        port=port,
        baud=115200,
        duration=monitor_timeout,
        filter_pattern="",
        allowed_roots=allowed_roots,
    )

    try:
        monitor_data = json.loads(monitor_result)
        result["monitor"]["output"] = monitor_data.get("output", "")
        result["monitor"]["captured_lines"] = monitor_data.get("captured_lines", 0)
    except (json.JSONDecodeError, TypeError):
        result["monitor"]["output"] = monitor_result

    # ---- Step 4: Analyze ----
    if result["monitor"]["output"]:
        panic_result = decode_panic(result["monitor"]["output"])
        try:
            panic_data = json.loads(panic_result)
            result["monitor"]["panic_detected"] = panic_data.get("panic_detected", False)
            result["monitor"]["panic_analysis"] = panic_data
        except (json.JSONDecodeError, TypeError):
            pass

    # ---- Summary ----
    parts = ["Build: OK"]
    if flash:
        parts.append("Flash: OK" if result["flash"]["success"] else "Flash: FAILED")
    parts.append(f"Monitor: {result['monitor']['captured_lines']} lines captured")
    if result["monitor"]["panic_detected"]:
        panic_info = result["monitor"].get("panic_analysis", {})
        parts.append(f"PANIC: {panic_info.get('description', 'Unknown')}")
    result["summary"] = " | ".join(parts)

    return json.dumps(result, indent=2)
