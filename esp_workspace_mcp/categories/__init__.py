"""
Category-based tool registration system for esp-workspace MCP server.

Each category is a self-contained module that registers a group of related tools
with the FastMCP instance. Categories can be enabled/disabled via configuration.

Usage in server.py:
    from esp_workspace_mcp.categories import CategoryRegistry
    
    enabled = config.get("categories", {}).get("enabled", [])
    if enabled:
        for name in enabled:
            CategoryRegistry.get(name).register(mcp, config)
    else:
        # Legacy: load all
        CategoryRegistry.load_all()
        for name in CategoryRegistry.list_categories():
            CategoryRegistry.get(name).register(mcp, config)
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Registry of all known category modules
# Each entry: "category_name" -> "module.path.ClassName"
_REGISTRY: dict[str, str] = {}


def register(name: str, module_path: str, class_name: str = "Category"):
    """Register a category. Called by each category module's __init__."""
    _REGISTRY[name] = f"{module_path}:{class_name}"


def get(name: str):
    """Get a category class by name."""
    if name not in _REGISTRY:
        return None
    module_path, class_name = _REGISTRY[name].rsplit(":", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def list_categories() -> list[str]:
    """List all registered category names."""
    return list(_REGISTRY.keys())


def load_all():
    """Import all category modules to trigger their registration."""
    for name in ("filesystem", "shell", "git", "search", "serial",
                 "diagnostics", "sessions", "esp_idf", "build_diagnostics",
                 "ai_native", "openmv"):
        try:
            importlib.import_module(f"esp_workspace_mcp.categories.{name}")
        except ImportError:
            pass  # Category not yet implemented


class CategoryRegistry:
    """Registry of tool categories. Provides a clean API for server.py.

    Usage:
        from esp_workspace_mcp.categories import CategoryRegistry
        CategoryRegistry.load_all()
        cls = CategoryRegistry.get("filesystem")
        if cls:
            cls.register(mcp, config)
    """

    @staticmethod
    def register(name: str, module_path: str, class_name: str = "Category"):
        register(name, module_path, class_name)

    @staticmethod
    def get(name: str):
        return get(name)

    @staticmethod
    def list_categories() -> list[str]:
        return list_categories()

    @staticmethod
    def load_all():
        load_all()
