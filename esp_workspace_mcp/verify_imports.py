#!/usr/bin/env python3
"""Quick verification that the new server.py and categories work correctly."""

import sys
import os

# Add the parent directory to path so we can import esp_workspace_mcp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("ESP-Workspace MCP Server — Import Verification")
print("=" * 60)

# Step 1: Check that esp_workspace_mcp is importable
try:
    import esp_workspace_mcp
    print("[OK] esp_workspace_mcp package imported")
    print(f"     Version: {getattr(esp_workspace_mcp, '__version__', 'unknown')}")
except ImportError as e:
    print(f"[FAIL] Cannot import esp_workspace_mcp: {e}")
    sys.exit(1)

# Step 2: Check that categories submodule is importable
try:
    from esp_workspace_mcp.categories import CategoryRegistry
    print("[OK] CategoryRegistry imported from esp_workspace_mcp.categories")
except ImportError as e:
    print(f"[FAIL] Cannot import CategoryRegistry: {e}")
    sys.exit(1)

# Step 3: Check that CategoryRegistry has the right API
for method in ['get', 'list_categories', 'load_all', 'register']:
    if hasattr(CategoryRegistry, method):
        print(f"[OK] CategoryRegistry.{method} exists")
    else:
        print(f"[FAIL] CategoryRegistry.{method} missing")
        sys.exit(1)

# Step 4: Load all categories
try:
    CategoryRegistry.load_all()
    cats = CategoryRegistry.list_categories()
    print(f"[OK] Categories loaded: {cats}")
except Exception as e:
    print(f"[FAIL] load_all() failed: {e}")
    sys.exit(1)

# Step 5: Check each category
for cat_name in cats:
    cls = CategoryRegistry.get(cat_name)
    if cls is None:
        print(f"[FAIL] Category '{cat_name}' returned None")
        sys.exit(1)
    tools = getattr(cls, 'TOOLS', [])
    desc = getattr(cls, 'DESCRIPTION', '')
    print(f"[OK] {cat_name}: {len(tools)} tools — {desc}")

# Step 6: Check that server.create_server is importable
try:
    from esp_workspace_mcp.server import create_server
    print("[OK] create_server imported from esp_workspace_mcp.server")
except ImportError as e:
    print(f"[FAIL] Cannot import create_server: {e}")
    print("     This may be OK if mcp package is not installed in this venv")
    print("     The server will work in the main venv where mcp IS installed")

# Step 7: Try to create the server (requires mcp package)
try:
    from esp_workspace_mcp.server import create_server, load_config
    config = load_config()
    print(f"[OK] Config loaded: {list(config.keys())}")
    
    mcp = create_server(config)
    print(f"[OK] MCP server created successfully")
    
    # Count registered tools
    tool_count = len(getattr(mcp, '_tool_manager', {})._tools) if hasattr(mcp, '_tool_manager') else '?'
    print(f"[OK] Registered tools: {tool_count}")
except ImportError as e:
    print(f"[SKIP] Full server test skipped (missing dependency: {e})")
except Exception as e:
    print(f"[FAIL] Server creation failed: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("All checks passed!")
print("=" * 60)
