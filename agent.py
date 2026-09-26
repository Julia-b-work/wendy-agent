import sys
import time
import anthropic
from dotenv import load_dotenv
from tools import list_files, read_file, search

STEP_LIMIT = 10
MAX_RETRIES = 3
RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)


NUDGE_MESSAGE = (
    "You have used tools {n} times without giving a final answer. "
    "Briefly explain why you still need more tools. If you don't have a "
    "strong reason, answer the question now using what you've already found."
)


load_dotenv()

_client = None

def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


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

def run_tool(name, tool_input):
    try:
        if name == "list_files":
            return list_files(tool_input["directory"])
        if name == "read_file":
            return read_file(tool_input["path"])
        if name == "search":
            return search(tool_input["query"])
        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"tool {name} crashed {type(exc).__name__}: {exc}"



def _create(client, messages):
    system = (
        "You are a coding assistant exploring a codebase. "
        "Always use your tools to gather real information before answering — "
        "never guess or tell the user to do it manually."
    )
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            return client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1000,
                system=system,
                tools=tools,
                messages=messages,
            )
        except RETRYABLE_ERRORS:
            if attempt == MAX_RETRIES - 1:
                raise
            print(f" -> retrying (attempt {attempt + 1})...")
            time.sleep(delay)
            delay *= 2

def run_agent(question, max_steps=None, client=None):
    if client is None:
        client = get_client()

    messages = [{"role": "user", "content": question}]

    step = 0
    next_checkpoint = STEP_LIMIT
    nudged = False
    while max_steps is None or step < max_steps:
        step += 1
        if step == STEP_LIMIT + 1 and not nudged:
            nudged = True
            messages.append({"role": "user", "content": NUDGE_MESSAGE.format(n=STEP_LIMIT)})

        print(f"\n[step {step}] asking Claude...")
        try:
            response = _create(client, messages)
        except anthropic.AuthenticationError as exc:
            return f"Authentication error: {exc}"
        except RETRYABLE_ERRORS as exc:
            return f"API error after retries: {exc}"
        except anthropic.APIError as exc:
            return f"API error: {exc}"
        except Exception as exc:
            return f"Unexpected error: {type(exc).__name__}: {exc}"

        messages.append({"role": "assistant", "content": response.content})

        for b in response.content:
            if b.type == "text":
                print(f"  [justification] {b.text}")

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            print(f"[step {step}] Claude answered (no more tools).")
            return "".join(b.text for b in response.content if b.type == "text")

        if step >= next_checkpoint:  # human gate
            choice = input(
                f"\nClaude has used tools {step} times and still wants more. Continue? [y/N] "
            ).strip().lower()
            if choice != "y":
                return f"Stopped by user after {step} steps."
            next_checkpoint += STEP_LIMIT

        tool_results = []
        for block in tool_uses:
            print(f" -> {block.name}({block.input})")
            result = run_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

    return f"Stopped after {max_steps} steps without a final answer."


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"your question here\"")
    else:
        print(run_agent(sys.argv[1]))
