"""Filesystem MCP tools: path-validated file operations."""
import os
import glob as globmod
from typing import List
from pathlib import Path


MAX_OUTPUT = 51200  # 50 KB


def _truncate(output: str) -> str:
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[OUTPUT TRUNCATED]"
    return output


def read_file(path: str, allowed_roots: List[str], offset: int = 0, limit: int = 500) -> str:
    """Read a text file with optional offset and limit for pagination."""
    from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
    
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied — path not within allowed roots"
    
    resolved = safe_resolve(path, allowed_roots)
    
    if not os.path.isfile(resolved):
        return f"Error: Not a file: {resolved}"
    
    try:
        with open(resolved, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        total = len(lines)
        selected = lines[offset:offset + limit]
        
        numbered = ''.join(f"{offset + i + 1}|{line}" for i, line in enumerate(selected))
        
        header = f"File: {resolved} | Lines: {total} | Showing: {offset+1}-{offset+len(selected)}\n"
        return _truncate(header + numbered)
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str, allowed_roots: List[str]) -> str:
    """Write content to a file, creating parent directories if needed."""
    from esp_workspace_mcp.utils.security import is_path_allowed
    
    parent = str(Path(path).parent)
    if not is_path_allowed(parent, allowed_roots):
        return f"Error: Access denied — parent directory not within allowed roots"
    
    try:
        os.makedirs(parent, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        lines = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
        return f"Wrote {len(content)} bytes ({lines} lines) to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def append_file(path: str, content: str, allowed_roots: List[str]) -> str:
    """Append content to an existing file."""
    from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
    
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied — path not within allowed roots"
    
    resolved = safe_resolve(path, allowed_roots)
    
    if not os.path.isfile(resolved):
        return f"Error: File does not exist: {resolved}"
    
    try:
        with open(resolved, 'a', encoding='utf-8') as f:
            f.write(content)
        return f"Appended {len(content)} bytes to {resolved}"
    except Exception as e:
        return f"Error appending to file: {e}"


def list_dir(path: str, allowed_roots: List[str]) -> str:
    """List directory entries with type info."""
    from esp_workspace_mcp.utils.security import list_safe_dir
    
    try:
        entries = list_safe_dir(path, allowed_roots)
    except ValueError as e:
        return f"Error: {e}"
    
    lines = [f"Directory: {path} | {len(entries)} entries\n"]
    lines.append(f"{'TYPE':<12} {'SIZE':>10} {'NAME'}")
    lines.append("-" * 50)
    
    dirs = [e for e in entries if e['type'] == 'directory']
    files = [e for e in entries if e['type'] == 'file']
    other = [e for e in entries if e['type'] not in ('directory', 'file')]
    
    for e in sorted(dirs, key=lambda x: x['name'].lower()):
        lines.append(f"{'dir':<12} {'':>10} {e['name']}/")
    for e in sorted(files, key=lambda x: x['name'].lower()):
        lines.append(f"{'file':<12} {e['size']:>10} {e['name']}")
    for e in sorted(other, key=lambda x: x['name'].lower()):
        lines.append(f"{e['type']:<12} {'':>10} {e['name']}")
    
    return _truncate('\n'.join(lines))


def create_dir(path: str, allowed_roots: List[str]) -> str:
    """Create a directory recursively."""
    from esp_workspace_mcp.utils.security import is_path_allowed
    
    # Check parent is allowed
    parent = str(Path(path).parent)
    if not is_path_allowed(parent, allowed_roots):
        return f"Error: Access denied — parent directory not within allowed roots"
    
    try:
        os.makedirs(path, exist_ok=True)
        return f"Directory created: {path}"
    except Exception as e:
        return f"Error creating directory: {e}"


def delete_path(path: str, allowed_roots: List[str]) -> str:
    """Delete a file or empty directory."""
    import shutil
    from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
    
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied — path not within allowed roots"
    
    resolved = safe_resolve(path, allowed_roots)
    
    if os.path.isfile(resolved):
        try:
            os.remove(resolved)
            return f"Deleted file: {resolved}"
        except Exception as e:
            return f"Error deleting file: {e}"
    elif os.path.isdir(resolved):
        try:
            # Only allow deleting empty directories for safety
            if os.listdir(resolved):
                return f"Error: Directory not empty. Use shutil.rmtree via shell for recursive delete: {resolved}"
            os.rmdir(resolved)
            return f"Deleted empty directory: {resolved}"
        except Exception as e:
            return f"Error deleting directory: {e}"
    else:
        return f"Error: Path does not exist: {resolved}"


def file_stat(path: str, allowed_roots: List[str]) -> str:
    """Get file/directory metadata."""
    import stat as statmod
    from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
    
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied — path not within allowed roots"
    
    resolved = safe_resolve(path, allowed_roots)
    
    try:
        st = os.stat(resolved)
        mode = statmod.filemode(st.st_mode)
        type_ = 'directory' if statmod.S_ISDIR(st.st_mode) else 'file' if statmod.S_ISREG(st.st_mode) else 'other'
        
        import datetime
        mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        result = f"""Path: {resolved}
Type: {type_}
Size: {st.st_size} bytes
Permissions: {mode}
Modified: {mtime}
Owner UID: {st.st_uid}
Owner GID: {st.st_gid}"""
        return result
    except Exception as e:
        return f"Error getting file stat: {e}"


def glob_search(pattern: str, path: str, allowed_roots: List[str]) -> str:
    """Find files matching a glob pattern."""
    from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed
    
    if not is_path_allowed(path, allowed_roots):
        return f"Error: Access denied — path not within allowed roots"
    
    resolved = safe_resolve(path, allowed_roots)
    
    try:
        matches = globmod.glob(os.path.join(resolved, '**', pattern), recursive=True)
        
        # Filter to allowed roots
        valid = [m for m in matches if is_path_allowed(m, allowed_roots)]
        
        if not valid:
            return f"No matches for pattern '{pattern}' in {resolved}"
        
        lines = [f"Glob: {pattern} in {resolved} | {len(valid)} matches\n"]
        for m in sorted(valid):
            try:
                st = os.stat(m)
                lines.append(f"  {st.st_size:>10} bytes  {m}")
            except OSError:
                lines.append(f"  {'?':>10} bytes  {m}")
        
        return _truncate('\n'.join(lines))
    except Exception as e:
        return f"Error in glob search: {e}"
