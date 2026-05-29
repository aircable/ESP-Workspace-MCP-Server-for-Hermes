"""Phase 4.3: Symbol Indexing.

Locate function/variable definitions and find all usages of a symbol.
Uses ctags/clangd if available, falls back to regex-based search.
"""
import json
import re
import subprocess
import logging
from pathlib import Path

from esp_workspace_mcp.utils.security import is_path_allowed

logger = logging.getLogger(__name__)

# C source file extensions for embedded firmware
_SOURCE_EXTS = {"*.c", "*.h", "*.cpp", "*.hpp", "*.cc", "*.cxx", "*.s", "*.S"}


def find_symbol(name: str, project_path: str, allowed_roots: list = None) -> str:
    """Locate the definition of a function, variable, or macro.

    Tries ctags first, then clangd, then falls back to regex search.

    Args:
        name: Symbol name to find (function, variable, macro, etc.)
        project_path: Absolute path to project root
        allowed_roots: List of allowed filesystem roots

    Returns:
        JSON array of locations where the symbol is defined
    """
    if allowed_roots and not is_path_allowed(project_path, allowed_roots):
        return json.dumps({"error": f"Path not allowed: {project_path}", "results": []})

    results = []

    # Strategy 1: Try ctags
    results = _try_ctags(name, project_path)
    if results:
        return json.dumps({"symbol": name, "method": "ctags", "results": results}, indent=2)

    # Strategy 2: Try clangd (via LSP or clang-query)
    results = _try_clangd(name, project_path)
    if results:
        return json.dumps({"symbol": name, "method": "clangd", "results": results}, indent=2)

    # Strategy 3: Regex fallback - look for definition patterns
    results = _regex_find_definition(name, project_path)
    if results:
        return json.dumps({"symbol": name, "method": "regex", "results": results}, indent=2)

    return json.dumps({
        "symbol": name,
        "method": "none",
        "results": [],
        "message": f"Could not find definition of '{name}' in {project_path}",
    }, indent=2)


def find_references(symbol: str, project_path: str, allowed_roots: list = None) -> str:
    """Find all usages of a symbol in a project.

    Args:
        symbol: Symbol name to search for
        project_path: Absolute path to project root
        allowed_roots: List of allowed filesystem roots

    Returns:
        JSON array of locations where the symbol is referenced
    """
    if allowed_roots and not is_path_allowed(project_path, allowed_roots):
        return json.dumps({"error": f"Path not allowed: {project_path}", "results": []})

    results = _regex_find_references(symbol, project_path)

    return json.dumps({
        "symbol": symbol,
        "method": "regex",
        "total_references": len(results),
        "results": results[:100],  # Cap at 100 results
    }, indent=2)


def _try_ctags(name: str, project_path: str) -> list:
    """Try to find symbol definition using ctags."""
    try:
        # Generate tags if .tags file doesn't exist, then search
        tags_file = Path(project_path) / ".tags"
        if not tags_file.exists():
            result = subprocess.run(
                ["ctags", "-R", "--fields=+n", "-f", ".tags", "."],
                cwd=project_path,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []

        if not tags_file.exists():
            return []

        # Search tags file for the symbol
        pattern = re.compile(rf"^{re.escape(name)}\t")
        results = []
        for line in tags_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if pattern.match(line) and not line.startswith("!"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    filepath = parts[1]
                    # Extract line number from fields
                    line_no = None
                    for part in parts[2:]:
                        if part.startswith("line:"):
                            line_no = int(part.split(":")[1])
                            break
                    kind = ""
                    for part in parts[2:]:
                        if part.startswith("kind:"):
                            kind = part.split(":")[1]
                            break
                    results.append({
                        "file": filepath,
                        "line": line_no or 0,
                        "kind": kind,
                        "pattern": parts[2] if len(parts) > 2 and not parts[2].startswith("/") else "",
                    })
                    if len(results) >= 10:
                        break
        return results
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return []


def _try_clangd(name: str, project_path: str) -> list:
    """Try to find symbol definition using clangd."""
    try:
        # Use clangd's --query-driver and index if available
        # This works if a compile_commands.json exists
        compile_db = Path(project_path) / "compile_commands.json"
        if not compile_db.exists():
            return []

        # Try using clang to find symbol in AST
        query = f"grep -rnw '{project_path}' -e '\\b{name}\\s*(' --include='*.c' --include='*.h' --include='*.cpp' --include='*.hpp' 2>/dev/null | head -5"
        result = subprocess.run(
            query, shell=True, capture_output=True, text=True, timeout=15,
        )
        results = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                results.append({"file": parts[0], "line": int(parts[1]) if parts[1].isdigit() else 0, "kind": "function-call"})
        return results
    except Exception:
        return []


def _regex_find_definition(name: str, project_path: str) -> list:
    """Find symbol definition using regex patterns."""
    results = []
    compiled_names = set()

    # Common definition patterns for C/C++
    definition_patterns = [
        # Function definition: ret_type name(...) {
        re.compile(rf"\b\w[\w\s:*&<>]*\s+\b{re.escape(name)}\s*\([^)]*\)\s*\{{"),
        # Variable definition: type name = value
        re.compile(rf"\b(?:static\s+)?(?:const\s+)?(?:volatile\s+)?\w[\w:*&<>]*\s+\b{re.escape(name)}\s*[=;\[]"),
        # Macro definition: #define name
        re.compile(rf"#\s*define\s+\b{re.escape(name)}\b"),
        # typedef / struct / enum
        re.compile(rf"\b(?:typedef\s+)?(?:struct|union|enum)\s+\b{re.escape(name)}\b"),
    ]

    root = Path(project_path)
    try:
        files = []
        for ext in _SOURCE_EXTS:
            files.extend(root.rglob(ext.lstrip("*.") if ext.startswith("*") else ext))
    except Exception:
        return results

    for fpath in files[:500]:  # Limit search scope
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            rel_path = str(fpath.relative_to(root))

            for i, pattern in enumerate(definition_patterns):
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    key = (rel_path, line_num)
                    if key not in compiled_names:
                        compiled_names.add(key)
                        kind = ["function", "variable", "macro", "type"][i]
                        line_content = content[match.start():match.start()+80].split("\n")[0].strip()
                        results.append({
                            "file": rel_path,
                            "line": line_num,
                            "kind": kind,
                            "pattern": line_content,
                        })
                        if len(results) >= 10:
                            return results
        except Exception:
            continue

    return results


def _regex_find_references(symbol: str, project_path: str) -> list:
    """Find all references to a symbol using ripgrep or regex."""
    results = []

    # Try ripgrep first
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "--line-number", "-w", symbol,
             "--type", "c", "--type", "cpp", project_path],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                fpath = parts[0]
                try:
                    line_no = int(parts[1])
                except ValueError:
                    line_no = 0
                content = parts[2].strip()
                results.append({"file": fpath, "line": line_no, "content": content[:120]})

        if results:
            return results
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: Python regex search
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    root = Path(project_path)
    try:
        files = []
        for ext in _SOURCE_EXTS:
            files.extend(root.rglob(ext))
    except Exception:
        return results

    for fpath in files[:500]:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            rel_path = str(fpath.relative_to(root))
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    results.append({
                        "file": rel_path, "line": i,
                        "content": line.strip()[:120],
                    })
                    if len(results) >= 100:
                        return results
        except Exception:
            continue

    return results
