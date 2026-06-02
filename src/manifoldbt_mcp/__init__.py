"""Model Context Protocol (MCP) server for manifoldbt.

Exposes the `manifoldbt <https://github.com/Jimmy7892/manifoldbt>`_
backtesting engine to MCP-compatible clients (Claude Desktop, Cursor,
Devin, VS Code, Windsurf, etc.) as tools, resources, and prompts.

Usage::

    pip install manifoldbt-mcp
    manifoldbt-mcp              # stdio transport (default)
    manifoldbt-mcp --http       # streamable-http transport on :8765
"""
from importlib.metadata import PackageNotFoundError, version

from manifoldbt_mcp.server import build_server, main

try:
    __version__ = version("manifoldbt-mcp")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["__version__", "build_server", "main"]
