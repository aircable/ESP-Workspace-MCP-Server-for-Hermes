"""Search tools: grep (regex search) and find_files (glob search)."""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List

from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed

logger = logging.getLogger(__name__)

MAX_RESULTS = 200
MAX_OUTPUT = 51200  # 50 KB


def _truncate(output: str) -> str:
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[OUTPUT TRUNCATED]"
    return output


def grep(
    pattern: str,
    path: str,
    allowed_roots: List[str],
    ignore_case: bool = False,
    file_pattern: str = "",
    max_results: int = MAX_RESULTS,
) -> str:
    """Search for a regex pattern inside files.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        allowed_roots: Allowed filesystem roots for sandboxing
        ignore_case: If True, perform case-insensitive search
        file_pattern: Glob pattern to filter files (e.g. '*.c', '*.h')
        max_results: Maximum number of matching lines to return

    Returns:
        Matching lines with file paths and line numbers
    """
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied: '{path}' is not within allowed roots"

    resolved = safe_resolve(path, allowed_roots)

    # Try ripgrep first, fall back to Python regex
    use_rg = False
    try:
        subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            timeout=5,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        use_rg = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if use_rg:
        return _grep_rg(pattern, resolved, ignore_case, file_pattern, max_results)
    else:
        return _grep_python(pattern, resolved, allowed_roots, ignore_case, file_pattern, max_results)


def _grep_rg(
    pattern: str,
    resolved: str,
    ignore_case: bool,
    file_pattern: str,
    max_results: int,
) -> str:
    """Use ripgrep for fast regex search."""
    import json

    cmd = [
        "rg",
        "--json",
        "--line-number",
        "--with-filename",
        "--no-heading",
        f"--max-count={max_results}",
    ]
    if ignore_case:
        cmd.append("--ignore-case")
    if file_pattern:
        cmd.extend(["--glob", file_pattern])

    cmd.extend(["--", pattern, resolved])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        lines = []
        count = 0
        for line in result.stdout.splitlines():
            if count >= max_results:
                break
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    file_path = data["data"]["path"]["text"]
                    line_num = data["data"]["line_number"]
                    text = data["data"]["lines"]["text"].rstrip("\n")
                    lines.append(f"{file_path}:{line_num}: {text}")
                    count += 1
            except (json.JSONDecodeError, KeyError):
                continue

        if lines:
            return _truncate("\n".join(lines))
        else:
            return "No matches found"

    except subprocess.TimeoutExpired:
        return "Error: Search timed out"
    except Exception as e:
        return f"Error searching: {e}"


def _grep_python(
    pattern: str,
    resolved: str,
    allowed_roots: List[str],
    ignore_case: bool,
    file_pattern: str,
    max_results: int,
) -> str:
    """Fallback: Python regex search."""
    try:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    ext_filter = ""
    if file_pattern and file_pattern.startswith("*."):
        ext_filter = file_pattern[1:]  # e.g. ".c"

    matches = []
    search_path = Path(resolved)

    if search_path.is_file():
        files = [search_path]
    else:
        if ext_filter:
            files = sorted(search_path.rglob(f"*{ext_filter}"))
        else:
            files = sorted(search_path.rglob("*"))

    for fpath in files:
        if len(matches) >= max_results:
            break
        if not fpath.is_file():
            continue

        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if len(matches) >= max_results:
                    break
                if regex.search(line):
                    rel = fpath.relative_to(search_path.parent) if fpath != search_path else fpath.name
                    matches.append(f"{rel}:{lineno}: {line.rstrip()}")
        except (PermissionError, OSError):
            continue

    if matches:
        return _truncate("\n".join(matches))
    else:
        return "No matches found"


def find_files(
    pattern: str,
    path: str,
    allowed_roots: List[str],
) -> str:
    """Find files matching a glob pattern (recursive).

    Args:
        pattern: Glob pattern, e.g. '*.c', '**/*.h', 'CMakeLists.txt'
        path: Directory to search in (must be within allowed roots)
        allowed_roots: Allowed filesystem roots for sandboxing

    Returns:
        Newline-separated list of matching file paths
    """
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied: '{path}' is not within allowed roots"

    resolved = safe_resolve(path, allowed_roots)

    if not os.path.isdir(resolved):
        return f"Error: Not a directory: '{resolved}'"

    try:
        matches = sorted(Path(resolved).rglob(pattern))
        matches = [str(m) for m in matches if m.is_file()]

        if matches:
            return _truncate("\n".join(matches))
        else:
            return "No files found"

    except Exception as e:
        return f"Error finding files: {e}"
