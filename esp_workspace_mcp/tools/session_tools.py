"""Session MCP tools: persistent working sessions across tool calls."""
import time
import threading
from typing import Dict, Optional


class SessionManager:
    """Manages persistent working sessions for AI agents.
    
    Each session maintains a working directory and metadata,
    allowing tools like run_command to inherit context.
    """

    def __init__(self, ttl_seconds: int = 7200):
        self._sessions: Dict[str, dict] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def create_session(self, session_id: str, working_dir: str = "") -> dict:
        """Create a new session.
        
        Args:
            session_id: Unique identifier for the session
            working_dir: Optional absolute path to use as default working directory
            
        Returns:
            dict with session info
        """
        with self._lock:
            if session_id in self._sessions:
                return {
                    'session_id': session_id,
                    'status': 'exists',
                    'working_dir': self._sessions[session_id]['working_dir'],
                    'created': self._sessions[session_id]['created'],
                }
            
            session = {
                'session_id': session_id,
                'working_dir': working_dir,
                'created': time.time(),
                'last_used': time.time(),
                'status': 'active',
            }
            self._sessions[session_id] = session
            return {
                'session_id': session_id,
                'status': 'created',
                'working_dir': working_dir,
                'created': session['created'],
            }

    def destroy_session(self, session_id: str) -> dict:
        """Destroy a session and clean up resources.
        
        Args:
            session_id: Session to destroy
            
        Returns:
            dict with result info
        """
        with self._lock:
            if session_id not in self._sessions:
                return {'error': f'Session not found: {session_id}'}
            
            del self._sessions[session_id]
            return {'session_id': session_id, 'status': 'destroyed'}

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session info by ID."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session['last_used'] = time.time()
            return session

    def list_sessions(self) -> list:
        """List all active sessions."""
        with self._lock:
            result = []
            now = time.time()
            for sid, s in self._sessions.items():
                result.append({
                    'session_id': sid,
                    'working_dir': s['working_dir'],
                    'status': s['status'],
                    'created': s['created'],
                    'last_used': s['last_used'],
                    'age_seconds': int(now - s['created']),
                    'idle_seconds': int(now - s['last_used']),
                })
            return result

    def get_all(self) -> dict:
        """Return raw sessions dict (for use in tool handlers)."""
        with self._lock:
            return dict(self._sessions)

    def cleanup_expired(self):
        """Remove sessions older than TTL."""
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.get('last_used', s['created']) > self._ttl_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
