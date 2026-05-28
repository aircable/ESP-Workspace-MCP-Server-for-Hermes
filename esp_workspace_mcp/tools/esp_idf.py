"""ESP-IDF MCP tools: build, flash, and manage ESP-IDF projects via eim."""
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from esp_workspace_mcp.utils.security import is_path_allowed, safe_resolve


IDF_CMAKE_SIGNATURES = [
    r'include($ENV{IDF_PATH}/tools/cmake/project.cmake)',
    r'include($ENV{IDF_PATH}/tools/cmakev2/idf.cmake)',
]


def is_valid_project_dir(directory: str) -> bool:
    """Check if directory is a valid ESP-IDF project."""
    root = Path(directory)
    if not root.is_dir():
        return False
    cmakelists = root / 'CMakeLists.txt'
    if not cmakelists.is_file():
        return False
    try:
        content = cmakelists.read_text(encoding='utf-8')
        return any(sig in content for sig in IDF_CMAKE_SIGNATURES)
    except Exception:
        return False


def eim_run(
    project_dir: str,
    commands: str,
    allowed_roots: List[str],
    wish_product: str = "",
    eim_path: str = "eim",
    timeout: int = 600,
    output_limit: int = 51200,
) -> dict:
    """Run an ESP-IDF command via the Espressif Install Manager.
    
    This is the core function all other ESP-IDF tools use.
    
    Args:
        project_dir: Absolute path to the ESP-IDF project
        commands: idf.py arguments, e.g. "fullclean reconfigure build"
        allowed_roots: Allowed filesystem roots for sandboxing
        wish_product: WISH_PRODUCT value (e.g. "TargetS3")
        eim_path: Path to eim executable
        timeout: Maximum execution time in seconds
        output_limit: Maximum output bytes
        
    Returns:
        dict with keys: success, stdout, stderr, return_code
        
    Example:
        eim_run("/path/to/project", "reconfigure build", roots, "TargetS3")
        # Executes: eim run "WISH_PRODUCT=TargetS3 idf.py reconfigure build"
    """
    # Validate project directory
    if not is_path_allowed(project_dir, allowed_roots):
        return {
            'success': False,
            'error': f"Access denied: '{project_dir}' not within allowed roots",
            'return_code': -1,
        }
    
    resolved = str(Path(project_dir).resolve())
    
    if not is_valid_project_dir(resolved):
        return {
            'success': False,
            'error': f"Not a valid ESP-IDF project: {resolved} (missing CMakeLists.txt with IDF signature)",
            'return_code': -1,
        }
    
    # Build the command
    idf_cmd = f"idf.py {commands}"
    if wish_product:
        idf_cmd = f"WISH_PRODUCT={wish_product} {idf_cmd}"
    
    cmd = [eim_path, "run", idf_cmd]
    
    # Clean environment — eim handles PATH setup
    env = {
        'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
        'HOME': os.environ.get('HOME', '/tmp'),
    }
    if wish_product:
        env['WISH_PRODUCT'] = wish_product
    
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=resolved,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            stderr += f"\n[TIMEOUT: eim command exceeded {timeout}s and was killed]"
            return {'success': False, 'stdout': stdout, 'stderr': stderr, 'return_code': -1}
        
        # Truncate
        total = (stdout or "") + (stderr or "")
        if len(total) > output_limit:
            half = output_limit // 2
            stdout = (stdout or "")[:half]
            stderr = (stderr or "")[:half]
            stderr += f"\n[OUTPUT TRUNCATED at {output_limit} bytes]"
        
        return {
            'success': proc.returncode == 0,
            'stdout': stdout or "",
            'stderr': stderr or "",
            'return_code': proc.returncode,
        }
    
    except FileNotFoundError:
        return {
            'success': False,
            'error': f"eim not found at '{eim_path}'. Ensure Espressif Install Manager is installed.",
            'return_code': 127,
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'return_code': -1,
        }


def format_eim_result(result: dict) -> str:
    """Format an eim_run result dict as human-readable string."""
    lines = []
    
    if 'error' in result:
        lines.append(f"ERROR: {result['error']}")
    
    status = "SUCCESS" if result.get('success') else "FAILED"
    lines.append(f"Status: {status} (exit code: {result.get('return_code', '?')})")
    
    stdout = result.get('stdout', '')
    stderr = result.get('stderr', '')
    
    if stdout.strip():
        lines.append(f"\n--- STDOUT ---\n{stdout}")
    if stderr.strip():
        lines.append(f"\n--- STDERR ---\n{stderr}")
    
    if not stdout.strip() and not stderr.strip():
        lines.append("(no output)")
    
    return '\n'.join(lines)
