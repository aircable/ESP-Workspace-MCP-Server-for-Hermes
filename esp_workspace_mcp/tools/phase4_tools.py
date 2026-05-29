"""Phase 4.1: High-Level File Operations.

Reduces round-trips by combining read/modify/write into single calls.
"""
import json
import difflib
import re
import logging
from pathlib import Path

from esp_workspace_mcp.utils.security import is_path_allowed

logger = logging.getLogger(__name__)


def replace_text(path: str, search: str, replace: str, replace_all: bool = False, allowed_roots: list = None) -> str:
    """Find and replace text in a file.

    Replaces occurrences of the search string with the replacement string.
    This is a single-call alternative to read_file -> modify -> write_file.

    Args:
        path: Absolute path to the file
        search: Text to find
        replace: Replacement text
        replace_all: If True, replace all occurrences; if False (default), replace only the first
        allowed_roots: List of allowed filesystem roots
    """
    if allowed_roots and not is_path_allowed(path, allowed_roots):
        return json.dumps({"error": f"Path not allowed: {path}", "replacements": 0})

    p = Path(path)
    if not p.is_file():
        return json.dumps({"error": f"File not found: {path}", "replacements": 0})

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {e}", "replacements": 0})

    if replace_all:
        count = content.count(search)
        new_content = content.replace(search, replace)
    else:
        if search in content:
            count = 1
            new_content = content.replace(search, replace, 1)
        else:
            count = 0
            new_content = content

    if count == 0:
        return json.dumps({"replacements": 0, "message": "Search string not found", "path": path})

    try:
        p.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Cannot write file: {e}", "replacements": 0})

    # Generate diff preview
    diff_lines = list(difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{p.name}",
        tofile=f"b/{p.name}",
        n=3,
    ))

    return json.dumps({
        "replacements": count,
        "path": path,
        "original_length": len(content),
        "new_length": len(new_content),
        "diff_preview": "".join(diff_lines[:20]),
    }, indent=2)


def patch_file(path: str, diff: str, allowed_roots: list = None) -> str:
    """Apply a unified diff (patch) to a file.

    Args:
        path: Absolute path to the file to patch
        diff: Unified diff text (can be partial - just the hunks for this file)
        allowed_roots: List of allowed filesystem roots
    """
    if allowed_roots and not is_path_allowed(path, allowed_roots):
        return json.dumps({"error": f"Path not allowed: {path}", "applied": False})

    p = Path(path)
    if not p.is_file():
        return json.dumps({"error": f"File not found: {path}", "applied": False})

    try:
        original_content = p.read_text(encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {e}", "applied": False})

    try:
        new_content = _apply_unified_diff(original_content, diff)
        if new_content is None:
            return json.dumps({"error": "Could not parse or apply diff", "applied": False})

        p.write_text(new_content, encoding="utf-8")

        orig_lines = original_content.count("\n") + 1
        new_lines = new_content.count("\n") + 1

        return json.dumps({
            "applied": True,
            "path": path,
            "original_lines": orig_lines,
            "new_lines": new_lines,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Patch failed: {e}", "applied": False})

def _apply_unified_diff(original_content, diff):
    import re
    original_lines = original_content.splitlines(keepends=True)
    result_lines = list(original_lines)
    hunk_pattern = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
    diff_lines = diff.splitlines()
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        match = hunk_pattern.match(line)
        if match:
            old_start = int(match.group(1)) - 1
            new_lines = []
            old_count = 0
            i += 1
            while i < len(diff_lines):
                dl = diff_lines[i]
                if dl.startswith('@@') and hunk_pattern.match(dl):
                    break
                if dl.startswith('-'):
                    old_count += 1
                elif dl.startswith('+'):
                    new_lines.append(dl[1:])
                elif dl.startswith(' '):
                    old_count += 1
                    new_lines.append(dl[1:])
                i += 1
            end = old_start + old_count
            if old_start < 0 or end > len(result_lines):
                return None
            result_lines[old_start:end] = new_lines
        else:
            i += 1
    return "".join(result_lines)
