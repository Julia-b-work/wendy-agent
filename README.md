# Wendy

A codebase Q&A agent built on Claude's tool-use API. Ask a question about a
project and it explores the code itself — listing files, searching, and reading
— then answers grounded in what it actually found, not what it guessed.

**Current version: 0.3.0** — see [CHANGELOG.md](CHANGELOG.md).

## What it does

- **Autonomous exploration** — given a question, decides which tool it needs and
  runs it, chaining multiple tools until it has enough real information.
- **Three tools** — `list_files` (walk a directory), `read_file` (read a file),
  and `search` (find a string across the whole project with line numbers).
- **Visible reasoning** — prints every step of the loop, so you can watch it
  think instead of trusting a black box.
- **Bounded loop** — after 10 tool-using turns, the agent pauses to ask you to
  continue and prompts Claude to justify itself before going on.
- **Robust** — a crashing tool can't kill the run, results are truncated to a
  sane size, binary files and junk directories are filtered out, and API errors
  are retried with backoff and reported cleanly.
- **Command-line interface** — ask questions directly: `agent.py "question"`.
- **MCP server** — the same tools are exposed as a Model Context Protocol
  server (`server.py`), so Claude Code and other MCP clients can use them.

## How it works

Wendy runs a **tool-use loop**, the same pattern behind coding agents like
Claude Code:

1. Send your question to Claude, along with the list of available tools.
2. Claude either answers, or replies with a *tool request* (e.g. "run `search`
   for `def run`").
3. Wendy executes the tool and feeds the result back into the conversation.
4. Repeat until Claude answers in plain text with no further tool requests.

The conversation history (the `messages` list) grows each iteration, so Claude
remembers everything it has already found.

To avoid runaway loops, after `STEP_LIMIT` (10) tool-using turns the agent
pauses and asks you whether to continue, and asks Claude to justify itself.

## MCP server

Wendy's tools are also available as a [Model Context Protocol](https://modelcontextprotocol.io) server:

```bash
.venv/bin/python server.py
```

Register it with Claude Code:

```bash
claude mcp add wendy -- .venv/bin/python server.py
```

Or inspect it in a browser with the MCP Inspector:

```bash
.venv/bin/mcp dev server.py
```

## Tech stack

- **Python 3**
- **anthropic** — Claude API client (tool use)
- **python-dotenv** — loads the API key from `.env`
- **mcp** — Model Context Protocol (the `server.py` interface)

## Project structure

```
.
├── agent.py           # the agent: tool-use loop, CLI
├── tools.py           # the three tools + helpers (shared by agent and server)
├── server.py          # MCP server exposing the tools to MCP clients
├── test_agent.py      # unit tests (run: python -m unittest test_agent)
├── requirements.txt   # Python dependencies
├── .env               # Anthropic API key (gitignored)
└── .gitignore
```

## Setup

1. Create a virtualenv and install dependencies:
   ```bash
   python -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
2. Create a `.env` file (never commit it):
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
3. Run:
   ```bash
   .venv/bin/python agent.py "what does run_agent do?"
   ```

## Status

- [x] Tool-use loop
- [x] Three tools (`list_files`, `read_file`, `search`)
- [x] CLI with step visibility
- [x] Step limit (nudge + human-in-the-loop gate)
- [x] Tool crash safety
- [x] Truncation
- [x] Noise filtering
- [x] API error handling (retry + clean messages)
- [x] MCP server (tools exposed to MCP clients)
