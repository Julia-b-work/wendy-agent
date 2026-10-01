# Wendy

A codebase Q&A agent built on Claude's tool-use API. Ask a question about a
project and it explores the code itself, listing files, searching, and reading,
then answers grounded in what it actually found, not what it guessed.

**Current version: 0.5.0** — see [CHANGELOG.md](docs/CHANGELOG.md).

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
- **Command-line interface** — ask questions directly: `wendy "question"`.
- **History-aware** — `git_log`, `git_blame`, `git_diff`, and `repo_map` answer
  the "why did this change?" questions that plain search can't.
- **Symbol-aware** — `list_symbols` and `find_definition` use tree-sitter to
  parse code into syntax trees, so "where is X defined?" returns the real
  definition, not a string match.
- **Semantic search** — `semantic_search` finds code by meaning: ask "where's
  the auth logic?" and it returns the matching functions even when those words
  never appear in the code, via a cached embedding index.
- **MCP server** — all ten tools are exposed as a Model Context Protocol
  server (`wendy-server`), so Claude Code and other MCP clients can use them.

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
wendy-server
```

Register it with Claude Code:

```bash
claude mcp add wendy -- /absolute/path/to/venv/bin/wendy-server
```

Or inspect it in a browser with the MCP Inspector:

```bash
.venv/bin/mcp dev wendy-server
```

![Claude Code invoking Wendy's git_blame tool](wendy-claude.gif)

## Tech stack

- **Python 3.10+**
- **anthropic** — Claude API client (tool use)
- **python-dotenv** — loads the API key from `.env`
- **mcp** — Model Context Protocol (the MCP server interface)
- **tree-sitter** + **tree-sitter-python** — symbol search (`list_symbols`, `find_definition`)
- **sentence-transformers** — optional, for `semantic_search` (see Setup)

## Project structure

```
.
├── src/
│   └── wendy/
│       ├── agent.py        # the agent: tool-use loop, CLI
│       ├── tools.py        # the tools + helpers (shared by agent and server)
│       ├── server.py       # MCP server exposing the tools to MCP clients
│       └── verify.py       # claim verification
├── tests/
│   ├── test_agent.py       # unit tests
│   └── test_verify.py      # verify tests
├── docs/
│   └── CHANGELOG.md
├── pyproject.toml          # packaging (hatchling) + dependencies
├── Dockerfile              # container build for the MCP server
├── LICENSE
├── demo.tape               # VHS source for the CLI demo
├── wendy-claude.gif        # demo: Claude Code invoking the MCP server
├── .env                    # Anthropic API key (gitignored)
└── .gitignore
```

## Setup

1. Create a virtualenv and install the package in editable mode:
   ```bash
   python -m venv .venv
   .venv/bin/pip install -e .
   ```
   To use `semantic_search`, install the extra instead (it pulls in torch):
   ```bash
   .venv/bin/pip install -e ".[semantic]"
   ```
2. Create a `.env` file (never commit it):
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
3. Run:
   ```bash
   wendy "what does run_agent do?"
   ```

## Tests

```bash
python -m unittest discover -s tests
```

CI runs the tests on Python 3.10, 3.12, and 3.13 on every push and pull request.

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
- [x] Git history tools (`git_log`, `git_blame`, `git_diff`, `repo_map`)
- [x] Symbol search (`list_symbols`, `find_definition` via tree-sitter)
- [x] Semantic search (`semantic_search` via embeddings + cached index)
- [x] Packaging (`pyproject.toml`, `wendy` and `wendy-server` entry points)
- [x] CI (tests on Python 3.10, 3.12, 3.13)
