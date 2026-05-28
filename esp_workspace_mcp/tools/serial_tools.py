"""Serial / UART tools: list ports, open/read/write/close sessions."""

import logging
import threading
import time
from typing import Dict, Optional

from esp_workspace_mcp.utils.security import is_path_allowed

logger = logging.getLogger(__name__)

# Session registry — maps session_id to SerialSession
_serial_sessions: Dict[str, "SerialSession"] = {}
_session_lock = threading.Lock()
_id_counter = 0


class SerialSession:
    """Wraps a pyserial connection with buffering."""

    def __init__(self, port: str, baudrate: int, allowed_roots: list):
        # Validate port path if it's a device path
        if port.startswith("/"):
            if not is_path_allowed(port, allowed_roots):
                # Still allow common serial port paths
                allowed_prefixes = ("/dev/tty", "/dev/cu.", "/dev/serial")
                if not any(port.startswith(p) for p in allowed_prefixes):
                    raise ValueError(f"Access denied for port: {port}")

        import serial  # Deferred import — pyserial may not always be installed

        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.1,  # Non-blocking reads
            write_timeout=2,
        )
        self.port = port
        self.baudrate = baudrate
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._error = None

    def read(self, timeout: float = 5) -> str:
        """Read available output from the serial port."""
        if self._error:
            return f"Error: {self._error}"
        if not self.ser or not self.ser.is_open:
            return "Error: Port is closed"

        self._check_read_errors()

        try:
            deadline = time.time() + timeout
            chunks = []

            while time.time() < deadline:
                in_waiting = self.ser.in_waiting
                if in_waiting > 0:
                    data = self.ser.read(in_waiting)
                    if data:
                        self._buffer.extend(data)
                        # Decode what we can, keep incomplete multi-byte chars in buffer
                        try:
                            text = self._buffer.decode("utf-8")
                            self._buffer.clear()
                            chunks.append(text)
                        except UnicodeDecodeError:
                            # Try decoding up to the last complete char
                            for i in range(1, min(4, len(self._buffer))):
                                try:
                                    text = self._buffer[:-i].decode("utf-8")
                                    remainder = self._buffer[-i:]
                                    self._buffer.clear()
                                    self._buffer.extend(remainder)
                                    chunks.append(text)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            else:
                                pass  # Need more data
                elif chunks:
                    break  # We got some data and nothing more is waiting
                else:
                    time.sleep(0.05)

            if chunks:
                result = "".join(chunks)
                # Truncate to keep output manageable
                if len(result) > 50000:
                    return result[:50000] + "\n[OUTPUT TRUNCATED]"
                return result
            else:
                return "(no output received)"

        except Exception as e:
            self._error = str(e)
            self._check_read_errors()
            return f"Error reading: {e}"

    def _check_read_errors(self):
        """Check if the device got disconnected."""
        # Check is_open alone is not enough, the port has to be polled
        try:
            # Will raise if device disappeared
            self.ser.in_waiting
            return None
        except Exception as e:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self._error = f"Device disconnected: {e}"
            return self._error

    def write(self, data: str) -> str:
        """Write data to the serial port."""
        if self._error:
            return f"Error: {self._error}"
        if not self.ser or not self.ser.is_open:
            return "Error: Port is closed"

        try:
            # Append newline if not present (common for REPL-style interfaces)
            if not data.endswith("\n"):
                data += "\n"
            self.ser.write(data.encode("utf-8"))
            self.ser.flush()
            return f"Wrote {len(data)} bytes"
        except Exception as e:
            self._error = str(e)
            return f"Error writing: {e}"

    def close(self):
        """Close the serial connection."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass

    @property
    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "is_open": self.is_open,
            "error": self._error,
        }


def _next_session_id() -> str:
    global _id_counter
    _id_counter += 1
    return f"serial-{_id_counter:04d}"


def list_serial_ports(allowed_roots: list) -> str:
    """Enumerate available serial ports.

    Args:
        allowed_roots: Allowed filesystem roots (unused but kept for API consistency)

    Returns:
        Newline-separated list of available serial ports with descriptions
    """
    try:
        import serial.tools.list_ports
    except ImportError:
        return "Error: pyserial is not installed: pip install pyserial"

    try:
        ports = serial.tools.list_ports.comports()
        if not ports:
            return "No serial ports found"

        lines = [f"Serial ports: {len(ports)} found\n"]
        for p in sorted(ports, key=lambda x: x.device):
            desc = p.description or "Unknown"
            hwid = p.hwid or ""
            lines.append(f"  {p.device:<20} {desc}  [{hwid}]")

        return "\n".join(lines)

    except Exception as e:
        return f"Error listing serial ports: {e}"


def serial_open(port: str, baud: int = 115200, allowed_roots: list = None) -> str:
    """Open a serial connection and return a session ID.

    Args:
        port: Serial port path (e.g. '/dev/ttyUSB0')
        baud: Baud rate (default: 115200)
        allowed_roots: Allowed filesystem roots for path validation

    Returns:
        Session ID string or error message
    """
    if allowed_roots is None:
        allowed_roots = []

    try:
        session = SerialSession(port, baud, allowed_roots)
        sid = _next_session_id()

        with _session_lock:
            _serial_sessions[sid] = session

        return f"Serial session opened: {sid} (port={port}, baud={baud})"

    except ValueError as e:
        return f"Error: {e}"
    except ImportError:
        return "Error: pyserial is not installed: pip install pyserial"
    except Exception as e:
        return f"Error opening serial port: {e}"


def serial_read(session_id: str, timeout: float = 5) -> str:
    """Read available output from a serial session.

    Args:
        session_id: Session ID from serial_open
        timeout: Read timeout in seconds (default: 5)

    Returns:
        Serial output as text, or error message
    """
    with _session_lock:
        session = _serial_sessions.get(session_id)

    if session is None:
        return f"Error: Session not found: {session_id}"

    result = session.read(timeout)
    return f"Session: {session_id}\n{result}"


def serial_write(session_id: str, data: str) -> str:
    """Write data to a serial session.

    Args:
        session_id: Session ID from serial_open
        data: Text data to send

    Returns:
        Result message
    """
    with _session_lock:
        session = _serial_sessions.get(session_id)

    if session is None:
        return f"Error: Session not found: {session_id}"

    result = session.write(data)
    return f"Session: {session_id}\n{result}"


def serial_close(session_id: str) -> str:
    """Close a serial session.

    Args:
        session_id: Session ID from serial_open

    Returns:
        Result message
    """
    with _session_lock:
        session = _serial_sessions.pop(session_id, None)

    if session is None:
        return f"Error: Session not found: {session_id}"

    try:
        session.close()
        return f"Session closed: {session_id}"
    except Exception as e:
        return f"Error closing session: {e}"


def serial_sessions(allowed_roots: list = None) -> str:
    """List all active serial sessions.

    Args:
        allowed_roots: Unused, kept for API consistency

    Returns:
        Formatted list of active sessions
    """
    with _session_lock:
        sessions = list(_serial_sessions.items())

    if not sessions:
        return "No active serial sessions"

    lines = [f"Active serial sessions: {len(sessions)}\n"]
    for sid, session in sessions:
        info = session.to_dict()
        status = "open" if info["is_open"] else "closed"
        if info["error"]:
            status = f"error: {info['error']}"
        lines.append(f"  {sid}: port={info['port']} baud={info['baudrate']} [{status}]")

    return "\n".join(lines)
