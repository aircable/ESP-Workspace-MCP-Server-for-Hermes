"""Process and shell execution utilities."""
import subprocess
import threading
import time
import uuid
from typing import Dict, Optional, Tuple


def run_subprocess(
    cmd: list,
    cwd: str,
    env: dict,
    timeout: int = 30,
    output_limit: int = 51200,
) -> Tuple[str, str, int]:
    """Run a subprocess command safely.
    
    Returns (stdout, stderr, return_code).
    Output truncated to output_limit bytes total.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
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
            stderr += f"\n[TIMEOUT: Command exceeded {timeout}s and was killed]"
            return (stdout or "", stderr or "", -1)
        
        # Truncate output
        total = (stdout or "") + (stderr or "")
        if len(total) > output_limit:
            half = output_limit // 2
            stdout = (stdout or "")[:half]
            stderr = (stderr or "")[:half]
            stderr += f"\n[OUTPUT TRUNCATED at {output_limit} bytes]"
        
        return (stdout or "", stderr or "", proc.returncode)
    
    except FileNotFoundError as e:
        return ("", f"Command not found: {e}", 127)
    except Exception as e:
        return ("", f"Execution error: {e}", -1)


class JobManager:
    """Manages background subprocess jobs."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self.jobs: Dict[str, dict] = {}
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
    
    def start_job(self, cmd: list, cwd: str, env: dict, label: str = "") -> str:
        """Start a background job. Returns job_id."""
        job_id = str(uuid.uuid4())[:8]
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with self._lock:
            self.jobs[job_id] = {
                'id': job_id,
                'proc': proc,
                'cmd': ' '.join(cmd),
                'cwd': cwd,
                'label': label,
                'status': 'running',
                'started': time.time(),
                'stdout_lines': [],
                'stderr_lines': [],
                'return_code': None,
            }
        
        # Start reader threads
        threading.Thread(
            target=self._reader, args=(job_id, proc.stdout, 'stdout_lines'), daemon=True
        ).start()
        threading.Thread(
            target=self._reader, args=(job_id, proc.stderr, 'stderr_lines'), daemon=True
        ).start()
        threading.Thread(
            target=self._waiter, args=(job_id, proc), daemon=True
        ).start()
        
        return job_id
    
    def _reader(self, job_id: str, stream, key: str):
        """Read lines from a stream into the job record."""
        try:
            for line in stream:
                with self._lock:
                    if job_id in self.jobs:
                        self.jobs[job_id][key].append(line)
        except Exception:
            pass
    
    def _waiter(self, job_id: str, proc):
        """Wait for process completion."""
        proc.wait()
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id]['return_code'] = proc.returncode
                self.jobs[job_id]['status'] = 'completed' if proc.returncode == 0 else 'failed'
    
    def get_output(self, job_id: str, offset: int = 0) -> dict:
        """Get combined output from a job starting at line offset."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return {'error': f'Job not found: {job_id}'}
            
            all_lines = job['stdout_lines'] + job['stderr_lines']
            total = len(all_lines)
            selected = all_lines[offset:]
            result = {
                'job_id': job_id,
                'status': job['status'],
                'cmd': job['cmd'],
                'return_code': job['return_code'],
                'total_lines': total,
                'offset': offset,
                'lines_returned': len(selected),
                'output': ''.join(selected),
            }
            return result
    
    def kill_job(self, job_id: str) -> dict:
        """Terminate a running job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return {'error': f'Job not found: {job_id}'}
            if job['status'] != 'running':
                return {'error': f'Job is not running: {job_id} (status={job["status"]})'}
            job['proc'].kill()
            job['status'] = 'killed'
            return {'job_id': job_id, 'status': 'killed'}
    
    def list_jobs(self) -> list:
        """List all jobs with their status."""
        with self._lock:
            result = []
            for job_id, job in self.jobs.items():
                result.append({
                    'id': job_id,
                    'cmd': job['cmd'][:80],
                    'status': job['status'],
                    'return_code': job['return_code'],
                    'started': job.get('started', 0),
                    'label': job.get('label', ''),
                    'output_lines': len(job['stdout_lines']) + len(job['stderr_lines']),
                })
            return result
    
    def cleanup_expired(self):
        """Remove jobs older than TTL."""
        now = time.time()
        with self._lock:
            expired = [
                jid for jid, j in self.jobs.items()
                if j['status'] in ('completed', 'failed', 'killed')
                and now - j.get('started', 0) > self.ttl_seconds
            ]
            for jid in expired:
                del self.jobs[jid]
