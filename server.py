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

if __name__ == "__main__":
    mcp.run()
