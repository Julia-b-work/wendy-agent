"""Filesystem and git tools shared by the CLI agent and the MCP server.

Every function returns a string and never raises, so a tool failure becomes a
message rather than a crash. This is the module the MCP server imports to expose
Wendy's capabilities to other clients.
"""

import os
import subprocess

# Result strings are capped so a huge file or listing can't blow up the context
# window sent to the model.
MAX_RESULT_CHARS = 16000

# Directories that are noise when exploring a codebase.
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "target",
}


def truncate(text, limit=MAX_RESULT_CHARS):
    """Truncate text to `limit` characters, appending a visible marker."""
    if len(text) <= limit:
        return text
    # The marker matters: it tells the model the content was cut off, so it
    # won't confidently answer about parts it never saw.
    return text[:limit] + "\n...[truncated]"


def is_binary(path):
    """Return True if the file looks binary (a null byte in its first KB)."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(1024)
    except OSError:
        return True


def skip_dir(name):
    """Return True for hidden directories or known junk directories."""
    return name.startswith(".") or name in IGNORED_DIRS


def list_files(directory):
    """List text files under `directory`, skipping hidden/junk dirs and binaries."""
    out = []
    for root, dirs, files in os.walk(directory):
        # Mutating dirs in place prunes the walk so we never descend into them.
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        for f in files:
            path = os.path.join(root, f)
            if is_binary(path):
                continue
            out.append(path)
    return truncate("\n".join(sorted(out)[:100]))


def read_file(path):
    """Read a file's contents, truncated if large."""
    try:
        with open(path, "r") as f:
            return truncate(f.read())
    except FileNotFoundError:
        return f"File not found: {path}"


def search(query, root="."):
    """Search text files for `query`, returning `path:line: content` matches."""
    out = []
    for root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        for f in files:
            path = os.path.join(root, f)
            if is_binary(path):
                continue
            try:
                with open(path, "r") as fh:
                    for i, line in enumerate(fh, 1):
                        if query in line:
                            out.append(f"{path}:{i}: {line.strip()}")
            except (UnicodeDecodeError, IsADirectoryError):
                continue
    return truncate("\n".join(out[:100]))


def _run_git(args):
    """Run a git command safely; return stdout, or an error string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,  # a hung git command must not hang the server
        )
        if result.returncode != 0:
            # Turn a failed git call into a message rather than a crash.
            return f"git error: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        return "git not found"
    except subprocess.TimeoutExpired:
        return "git timed out"


def repo_map(root="."):
    """Return a tree-style map of the project's directories and files."""
    lines = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not skip_dir(d))
        # Depth is the number of path separators below the root, used for indent.
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        indent = "  " * depth
        name = os.path.basename(dirpath) or root
        lines.append(f"{indent}{name}/")
        for f in sorted(files):
            if not is_binary(os.path.join(dirpath, f)):
                lines.append(f"{indent}  {f}")
    return truncate("\n".join(lines))


def git_log(n=20, path=None):
    """Return the most recent `n` commits, optionally limited to one file."""
    args = ["log", "--oneline", f"-{n}"]
    if path:
        args += ["--", path]
    return truncate(_run_git(args) or "(no commits)")


def git_blame(path):
    """Return who last changed each line of `path`, with commit hashes."""
    return truncate(_run_git(["blame", path]) or f"no blame info for {path}")


def git_diff(path=None):
    """Return uncommitted changes, optionally limited to one file."""
    args = ["diff"]
    if path:
        args += ["--", path]
    return truncate(_run_git(args) or "(no uncommitted changes)")
