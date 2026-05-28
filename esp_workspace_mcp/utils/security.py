"""Security module: path sandboxing and validation."""
import os
from pathlib import Path
from typing import List, Optional


def safe_resolve(path: str, allowed_roots: List[str]) -> str:
    """Resolve a path to absolute and validate it's within allowed roots.
    
    Resolves symlinks and rejects '..' traversal escapes.
    Returns the resolved absolute path on success.
    Raises ValueError if path escapes allowed roots.
    """
    resolved = Path(path).resolve()
    
    for root in allowed_roots:
        root_resolved = Path(root).resolve()
        try:
            resolved.relative_to(root_resolved)
            return str(resolved)
        except ValueError:
            continue
    
    raise ValueError(
        f"Path '{path}' (resolved: '{resolved}') is not within allowed roots: {allowed_roots}"
    )


def is_path_allowed(path: str, allowed_roots: List[str]) -> bool:
    """Check if a path is within allowed roots. Returns True if allowed."""
    try:
        safe_resolve(path, allowed_roots)
        return True
    except ValueError:
        return False


def validate_cwd(cwd: str, allowed_roots: List[str]) -> str:
    """Validate and resolve a working directory. Returns resolved path or raises."""
    if not os.path.isdir(cwd):
        raise ValueError(f"Working directory does not exist: '{cwd}'")
    return safe_resolve(cwd, allowed_roots)


def sanitize_env(env: Optional[dict] = None) -> dict:
    """Return a sanitized copy of the environment.
    
    Strips dangerous variables that could compromise security.
    """
    if env is None:
        env = dict(os.environ)
    
    dangerous_keys = {
        'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PATH', 'PYTHONPATH',
        'PYTHONHOME', 'BASH_ENV', 'ENV', 'GCONV_PATH',
        'HOSTALIASES', 'TMPDIR',
    }
    
    # Keep PATH but sanitize it
    safe_env = {}
    for k, v in env.items():
        upper_k = k.upper()
        if upper_k in dangerous_keys:
            continue
        safe_env[k] = v
    
    # Set a safe default PATH
    safe_env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    
    return safe_env


def list_safe_dir(path: str, allowed_roots: List[str]) -> list:
    """List directory entries with metadata, validating path first."""
    resolved = safe_resolve(path, allowed_roots)
    
    entries = []
    try:
        for entry in os.scandir(resolved):
            try:
                stat = entry.stat(follow_symlinks=False)
                entries.append({
                    'name': entry.name,
                    'path': entry.path,
                    'type': 'directory' if entry.is_dir(follow_symlinks=False) else 
                            'file' if entry.is_file(follow_symlinks=False) else 'other',
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                })
            except (PermissionError, OSError):
                entries.append({
                    'name': entry.name,
                    'path': entry.path,
                    'type': 'inaccessible',
                    'size': 0,
                    'modified': 0,
                })
    except PermissionError:
        raise ValueError(f"Permission denied listing directory: '{path}'")
    
    return entries
