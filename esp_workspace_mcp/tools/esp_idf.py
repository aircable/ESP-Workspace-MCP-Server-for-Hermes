"""ESP-IDF MCP tools: build, flash, and manage ESP-IDF projects via eim."""
import os
import re
import json
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
    
    # Clean environment - eim handles PATH setup
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


def parse_build_output(output: str) -> str:
    """Parse build output into structured errors and warnings.
    
    Args:
        output: Raw build output text from idf.py build
        
    Returns:
        JSON string with errors, warnings arrays and summary
    """
    errors = []
    warnings = []
    
    # Pattern: file:line:column: error: message
    error_pattern = re.compile(
        r'^(.+?):(\d+):(\d+)?\s*:\s*(?:error|fatal error)\s*:\s*(.+)$',
        re.IGNORECASE
    )
    # Pattern: file:line:column: warning: message
    warning_pattern = re.compile(
        r'^(.+?):(\d+):(\d+)?\s*:\s*warning\s*:\s*(.+)$',
        re.IGNORECASE
    )
    # Pattern: undefined reference to `symbol`
    undef_pattern = re.compile(
        r'undefined reference to\s*[`\'"](\w+)[`\'"]'
    )
    # Pattern: multiple definition of `symbol`
    multi_def_pattern = re.compile(
        r'multiple definition of\s*[`\'"](\w+)[`\'"]'
    )
    # Pattern: section `.text' will not fit in region
    section_pattern = re.compile(
        r"section\s+[`'\"](.+?)[`'\"]\s+will\s+not\s+fit\s+in\s+region\s+[`'\"](.+?)[`'\"]"
    )
    
    for line in output.splitlines():
        # Check error pattern
        m = error_pattern.match(line)
        if m:
            errors.append({
                'file': m.group(1).strip(),
                'line': int(m.group(2)),
                'column': int(m.group(3)) if m.group(3) else 0,
                'message': m.group(4).strip(),
                'severity': 'error',
            })
            continue
        
        # Check warning pattern
        m = warning_pattern.match(line)
        if m:
            warnings.append({
                'file': m.group(1).strip(),
                'line': int(m.group(2)),
                'column': int(m.group(3)) if m.group(3) else 0,
                'message': m.group(4).strip(),
                'severity': 'warning',
            })
            continue
        
        # Check undefined reference
        m = undef_pattern.search(line)
        if m:
            errors.append({
                'file': '',
                'line': 0,
                'message': f"undefined reference to `{m.group(1)}`",
                'severity': 'error',
                'context': line.strip(),
            })
            continue
        
        # Check multiple definition
        m = multi_def_pattern.search(line)
        if m:
            errors.append({
                'file': '',
                'line': 0,
                'message': f"multiple definition of `{m.group(1)}`",
                'severity': 'error',
                'context': line.strip(),
            })
            continue
        
        # Check section size
        m = section_pattern.search(line)
        if m:
            errors.append({
                'file': '',
                'line': 0,
                'message': f"section `{m.group(1)}` will not fit in region `{m.group(2)}`",
                'severity': 'error',
                'context': line.strip(),
            })
            continue
    
    # Check for overall build success/failure indicators
    build_failed = bool(errors)
    if not build_failed:
        for line in output.splitlines():
            if 'build failed' in line.lower() or 'error:' in line.lower():
                build_failed = True
                break
    
    summary_parts = []
    if errors:
        summary_parts.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}")
    if warnings:
        summary_parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
    
    if build_failed and errors:
        summary = f"Build failed with {', '.join(summary_parts)}"
    elif build_failed:
        summary = "Build failed"
    elif warnings:
        summary = f"Build succeeded with {', '.join(summary_parts)}"
    else:
        summary = "Build succeeded"
    
    result = {
        'build_success': not build_failed,
        'errors': errors,
        'warnings': warnings,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'summary': summary,
    }
    
    return json.dumps(result, indent=2)


def idf_size(project_dir: str, allowed_roots: List[str], wish_product: str = "",
             eim_path: str = "eim", timeout: int = 120) -> str:
    """Run idf.py size and return memory usage breakdown.
    
    Args:
        project_dir: Absolute path to the ESP-IDF project
        allowed_roots: Allowed filesystem roots
        wish_product: WISH_PRODUCT value
        eim_path: Path to eim executable
        timeout: Execution timeout
        
    Returns:
        JSON string with memory usage breakdown
    """
    import json as json_mod
    
    # Validate
    if not is_path_allowed(project_dir, allowed_roots):
        return json_mod.dumps({'success': False, 'error': f"Access denied: '{project_dir}'"})
    
    resolved = str(Path(project_dir).resolve())
    if not is_valid_project_dir(resolved):
        return json_mod.dumps({'success': False, 'error': f"Not a valid ESP-IDF project: {resolved}"})
    
    commands = "size"
    idf_cmd = f"idf.py {commands}"
    if wish_product:
        idf_cmd = f"WISH_PRODUCT={wish_product} {idf_cmd}"
    
    cmd = [eim_path, "run", idf_cmd]
    
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
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        stderr += f"\n[TIMEOUT: idf.py size exceeded {timeout}s]"
    
    if proc.returncode != 0:
        return json_mod.dumps({
            'success': False,
            'error': stderr or "idf.py size failed",
            'stdout': stdout,
        })
    
    # Parse idf.py size output
    memory_sections = {}
    total_flash = 0
    total_ram = 0
    
    size_pattern = re.compile(
        r'^\s*([\w.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)'
    )
    
    # Track section totals
    for line in stdout.splitlines():
        # Look for flash/ram section headers
        if 'Total' in line and 'used' in line:
            # Parse total line
            numbers = re.findall(r'\d+', line)
            if len(numbers) >= 2:
                total_flash = int(numbers[0])
                total_ram = int(numbers[1])
        
        m = size_pattern.match(line)
        if m:
            section = m.group(1)
            used = int(m.group(2))
            total = int(m.group(3)) if int(m.group(3)) > 0 else used
            memory_sections[section] = {
                'used': used,
                'total': total,
                'free': total - used if total > used else 0,
            }
    
    # Parse per-component breakdown if available
    components = {}
    in_components = False
    comp_pattern = re.compile(r'^\s*([\w./]+)\s+(\d+)\s*$')
    
    for line in stdout.splitlines():
        if '.text' in line and 'CODE' in line:
            continue  # Skip header lines
        
        m = comp_pattern.match(line)
        if m:
            comp_name = m.group(1).strip()
            comp_size = int(m.group(2))
            components[comp_name] = comp_size
    
    result = {
        'success': True,
        'total_flash': total_flash,
        'total_ram': total_ram,
        'memory_sections': memory_sections,
        'components': components,
        'raw_output': stdout if not memory_sections else '',
    }
    
    return json_mod.dumps(result, indent=2)


def idf_sdkconfig(project_dir: str, allowed_roots: List[str], wish_product: str = "",
                  eim_path: str = "eim", timeout: int = 60) -> str:
    """Run idf.py sdkconfig and return configuration data.
    
    Args:
        project_dir: Absolute path to the ESP-IDF project
        allowed_roots: Allowed filesystem roots
        wish_product: WISH_PRODUCT value
        eim_path: Path to eim executable
        timeout: Execution timeout
        
    Returns:
        JSON string with sdkconfig configuration
    """
    import json as json_mod
    
    # Validate
    if not is_path_allowed(project_dir, allowed_roots):
        return json_mod.dumps({'success': False, 'error': f"Access denied: '{project_dir}'"})
    
    resolved = str(Path(project_dir).resolve())
    if not is_valid_project_dir(resolved):
        return json_mod.dumps({'success': False, 'error': f"Not a valid ESP-IDF project: {resolved}"})
    
    sdkconfig_path = Path(resolved) / 'sdkconfig'
    config_lines = []
    
    if sdkconfig_path.exists():
        try:
            content = sdkconfig_path.read_text(encoding='utf-8')
            config = {}
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                if '=' in line:
                    key, _, value = line.partition('=')
                    config[key.strip()] = value.strip()
            
            result = {
                'success': True,
                'sdkconfig_path': str(sdkconfig_path),
                'config': config,
                'config_count': len(config),
            }
            return json_mod.dumps(result, indent=2)
        except Exception as e:
            return json_mod.dumps({
                'success': False,
                'error': f"Failed to read sdkconfig: {e}",
            })
    else:
        # sdkconfig doesn't exist yet - run idf.py sdkconfig to generate it
        commands = "sdkconfig"
        idf_cmd = f"idf.py {commands}"
        if wish_product:
            idf_cmd = f"WISH_PRODUCT={wish_product} {idf_cmd}"
        
        cmd = [eim_path, "run", idf_cmd]
        
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
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            stderr += f"\n[TIMEOUT: idf.py sdkconfig exceeded {timeout}s]"
        
        if proc.returncode != 0:
            return json_mod.dumps({
                'success': False,
                'error': stderr or "idf.py sdkconfig failed",
            })
        
        # Re-read the generated sdkconfig
        if sdkconfig_path.exists():
            try:
                content = sdkconfig_path.read_text(encoding='utf-8')
                config = {}
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        config[key.strip()] = value.strip()
                
                return json_mod.dumps({
                    'success': True,
                    'sdkconfig_path': str(sdkconfig_path),
                    'config': config,
                    'config_count': len(config),
                    'generated': True,
                }, indent=2)
            except Exception as e:
                return json_mod.dumps({
                    'success': False,
                    'error': f"Failed to read generated sdkconfig: {e}",
                })
        
        return json_mod.dumps({
            'success': False,
            'error': "sdkconfig file not found after generation",
        })


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
