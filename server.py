"""Wendy's tools exposed as a Model Context Protocol (MCP) server.

Each @mcp.tool() wrapper turns a tools.py function into an MCP tool: the
docstring becomes the tool description the model reads, and the type hints
become the input schema.
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP
import tools

mcp = FastMCP("wendy")

@mcp.tool()
def list_files(directory: str) -> str:
    """List files in a directory, skipping hidden and junk directories."""
    return tools.list_files(directory)

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file, truncated if its too large."""
    return tools.read_file(path)

@mcp.tool()
def search(query: str, root: str = ".") -> str:
    """Search all files for a string, returning matching files paths and line numbers."""
    return tools.search(query, root)

@mcp.tool()
def repo_map(root: str = ".") -> str:
    """Show a tree-style map of the project's directories and files."""
    return tools.repo_map(root)

@mcp.tool()
def git_log(n: int = 20, path: Optional[str] = None) -> str:
    """Show the most recent git commits, optionally limited to one file."""
    return tools.git_log(n, path)

@mcp.tool()
def git_blame(path: str) -> str:
    """Show who last changed each line of a file, with commit hashes."""
    return tools.git_blame(path)

@mcp.tool()
def git_diff(path: Optional[str] = None) -> str:
    """Show uncommitted changes, optionally limited to one file."""
    return tools.git_diff(path)

if __name__ == "__main__":
    mcp.run()
