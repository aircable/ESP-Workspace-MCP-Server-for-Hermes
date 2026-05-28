# SPDX-FileCopyrightText: 2026 contributors
# SPDX-License-Identifier: Apache-2.0

"""Configuration: load and validate environment at startup."""

import os
import sys
from typing import List
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server settings loaded from environment / .env."""

    # Authentication
    MCP_API_TOKEN: str = ""

    # Network
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8765

    # Logging
    MCP_LOG_LEVEL: str = "INFO"

    # Filesystem sandbox
    MCP_ALLOWED_ROOTS: str = "/home/juergen/AIRcableLLC"

    # ESP-IDF / EIM
    MCP_WISH_PRODUCT: str = ""
    MCP_IDF_PATH: str = ""
    MCP_EIM_PATH: str = "eim"

    # Shell/safety
    MCP_DEFAULT_TIMEOUT: int = 30
    MCP_MAX_TIMEOUT: int = 300
    MCP_OUTPUT_LIMIT: int = 51200  # 50 KB

    # Job management
    MCP_JOB_TTL_SECONDS: int = 3600  # 1 hour

    @property
    def allowed_roots(self) -> List[str]:
        return [r.strip() for r in self.MCP_ALLOWED_ROOTS.split(",") if r.strip()]


def load_settings(env_file: str = ".env") -> Settings:
    """Load settings from .env file and environment. Fail fast on missing required vars."""
    load_dotenv(env_file)
    settings = Settings()

    # Ensure at least one allowed root exists
    for root in settings.allowed_roots:
        if not os.path.isdir(root):
            print(f"WARNING: Allowed root does not exist: {root}", file=sys.stderr)

    return settings
