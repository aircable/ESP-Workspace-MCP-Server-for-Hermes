"""
ESP-Workspace MCP Server - Tools Package
"""
import logging
logger = logging.getLogger(__name__)

# Phase 1
from .filesystem import (read_file, write_file, append_file, list_dir, create_dir, delete_path, file_stat, glob_search)
from .shell import execute_command
from .esp_idf import eim_run

# Phase 2
from .git_tools import (git_status, git_diff, git_commit, git_branch, git_log)
from .search import grep, find_files
from .serial_tools import list_serial_ports
from .diagnostics import (get_idf_version, get_project_info, get_connected_devices)

# Phase 3 (business logic in esp_idf.py)
from .esp_idf import parse_build_output, idf_size, idf_sdkconfig

# Phase 3 (sessions)
# from .session_tools import create_session, destroy_session, list_sessions  # Not standalone functions

# Phase 4
from .phase4_tools import replace_text, patch_file
from .phase4_symbols import find_symbol, find_references
from .phase4_uart import monitor_uart, decode_panic
from .phase4_debug import run_debug_cycle

logger.info("All tool modules imported successfully.")
