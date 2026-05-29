"""CLI entry points for esp-workspace-mcp."""

import argparse
import os
import pathlib
import secrets
import sys

# TOML support: tomllib in 3.11+, tomli_w for writing
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        print("Install tomli for Python < 3.11: pip install tomli")
        sys.exit(1)

try:
    import tomli_w
except ImportError:
    tomli_w = None

DEFAULT_CONFIG_DIR = pathlib.Path.home() / ".config" / "esp-workspace"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"


def generate_config(path: pathlib.Path, interactive: bool = True) -> dict:
    """Generate a configuration file."""
    if interactive:
        print("=== esp-workspace MCP Server Configuration ===\n")
        token = input("Bearer token (leave blank to generate random): ").strip()
        if not token:
            token = secrets.token_urlsafe(48)
            print(f"Generated token: {token}")
        host = input("Bind host [0.0.0.0]: ").strip() or "0.0.0.0"
        port_s = input("Bind port [8765]: ").strip() or "8765"
        port = int(port_s)
        roots_s = input("Allowed path roots (comma-separated) [~/AIRcableLLC]: ").strip()
        if not roots_s:
            roots_s = str(pathlib.Path.home() / "AIRcableLLC")
        roots = [r.strip() for r in roots_s.split(",")]
        projects_s = input("ESP project directories (comma-separated) []: ").strip()
        projects = [p.strip() for p in projects_s.split(",") if p.strip()]
        wish = input("Default WISH_PRODUCT []: ").strip()
    else:
        token = secrets.token_urlsafe(48)
        host = "0.0.0.0"
        port = 8765
        roots = [str(pathlib.Path.home() / "AIRcableLLC")]
        projects = []
        wish = ""

    cfg = {
        "server": {"host": host, "port": port, "token": token, "log_level": "INFO"},
        "security": {"allowed_roots": roots},
        "esp": {"project_dirs": projects, "wish_product": wish},
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    if tomli_w:
        with open(path, "wb") as f:
            tomli_w.dump(cfg, f)
    else:
        # Fallback: write as .env format
        env_path = path.with_suffix(".env")
        with open(env_path, "w") as f:
            f.write(f"MCP_API_TOKEN={token}\n")
            f.write(f"MCP_HOST={host}\n")
            f.write(f"MCP_PORT={port}\n")
            f.write(f"MCP_ALLOWED_ROOTS={','.join(roots)}\n")
            f.write(f"MCP_WISH_PRODUCT={wish}\n")
        print(f"Wrote .env format to {env_path}")

    print(f"\nConfig written to {path}")
    if interactive:
        print("\nAdd this to your Hermes MCP config.yaml:")
        print(f"  esp-workspace:")
        print(f'    url: "http://{host}:{port}/sse"')
        print(f'    transport: sse')
        print(f'    headers:')
        print(f'      Authorization: "Bearer {token}"')
        print(f'    enabled: true')
    return cfg


def load_config_toml(path: pathlib.Path) -> dict:
    """Load config from TOML or convert from .env."""
    if path.exists():
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
        return cfg
    # Try .env fallback
    env_path = path.with_suffix(".env")
    if env_path.exists():
        from dotenv import dotenv_values
        vals = dotenv_values(env_path)
        return {
            "server": {
                "host": vals.get("MCP_HOST", "0.0.0.0"),
                "port": int(vals.get("MCP_PORT", 8765)),
                "token": vals.get("MCP_API_TOKEN", ""),
            },
            "security": {
                "allowed_roots": vals.get("MCP_ALLOWED_ROOTS", "").split(","),
            },
            "esp": {
                "wish_product": vals.get("MCP_WISH_PRODUCT", ""),
                "project_dirs": [],
            },
        }
    return None


def cmd_configure(args):
    """Run interactive configuration wizard."""
    path = pathlib.Path(args.config) if args.config else DEFAULT_CONFIG_FILE
    generate_config(path, interactive=True)


def cmd_init(args):
    """Generate default config file non-interactively."""
    path = pathlib.Path(args.config) if args.config else DEFAULT_CONFIG_FILE
    generate_config(path, interactive=False)


def cmd_start(args):
    """Start the MCP server from config file."""
    import subprocess
    import shutil

    path = pathlib.Path(args.config) if args.config else DEFAULT_CONFIG_FILE
    cfg = load_config_toml(path)
    if not cfg:
        print(f"No config found at {path}")
        print("Run 'esp-workspace-mcp configure' first.")
        sys.exit(1)

    server_cfg = cfg.get("server", {})
    sec_cfg = cfg.get("security", {})
    esp_cfg = cfg.get("esp", {})

    env = os.environ.copy()
    env["MCP_API_TOKEN"] = server_cfg.get("token", "")
    env["MCP_HOST"] = server_cfg.get("host", "0.0.0.0")
    env["MCP_PORT"] = str(server_cfg.get("port", 8765))
    env["MCP_LOG_LEVEL"] = server_cfg.get("log_level", "INFO")
    roots = sec_cfg.get("allowed_roots", [])
    env["MCP_ALLOWED_ROOTS"] = ",".join(roots)
    env["MCP_WISH_PRODUCT"] = esp_cfg.get("wish_product", "")
    projects = esp_cfg.get("project_dirs", [])
    if projects:
        env["MCP_PROJECT_DIRS"] = ",".join(projects)

    # Find run_server.py relative to this package
    pkg_dir = pathlib.Path(__file__).parent.parent
    run_server = pkg_dir / "run_server.py"

    if not run_server.exists():
        print(f"Cannot find run_server.py at {run_server}")
        print("Are you running from a pip install? Use 'esp-workspace-mcp start' from the repo root.")
        sys.exit(1)

    # Use the venv python if available
    venv_python = pkg_dir / ".venv" / "bin" / "python"
    if venv_python.exists():
        python = str(venv_python)
    else:
        python = sys.executable

    os.execve(python, [python, str(run_server)], env)


def cmd_run(args):
    """Direct server start (backward-compatible with python run_server.py)."""
    # Just set env from args and exec run_server.py
    env = os.environ.copy()
    if args.token:
        env["MCP_API_TOKEN"] = args.token
    if args.host:
        env["MCP_HOST"] = args.host
    if args.port:
        env["MCP_PORT"] = str(args.port)
    if args.roots:
        env["MCP_ALLOWED_ROOTS"] = args.roots

    pkg_dir = pathlib.Path(__file__).parent.parent
    run_server = pkg_dir / "run_server.py"
    venv_python = pkg_dir / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    os.execve(python, [python, str(run_server)], env)


def main():
    """Main entry point: esp-workspace-mcp start | configure | init"""
    parser = argparse.ArgumentParser(
        prog="esp-workspace-mcp",
        description="ESP-Workspace MCP Server — autonomous firmware development for AI agents",
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    start_p = sub.add_parser("start", help="Start server from config file")
    start_p.add_argument("--config", type=str, default=None, help="Path to config.toml")

    configure_p = sub.add_parser("configure", help="Interactive configuration wizard")
    configure_p.add_argument("--config", type=str, default=None)

    init_p = sub.add_parser("init", help="Generate default config")
    init_p.add_argument("--config", type=str, default=None)

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "configure":
        cmd_configure(args)
    elif args.command == "init":
        cmd_init(args)
    else:
        parser.print_help()


def cli_configure():
    """Entry point for esp-workspace-mcp-configure."""
    parser = argparse.ArgumentParser(prog="esp-workspace-mcp-configure")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    cmd_configure(args)


def cli_init():
    """Entry point for esp-workspace-mcp-init."""
    parser = argparse.ArgumentParser(prog="esp-workspace-mcp-init")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    cmd_init(args)
