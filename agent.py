import os
import sys
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

tools = [
    {
        "name": "list_files",
        "description": "List the files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path to list, e.g. 'src' or '.'",
                }
            },
            "required": ["directory"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read, e.g. 'src/main.py'",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "search",
        "description": "Search all files for a string and return matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The text to search for, e.g. 'def main' or 'TODO'",
                }
            },
            "required": ["query"],
        },
    },
]


def list_files(directory):
    out = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            out.append(os.path.join(root, f))
    return "\n".join(sorted(out)[:100])


def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"File not found: {path}"


def search(query):
    out = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            path = os.path.join(root, f)
            try:
                with open(path, "r") as fh:
                    for i, line in enumerate(fh, 1):
                        if query in line:
                            out.append(f"{path}:{i}: {line.strip()}")
            except (UnicodeDecodeError, IsADirectoryError):
                continue
    return "\n".join(out[:100])


def run_agent(question):
    messages = [{"role": "user", "content": question}]

    step = 0
    while True:
        step += 1
        print(f"\n[step {step}] asking Claude...")
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=(
                "You are a coding assistant exploring a codebase. "
                "Always use your tools to gather real information before answering — "
                "never guess or tell the user to do it manually."
            ),
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            print(f"[step {step}] Claude answered (no more tools).")
            return "".join(b.text for b in response.content if b.type == "text")

        tool_results = []
        for block in tool_uses:
            print(f"  -> {block.name}({block.input})")
            if block.name == "list_files":
                result = list_files(block.input["directory"])
            elif block.name == "read_file":
                result = read_file(block.input["path"])
            elif block.name == "search":
                result = search(block.input["query"])
            else:
                result = "unknown tool"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"your question here\"")
    else:
        print(run_agent(sys.argv[1]))
