"""Filesystem and git tools shared by the CLI agent and the MCP server.

Every function returns a string and never raises, so a tool failure becomes a
message rather than a crash. This is the module the MCP server imports to expose
Wendy's capabilities to other clients.
"""

import json
import os
import subprocess

import numpy as np
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

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


# Map file extension -> tree-sitter language.
_LANGUAGES = {
    ".py": Language(tspython.language()),
}

# Node types that count as "definitions", per language.
_DEFINITION_TYPES = {
    ".py": ("function_definition", "class_definition"),
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


def _language_for(path):
    """Return the tree-sitter Language for a file, or None if unsupported."""
    return _LANGUAGES.get(os.path.splitext(path)[1].lower())


def _symbols_in_file(path):
    """Return [(name, line, kind), ...] for function/class definitions."""
    lang = _language_for(path)
    if lang is None:
        return []
    try:
        with open(path, "rb") as f:
            src = f.read()
    except OSError:
        return []
    tree = Parser(lang).parse(src)
    types = _DEFINITION_TYPES[os.path.splitext(path)[1].lower()]
    out = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in types:
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "?"
            out.append((name, node.start_point[0] + 1, node.type))
        stack.extend(node.children)
    return out


def list_symbols(path):
    """List the functions and classes defined in a file, in file order."""
    symbols = sorted(_symbols_in_file(path), key=lambda s: s[1])
    if not symbols:
        return f"No symbols found in {path}"
    return truncate("\n".join(f"{line:5}  {kind:20}  {name}" for name, line, kind in symbols))


def find_definition(name, root="."):
    """Find where `name` is defined across the project."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        for f in files:
            path = os.path.join(dirpath, f)
            if is_binary(path) or _language_for(path) is None:
                continue
            for sym_name, line, kind in _symbols_in_file(path):
                if sym_name == name:
                    out.append(f"{path}:{line}: {kind} {name}")
    if not out:
        return f"No definition found for {name}"
    return truncate("\n".join(out))


_model = None


def _get_model():
    """Return the sentence-transformers model, loaded lazily (it's heavy)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "semantic_search requires 'sentence-transformers' "
                "(pip install sentence-transformers)"
            )
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _symbol_chunks(path):
    """Yield (name, line, source_text) for each function/class in a file."""
    lang = _language_for(path)
    if lang is None:
        return
    try:
        with open(path, "rb") as f:
            src = f.read()
    except OSError:
        return
    tree = Parser(lang).parse(src)
    types = _DEFINITION_TYPES[os.path.splitext(path)[1].lower()]
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in types:
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "?"
            text = src[node.start_byte:node.end_byte].decode(errors="ignore")
            yield name, node.start_point[0] + 1, text[:2000]
        stack.extend(node.children)


def _collect_chunks(root):
    """Return [(path, line, name, text), ...] for all symbols under root."""
    chunks = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        for f in files:
            path = os.path.join(dirpath, f)
            if is_binary(path) or _language_for(path) is None:
                continue
            for name, line, text in _symbol_chunks(path):
                chunks.append((path, line, name, text))
    return chunks


def _index_paths(root):
    """Return the (vectors, metadata) cache paths for a project root."""
    base = os.path.join(root, ".wendy_index")
    return base + ".npy", base + ".json"


def _build_index(root):
    """Embed every symbol once and cache the vectors to disk."""
    chunks = _collect_chunks(root)
    if not chunks:
        return
    vecs = np.asarray(_get_model().encode([c[3] for c in chunks]))
    vecs_path, meta_path = _index_paths(root)
    np.save(vecs_path, vecs)
    meta = [
        {"path": c[0], "line": c[1], "name": c[2], "mtime": os.path.getmtime(c[0])}
        for c in chunks
    ]
    with open(meta_path, "w") as f:
        json.dump(meta, f)


def _index_is_stale(root):
    """Return True if the index is missing or a file changed since it was built."""
    vecs_path, meta_path = _index_paths(root)
    if not (os.path.exists(vecs_path) and os.path.exists(meta_path)):
        return True
    with open(meta_path) as f:
        meta = json.load(f)
    for m in meta:
        if not os.path.exists(m["path"]) or os.path.getmtime(m["path"]) != m["mtime"]:
            return True
    return False


def semantic_search(query, root=".", top_k=5):
    """Return the functions/classes most semantically similar to `query`."""
    if _index_is_stale(root):
        _build_index(root)
    vecs_path, meta_path = _index_paths(root)
    if not (os.path.exists(vecs_path) and os.path.exists(meta_path)):
        return "(no code to search)"
    vecs = np.load(vecs_path)
    with open(meta_path) as f:
        meta = json.load(f)
    q = np.asarray(_get_model().encode([query])).reshape(-1)
    sims = vecs @ q / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(q) + 1e-9)
    idx = np.argsort(sims)[::-1][:top_k]
    out = [
        f"{sims[i]:.3f}  {meta[i]['path']}:{meta[i]['line']}: {meta[i]['name']}"
        for i in idx
    ]
    return truncate("\n".join(out))
