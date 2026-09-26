import os

MAX_RESULT_CHARS = 8000
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
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"

def is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(1024)
    except OSError:
        return True

def skip_dir(name):
    return name.startswith(".") or name in IGNORED_DIRS



def list_files(directory):
    out = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        for f in files:
            path = os.path.join(root, f)
            if is_binary(path):
                continue
            out.append(path)
    return truncate("\n".join(sorted(out)[:100]))


def read_file(path):
    try:
        with open(path, "r") as f:
            return truncate(f.read())
    except FileNotFoundError:
        return f"File not found: {path}"


def search(query, root="."):
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
