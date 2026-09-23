# Wendy

A codebase Q&A agent built on Claude's tool-use API. Ask a question about a
project and it explores the code itself — listing files, searching, and reading
— then answers grounded in what it actually found, not what it guessed.

**Current version: 0.1.2** — see [CHANGELOG.md](CHANGELOG.md).

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
  sane size, and binary files and junk directories are filtered out.
- **Command-line interface** — ask questions directly: `agent.py "question"`.

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

## Tech stack

- **Python 3**
- **anthropic** — Claude API client (tool use)
- **python-dotenv** — loads the API key from `.env`

## Project structure

```
.
├── agent.py           # the entire agent: tools, tool-use loop, CLI
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
- [ ] API error handling (retry + clean messages)
