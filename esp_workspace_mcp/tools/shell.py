"""Shell / process MCP tools: command execution."""
from typing import List, Optional

from esp_workspace_mcp.utils.security import validate_cwd, sanitize_env
from esp_workspace_mcp.utils.process import run_subprocess


def execute_command(
    cmd: str,
    allowed_roots: List[str],
    cwd: str = "",
    timeout: int = 30,
    max_timeout: int = 300,
    output_limit: int = 51200,
    job_mgr=None,
    background: bool = False,
    env_extras: dict = None,
    session_id: str = "",
    sessions: dict = None,
) -> dict:
    """Execute a shell command with full validation.
    
    Args:
        cmd: Shell command string
        allowed_roots: List of allowed filesystem roots
        cwd: Working directory (validated against allowed_roots)
        timeout: Execution timeout in seconds
        max_timeout: Maximum allowed timeout
        output_limit: Max output bytes
        job_mgr: JobManager instance for background execution
        background: If True, start as background job
        env_extras: Extra environment variables to pass to the command
        session_id: Optional session ID to inherit working directory from
        sessions: Active sessions dict (used with session_id)
        
    Returns:
        dict with keys: success, stdout, stderr, return_code, 
        (if background) also: job_id
    """
    import shlex
    
    # Resolve session working directory
    if session_id and sessions:
        session = sessions.get(session_id)
        if session:
            cwd = session.get('working_dir', cwd)
        else:
            return {'success': False, 'error': f'Session not found: {session_id}', 'return_code': -1}
    
    # Validate cwd
    if cwd:
        try:
            cwd = validate_cwd(cwd, allowed_roots)
        except ValueError as e:
            return {'success': False, 'error': str(e), 'return_code': -1}
    
    # Timeout clamping
    timeout = min(timeout, max_timeout)
    
    # Build environment
    env = sanitize_env()
    if env_extras:
        env.update(env_extras)
    
    # Parse command safely
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        return {'success': False, 'error': f'Invalid command syntax: {e}', 'return_code': -1}
    
    if not cmd_parts:
        return {'success': False, 'error': 'Empty command', 'return_code': -1}
    
    # Background execution
    if background and job_mgr:
        job_id = job_mgr.start_job(cmd_parts, cwd or '.', env, label=cmd[:60])
        return {
            'success': True,
            'background': True,
            'job_id': job_id,
            'message': f'Background job started: {job_id}',
        }
    
    # Foreground execution
    stdout, stderr, return_code = run_subprocess(
        cmd_parts, cwd or '.', env, timeout, output_limit
    )
    
    return {
        'success': return_code == 0,
        'stdout': stdout,
        'stderr': stderr,
        'return_code': return_code,
    }


def format_result(result: dict) -> str:
    """Format an execution result dict as a human-readable string."""
    lines = []
    
    if result.get('background'):
        lines.append(f"[Background Job] {result.get('message', '')}")
        lines.append(f"Job ID: {result.get('job_id', '')}")
        return '\n'.join(lines)
    
    status = "SUCCESS" if result.get('success') else "FAILED"
    lines.append(f"Status: {status} (exit code: {result.get('return_code', '?')})")
    
    stdout = result.get('stdout', '')
    stderr = result.get('stderr', '')
    
    if stdout:
        lines.append(f"\n--- STDOUT ---\n{stdout}")
    if stderr:
        lines.append(f"\n--- STDERR ---\n{stderr}")
    
    if not stdout and not stderr:
        lines.append("(no output)")
    
    return '\n'.join(lines)
