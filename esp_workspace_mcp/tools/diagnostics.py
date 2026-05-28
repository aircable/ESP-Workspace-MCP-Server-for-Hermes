"""Diagnostics tools: IDF version, project info, connected devices."""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List

from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
from esp_workspace_mcp.tools.esp_idf import is_valid_project_dir

logger = logging.getLogger(__name__)


def get_idf_version(
    allowed_roots: List[str],
    wish_product: str = "",
    eim_path: str = "eim",
) -> str:
    """Get the ESP-IDF version via eim.

    Args:
        allowed_roots: Allowed filesystem roots (unused but kept for API consistency)
        wish_product: WISH_PRODUCT value for the eim invocation
        eim_path: Path to the eim executable

    Returns:
        IDF version string or error message
    """
    try:
        cmd = [eim_path, "run"]
        if wish_product:
            cmd.append(f"WISH_PRODUCT={wish_product} idf.py --version")
        else:
            cmd.append("idf.py --version")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0:
            return f"ESP-IDF version: {output}"
        else:
            return f"Error getting IDF version (exit code {result.returncode}): {output}"

    except FileNotFoundError:
        return f"Error: eim not found at '{eim_path}'"
    except subprocess.TimeoutExpired:
        return "Error: IDF version check timed out"
    except Exception as e:
        return f"Error getting IDF version: {e}"


def get_project_info(project_dir: str, allowed_roots: List[str]) -> str:
    """Get project metadata: name, target, build directory status.

    Args:
        project_dir: Absolute path to the ESP-IDF project
        allowed_roots: Allowed filesystem roots for sandboxing

    Returns:
        Project info as formatted string
    """
    if not is_path_allowed(project_dir, allowed_roots):
        return f"Error: Access denied: '{project_dir}' is not within allowed roots"

    resolved = safe_resolve(project_dir, allowed_roots)

    if not os.path.isdir(resolved):
        return f"Error: Directory does not exist: '{resolved}'"

    if not is_valid_project_dir(resolved):
        return f"Error: Not a valid ESP-IDF project: '{resolved}'"

    lines = [f"Project: {resolved}", "=" * 60]

    # Project name from CMakeLists.txt
    cmake_path = Path(resolved) / "CMakeLists.txt"
    try:
        cmake_content = cmake_path.read_text(encoding="utf-8")
        name_match = re.search(r"project\(([^)]+)\)", cmake_content)
        if name_match:
            lines.append(f"Name: {name_match.group(1).strip()}")
    except Exception:
        pass

    # Target from sdkconfig
    sdkconfig_path = Path(resolved) / "sdkconfig"
    if sdkconfig_path.is_file():
        try:
            sdkconfig = sdkconfig_path.read_text(encoding="utf-8")
            target_match = re.search(r"CONFIG_IDF_TARGET=\"([^\"]+)\"", sdkconfig)
            if target_match:
                lines.append(f"Target: {target_match.group(1)}")

            # Build mode
            mode_match = re.search(r"CONFIG_COMPILER_OPTIMIZATION_LEVEL_(\w+)", sdkconfig)
            if mode_match:
                lines.append(f"Build mode: {mode_match.group(1).lower()}")

            # Bluetooth, WiFi, etc.
            features = []
            for feat_key, feat_name in [
                ("CONFIG_BT_ENABLED", "Bluetooth"),
                ("CONFIG_ESP_WIFI_ENABLED", "WiFi"),
                ("CONFIG_ETH_ENABLED", "Ethernet"),
                ("CONFIG_SPIFFS_ENABLED", "SPIFFS"),
                ("CONFIG_FATFS_ENABLED", "FATFS"),
            ]:
                if feat_key + "=y" in sdkconfig:
                    features.append(feat_name)
            if features:
                lines.append(f"Features: {', '.join(features)}")

        except Exception:
            pass
    else:
        lines.append("Target: not set (run set-target or reconfigure)")

    # Build directory status
    build_dir = Path(resolved) / "build"
    if build_dir.is_dir():
        try:
            # Count files and get total size
            file_count = sum(1 for _ in build_dir.rglob("*") if _.is_file())
            total_size = sum(f.stat().st_size for f in build_dir.rglob("*") if f.is_file())
            size_mb = total_size / (1024 * 1024)
            lines.append(f"Build dir: {file_count} files, {size_mb:.1f} MB")

            # Check for firmware binary
            for firmware in build_dir.rglob("*.bin"):
                fw_size = firmware.stat().st_size
                lines.append(f"Firmware: {firmware.relative_to(resolved)} ({fw_size} bytes)")
                break
        except Exception:
            lines.append("Build dir: exists")
    else:
        lines.append("Build dir: not built yet")

    # Count source files
    source_exts = {".c", ".h", ".cpp", ".S"}
    src_count = sum(
        1 for f in Path(resolved).rglob("*")
        if f.is_file() and f.suffix in source_exts
    )
    if src_count:
        lines.append(f"Source files: {src_count}")

    # sdkconfig.defaults
    defaults_path = Path(resolved) / "sdkconfig.defaults"
    if defaults_path.is_file():
        try:
            defaults = defaults_path.read_text(encoding="utf-8")
            line_count = len([l for l in defaults.splitlines() if l.strip() and not l.startswith("#")])
            lines.append(f"sdkconfig.defaults: {line_count} active settings")
        except Exception:
            pass

    # WISH_PRODUCT
    wish_product_file = Path(resolved) / "WISH_PRODUCT"
    if wish_product_file.is_file():
        try:
            wp = wish_product_file.read_text(encoding="utf-8").strip()
            lines.append(f"WISH_PRODUCT: {wp}")
        except Exception:
            pass

    return "\n".join(lines)


def get_connected_devices(allowed_roots: List[str] = None) -> str:
    """List connected USB/serial devices.

    Args:
        allowed_roots: Unused, kept for API consistency

    Returns:
        Formatted list of connected devices
    """
    devices = {}

    # Method 1: USB devices via lsusb
    try:
        result = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        if result.returncode == 0:
            usb_lines = result.stdout.strip().splitlines()
            for line in usb_lines:
                if line.strip():
                    devices.setdefault("USB", []).append(line.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: Serial ports
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        if ports:
            devices.setdefault("Serial", [])
            for p in sorted(ports, key=lambda x: x.device):
                devices["Serial"].append(f"{p.device}: {p.description} [{p.hwid}]")
    except ImportError:
        pass

    # Method 3: /dev/ttyUSB* and /dev/ttyACM*
    try:
        import glob
        tty_devices = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        if tty_devices:
            devices.setdefault("TTY", [])
            for dev in tty_devices:
                # Get permissions/owner
                try:
                    stat = os.stat(dev)
                    import pwd
                    owner = pwd.getpwuid(stat.st_uid).pw_name
                    devices["TTY"].append(f"{dev} (owner: {owner})")
                except (KeyError, OSError):
                    devices["TTY"].append(dev)
    except Exception:
        pass

    if not devices:
        return "No connected devices detected (or detection tools not available)"

    lines = ["Connected devices:", "=" * 60]
    for category, items in devices.items():
        lines.append(f"\n{category} ({len(items)}):")
        for item in items:
            lines.append(f"  {item}")

    return "\n".join(lines)
